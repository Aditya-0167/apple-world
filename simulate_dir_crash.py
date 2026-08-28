#!/usr/bin/env python3
"""
simulate_dir_crash.py

Byte-for-byte re-implementation of EXT4Reader.getDirEntries(dirTree:)
(Sources/ContainerizationEXT4/EXT4+Reader.swift), run against the real
directory block bytes of a crafted image, to show exactly which
Data.subdata(in:) call goes out of range.

    var offset = 0
    let entrySize = MemoryLayout<DirectoryEntry>.size   // 8
    while offset < dirTree.count {
        let dirEntry = dirTree.subdata(in: offset..<offset + entrySize)...
        guard dirEntry.recordLength >= entrySize else { break }
        if dirEntry.inode == 0 {
            offset += Int(dirEntry.recordLength)
            continue
        }
        let nameData = dirTree.subdata(in: offset + 8..<offset + 8 + Int(dirEntry.nameLength))
        ...
        offset += Int(dirEntry.recordLength)
    }

DirectoryEntry (EXT4+Types.swift): inode: UInt32, recordLength: UInt16,
nameLength: UInt8, fileType: UInt8  -> 8 bytes, in that order.
"""
import struct
import sys

BLOCK_SIZE = 4096
BLOCK_NUM = 1161   # dirvictim's data block, from `debugfs -R 'stat dirvictim'`
ENTRY_SIZE = 8


def load_block(img_path: str) -> bytes:
    with open(img_path, "rb") as f:
        f.seek(BLOCK_NUM * BLOCK_SIZE)
        return f.read(BLOCK_SIZE)


def simulate(dir_tree: bytes):
    count = len(dir_tree)
    offset = 0
    it = 0
    while offset < count:
        hi = offset + ENTRY_SIZE
        if hi > count:
            print(f"  iter {it}: dirTree.subdata(in: {offset}..<{hi})  "
                  f"[*** OUT OF RANGE (header read) -> traps, {count}-byte buffer ***]")
            print(f"\nCRASH CONFIRMED (Bug A / record-length gap): header read at "
                  f"offset {offset} needs {ENTRY_SIZE} bytes but only {count-offset} remain.")
            return
        inode, reclen, namelen, ftype = struct.unpack_from("<IHBB", dir_tree, offset)
        print(f"  iter {it}: header @ {offset}..<{hi} OK  "
              f"(inode={inode} recordLength={reclen} nameLength={namelen} fileType={ftype})")

        if reclen < ENTRY_SIZE:
            print(f"  recordLength {reclen} < {ENTRY_SIZE} -> loop breaks (no crash)")
            return

        if inode == 0:
            print(f"    inode==0 -> skip, offset += {reclen}")
            offset += reclen
            it += 1
            continue

        name_lo, name_hi = offset + 8, offset + 8 + namelen
        if name_hi > count:
            print(f"  iter {it}: dirTree.subdata(in: {name_lo}..<{name_hi})  "
                  f"[*** OUT OF RANGE (name read) -> traps, {count}-byte buffer ***]")
            print(f"\nCRASH CONFIRMED (Bug B / nameLength gap): name read at offset "
                  f"{name_lo} requests {namelen} bytes (to {name_hi}) but only "
                  f"{count-name_lo} remain.")
            return
        print(f"    name @ {name_lo}..<{name_hi} OK")
        offset += reclen
        it += 1

    print("\nLoop terminated normally -- no crash.")


if __name__ == "__main__":
    img = sys.argv[1] if len(sys.argv) > 1 else "poc_dirbug_recordlength.img"
    simulate(load_block(img))
