#!/usr/bin/env python3
"""Verificare round-trip: citim .pes-ul ca o masina si redesenam din fisier."""
import glob
import sys

import numpy as np
import pyembroidery
from PIL import Image, ImageDraw

FABRIC = (246, 243, 236)


def load_blocks(path):
    pat = pyembroidery.read(path)
    blocks = []
    for stitches, thread in pat.get_as_colorblocks():
        pts = [(x, y) for x, y, cmd in stitches if cmd == pyembroidery.STITCH]
        color = (thread.get_red(), thread.get_green(), thread.get_blue()) \
            if thread else (0, 0, 0)
        if pts:
            blocks.append((color, pts))
    return pat, blocks


def render(blocks, ext, scale=0.8, upto=None):
    w = int((ext[2] - ext[0]) * scale) + 20
    h = int((ext[3] - ext[1]) * scale) + 20
    img = Image.new("RGB", (w, h), FABRIC)
    dr = ImageDraw.Draw(img)
    tr = lambda p: ((p[0] - ext[0]) * scale + 10, (p[1] - ext[1]) * scale + 10)
    done = 0
    for color, pts in blocks:
        for a, b in zip(pts, pts[1:]):
            if upto is not None and done >= upto:
                return img
            dr.line([tr(a), tr(b)], fill=color, width=3)
            done += 1
    return img


for path in sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1
                             else "prototype/out/*.pes")):
    try:
        pat, blocks = load_blocks(path)
        ext = pat.extents()
        n = pat.count_stitches()
        print(f"OK  {path}: {(ext[2]-ext[0])/10:.0f}x{(ext[3]-ext[1])/10:.0f} mm, "
              f"{n} comenzi, {len(blocks)} blocuri de culoare, "
              f"{pat.count_color_changes()} schimbari fir")
        render(blocks, ext).save(path.replace(".pes", "_check.png"))
    except Exception as e:
        print(f"EROARE {path}: {e}")

# simulare animata pentru varianta recomandata
path = "prototype/out/cabana_mix.pes"
pat, blocks = load_blocks(path)
ext = pat.extents()
total = sum(len(p) - 1 for _, p in blocks)
frames = [render(blocks, ext, upto=int(total * t))
          for t in np.linspace(0.04, 1.0, 24)]
frames[0].save("prototype/out/cabana_mix_simulare.gif", save_all=True,
               append_images=frames[1:] + [frames[-1]] * 6,
               duration=180, loop=0)
print("GIF simulare -> prototype/out/cabana_mix_simulare.gif")
