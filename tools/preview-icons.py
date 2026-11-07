#!/usr/bin/env python3
"""Render a contact sheet of the built icon theme -> build/preview/icons.png.

Top half on the breach (dark) background, bottom half on parchment. Each half
shows every icon at 96px and the plain folder at the small sizes file
managers and sidebars use.

    ./build.py --only icons && ./tools/preview-icons.py
"""
import io
import re
import sys
from pathlib import Path

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "dist/icons/Cynosure/scalable"
OUT = ROOT / "build/preview/icons.png"
SMALL = [16, 24, 32, 48, 64]
BIG = 96
COLS = 7


def palette():
    text = (ROOT / "common/_palette.scss").read_text()
    return {m[1]: m[2] for m in re.finditer(r"\$([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", text)}


def render(path, size):
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), size, size)
    ok, buf = pb.save_to_bufferv("png", [], [])
    return Image.open(io.BytesIO(buf)).convert("RGBA")


def half(icons, bg, fg):
    rows = (len(icons) + COLS - 1) // COLS
    cell_w, cell_h = 150, 140
    w = COLS * cell_w + 40
    h = rows * cell_h + 130
    img = Image.new("RGBA", (w, h), bg)
    d = ImageDraw.Draw(img)
    for i, path in enumerate(icons):
        x = 20 + (i % COLS) * cell_w
        y = 20 + (i // COLS) * cell_h
        icon = render(path, BIG)
        img.alpha_composite(icon, (x + (cell_w - BIG) // 2, y))
        d.text((x + cell_w // 2, y + BIG + 14), path.stem, fill=fg, anchor="mm")
    x, y = 20, rows * cell_h + 30
    folder = THEME / "places" / "folder.svg"
    for size in SMALL:
        img.alpha_composite(render(folder, size), (x, y + 64 - size))
        d.text((x + size // 2, y + 78), f"{size}px", fill=fg, anchor="mm")
        x += size + 40
    return img


def main():
    if not THEME.exists():
        sys.exit("build first: ./build.py --only icons")
    pal = palette()
    icons = sorted(p for p in THEME.glob("places/*.svg"))
    dark = half(icons, pal["void"], pal["cream"])
    light = half(icons, pal["paper"], pal["ink"])
    sheet = Image.new("RGBA", (dark.width, dark.height + light.height))
    sheet.paste(dark, (0, 0))
    sheet.paste(light, (0, dark.height))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
