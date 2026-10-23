"""Ikoner för appen (PWA): blixt på mörk gradient, 192/512 px + maskable."""
from PIL import Image, ImageDraw
import os
os.makedirs("static/icons", exist_ok=True)
for size, name, pad in ((180, "apple-touch-icon.png", 0.14), (192, "icon-192.png", 0.12), (512, "icon-512.png", 0.12), (512, "icon-maskable-512.png", 0.22)):
    im = Image.new("RGB", (size, size), "#0b1220")
    d = ImageDraw.Draw(im)
    for y in range(size):                                   # lodrät gradient
        t = y / size
        d.line([(0, y), (size, y)], fill=(int(11 + 20 * t), int(18 + 60 * t), int(32 + 90 * t)))
    s = size * (1 - 2 * pad); ox = size * pad
    pts = [(0.58, 0.0), (0.18, 0.56), (0.46, 0.56), (0.36, 1.0), (0.84, 0.40), (0.54, 0.40), (0.70, 0.0)]
    d.polygon([(ox + s * x, ox + s * y) for x, y in pts], fill="#22d3a0")
    im.save(f"static/icons/{name}")
