#!/bin/sh
# Assemble the site from a clean ROM: tools/build_site.sh <clean.z64> [site dir]
set -e
W=/d/n64work/pokestadium2
ROM=${1:-$W/build/clean.z64}
SITE=${2:-$W/site}
EJS=$W/ejs_runtime            # data/ of EmulatorJS 4.2.3 (copied once from the DK64 session's site)
python - "$ROM" <<'PY'
import hashlib, sys
if hashlib.sha1(open(sys.argv[1], "rb").read()).hexdigest() == "d8343e69a7dc63b869cf6361d87cde64444281d3":
    sys.exit("refusing: that is the retail ROM")
PY
mkdir -p "$SITE"
find "$SITE" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -r "$EJS/data" "$SITE/data"
# libunrar (RARLab licence, not GPL-compatible) is never shipped: the site loads game.zip, not a RAR
rm -f "$SITE/data/compression/libunrar.js" "$SITE/data/compression/libunrar.wasm"
printf '# Compression Libraries\n\nThe EmulatorJS 4.2.3 zip and 7z extractors are kept. libunrar (RARLab unrar licence,\nnot GPL-compatible) was removed: this site ships game.zip and never loads a RAR archive.\n' > "$SITE/data/compression/README.md"
cp ports/ejs/index.html "$SITE/index.html"
python -c "import sys,zipfile; z=zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED,compresslevel=9); z.write(sys.argv[1],'game.z64'); z.close()" "$ROM" "$SITE/game.zip"
python ports/ejs/patch_core.py "$ROM" "$EJS/data/cores" "$SITE/data/cores"
cat > "$SITE/THIRD_PARTY.md" <<'MD'
# Third-party runtime in this site

- EmulatorJS 4.2.3 (`data/`), GPL-3.0: https://github.com/EmulatorJS/EmulatorJS (license: `data/LICENSE.EmulatorJS`)
- libretro mupen64plus-next core (`data/cores/mupen64plus_next-*.data`), GPL-2.0:
  source https://github.com/libretro/mupen64plus-libretro-nx (built by the EmulatorJS project)
- `game.zip` (game.z64) holds the game code and geometry documented by the pret/pokestadiumgs project with every picture and
  sound regenerated (see https://github.com/andrewnakas/pokestadium2-cleanroom).
MD
touch "$SITE/.nojekyll"
du -sh "$SITE" | cut -f1
