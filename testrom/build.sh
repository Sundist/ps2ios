#!/usr/bin/env bash
# Builds the test ROMs and their disc zips: testrom/build/PS1 Test ROM.zip and "PS1 Test ROM B.zip"
# Needs a MIPS little-endian GCC (Debian/Ubuntu: apt install gcc-mipsel-linux-gnu).
set -euo pipefail
cd "$(dirname "$0")"
CROSS=${CROSS:-mipsel-linux-gnu-}
mkdir -p build
CFLAGS="-march=r3000 -mabi=32 -mno-abicalls -fno-pic -G0 -msoft-float -mno-llsc -O2 -ffreestanding -fno-builtin -nostdlib -Wall -Wextra -Werror"
${CROSS}gcc $CFLAGS -c crt0.S -o build/crt0.o

# build <variant> <boot file> <disc name>
build() {
  ${CROSS}gcc $CFLAGS -DVARIANT=$1 -c main.c -o build/main$1.o
  ${CROSS}ld -T ps1.ld -nostdlib --no-warn-rwx-segments -o build/main$1.elf build/crt0.o build/main$1.o
  ${CROSS}objcopy -O binary build/main$1.elf build/main$1.bin
  python3 mkdisc.py --bin build/main$1.bin --entry "0x$(${CROSS}nm build/main$1.elf | awk '$3=="_start"{print $1}')" \
      --out build --name "$3" --boot "$2"
}
build 1 HBRW_000.01 "PS1 Test ROM"      # the disc the test app is built from
build 2 HBRW_000.02 "PS1 Test ROM B"    # a different game, for the universal player test
