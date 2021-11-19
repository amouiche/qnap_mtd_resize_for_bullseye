# QNAP partitions resize for kirkwood devices.

As [explained by Marin Michlmayr](https://www.cyrius.com/debian/kirkwood/qnap/ts-219/upgrade/), Debian bullseye support on kirkwood QNAP devices was dropped due to [mainly] the limited size of the Kernel partition (2MB).

Indeed, Bullseye current kernel image (vmlinuz-5.10.0-8-marvell) is 2445216 bytes long (2.3MB)

In addition, partition for initrd is also limited (9MB) which may lead to space issues.

Hopefully, some space is still unused for Debian in QNAP 16MB NOR flash. 

- An additional 3MB Rootfs2 partition is used by original QNAP firmware for its own purpose (install on empty HDD ?)
- A "NAS config" partition is 1.2MB large despite containing few configuration files (<128KB). This partition can be resized to 256KB (Flash block size) without losing the information.

## New Layout

With this script, we propose to use a new flash layout

![Layout](resources/partitions.png)

- We keep /dev/mtdX numbers mapping, in case some other users are using a fix numbering.
- we keep a window on legacy kernel mapping to help if we want to restore the original QNAP firmware or to install the Buster installer
- Rootfs1 is larger but use the same start offset (simplify the transition since no write in flash is required)
- Kernel is larger. We must be careful during the transition since offsets are different.

With this new layout, we can transparently upgrade to Bullseye

- More room for kernel and initrd
- Future kernel updates performed during `apt upgrade`will use the new layout without any further change or manual operations.

## Kernel and MTD partitions (for your information only)

(This section is for documentation only. You can skip it and go directly to the "[Resize process](#Resize process)" section...)

Linux has 2 methods for configuring the partitions.

1. **Device Tree** 

   This is the standard way to describe the device. 

   see: https://github.com/torvalds/linux/blob/master/arch/arm/boot/dts/kirkwood-ts219.dtsi

   ```
   			m25p128@0 {
   				[...]
   				partition@0 {
   					reg = <0x00000000 0x00080000>;
   					label = "U-Boot";
   				};
   				partition@200000 {
   					reg = <0x00200000 0x00200000>;
   					label = "Kernel";
   				};
   				partition@400000 {
   					reg = <0x00400000 0x00900000>;
   					label = "RootFS1";
   				};
   				partition@d00000 {
   					reg = <0x00d00000 0x00300000>;
   					label = "RootFS2";
   				};
   				partition@40000 {
   					reg = <0x00080000 0x00040000>;
   					label = "U-Boot Config";
   				};
   				partition@c0000 {
   					reg = <0x000c0000 0x00140000>;
   					label = "NAS Config";
   				};
   			};
   ```

   On Debian, binary versions (dtb) are provided by the [linux-image-4.19.0-16-marvell](https://packages.debian.org/buster/linux-image-4.19.0-16-marvell) package.

   Every time a new kernel version is flashed by `flash-kernel`, the proper dtb blob is concatenated to the kernel image so the kernel knows the details of the machine and is able to configure all the drivers properly (including the MTD partitions).

   It is not difficult to build a DTB and configure Debian to use this alternate DTB file. It simply need to be present in `/etc/flash-kernel/dtbs/`directory and `flash-kernel` will correctly switch to our own specific file.

   Example:

   ```
   cd [clone of linux sources]/linux
   # modify arch/arm/boot/dts/kirkwood-ts219.dtsi
   
   for D in kirkwood-ts219-6281 kirkwood-ts219-6282; do
       cpp -nostdinc -I include -I arch  -undef -x assembler-with-cpp \
          ./arch/arm/boot/dts/$D.dts \
          /tmp/preprocess.dts
       dtc -O dtb -o /tmp/$D.dtb /tmp/preprocess.dts
       cp /tmp/$D.dtb /etc/flash-kernel/dtbs/
       done
   
   ```

   

2. **kernel boot cmdline**

   U-boot can also override the DTB information by using `mtdparts=....`options as parsed by https://github.com/torvalds/linux/blob/master/drivers/mtd/parsers/cmdlinepart.c

   The kernel try use use cmdline parameters before DTB information.

   Original QNAP U-boot configuration doesn't use this method.



**I select the "kernel boot cmdline" solution to configure the new layout:**

- if `/etc/flash-kernel/dtbs/`content is modified or erased for some reasons (new install ?) the u-boot setup and the kernel MTD usage will not be synchronized and the device will fail to boot.
- cmdline only "patch/override" the MTD partitions information. If the original DTB file provided by Debian is updated for some reasons (driver fixes), the kernel will still continue to use those fixes.

The `qnap_mtd_resize.py` script will:

- Resize the "NAS config" filesystem
- Prepare the content of current "NAS config" partition (offset 0xc0000 to 0x200000) with the shrink FS + first 1MB of the current kernel
- prepare the image of current "Kernel" partition (starting at 0x200000) with tail of the current kernel
- Patch U-boot env/config for the new `bootargs`and `bootcmd`variables.
- Write flash from 0xc0000 to 0x200000 ("NAS config" + 1MB head of kernel)
- write flash from 0x200000 with 1MB tail of kernel.



## Resize process

### First, Do a backup of your MTD

```
cat /dev/mtd0 > /tmp/mtd0.uboot.backup
cat /dev/mtd1 > /tmp/mtd1.kernel.backup
cat /dev/mtd2 > /tmp/mtd2.rootfs1.backup
cat /dev/mtd3 > /tmp/mtd3.rootfs2.backup
cat /dev/mtd4 > /tmp/mtd4.uboot-config.backup
cat /dev/mtd5 > /tmp/mtd5.nas-config.backup
cd /tmp
tar cvzf mtd_backup.tgz mtd?.*.backup
```

And save this `mtd_backup.tgz`on your PC, transfering the file with scp / sftp or a USB drive....

### Then, run qnap_mtd_resize.py

A first run with `--dry-run`option to check that everything will be fine (except flashing)

```
sudo ./qnap_mtd_resize.py --dry-run
```

Example of dry-run log [here.](resources/QNAP_TS419_family_dryrun_log.txt)

If everything is fine run again without `--dry-run`

```
sudo ./qnap_mtd_resize.py
```

And reboot...

You are now running the same system, but with more room:

```
$ cat /proc/mtd 
dev:    size   erasesize  name
mtd0: 00080000 00040000 "uboot"
mtd1: 00300000 00040000 "Kernel"
mtd2: 00c00000 00040000 "RootFS1"
mtd3: 00200000 00040000 "Kernel_legacy"
mtd4: 00040000 00040000 "U-Boot Config"
mtd5: 00040000 00040000 "NAS Config"
```

Which makes possible to install Bullseye's kernel:

```
$ flash-kernel 
kirkwood-qnap: machine: QNAP TS219 family
Using DTB: kirkwood-ts219-6281.dtb
Installing /usr/lib/linux-image-5.10.0-8-marvell/kirkwood-ts219-6281.dtb into /boot/dtbs/5.10.0-8-marvell/./kirkwood-ts219-6281.dtb
Taking backup of kirkwood-ts219-6281.dtb.
Installing new kirkwood-ts219-6281.dtb.
flash-kernel: installing version 5.10.0-8-marvell
flash-kernel: appending /usr/lib/linux-image-5.10.0-8-marvell/kirkwood-ts219-6281.dtb to kernel
Generating kernel u-boot image... done.
Flashing kernel (using 2455558/3145728 bytes)... done.
Flashing initramfs (using 3992060/12582912 bytes)... done.
```



## Additional configuration to improve`initrd` size

Even if we increase Rootfs1 from 9 to 12 MB, you can still decrease the initrd size by compressing with `xz`

```
echo "COMPRESS=xz" > /etc/initramfs-tools/conf.d/compress
```



# List of tested devices:

|Model| cat /sys/firmware/devicetree/base/model | DTB file                | uboot env<br>(legacy)                                        | uboot_env<br>(new)                                           | Resize log                                 |      |
| --------------------------------------- | ----------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------ | ---- | ---- |
| TS-212P | QNAP TS219 family                       | kirkwood-ts219-6282.dtb |                                                              |                                                              | [log](resources/QNAP_TS212P_log.txt) |      |
| TS-219P | QNAP TS219 family                       | kirkwood-ts219-6281.dtb |                                                              |                                                              |                                            |      |
| TS-212 | QNAP TS219 family | kirkwood-ts219-6281.dtb | | | [log](resources/QNAP_TS212_dryrun_log.txt) | |
|TS-419PII | QNAP TS419 family                       | kirkwood-ts419-6282.dtb | [QNAP_TS419_family,uboot-env.legacy](resources/QNAP_TS419_family,uboot-env.legacy) | [QNAP_TS419_family,uboot-env.new](resources/QNAP_TS419_family,uboot-env.new) | [log](resources/QNAP_TS419_family_log.txt) |      |
|  |                         |                                                              |                                                              |                                            |      ||

