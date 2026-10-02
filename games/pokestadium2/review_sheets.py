"""Dirty room: numbered contact sheets of retail UI images for writing text labels / picture briefs.

    python -m games.pokestadium2.review_sheets <rom> <out dir> [archive ...]

Writes sheet_NN.png (images on a checker background, "#n" above each) and index.json
(n -> key "space:off", w, h, fmt). The sheets stay in the dirty room; only the labels written
from them (text, colours, short descriptions) go into the spec.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

from games.pokestadium2 import romio
from games.pokestadium2.sheet import decode

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 1000


def main(argv):
    rom = open(argv[1], "rb").read()
    out = argv[2]
    arcs = argv[3:] or ["1898000", "2268000"]
    os.makedirs(out, exist_ok=True)
    sp = romio.spaces(rom)
    texs = json.load(open(os.path.join(HERE, "spec", "textures.json")))
    texs = [t for t in texs if t["space"].split("/")[0] in arcs]
    for t in texs:
        if "pal" in t:
            t["pals"] = [t["pal"]]
    texs.sort(key=lambda t: (t["space"].split("/")[0], int(t["space"].split("/")[1]), t["off"]))
    index, sheets = {}, 0
    yy, xx = np.mgrid[0:H, 0:W]
    checker = np.where(((yy // 8 + xx // 8) % 2)[..., None] == 0, 70, 100).astype(np.uint8).repeat(3, 2)

    def new():
        return Image.fromarray(checker.copy()), 4, 4, 0
    im, x, y, rowh = new()
    dr = ImageDraw.Draw(im)
    for n, t in enumerate(texs):
        rgba = decode(sp, t)
        if rgba is None:
            continue
        k = 3 if max(t["w"], t["h"]) <= 40 else 2 if max(t["w"], t["h"]) <= 128 else 1
        pic = Image.fromarray(rgba, "RGBA").resize((t["w"] * k, t["h"] * k), Image.NEAREST)
        if pic.width > W - 8:
            pic = pic.crop((0, 0, W - 8, pic.height))
        if pic.height > H - 30:
            pic = pic.crop((0, 0, pic.width, H - 30))
        if x + pic.width + 4 > W:
            x, y, rowh = 4, y + rowh + 6, 0
        if y + pic.height + 14 > H:
            im.save(os.path.join(out, f"sheet_{sheets:02d}.png"))
            sheets += 1
            im, x, y, rowh = new()
            dr = ImageDraw.Draw(im)
        dr.text((x, y), f"#{n}", fill=(255, 255, 0))
        im.paste(pic, (x, y + 11), pic)
        index[n] = {"key": f"{t['space']}:{t['off']:X}", "w": t["w"], "h": t["h"], "fmt": f"{t['fmt']}{t['siz']}",
                    "sheet": sheets}
        x += max(pic.width, 30) + 6
        rowh = max(rowh, pic.height + 12)
    im.save(os.path.join(out, f"sheet_{sheets:02d}.png"))
    json.dump(index, open(os.path.join(out, "index.json"), "w"))
    print(f"{len(index)} images on {sheets + 1} sheets -> {out}")


if __name__ == "__main__":
    main(sys.argv)
