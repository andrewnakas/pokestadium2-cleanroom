"""Dirty room: what is left in each decoded file after textures, palettes, display lists and vertices.

    python -m games.pokestadium2.cover2 <rom> <texscan json> [archive prefix for detail]

Prints residual bytes per archive (bytes that are neither a listed texture/palette nor recognisable
geometry) and the largest residual ranges, so unlisted pictures can be found.
"""
import json
import struct
import sys
from collections import defaultdict

import numpy as np

from . import romio

DLOPS = set(range(0x00, 0x08)) | {0xD7, 0xD9, 0xDA, 0xDB, 0xDC, 0xDE, 0xDF, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7,
                                  0xE8, 0xE9, 0xED, 0xEE, 0xEF, 0xF0, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9,
                                  0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF, 0xB1, 0xB2}


def geometry(d):
    """-> bool mask of bytes that are display list commands or vertices they load"""
    n = len(d)
    m = np.zeros(n, bool)
    if n < 16:
        return m
    w = np.frombuffer(d[:n & ~7], ">u4").reshape(-1, 2)
    op = (w[:, 0] >> 24).astype(np.int32)
    isop = np.isin(op, list(DLOPS))
    # runs of >= 3 commands ending in / containing typical commands
    i = 0
    k = len(w)
    while i < k:
        if not isop[i] or (w[i, 0] == 0 and w[i, 1] == 0):
            i += 1
            continue
        j = i
        while j < k and isop[j]:
            j += 1
        seg = op[i:j]
        if j - i >= 3 and (np.isin(seg, [0xDF, 0xDE, 0x05, 0x06, 0x01, 0xFD, 0xE7])).sum() >= 2:
            m[i * 8:j * 8] = True
            for q in range(i, j):
                if op[q] == 0x01:                      # gSPVertex: n vertices at the segment offset
                    cnt = (int(w[q, 0]) >> 12) & 0xFF
                    a = int(w[q, 1]) & 0xFFFFFF
                    if 0 < cnt <= 64 and a + cnt * 16 <= n:
                        m[a:a + cnt * 16] = True
        i = j
    return m


def main(argv):
    rom = open(argv[1], "rb").read()
    js = json.load(open(argv[2]))
    sp = romio.spaces(rom)
    known = defaultdict(list)
    for t in js["tex"]:
        known[t["space"]].append((t["off"], t["off"] + t["w"] * t["h"] * t["siz"] // 8))
    for p in js["pal"]:
        known[p["space"]].append((p["off"], p["off"] + 2 * p["n"]))
    per = defaultdict(lambda: [0, 0, 0, 0])
    big = []
    for key, d in sp.items():
        if key == "rom":
            continue
        m = geometry(d)
        g = int(m.sum())
        t = np.zeros(len(d), bool)
        for a, e in known[key]:
            t[a:e] = True
        z = np.frombuffer(d, np.uint8) == 0
        rest = ~m & ~t
        arc = key.split("/")[0]
        per[arc][0] += len(d)
        per[arc][1] += int(t.sum())
        per[arc][2] += g
        per[arc][3] += int((rest & ~z).sum())
        # residual runs
        idx = np.flatnonzero(np.diff(np.concatenate([[0], rest.view(np.int8), [0]])))
        for a, e in zip(idx[::2], idx[1::2]):
            if e - a >= 512:
                big.append((int(e - a), key, int(a)))
    print("archive   bytes     tex+pal  geometry  residual(non-zero)")
    for arc, (n, t, g, r) in sorted(per.items()):
        print(f"{arc}  {n:9d} {t:9d} {g:9d} {r:9d}")
    big.sort(reverse=True)
    pre = argv[3] if len(argv) > 3 else ""
    print("largest residual ranges:")
    for n, key, a in [b for b in big if b[1].startswith(pre)][:30]:
        d = sp[key]
        print(f"  {key:14s} @{a:06X} {n:7d}  {d[a:a + 16].hex(' ', 4)}")
    json.dump(big, open("D:/n64work/pokestadium2/dirty/residual.json", "w"))


if __name__ == "__main__":
    main(sys.argv)
