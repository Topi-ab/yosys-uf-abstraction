# Build environment only: no sources baked in.
# Sources live on the host in ext/ and are bind-mounted at build time.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential clang bison flex gawk gperf git make cmake pkg-config \
      autoconf automake libtool \
      libreadline-dev tcl-dev libffi-dev zlib1g-dev libgmp-dev libboost-system-dev \
      libboost-python-dev libboost-filesystem-dev \
      gnat gnat-13 \
      python3 python3-dev python3-setuptools python3-click \
      ccache ca-certificates xz-utils \
      libmpfr-dev meson ninja-build python3-pyparsing python3-tomli python3-venv m4 \
 && rm -rf /var/lib/apt/lists/*

# compiler_check=content: the compiler's mtime is not stable inside the container,
# so the default (mtime) is unusable for hashing. A content hash is stable
# across the same compiler version.
ENV PATH=/usr/lib/ccache:$PATH \
    CCACHE_DIR=/ccache \
    CCACHE_MAXSIZE=5G \
    CCACHE_COMPILERCHECK=content
RUN mkdir -p /ccache && chmod 777 /ccache
WORKDIR /src
