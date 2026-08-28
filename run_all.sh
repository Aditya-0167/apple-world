#!/usr/bin/env bash
# run_all.sh -- runs the SwiftPM harness against every crafted image in turn.
# Each image is expected to CRASH the harness process (that's the bug) --
# a non-zero/signal exit is a PASS for that image, a clean "export() returned
# normally" is a FAIL (means that specific code path validated its bounds).
#
# Run from inside ext4-crash-poc/ on a Mac with a Swift toolchain:
#   swift build
#   ./run_all.sh

set -u
BIN=".build/debug/ext4-crash-poc"

if [ ! -x "$BIN" ]; then
    echo "Binary not found at $BIN -- run 'swift build' first." >&2
    exit 1
fi

images=(
    "poc.img:Bug 1 - getExtents entries overflow (file inode)"
    "poc_root_construction.img:Bug 1 - getExtents entries overflow (root inode, crashes on open)"
    "poc_depth1.img:Bug 1b - getExtents depth==1 index-node branch, same overflow one level down"
    "poc_dirbug_recordlength.img:Bug 2a - getDirEntries record-length gap"
    "poc_dirbug_namelength.img:Bug 2b - getDirEntries nameLength gap"
)

echo "======================================================================"
for entry in "${images[@]}"; do
    img="${entry%%:*}"
    desc="${entry#*:}"
    echo
    echo "--- $img ($desc) ---"
    "$BIN" "$img"
    status=$?
    if [ $status -eq 0 ]; then
        echo "RESULT: FAIL (exited cleanly -- did not crash, this path may not be reachable/fixed)"
    else
        echo "RESULT: PASS (crashed as expected, exit status $status)"
    fi
done
echo
echo "======================================================================"
echo "Done. PASS = the code path crashed the process, confirming the bug."
