# Pokemon Stadium 2 (USA) audio layout

Dirty-room analysis. Parser: `games/pokestadium2/audiofmt.py`
(`python -m games.pokestadium2.audiofmt <rom>` prints the one-screen summary).
All offsets are ROM offsets unless written `0x80……` (main code, vram = rom - 0x1000 + 0x80000400).

## Engine

Nintendo EAD's audio engine of the Ocarina of Time generation (not ultralib `n_audio`, not libmus):
three ROM files, each described by an `AudioTable` in the main code's data, plus a CPU-side
Factor 5 "MORT" speech decoder hooked in as sample codec 5. No audio container magic exists other
than `MORT` at the start of every speech clip.

Init code `0x80015D10..0x80015D98` stores the table pointers and calls `0x800143E8`
(`AudioLoad_InitTable(table, romAddr, 0)`) three times:

| file | ROM | table (vram / rom) | entries |
|---|---|---|---|
| Audioseq   | 0x14D6660-0x154F190 | 0x80086420 / 0x87020 | 137 (3 aliases) |
| Audiobank  | 0x4AD450-0x50F7E0   | 0x80085D60 / 0x86960 | 92 (2 aliases) |
| Audiotable | 0x50F7E0-0x14D6660  | 0x80086330 / 0x86F30 | 14 |
| sequence->font map | (main data) | 0x80086CC0 / 0x878C0 | 137 |

`AudioTable`: `s16 count; s16 pad; u32 romAddr(0 in ROM); u8 pad[8];` then `count` entries of 16 bytes:
`u32 offset (relative to the file); u32 size; s8 medium(2 = cart); s8 cachePolicy; s16 d1, d2, d3`.
`size == 0` means alias: `offset` is the index of the real entry.
Font entries: `d1 = bank1<<8 | bank2 (0xFF = none)`, `d2 = numInstruments<<8 | numDrums`, `d3 = numSfx`.
Sequence->font map: `u16 offset[137]` (from the map start) to `u8 n; u8 fontId[n]`.

The table sizes add up exactly to the three files (no gaps between entries).

## Section map

| ROM | what |
|---|---|
| 0x49B780-0x4AD450 | **not audio**: 0x20-byte records with floats, read by fragments 0x29/0x41 (previous file ends at 0x49B780, loaded by fragment 0xAE) |
| 0x4AD450-0x50F7E0 | Audiobank: 90 soundfonts |
| 0x50F7E0-0x14D6660 | Audiotable: 14 sample banks (below) |
| 0x14D6660-0x154F190 | Audioseq: 134 sequence scripts (EAD script: 0xD3 mute behaviour, 0xDB volume, 0xD7 enable channels, 0x90+n channel pointer ...). Music and sound-effect sequences; kept as facts |
| 0x154F190-0x15833A0 | **not the audio engine**: archive with magic `S1` (2 entries; first is a nested `S1` of 251 per-pokemon records, second is `u32 0x100` + 256 x `(u32 len, u32 offset)` + s16 blobs of ~7 KB). It has the shape of an ultralib `ALSeqFile` header but the payload is not MIDI; it is loaded by `0x800248A0` / `0x80031A6C` (game code, outside the audio engine). Purpose not determined (animation-like data keyed by pokemon) |
| 0x15833A0-0x15877A0 | **not audio**: 8-bit map with 0x80 fill, used by fragments 0x41/0x42/0xF7/0xFC |
| 0x15877A0 | first FRAGMENT |

The constants 0x5041C8 / 0x504240 / 0x552048 / 0x55D4A8 / 0x895440 / 0x147936C seen in the constant sweep are
not section starts (they fall inside fonts/banks; they are `lui/addiu` coincidences, e.g. fixed-point
constants of the speech decoder and libultra code).

Sample banks (Audiotable; headerless, samples back to back, 16-byte aligned):

| bank | ROM | samples | codec | used by font | class |
|---|---|---|---|---|---|
| 0 | 0x50F7E0-0x5175F0 | 12 | VADPCM | 0 | music instruments |
| 1 | 0x5175F0-0x5CCBD0 | 76 | VADPCM | 1 | music instruments |
| 2 | 0x5CCBD0-0x670CA0 | 34 | VADPCM | 2 | music instruments |
| 3 | 0x670CA0-0x67EE90 | 14 | VADPCM | 3 | music instruments |
| 4 | 0x67EE90-0x780330 | 265 | MORT | 4 (300 sfx slots) | speech |
| 5 | 0x780330-0xB6A1C0 | 571 | MORT | 5 (700 sfx slots) | speech |
| 6 | 0xB6A1C0-0xFA7740 | 551 | MORT | 6 (700 sfx slots) | speech |
| 7 | 0xFA7740-0xFA83E0 | 3 | VADPCM | 7 | music instruments |
| 8 | 0xFA83E0-0x1053C60 | 73 | VADPCM | 8 | music instruments |
| 9 | 0x1053C60-0x1083600 | 8 | VADPCM | 9 | music instruments |
| 10 | 0x1083600-0x1095760 | 10 | VADPCM | 10 | music instruments |
| 11 | 0x1095760-0x10B0EF0 | 12 | VADPCM | 11 | music instruments |
| 12 | 0x10B0EF0-0x126DC50 | 138 | VADPCM | 12 | sound effects (90 sfx-slot samples + 48 instrument samples) |
| 13 | 0x126DC50-0x14D6660 | 202 | VADPCM | 13..91 (77 fonts) | music instruments + drums, shared by the per-song fonts |

Totals: 1969 unique samples (5754 sample headers in fonts), 16 530 862 bytes; 582 VADPCM (6.9 MB),
1387 MORT (9.6 MB, 51.4 min). Unexplained: Audiotable 6 bytes (padding-like tail in bank 13),
Audiobank 12 bytes (one orphan 8-byte sfx pair in font 12, one 4-byte word in font 87), Audioseq 0.

Class notes: banks 4-6 being announcer speech is inferred (MORT, 16 kHz, sfx slots only, 1387 clips).
Which bank holds pokemon cries was **not determined**: there is no separate cry block; candidates are
bank 12 (sfx) or bank 1, or cries are built from instruments by sequences. Listening to
`dirty/audio_check` style decodes of bank 12 would settle it.

## Soundfont (Audiobank entry)

All pointers are offsets from the font start. Everything is big-endian.

```
font:   u32 drums       -> u32 drumPtr[numDrums]       (0 if none)
        u32 sfx         -> SoundEffect[numSfx]          (0 if none)
        u32 instPtr[numInstruments]                     (0 = empty slot)
Instrument (0x20): u8 loaded(0), rangeLo, rangeHi, decayIndex; u32 envelope;
                   {u32 sample; f32 tuning} low, normal, high
Drum (0x10):       u8 decayIndex, pan, loaded(0), pad; u32 sample; f32 tuning; u32 envelope
SoundEffect (8):   u32 sample; f32 tuning
Sample (0x10):     u32 codec:4 | medium:2 | unk:1 | relocated:1 | size:24
                   u32 addr   (offset inside the sample bank: medium 0 -> bank1, 1 -> bank2)
                   u32 loop; u32 book   (book = 0 for MORT)
Loop:              u32 start, end; s32 count (0 = no loop, -1 = forever); u32 numSamples;
                   s16 state[16] only if count != 0  (0x10 or 0x30 bytes)
Book:              s32 order(2); s32 npredictors(2, six samples 4); s16 book[8*order*npred]
Envelope:          {s16 delay; s16 arg}[] ended by delay 0 / -1 (hang) / -2 (goto) / -3 (restart); padded to 16
```

Every sample has its own Loop record (1969); 193 loop forever with state. Books: 577 distinct.
Fonts reference samples of exactly one bank (bank2 is always 0xFF). Several fonts reference the
same sample data (bank 13), each with its own header/book/loop copy: when a sample is regenerated,
**all** headers listed in `sample["hdrs"]` need the same book (and loop state).

Codec ids (sample header top nibble): 0 = VADPCM 9-byte frames (the only PCM codec used),
5 = MORT. Ids 1-4 (s8, s16, small ADPCM, reverb) do not occur.

Rates: the synthesis rate is 32 kHz (inferred: MORT clips carry 16000 Hz in their header and are
played with tuning 0.5), so a sample's natural rate is `32000 * tuning`
(most common: 16000, 32000, 22050, 28800, 28000). `parse()` reports the median tuning as `rate`.

VADPCM validation: predictor indices are always < npredictors; for looped samples the stored loop
state equals, bit-exactly, the 16 samples of the decoded frame that contains the loop start
(`cleanroom/audio/vadpcm.py` decode with the sample's book; 25/25 checked) - so the regenerated
`state` must be the decode of frame `loop_start // 16` of the new data. Six decoded excerpts are in
`D:/n64work/pokestadium2/dirty/audio_check/` (dirty room only).
`size` is `9 * ceil(samples / 16)` give or take one frame / a pad byte.

## Factor 5 "MORT" speech (codec 5)

It is the **GSM 06.10 full-rate (RPE-LTP) codec run at 16 kHz**, with its own framing: the LAR
decoding at `0x80020050` uses exactly the GSM tables (MIC -32,-32,-16,-16,-8,-8,-4,-4; INVA 13107,
13107,13107,13107,19223,17476,31454,29708; B 0,0,2048,-2560,94,-1792,-341,-1144).

Decoder: main code, CPU only (no custom RSP microcode; the output PCM is fed to the normal synthesis).

| vram | role |
|---|---|
| 0x8000C6xx-0x8000CDxx | glue in the synthesis: voice slots (0x18 bytes, states 1 init -> 2 buffering -> 3 playing), copies decoded PCM out of the ring buffer; DMA callback 0x8000C800 |
| 0x8001FCA0 | init(state, romAddr, readCallback); state is 0x25D8 bytes |
| 0x8001FD50 | pump: reads the stream in 0x400-byte blocks into a 0x1000-byte ring (state+0x1598), decodes frames into a 0xA00-sample ring (state+0x198) |
| 0x8001FFB0 / 0x80020018 / 0x80020038 | consume n samples / start / stop |
| 0x800205C0 | decode one frame: bit unpacking (all reads inlined) |
| 0x80020248, 0x80020330 | subframe loop, RPE/LTP reconstruction |
| 0x80020050 | LAR decode, then 0x80021834 |
| 0x800214C0-0x80021AC0 | hand-written assembly (`src/unk_220C0.s`): RPE dequantisation, short-term synthesis filter |

Clip format (the sample bytes; `size` in the sample header = clip length, a multiple of 4):

```
+0  'MORT'
+4  u16 frames          (160 samples each; loop.end in the font = frames * 160)
+6  u16 rate            (always 16000)
+8  u32 words           (low 24 bits: clip length / 4, header included)
+12 bitstream: big-endian u32 words, fields taken LSB first (a field may straddle two words,
    low part in the earlier word)
```

Frame stream, per output frame:
```
if no run is active:
    1 bit flag
    flag = 1: 4 bits n -> the next n+1 frames are silent (160 zero samples each, no more bits)
    flag = 0: 7 bits n -> the next n+1 frames are coded
coded frame (260 bits, GSM 06.10 parameter order):
    LARc[8]: 6,6,5,5,4,4,3,3 bits
    4 subframes: Nc 7, bc 2, Mc 2, xmaxc 6, xMc[13] 3 bits each
```
Frames are not byte aligned; the clip ends with 1..32 unused bits. Verified by walking all 1387
clips: every clip consumes its length to within 32 bits and all word counts match
(308 583 frames: 294 434 coded, 14 149 silent).

Regeneration:
- **Silent clip**: `audiofmt.mort_silence(frames)` builds the smallest valid stream (5 bits per 16
  silent frames); pad with zero words to the original length and keep the header's word count equal
  to the padded length / 4 (or just keep it <= original: the decoder stops after `frames` frames).
- **Encoder: feasible.** Any GSM 06.10 encoder (public ETSI spec; e.g. our own implementation fed
  with 16 kHz input, 160-sample frames) gives the 76 parameters per frame; pack them as above with
  one `0 + 7-bit` run header per <= 128 coded frames and `1 + 4-bit` headers for silent stretches.
  A clip with the same frame count fits in the original length when it has no more coded frames
  than the original (260 bits each); otherwise shorten/silence frames, or grow the clip and update
  `size` in every font header plus the bank table sizes.
- **Tools**: `cleanroom/codec/gsm610.py` (our GSM 06.10 decoder + encoder) and
  `games/pokestadium2/mort.py` (`unpack/pack/decode/encode`; `python games/pokestadium2/mort.py test`).
  Checked: `pack(unpack(x)) == x` byte for byte on all 1387 clips (runs are greedy: silent <= 16,
  coded <= 128; the body is `bits // 32 + 1` words, unused tail bits are zero); our decoder equals
  the standard decoder (PyAV/FFmpeg `gsm`, frames repacked as 33-byte 0xD frames) sample for sample
  on 20 clips (405k samples, max diff 0); encode -> decode of a decoded clip gives 9-14 dB SNR and
  the same whisper text.
- Game decoder vs standard: same algorithm. A silent frame is `bzero(out, 320)` and leaves the whole
  decoder state untouched (0x800207B8), which is what `gsm610.decode` does for `None` frames and
  what `mort.encode` mirrors (LTP history and previous LARs are held over skipped frames).
  The assembly has the standard de-emphasis (28180), output `2*msr` saturated and `& 0xFFF8`
  (0x800217D8-0x8002181C) and the standard LAR -> reflection mapping (0x80021A6C). Seen but not
  traced to the end: the filter stages and the de-emphasis accumulator appear to skip the
  intermediate 16-bit saturations of the reference, which could only matter when a clip overdrives
  the filter; we keep the standard arithmetic.
- Bank 4 (265 clips) is not announcer speech (short cries / effects: whisper gives nothing or "AHHH"/"RRRR"-style
  hallucinations at low confidence; all 265 are marked `speech: false`);
  banks 5 and 6 are the announcer. Transcripts: `games/pokestadium2/spec/voice_lines.json`.

## What to keep as facts

Tables, font structures (ranges, tunings, envelopes, decay indices, pans), loop points, sample
lengths/rates, sequence scripts and the sequence->font map. Regenerate: VADPCM sample data + books +
loop state, MORT bitstreams.
