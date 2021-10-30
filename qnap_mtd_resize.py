#!/usr/bin/env python3

"""
    SPDX-License-Identifier: GPL-2.0  

    Copyright 2021 Arnaud Mouiche
    
    
        
    This tool resize the MTD partitions of supported QNAP device
    in order to maximize the kernel and rootfs (ie. initrd) partitions.
    This done by:
    - adding 'mtdparts=....' on linux kernel cmdline to override 
      mtd partitions from the DTB file and use the new layout.
    - patch the uboot configuration to load kernel and initrd from 
      the new partitions
    - resize the 'NAS Config FS and partition' (ext2 fs containing some informations
      about the QNAP device)
    - move the "Kernel" partitions to there final partitions 
      (available on next reboot)
   
    
    
    While the legacy MTD partition is:
    
                           offset     size
        uboot          0x00000000 0x00080000  512KiB  /dev/mtd0
        U-Boot Config  0x00080000 0x00040000  256KiB  /dev/mtd4
        NAS Config     0x000c0000 0x00140000  1280KiB /dev/mtd5
        Kernel         0x00200000 0x00200000  2MiB    /dev/mtd1
        RootFS1        0x00400000 0x00900000  9MiB    /dev/mtd2
        RootFS2        0x00d00000 0x00300000  3MiB    /dev/mtd3
    
    The new mapping will be:
    
                            offset     size
        uboot          0x00000000 0x00080000  512KiB  /dev/mtd0
        U-Boot Config  0x00080000 0x00040000  256KiB  /dev/mtd4
        NAS Config     0x000c0000 0x00040000  256KiB  /dev/mtd5
        Kernel         0x00100000 0x00300000  3MiB    /dev/mtd1
        RootFS1        0x00400000 0x00c00000  12MiB   /dev/mtd2
        Kernel_legacy  0x00200000 0x00200000  2MiB    /dev/mtd3  (legacy Kernel range, overlap with new Kernel)


    Example for TS-219P
        U-boot legacy env
        
           bootcmd=uart1 0x68;cp.l 0xf8200000 0x800000 0x80000;cp.l 0xf8400000 0xa00000 0x240000;bootm 0x800000
           
           boorargs=console=ttyS0,115200 root=/dev/ram initrd=0xa00000,0x900000 ramdisk=32768
           
        New U-boot env
           bootcmd=uart1 0x68;cp.l 0xf8100000 0x800000 0xc0000;cp.l 0xf8400000 0xb00000 0x300000;bootm 0x800000
           
           boorargs=console=ttyS0,115200 root=/dev/ram initrd=0xb00000,0xc00000 ramdisk=32768 \ 
                    cmdlinepart.mtdparts="spi0.0:512k@0(uboot)ro,3M@0x100000(Kernel),\
                    12M@0x400000(RootFS1),2M@0x200000(Kernel_legacy),256k@0x80000(U-Boot Config),\
                    256k@0xc0000(NAS Config)"
    
     

    
"""


import subprocess
import os
import argparse
import logging
import re
import sys


# list here the model of tested QNAP device by listing the
# DTB files returned by /usr/share/flash-kernel/dtb-probe/kirkwood-qnap
TESTED_QNAP_DTB = [
    "kirkwood-ts219-6281.dtb",
    "kirkwood-ts419-6282.dtb",
    ]


def mtd_lookup(name):
    """
        For a given MTD partition name, return a tuple
        ("mtdX", size, erasesize)
        Raise a KeyError exception if not found.
    """
    for line in open("/proc/mtd").readlines():
        m = re.match(r'(mtd[0-9]+): ([0-9a-f]+) ([0-9a-f]+) "(.+)"', line.strip())
        if not m:
            continue
        if m.group(4) == name:
            return (m.group(1), int(m.group(2), 16), int(m.group(3), 16))
    raise KeyError(f"No mtd '{name}' device found.")
    

def str_replace(search, replace, text):
    """
        Search for 'search' pattern in 'text' and replace by 'replace'
        Raise a KeyError if 'search' is not found.
    """
    result = re.sub(search, replace, text)
    if result == text:
        raise KeyError(f"'{search}' not found in '{text}'")
    return result
        
        


parser = argparse.ArgumentParser(
        description='Tool to resize QNAP mtd partitions in order to increase the kernel and rootfs size'
        )

parser.add_argument("--loop", metavar="DEV", default="/dev/loop0", help="/dev/loopX device to use for 'NAS config' FS resize (default: /dev/loop0)")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()



###################################################################
print("\n[Check of the QNAP model and see if supported]")  
try:
    dtb_file = subprocess.check_output(["/usr/share/flash-kernel/dtb-probe/kirkwood-qnap"]).strip().decode()
except FileNotFoundError:
    print("'flash-kernel' package is not installed. Are you really running this script from a QNAP ?")
    exit(1)
except subprocess.CalledProcessError:
    print("You are not running this script from a supported QNAP device.")
    exit(1)
    
# check if dtb_file is none
print("DTB file:", dtb_file)

if dtb_file not in TESTED_QNAP_DTB:
    print("Partition resize was not tested on this device yet. Do you want to continue ? (y/N)")
    resp = sys.stdin.readline()
    if resp.strip().upper() != 'Y':
        print("Abort.")
        exit(1)

    print("In case of success, please report the DTB file indication.")
    print("\n"*3)


    
# check if the MTD kernel and rootfs1 are not already resized
mtd_kernel, size, _ = mtd_lookup("Kernel")
if size != 0x200000:
    print("Kernel has already been resized. Can't process further safely.")
    exit(1)
    
mtd_rootfs1, size, _ = mtd_lookup("RootFS1")
if size != 0x900000:
    print("RootFS1 has already been resized. Can't process further safely.")
    exit(1)
 
 
mtd_nas_config, size, _ = mtd_lookup("NAS Config")
if size != 0x00140000:
    print("'NAS config' has already been resized. Can't process further safely.")
    exit(1)
    
mtd_uboot_config, _, _ = mtd_lookup("U-Boot Config")


    
# early check of required tools to see if we have all of them
for tool_cmd in [
        "/sbin/flashcp -V", 
        "/sbin/flash_erase --version", 
        "/usr/bin/fw_setenv --version",
        "/usr/bin/fw_printenv --version",
        ]:
    print("Checking:", tool_cmd)
    try:
        subprocess.check_output(tool_cmd, shell=True)
    except:
        print("Failed. Please see manually if correctly installed")
        exit(1)
        
    
# root ?
if os.getuid() != 0:
    print("You must be root.")
    exit(1)
    
    
    
###################################################################
print("\n[find on which MTD device partitions are currently mounted]")  
mtd_master = None
for line in subprocess.check_output(["/usr/bin/dmesg"]).split(b"\n"):
    line = line.decode(errors="ignore")
    m = re.search(r'Creating [0-9]+ MTD partitions on "([^"]+)"', line)
    if m:
        mtd_master = m.group(1)
    
if not mtd_master:
    print("Failed: no information found with dmesg")
    exit(1)
else:
    print("  ", mtd_master)
    
    
    
###################################################################
print("\n[Dump current U-boot config']")

with open("/tmp/fw_env.config", "w") as F:
    F.write(f"""# MTD device name       Device offset   Env. size       Flash sector size       Number of sectors
/dev/{mtd_uboot_config}                 0x0000          0x1000           0x40000                 1
""")

uboot_env = {}
for line in subprocess.check_output(["/usr/bin/fw_printenv", "-c", "/tmp/fw_env.config"]).decode().split("\n"):
    line = line.strip()
    m = re.match(r"([a-zA-Z_0-9]+)=(.*)", line)
    if m:
        uboot_env[m.group(1)] = m.group(2)
try:
    bootcmd = uboot_env["bootcmd"]
    bootargs = uboot_env["bootargs"]
except KeyError:
    print("Missing 'bootcmd' or 'bootargs' in U-Boot Config")
    exit(1)
    
print("Current U-boot bootcmd:\n   ", bootcmd)
print("Current U-boot bootargs:\n   ", bootargs)

# detect the MTD device name
# Creating 6 MTD partitions on "spi0.0"


NEW_MTDPARTS=f"{mtd_master}:512k@0(uboot)ro,3M@0x100000(Kernel),12M@0x400000(RootFS1),2M@0x200000(Kernel_legacy),256k@0x80000(U-Boot Config),256k@0xc0000(NAS Config)"

    
    
   
   
###################################################################
print("\n[Prepare new 'bootcmd']")
try:
    bootcmd_new = str_replace("cp.l 0xf8200000 0x800000 0x0*80000",
                              "cp.l 0xf8100000 0x800000 0xc0000", bootcmd)
    bootcmd_new = str_replace("cp.l 0xf8400000 0xa00000 0x240000", 
                              "cp.l 0xf8400000 0xb00000 0x300000", bootcmd_new)
except KeyError as e:
    print(str(e))
    print("Don't know how to patch 'bootcmd' for this model. Please report this log.")
    exit(1)
    
print("   Old:", bootcmd)
print("   New:", bootcmd_new)


###################################################################
print("\n[Prepare new 'bootargs']")
try:
    bootargs_new = str_replace("initrd=0xa00000,0x900000", 
                              "initrd=0xb00000,0xc00000", bootargs)
                              
    # setup cmdlinepart.mtdparts=... to set the partitions for cases where 'cmdlinepart' is build as external module 
    # (which is the current Debian behavior)
    bootargs_new = bootargs_new + f' cmdlinepart.mtdparts="{NEW_MTDPARTS}"'
    
    # also add mtdparts=... if for some reasons in future, Debian will switch to internal module or if users are
    # building their own kernel with such configuration
    bootargs_new = bootargs_new + f' mtdparts="{NEW_MTDPARTS}"'

except KeyError as e:
    print(str(e))
    print("Don't know how to patch 'bootargs' for this model. Please report this log.")
    exit(1)
    
print("   Old:", bootargs)
print("   New:", bootargs_new)




###################################################################
print("\n[Prepare fw_setenv script (/tmp/fw_setenv.script)]")

# the (undocumented) syntax with '=' is supported by fw_setenv
# on both Buster (u-boot-tools) and Bullseye (libubootenv-tool),
# whereas the syntax without '=' is not supported in Bullseye
# and produces undesired effects (ie. non-bootable systems)
script=f"""
bootargs_backup={bootargs}
bootcmd_backup={bootcmd}
bootargs={bootargs_new}
bootcmd={bootcmd_new}
"""
with open("/tmp/fw_setenv.script", "w") as F:
    F.write(script)
    

print("\n[Dump current 'NAS config' and 'Kernel' images]")
cmd = f"""
    set -e
    set -x
    cat /dev/{mtd_nas_config} > /tmp/mtd_nas_config.dump
    """
    
subprocess.check_call(cmd, shell=True)
    

    
###################################################################
print("[Resize 'NAS config' dump from 1280KB to 256KB.]")

cmd = f"""
    set -e
    set -x
    /usr/sbin/modprobe loop
    
    /usr/sbin/losetup {args.loop} /tmp/mtd_nas_config.dump
    
    # run e2fsck twice. the First may return an error status even if FS is corrected
    /usr/sbin/e2fsck -f -p -v {args.loop} || true
    if ! /usr/sbin/e2fsck -f -p -v {args.loop}; then
        echo "e2fsck failed. 'NAS config' resize not possible automatically"
        /usr/sbin/losetup -d {args.loop}
        exit 1
    fi
    
    if ! /usr/sbin/resize2fs {args.loop} 128; then
        echo "resize2fs failed. 'NAS config' resize not possible automatically"
        /usr/sbin/losetup -d {args.loop}
        exit 1
    fi
    /usr/sbin/losetup -d {args.loop}
    """
    
subprocess.check_call(cmd, shell=True)


###################################################################
print("\n[Concatenate first 256K of 'NAS config' with first 1MB of Kernel > /tmp/mtd_nas_config.new]")
with open("/tmp/mtd_nas_config.new", "wb") as new_F:
    with open("/tmp/mtd_nas_config.dump", "rb") as F:
        new_F.write(F.read(256*1024))
    with open(f"/dev/{mtd_kernel}", "rb") as F:
        new_F.write(F.read(1024*1024))
    

print("\n[Prepare second 1MB of kernel tail > /tmp/mtd_kernel.tail]")
with open("/tmp/mtd_kernel.tail", "wb") as new_F:
    with open(f"/dev/{mtd_kernel}", "rb") as F:
        F.seek(1024*1024)
        new_F.write(F.read(1024*1024))



print("-"*60)
print("""    !!!! Warning !!!!

    Everything is fine up to now.
    Next steps will write the flash and may be subject to failures.
    
    It is highly recommended to perform a MTD backup and save the files
    somewhere (USB device, PC)
    
        cat /dev/mtd0 > /tmp/mtd0.uboot.backup
        cat /dev/mtd1 > /tmp/mtd1.kernel.backup
        cat /dev/mtd2 > /tmp/mtd2.rootfs1.backup
        cat /dev/mtd3 > /tmp/mtd3.rootfs2.backup
        cat /dev/mtd4 > /tmp/mtd4.uboot-config.backup
        cat /dev/mtd5 > /tmp/mtd5.nas-config.backup
        /usr/bin/fw_printenv -c /tmp/fw_env.config  > /tmp/uboot_config.backup.txt
        cd /tmp
        tar cvzf mtd_backup.tgz mtd?.*.backup uboot_config.backup.txt
        
        # now use scp / sftp to push/pull mtd_backup.tgz on another PC.
    
    Be sure you will not cut the power until the end of operations.
    In case of failure, you way need to recover with a Serial Console 
    to run U-boot commands
    
        https://www.cyrius.com/debian/kirkwood/qnap/ts-219/serial/
    
Continue and flash the new partitions ? (y/N)""")
if args.dry_run:
    print("Note: You are using --dry-run option. No flash operations will be performed if you answer 'y'.")

resp = sys.stdin.readline()
if resp.strip().upper() != 'Y':
    print("Abort.")
    exit(1)


###################################################################
print("\n[Flash 'NAS config' partition content (ie 'NAS config' + head of Kernel) (still a 'safe' op)]")
cmd = f"""/sbin/flashcp -v /tmp/mtd_nas_config.new /dev/{mtd_nas_config}"""
if not args.dry_run:
    print("+", cmd)
    subprocess.check_call(cmd, shell=True)
else:
    print("(Dry run)")
    print("+", cmd)
    
   
    
###################################################################
print("\n[Change U-boot config with new values)]")
cmd = f"""/usr/bin/fw_setenv -c /tmp/fw_env.config -s /tmp/fw_setenv.script"""
if not args.dry_run:
    print("+", cmd)
    subprocess.check_call(cmd, shell=True)
else:
    print("(Dry run)")
    print("+", cmd)



###################################################################
print("\n[Flash tail of the kernel in old 'Kernel' Partition]")
cmd = f"""/sbin/flashcp -v /tmp/mtd_kernel.tail /dev/{mtd_kernel}"""
if not args.dry_run:
    print("+", cmd)
    subprocess.check_call(cmd, shell=True)
else:
    print("(Dry run)")
    print("+", cmd)


###################################################################
print("-"*60)
print("""
    SUCCESS. You can reboot now.
    
    Notes: 
    - Don't perform kernel or system update before the next reboot... 
      so don't wait too long.
    - Consider compressing initrd with 'xz' to optimize the size with:
    
        echo "COMPRESS=xz" > /etc/initramfs-tools/conf.d/compress

    """)



