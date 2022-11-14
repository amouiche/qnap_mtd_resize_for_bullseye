# Recovery

QNAP provides a recovery mechanism that will restore the original Kernel and Rootfs

https://wiki.qnap.com/wiki/Firmware_Recovery

When reset button is pressed continuously during the boot, u-boot simply:

- download a image file using TFTP from IP 192.168.0.1 (it is using address 192.168.0.65 itself)
- Erase and program flash from adress 0x200000 to the end using the image downloaded (also starting at offset 0x200000 of the image file)

==> **Consequently, the u-boot env is not restored to its original content**.

==> **The partition resize will still apply after debian install **

This is sufficient if you expect to install Debian again.

If you really need to restore the very original firmware, you need to flash the backup you have performed before the very first Debian install.



## Recover original QNAP firmwre using the MTD backup performed before the first Debian install

You should have keep a backump of 6 dumps from mtd0 to mtd5

```
mtd0  524288 bytes
mtd1  2097152  bytes
mtd2  9437184  bytes
mtd3  3145728  bytes
mtd4  262144   bytes
mtd5  1310720  bytes
```

To restore the original QNAP firmware / partitions, we only need to write them again on Flash. The method depends the current OS you are running.



### From QNAP OS

QNAP firmware ssh server seems to miss `scp` or `sftp` feature. Let's use a USB key to store our backup:

- Copy all the `mtd?` files on a **ext3** formated USB storage key formated 

- ssh on QNAP (monitor DHCP with wireshark to detect which IP address was assigned to the QNAP) 

  ```
  ssh admin@xx.xx.xx.xx
  (password: admin)
  ```

- Plug the USB key on QNAP. Detect which block device is assigned to it using `dmesg`. Mount the partition

  ```
  # dmesg | grep Attached -A 10
  [ 8828.287137] sd 4:0:0:0: Attached scsi generic sg19 type 0
  [ 8829.369728] sd 4:0:0:0: [sdt] 7823360 512-byte logical blocks: (4.00 GB/3.73 GiB)
  [ 8829.387117] sd 4:0:0:0: [sdt] Write Protect is off
  [ 8829.391994] sd 4:0:0:0: [sdt] Mode Sense: 23 00 00 00
  [ 8829.401104] sd 4:0:0:0: [sdt] No Caching mode page present
  [ 8829.406655] sd 4:0:0:0: [sdt] Assuming drive cache: write through
  [ 8829.432952] sd 4:0:0:0: [sdt] No Caching mode page present
  [ 8829.438470] sd 4:0:0:0: [sdt] Assuming drive cache: write through
  [ 8829.476353]  sdt: sdt1
  [ 8829.501715] sd 4:0:0:0: [sdt] No Caching mode page present
  [ 8829.507237] sd 4:0:0:0: [sdt] Assuming drive cache: write through
  [ 8829.513379] sd 4:0:0:0: [sdt] Attached SCSI removable disk
  [ 8829.518888] [#] set usb polling mode (sdt)
  [ 8835.036675] active port 0 :139
  [ 8835.039743] active port 1 :445
  [ 8835.042830] active port 2 :20
  ```

  => here on `/dev/sdt1`

  ```
  mkdir /tmp/disk
  mount /dev/sdt1 /tmp/disk
  cd /tmp/disk
  ```

Now we can flash our mtd backups.

Note: we skip mtd0 with is the bootloader. It is never modified and we want to avoid bricking the QNAP by writing on it.

```
cd /tmp/disk
for i in 1 2 3 4 5; do cp -v mtd$i /dev/mtdblock$i; done
```

Now just reboot

```
reboot
```









### From Debian (before MTD partitions resizing)

You are in this state if `cat /proc/mtd` gives:

```
root@debian:~# cat /proc/mtd 
dev:    size   erasesize  name
mtd0: 00080000 00040000 "U-Boot"
mtd1: 00200000 00040000 "Kernel"
mtd2: 00900000 00040000 "RootFS1"
mtd3: 00300000 00040000 "RootFS2"
mtd4: 00040000 00040000 "U-Boot Config"
mtd5: 00140000 00040000 "NAS Config"
```

The recovery is straightforward. First transfer the mtd backup files to the QNAP (scp, USB key, etc...)

Then, from a ssh console on QNAP

```
sudo su
for i in 1 2 3 4 5; do echo mtd$i; flashcp -v mtd$i /dev/mtd$i; done

# then reboot
reboot -f
```

Note: There is no need [and you should avoid] rewriting `mtd0`. It contains the bootloader and is never modified. It is not possible to completely brick the QNAP except by writing this bootloader... so avoid it.

### From Debian (**After** MTD partitions resizing)

You are in this state if `cat /proc/mtd` gives:

```
root@debian:~# cat /proc/mtd 
dev:    size   erasesize  name
mtd0: 00080000 00040000 "uboot"
mtd1: 00300000 00040000 "Kernel"
mtd2: 00c00000 00040000 "RootFS1"
mtd3: 00200000 00040000 "Kernel_legacy"
mtd4: 00040000 00040000 "U-Boot_Config"
mtd5: 00040000 00040000 "NAS_Config"
```

You have the original mtd dump files. Upload them on your QNAP (scp, USB key ...)

You need now to build the image for the resized partitions

```
# mtd4_resized: first 256KB of mtd4 (old NAS config)
dd if=mtd5 of=mtd5_resized count=512
# mtd1_resized: last 1MB of mtd4 (old NAS config) + mtd1 (old kernel)
dd if=mtd5 of=mtd1_resized_a skip=512
cp mtd1 mtd1_resized_b
cat mtd1_resized_a mtd1_resized_b > mtd1_resized
rm mtd1_resized_a mtd1_resized_b
# mtd2_resized: mtd2 (old rootfs1) + mtd3 (old rootfs2)
cat mtd2 mtd3 > mtd2_resized
# mtd4_resized: identical to mtd4 (uboot config)
cp mtd4 mtd4_resized
```

You must have now 4 "resized" files

```
root@debian:~# ls -l *_resized
-rw-r--r-- 1 root root 3145728 Nov 13 18:38 mtd1_resized
-rw-r--r-- 1 root root 9699328 Nov 13 18:38 mtd2_resized
-rw-r--r-- 1 root root  262144 Nov 13 18:38 mtd4_resized
-rw-r--r-- 1 root root  262144 Nov 13 18:38 mtd5_resized
```

You can finalize the recovery by writing them on Flash

```
for i in 1 2 4 5; do flashcp -v mtd${i}_resized /dev/mtd$i; done

```

Finalize with a reboot

```
reboot -f
```

