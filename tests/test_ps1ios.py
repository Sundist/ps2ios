"""Tests for zip ingestion and disc probing, on synthetic discs (no game data).

    python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ps1ios.disc import probe, serial_from_boot  # noqa: E402
from ps1ios.ingest import IngestError, ingest  # noqa: E402

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


def _both16(v):
    return struct.pack("<H", v) + struct.pack(">H", v)


def _both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def _dirrec(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    body = (_both32(lba) + _both32(size) + bytes(7) + bytes([2 if is_dir else 0, 0, 0])
            + _both16(1) + bytes([len(name)]) + name)
    rec = bytes([0, 0]) + body
    if len(rec) % 2:
        rec += b"\0"
    return bytes([len(rec)]) + rec[1:]


def make_iso(files: dict) -> bytes:
    """Minimal ISO9660: PVD at 16, root dir at 18, files from 19 on."""
    sectors = {}
    lba = 19
    entries = []
    for name, data in files.items():
        n = (len(data) + 2047) // 2048 or 1
        sectors[lba] = data
        entries.append((name.encode() + b";1", lba, len(data)))
        lba += n
    root = _dirrec(b"\0", 18, 2048, True) + _dirrec(b"\1", 18, 2048, True)
    for name, l, s in entries:
        root += _dirrec(name, l, s, False)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[80:88] = _both32(lba)
    pvd[156:156 + 34] = _dirrec(b"\0", 18, 2048, True)
    img = bytearray(lba * 2048)
    img[16 * 2048:17 * 2048] = pvd
    img[17 * 2048] = 255
    img[17 * 2048 + 1:17 * 2048 + 6] = b"CD001"
    img[18 * 2048:18 * 2048 + len(root)] = root
    for l, data in sectors.items():
        img[l * 2048:l * 2048 + len(data)] = data
    return bytes(img)


def psx_disc(boot="SCES_008.91", entry=0x80013710, load=0x80010000) -> bytes:
    cnf = f"BOOT = cdrom:\\{boot};1\r\nTCB = 4\r\nEVENT = 10\r\nSTACK = 801FFFF0\r\n".encode()
    hdr = bytearray(2048)
    hdr[0:8] = b"PS-X EXE"
    struct.pack_into("<10I", hdr, 0x10, entry, 0, load, 0x800, 0, 0, 0, 0, 0x801FFFF0, 0)
    hdr[0x4C:0x4C + 26] = b"Sony Computer Entertainment"[:26]
    return make_iso({"SYSTEM.CNF": cnf, boot: bytes(hdr) + bytes(0x800)})


def to_raw(cooked: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(cooked), 2048):
        out += SYNC + b"\0\0\0\x02" + bytes(8) + cooked[i:i + 2048] + bytes(280)
    return bytes(out)


def make_zip(path, members: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


class IngestProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def z(self, members):
        p = os.path.join(self.d, "game.zip")
        make_zip(p, members)
        return p

    def test_cue_bin_nested_case_mismatch(self):
        raw = to_raw(psx_disc())
        zp = self.z({"Hercules/Hercules (Europe).cue": 'FILE "HERCULES (EUROPE).BIN" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n',
                     "Hercules/Hercules (Europe).bin": raw})
        ing = ingest(zp, os.path.join(self.d, "x"))
        self.assertEqual(len(ing.discs), 1)
        self.assertTrue(ing.primary.entry.endswith(".cue"))
        with open(ing.primary.entry) as f:
            self.assertIn('"Hercules (Europe).bin"', f.read())  # cue fixed to real case
        info = probe(ing.primary.data_track)
        self.assertEqual(info.serial, "SCES-00891")
        self.assertEqual(info.region, "PAL")
        self.assertEqual(info.exe.load_address, 0x80010000)
        self.assertEqual(info.exe.entry_pc, 0x80013710)

    def test_lone_bin_gets_cue(self):
        zp = self.z({"game.bin": to_raw(psx_disc("SLUS_005.94", 0x80012000))})
        ing = ingest(zp, os.path.join(self.d, "x"))
        self.assertTrue(ing.primary.generated_cue)
        with open(ing.primary.entry) as f:
            self.assertIn("MODE2/2352", f.read())
        info = probe(ing.primary.data_track)
        self.assertEqual((info.serial, info.region), ("SLUS-00594", "NTSC-U"))
        self.assertEqual(info.exe.entry_pc, 0x80012000)

    def test_iso_warns(self):
        zp = self.z({"g.iso": psx_disc("SLPS_012.34")})
        ing = ingest(zp, os.path.join(self.d, "x"))
        self.assertTrue(any("cooked" in w for w in ing.warnings))
        self.assertEqual(probe(ing.primary.data_track).serial, "SLPS-01234")

    def test_multi_disc_order(self):
        raw = to_raw(psx_disc())
        cue = lambda b: f'FILE "{b}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
        zp = self.z({"G (Disc 2).cue": cue("G (Disc 2).bin"), "G (Disc 2).bin": raw,
                     "G (Disc 1).cue": cue("G (Disc 1).bin"), "G (Disc 1).bin": raw})
        ing = ingest(zp, os.path.join(self.d, "x"))
        self.assertEqual([x.label for x in ing.discs], ["Disc 1", "Disc 2"])
        self.assertIn("Disc 1", ing.primary.entry)

    def test_rejects_zip_slip(self):
        zp = self.z({"../evil.bin": b"x"})
        with self.assertRaises(IngestError):
            ingest(zp, os.path.join(self.d, "x"))

    def test_rejects_pbp_and_empty(self):
        with self.assertRaises(IngestError):
            ingest(self.z({"EBOOT.PBP": b"\0PBP"}), os.path.join(self.d, "x"))
        with self.assertRaises(IngestError):
            ingest(self.z({"readme.txt": b"hi"}), os.path.join(self.d, "y"))

    def test_cue_missing_track(self):
        zp = self.z({"a.cue": 'FILE "a.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'})
        with self.assertRaises(IngestError):
            ingest(zp, os.path.join(self.d, "x"))

    def test_serial_parse(self):
        self.assertEqual(serial_from_boot("SCUS_944.26"), "SCUS-94426")
        self.assertIsNone(serial_from_boot("PSX.EXE"))

    def test_cli_inspect_curated_and_generic(self):
        zp = self.z({"h.bin": to_raw(psx_disc())})
        out = subprocess.run([sys.executable, "-m", "ps1ios", "inspect", zp], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        j = json.loads(out.stdout)
        self.assertEqual(j["project"]["kind"], "curated")
        zp2 = os.path.join(self.d, "o.zip")
        make_zip(zp2, {"o.bin": to_raw(psx_disc("SLUS_000.67"))})
        j2 = json.loads(subprocess.run([sys.executable, "-m", "ps1ios", "inspect", zp2], cwd=ROOT,
                                       capture_output=True, text=True).stdout)
        self.assertEqual(j2["project"]["kind"], "generic")

    @unittest.skipIf(sys.platform == "darwin", "Mac check only meaningful off macOS")
    def test_build_fails_cleanly_without_xcode(self):
        zp = self.z({"h.bin": to_raw(psx_disc())})
        r = subprocess.run([sys.executable, "-m", "ps1ios", "build", zp, "--team", "X", "--work",
                            os.path.join(self.d, "w")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        first = json.loads(r.stdout.splitlines()[0])
        self.assertEqual((first["ev"], first["k"], first["n"]), ("stage", 1, 9))
        self.assertIn("xcodebuild", r.stderr)


if __name__ == "__main__":
    unittest.main()
