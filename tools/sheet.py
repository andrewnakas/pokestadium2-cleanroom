"""Contact sheet of screenshots: python tools/sheet.py <out.png> <img>... [--w 400] [--cols 4]"""
import sys
from PIL import Image, ImageDraw
import os
a = sys.argv[1:]
w = int(a[a.index("--w") + 1]) if "--w" in a else 400
cols = int(a[a.index("--cols") + 1]) if "--cols" in a else 4
files = [f for i, f in enumerate(a[1:]) if not f.startswith("--") and a[i] not in ("--w", "--cols")]
ims = []
for f in files:
    im = Image.open(f).convert("RGB")
    im = im.resize((w, max(1, im.height * w // im.width)))
    ImageDraw.Draw(im).text((4, 2), os.path.basename(f), fill=(255, 255, 0))
    ims.append(im)
h = max(i.height for i in ims)
rows = (len(ims) + cols - 1) // cols
out = Image.new("RGB", (w * min(cols, len(ims)), h * rows))
for i, im in enumerate(ims):
    out.paste(im, (w * (i % cols), h * (i // cols)))
out.save(a[0])
print(a[0], len(ims), out.size)
