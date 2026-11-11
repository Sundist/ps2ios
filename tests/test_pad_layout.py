"""Tests for the touch pad layout and hit testing (ios/src/pad_layout.c).

Compiles pad_layout.c with the host C compiler, so the code under test is the
exact code the iOS app runs.
"""
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ios", "src")
CC = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")

U, D, L, R = 1, 2, 4, 8
CROSS, CIRCLE, SQUARE, TRIANGLE = 16, 32, 64, 128
L1, L2, R1, R2, SELECT, START = 256, 512, 1024, 2048, 4096, 8192

# (name, width, height, safe left, right, top, bottom) in landscape points
PHONES = [
    ("iPhone 13 Pro Max", 926, 428, 47, 47, 0, 21),
    ("iPhone 15 Pro Max", 932, 430, 59, 59, 0, 21),
    ("iPhone 13 mini", 812, 375, 50, 50, 0, 21),
    ("iPhone SE", 667, 375, 0, 0, 0, 0),
]


@unittest.skipUnless(CC, "no C compiler")
class PadLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.exe = os.path.join(cls.tmp.name, "pad_harness")
        subprocess.run([CC, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-I", SRC,
                        os.path.join(ROOT, "tests", "pad_harness.c"), os.path.join(SRC, "pad_layout.c"),
                        "-lm", "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_pad(self, screen, scale=1.0, points=()):
        _, w, h, sl, sr, st, sb = screen
        args = [self.exe] + [str(v) for v in (w, h, sl, sr, st, sb, scale)]
        stdin = "".join(f"{x} {y}\n" for x, y in points)
        out = subprocess.run(args, input=stdin, capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    @staticmethod
    def rect(c):
        return (c["cx"] - c["w"] / 2, c["cy"] - c["h"] / 2, c["cx"] + c["w"] / 2, c["cy"] + c["h"] / 2)

    def test_inside_safe_area_and_clear_of_picture(self):
        for scr in PHONES:
            name, w, h, sl, sr, st, sb = scr
            j = self.run_pad(scr)
            gx0, gx1 = j["game"]
            for c in j["controls"]:
                x0, y0, x1, y1 = self.rect(c)
                self.assertGreaterEqual(x0, sl - 0.01, f"{name} {c['label']} left of safe area")
                self.assertLessEqual(x1, w - sr + 0.01, f"{name} {c['label']} right of safe area")
                self.assertGreaterEqual(y0, st - 0.01, f"{name} {c['label']} above safe area")
                self.assertLessEqual(y1, h - sb + 0.01, f"{name} {c['label']} below safe area")
                # Covered width of the 4:3 picture. Zero where the side strips can
                # hold a 44 pt diamond (108 pt); on narrower phones a little overlap
                # is the price of full-size targets.
                strip = min(gx0 - sl, (w - gx1) - sr) - 8
                cover = max(0.0, min(x1, gx1) - max(x0, gx0))
                if strip >= 108:
                    self.assertEqual(cover, 0, f"{name} {c['label']} covers the game picture")
                else:
                    self.assertLessEqual(cover, 108 - strip + 0.01, f"{name} {c['label']} covers too much")

    def test_targets_big_enough_and_not_overlapping(self):
        for scr in PHONES:
            cs = self.run_pad(scr)["controls"]
            for c in cs:
                self.assertGreaterEqual(min(c["w"], c["h"]), 44 - 0.01, f"{scr[0]} {c['label']} under 44 pt")
            for i, a in enumerate(cs):
                for b in cs[i + 1:]:
                    if a["kind"] == 1 and b["kind"] == 1:   # round: real circles
                        dist = math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])
                        self.assertGreater(dist, a["w"] / 2 + b["w"] / 2, f"{scr[0]} {a['label']}/{b['label']} overlap")
                    else:
                        ax0, ay0, ax1, ay1 = self.rect(a)
                        bx0, by0, bx1, by1 = self.rect(b)
                        overlap = ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1
                        self.assertFalse(overlap, f"{scr[0]} {a['label']}/{b['label']} overlap")

    def test_hits(self):
        scr = PHONES[0]
        cs = {c["label"]: c for c in self.run_pad(scr)["controls"]}
        dp, x, o, sq, tr = cs["D-PAD"], cs["✕"], cs["○"], cs["□"], cs["△"]
        rad = dp["w"] / 2
        at = lambda deg, k=0.8: (dp["cx"] + rad * k * math.cos(math.radians(deg)),
                                 dp["cy"] - rad * k * math.sin(math.radians(deg)))
        pts = [
            (dp["cx"], dp["cy"]),            # dead zone
            at(0), at(90), at(180), at(270),
            at(45), at(135), at(225), at(315),
            at(30),                          # 15° off the diagonal: still a cardinal
            at(0, 1.15),                     # just outside the drawn pad: still captured
            (x["cx"], x["cy"]), (o["cx"], o["cy"]), (sq["cx"], sq["cy"]), (tr["cx"], tr["cy"]),
            ((x["cx"] + sq["cx"]) / 2, (x["cy"] + sq["cy"]) / 2),   # between Cross and Square
            (cs["L2"]["cx"], cs["L2"]["cy"]), (cs["R1"]["cx"], cs["R1"]["cy"]),
            (cs["SELECT"]["cx"], cs["SELECT"]["cy"]), (cs["START"]["cx"], cs["START"]["cy"]),
            (463, 214),                      # middle of the picture
        ]
        hits = self.run_pad(scr, points=pts)["hits"]
        self.assertEqual(hits, [0, R, U, L, D, U | R, U | L, D | L, D | R, R, R,
                                CROSS, CIRCLE, SQUARE, TRIANGLE, CROSS | SQUARE,
                                L2, R1, SELECT, START, 0])

    def test_scale_setting(self):
        small = self.run_pad(PHONES[0], 0.8)["controls"][0]["w"]
        big = self.run_pad(PHONES[0], 1.3)["controls"][0]["w"]
        self.assertLess(small, big)
        for c in self.run_pad(PHONES[0], 1.3)["controls"]:
            x0, y0, x1, y1 = self.rect(c)
            self.assertTrue(0 <= x0 and x1 <= 926 and 0 <= y0 and y1 <= 428, c["label"])


if __name__ == "__main__":
    unittest.main()
