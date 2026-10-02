"""Dirty room: guess (bits, row width) of a headerless texel range from its statistics.

Used for UI file ranges no code/display list describes. Stacked textures of one width are one tall
texture for our purposes, so only bit depth and row width matter.

    guess(bytes, prior=None) -> {"bits", "w", "h", "score"} or None
Self-test on known textures: python -m games.pokestadium2.texguess <rom> <texscan.json>
"""
import json
import sys
from collections import Counter

import numpy as np

WIDTHS = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 40, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80, 84,
          88, 92, 96, 100, 104, 108, 112, 116, 120, 124, 128, 136, 144, 152, 160, 176, 192, 200, 208, 224, 240, 256,
          288, 304, 320]


def texels(raw, bits):
    """per-texel coarse value (0..255-ish) for correlation tests"""
    a = np.frombuffer(raw, np.uint8)
    if bits == 16:
        a = a[:len(a) // 2 * 2].reshape(-1, 2).astype(np.int32)
        v = a[:, 0] << 8 | a[:, 1]
        return ((v >> 11) & 31) * 2 + ((v >> 6) & 31) * 4 + ((v >> 1) & 31) * 2
    if bits == 32:
        a = a[:len(a) // 4 * 4].reshape(-1, 4).astype(np.int32)
        return (a[:, 0] + 2 * a[:, 1] + a[:, 2]) // 4
    if bits == 8:
        return a.astype(np.int32)
    return np.stack([a >> 4, a & 15], -1).reshape(-1).astype(np.int32) * 17


def lag(v, n):
    if n >= len(v):
        return 1e9
    return float(np.abs(v[n:] - v[:-n]).mean())


def depth(raw):
    """bit depth from byte statistics: alternating bytes = 16/32-bit, like nibbles = 4-bit, else 8-bit"""
    a = np.frombuffer(raw, np.uint8).astype(np.int32)
    c1, c2, c4 = lag(a, 1) + 1e-3, lag(a, 2) + 1e-3, lag(a, 4) + 1e-3
    if c2 / c1 < 0.75 and len(a) % 2 == 0:
        if len(a) % 4 == 0 and c4 / c2 < 0.6:
            return 32
        return 16
    hi, lo = a >> 4, a & 15
    ph = np.bincount(hi, minlength=16) / len(a)
    pl = np.bincount(lo, minlength=16) / len(a)
    return 4 if 0.5 * np.abs(ph - pl).sum() < 0.2 else 8


def best_width(raw, bits, prior_w=None):
    v = texels(raw, bits)
    n = len(v)
    if n < 16:
        return None
    rnd = float(np.abs(v - np.roll(v, n // 2 + 7)).mean()) + 1e-3
    cands = [(lag(v, w) / rnd, w) for w in range(4, min(n // 2, 320) + 1, 2)]     # any row period, not only divisors
    if not cands:
        return None
    m = min(c[0] for c in cands)
    med = float(np.median([c[0] for c in cands]))
    weak = m > 0.8 * med
    if weak and prior_w and prior_w * 2 <= n:                         # no clear row period: follow the neighbour
        w, sc = prior_w, m
    else:
        near = [(sc, w) for sc, w in cands if sc <= m * 1.1 + 0.005]
        sc, w = min(near, key=lambda c: abs(np.log(c[1] * c[1] / n))) if weak else near[0]   # flat: squarest
    return {"bits": bits, "w": w, "h": n // w, "rest": n % w, "score": sc, "weak": weak}


def guess(raw, prior=None):
    """prior: (bits, w) of the previous known texture in the file (used when the statistics are flat)"""
    if len(set(raw)) < 3:
        bits, w = prior[:2] if prior else (16, 16)
        n = len(raw) * 8 // bits
        w = w if w * 2 <= n else max(1, n // 2)
        return {"bits": bits, "w": w, "h": n // w, "rest": n % w, "score": 1, "weak": True}
    bits = depth(raw)
    return best_width(raw, bits, prior[1] if prior and prior[0] == bits else None)


def main(argv):
    from . import romio
    sp = romio.spaces(open(argv[1], "rb").read())
    js = json.load(open(argv[2]))
    ok = Counter()
    bad = Counter()
    for t in js["tex"]:
        if t["space"] == "rom" or t["h"] < 4 or t["w"] < 8 or t["pri"] < 2 or sp[t["space"]][8:16] == b"FRAGMENT":
            continue
        n = t["w"] * t["h"] * t["siz"] // 8
        raw = sp[t["space"]][t["off"]:t["off"] + n]
        if len(set(raw)) < 3:
            continue
        g = guess(raw)
        k = t["siz"]
        if g and g["bits"] == t["siz"] and g["w"] == t["w"]:
            ok[k] += 1
        elif g and g["bits"] == t["siz"]:
            ok[f"{k} depth only"] += 1
            bad[(t["siz"], t["w"], g["w"])] += 1
        else:
            bad[(t["siz"], t["w"], g and (g["bits"], g["w"]))] += 1
            ok[f"{k} wrong"] += 1
    print("guess self-test:", dict(sorted(ok.items(), key=str)))
    print("misses:", bad.most_common(14))


if __name__ == "__main__":
    main(sys.argv)
