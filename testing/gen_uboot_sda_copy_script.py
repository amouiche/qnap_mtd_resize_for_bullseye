#!/usr/bin/env python3

sda1_size_blk = 9762816
sda1_offset_blk = 2048


max_chunk_size_MB = 256
ram_addr=0x800000

sda1_backup_offset_blk = 220000000




max_chunk_size_blk = max_chunk_size_MB * 1024 * 1024 // 512
max_uboot_cmd_size = 800


echo="echo "
echo=""

cmds = []
while sda1_size_blk:
    chunk_blk = min(sda1_size_blk, max_chunk_size_blk)
    
    cmds.append(echo+f"ide read {ram_addr:x} {sda1_backup_offset_blk:x} {chunk_blk:x}")
    cmds.append(echo+f"ide write {ram_addr:x} {sda1_offset_blk:x} {chunk_blk:x}")
    
    sda1_offset_blk += chunk_blk
    sda1_backup_offset_blk += chunk_blk
    sda1_size_blk += -chunk_blk
    


line=cmds[0]
for cmd in cmds[1:]:

    next_line = line + ";" + cmd
    if len(next_line) >= max_uboot_cmd_size:
        print(line)
        print()
        line = cmd
    else:
        line = next_line

        
if line:
    print(line)

