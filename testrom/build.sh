#!/usr/bin/env bash
# Builds the test ROM and a disc zip: testrom/build/PS1 Test ROM.zip
# Needs a MIPS little-endian GCC (Debian/Ubuntu: apt install gcc-mipsel-linux-gnu).
set -euo pipefail
cd "$(dirname "$0")"
CROSS=${CROSS:-mipsel-linux-gnu-}
mkdir -p build
CFLAGS="-march=r3000 -mabi=32 -mno-abicalls -fno-pic -G0 -msoft-float -mno-llsc -O2 -ffreestanding -fno-builtin -nostdlib -Wall -Wextra -Werror"
${CROSS}gcc $CFLAGS -c crt0.S -o build/crt0.o
${CROSS}gcc $CFLAGS -c main.c -o build/main.o
${CROSS}ld -T ps1.ld -nostdlib --no-warn-rwx-segments -o build/main.elf build/crt0.o build/main.o
${CROSS}objcopy -O binary build/main.elf build/main.bin
python3 mkdisc.py --bin build/main.bin --entry "0x$(${CROSS}nm build/main.elf | awk '$3=="_start"{print $1}')" \
    --out build --name "PS1 Test ROM"
