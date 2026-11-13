"""Tests for the universal player's on-device code: the C disc probe
(ios/src/disc_probe.c) and the game.toml rewrite (ios/src/game_config.cpp),
compiled with the host compilers and run on synthetic discs."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
SRC = os.path.join(ROOT, "ios", "src")
CC = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
CXX = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")

from test_ps1ios import make_iso, psx_disc, to_raw  # noqa: E402
from ps1ios.disc import probe  # noqa: E402

TOML = '''[game]
name = "PS1 Test"
id = "HBRW-00001"
players = 1
exe = "disc/HBRW_000.01"
disc = "disc/PS1 Test ROM.cue"
load_address = "0x80010000"
entry_pc = "0x80010000"
text_size = "0x00001000"

[recompiler]
seeds = "seeds/ghidra_funcs.txt"

[prepare_disc]
known_sha1 = ["abc"]

[netplay]
require_cue = true

[video]
renderer = "software"
'''


@unittest.skipUnless(CC and CXX, "no C/C++ compiler")
class UniversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.probe = os.path.join(d, "probe")
        cls.patch = os.path.join(d, "patch")
        obj = os.path.join(d, "disc_probe.o")
        subprocess.run([CC, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-I", SRC, "-c",
                        os.path.join(SRC, "disc_probe.c"), "-o", obj], check=True)
        subprocess.run([CC, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-I", SRC,
                        os.path.join(ROOT, "tests", "disc_probe_harness.c"), obj, "-o", cls.probe], check=True)
        subprocess.run([CXX, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", SRC,
                        os.path.join(ROOT, "tests", "game_config_harness.cpp"),
                        os.path.join(SRC, "game_config.cpp"), obj, "-o", cls.patch], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def write(self, name, data):
        p = os.path.join(self.tmp.name, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def c_probe(self, path):
        r = subprocess.run([self.probe, path], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout)

    def test_matches_python_probe(self):
        cases = [("a.bin", to_raw(psx_disc("SLUS_005.94", 0x80012340, 0x80010000))),
                 ("b.iso", psx_disc("SCES_008.91", 0x80013710, 0x80010000)),
                 ("c.bin", to_raw(psx_disc("SLPS_012.34", 0x80180000, 0x80180000)))]
        for name, data in cases:
            path = self.write(name, data)
            rc, j = self.c_probe(path)
            py = probe(path)
            self.assertEqual(rc, 0, name)
            self.assertEqual(j["boot"], py.boot)
            self.assertEqual(j["serial"], py.serial)
            self.assertEqual(j["entry_pc"], py.exe.entry_pc)
            self.assertEqual(j["load_address"], py.exe.load_address)
            self.assertEqual(j["text_size"], py.exe.text_size)
            self.assertEqual(j["stack_base"], py.exe.stack_base)

    def test_cue_resolves_track(self):
        self.write("Game (Disc 1).bin", to_raw(psx_disc("SLUS_000.67")))
        cue = self.write("Game (Disc 1).cue",
                         b'FILE "Game (Disc 1).bin" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n')
        rc, j = self.c_probe(cue)
        self.assertEqual((rc, j["serial"]), (0, "SLUS-00067"))

    def test_psx_exe_without_system_cnf(self):
        import struct
        hdr = bytearray(2048)
        hdr[0:8] = b"PS-X EXE"
        struct.pack_into("<10I", hdr, 0x10, 0x80010100, 0, 0x80010000, 0x800, 0, 0, 0, 0, 0x801FFFF0, 0)
        path = self.write("old.iso", make_iso({"PSX.EXE": bytes(hdr) + bytes(0x800)}))
        rc, j = self.c_probe(path)
        self.assertEqual((rc, j["boot"], j["serial"], j["entry_pc"]), (0, "PSX.EXE", "", 0x80010100))

    def test_rejects_non_disc(self):
        rc, j = self.c_probe(self.write("junk.bin", os.urandom(40000)))
        self.assertEqual((rc, j["ok"]), (1, 0))

    def test_game_toml_rewrite(self):
        disc = self.write("other.bin", to_raw(psx_disc("SLUS_005.94", 0x80012340, 0x80010000)))
        out = subprocess.run([self.patch, disc, "disc/Other Game.cue"], input=TOML, capture_output=True,
                             text=True, check=True).stdout
        for want in ('id = "SLUS-00594"', 'exe = "disc/SLUS_005.94"', 'disc = "disc/Other Game.cue"',
                     'entry_pc = "0x80012340"', 'load_address = "0x80010000"', 'players = 1',
                     '[video]\nrenderer = "software"', '[recompiler]'):
            self.assertIn(want, out)
        for gone in ("HBRW", "prepare_disc", "netplay", "known_sha1", "PS1 Test ROM"):
            self.assertNotIn(gone, out)
        self.assertEqual(out.count("[game]"), 1)
        self.assertEqual(out.count("entry_pc"), 1)


if __name__ == "__main__":
    unittest.main()
