#!/bin/bash
# Run any toolchain binary inside the runtime image, cwd mounted at /work.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
TTY=(); [ -t 0 ] && [ -t 1 ] && TTY=(-it)
exec docker run --rm "${TTY[@]}" -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/work" -w /work yosys-uf/toolchain:latest "$@"
