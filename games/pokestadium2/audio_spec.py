"""Dirty room: audio facts -> spec/audio.json (no sample data).

    python -m games.pokestadium2.audio_spec <rom> games/pokestadium2/spec

Per VADPCM sample: place, size, rate, loop points, the book / loop records of every font header that
uses it, and the coarse outline (cleanroom.audio.descriptor: per-frame f0, harmonicity, 16 band dB, RMS).
Per MORT speech clip: place, size, frame count (words and pitch are in voice_lines.json).
"""
import json
import struct
import sys

from cleanroom.audio import descriptor, vadpcm
from games.pokestadium2 import audiofmt


def main(argv):
    b = open(argv[1], "rb").read()
    p = audiofmt.parse(b)
    fonts = [(f["rom"], f["rom"] + f["size"]) for f in p["fonts"] if f.get("size")]

    def font_of(o):
        return next(a for a, e in fonts if a <= o < e)
    adpcm, mort = [], []
    for s in p["samples"]:
        if s["codec"] != "adpcm":
            mort.append({"rom": s["rom"], "size": s["size"], "bank": s["bank"]})
            continue
        recs = []
        for h in s["hdrs"]:
            base = font_of(h)
            loop, book = struct.unpack_from(">II", b, h + 8)
            recs.append([base + book, base + loop])
        order, npred = struct.unpack_from(">ii", b, s["book"])
        book = {"order": order, "npred": npred,
                "book": list(struct.unpack_from(">%dh" % (order * npred * 8), b, s["book"] + 8))}
        pcm = vadpcm.decode(b[s["rom"]:s["rom"] + s["size"] // 9 * 9], book)
        adpcm.append({"rom": s["rom"], "size": s["size"], "bank": s["bank"], "rate": int(s["rate"]),
                      "npred": npred, "loop_start": s["loop_start"], "loop_end": s["loop_end"],
                      "loop_count": s["loop_count"], "state": s["loop_len"] > 16, "recs": recs,
                      "desc": descriptor.describe(pcm, int(s["rate"]))})
    json.dump({"adpcm": adpcm, "mort": mort}, open(f"{argv[2]}/audio.json", "w"), separators=(",", ":"))
    print(f"audio spec: {len(adpcm)} VADPCM samples ({sum(len(a['recs']) for a in adpcm)} headers), "
          f"{len(mort)} speech clips")


if __name__ == "__main__":
    main(sys.argv)
