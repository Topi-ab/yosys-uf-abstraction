#!/bin/bash
# Host entry point. Everything compiles inside Docker; nothing is built on the host.
# Usage: ./build.sh [all|yosys|ghdl|ghdl-plugin|yices|z3|bitwuzla|sby|shell|image]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
BUILDER_IMG=yosys-uf/builder:latest
RUNTIME_IMG=yosys-uf/toolchain:latest
target=${1:-all}

docker build -t "$BUILDER_IMG" -f "$ROOT/docker/Dockerfile.builder" "$ROOT/docker"

mkdir -p "$ROOT/ext/_ccache" "$ROOT/ext/_install"
run() {
  docker run --rm -t \
    -u "$(id -u):$(id -g)" \
    -v "$ROOT:/src" \
    -v "$ROOT/ext/_ccache:/ccache" \
    -v "$ROOT/ext/_install:/opt/toolchain" \
    -e CCACHE_DIR=/ccache -e HOME=/tmp \
    -w /src "$BUILDER_IMG" "$@"
}

case "$target" in
  shell) exec docker run --rm -it -u "$(id -u):$(id -g)" -v "$ROOT:/src" \
           -v "$ROOT/ext/_ccache:/ccache" -v "$ROOT/ext/_install:/opt/toolchain" \
           -e CCACHE_DIR=/ccache -e HOME=/tmp \
           -w /src "$BUILDER_IMG" bash ;;
  image) ;;
  *)     run /src/scripts/build-all.sh "$target" ;;
esac

# Package the built binaries into the runtime image (binaries are only ever run in Docker).
docker build -t "$RUNTIME_IMG" -f "$ROOT/docker/Dockerfile.runtime" "$ROOT"
echo "runtime image: $RUNTIME_IMG   (use ./sby.sh / ./tc.sh)"
