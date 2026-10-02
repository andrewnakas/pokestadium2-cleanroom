#!/bin/sh
# tools/shots.sh <name> "<script>"  -> D:/n64work/pokestadium2/shots/<name>/sheet.png (site served on 8472)
W=/d/n64work/pokestadium2
CDP_MUTE=1 python ports/ejs/cdp_shot.py $W/shots/$1 --url "http://localhost:8472/index.html?audiolog=1" --script "$2" --gpu --port 9352 | tail -2
python tools/sheet.py $W/shots/$1/sheet.png $(ls $W/shots/$1/shot_*.png | sort -t_ -k2 -n) --w 480 2>&1 | tail -1
