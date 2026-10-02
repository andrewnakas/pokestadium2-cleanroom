#!/bin/sh
# tools/taint_loop.sh [n]: generate + taint scan, adding flagged textures to spec/reseed.json, until 0 failing
W=/d/n64work/pokestadium2
for i in $(seq 1 ${1:-4}); do
  python -m games.pokestadium2.generate $W/rom/baserom.z64 games/pokestadium2/spec $W/build/clean.z64 > $W/dirty/gen.log 2>&1 || { tail -3 $W/dirty/gen.log; echo GENERATE FAILED; echo LOOP DONE; exit 1; }; tail -2 $W/dirty/gen.log
  python -m games.pokestadium2.taint_report $W/rom/baserom.z64 $W/build/clean.z64 --reseed --out $W/dirty/taint_fail.json | grep -E "^taint|failing by|reseed"
  python -c "import json,sys; sys.exit(0 if not json.load(open('D:/n64work/pokestadium2/dirty/taint_fail.json')) else 1)" && echo "CLEAN after $i" && break
done
echo LOOP DONE
