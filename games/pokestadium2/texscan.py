"""Dirty room: find textures (space, offset, format, size) -> texscan.json.

    python -m games.pokestadium2.texscan <rom> <out texscan.json>

Sources: codescan (gDP constants in code, blit helper calls, display lists in data) for the main code,
the 77 code fragments, model/asset fragment files and UI files. Segment addresses are resolved to the
UI file each code fragment loads (ROM start constants in its code), scored by fit + image smoothness.
Then known layouts (fonts, icons, logo) and a guess for what is still uncovered (texguess).
"""
import json
import struct
import sys
from collections import Counter, defaultdict

import numpy as np

from . import codescan as cs
from . import romio

# Rev 2 addresses of the 2D blit helpers (1.0 addresses + 0x30): fmt, bits
FONT_CELLS = [(16, 10), (16, 12), (16, 16), (24, 20), (24, 24), (32, 32)]
BLIT = {}        # Stadium 2: blit helper addresses not identified yet


def frag_base(b, o):
    return (((romio.u32(b, o) & 0x03FFFFFF) << 2) | 0x80000000) - 0x20


def nbytes(t):
    return t["w"] * t["h"] * t["bits"] // 8


def lum(data, off, t):
    """coarse 2D sample array of a candidate texture (for smoothness scoring)"""
    n = nbytes(t)
    raw = np.frombuffer(data, np.uint8, n, off)
    if t["bits"] == 16:
        v = raw.reshape(-1, 2)
        v = ((v[:, 0].astype(np.int32) << 8 | v[:, 1]) >> 6 & 31) * 8 if t["fmt"] == "rgba" else v[:, 0].astype(np.int32)
    elif t["bits"] == 32:
        v = raw.reshape(-1, 4)[:, 1].astype(np.int32)
    elif t["bits"] == 8:
        v = (raw >> 4).astype(np.int32) * 16 if t["fmt"] == "ia" else raw.astype(np.int32)
    else:
        v = np.stack([raw >> 4, raw & 15], -1).reshape(-1).astype(np.int32) * 16
    return v[:t["w"] * t["h"]].reshape(t["h"], t["w"])


def smooth(data, off, t):
    """0..1: how image-like the bytes look at this width (1 = rows resemble their neighbours)"""
    if t["h"] < 2 or t["w"] < 2 or off < 0 or off + nbytes(t) > len(data):
        return 0.0
    a = lum(data, off, t)
    if a.max() == a.min():
        return 0.5
    dv = np.abs(np.diff(a, axis=0)).mean()
    sh = np.abs(a[1:] - np.roll(a[:-1], a.shape[1] // 2 + 1, axis=1)).mean()
    return float(np.clip(1.0 - dv / (sh + 1e-6), 0, 1))


def code_blobs(b, regs):
    """-> list of (name, rom offset, vram base, code bytes)"""
    frs = [r for r in regs if r["kind"] == "fragment"]
    out = [("main", 0x1000, 0x80000400, b[0x1000:frs[0]["rom"]])]
    for r in frs:
        o = r["rom"]
        rel = romio.u32(b, o + 0x14)
        base = frag_base(b, o)
        out.append((f"frag{(base >> 20) & 0xFF:02x}", o, base, b[o:o + rel]))
    return out


def collect(code, base, name):
    """textures referenced by one code blob: gDP constants, blit calls, display lists in its data"""
    tex, jals = cs.code_textures(code, base, name)
    tex += cs.data_textures(code, name + ":dl")
    for _, pc, target, regs_, stack in jals:
        if target in BLIT and 0x10 in stack and 0x14 in stack and 7 in regs_ and cs.is_addr(stack[0x10]):
            fmt, bits = BLIT[target]
            w, h = stack[0x14], regs_[7]
            if 0 < w <= 640 and 0 < h <= 480:
                tex.append({"addr": stack[0x10], "fmt": fmt, "bits": bits, "w": w, "h": h, "src": name + ":blit"})
                if target == 0x8001D590 and 0x14 in stack and cs.is_addr(stack.get(0x14, 0)):
                    pass
    return tex


def loads(code, base, starts):
    """region ROM starts referenced by constants in the code, in order of first use"""
    seen = []
    for e in cs.sweep(code, base):
        if e[0] == "const" and e[3] in starts and e[3] not in seen:
            seen.append(e[3])
    return seen


def main(argv):
    b = open(argv[1], "rb").read()
    regs = romio.layout()
    sp = romio.spaces(b)
    blobs = code_blobs(b, regs)
    found = {}            # (space, off) -> texture dict

    def add(space, off, t, pri):
        key = (space, off)
        e = {"space": space, "off": off, "fmt": t["fmt"].upper(), "siz": t["bits"], "w": t["w"], "h": t["h"],
             "pri": pri, "src": [t["src"]]}
        if t.get("tlut"):
            e["tlut"] = True
        if t.get("pal"):
            e["paladdr"] = t["pal"]
        old = found.get(key)
        if old is None or pri > old["pri"] or (pri == old["pri"] and nbytes(t) > old["w"] * old["h"] * old["siz"] // 8):
            found[key] = e

    # ---- 1. asset files that are fragments (models) or carry display lists: self-contained addresses
    stats = Counter()
    for key, data in sp.items():
        if key == "rom" or len(data) < 0x20:
            continue
        if data[8:16] == b"FRAGMENT":
            base = frag_base(data, 0)
            for t in cs.data_textures(data, key):
                off = t["addr"] - base
                if 0 <= off and off + nbytes(t) <= len(data):
                    add(key, off, t, 3)
                    stats["model"] += 1
                else:
                    stats["model ext"] += 1

    # ---- 2. code blobs: own data (0x8XX addresses) and segment addresses
    starts = {r["rom"]: r for r in regs if r["kind"] in ("szp", "archive")}
    ui_keys = [k for k, d in sp.items() if k != "rom" and d[8:16] != b"FRAGMENT" and len(d) >= 0x40
               and not k.startswith("0784A70")]
    region_keys = defaultdict(list)
    for k in ui_keys:
        region_keys[int(k.split("/")[0], 16)].append(k)
    report = []
    for name, rom_off, base, code in blobs:
        tex = collect(code, base, name)
        segs = defaultdict(list)
        for t in tex:
            a = t["addr"]
            if a >= 0x80000000:
                off = a - base
                if 0 <= off and off + nbytes(t) <= len(code):
                    add("rom", rom_off + off, t, 3)
                    stats["code data"] += 1
                else:
                    stats["other fragment"] += 1
            else:
                segs[a >> 24].append(t)
        if not segs:
            continue
        ld = [k for s in loads(code, base, starts) for k in region_keys.get(s, [])]
        for seg, ts in sorted(segs.items()):
            best = None
            for pool, bonus in ((ld, 0.15), (ui_keys, 0.0)):
                for k in pool:
                    data = sp[k]
                    sc = [smooth(data, (t["addr"] & 0xFFFFFF), t) for t in ts]
                    fit = sum(1 for t in ts if (t["addr"] & 0xFFFFFF) + nbytes(t) <= len(data))
                    score = (sum(sc) / len(ts)) * (fit / len(ts)) + bonus * (fit == len(ts))
                    if best is None or score > best[0]:
                        best = (score, k, fit)
                if best and best[0] >= 0.45:
                    break
            if best and best[0] >= 0.3:
                for t in ts:
                    off = t["addr"] & 0xFFFFFF
                    if off + nbytes(t) <= len(sp[best[1]]):
                        add(best[1], off, t, 2)
                        stats["segment"] += 1
                report.append(f"{name} seg{seg:x}: {len(ts)} -> {best[1]} score {best[0]:.2f} fit {best[2]}")
            else:
                stats["unresolved"] += len(ts)
                report.append(f"{name} seg{seg:x}: {len(ts)} UNRESOLVED best {best and (round(best[0], 2), best[1])}")

    # ---- 3. UI files with their own display lists (segment = the file itself when it fits)
    for key in ui_keys:
        data = sp[key]
        ts = cs.data_textures(data, key + ":dl")
        for t in ts:
            off = t["addr"] & 0xFFFFFF
            if t["addr"] < 0x10000000 and off + nbytes(t) <= len(data) and (t.get("tlut") or smooth(data, off, t) > 0.2):
                add(key, off, t, 2)
                stats["ui dl"] += 1

    # ---- 4. model files: texture records {u8 fmt; u8 siz; s16 w; s16 h; s16 w*h; u8* texels} (+ palette after it)
    FM = {0: "rgba", 2: "ci", 3: "ia", 4: "i"}
    pals = {}
    for key, data in sp.items():
        if key == "rom" or data[8:16] != b"FRAGMENT":
            continue
        base, n = frag_base(data, 0), len(data)
        for o in range(0x20, n - 12, 4):
            fmt, siz, w, h, nt, p = struct.unpack_from(">BBhhHI", data, o)
            if fmt in FM and siz <= 3 and 0 < w <= 256 and 0 < h <= 256 and base <= p < base + n and nt == (w * h) & 0xFFFF:
                t = {"fmt": FM[fmt], "bits": 4 << siz, "w": w, "h": h, "src": "rec"}
                if p - base + nbytes(t) > n or (fmt == 0 and siz < 2):
                    continue
                add(key, p - base, t, 4)
                stats["model rec"] += 1
                if fmt == 2:
                    pn = 16 if siz == 0 else 256
                    if o + 12 + 2 * pn <= n:
                        pals[(key, o + 12)] = pn
                        found[(key, p - base)]["pals"] = [[key, o + 12, pn]]

    # ---- 5. known layouts
    for key, data in sp.items():
        r = key.split("/")[0]
        if r == "081D000" and len(data) == 3200:
            add(key, 0, {"fmt": "rgba", "bits": 16, "w": 40, "h": 40, "src": "icon"}, 5)
        elif r == "0535260" and len(data) == 0x2000:
            add(key, 0, {"fmt": "rgba", "bits": 16, "w": 64, "h": 64, "src": "portrait"}, 5)
        elif r == "03B9C50":
            add(key, 0, {"fmt": "rgba", "bits": 16, "w": 128, "h": len(data) // 256, "src": "logo"}, 5)
        elif r == "03BA730":
            cw, ch = FONT_CELLS[int(key.split("/")[1])]
            ng = (len(data) - 0x90) // (cw * ch)
            for old in [k for k in found if k[0] == key]:
                del found[old]
            add(key, 0x90, {"fmt": "ia", "bits": 8, "w": cw, "h": ch * ng, "src": "font"}, 5)

    def drop_overlaps():
        by = defaultdict(list)
        for (k, o), t in found.items():
            by[k].append(t)
        n = 0
        for k, ts in by.items():
            ts.sort(key=lambda t: (-t["pri"], t["off"]))
            kept = []
            for t in ts:
                a, e = t["off"], t["off"] + t["w"] * t["h"] * t["siz"] // 8
                if any(a < ke and e > ka for ka, ke in kept):
                    del found[(k, t["off"])]
                    n += 1
                else:
                    kept.append((a, e))
        return n

    stats["overlap dropped"] = drop_overlaps()

    # ---- 6. anchors (every segment constant / data word into a resolved file) and a guess for uncovered ranges
    from . import texguess
    import re as _re
    segmap = {}
    for r in report:
        g = _re.match(r"(\w+) seg(\w+): \d+ -> (\S+)", r)
        if g:
            segmap[(g.group(1), int(g.group(2), 16))] = g.group(3)
    anchors = defaultdict(set)
    for name, rom_off, base, code in blobs:
        vals = [e[3] for e in cs.sweep(code, base) if e[0] == "const"]
        vals += list(struct.unpack_from(f">{len(code) // 4}I", code, 0))
        for v in vals:
            k = segmap.get((name, v >> 24))
            if k and (v & 0xFFFFFF) < len(sp[k]) and (v & 7) == 0:
                anchors[k].add(v & 0xFFFFFF)
    guessed = 0
    for key in ui_keys:
        if key.split("/")[0] in ("03BA730", "0784A70"):
            continue
        data = sp[key]
        known = sorted((t["off"], t["off"] + t["w"] * t["h"] * t["siz"] // 8, t) for (k, o), t in found.items()
                       if k == key and not t.get("tlut"))
        cuts = sorted(set([0, len(data)] + [a for a, b, t in known] + [b for a, b, t in known] + list(anchors[key])))
        prior = None
        ki = 0
        for a, b in zip(cuts, cuts[1:]):
            while ki < len(known) and known[ki][1] <= a:
                prior = (known[ki][2]["siz"], known[ki][2]["w"], known[ki][2]["fmt"])
                ki += 1
            if any(ka < b and kb > a for ka, kb, _ in known) or b - a < 16:
                continue
            g = texguess.guess(data[a:b], prior)
            if g is None:
                continue
            fmt = prior[2].lower() if prior and prior[0] == g["bits"] else {16: "rgba", 32: "rgba", 8: "ia", 4: "i"}[g["bits"]]
            add(key, a, {"fmt": fmt, "bits": g["bits"], "w": g["w"], "h": g["h"], "src": "guess"}, 1)
            found[(key, a)]["guess"] = round(g["score"], 2)
            if g.get("rest"):                                      # texels after the last full row
                ra = a + g["w"] * g["h"] * g["bits"] // 8
                add(key, ra, {"fmt": fmt, "bits": g["bits"], "w": g["rest"], "h": 1, "src": "guess"}, 1)
            prior = (g["bits"], g["w"], fmt)
            guessed += 1
    stats["guessed"] = guessed

    tex = sorted(found.values(), key=lambda t: (t["space"], t["off"]))
    pal = [{"space": k[0], "off": k[1], "n": n, "src": "rec"} for k, n in sorted(pals.items())]
    tex = [t for t in tex if not t.get("tlut")]
    OKF = {("RGBA", 16), ("RGBA", 32), ("CI", 4), ("CI", 8), ("IA", 4), ("IA", 8), ("IA", 16), ("I", 4), ("I", 8)}
    for t in tex:                                              # formats the codec has no entry for: same-depth stand-in
        if (t["fmt"], t["siz"]) not in OKF:
            t["fmt"] = {16: "IA" if t["fmt"] == "I" else "RGBA", 32: "RGBA", 8: "I", 4: "I"}[t["siz"]]
    json.dump({"tex": tex, "pal": pal, "sprites": [], "report": report}, open(argv[2], "w"))
    cov = defaultdict(int)
    for t in tex:
        cov[t["space"]] += t["w"] * t["h"] * t["siz"] // 8
    ui_tot = sum(len(sp[k]) for k in ui_keys)
    ui_cov = sum(cov[k] for k in ui_keys)
    fr = [k for k in sp if k != "rom" and sp[k][8:16] == b"FRAGMENT"]
    print(f"textures {len(tex)} palettes {len(pal)}  by source {dict(stats)}")
    print(f"UI files: {len(ui_keys)}, {ui_cov / 1024:.0f} of {ui_tot / 1024:.0f} KB covered; "
          f"model files: {len(fr)}, {sum(cov[k] for k in fr) / 1024:.0f} of {sum(len(sp[k]) for k in fr) / 1024:.0f} KB; "
          f"code: {cov['rom'] / 1024:.0f} KB")
    print(f"segment groups: {len(report)}, unresolved {sum('UNRES' in r for r in report)}")


if __name__ == "__main__":
    main(sys.argv)
