#!/usr/bin/env python3
"""Draw the touch pad layout from ios/src/pad_layout.c itself (compiled with
the host C compiler), in the overlay's drawing style. This is a layout drawing,
not a screenshot: the picture area is an empty placeholder.

  python3 tools/render_pad_layout.py docs/touch-layout.png [--pressed]
Needs: a C compiler and Pillow.
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ios", "src")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--screen", default="926,428,47,47,0,21", help="w,h,safeL,safeR,safeT,safeB (default iPhone 13 Pro Max)")
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--pressed", action="store_true", help="show Right+Up on the d-pad and Cross+Square held")
a = ap.parse_args()

cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
with tempfile.TemporaryDirectory() as t:
    exe = os.path.join(t, "pad")
    subprocess.run([cc, "-std=c99", "-O1", "-I", SRC, os.path.join(ROOT, "tests", "pad_harness.c"),
                    os.path.join(SRC, "pad_layout.c"), "-lm", "-o", exe], check=True)
    w, h, sl, sr, st, sb = [float(v) for v in a.screen.split(",")]
    lay = json.loads(subprocess.run([exe, *a.screen.split(","), str(a.scale)], input="",
                                    capture_output=True, text=True, check=True).stdout)

held = (1 | 8 | 16 | 64) if a.pressed else 0
SC, PAD = 3, 40
W, H = int(w), int(h)
img = Image.new("RGBA", ((W + 2 * PAD) * SC, (H + 2 * PAD) * SC), (235, 236, 240, 255))
d = ImageDraw.Draw(img)
ox = oy = PAD * SC
d.rounded_rectangle([ox - 14 * SC, oy - 14 * SC, ox + (W + 14) * SC, oy + (H + 14) * SC], radius=62 * SC, fill=(28, 28, 32))
screen = Image.new("RGBA", (W * SC, H * SC), (0, 0, 0, 0))
sd = ImageDraw.Draw(screen)
for y in range(H * SC):
    k = y / (H * SC)
    sd.line([(0, y), (W * SC, y)], fill=(int(52 + 30 * k), int(66 + 24 * k), int(92 + 10 * k), 255))
gx0, gx1 = lay["game"]
sd.rectangle([gx0 * SC, 0, gx1 * SC, H * SC], outline=(255, 255, 255, 60), width=2 * SC)
sd.rectangle([sl * SC, st * SC, (W - sr) * SC, (H - sb) * SC], outline=(255, 210, 90, 80), width=SC)

ov = Image.new("RGBA", screen.size, (0, 0, 0, 0))
od = ImageDraw.Draw(ov)
OPACITY = 0.6 / 0.6  # drawn at full strength; the app applies the opacity setting on top


def wa(alpha):
    return (255, 255, 255, int(255 * alpha * OPACITY))


def text(cx, cy, s, size, alpha):
    od = ImageDraw.Draw(ov)
    f = ImageFont.truetype(FONT, max(1, int(size * SC)))
    bb = od.textbbox((0, 0), s, font=f)
    od.text((cx * SC - (bb[2] - bb[0]) / 2 - bb[0], cy * SC - (bb[3] - bb[1]) / 2 - bb[1]), s, font=f, fill=wa(alpha))


for c in lay["controls"]:
    cx, cy, cw, ch = c["cx"], c["cy"], c["w"], c["h"]
    on = bool(held & c["bit"])
    if c["kind"] == 0:  # d-pad: base disc + four arms
        R = cw / 2
        arm, ln = R * 0.62, R * 0.92
        hub = arm / 2
        od.ellipse([(cx - R) * SC, (cy - R) * SC, (cx + R) * SC, (cy + R) * SC], fill=wa(0.07), outline=wa(0.25), width=2 * SC)
        # one cross, filled once (union of the two bars), like the app's nonzero-fill path
        m = Image.new("L", ov.size, 0)
        md = ImageDraw.Draw(m)
        md.rounded_rectangle([(cx - hub) * SC, (cy - ln) * SC, (cx + hub) * SC, (cy + ln) * SC], radius=arm * 0.25 * SC, fill=255)
        md.rounded_rectangle([(cx - ln) * SC, (cy - hub) * SC, (cx + ln) * SC, (cy + hub) * SC], radius=arm * 0.25 * SC, fill=255)
        layer = Image.new("RGBA", ov.size, wa(0.18))
        ov.paste(Image.alpha_composite(ov, layer), (0, 0), m)
        od = ImageDraw.Draw(ov)
        arms = [(1, (cx - hub, cy - ln, cx + hub, cy - hub), "▲", (cx, cy - ln * 0.62)),
                (2, (cx - hub, cy + hub, cx + hub, cy + ln), "▼", (cx, cy + ln * 0.62)),
                (4, (cx - ln, cy - hub, cx - hub, cy + hub), "◀", (cx - ln * 0.62, cy)),
                (8, (cx + hub, cy - hub, cx + ln, cy + hub), "▶", (cx + ln * 0.62, cy))]
        for bit, (x0, y0, x1, y1), g, (gx, gy) in arms:
            a_on = bool(held & bit)
            if a_on:
                hl = Image.new("RGBA", ov.size, (0, 0, 0, 0))
                ImageDraw.Draw(hl).rounded_rectangle([x0 * SC, y0 * SC, x1 * SC, y1 * SC], radius=arm * 0.25 * SC, fill=wa(0.42))
                ov.alpha_composite(hl)
                od = ImageDraw.Draw(ov)
            text(gx, gy, g, arm * 0.42, 1.0 if a_on else 0.85)
        continue
    if on:
        cw, ch = cw * 0.94, ch * 0.94
    box = [(cx - cw / 2) * SC, (cy - ch / 2) * SC, (cx + cw / 2) * SC, (cy + ch / 2) * SC]
    if c["kind"] == 1:
        od.ellipse(box, fill=wa(0.5 if on else 0.16), outline=wa(0.6), width=2 * SC)
        text(cx, cy, c["label"], ch * 0.44, 1.0)
    else:
        od.rounded_rectangle(box, radius=ch / 2 * SC, fill=wa(0.5 if on else 0.16), outline=wa(0.6), width=2 * SC)
        text(cx, cy, c["label"], min(ch * 0.36, cw * 0.2), 0.95)

screen = Image.alpha_composite(screen, ov)
mask = Image.new("L", screen.size, 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W * SC, H * SC], radius=50 * SC, fill=255)
img.paste(screen, (ox, oy), mask)
if sl > 0:  # notch side in landscape
    d.rounded_rectangle([ox - 2 * SC, oy + (H / 2 - 105) * SC, ox + 30 * SC, oy + (H / 2 + 105) * SC], radius=16 * SC, fill=(28, 28, 32))
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
img.convert("RGB").save(a.out, optimize=True)
print(a.out)
