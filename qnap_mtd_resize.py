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
        U-Boot_Config  0x00080000 0x00040000  256KiB  /dev/mtd4
        NAS_Config     0x000c0000 0x00040000  256KiB  /dev/mtd5
        Kernel         0x00100000 0x00300000  3MiB    /dev/mtd1
        RootFS1        0x00400000 0x00c00000  12MiB   /dev/mtd2
        Kernel_legacy  0x00200000 0x00200000  2MiB    /dev/mtd3  (legacy Kernel range, overlap with new Kernel)


    Example for TS-219P
        U-boot legacy env
        
           bootcmd=uart1 0x68;cp.l 0xf8200000 0x800000 0x80000;cp.l 0xf8400000 0xa00000 0x240000;bootm 0x800000
           
           boorargs=console=ttyS0,115200 root=/dev/ram initrd=0xa00000,0x900000 ramdisk=32768
           
        New U-boot env
           bootcmd=uart1 0x68;cp.l 0xf8100000 0x800000 0xc0000;cp.l 0xf8400000 0xb00000 0x300000;bootm 0x800000;\
                    echo Kernel_legacy layout fallback;bootm 0x900000
           
           boorargs=console=ttyS0,115200 root=/dev/ram initrd=0xb00000,0xc00000 ramdisk=32768 \ 
                    cmdlinepart.mtdparts=spi0.0:512k@0(uboot)ro,3M@0x100000(Kernel),\
                    12M@0x400000(RootFS1),2M@0x200000(Kernel_legacy),256k@0x80000(U-Boot_Config),\
                    256k@0xc0000(NAS_Config)
    
     

    
"""


import subprocess
import os
import argparse
import logging
import re
import sys
import shutil


# list here the model of tested QNAP device by listing the
# DTB files returned by /usr/share/flash-kernel/dtb-probe/kirkwood-qnap
TESTED_QNAP_DTB = [
    "kirkwood-ts219-6281.dtb",
    "kirkwood-ts219-6282.dtb",
    "kirkwood-ts419-6281.dtb",
    "kirkwood-ts419-6282.dtb",
    ]


def mtd_lookup(*names):
    """
        For a list of MTD partition names, return a tuple
        ("mtdX", size, erasesize) of the first match
        Raise a KeyError exception if not found.
    """
    for line in open("/proc/mtd").readlines():
        m = re.match(r'(mtd[0-9]+): ([0-9a-f]+) ([0-9a-f]+) "(.+)"', line.strip())
        if not m:
            continue
        if m.group(4) in names:
            return (m.group(1), int(m.group(2), 16), int(m.group(3), 16))
    raise KeyError(f"No mtd {names} device found.")
    

def str_replace(search, replace, text):
    """
        Search for 'search' pattern in 'text' and replace by 'replace'
        Raise a KeyError if 'search' is not found.
    """
    result = re.sub(search, replace, text)
    if result == text:
        raise KeyError(f"'{search}' not found in '{text}'")
    return result


def try_shell_cmd(cmd, on_error=None):
    """
        Execute 'cmd' just to see if it returns 0 (and everything is fine) 
        or something else due to:
        - missing executable
        - wrong executable version

        if 'on_error' is not None, display the 'on_error' message and exit

        Return True is success, False otherwise
    """
    try:
        subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return True
    except:
        if on_error:
            print(on_error)
            exit(1)
        return False




parser = argparse.ArgumentParser(
        description='Tool to resize QNAP mtd partitions in order to increase the kernel and rootfs size'
        )

parser.add_argument("--dry-run", action="store_true", help="Don't modify the flash content")
parser.add_argument("--skip-bootargs", action="store_true", help="[WARNING] Don't patch bootargs. --setenv-script also required")
parser.add_argument("--skip-bootcmd", action="store_true", help="[WARNING] Don't patch bootcmd. --setenv-script also required")
parser.add_argument("--setenv-script-append", metavar="FILE", help="""
    Additional setenv script to append in addition to the bootargs and bootcmd patching.
    (see man fw_setenv)")
    """)
parser.add_argument("--drop-nas-config", action="store_true", help="""
    Don't try to resize 'NAS config' partition and drop its content.
    (Useful if e2fsck keeps failing and the partition is not recoverable)")
    """)

args = parser.parse_args()


if (args.skip_bootargs or args.skip_bootcmd) and (not args.setenv_script_append):
    print("--skip-bootargs and --skip-bootcmd require to also use --setenv-script-append option to provide the proper final settings for bootargs and bootcmd")
    print("Use and empty file if you definitely don't want to modify bootargs or bootcmd")
    exit(1)



if args.setenv_script_append:
    try:
        setenv_script_append_content = open(args.setenv_script_append).read()
    except:
        print(f"Failed to read {args.setenv_script_append}")
        exit(1)


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
 
 
mtd_nas_config, size, _ = mtd_lookup("NAS Config", "NAS_Config")
if size != 0x00140000:
    print("'NAS config' has already been resized. Can't process further safely.")
    exit(1)
    
mtd_uboot_config, _, _ = mtd_lookup("U-Boot Config", "U-Boot_Config")



# add /sbin and /usr/sbin in the PATH to be sure tools like flashcp can be found
os.environ["PATH"] += ":/sbin:/usr/sbin"
    
# early check of required tools to see if we have all of them
for tool_cmd in [
        "flashcp -V", 
        "flash_erase --version", 
        ]:
    print("Checking:", tool_cmd)
    try_shell_cmd(tool_cmd, on_error=f"'{tool_cmd}' Failed. Please see manually if correctly installed")

        

# check if fw_setenv is coming from "libubootenv-tool" package (bullseye) or "u-boot-tools" package (buster)
# There are some little differences to take in count
if (    try_shell_cmd("fw_setenv -v") and 
        try_shell_cmd("fw_setenv -h 2>&1 | grep 'Modify variables in U-Boot environment' -q") and 
        try_shell_cmd("fw_setenv -h 2>&1 | grep -q -- --lock")
        ):
    print("Using 'u-boot-tools' package")
    has_libubootenv = False
    try_shell_cmd("fw_printenv -v", on_error="'fw_printenv -v' Failed. Please see manually if correctly installed")
elif (try_shell_cmd("fw_setenv -V") and 
        try_shell_cmd("fw_setenv -h 2>&1 | grep -q -- --defenv")
        ):
    print("Using 'libubootenv-tool' package")
    has_libubootenv = True
    try_shell_cmd("fw_printenv -V", on_error="'fw_printenv -V' Failed. Please see manually if correctly installed")
else:
    print("'fw_setenv' is missing or its version can't be defined. Please see manually if correctly installed")
    exit(1)


    
# root ?
if os.getuid() != 0:
    print("You must be root.")
    exit(1)
    
    
    
###################################################################
print("\n[find on which MTD device partitions are currently mounted]")  
mtd_master = None
for line in subprocess.check_output(["dmesg"]).split(b"\n"):
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
for line in subprocess.check_output(["fw_printenv", "-c", "/tmp/fw_env.config"]).decode().split("\n"):
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


NEW_MTDPARTS=f"{mtd_master}:512k@0(uboot)ro,3M@0x100000(Kernel),12M@0x400000(RootFS1),2M@0x200000(Kernel_legacy),256k@0x80000(U-Boot_Config),256k@0xc0000(NAS_Config)"

    
    
   
   
###################################################################
if args.skip_bootcmd:
    print("\n[Skipping 'bootcmd patching']")
    print("You should manual modify the uboot env variable to let uboot load:")
    print("  - load the 3MB kernel image from flash (bus address 0xf8100000) to memory at address 0x800000")
    print("  - load the 12MB initrf image from flash (bus address 0xf8400000) to memory at address 0xb00000")
else:
    print("\n[Prepare new 'bootcmd']")
    try:
        if bootcmd.find("cp.l") >= 0:
            # most common configuration
            bootcmd_new = str_replace("cp.l 0xf8200000 0x800000 0x0*80000",
                                      "cp.l 0xf8100000 0x800000 0xc0000", bootcmd)
            bootcmd_new = str_replace("cp.l 0xf8400000 0xa00000 0x240000",
                                      "cp.l 0xf8400000 0xb00000 0x300000", bootcmd_new)
        elif bootcmd.find("cp.b") >= 0:
            # some old configurations are using cp.b
            bootcmd_new = str_replace("cp.b 0xf8200000 0x800000 0x200000",
                                      "cp.b 0xf8100000 0x800000 0x300000", bootcmd)
            bootcmd_new = str_replace("cp.b 0xf8400000 0xa00000 0x900000",
                                      "cp.b 0xf8400000 0xb00000 0xc00000", bootcmd_new)
        else:
            raise KeyError("bootcmd not using 'cp.l' nor 'cp.b'")
                                  
        # in case of QNAP TFTPBOOT recovery (ie. pressing reset button during boot + running live-cd-20130730.iso from VM)
        # uboot will:
        # - flash the legacy kernel at flash offset 0x200000
        # - flash the legacy rootfs at flash offset 0x400000
        # - DOESN'T restore the original uboot env
        # If we want to be able to boot after a QNAP TFTPBOOT recovery, our "bootcmd" must be able to fallback
        # to a kernel at flash 0x200000 (which is loaded in memory at 0x900000 when we load ou 3MB kernel from flash 0x100000)
        bootcmd_new += ";echo Kernel_legacy layout fallback;bootm 0x900000"
    except KeyError as e:
        print(str(e))
        print("Don't know how to patch 'bootcmd' for this model. Please report this log.")
        exit(1)
        
    print("   Old:", bootcmd)
    print("   New:", bootcmd_new)


###################################################################
if args.skip_bootargs:
    print("\n[Skipping 'bootargs patching']")
    print("You should manual modify the uboot env variable to add the following lines to your kernel cmdline/bootagrgs:")
    print(f' cmdlinepart.mtdparts={NEW_MTDPARTS} mtdparts={NEW_MTDPARTS}')
else:
    print("\n[Prepare new 'bootargs']")
    try:
        bootargs_new = str_replace("initrd=0xa00000,0x900000", 
                                  "initrd=0xb00000,0xc00000", bootargs)
                                  
        # setup cmdlinepart.mtdparts=... to set the partitions for cases where 'cmdlinepart' is build as external module 
        # (which is the current Debian behavior)
        bootargs_new = bootargs_new + f' cmdlinepart.mtdparts={NEW_MTDPARTS}'
        
        # also add mtdparts=... if for some reasons in future, Debian will switch to internal module or if users are
        # building their own kernel with such configuration
        bootargs_new = bootargs_new + f' mtdparts={NEW_MTDPARTS}'

    except KeyError as e:
        print(str(e))
        print("Don't know how to patch 'bootargs' for this model. Please report this log.")
        exit(1)
    
    print("   Old:", bootargs)
    print("   New:", bootargs_new)




###################################################################
print("\n[Prepare fw_setenv script (/tmp/fw_setenv.script)]")

script=""


# fw_set env differs in script syntax if the tool is coming from libubootenv or not
if has_libubootenv:
    equal="="
else:
    equal=" "


if not args.skip_bootargs:
    script += f"""
bootargs_backup{equal}{bootargs}
bootargs{equal}{bootargs_new}
"""

if not args.skip_bootcmd:
    script += f"""
bootcmd_backup{equal}{bootcmd}
bootcmd{equal}{bootcmd_new}
"""

if args.setenv_script_append:
    print(f"Append {args.setenv_script_append}")
    script += setenv_script_append_content


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
if args.drop_nas_config:
    print("[--drop-nas-config => don't try to resize 'NAS config']")
else:
    print("[Resize 'NAS config' dump from 1280KB to 256KB.]")

    cmd = f"""
    set -e
    set -x
    modprobe loop
    
    loopdev=$(losetup --show -f /tmp/mtd_nas_config.dump)
    
    # run e2fsck twice. the First may return an error status even if FS is corrected
    e2fsck -f -p -v $loopdev || true
    if ! e2fsck -f -p -v $loopdev; then
        echo "e2fsck failed. 'NAS config' resize not possible automatically"
        losetup -d $loopdev
        exit 1
    fi
    
    if ! resize2fs $loopdev 128; then
        echo "resize2fs failed. 'NAS config' resize not possible automatically"
        losetup -d $loopdev
        exit 1
    fi
    losetup -d $loopdev
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
        fw_printenv -c /tmp/fw_env.config  > /tmp/uboot_config.backup.txt
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
cmd = f"""flashcp -v /tmp/mtd_nas_config.new /dev/{mtd_nas_config}"""
if not args.dry_run:
    print("+", cmd)
    subprocess.check_call(cmd, shell=True)
else:
    print("(Dry run)")
    print("+", cmd)
    
   
    
###################################################################
print("\n[Change U-boot config with new values)]")
cmd = f"""fw_setenv -c /tmp/fw_env.config -s /tmp/fw_setenv.script"""
if not args.dry_run:
    print("+", cmd)
    subprocess.check_call(cmd, shell=True)
else:
    print("(Dry run)")
    print("+", cmd)



###################################################################
print("\n[Flash tail of the kernel in old 'Kernel' Partition]")
cmd = f"""flashcp -v /tmp/mtd_kernel.tail /dev/{mtd_kernel}"""
if not args.dry_run:
    print("+", cmd)
    subprocess.check_call(cmd, shell=True)
else:
    print("(Dry run)")
    print("+", cmd)


###################################################################
print("\n[Make a copy of /tmp/fw_env.config into /etc/fw_env.config (if not already existing)]")
if not args.dry_run:
    if not os.path.exists("/etc/fw_env.config"):
        shutil.copy("/tmp/fw_env.config", "/etc/fw_env.config")



###################################################################
print("-"*60)
print("""
    SUCCESS. 

    Now, REBOOT !
    
    Notes: 
    - DO NOT PERFORM A KERNEL OR SYSTEM UPDATE before the next reboot !... 
      so don't wait too long.
    - Consider compressing initrd with 'xz' to optimize the size with:
    
        echo "COMPRESS=xz" > /etc/initramfs-tools/conf.d/compress

    """)



