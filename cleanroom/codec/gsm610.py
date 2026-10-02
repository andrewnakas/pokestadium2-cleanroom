"""GSM 06.10 full-rate speech codec (RPE-LTP), written from the public ETSI algorithm description.

A frame is 160 samples and 76 parameters:
    LARc[8], then 4 sub-frames of (Nc, bc, Mc, xmaxc, xMc[13])      -> 260 bits (WIDTHS)

decode(frames)            -> int16 samples.  Integer arithmetic of the standard decoder (bit-exact).
                             A frame given as None is 160 zero samples with the decoder state held
                             (used by containers with silent frames).
encode(pcm, skip=None)    -> list of 76-int lists (None where skip[f]).  Standard encoder structure
                             (pre-processing, LPC -> LAR, short-term analysis lattice, LTP, RPE-APCM);
                             pre-processing and the Schur recursion use floats, so it is not bit-exact
                             with a reference encoder, but everything the decoder sees is standard.
params_to_int / int_to_params   fields in order, each LSB first (field 0 at bit 0)
to_gsm33 / from_gsm33           the usual 33-byte frame (0xD nibble, fields MSB first)
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

WIDTHS = [6, 6, 5, 5, 4, 4, 3, 3] + [7, 2, 2, 6] * 0
for _ in range(4):
    WIDTHS += [7, 2, 2, 6] + [3] * 13
FRAME_BITS = sum(WIDTHS)            # 260
NPARAM = len(WIDTHS)                # 76

MIC = np.array([-32, -32, -16, -16, -8, -8, -4, -4], np.int64)
MAC = np.array([31, 31, 15, 15, 7, 7, 3, 3], np.int64)
B = np.array([0, 0, 2048, -2560, 94, -1792, -341, -1144], np.int64)
A = np.array([20480, 20480, 20480, 20480, 13964, 15360, 8534, 9036], np.int64)
INVA = np.array([13107, 13107, 13107, 13107, 19223, 17476, 31454, 29708], np.int64)
FAC = [18431, 20479, 22527, 24575, 26623, 28671, 30719, 32767]
NRFAC = [29128, 26215, 23832, 21846, 20165, 18725, 17476, 16384]
QLB = [3277, 11469, 21299, 32767]
H = np.array([-134, -374, 0, 2054, 5741, 8192, 5741, 2054, 0, -374, -134], np.int64)
REGIONS = (13, 14, 13, 120)         # LAR interpolation regions inside a frame


def _exp_mant(xmaxc):
    e = 0
    if xmaxc > 15:
        e = (xmaxc >> 3) - 1
    m = xmaxc - (e << 3)
    if m == 0:
        return -4, 7
    while m <= 7:
        m = (m << 1) | 1
        e -= 1
    return e, m - 8


EXP_MANT = [_exp_mant(i) for i in range(64)]


def _sat(x):
    return np.clip(x, -32768, 32767)


def _larpp(larc):
    """coded LARs (n, 8) -> decoded LARpp"""
    t = (larc + MIC) << 10
    t = _sat(t - (B << 1))
    t = (INVA * t + 16384) >> 15
    return _sat(t + t)


def _rp_regions(larc):
    """coded LARs of consecutive coded frames (n, 8) -> reflection coefficients (n, 4 regions, 8)"""
    c = _larpp(np.asarray(larc, np.int64).reshape(-1, 8))
    p = np.vstack([np.zeros((1, 8), np.int64), c[:-1]])
    lar = np.stack([(p >> 2) + (c >> 2) + (p >> 1), (p >> 1) + (c >> 1), (p >> 2) + (c >> 2) + (c >> 1), c], 1)
    t = np.minimum(np.abs(lar), 32767)
    r = np.where(t < 11059, t << 1, np.where(t < 20070, t + 11059, np.minimum((t >> 2) + 26112, 32767)))
    return np.where(lar < 0, -r, r)


# ---------------------------------------------------------------- decoder
def decode(frames):
    n = len(frames)
    coded = [f for f in frames if f is not None]
    out = np.zeros(n * 160, np.int16)
    if not coded:
        return out
    rps = _rp_regions(np.array([f[:8] for f in coded])).tolist()
    v = [0] * 9
    hist = [0] * 120
    nrp, msr, ci = 40, 0, 0
    for fi, p in enumerate(frames):
        if p is None:
            continue
        wt = []
        for j in range(4):
            o = 8 + 17 * j
            nc, bc, mc, xmaxc = p[o], p[o + 1], p[o + 2], p[o + 3]
            e, m = EXP_MANT[xmaxc]
            f1, t2 = FAC[m], 6 - e
            t3 = (1 << (t2 - 1)) if t2 >= 1 else 0
            erp = [0] * 40
            for i in range(13):
                erp[mc + 3 * i] = ((f1 * (((p[o + 4 + i] << 1) - 7) << 12) + 16384 >> 15) + t3) >> t2
            if 40 <= nc <= 120:
                nrp = nc
            brp, base = QLB[bc], 120 - nrp
            new = [erp[k] + (brp * hist[base + k] + 16384 >> 15) for k in range(40)]
            new = [32767 if x > 32767 else -32768 if x < -32768 else x for x in new]
            hist = hist[40:] + new
            wt += new
        rp4 = rps[ci]
        ci += 1
        k, res = 0, []
        for reg in range(4):
            rr = rp4[reg]
            r7 = rr[7]
            idx = (6, 5, 4, 3, 2, 1, 0)
            for k in range(k, k + REGIONS[reg]):
                sri = wt[k] - (r7 * v[7] + 16384 >> 15)
                if sri > 32767:
                    sri = 32767
                elif sri < -32768:
                    sri = -32768
                for i in idx:
                    r, vi = rr[i], v[i]
                    sri -= r * vi + 16384 >> 15
                    if sri > 32767:
                        sri = 32767
                    elif sri < -32768:
                        sri = -32768
                    t = vi + (r * sri + 16384 >> 15)
                    v[i + 1] = 32767 if t > 32767 else -32768 if t < -32768 else t
                v[0] = sri
                msr = sri + (msr * 28180 + 16384 >> 15)            # de-emphasis
                if msr > 32767:
                    msr = 32767
                elif msr < -32768:
                    msr = -32768
                t = msr + msr
                res.append((32767 if t > 32767 else -32768 if t < -32768 else t) & -8)
            k += 1
        out[fi * 160:fi * 160 + 160] = res
    return out


# ---------------------------------------------------------------- encoder
def _lpc(so, nf):
    """pre-processed signal -> coded LARs (nf, 8)"""
    x = so.reshape(nf, 160).astype(np.float64)
    acf = np.stack([(x[:, k:] * x[:, :160 - k]).sum(1) for k in range(9)], 1)
    P, K = acf.copy(), acf.copy()
    r = np.zeros((nf, 8))
    alive = acf[:, 0] > 0
    for n in range(1, 9):                                           # Schur recursion
        alive &= (P[:, 0] >= np.abs(P[:, 1])) & (P[:, 0] > 0)
        rn = np.where(alive, -P[:, 1] / np.where(alive, P[:, 0], 1.0), 0.0)
        r[:, n - 1] = rn
        if n == 8:
            break
        P[:, 0] += P[:, 1] * rn
        hi = 9 - n
        pn = P[:, 2:hi + 1] + K[:, 1:hi] * rn[:, None]
        K[:, 1:hi] += P[:, 2:hi + 1] * rn[:, None]
        P[:, 1:hi] = pn
    r16 = np.clip(np.rint(r * 32768), -32767, 32767).astype(np.int64)
    t = np.abs(r16)
    lar = np.where(t < 22118, t >> 1, np.where(t < 31130, t - 11059, (t - 26112) << 2))
    lar = np.where(r16 < 0, -lar, lar)
    q = (((A * lar) >> 15) + B + 256) >> 9
    return np.clip(q, MIC, MAC) - MIC


def encode(pcm, skip=None):
    from scipy.signal import lfilter
    s = np.asarray(pcm, np.int16).astype(np.int64)
    nf = -(-len(s) // 160)
    s = np.concatenate([s, np.zeros(nf * 160 - len(s), np.int64)])
    skip = np.zeros(nf, bool) if skip is None else np.asarray(skip, bool)
    keep = ~skip
    # pre-processing: downscale, offset compensation, pre-emphasis
    a, b = 32735 / 32768, 28180 / 32768
    so = lfilter(np.convolve([1.0, -1.0], [1.0, -b]), [1.0, -a], ((s >> 3) << 2).astype(np.float64))
    so = np.clip(np.rint(so), -32768, 32767).astype(np.int64)
    larc = _lpc(so, nf)
    # short-term analysis lattice with the decoder's interpolated coefficients
    reg = np.zeros((nf, 4, 8), np.int64)
    if keep.any():
        reg[keep] = _rp_regions(larc[keep])
    rp = np.repeat(reg.reshape(nf * 4, 8), np.tile(REGIONS, nf), axis=0)
    d = sav = so
    for i in range(8):
        u = np.concatenate([[0], sav[:-1]])
        ri = rp[:, i]
        sav, d = _sat(u + ((ri * d + 16384) >> 15)), _sat(d + ((ri * u + 16384) >> 15))
    # LTP + RPE per sub-frame
    hist = np.zeros(120, np.int64)
    win = sliding_window_view(hist, 40)                             # row j = lag 120 - j
    out = []
    lc = larc.tolist()
    for f in range(nf):
        if skip[f]:
            out.append(None)
            continue
        p = lc[f]
        for j in range(4):
            ds = d[f * 160 + j * 40:f * 160 + j * 40 + 40]
            corr = (win @ ds)[::-1]                                 # index = lag - 40
            i = int(corr.argmax())
            lmax = int(corr[i])
            nc = 40 + i if lmax > 0 else 40
            past = hist[120 - nc:160 - nc]
            bc = 0
            if lmax > 0:
                power = int(past @ past)
                bc = 3 if lmax >= power else (lmax * 5 > power) + (lmax * 2 > power) + (lmax * 5 > power * 4)
            dpp = (QLB[bc] * past + 16384) >> 15
            e = _sat(ds - dpp)
            x = _sat((np.convolve(e, H)[5:45] + 4096) >> 13)
            xs = x >> 2
            em = [int(xs[m:m + 37:3] @ xs[m:m + 37:3]) for m in range(4)]
            mc = em.index(max(em))
            xm = x[mc:mc + 37:3]
            xmax = min(int(np.abs(xm).max()), 32767)
            ex = min(6, (xmax >> 9).bit_length())
            xmaxc = (xmax >> (ex + 5)) + (ex << 3)
            ex, mant = EXP_MANT[xmaxc]
            t2 = 6 - ex
            xmc = np.clip(((((xm << t2) * NRFAC[mant]) >> 15) >> 12) + 4, 0, 7)
            t3 = (1 << (t2 - 1)) if t2 >= 1 else 0
            xmp = (((FAC[mant] * (((xmc << 1) - 7) << 12) + 16384) >> 15) + t3) >> t2
            ep = np.zeros(40, np.int64)
            ep[mc:mc + 37:3] = xmp
            hist[:80] = hist[40:].copy()
            hist[80:] = _sat(ep + dpp)
            p += [nc, bc, mc, xmaxc] + xmc.tolist()
        out.append(p)
    return out


# ---------------------------------------------------------------- bit packing
def params_to_int(p):
    v = pos = 0
    for w, x in zip(WIDTHS, p):
        v |= (x & ((1 << w) - 1)) << pos
        pos += w
    return v


def int_to_params(v):
    p = []
    for w in WIDTHS:
        p.append(v & ((1 << w) - 1))
        v >>= w
    return p


def to_gsm33(p):
    v = 0xD
    for w, x in zip(WIDTHS, p):
        v = (v << w) | (x & ((1 << w) - 1))
    return v.to_bytes(33, "big")


def from_gsm33(b):
    v = int.from_bytes(b[:33], "big")
    assert v >> 260 == 0xD
    p, pos = [], 260
    for w in WIDTHS:
        pos -= w
        p.append((v >> pos) & ((1 << w) - 1))
    return p
