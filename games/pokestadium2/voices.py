"""Speech clips (MORT): placeholder voices + practice pack.

    python -m games.pokestadium2.voices outline <rom>      dirty: coarse outline of every clip -> spec/voice_outline.json
    python -m games.pokestadium2.voices build [n]          clean: speak / synthesise every clip -> cache (resumable)
    python -m games.pokestadium2.voices practice <rom>     dirty, personal use: D:/n64work/pokestadium2/practice/
    clips() -> {rom offset: clip bytes}                    (used by audio.patches)

Announcer lines (banks 5, 6; words in spec/voice_lines.json, a kept fact) are spoken by Piper TTS (our own
placeholder performance, not the original actor), fitted to the clip's frame count and encoded with our GSM
06.10 encoder. Clips without words (bank 4: Pokemon cries and shouts) are resynthesised from the coarse
outline (cleanroom.audio.descriptor), like every other sample.
"""
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")
CACHE = os.environ.get("PS2_VOICE_CACHE", "D:/n64work/pokestadium2/clean/voices")
PIPER_DIR = os.environ.get("PIPER_VOICES", "piper_voices")
MODEL = "en_US-ryan-high"
HZ = 16000


def lines():
    return json.load(open(os.path.join(SPEC, "voice_lines.json"), encoding="utf-8"))


def clips():
    out = {}
    if not os.path.isdir(CACHE):
        return out
    for f in os.listdir(CACHE):
        if f.endswith(".mort"):
            out[int(f[:-5], 16)] = open(os.path.join(CACHE, f), "rb").read()
    return out


# ---- dirty room ----

def outline(argv):
    from cleanroom.audio import descriptor
    from games.pokestadium2 import mort
    rom = open(argv[0], "rb").read()
    out = {}
    L = lines()
    for i, ln in enumerate(L):
        pcm = mort.decode(rom[ln["rom"]:ln["rom"] + ln["bytes"]])
        x = np.asarray(pcm, np.float32)
        out[f"{ln['rom']:X}"] = {"desc": descriptor.describe(pcm, HZ),
                                 "rms": round(float(np.sqrt((x ** 2).mean())), 1)}
        if i % 200 == 199:
            print(f"  {i + 1}/{len(L)}", flush=True)
    json.dump(out, open(os.path.join(SPEC, "voice_outline.json"), "w"), separators=(",", ":"))
    print(f"voice outline: {len(out)} clips")


def practice(argv):
    """call-and-response pack for the user's own recordings (retail clips: never leaves this PC)"""
    sys.path.insert(0, "D:/n64work/voicekit/packs")
    import common
    from games.pokestadium2 import mort
    rom = open(argv[0], "rb").read()
    out = argv[1] if len(argv) > 1 else "D:/n64work/pokestadium2/practice"
    L = [ln for ln in lines() if ln.get("speech") and ln.get("text")]
    items = []
    for i, ln in enumerate(L):
        pcm = np.asarray(mort.decode(rom[ln["rom"]:ln["rom"] + ln["bytes"]]), np.float32) / 32768
        items.append({"who": "announcer%02d" % (i // 100 + 1), "name": ln["id"], "text": ln["text"],
                      "pcm": common.to_hz(pcm, HZ), "slot": {"rom": ln["rom"], "frames": ln["frames"]}})
    common.write_pack(out, "Pokemon Stadium 2", items)


# ---- clean room ----

_VOICE = None


def speak(text, seconds):
    """Piper at a pace that fits the slot -> float32 at 16 kHz"""
    global _VOICE
    import librosa
    from piper import PiperVoice, SynthesisConfig
    if _VOICE is None:
        _VOICE = PiperVoice.load(os.path.join(PIPER_DIR, MODEL + ".onnx"))

    def run(scale):
        cfg = SynthesisConfig(length_scale=scale, noise_scale=0.8, noise_w_scale=0.9)
        x = np.concatenate([c.audio_float_array for c in _VOICE.synthesize(text, syn_config=cfg)]).astype(np.float32)
        idx = np.nonzero(np.abs(x) > 0.006)[0]
        if len(idx):
            x = x[max(0, idx[0] - 300):idx[-1] + 300]
        return x
    sr = _VOICE.config.sample_rate
    x = run(1.0)
    want = max(0.2, seconds - 0.04)
    if len(x) / sr > want:                                  # too long: speak faster (down to 0.6), then time-compress
        x = run(max(0.6, want / (len(x) / sr) * 0.97))
    y = librosa.resample(x, orig_sr=sr, target_sr=HZ).astype(np.float32)
    if len(y) / HZ > seconds:
        y = librosa.effects.time_stretch(y, rate=len(y) / HZ / seconds * 1.02).astype(np.float32)
    return y


def build(argv):
    from cleanroom.audio import descriptor
    from cleanroom.decomp.gen import h32
    from games.pokestadium2 import mort
    os.makedirs(CACHE, exist_ok=True)
    L = lines()
    O = json.load(open(os.path.join(SPEC, "voice_outline.json")))
    limit = int(argv[0]) if argv else None
    done = spoken = 0
    for ln in L:
        p = os.path.join(CACHE, f"{ln['rom']:07X}.mort")
        if os.path.exists(p):
            continue
        n = ln["frames"] * 160
        o = O[f"{ln['rom']:X}"]
        if ln.get("speech") and ln.get("text"):
            y = speak(ln["text"], n / HZ)
            x = np.zeros(n, np.float32)
            a = max(0, (n - len(y)) // 8)                   # start near the front, as an announcer does
            x[a:a + len(y)] = y[:n - a]
            spoken += 1
        else:
            x = descriptor.synthesize(o["desc"], n, HZ, seed=h32("cry", ln["rom"]))
            x = np.pad(np.asarray(x, np.float32)[:n], (0, max(0, n - len(x))))
        rms = float(np.sqrt((x ** 2).mean())) + 1e-9
        x = x * min(o["rms"] / 32768 / rms, 0.95 / (np.abs(x).max() + 1e-9))      # kept loudness
        pcm = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)
        clip = mort.encode(pcm, ln["frames"], ln["bytes"])
        assert len(clip) <= ln["bytes"] and struct.unpack_from(">H", clip, 4)[0] == ln["frames"]
        open(p, "wb").write(clip)
        done += 1
        if done % 50 == 0:
            print(f"  {done} clips ({spoken} spoken)", flush=True)
        if limit and done >= limit:
            break
    print(f"voices: {done} new clips ({spoken} spoken), cache {len(os.listdir(CACHE))} of {len(L)}")


if __name__ == "__main__":
    {"outline": outline, "build": build, "practice": practice}[sys.argv[1]](sys.argv[2:])
