#!/bin/bash
# Run any toolchain binary inside the runtime image, cwd mounted at /work.
# TC_IMAGE selects the image (default: the locally built yosys-uf/toolchain:latest), e.g.
#   TC_IMAGE=ghcr.io/topi-ab/yosys-uf-abstraction:v0.1.1 ./tc.sh yosys -V
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
TTY=(); [ -t 0 ] && [ -t 1 ] && TTY=(-it)
exec docker run --rm "${TTY[@]}" -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work "${TC_IMAGE:-yosys-uf/toolchain:latest}" "$@"
