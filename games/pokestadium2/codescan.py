"""Dirty room: texture facts (format, size, address) from the game's code and display lists.

Three sources, all static:
  1. code: constants built by lui/ori/addiu that are gDP words (the expanded gDPLoadTextureBlock /
     gDPLoadTextureTile macros): SetTextureImage address + render SetTile + SetTileSize.
  2. code: calls of the 2D blit helpers (x, y, w, h, ptr, texture width, ...) with constant arguments.
  3. data: F3DEX2 display lists stored as data (fragments, model files, UI files).
Addresses are segment addresses (0x0Sxxxxxx) or fragment addresses (0x8XXxxxxx).
"""
import struct

FMT = {0: "rgba", 1: "yuv", 2: "ci", 3: "ia", 4: "i"}
BITS = {0: 4, 1: 8, 2: 16, 3: 32}


def words(b, o, n):
    return struct.unpack_from(f">{n}I", b, o)


# ------------------------------------------------------------------ MIPS constant sweep

def sweep(code, vram):
    """Yield events from a linear sweep with constant tracking.

    ("const", pc, reg, value)   register got a constant value
    ("store", pc, base reg, offset, value)   sw/sh of a constant to memory
    ("jal", pc, target, {reg: const}, {sp offset: const})
    """
    ws = words(code, 0, len(code) // 4)
    reg = {0: 0}
    stack = {}
    ev = []
    pend = None
    for i, w in enumerate(ws):
        pc = vram + i * 4
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm
        fire = pend
        pend = None
        if op == 0x0F:                                   # lui
            reg[rt] = (imm << 16) & 0xFFFFFFFF
        elif op == 0x0D and rs in reg:                   # ori
            reg[rt] = reg[rs] | imm
            ev.append(("const", pc, rt, reg[rt]))
        elif op == 0x09 and rs in reg:                   # addiu
            reg[rt] = (reg[rs] + simm) & 0xFFFFFFFF
            ev.append(("const", pc, rt, reg[rt]))
        elif op in (0x2B, 0x29, 0x28):                   # sw / sh / sb
            if rt in reg:
                if rs == 29:
                    stack[simm] = reg[rt]
                else:
                    ev.append(("store", pc, rs, simm, reg[rt]))
        elif op == 0x03:                                 # jal
            pend = ("jal", pc, 0x80000000 | ((w & 0x03FFFFFF) << 2))
        elif op == 0 and (w & 0x3F) in (0x21, 0x25) and (rt == 0 or rs == 0) and ((w >> 11) & 31):   # move
            src = rs if rt == 0 else rt
            rd = (w >> 11) & 31
            if src in reg:
                reg[rd] = reg[src]
            else:
                reg.pop(rd, None)
        elif op == 0:                                    # other R-type
            fn = w & 0x3F
            if fn == 0x08:                               # jr: end of function (after the delay slot)
                pend = ("ret",)
            elif fn == 0x09:                             # jalr
                pend = ("jal", pc, 0)
            else:
                reg.pop((w >> 11) & 31, None)
        elif op in (0x08, 0x0A, 0x0B, 0x0C, 0x0E, 0x20, 0x21, 0x23, 0x24, 0x25, 0x09, 0x0D):   # I-type writes rt
            reg.pop(rt, None)
        reg[0] = 0
        if fire:
            if fire[0] == "jal":
                ev.append(("jal", fire[1], fire[2], {r: reg[r] for r in (4, 5, 6, 7) if r in reg}, dict(stack)))
                for r in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31):
                    reg.pop(r, None)
            else:
                reg = {0: 0}
                stack = {}
    return ev


# ------------------------------------------------------------------ gDP word streams

def is_addr(v):
    return (0x01000000 <= v < 0x10000000) or (0x80000000 <= v < 0x92000000)


GDP = (0xFD, 0xF5, 0xF3, 0xF4, 0xF2, 0xF0)


class TileState:
    """Feed gDP words in order; collects textures as dicts."""

    def __init__(self, src):
        self.src = src
        self.out = []
        self.img = None        # (addr, fmt, siz)
        self.tlut = None
        self.tile = {}         # tile -> (fmt, siz, line)
        self.last_load = None

    def cmd(self, w0, w1):
        op = w0 >> 24
        if op == 0xFD:
            self.img = (w1, (w0 >> 21) & 7, (w0 >> 19) & 3) if is_addr(w1) else None
        elif op == 0xF5:
            t = (w1 >> 24) & 7
            self.tile[t] = ((w0 >> 21) & 7, (w0 >> 19) & 3, (w0 >> 9) & 0x1FF)
        elif op == 0xF0:                                  # LoadTLUT
            if self.img:
                n = ((w1 >> 14) & 0x3FF) + 1
                self.out.append({"addr": self.img[0], "fmt": "rgba", "bits": 16, "w": n, "h": 1, "tlut": True,
                                 "src": self.src})
                self.tlut = self.img[0]
        elif op in (0xF3, 0xF4):
            self.last_load = (op, w0, w1, self.img)
        elif op == 0xF2:
            t = (w1 >> 24) & 7
            if t not in self.tile or self.last_load is None or self.last_load[3] is None:
                return
            fmt, siz, line = self.tile[t]
            lop, l0, l1, img = self.last_load
            w = (((w1 >> 12) & 0xFFF) - ((w0 >> 12) & 0xFFF)) // 4 + 1
            h = ((w1 & 0xFFF) - (w0 & 0xFFF)) // 4 + 1
            if lop == 0xF4:                                # LoadTile: image width from SetTextureImage
                pass
            if not (0 < w <= 1024 and 0 < h <= 1024) or fmt not in FMT:
                return
            self.out.append({"addr": img[0], "fmt": FMT[fmt], "bits": BITS[siz], "w": w, "h": h, "src": self.src,
                             "load": "tile" if lop == 0xF4 else "block",
                             "pal": self.tlut if fmt == 2 else None})
            self.last_load = None


def code_textures(code, vram, name):
    """Sources 1 and 2 for one code blob. -> (textures, jal events)"""
    ev = sweep(code, vram)
    st = TileState(name)
    pend = None            # (w0, pc) waiting for the store of w1 at offset 4
    jals = []
    for e in ev:
        if e[0] == "jal":
            jals.append(e)
            continue
        if e[0] != "store":
            continue
        _, pc, base, off, v = e
        if off == 0:
            if pend:
                st.cmd(pend[0], 0)
            pend = (v, pc) if (v >> 24) in GDP else None
        elif off == 4 and pend:
            st.cmd(pend[0], v if pc - pend[1] <= 0x28 else 0)
            pend = None
    return st.out, jals


# ------------------------------------------------------------------ display lists stored as data

DL_OPS = {0xFD, 0xF5, 0xF3, 0xF4, 0xF2, 0xF0, 0xE6, 0xE7, 0xE8, 0xDF, 0xDE, 0xD7, 0xD9, 0xDA, 0xDB, 0xFC, 0xE2, 0xE3,
          0xFA, 0xFB, 0xF9, 0xF8, 0x01, 0x05, 0x06, 0x07, 0xE4, 0xE1, 0xF1, 0xED, 0xEF, 0xF6, 0xF7, 0xFE, 0xFF, 0xDC,
          0xD8, 0xDD, 0xE9, 0xE5, 0xE0, 0x00, 0x02, 0x03, 0x04}


def data_textures(data, name):
    """Source 3: walk 8-byte aligned words; a SetTextureImage starts tracking, tile state carries on."""
    st = TileState(name)
    n = len(data) // 4
    ws = words(data, 0, n)
    i = 0
    live = 0
    while i + 1 < n:
        w0, w1 = ws[i], ws[i + 1]
        op = w0 >> 24
        if op == 0xFD and (w0 & 0x0007F000) == 0 and is_addr(w1):
            live = 64
        if live:
            if op in DL_OPS:
                st.cmd(w0, w1)
                live -= 1
                i += 2
                continue
            live = 0
        i += 1 if not live else 2
    return st.out
