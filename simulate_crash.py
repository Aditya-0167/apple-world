#!/usr/bin/env python3
"""
simulate_crash.py

Runs the *exact* parsing logic of EXT4Reader.getExtents(inode:) (depth==0
branch, Sources/ContainerizationEXT4/EXT4+Reader.swift) against the real
bytes of poc.img, to show precisely which iteration would call
Data.subdata(in:) with an out-of-range Range on a 60-byte i_block buffer.

This is not a substitute for running it in Swift -- it's a byte-for-byte
re-implementation of the loop so a reviewer without a Mac/Swift toolchain
handy can confirm the trigger condition against the actual crafted image
before running the real Swift reproduction.

Struct sizes/offsets below are taken directly from the current
apple/containerization main branch:
  - EXT4.Inode.block          : Sources/ContainerizationEXT4/EXT4+Types.swift (60-byte tuple, offset 40 in Inode)
  - EXT4.ExtentHeader / .ExtentLeaf : Sources/ContainerizationEXT4/EXT4+Types.swift (12 bytes each)
  - getExtents(inode:) depth==0 loop : Sources/ContainerizationEXT4/EXT4+Reader.swift
"""
import struct
import sys

BLOCK_SIZE = 4096
INODE_TABLE_START_BLOCK = 34
INODE_SIZE = 256
IBLOCK_STRUCT_OFFSET = 40   # offset of Inode.block within the on-disk inode
HEADER_SIZE = 12            # MemoryLayout<EXT4.ExtentHeader>.size
LEAF_SIZE = 12               # MemoryLayout<EXT4.ExtentLeaf>.size
EXT4_EXTENT_MAGIC = 0xF30A


def load_iblock(img_path: str, inode_num: int) -> bytes:
    inode_table_start = INODE_TABLE_START_BLOCK * BLOCK_SIZE
    inode_offset = inode_table_start + (inode_num - 1) * INODE_SIZE
    iblock_offset = inode_offset + IBLOCK_STRUCT_OFFSET
    with open(img_path, "rb") as f:
        f.seek(iblock_offset)
        return f.read(60)


def simulate(inode_block: bytes):
    """Mirrors:
        var offset = 0
        let header = inodeBlock.subdata(in: offset..<offset+12)...
        offset += 12
        for _ in 0..<header.entries {
            let leaf = inodeBlock.subdata(in: offset..<offset+12)...
            offset += 12
        }
    """
    count = len(inode_block)
    magic, entries, max_, depth, gen = struct.unpack_from("<HHHHI", inode_block, 0)
    print(f"inodeBlock.count = {count}")
    print(f"header: magic=0x{magic:04x} entries={entries} max={max_} depth={depth} generation={gen}")

    if magic != EXT4_EXTENT_MAGIC:
        print("magic check fails -> getExtents returns [] early (not our case)")
        return
    if depth != 0:
        print("depth != 0, this script only simulates the depth==0 branch")
        return

    offset = HEADER_SIZE
    for i in range(entries):
        lo, hi = offset, offset + LEAF_SIZE
        in_range = hi <= count
        status = "OK" if in_range else "*** OUT OF RANGE -> Data.subdata traps (Fatal error) ***"
        print(f"  iteration {i}: inodeBlock.subdata(in: {lo}..<{hi})  [{status}]")
        if not in_range:
            print(f"\nCRASH CONFIRMED: iteration {i} (0-indexed) requests bytes "
                  f"[{lo}, {hi}) from a {count}-byte buffer.")
            return
        offset += LEAF_SIZE
    print("\nAll iterations stayed in-bounds -- no crash for this entries value.")


if __name__ == "__main__":
    img = sys.argv[1] if len(sys.argv) > 1 else "poc.img"
    inode = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    iblock = load_iblock(img, inode)
    simulate(iblock)
