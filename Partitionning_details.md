## Kernel and MTD partitions

(This section is for documentation only and describes how Flash partitions are defined under linux.)

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
   
   for D in kirkwood-ts219-6281 kirkwood-ts219-6282 kirkwood-ts419-6281 kirkwood-ts419-6282; do
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
- Patch U-boot env/config for the new `bootargs`and `bootcmd`variables, to boot either from the new kernel layout (kernel @ 0x100000) or the legacy as a fallback (kernel @ 0x200000)
- Write flash from 0xc0000 to 0x200000 ("NAS config" + 1MB head of kernel)
- write flash from 0x200000 with 1MB tail of kernel.

