"""Read a PS1 disc image: SYSTEM.CNF, the BOOT executable and its PS-X EXE header.

Read-only. Supports raw 2352-byte sector images (.bin/.img, MODE1 or MODE2)
and cooked 2048-byte images (.iso). CHD is not parsed here (psxrecomp reads
it itself); for a .chd only the file name is reported.
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field

SECTOR = 2048
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


class DiscError(Exception):
    pass


class Image:
    def __init__(self, path: str):
        self.path = path
        self.f = open(path, "rb")
        self.size = os.path.getsize(path)
        head = self.f.read(16)
        self.raw = head[:12] == SYNC
        self.stride = 2352 if self.raw else 2048
        self.offset = 0
        if self.raw:
            self.offset = 24 if head[15] == 2 else 16

    def close(self) -> None:
        self.f.close()

    def read(self, lba: int, count: int = 1) -> bytes:
        out = bytearray()
        for i in range(count):
            self.f.seek((lba + i) * self.stride + self.offset)
            out += self.f.read(SECTOR)
        return bytes(out)


def _dir_entries(img: Image, lba: int, size: int):
    data = img.read(lba, (size + SECTOR - 1) // SECTOR)
    pos = 0
    while pos < len(data):
        ln = data[pos]
        if ln == 0:
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        rec = data[pos:pos + ln]
        if len(rec) < 34:
            break
        ext_lba = struct.unpack_from("<I", rec, 2)[0]
        ext_size = struct.unpack_from("<I", rec, 10)[0]
        is_dir = bool(rec[25] & 2)
        nlen = rec[32]
        name = rec[33:33 + nlen].decode("latin-1")
        yield name, ext_lba, ext_size, is_dir
        pos += ln


def _root(img: Image):
    pvd = img.read(16)
    if pvd[1:6] != b"CD001":
        raise DiscError("not an ISO9660 data track (no CD001 at sector 16)")
    root = pvd[156:156 + 34]
    return struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]


def read_file(img: Image, name: str) -> bytes | None:
    """Read a file by path (e.g. 'SYSTEM.CNF' or 'EXE\\MAIN.EXE'), case-insensitive."""
    lba, size = _root(img)
    parts = [p for p in re.split(r"[\\/]", name) if p]
    for i, part in enumerate(parts):
        want = part.upper().split(";")[0]
        found = None
        for n, elba, esize, is_dir in _dir_entries(img, lba, size):
            if n.upper().split(";")[0] == want and is_dir == (i < len(parts) - 1):
                found = (elba, esize)
                break
        if found is None:
            return None
        lba, size = found
    return img.read(lba, (size + SECTOR - 1) // SECTOR)[:size]


def parse_system_cnf(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def boot_path(cnf: dict) -> str | None:
    m = re.search(r"cdrom0?:\\?\\?([^;\s]+)", cnf.get("BOOT", ""), re.I)
    return m.group(1).lstrip("\\") if m else None


def serial_from_boot(boot: str) -> str | None:
    """SCES_008.91 -> SCES-00891 (the usual PS1 boot-file naming)."""
    base = re.split(r"[\\/]", boot)[-1].upper().split(";")[0]
    m = re.match(r"^([A-Z]{4})[_-](\d{3})\.(\d{2})$", base)
    return f"{m.group(1)}-{m.group(2)}{m.group(3)}" if m else None


REGIONS = {"SCES": "PAL", "SLES": "PAL", "SCED": "PAL", "SLED": "PAL",
           "SCUS": "NTSC-U", "SLUS": "NTSC-U", "PAPX": "NTSC-J",
           "SCPS": "NTSC-J", "SLPS": "NTSC-J", "SLPM": "NTSC-J", "SIPS": "NTSC-J"}


@dataclass
class ExeHeader:
    entry_pc: int
    gp0: int
    load_address: int
    text_size: int
    stack_base: int
    marker: str

    def as_dict(self) -> dict:
        return {"entry_pc": f"0x{self.entry_pc:08X}", "gp0": f"0x{self.gp0:08X}",
                "load_address": f"0x{self.load_address:08X}", "text_size": f"0x{self.text_size:08X}",
                "stack_base": f"0x{self.stack_base:08X}", "region_marker": self.marker}


def parse_exe_header(hdr: bytes) -> ExeHeader | None:
    if len(hdr) < 0x80 or hdr[:8] != b"PS-X EXE":
        return None
    pc0, gp0, t_addr, t_size, _d, _ds, _b, _bs, s_addr, _ss = struct.unpack_from("<10I", hdr, 0x10)
    marker = hdr[0x4C:0x80].split(b"\x00")[0].decode("latin-1", "replace")
    return ExeHeader(pc0, gp0, t_addr, t_size, s_addr, marker)


@dataclass
class DiscInfo:
    image: str
    sector_format: str
    boot: str
    serial: str | None
    region: str | None
    exe: ExeHeader
    system_cnf: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"image": os.path.basename(self.image), "sector_format": self.sector_format,
                "boot_file": self.boot, "serial": self.serial, "region": self.region,
                "system_cnf": self.system_cnf, "exe_header": self.exe.as_dict()}


def probe(data_track: str) -> DiscInfo:
    """Probe the first data track (a .bin/.img/.iso file)."""
    img = Image(data_track)
    try:
        cnf_raw = read_file(img, "SYSTEM.CNF")
        if cnf_raw is not None:
            cnf = parse_system_cnf(cnf_raw.decode("latin-1"))
            boot = boot_path(cnf)
            if not boot:
                raise DiscError("SYSTEM.CNF has no BOOT line")
        else:
            # Very early titles boot PSX.EXE without a SYSTEM.CNF.
            cnf, boot = {}, "PSX.EXE"
        exe = read_file(img, boot)
        if exe is None:
            raise DiscError(f"BOOT target {boot} not found on the disc")
        hdr = parse_exe_header(exe[:2048])
        if hdr is None:
            raise DiscError(f"{boot} has no PS-X EXE header")
        serial = serial_from_boot(boot)
        return DiscInfo(data_track, "raw 2352" if img.raw else "cooked 2048", boot, serial,
                        REGIONS.get(serial[:4]) if serial else None, hdr, cnf)
    finally:
        img.close()
