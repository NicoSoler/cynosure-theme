#!/usr/bin/env python3
"""Draw a mock JetBrains window from the built themes -> build/preview/jetbrains.png.

Not the real IDE: a sketch of the Islands layout (frame, square islands, a
project tree with a selected row, an editor tab, highlighted code) using the
generated theme tokens and editor scheme, to judge colours without restarting
an IDE. Needs Pillow and Pygments.

    ./build.py --only jetbrains && ./tools/preview-jetbrains.py
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pygments import lex
from pygments.lexers import PythonLexer
from pygments.token import Token

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "preview" / "jetbrains.png"

CODE = '''@dataclass
class Datatermninal:
    """Remote control via dataterminals Alpha and Bravo."""
    name: str
    online: bool = False

    def authorize(self, sector: int = 3) -> str:
        # MX://CORE SHUTDOWN ADVISED...
        code = f"BD 55 1C E9\\n{sector:02d}"
        return code if self.online else None
'''

TOKENS = [  # pygments token -> scheme attribute (first match wins)
    (Token.Comment, "DEFAULT_LINE_COMMENT"), (Token.Literal.String.Doc, "DEFAULT_DOC_COMMENT"),
    (Token.Literal.String.Escape, "DEFAULT_VALID_STRING_ESCAPE"),
    (Token.Literal.String.Interpol, "DEFAULT_VALID_STRING_ESCAPE"),
    (Token.Literal.String, "DEFAULT_STRING"), (Token.Literal.Number, "DEFAULT_NUMBER"),
    (Token.Name.Decorator, "DEFAULT_METADATA"), (Token.Name.Function, "DEFAULT_FUNCTION_DECLARATION"),
    (Token.Name.Class, "DEFAULT_CLASS_NAME"), (Token.Name.Builtin.Pseudo, "DEFAULT_KEYWORD"),
    (Token.Name.Builtin, "DEFAULT_PREDEFINED_SYMBOL"), (Token.Keyword, "DEFAULT_KEYWORD"),
    (Token.Operator, "DEFAULT_OPERATION_SIGN"), (Token.Punctuation, "DEFAULT_BRACES"),
]


def font(family, size, bold=False):
    q = f"{family}:{'bold' if bold else 'regular'}"
    path = subprocess.run(["fc-match", "-f", "%{file}", q], capture_output=True, text=True).stdout
    return ImageFont.truetype(path, size)


class Theme:
    def __init__(self, z, tid):
        self.t = json.loads(z.read(f"themes/{tid}.theme.json"))
        self.s = ET.fromstring(z.read(f"themes/{tid}.xml"))
        self.attrs = {o.get("name"): o for o in self.s.find("attributes")}

    def c(self, name):
        """Token / named colour -> RGBA tuple."""
        v = self.t["colors"].get(name, name)
        for _ in range(10):
            if v.startswith("#"):
                break
            v = self.t["colors"][v]
        h = v.lstrip("#")
        rgba = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
        return tuple(rgba + [255] * (4 - len(rgba)))

    def fg(self, attr, depth=0):
        o = self.attrs.get(attr)
        if o is not None:
            for x in o.iter("option"):
                if x.get("name") == "FOREGROUND" and x.get("value"):
                    h = x.get("value").zfill(6)
                    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
            if o.get("baseAttributes") and depth < 5:
                return self.fg(o.get("baseAttributes"), depth + 1)
        return self.fg("TEXT", depth + 1) if attr != "TEXT" else (200, 200, 200, 255)


def over(base, rgba):
    a = rgba[3] / 255
    return tuple(round(b * (1 - a) + c * a) for b, c in zip(base[:3], rgba[:3])) + (255,)


def draw(th, w=1000, h=520):
    ui, mono = font("Inter, Adwaita Sans, sans-serif", 14), font("JetBrains Mono, Adwaita Mono, monospace", 14)
    frame = th.c("main-window-bg")
    img = Image.new("RGBA", (w, h), frame)
    d = ImageDraw.Draw(img)
    text = th.c("text-default")
    muted = over(frame, th.c("text-muted"))
    d.text((16, 12), "cynosure-theme   main", fill=text, font=ui)
    d.text((w - 160, 12), "RUN   STOP", fill=muted, font=ui)

    gap, top = 6, 40
    # Project island
    tw = th.c("tool-window-bg")
    d.rectangle([gap, top, 250, h - 30], fill=tw)
    d.text((gap + 12, top + 8), "Project", fill=text, font=ui)
    rows = ["v cynosure-theme", "   > common", "   > gtk", "   v jetbrains", "       plugin.xml",
            "       variants.json", "   > sway", "     build.py", "     install.sh"]
    for i, r in enumerate(rows):
        y = top + 36 + i * 24
        if i == 5:
            d.rectangle([gap + 4, y - 3, 246, y + 19], fill=over(tw, th.c("selection-bg-active")))
        d.text((gap + 12, y), r, fill=text, font=ui)

    # Editor island
    ex = 250 + gap
    eb = th.c("editor-bg")
    d.rectangle([ex, top, w - gap, h - 30], fill=eb)
    d.text((ex + 14, top + 8), "datatermninal.py", fill=text, font=ui)
    tab_w = d.textlength("datatermninal.py", font=ui)
    d.rectangle([ex + 10, top + 30, ex + 18 + tab_w, top + 32], fill=th.c("tab-selected-border-active"))
    d.line([ex, top + 33, w - gap, top + 33], fill=over(eb, th.c("editor-border")))

    y0 = top + 46
    ln = over(eb, (*th.fg("TEXT")[:3], 77))
    caret_line = 6
    d.rectangle([ex, y0 + caret_line * 22 - 2, w - gap, y0 + caret_line * 22 + 18],
                fill=over(eb, (*th.fg("TEXT")[:3], 13)))
    x, line = ex + 56, 0
    d.text((ex + 12, y0), " 1", fill=ln, font=mono)
    for tok, val in lex(CODE, PythonLexer()):
        attr = next((a for t, a in TOKENS if tok in t), "TEXT")
        for j, part in enumerate(val.split("\n")):
            if j:
                line += 1
                x = ex + 56
                if line < CODE.count("\n"):
                    d.text((ex + 12, y0 + line * 22), f"{line + 1:2d}", fill=ln, font=mono)
            if part:
                d.text((x, y0 + line * 22), part, fill=th.fg(attr), font=mono)
                x += d.textlength(part, font=mono)

    # Status bar
    d.text((16, h - 24), "jetbrains › variants.json", fill=muted, font=ui)
    d.text((w - 220, h - 24), "4:32   UTF-8   Python 3.13", fill=muted, font=ui)
    return img


def main():
    jars = sorted((ROOT / "dist" / "jetbrains").glob("*.jar"))
    if not jars:
        sys.exit("build first: ./build.py --only jetbrains")
    with zipfile.ZipFile(jars[-1]) as z:
        a = draw(Theme(z, "cynosure-breach"))
        b = draw(Theme(z, "cynosure-parchment"))
    sheet = Image.new("RGBA", (a.width, a.height + b.height + 10), (255, 255, 255, 255))
    sheet.paste(a, (0, 0))
    sheet.paste(b, (0, a.height + 10))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
