# Pokemon models (archive 27ED000) — format notes

Renderer: `games/pokestadium2/model_render.py` (`load`, `render`, `sheet`, `texture_table`).
282 files: 0 = a scene/test model, 1..251 = Pokedex order, 252 substitute doll, 253 egg,
254..278 Unown B..Z, 279 second Pikachu, 280 Poke Ball, 281 second Ho-Oh.

## File
Each file is a FRAGMENT (0x20 header, then data; pointers are `0x8FF00000 + file offset`).
The fragment's only code (at 0x20) returns a root pointer: `lui v1,hi; addiu v1,lo` (bytes 0x2E, 0x32).
Root = `{u16 model id, u16 1; u32 ?; lists*[3]; func*}`; `*lists[0]` is the **geo layout** script.
File order: texels, texture records, palettes, tile lists, Vtx, display lists, materials, script, root.

## Geo layout (same interpreter as Stadium 1 `src/geo_layout.c`; first byte = command)
| cmd | size | meaning |
|-----|------|---------|
| 00/03 | 8 | branch + return address (ptr at +4); 02 jump; 04 return; 01 end |
| 05 / 06 | 4 | open / close child level (children inherit the last node's matrix) |
| 08 | 12 | attach callback `func, arg` to the last node |
| 09 | 4 | group |
| 14 | 12 | light; 18 (8) shadow; 24 (4) attachment point; 28/29 (4) own-lights begin/end (Magcargo) |
| 17 | 0x14 | tables: `s16 ntex @2, s16 npal @4, s16 nvtx @6, tex* @8, pal* @C, vtx* @10` |
| 1B | 0x10 | rotate (degrees s16 x3) + translate (s16 x3) |
| 1C | 0x10 | scale (3 x 16.16); every model starts with 0.1 |
| 1D | 0x1C | **joint**: `u8 slot, u8 flags, u8 anim index, Vec3s t, Vec3s r (binary angles), 3 x 16.16 scale` |
| 1E | 8 | display list drawn with another joint's matrix: `u8 layer, s16 slot, Gfx*` |
| 20 | 0x14 | rotate/translate + display list; 21 (0x10) billboard display list |
| 22 | 8 | display list with the current matrix: `u8 layer, Gfx*` (NULL = callback only) |
| 23 | 0x10 | material: `u8 mode, s16 ?, Gfx* tile list, s16 tex index, s16 pal index, rgba prim` |
| 25 | 4 | flag the last node: reset material state after it is drawn |

## Joints (rest pose is in the file; no animation data needed)
Rotation matrix = engine `func_8000F730` (row vectors, X then Y then Z). Two kinds:
- flags bit0 = 1 (gen 1 models): scale compensated. `U = R(t * S_parent) * U_parent`,
  `S = S_parent * scale`, drawn matrix `M = diag(S) * U` (scale does not shear the children).
- flags bit0 = 0 (most gen 2 models): plain `M = S * R * T * M_parent`.
Each joint stores its matrix in `slot`; cmd 1E uses a slot to load vertices skinned to another joint
(usually a list that is only a G_VTX), then a cmd 22 list loads more and draws triangles across both.
A slot may be used before its joint appears in the script: resolve joints in a first pass.

## Display lists (F3DEX2)
Only `01 VTX` (direct pointers), `05/06/07` triangles, `D9` geometry mode (0x400 cull back,
0x200 front, 0x20000 lighting, 0x40000 texture gen), `D7` texture scale, `DE`, `DF`.
No texture loads inside: the engine emits SetTImg from the material. Vertices carry normals
(lighting is on for the whole scene); colour comes from texture x prim x light.

## Textures
Record (12 bytes): `u8 fmt; u8 siz; s16 w; s16 h; u16 w*h; u8* texels` (fmt/siz = G_IM_*).
Tile list (per material): `SetTile 7, LoadBlock, SetTile 0 (fmt, siz, cms/cmt, masks, shifts),
SetTileSize, End`; a zero SetTileSize means a callback sets it at run time.
Palette table entry (12 bytes): `s32 count; u16* colours (RGBA16); Gfx* load list`; the material's
pal index picks it. **The palette is not next to the texels and not after the record.**
(spec/textures.json currently gives `pal` offsets inside the record table for the 11 CI models
16 17 18 21 26 58 85 103 126 151 279; `texture_table(i)` returns the real offsets.)

## Layers and material state
`layer & 15` picks a bucket; buckets are drawn in order, each is its own list stream with its own
vertex buffer and RDP state: 1..3 opaque (2 decal), 4 cutout (alpha test), 5..8 translucent
(6 decal, 8 writes z). Mode = row of the combine table (Stadium 1 `D_8006F1B4`): 0 prim, 1 tex*prim
(alpha tex), 2 tex decal over prim, 3 tex*prim (alpha prim), 4 both alphas; +5 unlit; +10 shade
instead of prim. The engine only emits what differs from the bucket's *tracked* mode/prim/texture, so a
plain `23 01 .. tex -1 .. FFFFFFFF` node after a callback changes nothing: the callback's state stays
until a cmd 25 reset. Emulate this or gen 2 bodies come out white.

## Callbacks (cmd 08, functions in fragment 0x81, ROM 0x15E8B0)
- `0x81000140` material (51 models, most of gen 2): `arg = {M, M2}` (M2 = second texture).
  `M = {T*, A*, C*, G*}`; `T = {texels*, palette*, header*}`,
  header `= {u8 fmt, siz, cms, cmt, masks, maskt, shifts, shiftt; s16 w, h}`;
  `C = {u8 combine[16]*, u8 prim[5]* (rgba + lod), u8 env[4]*}`;
  `A = {.., colour keys* @8, texture frames* @C}` (keys: prim frames* @C, env frames* @10;
  frames: `{count, texels*[]}`); `G = {u32 geometry mode bits, u16 scale s, t}`.
  combine bytes: a0 b0 c0 d0 Aa0 Ab0 Ac0 Ad0 a1 b1 c1 d1 Aa1 Ab1 Ac1 Ad1 (2-cycle).
- `0x81000040` `{begin list, end list}`: texture gen (shiny parts, 9 models).
- `0x81000048` (Grimer, Muk) and `0x81000068` (Ponyta, Rapidash, Moltres): build the node's list at
  run time from texel pointers in arg (frame 0 at arg+0 / arg+4).
- `0x81000080` shadow; `0x30 0x38 0x58 0x60 0x70 0x78 0x88`: sprites and effects (tail flames,
  gas, sparks) — not drawn by the renderer.

## Renderer notes
Orthographic, z-buffer, 3x supersampling, bilinear fetch with clamp/mirror/wrap, fixed light on the
normals, auto-framed. 282 models at 96x96: about a minute.
