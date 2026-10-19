# Pokémon Stadium 2 — clean room web build

Play: **https://andrewnakas.github.io/pokestadium2-cleanroom/**

Pokémon Stadium 2 running in the browser (EmulatorJS + the mupen64plus-next core, WebGL) from a
**clean ROM image**: the game's code, geometry, animation, text and note sequences as documented by the
[pret/pokestadiumgs](https://github.com/pret/pokestadiumgs) decompilation, with **every picture and every
sound regenerated**. No retail pixels or audio samples are in the published image.

Controls: arrows move · `X` A · `C` B · `Z` Z · `S` R · `Q` L · `T F G H` D-pad · `Enter` Start ·
`I J K L` C buttons · gamepads work too. Saves stay in the browser.

## What is kept, what is generated

The retail ROM is read once, in a "dirty room" step, which keeps only coarse facts (`games/pokestadium2/spec/`).
The clean image is built from those facts plus the code/geometry the decomp reproduces:

| Asset (count) | Kept fact | Generated |
|---|---|---|
| Textures (8885) and palettes (242) | format, size, a 4×4 colour grid (16×16 for large pictures), a 2-bit alpha outline | colour from the grid plus our own noise detail; palettes re-quantised |
| Fonts (6 files, 177 glyphs each) | cell size, advance widths, the game's glyph order | drawn with an original stroke font (`drawn.py`) |
| Text in UI images (525) | the words and their colours (`spec/labels.json`) | re-typeset |
| JPEG backgrounds (107) | size, 16×16 colour grid | new baseline JPEGs in the game's segment layout (`jpegs.py`) |
| Instrument, drum and effect samples (582) | length, rate, loop points, a coarse spectral outline | resynthesised; our own VADPCM codebooks and loop states (`audio.py`) |
| Speech clips (1387, GSM 06.10 frames) | frame count, one median pitch, a coarse outline (the words were a Whisper transcript, `spec/voice_lines.json`; removed 2026-10-19, see below) | placeholder text-to-speech performance of the words (not the original announcer), cries resynthesised from outlines; encoded with our own GSM encoder (`cleanroom/codec/gsm610.py`, `voices.py`) |
| Music and effect sequences, soundfont parameters | kept (note events) | played by the resynthesised instruments |
| Game Boy Tower data (206 blobs) | size | blanked: it only runs with a real cartridge in a Transfer Pak |
| Models, animation, text, scripts, tables | kept (code / geometry / text) | — |

Everything is regenerated **in place** (same offsets, same decoded sizes, compressed files fitted to their
slots), so the code runs unchanged. `taint_report.py` scans every regenerated stream (stored bytes and decoded
pixels / PCM) against the retail one for shared runs of 32 bytes or more: **0 failing**.

## Layout

- `games/pokestadium2/` — the game module: containers (`romio.py`), image tables (`imgtab.py`), scans
  (`scan2.py`, `texscan.py`), dirty-room fact extraction (`extract_spec.py`, `audio_spec.py`, `jpegs.py`),
  clean-room generation (`generate.py`, `drawn.py`, `audio.py`, `voices.py`), `taint_report.py`.
- `cleanroom/` — shared library (texture codecs, stroke font, VADPCM, GSM 06.10, descriptors, taint scan).
- `ports/ejs/` — the web page and the emulator settings patch; `tools/build_site.sh` assembles the site.
- `docs/` — format notes (`AUDIO.md`), the playbook this build followed.

## Build

Needs your own ROM (Pokémon Stadium 2 USA, sha1 `d8343e69a7dc63b869cf6361d87cde64444281d3`); it is never
published and nothing here downloads one.

```sh
python -m games.pokestadium2.generate <rom.z64> games/pokestadium2/spec build/clean.z64
python -m games.pokestadium2.taint_report <rom.z64> build/clean.z64      # must print 0 failing
sh tools/build_site.sh build/clean.z64 site
python ports/wasm/serve.py site 8472
```

Third-party runtime: EmulatorJS (GPL-3.0) and the libretro mupen64plus-next core (GPL-2.0); see
`THIRD_PARTY.md` in the site.

Pokémon and Pokémon Stadium are trademarks of Nintendo / Creatures / GAME FREAK. This is an unofficial,
non-commercial preservation and research project.

## 2026-10-19: transcripts removed

`games/pokestadium2/spec/voice_lines.json` held Whisper transcripts of the retail announcer and was removed.
The placeholder TTS clips in the current build were spoken from those transcripts, so their wording is retail
wording; they stay until the commentary is rewritten. `voices.py` / `mort.py` need a new, transcript-free line
list before they can run again. The file is still in git history (to be purged with the history rewrite).
