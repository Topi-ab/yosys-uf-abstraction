#!/bin/bash
# Prints a short hash of everything that determines the toolchain image: the commits of
# the built submodules and the build/packaging files. CI uses it as the image tag, so the
# toolchain is rebuilt only when one of these inputs changes.
set -euo pipefail
cd "$(dirname "$0")/.."
{
    git ls-files -s ext/ghdl ext/ghdl-yosys-plugin ext/yosys ext/sby ext/yices2 ext/z3 ext/bitwuzla \
        | awk '{print $2, $4}'
    for f in scripts/build-all.sh docker/Dockerfile.builder docker/Dockerfile.runtime; do
        echo "$(git hash-object "$f") $f"
    done
} | sha256sum | cut -c1-16
