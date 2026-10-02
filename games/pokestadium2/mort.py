"""Factor 5 "MORT" speech clips (Pokemon Stadium 2 sample codec 5): GSM 06.10 frames in a run-length
framed bitstream.  Format: docs/AUDIO.md.  Codec: cleanroom/codec/gsm610.py.

unpack(clip) -> (rate, frames)      frames: None (silent) or 76 GSM parameters
pack(rate, frames, pad_to=None)     exact container syntax (greedy runs: silent <= 16, coded <= 128)
decode(clip) -> int16               encode(pcm, n_frames, max_bytes) -> clip bytes

CLI (dirty room; reads the ROM, writes only under D:/n64work/pokestadium2/dirty and spec/voice_lines.json):
    python games/pokestadium2/mort.py test [ROM]         container / decoder / encoder checks
    python games/pokestadium2/mort.py transcribe [ROM]   decode all clips, whisper, write the spec
"""
import itertools
import json
import os
import struct
import sys

import numpy as np

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cleanroom.codec import gsm610

W = np.array(gsm610.WIDTHS)
_FIELD = np.repeat(np.arange(len(W)), W)                    # bit -> field
_SHIFT = np.concatenate([np.arange(w) for w in W])          # bit -> bit inside the field (LSB first)
_START = np.concatenate([[0], np.cumsum(W)[:-1]])
_ARANGE = np.arange(gsm610.FRAME_BITS)


def _runs(silent):
    """frame mask -> [(is_silent, count)] with the container's run limits"""
    out = []
    for s, g in itertools.groupby(silent):
        n, lim = len(list(g)), 16 if s else 128
        while n > 0:
            out.append((s, min(n, lim)))
            n -= lim
    return out


def _bits_needed(silent):
    return sum(5 if s else 8 + 260 * n for s, n in _runs(silent))


def clip_bytes_for(silent):
    """clip length for a silent-frame mask"""
    return 12 + 4 * (_bits_needed(silent) // 32 + 1)


def unpack(clip, info=None):
    assert clip[:4] == b"MORT"
    nfr, rate, words = struct.unpack_from(">HHI", clip, 4)
    body = np.frombuffer(clip, ">u4", (len(clip) - 12) // 4, 12).astype("<u4")
    bits = np.unpackbits(body.view(np.uint8), bitorder="little")
    pos, left, starts, mask = 0, nfr, [], []
    while left > 0:
        if bits[pos]:
            n = int(bits[pos + 1:pos + 5] @ (1, 2, 4, 8)) + 1
            pos += 5
            n = min(n, left)
            mask += [True] * n
        else:
            n = int(bits[pos + 1:pos + 8] @ (1, 2, 4, 8, 16, 32, 64)) + 1
            pos += 8
            n = min(n, left)
            starts += range(pos, pos + 260 * n, 260)
            mask += [False] * n
            pos += 260 * n
        left -= n
    frames = [None] * nfr
    if starts:
        fb = bits[np.array(starts)[:, None] + _ARANGE].astype(np.int64) << _SHIFT
        par = iter(np.add.reduceat(fb, _START, axis=1).tolist())
        frames = [None if m else next(par) for m in mask]
    if info is not None:
        info.update(bits=pos, words=words & 0xFFFFFF, tail=int(bits[pos:].sum()))
    return rate, frames


def pack(rate, frames, pad_to=None):
    silent = [f is None for f in frames]
    total = _bits_needed(silent)
    nw = total // 32 + 1                                     # always 1..32 unused bits at the end
    if pad_to:
        assert pad_to % 4 == 0 and pad_to >= 12 + 4 * nw, "clip does not fit"
        nw = (pad_to - 12) // 4
    bits = np.zeros(nw * 32, np.uint8)
    pos, starts = 0, []
    for s, n in _runs(silent):
        if s:
            bits[pos:pos + 5] = [1] + [(n - 1) >> i & 1 for i in range(4)]
            pos += 5
        else:
            bits[pos + 1:pos + 8] = [(n - 1) >> i & 1 for i in range(7)]
            pos += 8
            starts += range(pos, pos + 260 * n, 260)
            pos += 260 * n
    if starts:
        par = np.array([f for f in frames if f is not None], np.int64)
        bits[np.array(starts)[:, None] + _ARANGE] = (par[:, _FIELD] >> _SHIFT) & 1
    body = np.packbits(bits, bitorder="little").view("<u4").astype(">u4").tobytes()
    return b"MORT" + struct.pack(">HHI", len(frames), rate, 3 + nw) + body


def decode(clip):
    return gsm610.decode(unpack(clip)[1])


def encode(pcm, n_frames, max_bytes, rate=16000, silence_rms=24.0, pad=False):
    """16 kHz int16 -> clip of exactly n_frames frames, at most max_bytes long.  Frames quieter than
    silence_rms become silent runs; while the clip is too long, the quietest coded frames follow."""
    x = np.zeros(n_frames * 160, np.int16)
    pcm = np.asarray(pcm, np.int16)[:len(x)]
    x[:len(pcm)] = pcm
    rms = np.sqrt((x.reshape(n_frames, 160).astype(np.float64) ** 2).mean(1))
    silent = rms < silence_rms
    order = np.argsort(rms, kind="stable")
    while clip_bytes_for(silent) > max_bytes:
        coded = [i for i in order if not silent[i]]
        if not coded:
            raise ValueError("%d frames do not fit in %d bytes" % (n_frames, max_bytes))
        need = max(1, ((clip_bytes_for(silent) - max_bytes) * 8 - 31) // 260)
        silent[coded[:need]] = True
    return pack(rate, gsm610.encode(x, skip=silent), pad_to=max_bytes if pad else None)


# ---------------------------------------------------------------- dirty-room tools
ROM = "D:/n64work/pokestadium2/rom/baserom.z64"
DIRTY = "D:/n64work/pokestadium2/dirty"
SPEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spec", "voice_lines.json")


def clips(rom):
    from games.pokestadium2 import audiofmt
    n = {}
    out = []
    for s in audiofmt.parse(rom)["samples"]:
        if s["codec"] == "mort":
            k = n.get(s["bank"], 0)
            n[s["bank"]] = k + 1
            out.append(("%d_%03d" % (s["bank"], k), s["rom"], s["size"]))
    return out


def _whisper(model="small.en"):
    from faster_whisper import WhisperModel
    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=3)


def _transcribe(wm, pcm):
    segs, _ = wm.transcribe(pcm.astype(np.float32) / 32768.0, language="en", beam_size=5,
                            condition_on_previous_text=False, vad_filter=False,
                            temperature=0.0, max_new_tokens=64,     # no fallback passes on non-speech clips
                            chunk_length=min(30, len(pcm) // 16000 + 2))   # short window: same text, faster
    segs = list(segs)
    text = " ".join(s.text.strip() for s in segs).strip()
    if not segs:
        return "", -9.0, 1.0
    return text, float(np.mean([s.avg_logprob for s in segs])), float(max(s.no_speech_prob for s in segs))


def _av_decode(frames):
    import av
    c = av.CodecContext.create("gsm", "r")
    c.sample_rate = 8000
    c.layout = "mono"
    out = []
    for p in frames:
        for fr in c.decode(av.Packet(gsm610.to_gsm33(p))):
            out.append(fr.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.int16)


def test(rom, whisper=True):
    C = clips(rom)
    exact = same_used = tail = 0
    for cid, o, n in C:
        x = rom[o:o + n]
        info = {}
        rate, fr = unpack(x, info)
        y = pack(rate, fr)
        exact += y == x
        same_used += len(y) <= len(x) and y[12:12 + info["bits"] // 8] == x[12:12 + info["bits"] // 8] and y[:12] == x[:12]
        tail += info["tail"] != 0
    print("container: %d clips; pack(unpack(x)) == x for %d; header+used bits equal for %d; clips with non-zero tail bits %d"
          % (len(C), exact, same_used, tail))
    rng = np.random.default_rng(1)
    mx, tot, ns = 0, 0.0, 0
    pick = sorted(rng.choice(len(C), 20, replace=False))
    for i in pick:
        cid, o, n = C[i]
        fr = [f for f in unpack(rom[o:o + n])[1] if f is not None][:150]
        assert all(gsm610.from_gsm33(gsm610.to_gsm33(f)) == f and gsm610.int_to_params(gsm610.params_to_int(f)) == f for f in fr)
        a, b = gsm610.decode(fr).astype(np.int64), _av_decode(fr).astype(np.int64)
        m = min(len(a), len(b))
        dlt = np.abs(a[:m] - b[:m])
        mx, tot, ns = max(mx, int(dlt.max())), tot + dlt.sum(), ns + m
    print("decoder vs PyAV gsm: 20 clips, %d samples, max abs diff %d, mean abs diff %.4f" % (ns, mx, tot / ns))
    wm = _whisper() if whisper else None
    import time
    for i in pick[:3]:
        cid, o, n = C[i]
        x = rom[o:o + n]
        a = decode(x)
        t = time.time()
        y = encode(a, len(a) // 160, n)
        dt = time.time() - t
        b = decode(y)
        af, bf = a.astype(np.float64), b.astype(np.float64)
        snr = 10 * np.log10((af ** 2).sum() / max(1.0, ((af - bf) ** 2).sum()))
        print("round trip %s: %d frames, %d -> %d bytes, SNR %.1f dB, encode %.2f ms/frame" % (
            cid, len(a) // 160, n, len(y), snr, 1000 * dt / (len(a) // 160)))
        if wm:
            print("   original : %s\n   re-encoded: %s" % (_transcribe(wm, a)[0][:110], _transcribe(wm, b)[0][:110]))
    y = encode(a, len(a) // 160, 12 + (n - 12) // 2 // 4 * 4)
    print("half-size encode: %d bytes, %d of %d frames coded, frames ok %s" % (
        len(y), sum(f is not None for f in unpack(y)[1]), len(a) // 160, len(decode(y)) == len(a)))


def transcribe(rom, model="small.en"):
    import time
    import wave
    from cleanroom.audio.pitch import median_f0
    C = clips(rom)
    wavdir, prog = DIRTY + "/mort_wav", DIRTY + "/mort_transcribe.jsonl"
    os.makedirs(wavdir, exist_ok=True)
    done = {}
    if os.path.exists(prog):
        for ln in open(prog, encoding="utf-8"):
            if ln.strip():
                r = json.loads(ln)
                done[r["id"]] = r
    print("clips %d, already done %d" % (len(C), len(done)), flush=True)
    wm = _whisper(model)
    t0 = time.time()
    with open(prog, "a", encoding="utf-8") as fh:
        for k, (cid, o, n) in enumerate(C):
            if cid in done:
                continue
            x = rom[o:o + n]
            fr = unpack(x)[1]
            wp = "%s/%s.wav" % (wavdir, cid)
            if os.path.exists(wp):
                with wave.open(wp, "rb") as w:
                    pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            else:
                pcm = gsm610.decode(fr)
                with wave.open(wp, "wb") as w:
                    w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
                    w.writeframes(pcm.tobytes())
            text, lp, nsp = _transcribe(wm, pcm)
            f0 = median_f0(pcm.astype(np.float64) / 32768.0, 16000)
            r = dict(id=cid, rom=o, bytes=n, frames=len(fr), coded=sum(f is not None for f in fr), text=text,
                     f0=None if f0 is None else round(f0, 1), conf=round(lp, 2), nospeech=round(nsp, 2))
            done[cid] = r
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if k % 25 == 0:
                print("%4d/%d %s %.0fs  %s" % (k, len(C), cid, time.time() - t0, text[:60]), flush=True)
    write_spec(C, done)
    print("DONE", flush=True)


def is_speech(r):
    words = [w for w in r["text"].split() if any(ch.isalpha() for ch in w)]
    if r["id"].startswith("4_"):                       # bank 4 = cries / effects; whisper only hallucinates there
        return False
    if r["text"].strip().lower().rstrip(".!") in ("thanks for watching", "we'll see you next time", "you"):
        return False                                   # whisper's stock outputs for non-speech
    return bool(words) and r["conf"] > -1.0 and r["nospeech"] < 0.6


def write_spec(C, done):
    out = []
    for cid, o, n in C:
        r = dict(done[cid])
        r["speech"] = is_speech(r)
        r.pop("nospeech")
        out.append(r)
    with open(SPEC, "w", encoding="utf-8") as fh:
        fh.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n]\n")
    sp = [r for r in out if r["speech"]]
    print("voice_lines.json: %d clips, %d with text, %d speech, %d not speech, %.1f min total" % (
        len(out), sum(bool(r["text"]) for r in out), len(sp), len(out) - len(sp), sum(r["frames"] for r in out) / 6000))
    for r in sp[::max(1, len(sp) // 10)][:10]:
        print("  %s  %s" % (r["id"], r["text"][:90]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    rom = open(sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else ROM, "rb").read()
    if cmd == "test":
        test(rom, "--nowhisper" not in sys.argv)
    elif cmd == "transcribe":
        transcribe(rom, "base.en" if "--base" in sys.argv else "small.en")
    elif cmd == "spec":
        done = {json.loads(ln)["id"]: json.loads(ln) for ln in open(DIRTY + "/mort_transcribe.jsonl", encoding="utf-8") if ln.strip()}
        write_spec(clips(rom), done)
