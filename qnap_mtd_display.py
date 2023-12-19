#!/usr/bin/env python3

"""
    SPDX-License-Identifier: GPL-2.0  

    Copyright 2021 Arnaud Mouiche
    GPV Mods for SABOTEUR layout (see  https://forum.qnap.com/viewtopic.php?t=167230)
    
    This tool can be run after a reboot following qnap_mtd_resize.py.
    It simply displays what the settings now are.
    This is a read only script, so nothing is changed.

    
    While the legacy MTD partition is:
    
                           offset     size
        uboot          0x00000000 0x00080000  512KiB  /dev/mtd0
        U-Boot Config  0x00080000 0x00040000  256KiB  /dev/mtd4  ... Holds U-Boot variables
        NAS Config     0x000c0000 0x00140000  1280KiB /dev/mtd5
        Kernel         0x00200000 0x00200000  2MiB    /dev/mtd1  ... Holds Kernel
        RootFS1        0x00400000 0x00900000  9MiB    /dev/mtd2  ... Holds /boot/initrd.img
        RootFS2        0x00d00000 0x00300000  3MiB    /dev/mtd3  (unlused)



    ... and the SABOTEUR MTD partition is:
    
                           offset     size
        uboot          0x00000000 0x00080000  512KiB  /dev/mtd0
        U-Boot Config  0x00080000 0x00040000  256KiB  /dev/mtd4  ... Holds U-Boot variables
        NAS Config     0x000c0000 0x00140000  1280KiB /dev/mtd5
        Kernel         0x00200000 0x00200000  2MiB    /dev/mtd1  (unused)
        RootFS1        0x00400000 0x00900000  9MiB    /dev/mtd2  ... Holds /boot/initrd.img
        RootFS2        0x00d00000 0x00300000  3MiB    /dev/mtd3  ... Holds Kernel


    The new mapping should now be:
    
                            offset     size
        uboot          0x00000000 0x00080000  512KiB  /dev/mtd0
        U-Boot_Config  0x00080000 0x00040000  256KiB  /dev/mtd4
        NAS_Config     0x000c0000 0x00040000  256KiB  /dev/mtd5
        Kernel         0x00100000 0x00300000  3MiB    /dev/mtd1  ... Holds Kernel
        RootFS1        0x00400000 0x00c00000  12MiB   /dev/mtd2  ... Holds /boot/initrd.img
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

DB="/etc/flash-kernel/db"
NEWDB="/etc/flash-kernel/newdb"



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
    return ("Missing", 0, 0)
    




###################################################################

    
print ("The MTD partitions are as follows")
with open('/proc/mtd', 'r', encoding="utf-8") as F:
    print(F.read())

# Display the sizes
mtd_kernel, size, _ = mtd_lookup("Kernel")

print("Kernel is ", mtd_kernel, "Size is " , size, "(", size/(1024*1024),  ") Mb" )

    
mtd_rootfs1, size, _ = mtd_lookup("RootFS1")

print("ROOTFS1 is ", mtd_rootfs1, "Size is " , size, "(", size/(1024*1024),  ") Mb" )

mtd_rootfs2, size, _ = mtd_lookup("RootFS2")

print("ROOTFS2 is ", mtd_rootfs2, "Size is " , size, "(", size/(1024*1024),  ") Mb" )

mtd_nas_config, size, _ = mtd_lookup("NAS Config", "NAS_Config")
print("NAS_CONFIG is ", mtd_nas_config, "Size is " , size, "(", size/(1024),  ") Kb" )

mtd_uboot_config, size, _ = mtd_lookup("U-Boot Config", "U-Boot_Config")

print("UBOOT_CONFIG is ", mtd_uboot_config, "Size is " , size, "(", size/(1024),  ") Kb" )



    
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



