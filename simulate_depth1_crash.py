#!/usr/bin/env python3
"""
simulate_depth1_crash.py

Byte-for-byte re-implementation of EXT4Reader.getExtents(inode:)'s depth==1
branch (Sources/ContainerizationEXT4/EXT4+Reader.swift), run against the
real bytes of poc_depth1.img.

    case 1:
        for _ in 0..<header.entries {                      // header = inode's own i_block header
            let indexNode = inodeBlock.subdata(...)          // ExtentIndex, 12 bytes
            try self.seek(block: indexNode.leafLow)
            let block = try self.handle.read(upToCount: Int(self.blockSize))   // full 4096-byte block
            let leafHeader = block.subdata(in: 0..<12)...    // ExtentHeader read from the disk block
            guard leafHeader.magic == EXT4.ExtentHeaderMagic else { throw ... }
            for _ in 0..<leafHeader.entries {                 // <-- NO check against block.count
                let leaf = block.subdata(in: blockOffset..<blockOffset+12)...
                blockOffset += 12
            }
        }

Two headers are involved: the inode's own 60-byte i_block header (says
depth=1, entries=1 -- correctly bounded, that part is fine) and the disk
BLOCK's header read from the pointed-to block (leafHeader.entries is used
against a 4096-byte buffer with no bounds check -- that's the bug).
"""
import struct
import sys

BLOCK_SIZE = 4096
INODE_TABLE_START_BLOCK = 34
INODE_SIZE = 256
HEADER_SIZE = 12
INDEX_SIZE = 12
LEAF_SIZE = 12


def simulate(img_path: str, inode_num: int):
    inode_offset = INODE_TABLE_START_BLOCK * BLOCK_SIZE + (inode_num - 1) * INODE_SIZE
    iblock_offset = inode_offset + 40

    with open(img_path, "rb") as f:
        f.seek(iblock_offset)
        iblock = f.read(60)
        magic, entries, mx, depth, gen = struct.unpack_from("<HHHHI", iblock, 0)
        print(f"inode {inode_num} i_block: magic=0x{magic:04x} entries={entries} "
              f"max={mx} depth={depth}")
        assert magic == 0xF30A and depth == 1, "this simulator expects a depth=1 index node"

        offset = HEADER_SIZE
        for i in range(entries):
            block_no, leaf_low, leaf_high, unused = struct.unpack_from(
                "<IIHH", iblock, offset)
            print(f"  index {i}: block={block_no} leafLow={leaf_low}  -> seek(block: {leaf_low})")

            f.seek(leaf_low * BLOCK_SIZE)
            block = f.read(BLOCK_SIZE)
            count = len(block)

            lmagic, lentries, lmax, ldepth, lgen = struct.unpack_from("<HHHHI", block, 0)
            print(f"    leaf block header: magic=0x{lmagic:04x} entries={lentries} "
                  f"max={lmax} depth={ldepth}  (buffer is {count} bytes, "
                  f"real capacity = {(count-HEADER_SIZE)//LEAF_SIZE} leaves)")
            assert lmagic == 0xF30A, "leaf header magic check would throw Error.invalidExtents here"

            block_offset = HEADER_SIZE
            for j in range(lentries):
                lo, hi = block_offset, block_offset + LEAF_SIZE
                if hi > count:
                    print(f"    leaf iter {j}: block.subdata(in: {lo}..<{hi})  "
                          f"[*** OUT OF RANGE -> traps, {count}-byte buffer ***]")
                    print(f"\nCRASH CONFIRMED (depth==1 branch): leaf read {j} at block-offset "
                          f"{lo} needs {LEAF_SIZE} bytes but only {count-lo} remain in the "
                          f"{count}-byte disk block.")
                    return
                block_offset += LEAF_SIZE
            offset += INDEX_SIZE

    print("\nLoop terminated normally -- no crash.")


if __name__ == "__main__":
    img = sys.argv[1] if len(sys.argv) > 1 else "poc_depth1.img"
    inode = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    simulate(img, inode)
