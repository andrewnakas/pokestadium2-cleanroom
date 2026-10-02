"""Clean room: every sound regenerated in place.

    patches(rom) -> [(space "rom", offset, bytes)]          (used by generate)
    python -m games.pokestadium2.audio <cache dir>           (pre-render the VADPCM samples; slow, cached)

VADPCM samples (instruments, drums, effects): a new waveform with the kept outline (descriptor.synthesize),
encoded with our own codebook; the book and loop state of every font header that uses the sample are rewritten.
Speech clips (MORT = GSM 06.10 frames): our own spoken lines (games.pokestadium2.voices) or silence.
Sequences, soundfont parameters and envelopes are kept facts.
"""
import json
import os
import struct
import sys

import numpy as np

from cleanroom.audio import descriptor, vadpcm
from cleanroom.decomp.gen import h32

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")
CACHE = os.environ.get("PS2_AUDIO_CACHE", "D:/n64work/pokestadium2/clean/audio")
TONAL = [(1.0, 0.0), (1.8, -0.82)]
NOISY = [(0.0, 0.0), (1.0, 0.0)]


def render(s):
    """-> (adpcm bytes, book dict, loop state or None)"""
    n = s["size"] // 9 * 16
    x = descriptor.synthesize(s["desc"], n, s["rate"], seed=h32("smp", s["rom"]))
    x = np.pad(np.asarray(x, np.float32)[:n], (0, max(0, n - len(x))))
    looped = s["loop_count"] != 0 and 0 < s["loop_end"] <= n and s["loop_start"] < s["loop_end"]
    if looped:
        x = descriptor.make_loop_seamless(x, s["loop_start"], s["loop_end"])
    dith = np.random.default_rng(h32("dither", s["rom"])).integers(-1, 2, n)
    pcm = np.clip(np.round(np.clip(x, -1, 1) * 32000) + dith, -32768, 32767).astype(np.int16)
    preds = vadpcm.PREDICTORS if s["npred"] == 4 else (TONAL if s["tonal"] else NOISY)
    data, book, dec = vadpcm.encode(pcm, vadpcm.make_book(preds))
    state = None
    if s["state"]:
        a = s["loop_start"] // 16 * 16
        state = [int(v) for v in dec[a:a + 16]]
        state += [0] * (16 - len(state))
    return data, book, state


def load():
    """spec + the predictor family per sample (samples whose headers share a book record get the same one)"""
    spec = json.load(open(os.path.join(SPEC, "audio.json")))
    par = list(range(len(spec["adpcm"])))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    owner = {}
    for i, s in enumerate(spec["adpcm"]):
        fr = s["desc"]["frames"]
        s["tonal"] = bool(fr) and float(np.mean([f["h"] for f in fr])) > 0.5
        for bo, _ in s["recs"]:
            if bo in owner:
                par[find(i)] = find(owner[bo])
            owner[bo] = i
    group = {}
    for i, s in enumerate(spec["adpcm"]):
        group[find(i)] = group.get(find(i), False) or s["tonal"]
    for i, s in enumerate(spec["adpcm"]):
        s["tonal"] = group[find(i)]
    return spec


def cached(s):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{s['rom']:07X}.json")
    if os.path.exists(p):
        d = json.load(open(p))
        return bytes.fromhex(d["data"]), d["book"], d["state"]
    data, book, state = render(s)
    json.dump({"data": data.hex(), "book": book, "state": state}, open(p, "w"))
    return data, book, state


def patches(rom):
    spec = load()
    out = []
    books = {}
    for s in spec["adpcm"]:
        data, book, state = cached(s)
        data = data[:s["size"]]
        out.append(("rom", s["rom"], data + bytes(s["size"] - len(data))))
        for bo, lo in s["recs"]:
            if bo in books and books[bo] != book["book"]:
                raise ValueError(f"book {bo:X} shared by samples with different books")
            books[bo] = book["book"]
            out.append(("rom", bo + 8, struct.pack(">%dh" % len(book["book"]), *book["book"])))
            if state is not None:
                out.append(("rom", lo + 16, struct.pack(">16h", *state)))
    try:
        from games.pokestadium2 import voices
        speech = voices.clips()
    except ImportError:
        speech = {}
    from games.pokestadium2 import audiofmt
    spoken = 0
    for m in spec["mort"]:
        clip = speech.get(m["rom"])
        if clip is None:
            frames = struct.unpack_from(">H", rom, m["rom"] + 4)[0]       # kept fact: clip length in frames
            clip = audiofmt.mort_silence(frames)
        else:
            spoken += 1
        if len(clip) > m["size"]:
            raise ValueError(f"speech clip {m['rom']:X} does not fit")
        out.append(("rom", m["rom"], clip + bytes(m["size"] - len(clip))))
    print(f"audio: {len(spec['adpcm'])} samples, {len(books)} books, {len(spec['mort'])} speech clips ({spoken} spoken)")
    return out


def main(argv):
    spec = load()
    todo = [s for s in spec["adpcm"] if not os.path.exists(os.path.join(CACHE, f"{s['rom']:07X}.json"))]
    print(f"rendering {len(todo)} of {len(spec['adpcm'])} samples", flush=True)
    for i, s in enumerate(todo):
        cached(s)
        if i % 50 == 49:
            print(f"  {i + 1}", flush=True)
    print("done")


if __name__ == "__main__":
    main(sys.argv)
