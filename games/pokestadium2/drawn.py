"""Drawn overrides (clean room): pictures that must read correctly are drawn from scratch.

    hooks(spec dir, rom) -> {"<space>:<off hex>": RGBA array, "__jpeg__": {key: RGB}, "__bytes__": [...]}

Fonts: the six font files (archive 0437750) hold 177 IA8 cells behind a 0xB0-byte advance table (kept fact,
read from the ROM being built). The glyph order below is the game's text encoding (a fact); every glyph is
drawn with our own stroke font (cleanroom.gfx.strokefont) and fitted to its advance.
"""
import json

import numpy as np

from cleanroom.gfx import strokefont as sf

FONT_ARC = "0437750"
FONT_HEAD = 0xB0
G = sf.G


def T(lines, sx=1.0, dx=0.0, dy=0.0, sy=None):
    sy = sx if sy is None else sy
    return [[(dx + x * sx, dy + y * sy) for x, y in line] for line in lines]


def width(lines):
    xs = [x for line in lines for x, _ in line]
    return max(xs) - min(xs)


def left(lines):
    m = min(x for line in lines for x, _ in line)
    return T(lines, 1.0, -m, 0.0)


ACC = {
    "acute": [[(1.4, 1.2), (2.8, 0.0)]],
    "grave": [[(1.2, 0.0), (2.6, 1.2)]],
    "circ": [[(0.9, 1.2), (2.0, 0.0), (3.1, 1.2)]],
    "uml": [[(1.0, 0.5), (1.0, 0.5)], [(3.0, 0.5), (3.0, 0.5)]],
    "tilde": [[(0.6, 1.0), (1.5, 0.2), (2.5, 1.0), (3.4, 0.2)]],
}
CEDILLA = [[(2.0, 6.0), (2.5, 6.8), (1.6, 7.4)]]
DOTLESS_I = [[(0, 2), (0, 6)]]


def accented(base, acc):
    if base == "i":
        lines = T(DOTLESS_I, 1.0, 2.0, 0.0)
        return left(lines + ACC[acc])
    lines = left(G[base])
    cx = width(lines) / 2 - 2.0
    if base.isupper():
        lines = T(lines, 1.0, 0.0, 2.2, sy=3.8 / 6.0)
        return lines + T(ACC[acc], 1.0, cx, 0.0, sy=0.75)
    return lines + T(ACC[acc], 1.0, cx, 0.0)


def pair(a, b, s=0.56):
    return left(G[a]) and T(left(G[a]), s) + T(left(G[b]) if isinstance(b, str) else b, s, 2.5, 2.9)


def apos_before(c):
    return [[(0.5, 0.0), (0.1, 1.5)]] + T(left(G[c]), 1.0, 1.5, 0.0)


def apos_after(c):
    lines = left(G[c])
    return lines + [[(width(lines) + 1.2, 0.0), (width(lines) + 0.8, 1.5)]]


def flip(lines):
    return [[(x, 7.0 - y) for x, y in line] for line in lines]


def charmap():
    """glyph index -> polylines (design grid 4 x 7.5) or ("poly", points) or None"""
    m = {}
    put = m.__setitem__
    put(0x01, left(G["P"]) + [[(-0.8, 4.2), (2.6, 4.2)], [(-0.8, 5.1), (2.6, 5.1)]])
    put(0x02, [[(0.2, 3.4), (1.2, 2.6), (2.4, 2.6), (3.2, 3.4), (3.2, 5.2), (2.4, 6), (1.2, 6), (0.2, 5.2), (0.2, 3.4)],
               [(2.8, 2.8), (4.4, 0.4)], [(2.9, 0.4), (4.4, 0.4), (4.4, 1.9)]])
    put(0x03, left(G["("]))
    put(0x04, left(G[")"]))
    put(0x05, [[(0, 3.2), (0, 3.2)]])
    put(0x06, left(G["%"]))
    put(0x07, [[(1.6, 0), (0, 0), (0, 6.8), (1.6, 6.8)]])
    put(0x08, [[(0, 0), (1.6, 0), (1.6, 6.8), (0, 6.8)]])
    put(0x09, [[(0.6, 0), (1.8, 0), (2.4, 0.6), (2.4, 1.6), (1.8, 2.2), (0.6, 2.2), (0, 1.6), (0, 0.6), (0.6, 0)]])
    put(0x0D, left(G["&"]))
    put(0x0E, [[(0, 3.4), (1, 2.6), (3, 3.6), (4, 2.8)]])
    put(0x0F, ("poly", [(0.0, 1.6), (7.0, 1.6), (3.5, 5.6)], 7.0))
    for i, c in enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        put(0x10 + i, left(G[c]))
    put(0x34, left(G["!"]))
    put(0x35, [[(0, 0), (0, 1.8)], [(2.2, 0), (2.2, 1.8)]])
    put(0x36, [[(0, 2.6), (3, 5.6)], [(3, 2.6), (0, 5.6)]])
    put(0x37, [[(0.4, 0), (0, 1.8)]])
    put(0x38, left(G["*"]))
    put(0x39, left(G["+"]))
    put(0x3A, left(G[","]))
    put(0x3B, [[(0, 3.2), (3, 3.2)]])
    put(0x3C, left(G["."]))
    put(0x3D, left(G["/"]))
    put(0x3E, left(G[":"]))
    put(0x3F, left(G["="]))
    put(0x40, left(G["?"]))
    put(0x41, [[(1, 0), (3, 0), (4, 1), (4, 2.6), (3, 3.6), (1, 3.6), (0, 2.6), (0, 1), (1, 0)],
               [(2, 3.6), (2, 6.8)], [(0.7, 5.3), (3.3, 5.3)]])
    put(0x42, [[(0.6, 2.5), (0.6, 2.5)], [(0.6, 5.6), (0, 7)]])
    put(0x43, pair("P", "K"))
    put(0x44, pair("M", "N"))
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        put(0x45 + i, left(G[c]))
    seq = [("A", "uml"), ("O", "uml"), ("U", "uml"), ("a", "uml"), ("o", "uml"), ("u", "uml"), None,
           ("A", "acute"), ("A", "grave"), ("A", "circ"), ("C", "ced"), ("E", "acute"), ("E", "grave"), ("E", "circ"),
           ("E", "uml"), ("O", "circ"), ("I", "uml"), ("U", "grave"), ("U", "circ"), ("a", "acute"), ("a", "grave"),
           ("a", "circ"), ("c", "ced"), ("e", "acute"), ("e", "grave"), ("e", "circ"), ("e", "uml"), ("o", "circ"),
           ("i", "uml"), ("u", "grave"), ("u", "circ"), ("I", "acute"), ("I", "grave"), ("I", "circ"), ("N", "tilde"),
           ("O", "acute"), ("O", "grave"), ("U", "acute"), ("i", "acute"), ("i", "grave"), ("i", "circ"),
           ("n", "tilde"), ("o", "acute"), ("o", "grave"), ("u", "acute")]
    for i, e in enumerate(seq):
        if e is None:                                      # sharp s
            put(0x5F + i, [[(0, 7), (0, 1), (1, 0), (2.4, 0), (3.2, 0.9), (3.2, 2), (2, 3), (3.6, 4), (3.6, 5.2),
                            (2.7, 6), (1.5, 6)]])
        elif e[1] == "ced":
            put(0x5F + i, left(G[e[0]]) + CEDILLA)
        else:
            put(0x5F + i, accented(*e))
    put(0x8C, [[(0.6, 0), (1.8, 0), (2.4, 0.6), (2.4, 1.6), (1.8, 2.2), (0.6, 2.2), (0, 1.6), (0, 0.6), (0.6, 0)]])
    put(0x8D, T(left(G["a"]), 0.6, 0.0, -1.2))
    put(0x8E, flip(left(G["?"])))
    put(0x8F, flip(left(G["!"])))
    put(0x90, T(left(G["P"]), 0.56) + T(left(G["o"]), 0.56, 2.5, 2.9))
    put(0x91, T(left(G["K"]), 0.56) + T(accented("e", "acute"), 0.56, 2.5, 2.9))
    put(0x92, [[(0, 6), (0, 6)], [(1.8, 6), (1.8, 6)], [(3.6, 6), (3.6, 6)]])
    for i, c in enumerate("dlmrstv"):
        put(0x93 + i, apos_before(c))
    put(0x9A, [[(0.4, 3.4), (0.4, 0.4), (2.6, 0.4)]])
    put(0x9B, [[(2.6, 3.0), (2.6, 6.0), (0.4, 6.0)]])
    for i, c in enumerate("cdjlmnpstuy"):
        put(0x9C + i, apos_after(c))
    return m


def glyph_cell(lines, cw, ch, adv, style):
    """IA cell (ch, cw, 4): white fill, dark outline, alpha = coverage of both"""
    ss = 3
    H, W = ch * ss, cw * ss
    fill = np.zeros((H, W), np.float32)
    th = max(0.62, ch * (0.05 if style == "light" else 0.062)) * ss
    sy = (H - 3.0 * ss - 2 * th) / 7.5
    oy = 1.5 * ss + th * 0.6
    if isinstance(lines, tuple):                           # filled polygon
        from cleanroom.gfx.glyphs import _poly_mask
        pts = [(1.5 + x * (adv - 3.0) / lines[2], oy / ss + y * sy / ss) for x, y in lines[1]]
        fill_s = _poly_mask(cw, ch, pts)
    else:
        span = max(1e-3, width(lines))
        room = max(1.0, (adv - 2.2) * ss - 2 * th)
        sx = min(sy * 0.92, room / span)
        minx = min(x for line in lines for x, _ in line)
        ox = max(1.0 * ss + th, (adv * ss - span * sx) / 2) - minx * sx
        sf._stroke(fill, lines, ox, oy, sx, sy, th)
        fill_s = fill.reshape(ch, ss, cw, ss).mean((1, 3))
    fill_s = np.clip(fill_s * 1.25, 0, 1)
    out = np.zeros((ch, cw), np.float32)                   # outline: the fill grown by one pixel
    p = np.pad(fill_s, 1)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out = np.maximum(out, p[dy:dy + ch, dx:dx + cw] * (1.0 if dx == 1 or dy == 1 else 0.7))
    alpha = np.maximum(fill_s, out)
    cell = np.zeros((ch, cw, 4), np.float32)
    cell[..., :3] = (255 * fill_s / np.maximum(alpha, 1e-3))[..., None]
    cell[..., 3] = alpha * 255
    return cell


def font_texture(base, widths, cw, ch, ng, style):
    m = charmap()
    out = base.astype(np.float32).copy()
    for i in range(min(ng, 0xB0)):
        cell = np.zeros((ch, cw, 4), np.float32)
        if i in m and m[i]:
            adv = widths[i] if i < len(widths) and widths[i] else cw
            cell = glyph_cell(m[i], cw, ch, min(adv, cw), style)
        out[i * ch:(i + 1) * ch] = cell
    return np.clip(out, 0, 255).astype(np.uint8)


# ---- text baked into UI images: re-typeset from spec/labels.json (wording and colours are kept facts) ----

LABEL_KINDS = ("text", "button", "frame")


def can_set(text):
    return all(c == " " or sf.glyph(c) or c in "é" for c in text)


def line_mask(text, bold):
    """tight coverage mask of one line at a large size"""
    hh = 96
    th = hh * (0.105 if bold else 0.075)
    if "é" in text:                                        # POKéMON: small e with an acute
        parts = text.split("é")
        segs = []
        for i, p in enumerate(parts):
            if p:
                segs.append(sf.render_line(p, hh, thickness=th))
            if i < len(parts) - 1:
                cell = np.zeros((hh, int(hh * 0.66)), np.float32)
                sy = (hh - 2 * th) / 7.5
                sf._stroke(cell, accented("e", "acute"), th + 1, th, sy * 1.05, sy, th * 0.62)
                segs.append(cell)
        m = np.concatenate(segs, 1)
    else:
        m = sf.render_line(text, hh, thickness=th)
    ys, xs = np.nonzero(m > 0.05)
    if not len(ys):
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def text_mask(lines, w, h, bold=True, italic=False):
    from PIL import Image
    out = np.zeros((h, w), np.float32)
    n = len(lines)
    gap = max(1, int(round(h * 0.06)))
    slot_h = (h - gap * (n + 1)) / n
    if slot_h < 3 or w < 4:
        return out
    for i, text in enumerate(lines):
        m = line_mask(text.strip(), bold)
        if m is None:
            continue
        if italic:
            sh = np.zeros((m.shape[0], m.shape[1] + int(m.shape[0] * 0.2) + 1), np.float32)
            for r in range(m.shape[0]):
                o = int((m.shape[0] - 1 - r) * 0.2)
                sh[r, o:o + m.shape[1]] = m[r]
            m = sh
        k = slot_h / m.shape[0]
        tw = m.shape[1] * k
        room = w - 2
        if tw > room:                                      # squeeze, then shrink
            k2 = max(room / tw, 0.62)
            tw2 = tw * k2
            if tw2 > room:
                k *= room / tw2
                tw2 = room
            tw = tw2
        tw, th_ = max(1, int(round(tw))), max(1, int(round(m.shape[0] * k)))
        r = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((tw, th_), Image.LANCZOS), np.float32) / 255
        y0 = int(round(gap + i * (slot_h + gap) + (slot_h - th_) / 2))
        x0 = (w - tw) // 2
        y1, x1 = min(h, y0 + th_), min(w, x0 + tw)
        out[y0:y1, x0:x1] = np.maximum(out[y0:y1, x0:x1], r[:y1 - y0, :x1 - x0])
    return np.clip(out * 1.2, 0, 1)


def label_image(base, lab):
    """base: grid picture (kept colours + alpha outline); lab: label -> RGBA with the wording drawn in"""
    h, w = base.shape[:2]
    a = base[..., 3]
    solid = lab.get("bg") is not None or lab["kind"] != "text"
    ys, xs = np.nonzero(a > 40)
    if len(ys) and solid:
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    else:
        y0, y1, x0, x1 = 0, h, 0, w
    if lab["kind"] == "button":                            # lettering sits inside the button face
        my, mx = int((y1 - y0) * 0.2), int((x1 - x0) * 0.2)
        y0, y1, x0, x1 = y0 + my, y1 - my, x0 + mx, x1 - mx
    bh, bw = y1 - y0, x1 - x0
    if bh < 4 or bw < 4:
        return None
    rot = lab.get("rot", 0)
    lines = lab["text"]
    if rot:
        m = text_mask(lines, bh, bw, True, lab.get("italic", False))
        m = np.rot90(m, 1 if rot < 0 else -1)
    else:
        m = text_mask(lines, bw, bh, True, lab.get("italic", False))
    full = np.zeros((h, w), np.float32)
    full[y0:y1, x0:x1] = m
    ink = np.array(lab.get("ink") or [255, 255, 255], np.float32)
    oc = lab.get("outline")
    out = base.astype(np.float32).copy()
    if not solid:
        out[..., 3] = 0
        out[..., :3] = ink
    edge = np.zeros_like(full)
    if oc is not None and min(h, w) >= 10:
        p = np.pad(full, 1)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                edge = np.maximum(edge, p[dy:dy + h, dx:dx + w])
        out[..., :3] = out[..., :3] * (1 - edge[..., None]) + np.array(oc, np.float32) * edge[..., None]
    out[..., :3] = out[..., :3] * (1 - full[..., None]) + ink * full[..., None]
    out[..., 3] = np.maximum(out[..., 3], np.maximum(full, edge) * 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def hooks(spec, rom):
    from games.pokestadium2 import generate, romio
    out = {}
    texs = json.load(open(f"{spec}/textures.json"))
    labels = json.load(open(f"{spec}/labels.json", encoding="utf-8"))
    sp = None
    nl = 0
    for t in texs:
        key = f"{t['space']}:{t['off']:X}"
        lab = labels.get(key)
        if lab and lab.get("text") and lab.get("kind") in LABEL_KINDS and all(can_set(x) for x in lab["text"]):
            img = label_image(generate.from_grid(key, t, t["w"], t["h"]), lab)
            if img is not None:
                out[key] = img
                nl += 1
            continue
        if t["space"].split("/")[0] != FONT_ARC or t["off"] != FONT_HEAD:
            continue
        if sp is None:
            sp = romio.spaces(rom, kinds=("szp",))
        fi = int(t["space"].split("/")[1])
        cw = t["w"]
        ch = {0: 10, 1: 12, 2: 16, 3: 20, 4: 24, 5: 16}[fi]
        ng = t["h"] // ch
        widths = list(sp[t["space"]][:FONT_HEAD])          # advance table: kept
        base = generate.from_grid(key, t, t["w"], t["h"])
        out[key] = font_texture(base, widths, cw, ch, ng, "light" if fi == 5 else "bold")
    print(f"drawn: {nl} text labels, {len(out) - nl} fonts")
    return out


if __name__ == "__main__":                                 # dev: font sheet -> PNG
    import sys
    from PIL import Image
    cw, ch = 24, 24
    w = [14] * 177
    w[0x0F] = 24
    tex = font_texture(np.zeros((ch * 177, cw, 4), np.uint8), w, cw, ch, 177, "bold")
    cells = tex.reshape(177, ch, cw, 4)
    sheet = np.full((12 * ch, 16 * cw, 3), 60, np.float32)
    for i in range(177):
        y, x = (i // 16) * ch, (i % 16) * cw
        a = cells[i][..., 3:4] / 255.0
        sheet[y:y + ch, x:x + cw] = sheet[y:y + ch, x:x + cw] * (1 - a) + cells[i][..., :3] * a
    Image.fromarray(sheet.astype(np.uint8)).resize((16 * cw * 2, 12 * ch * 2), Image.NEAREST).save(sys.argv[1])
