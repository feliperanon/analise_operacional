#!/usr/bin/env python3
"""
Gera favicon e ícones PWA (incl. maskable) a partir da logo em PDF (página 1),
com fallback para PNG corporativo em static/.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

DEFAULT_PDF = STATIC / "brand" / "logo-souza-pinto-source.pdf"
FALLBACK_PNG = STATIC / "logo-souza-pinto-corporate.png"

SIZES = [
    (32, "favicon-32x32.png"),
    (192, "icons/pwa-192.png"),
    (512, "icons/pwa-512.png"),
]


def rasterize_pdf_first_page(pdf_path: Path, dpi: float) -> Image.Image:
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=True)
        return Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
    finally:
        doc.close()


def trim_image(img: Image.Image, bg_threshold: int = 248) -> Image.Image:
    """Remove margens claras ao redor da arte (PDF costuma trazer muito branco)."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    bbox = img.getbbox()
    if not bbox:
        return img

    pixels = img.load()
    x0, y0, x1, y1 = bbox

    def row_has_content(y: int) -> bool:
        for x in range(x0, x1):
            r, g, b, a = pixels[x, y]
            if a < 250:
                return True
            if r < bg_threshold or g < bg_threshold or b < bg_threshold:
                return True
        return False

    def col_has_content(x: int) -> bool:
        for y in range(y0, y1):
            r, g, b, a = pixels[x, y]
            if a < 250:
                return True
            if r < bg_threshold or g < bg_threshold or b < bg_threshold:
                return True
        return False

    top, bottom = y0, y1 - 1
    while top < bottom and not row_has_content(top):
        top += 1
    while bottom > top and not row_has_content(bottom):
        bottom -= 1

    left, right = x0, x1 - 1
    while left < right and not col_has_content(left):
        left += 1
    while right > left and not col_has_content(right):
        right -= 1

    pad = max(2, int(min(img.width, img.height) * 0.003))
    left = max(x0, left - pad)
    top = max(y0, top - pad)
    right = min(x1 - 1, right + pad)
    bottom = min(y1 - 1, bottom + pad)

    return img.crop((left, top, right + 1, bottom + 1))


def load_source_image(pdf_path: Path, png_fallback: Path, dpi: float) -> Image.Image:
    if pdf_path.is_file():
        img = rasterize_pdf_first_page(pdf_path, dpi=dpi)
        return trim_image(img)
    if png_fallback.is_file():
        return trim_image(Image.open(png_fallback).convert("RGBA"))
    raise FileNotFoundError(
        f"Nenhuma fonte encontrada: PDF ({pdf_path}) ou PNG ({png_fallback})."
    )


def compose_square_icon(src: Image.Image, size: int, pad_ratio: float = 0.11) -> Image.Image:
    """Logo centralizada em quadrado branco; padding ~11% favorece ícones maskable."""
    w, h = src.size
    pad = max(1, int(size * pad_ratio))
    box = size - 2 * pad
    scale = min(box / w, box / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    x = (size - nw) // 2
    y = (size - nh) // 2
    canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera favicon e ícones PWA a partir de PDF ou PNG.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF da logo (página 1).")
    parser.add_argument(
        "--fallback-png",
        type=Path,
        default=FALLBACK_PNG,
        help="PNG se o PDF não existir.",
    )
    parser.add_argument("--dpi", type=float, default=300.0, help="DPI ao rasterizar o PDF.")
    args = parser.parse_args()

    img_src = load_source_image(args.pdf, args.fallback_png, dpi=args.dpi)

    for size, name in SIZES:
        out_path = STATIC / name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        icon = compose_square_icon(img_src, size)
        icon.save(out_path, "PNG", optimize=True)
        print(f"Gerado: {out_path}")


if __name__ == "__main__":
    main()
