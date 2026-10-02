"""Software renderer for the Pokemon models (archive 27ED000, 282 FRAGMENT files): our own pictures of
the game's geometry (icons, portraits). See docs/MODELS.md for the format.

    from games.pokestadium2 import model_render as mr
    m = mr.load(open(rom, "rb").read())
    rgba = mr.render(25, size=(96, 96), yaw=30, pitch=12)          # uses the last load()
    python -m games.pokestadium2.model_render <rom> <out.png> [first [count]] [--size N] [--yaw D] [--pitch D]

Geometry and textures come from the ROM given to load(): use the clean ROM for anything published.
"""
import struct
import sys
import time

import numpy as np

from cleanroom.gfx import texfmt
from . import romio

ARCHIVE = 0x27ED000
# geo layout command sizes (same engine as Pokemon Stadium 1, src/geo_layout.c)
SIZES = {0: 8, 1: 4, 2: 8, 3: 8, 4: 4, 5: 4, 6: 4, 7: 8, 8: 12, 9: 4, 0xA: 8, 0xB: 0x18, 0xC: 4, 0xD: 4, 0xE: 4,
         0xF: 4, 0x10: 4, 0x11: 4, 0x12: 4, 0x13: 8, 0x14: 12, 0x15: 12, 0x16: 4, 0x17: 0x14, 0x18: 8, 0x19: 8,
         0x1A: 4, 0x1B: 0x10, 0x1C: 0x10, 0x1D: 0x1C, 0x1E: 8, 0x1F: 0x18, 0x20: 0x14, 0x21: 0x10, 0x22: 8,
         0x23: 0x10, 0x24: 4, 0x25: 4, 0x26: 0x14, 0x28: 4, 0x29: 4}
G_CULL_FRONT, G_CULL_BACK, G_LIGHTING, G_TEXTURE_GEN = 0x200, 0x400, 0x20000, 0x40000
LIGHT = np.array([-0.35, 0.55, 0.76])
AMBIENT, DIFFUSE = 0.62, 0.45

# engine combine table (Stadium 1 D_8006F1B4): a0 b0 c0 d0 Aa0 Ab0 Ac0 Ad0 a1 b1 c1 d1 Aa1 Ab1 Ac1 Ad1
CC_TABLE = [
    (0x1F, 0x1F, 0x1F, 3, 7, 7, 7, 3, 0, 0x1F, 4, 0x1F, 0, 7, 6, 7),
    (1, 0x1F, 3, 0x1F, 7, 7, 7, 1, 0, 0x1F, 4, 0x1F, 0, 7, 6, 7),
    (1, 3, 8, 3, 7, 7, 3, 7, 0, 0x1F, 4, 0x1F, 0, 7, 6, 7),
    (1, 0x1F, 3, 0x1F, 7, 7, 7, 3, 0, 0x1F, 4, 0x1F, 0, 7, 6, 7),
    (1, 0x1F, 3, 0x1F, 1, 7, 3, 7, 0, 0x1F, 4, 0x1F, 0, 7, 6, 7),
    (0x1F, 0x1F, 0x1F, 3, 7, 7, 7, 3, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 0x1F, 3, 0x1F, 7, 7, 7, 1, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 3, 8, 3, 7, 7, 3, 7, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 0x1F, 3, 0x1F, 7, 7, 7, 3, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 0x1F, 3, 0x1F, 1, 7, 3, 7, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (0x1F, 0x1F, 0x1F, 4, 7, 7, 7, 4, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 0x1F, 4, 0x1F, 7, 7, 7, 1, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 4, 8, 4, 7, 7, 3, 7, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 0x1F, 4, 0x1F, 7, 7, 7, 4, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
    (1, 0x1F, 4, 0x1F, 1, 7, 4, 7, 0x1F, 0x1F, 0x1F, 0, 0, 7, 6, 7),
]
NO_TILE = {"fmt": None, "siz": None, "cms": 0, "cmt": 0, "masks": 0, "maskt": 0, "shifts": 0, "shiftt": 0,
           "uls": 0, "ult": 0, "lrs": None, "lrt": None, "pal": None}

_cur = None


def _ptr(v):
    """0x8FF00000-based pointer -> file offset (None for NULL / foreign)."""
    return v & 0xFFFFF if (v >> 20) == 0x8FF else None


def _rot(rx, ry, rz):
    """engine func_8000F730: row-vector rotation from binary angles."""
    a = np.array([rx, ry, rz], np.float64) * (np.pi / 32768.0)
    sx, sy, sz = np.sin(a)
    cx, cy, cz = np.cos(a)
    return np.array([[cy * cz, cy * sz, -sy],
                     [sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy],
                     [cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy]])


def _rot_zxy(rx, ry, rz):
    """engine func_8000F2C4 (translate/rotate nodes)."""
    a = np.array([rx, ry, rz], np.float64) * (np.pi / 32768.0)
    sx, sy, sz = np.sin(a)
    cx, cy, cz = np.cos(a)
    return np.array([[cy * cz + sx * sy * sz, cx * sz, -sy * cz + sx * cy * sz],
                     [-cy * sz + sx * sy * cz, cx * cz, sy * sz + sx * cy * cz],
                     [cx * sy, -sx, cx * cy]])


def _m4(r, t):
    m = np.eye(4)
    m[:3, :3] = r
    m[3, :3] = t
    return m


class Model:
    """One model file: runs the geo layout once and keeps draw batches in model space."""

    def __init__(self, data, index=-1):
        self.b = data
        self.index = index
        self.tex = {}
        self.batches = []        # dict(layer, P (n,3,3), N (n,3,3), C (n,3,4), UV (n,3,2), lit, mat)
        self.notes = []
        self.joints = 0
        self.effects = 0         # callback nodes we do not draw (flames, sprites, ...)
        self.slots = {}
        self.dry = True
        self._run()              # pass 1: joint matrices (display lists may use a joint defined later)
        self.dry = False
        self.joints = 0
        self.notes = []
        self._run()

    # ---- file access -------------------------------------------------------------------------------------
    def u32(self, o):
        return struct.unpack_from(">I", self.b, o)[0]

    def root_script(self):
        b = self.b
        if b[8:16] != b"FRAGMENT":
            raise ValueError("not a FRAGMENT")
        hi = struct.unpack_from(">H", b, 0x2E)[0]         # lui v1, hi ; addiu v1, v1, lo ; jr ra
        lo = struct.unpack_from(">h", b, 0x32)[0]
        root = _ptr(((hi << 16) + lo) & 0xFFFFFFFF)
        if root is None:
            raise ValueError("no root pointer")
        self.root = root
        lst = _ptr(self.u32(root + 8))
        return _ptr(self.u32(lst))

    # ---- textures ----------------------------------------------------------------------------------------
    def tex_record(self, idx):
        o = self.textab + idx * 12
        fmt, typ, w, h, n, p = struct.unpack_from(">BBhhHI", self.b, o)
        return fmt, typ, w, h, _ptr(p)

    def texture(self, fmt, siz, w, h, off, pal=None):
        """decoded RGBA float (h, w, 4) 0..1"""
        key = (fmt, siz, w, h, off, pal)
        if key in self.tex:
            return self.tex[key]
        b = self.b
        try:
            n = texfmt.texel_bytes(w, h, siz)
            palette = None
            if fmt == texfmt.CI:
                po = pal if pal is not None else off + n
                cnt = 16 if siz == texfmt.B4 else 256
                v = np.frombuffer(b[po:po + cnt * 2], ">u2").astype(np.int64)
                palette = np.stack([((v >> 11) & 31) * 255 // 31, ((v >> 6) & 31) * 255 // 31,
                                    ((v >> 1) & 31) * 255 // 31, (v & 1) * 255], 1)
                if len(palette) < cnt:
                    palette = np.vstack([palette, np.zeros((cnt - len(palette), 4), np.int64)])
            img = texfmt.decode(b[off:off + n], w, h, fmt, siz, palette).astype(np.float32) / 255.0
        except Exception as e:                                        # noqa: BLE001
            self.notes.append(f"tex {off:X} {fmt}/{siz} {w}x{h}: {e}")
            img = None
        self.tex[key] = img
        return img

    # ---- display lists -----------------------------------------------------------------------------------
    def tile_dl(self, off):
        """material DL (SetTile/LoadBlock/SetTileSize) -> tile 0 parameters"""
        t = {"fmt": None, "siz": None, "cms": 0, "cmt": 0, "masks": 0, "maskt": 0, "shifts": 0, "shiftt": 0,
             "uls": 0, "ult": 0, "lrs": None, "lrt": None, "pal": None}
        b = self.b
        for i in range(64):
            w0, w1 = struct.unpack_from(">II", b, off + i * 8)
            op = w0 >> 24
            if op == 0xDF:
                break
            if op == 0xF5 and (w1 >> 24) & 7 == 0:
                t.update(fmt=(w0 >> 21) & 7, siz=(w0 >> 19) & 3, cmt=(w1 >> 18) & 3, maskt=(w1 >> 14) & 15,
                         shiftt=(w1 >> 10) & 15, cms=(w1 >> 8) & 3, masks=(w1 >> 4) & 15, shifts=w1 & 15)
            elif op == 0xF2 and (w1 >> 24) & 7 == 0:
                t.update(uls=(w0 >> 12) & 0xFFF, ult=w0 & 0xFFF, lrs=(w1 >> 12) & 0xFFF, lrt=w1 & 0xFFF)
            elif op == 0xFD:
                p = _ptr(w1)
                if p is not None:
                    t["pal"] = p                                   # a TLUT image set inside the list
        if not t["lrs"] and not t["lrt"]:
            t["lrs"] = t["lrt"] = None                             # size set at run time by a callback
        return t

    def run_dl(self, off, M, layer, depth=0):
        b = self.b
        if self.dry:
            return
        st = self.st if depth else self.use(layer)
        R = M[:3, :3]
        for i in range(4096):
            if off + i * 8 + 8 > len(b):
                break
            w0, w1 = struct.unpack_from(">II", b, off + i * 8)
            op = w0 >> 24
            if op == 0xDF:
                break
            if op == 0x01:
                n = (w0 >> 12) & 0xFF
                v0 = ((w0 >> 1) & 0x7F) - n
                p = _ptr(w1)
                if p is None or v0 < 0 or v0 + n > 64 or p + n * 16 > len(b):
                    self.notes.append(f"vtx {w1:08X}")
                    continue
                raw = np.frombuffer(b[p:p + n * 16], np.uint8).reshape(n, 16)
                pos = raw[:, 0:6].copy().view(">i2").astype(np.float64)
                st["vp"][v0:v0 + n] = pos @ R + M[3, :3]
                st["vuv"][v0:v0 + n] = raw[:, 8:12].copy().view(">i2").astype(np.float64)
                st["vc"][v0:v0 + n] = raw[:, 12:16]
                nrm = raw[:, 12:15].copy().view(np.int8).astype(np.float64) @ R
                ln = np.linalg.norm(nrm, axis=1, keepdims=True)
                st["vn"][v0:v0 + n] = nrm / np.maximum(ln, 1e-9)
            elif op in (0x05, 0x06, 0x07):
                tris = [((w0 >> 16) & 0xFF, (w0 >> 8) & 0xFF, w0 & 0xFF)]
                if op != 0x05:
                    tris.append(((w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF))
                for t in tris:
                    self.emit([x >> 1 for x in t], layer)
            elif op == 0xD9:
                st["geom"] = (st["geom"] & (w0 & 0xFFFFFF)) | w1
            elif op == 0xDE:
                p = _ptr(w1)
                if p is not None and depth < 8:
                    self.run_dl(p, M, layer, depth + 1)
                if (w0 >> 16) & 0xFF:
                    break
            elif op == 0xD7:
                st["tscale"] = ((w1 >> 16) / 65536.0, (w1 & 0xFFFF) / 65536.0)
            elif op == 0xFA:
                self.touch(st, dict(st["mat"], prim=np.array([(w1 >> 24) & 255, (w1 >> 16) & 255, (w1 >> 8) & 255,
                                                              w1 & 255]) / 255.0))

    def emit(self, idx, layer):
        st = self.st
        if max(idx) >= 64:
            return
        key = (layer, st["ver"], st["geom"] & (G_CULL_FRONT | G_CULL_BACK | G_LIGHTING | G_TEXTURE_GEN), st["tscale"])
        if self.acc_key != key:
            self.flush()
            self.acc_key = key
            self.acc_mat = dict(st["mat"], geom=st["geom"], layer=layer, tscale=st["tscale"])
        self.acc.append((st["vp"][idx], st["vn"][idx], st["vc"][idx], st["vuv"][idx]))

    def flush(self):
        if self.acc:
            P, N, C, UV = (np.array(x) for x in zip(*self.acc))
            self.batches.append({"P": P, "N": N, "C": C.astype(np.float64) / 255.0, "UV": UV, "mat": self.acc_mat})
        self.acc = []
        self.acc_key = None

    # ---- materials ---------------------------------------------------------------------------------------
    def use(self, layer):
        """Select the layer's bucket (each layer is its own display list stream with its own RSP/RDP state) and
        apply the pending material node the way the engine does: only what differs from the bucket's *tracked*
        mode / prim colour / texture is emitted, so state set by a draw callback survives plain material nodes."""
        key = layer & 15
        st = self.bk.get(key)
        if st is None:
            st = self.bk[key] = {
                "vp": np.zeros((64, 3)), "vn": np.zeros((64, 3)), "vc": np.zeros((64, 4), np.uint8),
                "vuv": np.zeros((64, 2)), "geom": G_CULL_BACK | G_LIGHTING, "tscale": (1.0, 1.0),
                "mat": {"cc": CC_TABLE[0], "prim": np.ones(4), "env": np.zeros(4), "lod": 1.0, "img": None,
                        "tile": None, "img1": None, "tile1": None},
                "tr": {"mode": 0, "prim": (255, 255, 255, 255), "tex": None}, "ver": (key, 0)}
        if self.st is not st:
            self.flush()
        self.st = st
        mode, dl, tex, pal, prim = self.pending
        tr = st["tr"]
        mat = dict(st["mat"])
        changed = False
        if tex >= 0 and self.textab is not None and tex < self.ntex:
            if tr["tex"] != (tex, pal, dl):
                tr["tex"] = (tex, pal, dl)
                changed = True
                fmt, typ, w, h, p = self.tex_record(tex)
                tile = self.tile_dl(dl) if dl is not None else dict(NO_TILE)
                f = tile["fmt"] if tile.get("fmt") is not None else fmt
                z = tile["siz"] if tile.get("siz") is not None else typ
                poff = self.palette_for(tex, pal, p, w, h, z) if f == texfmt.CI and p is not None else None
                mat["img"], mat["tile"] = None, None
                if p is not None and w > 0 and h > 0:
                    mat["img"], mat["tile"] = self.texture(f, z, w, h, p, poff), tile
        elif tr["tex"] is not None:
            tr["tex"] = None
            mat["img"] = mat["tile"] = None
            changed = True
        if tuple(prim) != tr["prim"]:
            tr["prim"] = tuple(prim)
            mat["prim"] = np.array(prim) / 255.0
            mat["lod"] = 1.0
            changed = True
        if mode != tr["mode"]:
            tr["mode"] = mode
            mat["cc"] = CC_TABLE[mode] if mode < len(CC_TABLE) else CC_TABLE[1]
            changed = True
        if changed:
            self.touch(st, mat)
        return st

    def override_texels(self, p):
        """effect callbacks (0x48 sludge, 0x68 flames) build the node's list at run time: the material's texture
        with other texels (frame 0)"""
        mode, dl, tex, pal, prim = self.pending
        if p is None or not (0 <= tex < self.ntex) or self.textab is None:
            return False
        fmt, typ, w, h, _ = self.tex_record(tex)
        tile = self.tile_dl(dl) if dl is not None else dict(NO_TILE)
        f = tile["fmt"] if tile.get("fmt") is not None else fmt
        z = tile["siz"] if tile.get("siz") is not None else typ
        if f == texfmt.CI or w <= 0 or h <= 0 or p + texfmt.texel_bytes(w, h, z) > len(self.b):
            return False
        img = self.texture(f, z, w, h, p, None)
        if img is None:
            return False
        self.touch(self.st, dict(self.st["mat"], img=img, tile=tile))
        return True

    def touch(self, st, mat):
        self.flush()
        st["mat"] = mat
        self.nver += 1
        st["ver"] = (st["ver"][0], self.nver)

    def reset(self, layer):
        """engine func_80015684 (after a node flagged by cmd 0x25): back to the tracked material, texture off"""
        st = self.bk.get(layer & 15)
        if st is None:
            return
        tr = st["tr"]
        tr["tex"] = None
        mat = dict(st["mat"], img=None, tile=None, img1=None, tile1=None, prim=np.array(tr["prim"]) / 255.0, lod=1.0,
                   cc=CC_TABLE[tr["mode"]] if tr["mode"] < len(CC_TABLE) else CC_TABLE[1])
        st["geom"] = (st["geom"] | G_CULL_BACK) & ~G_TEXTURE_GEN
        st["tscale"] = (1.0, 1.0)
        self.touch(st, mat)

    def palette_for(self, tex, pal, p, w, h, siz):
        """CI palette offset: palette table entry {s32 count; u16 *colours; Gfx *load} picked by the material."""
        if self.paltab is not None and pal is not None and 0 <= pal < self.npal:
            q = _ptr(self.u32(self.paltab + pal * 12 + 4))
            if q is not None:
                return q
        if self.paltab is not None and self.npal > 0:
            want = 16 if siz == texfmt.B4 else 256
            for j in range(self.npal):
                if self.u32(self.paltab + j * 12) == want:
                    return _ptr(self.u32(self.paltab + j * 12 + 4))
        self.notes.append(f"no palette for tex {tex}")
        return p + texfmt.texel_bytes(w, h, siz)

    def _layer(self, M):
        """texture of one callback material: T = {texels, palette, header}; header = {u8 fmt, siz, cms, cmt,
        masks, maskt, shifts, shiftt; s16 w, h}; A[0xC] = {count, frames*} replaces the texels (frame 0)."""
        b = self.b
        T, A = _ptr(self.u32(M)), _ptr(self.u32(M + 4))
        if T is None:
            return None, None
        texels, pal, hdr = _ptr(self.u32(T)), _ptr(self.u32(T + 4)), _ptr(self.u32(T + 8))
        if A is not None:
            F = _ptr(self.u32(A + 0xC))
            if F is not None and self.u32(F) > 0 and _ptr(self.u32(F + 4)) is not None:
                texels = _ptr(self.u32(_ptr(self.u32(F + 4)))) or texels
        if texels is None or hdr is None:
            return None, None
        fmt, siz, cms, cmt, ms, mt, ss, sh, w, h = struct.unpack_from(">8Bhh", b, hdr)
        if fmt > 4 or siz > 3 or not (0 < w <= 1024 and 0 < h <= 1024):
            return None, None
        tile = {"cms": cms & 3, "cmt": cmt & 3, "masks": ms & 15, "maskt": mt & 15, "shifts": ss & 15,
                "shiftt": sh & 15, "uls": 0, "ult": 0, "lrs": (w - 1) * 4, "lrt": (h - 1) * 4, "pal": None}
        if fmt == texfmt.CI and pal is None:
            pal = self.palette_for(self.texels.get(texels, -1), None, texels, w, h, siz)
        return self.texture(fmt, siz, w, h, texels, pal if fmt == texfmt.CI else None), tile

    def callback_material(self, arg):
        """Draw callback 0x81000140 (Stadium 2 materials): arg = {M, M2}; M = {T texture, A animation, C colours,
        G geometry}; C = {combine[16]*, prim[5]*, env[4]*}; A[8] = colour keys {.., prim frames* @0xC, env frames*
        @0x10}; G = {u32 geometry mode bits, u16 texture scale s, t}. M2 supplies TEXEL1."""
        b = self.b
        M, M2 = _ptr(self.u32(arg)), _ptr(self.u32(arg + 4))
        if M is None or M + 16 > len(b):
            return False
        mat = dict(self.st["mat"])
        A, C, G = _ptr(self.u32(M + 4)), _ptr(self.u32(M + 8)), _ptr(self.u32(M + 0xC))
        K = _ptr(self.u32(A + 8)) if A is not None else None
        if C is not None:
            cc = _ptr(self.u32(C))
            if cc is not None:
                mat["cc"] = tuple(b[cc:cc + 16])
            pp, ep = _ptr(self.u32(C + 4)), _ptr(self.u32(C + 8))
            if K is None:
                if pp is not None:
                    mat["prim"] = np.array(list(b[pp:pp + 4])) / 255.0
                    mat["lod"] = b[pp + 4] / 255.0
                if ep is not None:
                    mat["env"] = np.array(list(b[ep:ep + 4])) / 255.0
        if K is not None:
            pp, ep = _ptr(self.u32(K + 0xC)), _ptr(self.u32(K + 0x10))
            if pp is not None:
                mat["prim"] = np.array(list(b[pp:pp + 4])) / 255.0
                mat["lod"] = b[pp + 4] / 255.0
            if ep is not None:
                mat["env"] = np.array(list(b[ep:ep + 4])) / 255.0
        if G is not None:
            self.st["geom"] |= self.u32(G) & 0xFFFFFF
            sc = struct.unpack_from(">HH", b, G + 4)
            self.st["tscale"] = (sc[0] / 65536.0, sc[1] / 65536.0)
        img, tile = self._layer(M)
        if img is not None:
            mat["img"], mat["tile"] = img, tile
        if M2 is not None and M2 + 16 <= len(b):
            img1, tile1 = self._layer(M2)
            if img1 is not None:
                mat["img1"], mat["tile1"] = img1, tile1
        self.touch(self.st, mat)
        return True

    # ---- geo layout --------------------------------------------------------------------------------------
    def _run(self):
        b = self.b
        pc = self.root_script()
        self.textab, self.ntex, self.texels = None, 0, {}
        self.paltab, self.npal = None, 0
        self.acc, self.acc_key, self.acc_mat = [], None, None
        self.bk, self.st, self.nver = {}, None, 0
        self.pending = (0, None, -1, -1, (255, 255, 255, 255))
        last_layer = None
        ident = {"M": np.eye(4), "U": np.eye(4), "S": np.ones(3), "flag": 0}
        par = [ident]            # transform of the parent node per open level
        last = ident             # transform of the last node at the current level
        slots = self.slots
        ret = []
        last_cmd = None
        for _ in range(20000):
            c = b[pc]
            if c not in SIZES:
                self.notes.append(f"geo cmd {c:02X} at {pc:X}")
                break
            nxt = pc + SIZES[c]
            P = par[-1]
            node = P
            if c == 0x01:
                break
            elif c in (0x00, 0x03):
                ret.append(nxt)
                nxt = _ptr(self.u32(pc + 4))
            elif c == 0x02:
                nxt = _ptr(self.u32(pc + 4))
            elif c == 0x04:
                nxt = ret.pop() if ret else None
            elif c == 0x05:
                par.append(last)
            elif c == 0x06:
                if len(par) > 1:
                    last = par.pop()
            elif c == 0x08:
                func, arg = struct.unpack_from(">II", b, pc + 4)
                a = _ptr(arg)
                if a is not None and not self.dry and func >> 24 == 0x81 and last_layer is not None:
                    self.use(last_layer)
                    if func & 0xFFF == 0x140:
                        if not self.callback_material(a):
                            self.notes.append(f"material {arg:08X}")
                    else:
                        d = _ptr(self.u32(a))
                        if func & 0xFFF == 0x40 and d is not None:
                            self.run_dl(d, P["M"], last_layer)       # begin list: geometry mode + texture scale
                        elif func & 0xFFF in (0x48, 0x68):
                            self.override_texels(_ptr(self.u32(a + (4 if func & 0xFFF == 0x68 else 0))))
                            self.effects += 1
                        else:
                            self.effects += 1
            elif c == 0x17:
                self.ntex = struct.unpack_from(">h", b, pc + 2)[0]
                self.textab = _ptr(self.u32(pc + 8))
                self.npal = struct.unpack_from(">h", b, pc + 4)[0]
                self.paltab = _ptr(self.u32(pc + 0xC))
                if self.textab is not None:
                    for i in range(self.ntex):
                        p = self.tex_record(i)[4]
                        if p is not None:
                            self.texels.setdefault(p, i)
            elif c == 0x1B:
                rx, ry, rz, tx, ty, tz = struct.unpack_from(">6h", b, pc + 4)
                ang = [(v << 15) // 180 for v in (rx, ry, rz)]
                M = _m4(_rot_zxy(*ang), [tx, ty, tz]) @ P["M"]
                node = {"M": M, "U": M, "S": P["S"], "flag": 0}
            elif c == 0x1C:
                s = np.array(struct.unpack_from(">3i", b, pc + 4)) / 65536.0
                M = P["M"].copy()
                M[:3] *= s[:, None]
                node = {"M": M, "U": P["U"], "S": P["S"], "flag": 0}
            elif c == 0x1D:
                slot, flags, anim = b[pc + 1], b[pc + 2], b[pc + 3]
                t = np.array(struct.unpack_from(">3h", b, pc + 4), np.float64)
                r = struct.unpack_from(">3h", b, pc + 10)
                s = np.array(struct.unpack_from(">3i", b, pc + 16)) / 65536.0
                self.joints += 1
                if flags & 1:        # scale-compensated joint (the usual case)
                    base = P["U"] if P["flag"] else P["M"]
                    U = _m4(_rot(*r), t * P["S"]) @ base
                    S = P["S"] * s
                    M = U.copy()
                    M[:3] *= S[:, None]
                    node = {"M": M, "U": U, "S": S, "flag": 1}
                else:
                    L = _m4(_rot(*r) * s[:, None], t)
                    M = L @ P["M"]
                    node = {"M": M, "U": M, "S": P["S"], "flag": 0}
                slots[slot] = node["M"]
            elif c == 0x1E:
                layer, slot, dl = b[pc + 1], struct.unpack_from(">h", b, pc + 2)[0], _ptr(self.u32(pc + 4))
                M = slots.get(slot)
                if dl is not None and M is not None:
                    self.run_dl(dl, M, layer)
                elif dl is not None:
                    self.notes.append(f"slot {slot} unset")
            elif c == 0x20:
                layer = b[pc + 1]
                rx, ry, rz, tx, ty, tz = struct.unpack_from(">6h", b, pc + 4)
                ang = [(v << 15) // 180 for v in (rx, ry, rz)]
                M = _m4(_rot_zxy(*ang), [tx, ty, tz]) @ P["M"]
                node = {"M": M, "U": M, "S": P["S"], "flag": 0}
                dl = _ptr(self.u32(pc + 0x10))
                if dl is not None:
                    self.run_dl(dl, M, layer)
            elif c == 0x21:
                layer = b[pc + 1]
                dl = _ptr(self.u32(pc + 0xC))
                self.billboards = getattr(self, "billboards", 0) + 1
                if dl is not None:
                    self.run_dl(dl, P["M"], layer)
            elif c == 0x22:
                layer, dl = b[pc + 1], _ptr(self.u32(pc + 4))
                if dl is not None:
                    self.run_dl(dl, P["M"], layer)
            elif c == 0x23:
                mode = b[pc + 1]
                dl = _ptr(self.u32(pc + 4))
                tex, pal = struct.unpack_from(">hh", b, pc + 8)
                self.pending = (mode, dl, tex, pal, tuple(b[pc + 12:pc + 16]))
            elif c == 0x25:
                if last_layer is not None and not self.dry:
                    self.reset(last_layer)
            if c in (0x1E, 0x20, 0x21, 0x22):
                last_layer = b[pc + 1]
            elif c not in (0x05, 0x06, 0x08, 0x25, 0, 1, 2, 3, 4):
                last_layer = None
            if c not in (0x05, 0x06, 0x08, 0x25, 0, 1, 2, 3, 4):
                last = node
            last_cmd = c
            pc = nxt
            if pc is None:
                break
        self.flush()

    # ---- bounds ------------------------------------------------------------------------------------------
    def points(self):
        if not self.batches:
            return np.zeros((0, 3))
        return np.vstack([x["P"].reshape(-1, 3) for x in self.batches])


class Models:
    def __init__(self, rom):
        lay = [r for r in romio.layout() if r["rom"] == ARCHIVE][0]
        arc = rom[ARCHIVE:ARCHIVE + lay.get("span", lay["size"])]
        self.files = [arc[a:a + s] for a, s in romio.archive_files(arc)]
        self.cache = {}

    def __len__(self):
        return len(self.files)

    def model(self, i):
        if i not in self.cache:
            raw = self.files[i]
            data = romio.szp_unpack(raw)[0] if romio.kind(raw[:16]) == "szp" else bytes(raw)
            self.cache[i] = Model(data, i)
        return self.cache[i]


def load(rom_bytes):
    global _cur
    _cur = Models(rom_bytes)
    return _cur


def texture_table(model_index, models=None):
    """Textures the model's materials actually bind: dicts (off, fmt, siz, w, h, pal) with file offsets; pal is
    the CI palette offset from the model's palette table (None otherwise)."""
    m = (models or _cur).model(model_index)
    return [dict(off=k[4], fmt=k[0], siz=k[1], w=k[2], h=k[3], pal=k[5]) for k in sorted(m.tex, key=lambda k: k[4])]


def _view(yaw, pitch):
    y, p = np.radians(yaw), np.radians(pitch)
    ry = np.array([[np.cos(y), 0, -np.sin(y)], [0, 1, 0], [np.sin(y), 0, np.cos(y)]])
    rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    return rx @ ry               # column vectors: v = V @ p


def _wrap(c, cm, mask, n):
    """texel coordinate (float array, already tile-relative) -> index into an n-wide image"""
    i = np.floor(c).astype(np.int64)
    if mask:
        size = 1 << mask
        if cm & 1:
            j = i & (2 * size - 1)
            i = np.where(j >= size, 2 * size - 1 - j, j)
        else:
            i = i & (size - 1)
    return np.clip(i, 0, n - 1)


def _sample(img, tile, s, t):
    h, w = img.shape[:2]
    out = None
    if tile["cms"] & 2 and tile["lrs"] is not None:
        s = np.clip(s, 0, (tile["lrs"] - tile["uls"]) / 4.0)
    if tile["cmt"] & 2 and tile["lrt"] is not None:
        t = np.clip(t, 0, (tile["lrt"] - tile["ult"]) / 4.0)
    fs, ft = s - np.floor(s), t - np.floor(t)
    for ds, dt, wgt in ((0, 0, (1 - fs) * (1 - ft)), (1, 0, fs * (1 - ft)), (0, 1, (1 - fs) * ft), (1, 1, fs * ft)):
        si, ti = s + ds, t + dt
        if tile["cms"] & 2 and tile["lrs"] is not None:
            si = np.minimum(si, (tile["lrs"] - tile["uls"]) / 4.0)
        if tile["cmt"] & 2 and tile["lrt"] is not None:
            ti = np.minimum(ti, (tile["lrt"] - tile["ult"]) / 4.0)
        tex = img[_wrap(ti, tile["cmt"], tile["maskt"], h), _wrap(si, tile["cms"], tile["masks"], w)]
        out = tex * wgt[:, None] if out is None else out + tex * wgt[:, None]
    return out


def _combine(cc, t0, t1, prim, env, shade, lod):
    """N64 2-cycle colour combiner on (n, 4) arrays: (a - b) * c + d per cycle."""
    n = len(shade)
    one, zero = np.ones((n, 4)), np.zeros((n, 4))
    t0 = one if t0 is None else t0
    t1 = one if t1 is None else t1
    P, E = np.broadcast_to(prim, (n, 4)), np.broadcast_to(env, (n, 4))
    comb = zero
    z1 = zero[:, 0]
    for cyc in (0, 8):
        if cyc == 0:
            a, b, c, d, Aa, Ab, Ac, Ad = cc[0], cc[1], cc[2], cc[3], cc[4], cc[5], cc[6], cc[7]
        else:
            a, b, c, d, Aa, Ab, Ac, Ad = cc[8], cc[9], cc[10], cc[11], cc[12], cc[13], cc[14], cc[15]
        rgb = {0: comb, 1: t0, 2: t1, 3: P, 4: shade, 5: E, 6: one}
        cs = {0: comb, 1: t0, 2: t1, 3: P, 4: shade, 5: E, 7: comb[:, 3:4], 8: t0[:, 3:4], 9: t1[:, 3:4],
              10: P[:, 3:4], 11: shade[:, 3:4], 12: E[:, 3:4], 14: one * lod}
        ra, rb, rd = rgb.get(a, zero), rgb.get(b if b != 6 else -1, zero), rgb.get(d if d != 7 else -1, zero)
        rc = cs.get(c, zero)
        col = (ra[:, :3] - rb[:, :3]) * (rc[:, :3] if rc.shape[1] == 4 else rc) + rd[:, :3]
        al = {0: comb[:, 3], 1: t0[:, 3], 2: t1[:, 3], 3: P[:, 3], 4: shade[:, 3], 5: E[:, 3], 6: one[:, 0]}
        ac = {1: t0[:, 3], 2: t1[:, 3], 3: P[:, 3], 4: shade[:, 3], 5: E[:, 3], 6: one[:, 0] * lod}
        alpha = (al.get(Aa, z1) - al.get(Ab, z1)) * ac.get(Ac, z1) + al.get(Ad, z1)
        comb = np.concatenate([col, alpha[:, None]], 1)
    return comb


def _shift(v, sh):
    return v / (1 << sh) if sh <= 10 else v * (1 << (16 - sh))


def render(model_index, size=(96, 96), yaw=30, pitch=12, bg=None, ss=3, models=None, margin=0.06, stats=None):
    """RGBA uint8 (h, w, 4) picture of one model; transparent background unless bg=(r, g, b[, a])."""
    ms = models or _cur
    m = ms.model(model_index) if not isinstance(model_index, Model) else model_index
    w, h = size
    W, H = w * ss, h * ss
    col = np.zeros((H, W, 4), np.float32)
    zb = np.full((H, W), -np.inf, np.float32)
    V = _view(yaw, pitch)
    pts = m.points()
    if len(pts):
        q = pts @ V.T
        lo, hi = q.min(0), q.max(0)
        span = max((hi[0] - lo[0]) / W, (hi[1] - lo[1]) / H, 1e-9)
        k = (1 - 2 * margin) / span
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        zspan = max(hi[2] - lo[2], 1e-6)
        ntri = 0
        order = sorted(range(len(m.batches)), key=lambda i: (m.batches[i]["mat"]["layer"] & 15, i))
        for bi in order:
            bt = m.batches[bi]
            mat = bt["mat"]
            layer = mat["layer"] & 15
            Q = bt["P"] @ V.T                                   # (n,3,3)
            X = (Q[..., 0] - cx) * k + W / 2
            Y = H / 2 - (Q[..., 1] - cy) * k
            Z = Q[..., 2]
            geom = mat["geom"]
            cc = mat["cc"]
            if geom & G_LIGHTING:
                nv = bt["N"] @ V.T
                sh = AMBIENT + DIFFUSE * np.clip(nv @ LIGHT, 0, 1)
                shade = np.concatenate([np.repeat(sh[..., None], 3, 2), np.ones(sh.shape + (1,))], 2)
            else:
                shade = bt["C"]
            layers = ((mat["img"], mat["tile"]), (mat["img1"], mat["tile1"]))
            UVs = []
            for img, tile in layers:
                if img is None:
                    UVs.append(None)
                    continue
                ts = mat.get("tscale", (1.0, 1.0))
                if geom & G_TEXTURE_GEN:
                    nv = bt["N"] @ V.T
                    UV = np.stack([(nv[..., 0] * 0.5 + 0.5) * 1024 * ts[0], (0.5 - nv[..., 1] * 0.5) * 1024 * ts[1]], -1)
                else:
                    UV = bt["UV"] / 32.0 * np.array([min(ts[0] * 1.0000153, 1.0), min(ts[1] * 1.0000153, 1.0)])
                UVs.append(np.stack([_shift(UV[..., 0], tile["shifts"]) - tile["uls"] / 4.0,
                                     _shift(UV[..., 1], tile["shiftt"]) - tile["ult"] / 4.0], -1))
            area = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
            keep = np.abs(area) > 1e-9
            if geom & G_CULL_BACK:
                keep &= area < 0
            if geom & G_CULL_FRONT:
                keep &= area > 0
            bias = zspan * (0.004 if layer in (2, 6) else 0.0)
            for ti in np.nonzero(keep)[0]:
                x, y = X[ti], Y[ti]
                x0, x1 = max(int(np.floor(x.min())), 0), min(int(np.ceil(x.max())) + 1, W)
                y0, y1 = max(int(np.floor(y.min())), 0), min(int(np.ceil(y.max())) + 1, H)
                if x0 >= x1 or y0 >= y1:
                    continue
                px = np.arange(x0, x1) + 0.5
                py = (np.arange(y0, y1) + 0.5)[:, None]
                a = area[ti]
                w0 = ((x[1] - px) * (y[2] - py) - (x[2] - px) * (y[1] - py)) / a
                w1 = ((x[2] - px) * (y[0] - py) - (x[0] - px) * (y[2] - py)) / a
                w2 = 1.0 - w0 - w1
                inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
                if not inside.any():
                    continue
                z = w0 * Z[ti, 0] + w1 * Z[ti, 1] + w2 * Z[ti, 2]
                zv = zb[y0:y1, x0:x1]
                inside &= (z + bias) >= zv
                yy, xx = np.nonzero(inside)
                if not len(yy):
                    continue
                b0, b1, b2 = w0[yy, xx], w1[yy, xx], w2[yy, xx]
                bw = np.stack([b0, b1, b2], 1)
                texs = []
                for (img, tile), UV in zip(layers, UVs):
                    if UV is None:
                        texs.append(None)
                    else:
                        st_ = bw @ UV[ti]
                        texs.append(_sample(img, tile, st_[:, 0], st_[:, 1]))
                out = _combine(cc, texs[0], texs[1] if texs[1] is not None else texs[0], mat["prim"], mat["env"],
                               bw @ shade[ti], mat["lod"])
                al = np.clip(out[:, 3], 0, 1)
                ys, xs = yy + y0, xx + x0
                if layer <= 3 or layer > 8:
                    al = np.ones_like(al)
                elif layer == 4:
                    ok = al >= 0.5
                    ys, xs, out, al = ys[ok], xs[ok], out[ok], np.ones(int(ok.sum()))
                    yy, xx = yy[ok], xx[ok]
                dst = col[ys, xs]
                rgb = np.clip(out[:, :3], 0, 1)
                dst[:, :3] = rgb * al[:, None] + dst[:, :3] * (1 - al[:, None])
                dst[:, 3] = al + dst[:, 3] * (1 - al)
                col[ys, xs] = dst
                if layer <= 4 or layer == 8:
                    zb[ys, xs] = z[yy, xx]
                ntri += 1
        if stats is not None:
            stats.update(tris=int(sum(len(x["P"]) for x in m.batches)), drawn=ntri, joints=m.joints, effects=m.effects,
                         notes=m.notes, cover=float((col[..., 3] > 0).mean()))
    img = col.reshape(h, ss, w, ss, 4)
    a = img[..., 3:4]
    rgb = (img[..., :3] * a).sum((1, 3)) / np.maximum(a.sum((1, 3)), 1e-6)     # un-premultiplied average
    out = np.concatenate([rgb, a.mean((1, 3))], 2)
    if bg is not None:
        bgc = np.array(list(bg)[:3], np.float32) / 255.0
        out[..., :3] = out[..., :3] * out[..., 3:4] + bgc * (1 - out[..., 3:4])
        out[..., 3] = 1.0
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def sheet(models, first=0, count=48, cell=96, cols=8, yaw=30, pitch=12, ss=3, bg=(58, 62, 74)):
    """contact sheet (PIL image) + per-model stats"""
    from PIL import Image, ImageDraw
    idx = list(range(first, min(first + count, len(models))))
    rows = (len(idx) + cols - 1) // cols
    im = Image.new("RGBA", (cols * cell, rows * cell), bg + (255,))
    dr = ImageDraw.Draw(im)
    report = {}
    for n, i in enumerate(idx):
        st = {}
        try:
            px = render(i, (cell, cell), yaw, pitch, ss=ss, models=models, stats=st)
            tile = Image.fromarray(px, "RGBA")
            im.alpha_composite(tile, ((n % cols) * cell, (n // cols) * cell))
        except Exception as e:                                        # noqa: BLE001
            st = {"error": repr(e)[:80]}
        report[i] = st
        dr.text(((n % cols) * cell + 2, (n // cols) * cell + 1), str(i), fill=(255, 255, 255, 255))
    return im, report


def main(argv):
    opt = {"size": 96, "yaw": 30, "pitch": 12, "ss": 3, "cols": 8}
    for i, a in enumerate(argv):
        if a.startswith("--") and a[2:] in opt and i + 1 < len(argv):
            opt[a[2:]] = float(argv[i + 1]) if a[2:] in ("yaw", "pitch") else int(argv[i + 1])
    pos = []
    skip = False
    for a in argv:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = True
            continue
        pos.append(a)
    rom_path, out = pos[0], pos[1]
    for attempt in range(5):
        try:
            rom = open(rom_path, "rb").read()
            models = load(rom)
            break
        except Exception as e:                                        # noqa: BLE001  (file being rewritten)
            if attempt == 4:
                raise
            time.sleep(3)
    first = int(pos[2]) if len(pos) > 2 else 0
    count = int(pos[3]) if len(pos) > 3 else len(models) - first
    t0 = time.time()
    im, rep = sheet(models, first, count, opt["size"], opt["cols"], opt["yaw"], opt["pitch"], opt["ss"])
    im.save(out)
    bad = {i: s for i, s in rep.items() if s.get("error") or s.get("notes") or s.get("cover", 0) < 0.03}
    print(f"{out}: models {first}..{first + len(rep) - 1}, {time.time() - t0:.1f}s, "
          f"{sum(s.get('tris', 0) for s in rep.values())} tris, {len(bad)} flagged")
    for i, s in list(bad.items())[:12]:
        print(f"  {i}: {s.get('error') or ''} cover={s.get('cover', 0):.2f} {'; '.join(s.get('notes', [])[:2])}")


if __name__ == "__main__":
    main(sys.argv[1:])
