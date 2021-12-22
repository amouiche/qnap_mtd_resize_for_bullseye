## Partitions sur sda

```
Disk /dev/sda: 1.4 TiB, 1500301910016 bytes, 2930277168 sectors
Disk model: SAMSUNG HD154UI 
Units: sectors of 1 * 512 = 512 bytes
Sector size (logical/physical): 512 bytes / 512 bytes
I/O size (minimum/optimal): 512 bytes / 512 bytes
Disklabel type: dos
Disk identifier: 0xe668f527

Device     Boot   Start      End  Sectors  Size Id Type
/dev/sda1          2048  9764863  9762816  4.7G 83 Linux  => image debian
/dev/sda2       9764864 30736383 20971520   10G 83 Linux  => used for storing backups

```



------



## Debian Buster

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

Réalisation du backup

```
BACKUP=debian_buster
mkdir -p /mnt/disk
mount /dev/sda2 /mnt/disk
mkdir -p /mnt/disk/$BACKUP
cd /mnt/disk/$BACKUP
mkdir dev
cat /proc/mtd > proc.mtd
for dev in /dev/mtd?; do dd if=$dev of=/mnt/disk/$BACKUP/$dev; done
            30736383
SDA_OFFSET=    100000000 blk
KERNEL_OFFSET  100000000 blk  size 0x00200000 bytes => 4096 blk
INITRD_OFFSET  110000000 blk  size 0x00900000 bytes => 18432 blk
SDA1_OFFSET    120000000 blk  size 9762816 blk



dd if=/dev/mtd1 of=/dev/sda seek=100000000
dd if=/dev/mtd2 of=/dev/sda seek=110000000

dd if=/dev/sda1 ibs=1048576 of=/dev/sda seek=120000000 status=progress

```



Restoration de /dev/sda1 depuis le shell d'uboot et boot sur le kernel+initrd de buster

```
ide read 800000 7270e00 80000;ide write 800000 800 80000;ide read 800000 72f0e00 80000;ide write 800000 80800 80000;ide read 800000 7370e00 80000;ide write 800000 100800 80000;ide read 800000 73f0e00 80000;ide write 800000 180800 80000;ide read 800000 7470e00 80000;ide write 800000 200800 80000;ide read 800000 74f0e00 80000;ide write 800000 280800 80000;ide read 800000 7570e00 80000;ide write 800000 300800 80000;ide read 800000 75f0e00 80000;ide write 800000 380800 80000;ide read 800000 7670e00 80000;ide write 800000 400800 80000;ide read 800000 76f0e00 80000;ide write 800000 480800 80000;ide read 800000 7770e00 80000;ide write 800000 500800 80000;ide read 800000 77f0e00 80000;ide write 800000 580800 80000;ide read 800000 7870e00 80000;ide write 800000 600800 80000

ide read 800000 78f0e00 80000;ide write 800000 680800 80000;ide read 800000 7970e00 80000;ide write 800000 700800 80000;ide read 800000 79f0e00 80000;ide write 800000 780800 80000;ide read 800000 7a70e00 80000;ide write 800000 800800 80000;ide read 800000 7af0e00 80000;ide write 800000 880800 80000;ide read 800000 7b70e00 4f800;ide write 800000 900800 4f800


# load kernel to 0x800000  from block 100000000=0x5f5e100
# load initrd to 0xa00000
# and boot
setenv bootargs console=ttyS0,115200 root=/dev/ram initrd=0xa00000,0x900000 ramdisk=32768

ide read 800000 5f5e100 1000
ide read a00000 68e7780 4800
bootm 0x800000
```

Restoration finale de /dev/mtd1 à mtd5 sous linux

```
BACKUP=debian_buster
mkdir -p /mnt/disk
mount -o ro /dev/sda2 /mnt/disk
cd /mnt/disk/$BACKUP/dev
for i in 1 2 3 4 5; do
	echo mtd$i
	/usr/sbin/flashcp -v mtd$i /dev/mtd$i
done

```

------

## Bullseye avec le kernel de buster

Réalisation du backup

```
BACKUP=debian_bullseye_buster
mkdir -p /mnt/disk
mount /dev/sda2 /mnt/disk
mkdir -p /mnt/disk/$BACKUP
cd /mnt/disk/$BACKUP
mkdir dev
cat /proc/mtd > proc.mtd
for dev in /dev/mtd?; do dd if=$dev of=/mnt/disk/$BACKUP/$dev; done
            
SDA_OFFSET=    200000000 blk
KERNEL_OFFSET  200000000 blk  size 0x00200000 bytes => 4096 blk
INITRD_OFFSET  210000000 blk  size 0x00900000 bytes => 18432 blk
SDA1_OFFSET    220000000 blk  size 9762816 blk

MTD3_DUMP_OFFSET 230000000  size 6144 blk
MTD4_DUMP_OFFSET 234000000  size 512 blk
MTD5_DUMP_OFFSET 235000000  size 2560 blk


dd if=/dev/mtd1 of=/dev/sda seek=200000000
dd if=/dev/mtd2 of=/dev/sda seek=210000000
dd if=/dev/mtd3 of=/dev/sda seek=230000000
dd if=/dev/mtd4 of=/dev/sda seek=240000000
dd if=/dev/mtd5 of=/dev/sda seek=250000000

dd if=/dev/sda1 ibs=1048576 of=/dev/sda seek=220000000 status=progress

```



boot sur le kernel+initrd de bullseye + kernel buster et execution de /bin/sh

```
# load kernel to 0x800000  from block 200000000=0xbebc200
# load initrd to 0xa00000  from block 210000000=0xc845880
# and boot
setenv bootargs console=ttyS0,115200 root=/dev/ram initrd=0xa00000,0x900000 ramdisk=32768 init=/bin/sh

ide read 800000 bebc200 1000
ide read a00000 c845880 4800
bootm 0x800000
```

dans /bin/sh, restauration de /dev/sda1 depuis la copie en block 220000000 ansi que des partitions mtd

```
BACKUP=debian_bullseye_buster
dd if=/dev/sda skip=220000000 of=/dev/sda1 obs=1048576

# et reboot
reboot -f
```

reboot sur le kernel+initrd de bullseye + kernel buster + filesystem complet

```
# load kernel to 0x800000  from block 200000000=0xbebc200
# load initrd to 0xa00000  from block 210000000=0xc845880
# and boot
setenv bootargs console=ttyS0,115200 root=/dev/ram initrd=0xa00000,0x900000 ramdisk=32768

ide read 800000 bebc200 1000
ide read a00000 c845880 4800
bootm 0x800000
```

Restoration finale de /dev/mtd1 à mtd5 sous linux

```
BACKUP=debian_bullseye_buster
mount /dev/sda2 /mnt/disk
cd /mnt/disk/$BACKUP/dev
for i in 1 2 3 4 5; do
	echo mtd$i
	/usr/sbin/flashcp -v mtd$i /dev/mtd$i
done


```

------

