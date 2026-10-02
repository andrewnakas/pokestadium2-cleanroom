"""Dirty room: find every asset container in the ROM by scanning (works for any revision).

    python -m games.pokestadium2.layout <rom> <out layout.json>

Regions: BinArchives (files listed), and standalone PERS-SZP / PRESJPEG / Yay0 / FRAGMENT
items outside archives. `span` = bytes up to the next region (the room a rebuilt item has).
"""
import json
import re
import struct
import sys
from collections import Counter

from . import romio


def scan_archives(b, start=0x1000):
    u = lambda o: struct.unpack_from(">I", b, o)[0]
    arcs, o = [], start
    while o < len(b) - 0x20:
        if b[o:o + 3] == b"\0\0\0" and b[o + 4:o + 8] == b"\0\0\0\0":
            ts, n = u(o + 8), u(o + 12)
            if 0 < n < 2000 and 0x10 + n * 16 <= ts < 0x1000000 and o + ts <= len(b):
                fs = [(u(o + 0x10 + i * 16), u(o + 0x14 + i * 16)) for i in range(n)]
                if fs[0][0] in (0x10 + n * 16, (0x10 + n * 16 + 15) & ~15) and all(a + s <= ts + 16 for a, s in fs) \
                        and all(fs[i][0] <= fs[i + 1][0] for i in range(n - 1)):
                    arcs.append({"kind": "archive", "rom": o, "size": ts, "files": fs})
                    o += (ts + 15) & ~15
                    continue
        o += 0x10
    return arcs


def scan(b):
    regs = scan_archives(b)
    arcs = list(regs)
    inside = lambda o: any(a["rom"] <= o < a["rom"] + a["size"] for a in arcs)
    for magic, kind, back in ((b"PERS-SZP", "szp", 0), (b"PRESJPEG", "jpeg", 0), (b"FRAGMENT", "fragment", 8)):
        for m in re.finditer(re.escape(magic), b):
            o = m.start() - back
            if o % 4 == 0 and not inside(o):
                regs.append({"kind": kind, "rom": o})
    szp = [r["rom"] for r in regs if r["kind"] == "szp"]
    for m in re.finditer(b"Yay0", b):
        o = m.start()
        if o % 4 or inside(o):
            continue
        dec, lnk, chk = struct.unpack_from(">3I", b, o + 4)
        if not (0 < dec < 0x800000 and 16 <= lnk <= chk < 0x800000):
            continue
        if any(0 < o - s <= 0x4000 and romio.u32(b, s + 8) == o - s for s in szp):
            continue                                   # the Yay0 body of a PERS-SZP
        regs.append({"kind": "yay0", "rom": o, "dec": dec})
    regs.sort(key=lambda r: r["rom"])
    for r, nx in zip(regs, regs[1:] + [{"rom": len(b)}]):
        r["span"] = nx["rom"] - r["rom"]
    return regs


def main(argv):
    b = open(argv[1], "rb").read()
    regs = scan(b)
    json.dump(regs, open(argv[2], "w"))
    c = Counter(r["kind"] for r in regs)
    print("regions:", dict(c), "archive files:", sum(len(r["files"]) for r in regs if r["kind"] == "archive"))
    # runs of same-kind standalone regions, one line each
    run = []
    for r in regs + [None]:
        if run and (r is None or r["kind"] != run[0]["kind"] or r["kind"] == "archive"):
            a = run[0]
            extra = f" files {len(a['files'])}" if a["kind"] == "archive" else ""
            print(f"  {a['rom']:#9x}..{run[-1]['rom'] + run[-1]['span']:#9x} {a['kind']:8s} x{len(run)}{extra}")
            run = []
        if r is not None:
            run.append(r)


if __name__ == "__main__":
    main(sys.argv)
