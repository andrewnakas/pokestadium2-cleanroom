"""Dirty room: decompress every container item into <work>/dirty/ and add real lengths to the layout.

    python -m games.pokestadium2.dump <rom> <layout.json> <dirty dir>

Names: <rom offset hex>/<n>.<kind>  (archive files) or <rom offset hex>.<kind> (standalone).
"""
import json
import os
import sys
from collections import Counter

import crunch64

from . import romio


def item(b, o, size=None):
    """-> (kind, decoded bytes, compressed length)"""
    k = romio.kind(b[o:o + 16])
    if k == "szp":
        hs = romio.u32(b, o + 8)
        ln = hs + romio.yay0_len(b, o + hs)
        return k, romio.szp_unpack(b[o:o + ln])[0], ln
    if k == "yay0":
        ln = romio.yay0_len(b, o)
        return k, crunch64.yay0.decompress(bytes(b[o:o + ln])), ln
    if k == "fragment":
        ln = size or romio.u32(b, o + 0x18)
        return k, bytes(b[o:o + ln]), ln
    return k, bytes(b[o:o + size]) if size else b"", size or 0


def main(argv):
    b = open(argv[1], "rb").read()
    regs = json.load(open(argv[2]))
    out = argv[3]
    os.makedirs(out, exist_ok=True)
    tot = Counter()
    for r in regs:
        if r["kind"] == "archive":
            d = os.path.join(out, f"{r['rom']:07X}")
            os.makedirs(d, exist_ok=True)
            for i, (a, s) in enumerate(r["files"]):
                k, data, _ = item(b, r["rom"] + a, s)
                open(os.path.join(d, f"{i}.{k}"), "wb").write(data)
                tot[k] += len(data)
        elif r["kind"] == "jpeg":
            r["len"] = r["span"]
            open(os.path.join(out, f"{r['rom']:07X}.jpeg"), "wb").write(b[r["rom"]:r["rom"] + r["span"]])
        else:
            k, data, ln = item(b, r["rom"])
            r["len"] = ln
            r["slack"] = r["span"] - ln
            open(os.path.join(out, f"{r['rom']:07X}.{k}"), "wb").write(data)
            tot[k] += len(data)
    json.dump(regs, open(argv[2], "w"))
    print("decoded bytes:", dict(tot))
    big = [(r["slack"], r["rom"], r["kind"]) for r in regs if r.get("slack", 0) > 0x40 and r["kind"] != "fragment"]
    print("raw data after items (slack > 0x40):", [(hex(o), k, hex(s)) for s, o, k in sorted(big, reverse=True)[:14]])


if __name__ == "__main__":
    main(sys.argv)
