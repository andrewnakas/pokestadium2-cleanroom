"""Dirty room: the texture list for Stadium 2 from exact sources only (no guessing).

    python -m games.pokestadium2.scan2 <dirty dir> <texscan.json from texscan (model records)> <out texscan2.json>

Sources: image tables (UI archives 1898000, 2268000), icon archives (40x40 RGBA16), fonts (width table + IA8
cells), model fragment texture records / display lists (from texscan, guesses dropped).
"""
import json
import os
import sys
from collections import Counter

from . import imgtab

FONT_CELLS = [(16, 10), (16, 12), (16, 16), (24, 20), (24, 24), (16, 16)]
FONT_HEAD = 0xB0
IMGTAB = ("1898000", "2268000")
ICONS = ("258D000", "2675000")
FACES = "3FD5000"
FRAG_SRC_OK = ("rec", "dl")


def files(root, arc):
    p = os.path.join(root, arc)
    for f in sorted(os.listdir(p), key=lambda x: int(x.split(".")[0])):
        yield f"{arc}/{f.split('.')[0]}", open(os.path.join(p, f), "rb").read()


def main(argv):
    root, old, out = argv[1], json.load(open(argv[2])), argv[3]
    tex, pal, st, skipped = [], [], Counter(), []
    for arc in IMGTAB:
        for key, d in files(root, arc):
            t = imgtab.parse(d)
            if t is None:
                skipped.append((key, len(d)))
                continue
            seen = set()
            for i in t:
                if i is None or i["off"] in seen:
                    continue
                seen.add(i["off"])
                e = {"space": key, "off": i["off"], "fmt": i["fmt"], "siz": i["siz"], "w": i["w"], "h": i["h"], "src": ["imgtab"],
                     "swap": 8 if i["siz"] == 32 else 4}
                if i["fmt"] == "CI":
                    n = 256 if i["siz"] == 8 else 16
                    po = i["off"] + i["n"]
                    e["pals"] = [[key, po, n]]
                    pal.append({"space": key, "off": po, "n": n, "src": "imgtab"})
                tex.append(e)
                st["imgtab " + i["fmt"] + str(i["siz"])] += 1
    for arc in ICONS:
        for key, d in files(root, arc):
            if len(d) == 3200:
                tex.append({"space": key, "off": 0, "fmt": "RGBA", "siz": 16, "w": 40, "h": 40, "src": ["icon"]})
                st["icon"] += 1
            else:
                skipped.append((key, len(d)))
    for key, d in files(root, "0437750"):
        cw, ch = FONT_CELLS[int(key.split("/")[1])]
        ng = (len(d) - FONT_HEAD) // (cw * ch)
        tex.append({"space": key, "off": FONT_HEAD, "fmt": "IA", "siz": 8, "w": cw, "h": ch * ng, "src": ["font"], "cell": [cw, ch, ng]})
        rest = len(d) - FONT_HEAD - cw * ch * ng
        if rest >= cw:
            tex.append({"space": key, "off": FONT_HEAD + cw * ch * ng, "fmt": "IA", "siz": 8, "w": cw, "h": rest // cw, "src": ["font tail"]})
        st["font"] += 1
    # headerless RGBA16 blocks (face textures of eight Pokemon; the Game Boy Tower frame): 0x800-byte tiles,
    # 64 wide where the rows fit that width better than 32
    import numpy as np

    def rough(d, w):
        v = (np.frombuffer(d, ">u2") >> 6 & 31).astype(np.int32).reshape(-1, w)
        return float(np.abs(np.diff(v, axis=0)).mean())
    blobs = [(k, d) for k, d in files(root, FACES) if len(d) > 16]
    blobs.append(("1600630", open(os.path.join(root, "1600630.yay0"), "rb").read()))
    for key, d in blobs:
        for a in range(0, len(d) - 63, 0x800):
            n = min(0x800, len(d) - a) // 64 * 64
            blk = d[a:a + n]
            w = 64 if n >= 256 and rough(blk[:n // 128 * 128], 64) < rough(blk, 32) else 32
            n = n // (2 * w) * 2 * w
            tex.append({"space": key, "off": a, "fmt": "RGBA", "siz": 16, "w": w, "h": n // (2 * w), "src": ["block"]})
            st["block"] += 1
    # full-screen CI8 picture behind the first menu: 256-entry palette, then 256x224 indices
    tex.append({"space": "1600010", "off": 0x200, "fmt": "CI", "siz": 8, "w": 256, "h": 224, "src": ["screen"],
                "pals": [["1600010", 0, 256]]})
    pal.append({"space": "1600010", "off": 0, "n": 256, "src": "screen"})
    done = set(IMGTAB) | set(ICONS) | {"0437750"}
    keep_pal = set()
    for t in old["tex"]:
        arc = t["space"].split("/")[0]
        src = t["src"][0].split(":")[-1]
        if arc in done or t["space"] == "rom" or (src not in FRAG_SRC_OK and "0x" not in src and not src.isdigit() and t.get("pri", 0) < 3):
            continue
        if t.get("pri", 0) < 3:
            continue
        tex.append(t)
        st["model " + t["fmt"] + str(t["siz"])] += 1
        for p in t.get("pals", []):
            keep_pal.add((p[0], p[1]))
    # model CI palettes: the palette table {s32 count; u16* colours; Gfx* load} (docs/MODELS.md), not the bytes
    # after the texture record. Bound textures take the palette their material names; others the nearest one.
    import struct
    from . import model_render
    ci_files = sorted({t["space"] for t in tex if t["fmt"] == "CI" and "/" in t["space"]
                       and t["space"].split("/")[0] not in done})
    npal = 0
    for key in ci_files:
        arc, idx = key.split("/")
        d = open(os.path.join(root, arc, idx + ".szp"), "rb").read()
        table = {}
        for o in range(0, len(d) - 11, 4):
            c, p1, p2 = struct.unpack_from(">iII", d, o)
            if c in (16, 256) and p1 >> 20 == 0x8FF and p2 >> 20 == 0x8FF and (p1 & 0xFFFFF) + 2 * c <= len(d)                     and (p2 & 0xFFFFF) < len(d):
                table[p1 & 0xFFFFF] = c
        bound = {}
        try:
            m = model_render.Model(d, int(idx))
            bound = {k[4]: k[5] for k in m.tex if k[5] is not None}
        except Exception:
            pass
        offs = sorted(table)
        for t in sorted((t for t in tex if t["space"] == key and t["fmt"] == "CI"), key=lambda t: t["off"]):
            want = 16 if t["siz"] == 4 else 256
            po = bound.get(t["off"])
            if po not in table:
                cands = [o for o in offs if table[o] == want] or offs
                same = [x for x in tex if x["space"] == key and x["fmt"] == "CI" and x["off"] <= t["off"]
                        and x.get("pals") and x["pals"][0][1] in table and x["siz"] == t["siz"]]
                po = same[-1]["pals"][0][1] if same else (cands[0] if cands else None)
            if po is None:
                t.pop("pals", None)
                st["model CI without palette"] += 1
                continue
            t["pals"] = [[key, po, table[po]]]
        for o in offs:
            pal.append({"space": key, "off": o, "n": table[o], "src": "paltable"})
            npal += 1
    st["model palettes"] = npal
    json.dump({"tex": tex, "pal": pal, "sprites": [], "report": []}, open(out, "w"))
    nb = sum(t["w"] * t["h"] * t["siz"] // 8 for t in tex)
    print(f"textures {len(tex)} ({nb / 1e6:.1f} MB) palettes {len(pal)}")
    print(dict(sorted(st.items())))
    print("skipped:", skipped[:12])


if __name__ == "__main__":
    main(sys.argv)
