"""One-off: turn a downloaded Jellyfin logo into a Discord-ready square PNG.

Picks the highest-resolution candidate from Downloads, scales it to fill a
1024x1024 transparent canvas (>= Discord's 512x288 minimum), and saves a PNG.
"""
import os

from PIL import Image

downloads = os.path.join(os.path.expanduser("~"), "Downloads")
candidates = [
    "jellyfin-icon.png",
    "jellyfin-icon (1).png",
    "Jellyfin--Streamline-Simple-Icons.png",
    "jellyfin-ib5k2owl3jls58wk7oywcc.webp",
]

best = None  # (min_dimension, filename, image)
for name in candidates:
    path = os.path.join(downloads, name)
    if not os.path.exists(path):
        continue
    img = Image.open(path).convert("RGBA")
    print(f"source: {name:45s} {img.size} {img.mode}")
    score = min(img.size)
    if best is None or score > best[0]:
        best = (score, name, img)

if not best:
    raise SystemExit("No candidate logo found in Downloads")

_, chosen, img = best
print(f"chosen: {chosen} {img.size}")

SIZE = 1024
w, h = img.size
scale = SIZE / max(w, h)
resized = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
canvas.paste(resized, ((SIZE - resized.size[0]) // 2, (SIZE - resized.size[1]) // 2), resized)

out = os.path.join(downloads, "jellyfin-discord.png")
canvas.save(out, "PNG")
print(f"wrote:  {out} {canvas.size} PNG")
