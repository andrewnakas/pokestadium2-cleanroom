"""Image tables (Stadium 2 UI files): u32 n; u32 ptr[n] (0x8FF00000-based or file-relative); each image is
{u16 w; u16 h; u8 fmt; u8 siz; u16 0} at ptr-8 followed by the texels (G_IM_FMT / G_IM_SIZ codes).

    parse(data) -> list of {"off", "w", "h", "fmt", "siz", "n"} or None if the file is not an image table
    python -m games.pokestadium2.imgtab <dirty dir>      (summary)
"""
import collections
import os
import struct
import sys

FMT = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}


def parse(d):
    if len(d) < 0x10:
        return None
    n = struct.unpack_from(">I", d, 0)[0]
    if not 0 < n < 0x800 or 4 + 4 * n + 8 > len(d):
        return None
    ptrs = struct.unpack_from(f">{n}I", d, 4)
    out = []
    for p in ptrs:
        if p == 0:
            out.append(None)
            continue
        if p >> 20 == 0x8FF:
            p &= 0xFFFFF
        if p < 4 + 4 * n + 8 or p > len(d) or p & 7:
            return None
        w, h, fmt, siz, z = struct.unpack_from(">HHBBH", d, p - 8)
        if fmt not in FMT or siz > 3 or not 0 < w <= 1024 or not 0 < h <= 4096:
            return None
        nb = (w * h * (4 << siz) + 7) // 8
        if p + nb > len(d):
            return None
        out.append({"off": p, "w": w, "h": h, "fmt": FMT[fmt], "siz": 4 << siz, "n": nb, "flag": z})
    return out


def main(argv):
    root = argv[1]
    c, kinds, bad, tot, cov = collections.Counter(), collections.Counter(), [], 0, 0
    for dn in sorted(os.listdir(root)):
        p = os.path.join(root, dn)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if f.endswith((".fragment", ".jpeg")):
                continue
            d = open(os.path.join(p, f), "rb").read()
            t = parse(d)
            if t is None:
                c[dn + " no"] += 1
                continue
            c[dn + " yes"] += 1
            tot += len(d)
            ends = sorted((i["off"], i["off"] + i["n"]) for i in t if i)
            cov += sum(e - a for a, e in set(ends)) + 8 * len(set(ends)) + 4 + 4 * len(t)
            for i in t:
                if i:
                    kinds[(i["fmt"], i["siz"], i["flag"])] += 1
    print({k: v for k, v in sorted(c.items()) if "yes" in k})
    print("formats (fmt, bits, flag):", dict(kinds))
    print(f"table files: {tot / 1e6:.2f} MB, covered by images+headers {cov / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv)
