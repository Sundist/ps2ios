#!/usr/bin/env python3
"""Build a PS-X EXE from a flat binary and a bootable PS1 disc image around it.

  python3 mkdisc.py --bin build/main.bin --entry 0x80010000 --out build/disc --name "PS1 Test"

Writes <out>/<NAME>.bin + .cue (raw MODE2/2352, Mode 2 Form 1 sectors with
EDC/ECC) holding an ISO9660 volume with SYSTEM.CNF and the EXE, and a zip of
both. The system area (sectors 0-15) is left empty: no Sony license data is
included. psxrecomp's CD controller reports the region from SYSTEM.CNF.
"""
import argparse
import os
import struct
import zipfile

SERIAL_FILE = "HBRW_000.01"   # default boot file; homebrew-style name, serial HBRW-00001
LOAD_ADDR = 0x80010000
STACK = 0x801FFFF0

# ---------------------------------------------------------------- EXE


def make_exe(body: bytes, entry: int) -> bytes:
    body = body + bytes((-len(body)) % 2048)
    hdr = bytearray(2048)
    hdr[0:8] = b"PS-X EXE"
    struct.pack_into("<10I", hdr, 0x10, entry, 0, LOAD_ADDR, len(body), 0, 0, 0, 0, STACK, 0)
    marker = b"Sony Computer Entertainment Inc. for North America area"
    hdr[0x4C:0x4C + len(marker)] = marker
    return bytes(hdr) + body

# ---------------------------------------------------------------- EDC / ECC (CD-ROM Mode 2 Form 1)


def _tables():
    f_lut, b_lut, edc = [0] * 256, [0] * 256, [0] * 256
    for i in range(256):
        j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
        f_lut[i] = j
        b_lut[i ^ j] = i
        e = i
        for _ in range(8):
            e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
        edc[i] = e
    return f_lut, b_lut, edc


F_LUT, B_LUT, EDC_LUT = _tables()


def edc(data: bytes) -> int:
    e = 0
    for b in data:
        e = (e >> 8) ^ EDC_LUT[(e ^ b) & 0xFF]
    return e


def _ecc_block(src: bytearray, major_count, minor_count, major_mult, minor_inc, dest: bytearray, dest_off):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = F_LUT[a]
        a = B_LUT[F_LUT[a] ^ b]
        dest[dest_off + major] = a
        dest[dest_off + major + major_count] = a ^ b


def finish_form1(sector: bytearray) -> None:
    struct.pack_into("<I", sector, 0x818, edc(bytes(sector[0x10:0x818])))
    saved = sector[0x0C:0x10]
    sector[0x0C:0x10] = b"\0\0\0\0"            # Mode 2: ECC computed with a zero header
    view = sector[0x0C:]
    _ecc_block(view, 86, 24, 2, 86, view, 0x81C - 0x0C)
    _ecc_block(view, 52, 43, 86, 88, view, 0x8C8 - 0x0C)
    sector[0x0C:] = view
    sector[0x0C:0x10] = saved


def bcd(n):
    return ((n // 10) << 4) | (n % 10)


def raw_sector(lba: int, data: bytes, submode: int) -> bytes:
    s = bytearray(2352)
    s[0:12] = b"\x00" + b"\xff" * 10 + b"\x00"
    a = lba + 150
    s[12:16] = bytes([bcd(a // 4500), bcd(a // 75 % 60), bcd(a % 75), 2])
    s[16:24] = bytes([0, 0, submode, 0, 0, 0, submode, 0])
    s[24:24 + len(data)] = data
    finish_form1(s)
    return bytes(s)

# ---------------------------------------------------------------- ISO9660


def both16(v):
    return struct.pack("<H", v) + struct.pack(">H", v)


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


DATE7 = bytes([126, 1, 1, 0, 0, 0, 0])            # 2026-01-01 00:00:00 GMT
DATE17 = b"2026010100000000\x00"


def dirrec(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    r = bytearray([0, 0]) + both32(lba) + both32(size) + DATE7 + bytes([2 if is_dir else 0, 0, 0]) \
        + both16(1) + bytes([len(name)]) + name
    if len(r) % 2:
        r += b"\0"
    r[0] = len(r)
    return bytes(r)


def pad(s: bytes, n: int) -> bytes:
    return s[:n] + b" " * (n - len(s[:n]))


def build_iso_sectors(files: dict, volume: str):
    """Returns a list of (data, submode) for every 2048-byte sector of the volume."""
    ROOT, LPT, MPT, FIRST = 20, 18, 19, 21
    names = sorted(files)
    lba = FIRST
    placed = []
    for n in names:
        placed.append((n, lba, len(files[n])))
        lba += max(1, (len(files[n]) + 2047) // 2048)
    total = lba + 150                                     # trailing padding
    root = dirrec(b"\0", ROOT, 2048, True) + dirrec(b"\1", ROOT, 2048, True)
    for n, l, sz in placed:
        root += dirrec((n + ";1").encode(), l, sz, False)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[8:40] = pad(b"PLAYSTATION", 32)
    pvd[40:72] = pad(volume.encode(), 32)
    pvd[80:88] = both32(total)
    pvd[120:124] = both16(1)
    pvd[124:128] = both16(1)
    pvd[128:132] = both16(2048)
    pvd[132:140] = both32(10)
    struct.pack_into("<I", pvd, 140, LPT)
    struct.pack_into(">I", pvd, 148, MPT)
    pvd[156:190] = dirrec(b"\0", ROOT, 2048, True)
    for off, n in ((190, 128), (318, 128), (446, 128), (574, 128), (702, 37), (739, 37), (776, 37)):
        pvd[off:off + n] = b" " * n
    pvd[574:574 + 11] = b"PLAYSTATION"
    for off in (813, 830, 847, 864):
        pvd[off:off + 17] = DATE17
    pvd[881] = 1
    term = bytearray(2048)
    term[0] = 255
    term[1:6] = b"CD001"
    term[6] = 1
    lpt = bytes([1, 0]) + struct.pack("<I", ROOT) + struct.pack("<H", 1) + b"\0\0"
    mpt = bytes([1, 0]) + struct.pack(">I", ROOT) + struct.pack(">H", 1) + b"\0\0"

    sectors = [(b"", 0x00)] * 16
    sectors.append((bytes(pvd), 0x09))
    sectors.append((bytes(term), 0x89))
    sectors.append((lpt, 0x89))
    sectors.append((mpt, 0x89))
    sectors.append((root, 0x89))
    for n, l, sz in placed:
        data = files[n]
        count = max(1, (sz + 2047) // 2048)
        for i in range(count):
            sectors.append((data[i * 2048:(i + 1) * 2048], 0x89 if i == count - 1 else 0x08))
    while len(sectors) < total:
        sectors.append((b"", 0x00))
    return sectors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True, help="flat binary linked at 0x80010000")
    ap.add_argument("--entry", default="0x80010000")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="PS1 Test ROM")
    ap.add_argument("--boot", default=SERIAL_FILE, help="boot file name on the disc, e.g. HBRW_000.02")
    a = ap.parse_args()
    with open(a.bin, "rb") as f:
        exe = make_exe(f.read(), int(a.entry, 0))
    cnf = (f"BOOT = cdrom:\\{a.boot};1\r\nTCB = 4\r\nEVENT = 10\r\nSTACK = 801FFFF0\r\n").encode()
    sectors = build_iso_sectors({"SYSTEM.CNF": cnf, a.boot: exe}, "PS1TEST")
    os.makedirs(a.out, exist_ok=True)
    base = a.name
    bin_path = os.path.join(a.out, base + ".bin")
    with open(bin_path, "wb") as f:
        for lba, (data, sub) in enumerate(sectors):
            f.write(raw_sector(lba, data, sub))
    cue_path = os.path.join(a.out, base + ".cue")
    with open(cue_path, "w") as f:
        f.write(f'FILE "{base}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    with open(os.path.join(a.out, base + ".exe"), "wb") as f:
        f.write(exe)
    zip_path = os.path.join(a.out, base + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(cue_path, base + "/" + base + ".cue")
        z.write(bin_path, base + "/" + base + ".bin")
    print(zip_path)


if __name__ == "__main__":
    main()
