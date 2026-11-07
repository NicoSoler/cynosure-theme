#!/usr/bin/env python3
"""Build the Cynosure themes into dist/.

GTK 4:  gtk/gtk.scss  ->  dist/Cynosure/gtk-4.0/libadwaita.css
        (deliberately not gtk.css: plain GTK 4 apps would load that as a full
        theme when Cynosure is selected; libadwaita gets it via
        ~/.config/gtk-4.0/gtk.css, linked by gtk/cynosure-gtk-sync)

Shell:  GNOME's own light stylesheet is extracted from the installed
        gnome-shell-theme.gresource, recoloured onto the Cynosure palette,
        has its corner radii flattened, and gets gnome-shell/gnome-shell.scss
        appended  ->  dist/Cynosure/gnome-shell/gnome-shell.css

        Because the base comes from the installed Shell, rebuild after a
        GNOME upgrade:  ./build.py --refresh

Sway:   every file under sway/ is copied to dist/sway/ (same layout as
        ~/.config), with palette placeholders filled in:

            {{paper}}          -> #e4d9b0
            {{paper|bare}}     -> e4d9b0      (foot, swaylock, swaynag)
            {{paper|cc}}       -> #e4d9b0cc   (append alpha)
            {{paper|bare|ff}}  -> e4d9b0ff    (fuzzel)

Icons:  icons/folder.svg is rendered once per entry in icons/manifest.json,
        with a glyph from icons/glyphs/ printed on the folder face
        ->  dist/icons/Cynosure/  (inherits Adwaita for everything else)

VS Code: vscode/theme.jsonc is rendered once per variant in vscode/variants.json
        (roles -> palette colours) and packed with vscode/package.json
        ->  dist/vscode/cynosure-theme-<version>.vsix

Firefox: firefox/*.css (palette placeholders) -> dist/firefox/, installed to
        <profile>/chrome/cynosure/ and @import-ed from userChrome/userContent.css

Requires: python3, sassc (or dart-sass `sass`), and `gresource` (glib2) for
extracting the upstream stylesheet.
"""

import argparse
import colorsys
import json
import re
import shutil
import zipfile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMON = ROOT / "common"        # palette + fonts, shared by every target
GTK_SRC = ROOT / "gtk" / "gtk.scss"
SHELL_SRC = ROOT / "gnome-shell" / "gnome-shell.scss"
SWAY_SRC = ROOT / "sway"
ICONS_SRC = ROOT / "icons"
VSCODE_SRC = ROOT / "vscode"
FIREFOX_SRC = ROOT / "firefox"
BUILD = ROOT / "build"
DIST = ROOT / "dist" / "Cynosure"   # GNOME-style theme dir -> ~/.themes/Cynosure
DIST_SWAY = ROOT / "dist" / "sway"  # mirrors ~/.config
DIST_ICONS = ROOT / "dist" / "icons" / "Cynosure"   # -> ~/.local/share/icons/Cynosure
DIST_VSCODE = ROOT / "dist" / "vscode"              # unpacked extension + .vsix
DIST_FIREFOX = ROOT / "dist" / "firefox"            # -> <profile>/chrome/cynosure/

SHELL_GRESOURCE = "/usr/share/gnome-shell/gnome-shell-theme.gresource"
SHELL_RESOURCE = "/org/gnome/shell/theme/gnome-shell-light.css"
UPSTREAM_CSS = BUILD / "upstream" / "gnome-shell-light.css"


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

def load_palette():
    """Read `$name: #hex;` declarations from common/_palette.scss."""
    text = (COMMON / "_palette.scss").read_text()
    pal = {m[1]: m[2].lower()
           for m in re.finditer(r"\$([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", text)}
    if not pal:
        sys.exit("error: no colours found in common/_palette.scss")
    return pal


def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def luminance(rgb):
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class Recolor:
    """Maps upstream (Adwaita light) colours onto the Cynosure palette.

    Neutral greys are mapped by luminance along GREY_RAMP: each anchor pins an
    upstream grey to a palette colour, and greys in between are interpolated.
    Saturated colours are mapped by hue family. Near-black is left alone so
    shadows stay shadows.

    To change how something is recoloured, edit GREY_RAMP / HUE_FAMILIES.
    """

    # (upstream grey, palette colour). Must be sorted by luminance.
    GREY_RAMP = [
        ("#0c0c0e", "ink"),
        ("#222226", "ink"),         # body text
        ("#2e2e33", "navy"),        # dark surfaces (OSD, keys)
        ("#38383b", "navy-light"),
        ("#6b6b6e", "ink-soft"),    # dim text
        ("#cacad4", "paper-deep"),  # sub-menus
        ("#ececf0", "paper-dark"),  # hover fills
        ("#fafafb", "paper"),       # main surfaces
        ("#ffffff", "paper-light"), # cards, entries
    ]

    def __init__(self, pal):
        self.pal = pal
        self.ramp = [(luminance(hex_to_rgb(up)), hex_to_rgb(pal[name]))
                     for up, name in self.GREY_RAMP]
        self.hue_families = [
            # (hue range in degrees, palette colour, upstream reference shade).
            # Upstream shades darker/lighter than the reference (hover, pressed)
            # keep that lightness offset relative to the palette colour.
            ((340, 360), "red", "#c01c28"),
            ((0, 15), "red", "#c01c28"),
            ((15, 65), "amber", "#e5a50a"),
        ]
        self.fallback = "navy"   # blues, greens, purples...

    def grey(self, rgb):
        lum = luminance(rgb)
        if lum <= self.ramp[0][0]:
            return self.ramp[0][1]
        for (l0, c0), (l1, c1) in zip(self.ramp, self.ramp[1:]):
            if lum <= l1:
                return lerp(c0, c1, (lum - l0) / (l1 - l0) if l1 > l0 else 0)
        return self.ramp[-1][1]

    def map(self, rgb):
        if max(rgb) < 12:               # black / near-black: shadows
            return rgb
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        if s < 0.12 or max(rgb) - min(rgb) < 12:
            return self.grey(rgb)
        deg = h * 360
        for (lo, hi), name, ref in self.hue_families:
            if lo <= deg < hi:
                ref_l = colorsys.rgb_to_hls(*(c / 255 for c in hex_to_rgb(ref)))[1]
                th, tl, ts = colorsys.rgb_to_hls(*(c / 255 for c in hex_to_rgb(self.pal[name])))
                nl = max(0.0, min(1.0, tl + (l - ref_l)))
                return tuple(c * 255 for c in colorsys.hls_to_rgb(th, nl, ts))
        return hex_to_rgb(self.pal[self.fallback])

    def css(self, text):
        seen = {}

        def sub_hex(m):
            out = rgb_to_hex(self.map(hex_to_rgb(m[1])))
            seen[m[0].lower()] = out
            return out

        def sub_rgb(m):
            r, g, b = (int(x) for x in m.group(2, 3, 4))
            nr, ng, nb = (round(c) for c in self.map((r, g, b)))
            return f"{m[1]}({nr}, {ng}, {nb}"

        text = re.sub(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", sub_hex, text)
        text = re.sub(r"(rgba?)\((\d+),\s*(\d+),\s*(\d+)", sub_rgb, text)
        text = re.sub(r"\bwhite\b(?!-)", self.pal["paper-light"], text)
        # The system accent colour becomes Cynosure navy, whatever the user picked.
        text = text.replace("-st-accent-fg-color", self.pal["paper-light"])
        text = text.replace("-st-accent-color", self.pal["navy"])
        return text, seen


def flatten_radii(text):
    """Every corner on a Cynosure terminal is square."""
    return re.sub(r"((?:-arrow-)?border-radius)\s*:[^;}]*", r"\1: 0", text)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

def compile_scss(path):
    if shutil.which("sassc"):
        cmd = ["sassc", "-t", "expanded", "-I", str(COMMON), str(path)]
    elif shutil.which("sass"):
        cmd = ["sass", "--no-source-map", "--quiet-deps", "-I", str(COMMON), str(path)]
    else:
        sys.exit("error: need `sassc` or `sass` (dart-sass) on PATH")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        sys.exit(f"error compiling {path.relative_to(ROOT)}:\n{res.stderr}")
    return res.stdout


def shell_available():
    return UPSTREAM_CSS.exists() or Path(SHELL_GRESOURCE).exists()


def upstream_shell_css(refresh):
    if UPSTREAM_CSS.exists() and not refresh:
        return UPSTREAM_CSS.read_text()
    if not shutil.which("gresource"):
        sys.exit("error: need `gresource` (glib2) to extract the Shell stylesheet")
    res = subprocess.run(["gresource", "extract", SHELL_GRESOURCE, SHELL_RESOURCE],
                         capture_output=True, text=True)
    if res.returncode:
        sys.exit(f"error extracting {SHELL_RESOURCE}:\n{res.stderr}")
    version = subprocess.run(["gnome-shell", "--version"],
                             capture_output=True, text=True).stdout.strip()
    UPSTREAM_CSS.parent.mkdir(parents=True, exist_ok=True)
    UPSTREAM_CSS.write_text(res.stdout)
    (UPSTREAM_CSS.parent / "VERSION").write_text(version + "\n")
    print(f"  extracted upstream stylesheet from {version or 'GNOME Shell'}")
    return res.stdout


# --------------------------------------------------------------------------
# Templates (Sway & friends)
# --------------------------------------------------------------------------

def is_colour(value):
    return re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def resolve_colour(spec, pal, where):
    """'khaki' or 'khaki|99' -> '#7f7849' / '#7f784999'."""
    name, *filters = spec.split("|")
    if name not in pal:
        sys.exit(f"error: {where}: unknown palette colour '{name}'")
    value = pal[name]
    for f in filters:
        if not re.fullmatch(r"[0-9a-fA-F]{2}", f):
            sys.exit(f"error: {where}: bad alpha '|{f}' in '{spec}'")
        value += f.lower()
    return value


PLACEHOLDER = re.compile(r"\{\{\s*([\w-]+)((?:\|[\w]+)*)\s*\}\}")


def render_template(text, pal, where, extra=None):
    """Fill {{name|filters}} placeholders. `extra` holds non-colour values
    (e.g. an icon's glyph markup) that are inserted verbatim."""
    extra = extra or {}

    def sub(m):
        name, filters = m[1], [f for f in m[2].split("|") if f]
        if name in extra and not (filters and is_colour(extra[name])):
            if filters:
                sys.exit(f"error: {where}: filters on non-colour {{{{{name}}}}}")
            return extra[name]
        if name in extra:
            value = extra[name]
        elif name not in pal:
            line = text.count("\n", 0, m.start()) + 1
            sys.exit(f"error: {where}:{line}: unknown palette colour {{{{{name}}}}}")
        else:
            value = pal[name]
        for f in filters:
            if f == "bare":
                value = value.lstrip("#")
            elif re.fullmatch(r"[0-9a-fA-F]{2}", f):
                value += f.lower()
            else:
                sys.exit(f"error: {where}: unknown filter |{f} on {{{{{name}}}}}")
        return value

    return PLACEHOLDER.sub(sub, text)


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

HEADER = """\
/* Cynosure — {what}
 * GENERATED by build.py from {src} — edit that instead.
 */
"""


def build_gtk(pal):
    out = DIST / "gtk-4.0" / "libadwaita.css"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(HEADER.format(what="GTK 4 / libadwaita", src="gtk/gtk.scss") +
                   compile_scss(GTK_SRC))
    print(f"  {out.relative_to(ROOT)}")
    # GTK 3 layer (tooltips...), imported after adw-gtk3 by cynosure-gtk-sync.
    render_dir(pal, ROOT / "gtk" / "gtk-3.0", DIST / "gtk-3.0")


def build_shell(pal, refresh, verbose):
    base, seen = Recolor(pal).css(upstream_shell_css(refresh))
    base = flatten_radii(base)
    overrides = compile_scss(SHELL_SRC)

    out = DIST / "gnome-shell" / "gnome-shell.css"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        HEADER.format(what="GNOME Shell", src="gnome-shell/gnome-shell.scss") +
        "\n/* ---- 1. upstream gnome-shell-light.css, recoloured ---- */\n" + base +
        "\n\n/* ---- 2. gnome-shell/gnome-shell.scss ---- */\n" + overrides)
    print(f"  {out.relative_to(ROOT)}  ({len(seen)} upstream colours remapped)")
    if verbose:
        for up, new in sorted(seen.items()):
            print(f"    {up} -> {new}")


def build_index():
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "index.theme").write_text(
        "[Desktop Entry]\n"
        "Type=X-GNOME-Metatheme\n"
        "Name=Cynosure\n"
        "Comment=Encryption measures & defensive ICE\n"
        "Encoding=UTF-8\n\n"
        "[X-GNOME-Metatheme]\n"
        "GtkTheme=Cynosure\n")


def render_dir(pal, src_dir, out_dir):
    """Render every file under src_dir (palette placeholders) into out_dir."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    count = 0
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file() or src.name == "README.md":
            continue
        rel = src.relative_to(src_dir)
        out = out_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text()
        except UnicodeDecodeError:          # binary asset: copy verbatim
            shutil.copy2(src, out)
        else:
            out.write_text(render_template(text, pal, f"{src_dir.name}/{rel}"))
            shutil.copymode(src, out)       # keep scripts executable
        count += 1
    print(f"  {out_dir.relative_to(ROOT)}/  ({count} files)")


def build_sway(pal):
    render_dir(pal, SWAY_SRC, DIST_SWAY)


def build_firefox(pal):
    render_dir(pal, FIREFOX_SRC, DIST_FIREFOX)


ICON_INDEX = """\
[Icon Theme]
Name=Cynosure
Comment=Datafile folders from the Cynosure terminals
Example=folder
Inherits=Adwaita,AdwaitaLegacy,hicolor
Directories={dirs}
"""

ICON_DIR = """
[{dir}]
Context={context}
Size=128
MinSize=8
MaxSize=512
Type=Scalable
"""


def build_icons(pal):
    manifest = json.loads((ICONS_SRC / "manifest.json").read_text())
    template = (ICONS_SRC / "folder.svg").read_text()
    defaults = manifest.get("defaults", {})
    if DIST_ICONS.exists():
        shutil.rmtree(DIST_ICONS)

    def colour(name, where):
        if name not in pal:
            sys.exit(f"error: {where}: unknown palette colour '{name}'")
        return pal[name]

    rendered, contexts = {}, set()

    def write(name, svg, context):
        out = DIST_ICONS / "scalable" / context / f"{name}.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(svg)
        contexts.add(context)

    for name, opts in manifest["icons"].items():
        opts = {**defaults, **opts}
        where = f"icons/manifest.json [{name}]"
        glyph = ""
        if "glyph" in opts:
            gpath = ICONS_SRC / "glyphs" / f"{opts['glyph']}.svg"
            if not gpath.exists():
                sys.exit(f"error: {where}: no glyph {gpath.relative_to(ROOT)}")
            glyph = gpath.read_text()
        face_a, face_b = (colour(c, where) for c in opts["face"])
        svg = render_template(template, pal, f"icons/folder.svg ({name})", {
            "face-a": face_a, "face-b": face_b,
            "label": colour(opts["label"], where), "glyph": glyph,
        })
        # Strip comments: file-type sniffing (shared-mime-info) only looks for
        # "<svg" near the start of the file, and the template's docs push it out.
        svg = re.sub(r"<!--.*?-->\s*", "", svg, flags=re.S)
        rendered[name] = svg
        write(name, svg, opts["context"])

    for name, opts in manifest.get("aliases", {}).items():
        if opts["icon"] not in rendered:
            sys.exit(f"error: icons/manifest.json alias {name}: unknown icon {opts['icon']}")
        write(name, rendered[opts["icon"]], opts.get("context", defaults.get("context", "places")))

    dirs = [f"scalable/{c}" for c in sorted(contexts)]
    (DIST_ICONS / "index.theme").write_text(
        ICON_INDEX.format(dirs=",".join(dirs)) +
        "".join(ICON_DIR.format(dir=d, context=d.split("/")[1].capitalize()) for d in dirs))
    count = len(rendered) + len(manifest.get("aliases", {}))
    print(f"  {DIST_ICONS.relative_to(ROOT)}/  ({count} icons)")


VSIX_CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json"/>
  <Default Extension=".vsixmanifest" ContentType="text/xml"/>
  <Default Extension=".md" ContentType="text/markdown"/>
</Types>
"""

VSIX_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{name}" Version="{version}" Publisher="{publisher}"/>
    <DisplayName>{displayName}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Tags>{tags}</Tags>
    <Categories>Themes</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{engine}"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui,workspace"/>
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value=""/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true"/>
  </Assets>
</PackageManifest>
"""


def strip_jsonc(text):
    """Remove full-line // comments (all the template uses)."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))


def build_vscode(pal):
    from xml.sax.saxutils import escape
    pkg = json.loads((VSCODE_SRC / "package.json").read_text())
    variants = json.loads((VSCODE_SRC / "variants.json").read_text())
    template = (VSCODE_SRC / "theme.jsonc").read_text()
    if DIST_VSCODE.exists():
        shutil.rmtree(DIST_VSCODE)
    ext = DIST_VSCODE / pkg["name"]
    (ext / "themes").mkdir(parents=True)

    pkg["contributes"]["themes"] = []
    for label, v in variants.items():
        if label.startswith("_"):
            continue
        where = f"vscode/variants.json [{label}]"
        roles = {k: resolve_colour(c, pal, f"{where} {k}") for k, c in v["roles"].items()}
        roles.update(name=label, type="dark" if v["uiTheme"] == "vs-dark" else "light")
        text = render_template(template, pal, f"vscode/theme.jsonc ({label})", roles)
        try:
            theme = json.loads(strip_jsonc(text))
        except json.JSONDecodeError as e:
            sys.exit(f"error: vscode/theme.jsonc ({label}) is not valid JSON: {e}")
        rel = f"./themes/{v['file']}-color-theme.json"
        (ext / rel).write_text(json.dumps(theme, indent=2) + "\n")
        pkg["contributes"]["themes"].append({"label": label, "uiTheme": v["uiTheme"], "path": rel})

    (ext / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")
    shutil.copy2(VSCODE_SRC / "README.md", ext / "README.md")

    # A .vsix is a zip: [Content_Types].xml + extension.vsixmanifest + extension/...
    vsix = DIST_VSCODE / f"{pkg['name']}-{pkg['version']}.vsix"
    manifest = VSIX_MANIFEST.format(
        name=pkg["name"], version=pkg["version"], publisher=pkg["publisher"],
        displayName=escape(pkg["displayName"]), description=escape(pkg["description"]),
        tags=escape(",".join(pkg.get("keywords", []))), engine=pkg["engines"]["vscode"])
    with zipfile.ZipFile(vsix, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", VSIX_CONTENT_TYPES)
        z.writestr("extension.vsixmanifest", manifest)
        for f in sorted(ext.rglob("*")):
            if f.is_file():
                z.write(f, "extension/" + f.relative_to(ext).as_posix())
    print(f"  {vsix.relative_to(ROOT)}  ({len(pkg['contributes']['themes'])} themes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true",
                    help="re-extract the upstream Shell stylesheet (after a GNOME upgrade)")
    ap.add_argument("--only", choices=["gtk", "shell", "sway", "icons", "vscode", "firefox"], action="append",
                    help="build only these targets (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every upstream colour and what it was mapped to")
    args = ap.parse_args()
    targets = set(args.only or ["gtk", "shell", "sway", "icons", "vscode", "firefox"])

    pal = load_palette()
    print("Building Cynosure")
    if "gtk" in targets:
        build_gtk(pal)
    if "shell" in targets:
        if shell_available() or args.only:
            build_shell(pal, args.refresh, args.verbose)
        else:
            print("  skipping GNOME Shell (not installed here)")
    if targets & {"gtk", "shell"}:
        build_index()
    if "icons" in targets:
        build_icons(pal)
    if "sway" in targets:
        build_sway(pal)
    if "vscode" in targets:
        build_vscode(pal)
    if "firefox" in targets:
        build_firefox(pal)
    print("Done -> dist/")


if __name__ == "__main__":
    main()
