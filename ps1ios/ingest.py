"""Take a .zip of a PS1 game and find the disc image inside it.

Accepted inside the zip (any folder depth):
  .cue + its .bin tracks (preferred, Redump style; multi-track kept)
  .chd
  a lone .bin / .img (raw 2352) -> a cue sheet is written for it
  .iso (cooked 2048) -> used as is; CD audio and XA may be missing
Rejected with a message: .pbp (PSN EBOOT), .ecm, nested archives.
Multi-disc sets: every disc is kept; disc 1 is built and the rest are listed.

Extraction is defensive: no absolute paths, no '..', no links, size caps.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass, field

MAX_TOTAL = 3 * 1024 ** 3      # 3 GB uncompressed
MAX_FILES = 512
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


class IngestError(Exception):
    pass


@dataclass
class Disc:
    label: str           # e.g. "Disc 1"
    entry: str           # path given to psxrecomp (.cue / .chd / .iso)
    data_track: str      # first data track (for probing); "" for .chd
    generated_cue: bool = False


@dataclass
class Ingested:
    root: str
    discs: list[Disc] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def primary(self) -> Disc:
        return self.discs[0]


def safe_extract(zip_path: str, dest: str) -> list[str]:
    if not zipfile.is_zipfile(zip_path):
        raise IngestError(f"{zip_path} is not a zip file")
    os.makedirs(dest, exist_ok=True)
    real_dest = os.path.realpath(dest)
    out = []
    with zipfile.ZipFile(zip_path) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES:
            raise IngestError(f"zip has {len(infos)} files (limit {MAX_FILES})")
        if sum(i.file_size for i in infos) > MAX_TOTAL:
            raise IngestError("zip expands to more than 3 GB")
        for i in infos:
            name = i.filename.replace("\\", "/")
            mode = (i.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise IngestError(f"zip contains a link: {name}")
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                raise IngestError(f"unsafe path in zip: {name}")
            target = os.path.realpath(os.path.join(dest, name))
            if not target.startswith(real_dest + os.sep):
                raise IngestError(f"unsafe path in zip: {name}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(i) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            out.append(target)
    return out


def _cue_files(cue: str) -> list[str]:
    with open(cue, encoding="latin-1") as f:
        txt = f.read()
    return re.findall(r'^\s*FILE\s+"?(.+?)"?\s+(?:BINARY|MOTOROLA|WAVE|MP3|AIFF)\s*$', txt, re.M | re.I)


def _fix_cue_case(cue: str) -> list[str]:
    """Resolve FILE entries case-insensitively (zips made on Windows); rewrite the cue if needed."""
    d = os.path.dirname(cue)
    present = {n.lower(): n for n in os.listdir(d)}
    with open(cue, encoding="latin-1") as f:
        txt = f.read()
    tracks, changed = [], False
    for name in _cue_files(cue):
        base = os.path.basename(name.replace("\\", "/"))
        real = present.get(base.lower())
        if real is None:
            raise IngestError(f"{os.path.basename(cue)} lists {base}, which is not in the zip")
        if real != name:
            txt = txt.replace(name, real)
            changed = True
        tracks.append(os.path.join(d, real))
    if changed:
        with open(cue, "w", encoding="latin-1") as f:
            f.write(txt)
    return tracks


def _write_cue(bin_path: str) -> str:
    with open(bin_path, "rb") as f:
        head = f.read(16)
    if head[:12] != SYNC:
        raise IngestError(f"{os.path.basename(bin_path)} is not a raw 2352-byte image and has no .cue")
    mode = "MODE2/2352" if head[15] == 2 else "MODE1/2352"
    cue = os.path.splitext(bin_path)[0] + ".cue"
    with open(cue, "w", encoding="latin-1") as f:
        f.write(f'FILE "{os.path.basename(bin_path)}" BINARY\n  TRACK 01 {mode}\n    INDEX 01 00:00:00\n')
    return cue


_DISC_RE = re.compile(r"\(\s*dis[ck]\s*(\d+)", re.I)


def _disc_no(path: str) -> int:
    m = _DISC_RE.search(os.path.basename(path))
    return int(m.group(1)) if m else 1


def ingest(zip_path: str, dest: str) -> Ingested:
    files = safe_extract(zip_path, dest)
    res = Ingested(dest)
    by_ext: dict[str, list[str]] = {}
    for p in files:
        by_ext.setdefault(os.path.splitext(p)[1].lower(), []).append(p)
    for bad, why in ((".pbp", "PSN EBOOT (.pbp) is not supported: use the original disc dump (cue/bin)"),
                     (".ecm", ".ecm images must be unpacked (unecm) first"),
                     (".7z", "nested archives are not supported"), (".rar", "nested archives are not supported"),
                     (".zip", "nested archives are not supported")):
        if by_ext.get(bad) and not any(by_ext.get(e) for e in (".cue", ".chd", ".bin", ".img", ".iso")):
            raise IngestError(why)
    used: set[str] = set()
    discs: list[Disc] = []
    for cue in sorted(by_ext.get(".cue", [])):
        tracks = _fix_cue_case(cue)
        used.update(os.path.realpath(t) for t in tracks)
        discs.append(Disc("", cue, tracks[0] if tracks else ""))
    for chd in sorted(by_ext.get(".chd", [])):
        discs.append(Disc("", chd, ""))
    for b in sorted(by_ext.get(".bin", []) + by_ext.get(".img", [])):
        if os.path.realpath(b) in used:
            continue
        try:
            cue = _write_cue(b)
        except IngestError as e:
            res.warnings.append(str(e))
            continue
        discs.append(Disc("", cue, b, generated_cue=True))
        res.warnings.append(f"no .cue for {os.path.basename(b)}: wrote one (single data track; CD-DA music tracks would be missing)")
    for iso in sorted(by_ext.get(".iso", [])):
        discs.append(Disc("", iso, iso))
        res.warnings.append(f"{os.path.basename(iso)} is a cooked 2048-byte image: XA audio and videos may not play; a cue/bin dump is better")
    if not discs:
        raise IngestError("no PS1 disc image (.cue/.bin, .chd, .img, .iso) found in the zip")
    discs.sort(key=lambda d: (_disc_no(d.entry), d.entry))
    for d in discs:
        d.label = f"Disc {_disc_no(d.entry)}"
    if len(discs) > 1:
        res.warnings.append("multi-disc set: " + ", ".join(f"{d.label}={os.path.basename(d.entry)}" for d in discs)
                            + f"; building from {os.path.basename(discs[0].entry)}, the others are copied to the phone too")
    res.discs = discs
    return res
