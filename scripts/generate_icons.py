#!/usr/bin/env python3
"""Gera favicon e ícones PWA a partir da logo Souza Pinto."""
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent.parent / "static" / "logo-souza-pinto-corporate.png"
OUT = Path(__file__).resolve().parent.parent / "static"

SIZES = [
    (32, "favicon-32x32.png"),
    (192, "icons/pwa-192.png"),
    (512, "icons/pwa-512.png"),
]


def main():
    img = Image.open(SRC).convert("RGBA")
    w, h = img.size

    for size, name in SIZES:
        out_path = OUT / name
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Quadrado branco com padding (10% em cada lado)
        pad = int(size * 0.12)
        box = size - 2 * pad
        scale = min(box / w, box / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        x = (size - nw) // 2
        y = (size - nh) // 2
        canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)

        canvas.save(out_path, "PNG", optimize=True)
        print(f"Gerado: {out_path}")


if __name__ == "__main__":
    main()
