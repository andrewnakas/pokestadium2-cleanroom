"""Write a ROM with replaced container contents (same places, same decoded sizes).

    rebuild(rom bytes, layout regions, provider) -> (bytearray, report)

provider(key, kind, data) -> new decoded bytes (same length) or None to keep the bytes as they are.
key = "<rom hex>" for standalone items, "<rom hex>/<n>" for archive files.
Self-test (dev): python -m games.pokestadium2.rebuild <rom> <layout.json> <out.z64>   (identity content, our compressor)
"""
import json
import struct
import sys

import crunch64

from . import romio


def pack(kind, orig, new):
    """Re-encode one item. orig = the item's ROM bytes (header + stream)."""
    if kind == "szp":
        hs = romio.u32(orig, 8)
        return orig[:hs] + crunch64.yay0.compress(bytes(new))
    if kind == "yay0":
        return crunch64.yay0.compress(bytes(new))
    return bytes(new)


def decode(kind, orig):
    if kind == "szp":
        return crunch64.yay0.decompress(bytes(orig[romio.u32(orig, 8):]))
    if kind == "yay0":
        return crunch64.yay0.decompress(bytes(orig))
    return bytes(orig)


def rebuild(rom, regs, provider):
    out = bytearray(rom)
    rep = {"items": 0, "changed": 0, "over": []}
    for r in regs:
        o = r["rom"]
        if r["kind"] == "archive":
            span = (r["size"] + 15) & ~15
            files, changed = [], False
            for i, (a, s) in enumerate(r["files"]):
                orig = rom[o + a:o + a + s]
                k = romio.kind(orig[:16])
                old = decode(k, orig)
                new = provider(f"{o:07X}/{i}", k, old)
                rep["items"] += 1
                if new is None or bytes(new) == old:
                    files.append(orig)
                else:
                    files.append(pack(k, orig, new))
                    changed = True
                    rep["changed"] += 1
            if changed:
                try:
                    out[o:o + span] = romio.archive_build(rom[o:o + 0x10], files, span=span)
                    struct.pack_into(">I", out, o + 8, r["size"])       # code may use the retail size
                except ValueError as e:
                    rep["over"].append((f"{o:07X}", str(e)))
        elif r["kind"] in ("szp", "yay0"):
            orig = rom[o:o + r["len"]]
            old = decode(r["kind"], orig)
            new = provider(f"{o:07X}", r["kind"], old)
            rep["items"] += 1
            if new is None or bytes(new) == old:
                continue
            enc = pack(r["kind"], orig, new)
            if len(enc) > r["len"]:
                rep["over"].append((f"{o:07X}", f"{len(enc):#x} > {r['len']:#x}"))
                continue
            out[o:o + r["len"]] = enc + bytes(r["len"] - len(enc))
            rep["changed"] += 1
    return out, rep


def main(argv):
    rom = open(argv[1], "rb").read()
    regs = json.load(open(argv[2]))
    out, rep = rebuild(rom, regs, lambda key, kind, data: data if kind in ("szp", "yay0") else None)
    open(argv[3], "wb").write(out)
    same = sum(1 for i in range(0, len(rom), 4096) if rom[i:i + 4096] == out[i:i + 4096])
    print(f"items {rep['items']} recompressed {rep['changed']} over-span {len(rep['over'])} {rep['over'][:6]}")
    print(f"unchanged 4K pages: {same}/{len(rom) // 4096}")


if __name__ == "__main__":
    main(sys.argv)
