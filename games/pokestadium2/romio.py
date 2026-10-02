"""Pokemon Stadium (US 1.0) ROM containers: read, rebuild, header CRC.

Formats from the decomp (src/3FB0.h, src/memmap.h); see docs/FORMATS.md.
Archive locations in the ROM are fixed (linker symbols and immediates in code), so a
rebuilt archive must fit its retail span; files inside may change size (table rewrite).
"""
import json
import os
import struct

import crunch64

RETAIL_SHA1 = "d8343e69a7dc63b869cf6361d87cde64444281d3"
SEEDS = {6102: 0xF8CA4DDC, 6103: 0xA3886759, 6105: 0xDF26F436, 6106: 0x1FEA617A}


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


# ---- BinArchive: 0x10 header (flags, fragment id, 0, total_size, num_files) + 0x10 per file ----

def is_archive(b):
    return len(b) >= 0x10 and b[0:3] == b"\0\0\0" and b[4:8] == b"\0\0\0\0" and 0 < u32(b, 12) < 0x4000 \
        and u32(b, 8) <= len(b) and 0x10 + u32(b, 12) * 0x10 <= u32(b, 8)


def archive_files(b):
    """-> list of (offset, size) relative to the archive start."""
    return [(u32(b, 0x10 + i * 0x10), u32(b, 0x14 + i * 0x10)) for i in range(u32(b, 12))]


def archive_build(head, files, span=None, align=0x10):
    """Rebuild an archive from its original 0x10 header and a list of file bytes."""
    n = len(files)
    out = bytearray(head[:0x10]) + bytearray(n * 0x10)
    seen = {}                                            # identical files share one copy (as retail does)
    for i, f in enumerate(files):
        f = bytes(f)
        if f not in seen:
            while len(out) % align:
                out.append(0)
            seen[f] = len(out)
            out += f
        struct.pack_into(">II", out, 0x10 + i * 0x10, seen[f], len(f))
    while len(out) % align:
        out.append(0)
    struct.pack_into(">II", out, 8, len(out), n)
    if span is not None:
        if len(out) > span:
            raise ValueError(f"archive {len(out):#x} > span {span:#x}")
        out += bytes(span - len(out))
    return out


# ---- PERS-SZP: magic, header_size, size1 (data), size2 (data + bss), n patch pairs, pairs, Yay0 ----

def kind(b):
    if b[:8] == b"PERS-SZP":
        return "szp"
    if b[:8] == b"PRESJPEG":
        return "jpeg"
    if b[8:16] == b"FRAGMENT":
        return "fragment"
    if b[:4] == b"Yay0":
        return "yay0"
    return "raw"


def szp_unpack(b):
    """-> (data, meta); meta keeps what a rebuild must preserve (sizes, pointer patches)."""
    hs, s1, s2, n = struct.unpack_from(">4I", b, 8)
    pairs = [struct.unpack_from(">II", b, 0x18 + i * 8) for i in range(n)]
    data = crunch64.yay0.decompress(bytes(b[hs:]))
    return data, {"header_size": hs, "size1": s1, "size2": s2, "pairs": pairs, "head": bytes(b[:hs])}


def szp_pack(data, meta):
    """Same decompressed size as retail (sizes and patch offsets in the kept header stay valid)."""
    out = bytearray(meta["head"])
    out += crunch64.yay0.compress(bytes(data))
    while len(out) % 4:
        out.append(0)
    return bytes(out)


def jpeg_unpack(b):
    hs = u32(b, 8)
    return bytes(b[hs:]), {"head": bytes(b[:hs])}


# ---- FRAGMENT: u32 inst[2], "FRAGMENT", headerSize, relocOffset, sizeInRom, sizeInRam ----

def fragment_info(b):
    hs, rel, rom, ram = struct.unpack_from(">4I", b, 0x10)
    n = u32(b, rel) if rel + 4 <= len(b) else 0
    relocs = [u32(b, rel + 4 + i * 4) for i in range(n)]
    return {"header_size": hs, "reloc": rel, "rom": rom, "ram": ram,
            "relocs": [(r >> 24, r & 0xFFFFFF) for r in relocs]}


def rowswap(raw, rowbytes, unit):
    """UI images keep odd rows with the two halves of every 2*unit bytes exchanged (ready for a
    dxt=0 block load). The exchange is its own inverse."""
    import numpy as np
    n = len(raw) // rowbytes * rowbytes
    a = np.frombuffer(bytes(raw[:n]), np.uint8).reshape(-1, rowbytes).copy()
    k = rowbytes // (2 * unit) * 2 * unit
    if k:
        a[1::2, :k] = a[1::2, :k].reshape(-1, k // (2 * unit), 2, unit)[:, :, ::-1, :].reshape(-1, k)
    return a.tobytes() + bytes(raw[n:])


# ---- header CRC ----

def crc(rom, cic):
    M = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = SEEDS[cic]
    words = struct.unpack_from(">262144I", rom, 0x1000)
    for i, d in enumerate(words):
        s = (t6 + d) & M
        if s < t6:
            t4 = (t4 + 1) & M
        t6 = s
        t3 ^= d
        sh = d & 0x1F
        r = ((d << sh) | (d >> (32 - sh))) & M if sh else d
        t5 = (t5 + r) & M
        t2 = t2 ^ r if t2 > d else t2 ^ t6 ^ d
        if cic == 6105:
            t1 = (t1 + (struct.unpack_from(">I", rom, 0x40 + 0x0710 + ((i * 4) & 0xFF))[0] ^ d)) & M
        else:
            t1 = (t1 + (t5 ^ d)) & M
    if cic == 6103:
        return ((t6 ^ t4) + t3) & M, ((t5 ^ t2) + t1) & M
    if cic == 6106:
        return ((t6 * t4) + t3) & M, ((t5 * t2) + t1) & M
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def detect_cic(rom):
    want = struct.unpack_from(">II", rom, 0x10)
    for cic in SEEDS:
        if crc(rom, cic) == want:
            return cic
    return None


def fix_crc(rom, cic):
    struct.pack_into(">II", rom, 0x10, *crc(rom, cic))


def yay0_len(b, o):
    """Compressed length of the Yay0 stream at b[o:] (walks the control bits)."""
    dec, lnk, chk = struct.unpack_from(">3I", b, o + 4)
    mp, lp, cp, n = o + 16, o + lnk, o + chk, 0
    while n < dec:
        bits = u32(b, mp)
        mp += 4
        for k in range(31, -1, -1):
            if bits >> k & 1:
                cp += 1
                n += 1
            else:
                v = (b[lp] << 8) | b[lp + 1]
                lp += 2
                c = v >> 12
                if c == 0:
                    c = b[cp] + 16
                    cp += 1
                n += c + 2
            if n >= dec:
                break
    return (max(mp, lp, cp) - o + 3) & ~3


# ---- spaces: "rom" + every decoded container item, keyed "<rom hex>" or "<rom hex>/<n>" ----

LAYOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spec", "layout.json")


def layout():
    return json.load(open(LAYOUT))


def spaces(rom, kinds=("szp", "raw", "jpeg", "yay0")):
    """Decoded items (PERS-SZP, raw and PRESJPEG archive files, standalone Yay0); archive tables read from this ROM."""
    sp = {"rom": bytes(rom)}
    for r in layout():
        o = r["rom"]
        if r["kind"] == "archive":
            for i, (a, s) in enumerate(archive_files(rom[o:o + r["size"]])):
                k = kind(rom[o + a:o + a + 16])
                if k in kinds:
                    sp[f"{o:07X}/{i}"] = szp_unpack(rom[o + a:o + a + s])[0] if k == "szp" else bytes(rom[o + a:o + a + s])
        elif r["kind"] == "szp" and "szp" in kinds:
            sp[f"{o:07X}"] = szp_unpack(rom[o:o + r["span"]])[0]
        elif r["kind"] == "yay0" and "yay0" in kinds:
            sp[f"{o:07X}"] = crunch64.yay0.decompress(bytes(rom[o:o + r["len"]]))
    return sp


def pack(sp):
    from . import rebuild
    out, rep = rebuild.rebuild(bytes(sp["rom"]), layout(), lambda key, k, data: sp.get(key))
    if rep["over"]:
        raise ValueError(f"items over their span: {rep['over'][:8]}")
    return out


def budgets(rom):
    """key -> the largest Yay0 stream (bytes) the item's ROM slot can hold"""
    out = {}
    for r in layout():
        o = r["rom"]
        if r["kind"] == "archive":
            for i, (a, s) in enumerate(r["files"]):
                if kind(rom[o + a:o + a + 16]) == "szp":
                    out[f"{o:07X}/{i}"] = (s - u32(rom, o + a + 8)) & ~3
        elif r["kind"] == "szp":
            out[f"{o:07X}"] = r["len"] - u32(rom, o + 8)
        elif r["kind"] == "yay0":
            out[f"{o:07X}"] = r["len"]
    return out


def packed_len(data):
    import crunch64
    return len(crunch64.yay0.compress(bytes(data)))
