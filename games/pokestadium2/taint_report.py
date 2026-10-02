"""Taint report: every generated stream of the clean ROM vs every retail one (dev check; needs the retail ROM).

    python -m games.pokestadium2.taint_report <retail.z64> <clean.z64> [--list]

Scanned (cleanroom.taint windows; a shared run >= FAIL_RUN bytes fails):
  * every texture / sprite bitmap range as stored bytes and decoded RGBA (CI with its palette),
  * every palette range and every font glyph table,
  * every sample: VADPCM bytes and decoded PCM, codebooks and loop states.
Kept facts (code, geometry, animation, text, note sequences, bank structure) are not scanned.
"""
import json
import os
import struct
import sys

import numpy as np

from cleanroom import taint
from cleanroom.audio import vadpcm
from cleanroom.gfx import texfmt
from games.pokestadium2 import romio
from games.pokestadium2.generate import FMTN, SIZN

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")


def streams(sp, texs, pals, aud, extra, jpg, blobs):
    for t in texs:
        nb = texfmt.texel_bytes(t["w"], t["h"], SIZN[t["siz"]])
        b = bytes(sp[t["space"]][t["off"]:t["off"] + nb])
        key = f"{t['space']}:{t['off']:X}"
        yield "tex:" + key, b
        pal = None
        if t["fmt"] == "CI":
            if "pal" not in t:
                continue
            ps, po, n = t["pal"]
            n = min(n, 16 if t["siz"] == 4 else 256)
            pal = texfmt.decode(bytes(sp[ps][po:po + 2 * n]), n, 1, 0, 2).reshape(n, 4)
            full = 16 if t["siz"] == 4 else 256
            if n < full:
                pal = np.concatenate([pal, np.zeros((full - n, 4), np.uint8)])
        if t.get("swap"):
            b = romio.rowswap(b, t["w"] * t["siz"] // 8, t["swap"])
        img = texfmt.decode(b, t["w"], t["h"], FMTN[t["fmt"]], SIZN[t["siz"]], pal)
        yield "rgba:" + key, img[img[..., 3] > 0].tobytes()
    for p in pals:
        yield f"pal:{p['space']}:{p['off']:X}", bytes(sp[p["space"]][p["off"]:p["off"] + 2 * p["n"]])
    for label, (space, off, n) in extra.items():
        yield label, bytes(sp[space][off:off + n])
    rom = sp["rom"]
    for a in aud["adpcm"]:
        data = rom[a["rom"]:a["rom"] + a["size"]]
        yield f"adpcm:{a['rom']:X}", data
        for bo, lo in a["recs"][:1]:
            order, npred = struct.unpack_from(">ii", rom, bo)
            n = order * npred * 8
            book = {"order": order, "npred": npred, "book": list(struct.unpack_from(">%dh" % n, rom, bo + 8))}
            yield f"pcm:{a['rom']:X}", vadpcm.decode(data[:len(data) // 9 * 9], book).astype(">i2").tobytes()
        for bo, lo in a["recs"]:
            yield f"book:{bo:X}", rom[bo + 8:bo + 8 + 16 * a["npred"] * 2]
            if a["state"]:
                yield f"loop:{lo:X}", rom[lo + 16:lo + 48]
    for m in aud["mort"]:
        yield f"mort:{m['rom']:X}", rom[m["rom"] + 12:m["rom"] + m["size"]]
    import io
    from PIL import Image
    for e in jpg:
        d = sp[e["key"]]
        j = d[16:]
        yield "jpeg:" + e["key"], j[j.index(bytes([0xFF, 0xDA])) + 14:]      # entropy-coded scan (headers are standard tables)
        yield "jpegpix:" + e["key"], np.asarray(Image.open(io.BytesIO(d[16:])).convert("RGB")).tobytes()
    for bl in blobs:
        yield "blob:" + bl["key"], sp[bl["key"]]


def main(argv):
    retail, clean = open(argv[1], "rb").read(), open(argv[2], "rb").read()
    texs = json.load(open(f"{SPEC}/textures.json"))
    pals = json.load(open(f"{SPEC}/palettes.json"))
    aud = json.load(open(f"{SPEC}/audio.json"))
    jpg = json.load(open(f"{SPEC}/jpegs.json"))
    blobs = json.load(open(f"{SPEC}/blobs.json"))
    extra = {}
    try:
        from games.pokestadium2 import drawn
        extra = drawn.taint_ranges()
    except (ImportError, AttributeError):
        pass
    rs, cs = romio.spaces(retail), romio.spaces(clean)
    index = taint.build_index(s for _, s in streams(rs, texs, pals, aud, extra, jpg, blobs))
    n = [0]

    def counted():
        for lab, s in streams(cs, texs, pals, aud, extra, jpg, blobs):
            n[0] += 1
            yield lab, s
    hits = taint.scan(index, counted())
    fail = [h for h in hits if h[3] >= taint.FAIL_RUN]
    print(f"taint: {n[0]} streams scanned, {len(hits)} with shared windows, {len(fail)} failing "
          f"(run >= {taint.FAIL_RUN} B)")
    for h in sorted(fail, key=lambda h: -h[3])[:40 if "--list" in argv else 12]:
        print(f"  {h[0]:40s} first@{h[1]} windows={h[2]} run={h[3]}")
    if "--reseed" in argv and fail:
        rp = os.path.join(SPEC, "reseed.json")
        old = set(json.load(open(rp))) if os.path.exists(rp) else set()
        new = old | {h[0].split(":", 1)[1] for h in fail}
        json.dump(sorted(new), open(rp, "w"), indent=0)
        print(f"  reseed list: {len(new)} keys -> {rp}")
    if "--out" in argv:
        json.dump(sorted(fail, key=lambda h: -h[3]), open(argv[argv.index("--out") + 1], "w"))
    kinds = {}
    for h in fail:
        k = h[0].split(":")[0]
        kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        print("  failing by kind:", kinds)


if __name__ == "__main__":
    main(sys.argv)
