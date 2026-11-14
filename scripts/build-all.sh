#!/bin/bash
# Builds the toolchain. Normally run inside the builder container (./build.sh,
# /src = repo root). EXT, PREFIX and JOBS can be set in the environment; EXT
# defaults to the repo's ext/ directory, located relative to this script.
set -euo pipefail

# Install prefix is identical at build time and run time (ext/_install is
# bind-mounted at /opt/toolchain), so baked-in paths such as GHDL's library
# directory stay valid inside the runtime image.
PREFIX=${PREFIX:-/opt/toolchain}
JOBS=${JOBS:-$(nproc)}
EXT=${EXT:-$(cd "$(dirname "$0")/.." && pwd)/ext}
export PATH=/usr/lib/ccache:$PREFIX/bin:$PATH
export PKG_CONFIG_PATH=$PREFIX/lib/pkgconfig:${PKG_CONFIG_PATH:-}
export LD_LIBRARY_PATH=$PREFIX/lib:${LD_LIBRARY_PATH:-}

mkdir -p "$PREFIX"
only=${1:-all}
want() { [ "$only" = all ] || [ "$only" = "$1" ]; }
step() { echo; echo "=== $* ==="; }

if want yosys; then
  step "yosys"
  mkdir -p "$EXT/_build/yosys"
  cmake -S "$EXT/yosys" -B "$EXT/_build/yosys" \
      -DCMAKE_INSTALL_PREFIX="$PREFIX" \
      -DCMAKE_BUILD_TYPE=Release \
      -DYOSYS_COMPILER_LAUNCHER=ccache \
      -DYOSYS_ENABLE_UNIT_TESTS=OFF \
      -DYOSYS_INSTALL_LIBRARY=ON
  cmake --build "$EXT/_build/yosys" -j"$JOBS"
  cmake --install "$EXT/_build/yosys"
fi

if want ghdl; then
  step "ghdl (mcode)"
  mkdir -p "$EXT/_build/ghdl"
  cd "$EXT/_build/ghdl"
  [ -f Makefile ] || "$EXT/ghdl/configure" --prefix="$PREFIX" --enable-synth
  # GNAT compiles the Ada part with gnatmake, which ignores make -j; give it its own -j.
  make -j"$JOBS" GNATMAKE="gnatmake -j$JOBS"
  make install
  # libghdl needed by the yosys plugin
  make -C "$EXT/_build/ghdl" install || true
fi

if want ghdl-plugin; then
  step "ghdl-yosys-plugin"
  make -C "$EXT/ghdl-yosys-plugin" -j"$JOBS" \
      GHDL="$PREFIX/bin/ghdl" \
      GHDL_LIBDIR="$PREFIX/lib" \
      YOSYS_CONFIG="$PREFIX/bin/yosys-config"
  make -C "$EXT/ghdl-yosys-plugin" \
      YOSYS_CONFIG="$PREFIX/bin/yosys-config" install
fi

if want yices; then
  step "yices2"
  cd "$EXT/yices2"
  [ -f configure ] || autoconf
  [ -f config.status ] || ./configure --prefix="$PREFIX"
  make -j"$JOBS"
  make install
fi

if want z3; then
  step "z3"
  mkdir -p "$EXT/_build/z3"
  cd "$EXT/_build/z3"
  [ -f Makefile ] || cmake -DCMAKE_INSTALL_PREFIX="$PREFIX" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
        -DZ3_BUILD_LIBZ3_SHARED=ON -DZ3_BUILD_PYTHON_BINDINGS=OFF \
        "$EXT/z3"
  cmake --build . -j"$JOBS"
  cmake --install .
fi

if want bitwuzla; then
  step "bitwuzla"
  # meson + ninja, with CaDiCaL as the SAT backend. The dependencies (cadical,
  # symfpu) are fetched by meson wraps into ext/bitwuzla/subprojects/ (needs
  # network access). ccache comes from PATH (/usr/lib/ccache); meson also
  # detects it by itself.
  cd "$EXT/bitwuzla"
  ./configure.py release --prefix "$PREFIX" -b "$EXT/_build/bitwuzla"
  meson compile -C "$EXT/_build/bitwuzla" -j "$JOBS"
  meson install -C "$EXT/_build/bitwuzla"
fi

if want sby; then
  step "sby"
  make -C "$EXT/sby" install PREFIX="$PREFIX"
fi

# License files of every built component, shipped with the binaries (GHDL is
# GPL-2.0-or-later, ghdl-yosys-plugin and Yices are GPL-3.0-or-later, Yosys and
# SymbiYosys are ISC, Z3 and Bitwuzla are MIT).
for repo in ghdl ghdl-yosys-plugin yosys sby yices2 z3 bitwuzla; do
  [ -d "$EXT/$repo" ] || continue
  dst="$PREFIX/share/licenses/$repo"
  mkdir -p "$dst"
  for f in "$EXT/$repo"/LICENSE* "$EXT/$repo"/COPYING* "$EXT/$repo"/COPYRIGHT*; do
    [ -f "$f" ] && cp "$f" "$dst/"
  done
done

echo
echo "=== done -> $PREFIX ==="
ls "$PREFIX/bin"
