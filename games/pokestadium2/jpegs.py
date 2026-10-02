"""PRESJPEG pictures (backgrounds, 4:2:0 baseline JPEG behind a 0x10 header).

Dirty room:   python -m games.pokestadium2.jpegs <dirty dir> games/pokestadium2/spec
    -> spec/jpegs.json: key, width, height, decoded size, colour grid (16x16 block means). No pixels.
Clean room:   build(entry, quality) -> file bytes in the game's segment layout
    (DQT with both tables, one DHT with the four standard tables, SOF0, SOS, scan, EOI).
"""
import io
import json
import os
import struct
import sys

import numpy as np

ARCS = ("1E70000", "2230000")


def facts(root):
    from PIL import Image
    from cleanroom.decomp.spec import grid
    out = []
    for arc in ARCS:
        p = os.path.join(root, arc)
        for f in sorted(os.listdir(p), key=lambda x: int(x.split(".")[0])):
            d = open(os.path.join(p, f), "rb").read()
            if d[:8] != b"PRESJPEG":
                continue
            hs, dec = struct.unpack_from(">II", d, 8)
            im = np.asarray(Image.open(io.BytesIO(d[hs:])).convert("RGBA"))
            out.append({"key": f"{arc}/{f.split('.')[0]}", "w": im.shape[1], "h": im.shape[0], "dec": dec,
                        "grid": grid(im, 16)})
    return out


def _segments(j):
    o, out = 2, []
    while True:
        m, ln = j[o + 1], struct.unpack_from(">H", j, o + 2)[0]
        out.append((m, j[o + 4:o + 2 + ln]))
        o += 2 + ln
        if m == 0xDA:
            return out, j[o:]


def encode(rgb, quality):
    """RGB uint8 (h, w, 3) -> JPEG bytes in the game's layout"""
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "JPEG", quality=quality, subsampling=2, optimize=False)
    segs, scan = _segments(buf.getvalue())

    def seg(m, body):
        return bytes([0xFF, m]) + struct.pack(">H", len(body) + 2) + body
    dqt = b"".join(b for m, b in segs if m == 0xDB)
    dht = b"".join(b for m, b in segs if m == 0xC4)
    tabs, o = [], 0
    while o < len(dht):                                    # the game reads DC0, DC1, AC0, AC1 in that order
        n = 17 + sum(dht[o + 1:o + 17])
        tabs.append(dht[o:o + n])
        o += n
    dht = b"".join(sorted(tabs, key=lambda t: t[0]))
    sof = [b for m, b in segs if m == 0xC0][0]
    sos = [b for m, b in segs if m == 0xDA][0]
    return b"\xff\xd8" + seg(0xDB, dqt) + seg(0xC4, dht) + seg(0xC0, sof) + seg(0xDA, sos) + scan


def picture(e, hooks=None):
    """RGB for one entry: a drawn override, else the colour grid with our own detail"""
    from cleanroom.decomp.gen import detail, h32, upsample_grid
    if hooks and e["key"] in hooks:
        return hooks[e["key"]]
    rgba = upsample_grid(e["grid"], 16, e["w"], e["h"])
    rgba[..., :3] *= detail(h32("jpeg", e["key"]), e["w"], e["h"], 0.04, 6.0)[..., None]
    from games.pokestadium2 import generate
    rgba = generate.shifted(e["key"], rgba)                # taint-flagged pictures: seeded colour shift
    if e["key"] in generate.RESEED:
        rgba[..., :3] += np.random.default_rng(h32("jn", e["key"])).normal(0, 5.0, rgba[..., :3].shape)
    return np.clip(rgba[..., :3], 0, 255).astype(np.uint8)


def build(e, quality=85, hooks=None):
    j = encode(picture(e, hooks), quality)
    out = b"PRESJPEG" + struct.pack(">II", 0x10, e["dec"]) + j
    return out + b"\xff" * (-len(out) % 16)


def main(argv):
    f = facts(argv[1])
    json.dump(f, open(os.path.join(argv[2], "jpegs.json"), "w"), separators=(",", ":"))
    print(f"jpegs: {len(f)} pictures -> {argv[2]}/jpegs.json")


if __name__ == "__main__":
    main(sys.argv)
