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

JetBrains: the installed IDE's Islands theme (UI + editor schemes), recoloured
        with jetbrains/variants.json and the shared editor roles
        ->  dist/jetbrains/cynosure-theme-<version>.jar

Requires: python3, sassc (or dart-sass `sass`), and `gresource` (glib2) for
extracting the upstream stylesheet.
"""

import argparse
import colorsys
import json
import copy
import os
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
JETBRAINS_SRC = ROOT / "jetbrains"
BUILD = ROOT / "build"
DIST = ROOT / "dist" / "Cynosure"   # GNOME-style theme dir -> ~/.themes/Cynosure
DIST_SWAY = ROOT / "dist" / "sway"  # mirrors ~/.config
DIST_ICONS = ROOT / "dist" / "icons" / "Cynosure"   # -> ~/.local/share/icons/Cynosure
DIST_VSCODE = ROOT / "dist" / "vscode"              # unpacked extension + .vsix
DIST_FIREFOX = ROOT / "dist" / "firefox"            # -> <profile>/chrome/cynosure/
DIST_JETBRAINS = ROOT / "dist" / "jetbrains"        # plugin .jar
JB_UPSTREAM = BUILD / "upstream" / "jetbrains"

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


def load_roles(name, overrides=None):
    """A role set from common/editor-roles.json, plus per-consumer overrides."""
    sets = json.loads((COMMON / "editor-roles.json").read_text())
    if name not in sets:
        sys.exit(f"error: common/editor-roles.json has no role set '{name}'")
    return {**sets[name], **(overrides or {})}


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
        roles = {k: resolve_colour(c, pal, f"{where} {k}")
                 for k, c in load_roles(v["roles"]).items()}
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



# --------------------------------------------------------------------------
# JetBrains
# --------------------------------------------------------------------------
#
# Like the Shell theme, the JetBrains themes are generated from the installed
# IDE's own theme (Islands) so they cover every UI key of that version:
#   1. extract the Islands themes + their parents and the editor schemes
#      (Default, Darcula, per-language add-ons) from the IDE's jars;
#   2. merge each inheritance chain into one theme / one scheme;
#   3. recolour every colour with the variant's ramps (jetbrains/variants.json),
#      pin the semantic tokens and the shared editor roles, zero all radii;
#   4. pack META-INF/plugin.xml + themes/ into a plugin .jar.

import xml.etree.ElementTree as ET

JB_THEME_FILES = {   # cache name -> path inside intellij.platform.ide.impl.jar
    "islands-dark.theme.json": "themes/islands/ManyIslandsDark.theme.json",
    "islands-light.theme.json": "themes/islands/ManyIslandsLight.theme.json",
    "expui-dark.theme.json": "themes/expUI/expUI_dark.theme.json",
    "expui-light.theme.json": "themes/expUI/expUI_light.theme.json",
    "expui-light-header.theme.json": "themes/expUI/expUI_light_with_light_header.theme.json",
    "islands-dark-scheme.xml": "themes/islands/IslandSchemeDark.xml",
    "light-scheme.xml": "themes/expUI/expUI_lightScheme.xml",
    "default-schemes.xml": "DefaultColorSchemesManager.xml",
}
# UI inheritance chains (parent first); the theme keeps Islands' own parent.
JB_UI_CHAIN = {
    "dark": ["expui-dark.theme.json", "islands-dark.theme.json"],
    "light": ["expui-light.theme.json", "expui-light-header.theme.json", "islands-light.theme.json"],
}
# Editor scheme chains: base scheme(s) from DefaultColorSchemesManager.xml, the
# per-language add-on suffix, and the Islands-specific scheme on top.
# The dark chain must NOT include Default: Darcula leaves many keys undefined
# on purpose (e.g. Java's STATIC_FINAL_FIELD_ATTRIBUTES, used for enum
# constants) so they fall back to DEFAULT_CONSTANT & co.; Default's explicit
# values are dark colours meant for a white background.
JB_SCHEME_CHAIN = {
    "dark": (["Darcula"], "Darcula", "islands-dark-scheme.xml", "Darcula"),
    "light": (["Default"], "Default", "light-scheme.xml", "Default"),
}
JB_COLOR_FIELDS = {"FOREGROUND", "BACKGROUND", "EFFECT_COLOR", "ERROR_STRIPE_COLOR"}


def find_jetbrains_ide():
    """An installed IDE with the Islands theme: $JETBRAINS_IDE, Toolbox apps, /opt."""
    cands = [Path(os.environ["JETBRAINS_IDE"])] if os.environ.get("JETBRAINS_IDE") else []
    apps = sorted(Path.home().glob(".local/share/JetBrains/Toolbox/apps/*"))
    apps.sort(key=lambda p: "idea" not in p.name)      # IDEA first: most plugins
    cands += apps + sorted(Path("/opt").glob("*"))
    for c in cands:
        if (c / "lib" / "intellij.platform.ide.impl.jar").exists():
            return c
    return None


def jetbrains_upstream(refresh):
    """Extract (or reuse) the upstream theme files; returns the cache dir."""
    stamp = JB_UPSTREAM / "VERSION"
    if stamp.exists() and not refresh:
        return JB_UPSTREAM
    ide = find_jetbrains_ide()
    if not ide:
        return None
    if JB_UPSTREAM.exists():
        shutil.rmtree(JB_UPSTREAM)
    (JB_UPSTREAM / "addons").mkdir(parents=True)
    with zipfile.ZipFile(ide / "lib" / "intellij.platform.ide.impl.jar") as z:
        for name, inner in JB_THEME_FILES.items():
            (JB_UPSTREAM / name).write_bytes(z.read(inner))
    # Per-language scheme add-ons (XmlDarcula.xml, SqlDefault.xml...).
    addon = re.compile(r"^colorSchemes/[\w.-]*(Darcula|Default)\.xml$")
    for jar in sorted(ide.glob("lib/**/*.jar")) + sorted(ide.glob("plugins/**/*.jar")):
        try:
            with zipfile.ZipFile(jar) as z:
                for n in z.namelist():
                    if addon.match(n):
                        (JB_UPSTREAM / "addons" / f"{jar.stem}__{Path(n).name}").write_bytes(z.read(n))
        except zipfile.BadZipFile:
            continue
    info = json.loads((ide / "product-info.json").read_text()) if (ide / "product-info.json").exists() else {}
    stamp.write_text(f"{info.get('name', ide.name)} {info.get('version', '')} ({info.get('buildNumber', '?')})\n")
    print(f"  extracted JetBrains themes from {stamp.read_text().strip()}")
    return JB_UPSTREAM


class Ramps:
    """Maps any colour onto palette ramps: greys by luminance onto 'grey',
    saturated colours onto the ramp of their hue family."""

    FAMILIES = [(15, "red"), (70, "amber"), (165, "green"), (200, "cyan"),
                (255, "blue"), (345, "magenta"), (360, "red")]

    def __init__(self, spec, pal, where):
        self.ramps = {}
        for fam, names in spec.items():
            pts = []
            for n in names:
                if n not in pal:
                    sys.exit(f"error: {where}: unknown palette colour '{n}' in ramp '{fam}'")
                rgb = hex_to_rgb(pal[n])
                pts.append((luminance(rgb), rgb))
            self.ramps[fam] = sorted(pts)
        if "grey" not in self.ramps:
            sys.exit(f"error: {where}: every ramp set needs a 'grey' ramp")

    def family(self, rgb):
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        if s < 0.15 or max(rgb) - min(rgb) < 24:
            return "grey"
        deg = h * 360
        fam = next(f for limit, f in self.FAMILIES if deg < limit)
        return fam if fam in self.ramps else "grey"

    def map(self, rgb):
        pts = self.ramps[self.family(rgb)]
        lum = luminance(rgb)
        if lum <= pts[0][0]:
            return pts[0][1]
        for (l0, c0), (l1, c1) in zip(pts, pts[1:]):
            if lum <= l1:
                return lerp(c0, c1, (lum - l0) / (l1 - l0) if l1 > l0 else 0)
        return pts[-1][1]

    def hex(self, value):
        """'#RRGGBB[AA]' (or bare 'RRGGBB' for schemes) -> recoloured, same form."""
        m = re.fullmatch(r"(#?)([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", value)
        if not m:
            return value
        rgb = hex_to_rgb(m[2])
        new = rgb if max(rgb) < 8 else self.map(rgb)    # keep black (shadows)
        out = rgb_to_hex(new)[1:]
        out = out.upper() if m[2].isupper() else out
        return f"{m[1]}{out}{m[3] or ''}"


def wcag_contrast(a, b):
    """WCAG contrast ratio of two RGB tuples."""
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    la, lb = (0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b_) for r, g, b_ in (a, b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg, bg, toward, minimum):
    """Mix fg toward `toward` (the main text colour) until it reaches `minimum`
    contrast against bg. Keeps the hue; muted colours stay muted, just legible."""
    if wcag_contrast(fg, bg) >= minimum:
        return fg
    for step in range(1, 21):
        c = lerp(fg, toward, step / 20)
        if wcag_contrast(c, bg) >= minimum:
            return c
    return toward


def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def recolour_json(obj, ramps, keep_keys=False):
    """Recolour every #hex in string values (dict keys untouched)."""
    if isinstance(obj, dict):
        return {k: recolour_json(v, ramps) for k, v in obj.items()}
    if isinstance(obj, list):
        return [recolour_json(v, ramps) for v in obj]
    if isinstance(obj, str):
        return re.sub(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", lambda m: ramps.hex(m[0]), obj)
    return obj


def zero_arcs(ui):
    """Square corners: every *arc / *ArcLength key becomes 0 (or '0,0,0,0')."""
    for k, v in ui.items():
        if isinstance(v, dict):
            zero_arcs(v)
        elif re.search(r"(?i)arc(length)?(\.compact)?$", k) and "color" not in k.lower():
            if isinstance(v, str) and "," in v:
                ui[k] = ",".join("0" for _ in v.split(","))
            elif isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                ui[k] = 0


def jb_colour(spec, pal, where):
    """Palette spec -> '#RRGGBB' / '#RRGGBBAA' (JetBrains takes 8-digit hex)."""
    return resolve_colour(spec, pal, where).upper()


def jb_theme(v, pal, up, ramps):
    chain = [json.loads((up / f).read_text()) for f in JB_UI_CHAIN[v["upstream"]]]
    islands = chain[-1]
    colors, ui, icons = {}, {}, {}
    for t in chain:
        colors = deep_merge(colors, t.get("colors", {}))
        ui = deep_merge(ui, t.get("ui", {}))
        icons = deep_merge(icons, t.get("icons", {}))
    where = f"jetbrains/variants.json [{v['id']}]"
    colors = recolour_json(colors, ramps)
    ui = recolour_json(ui, ramps)
    icons = recolour_json(icons, ramps)       # ColorPalette: keys are SVG colours, kept
    for token, spec in v.get("tokens", {}).items():
        if token not in colors:
            print(f"    note: token '{token}' isn't defined upstream any more")
        colors[token] = jb_colour(spec, pal, f"{where} token {token}")
    zero_arcs(ui)
    ui = deep_merge(ui, v.get("ui", {}))
    return {
        "name": v["name"],
        "dark": v["dark"],
        "author": "Cynosure (generated from JetBrains Islands)",
        "parentTheme": islands.get("parentTheme"),
        "editorScheme": f"/themes/{v['id']}.xml",
        "colors": colors,
        "ui": ui,
        "icons": icons,
    }


def scheme_options(root):
    """(colors, attributes) option elements of a <scheme> / add-on file."""
    colors, attrs = {}, {}
    for sect, store in (("colors", colors), ("attributes", attrs)):
        for el in root.iter(sect):
            for opt in el.findall("option"):
                store[opt.get("name")] = copy.deepcopy(opt)
    return colors, attrs


def jb_scheme(v, pal, up, ramps, roles):
    bases, suffix, top, parent = JB_SCHEME_CHAIN[v["upstream"]]
    managers = ET.parse(up / "default-schemes.xml").getroot()
    sources = [s for b in bases for s in managers.iter("scheme") if s.get("name") == b]
    sources += [ET.parse(f).getroot() for f in sorted((up / "addons").glob(f"*{suffix}.xml"))]
    sources.append(ET.parse(up / top).getroot())
    colors, attrs = {}, {}
    for src in sources:
        c, a = scheme_options(src)
        colors.update(c)
        attrs.update(a)

    def rc(val):
        """Scheme colours are bare hex: RRGGBB, RRGGBBAA, or short ('0')."""
        if val and re.fullmatch(r"[0-9a-fA-F]{8}", val):
            return ramps.hex(val)
        if val and re.fullmatch(r"[0-9a-fA-F]{1,6}", val):
            return ramps.hex(val.zfill(6))
        return val

    for opt in colors.values():
        opt.set("value", rc(opt.get("value")))
    for opt in attrs.values():
        for o in opt.iter("option"):
            if o.get("name") in JB_COLOR_FIELDS:
                for k in ("value", "deuteranopia", "protanopia"):
                    if o.get(k):
                        o.set(k, rc(o.get(k)))

    # --- the shared editor roles on top ---------------------------------------
    where = f"jetbrains/variants.json [{v['id']}] roles"
    bg = hex_to_rgb(resolve_colour(roles["bg"], pal, where)[:7])
    text = hex_to_rgb(resolve_colour(roles["fg"], pal, where)[:7])

    # Upstream colours are tuned for upstream backgrounds (white, Darcula grey);
    # after recolouring some text colours end up too close to ours. Lift every
    # foreground that has no background of its own to a minimum contrast.
    minimum = v.get("min_contrast", 3.0)
    lifted = 0
    for opt in attrs.values():
        val = opt.find("value")
        if val is None:
            continue
        fields = {o.get("name"): o for o in val.findall("option")}
        fg_opt, bg_opt = fields.get("FOREGROUND"), fields.get("BACKGROUND")
        if fg_opt is None or (bg_opt is not None and bg_opt.get("value")):
            continue
        h = fg_opt.get("value") or ""
        if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
            continue
        new = ensure_contrast(hex_to_rgb(h), bg, text, minimum)
        if new != hex_to_rgb(h):
            fg_opt.set("value", rgb_to_hex(new)[1:])
            lifted += 1
    if lifted:
        print(f"    {v['name']}: lifted {lifted} text colours to {minimum}:1 contrast")

    def solid(spec, alpha=None):
        """Role colour as 6-hex, alpha (from spec or argument) blended onto bg."""
        c = resolve_colour(spec, pal, where)
        a = int(c[7:9], 16) / 255 if len(c) > 7 else 1.0
        if alpha is not None:
            a = alpha
        return rgb_to_hex(lerp(bg, hex_to_rgb(c[:7]), a))[1:]

    def set_colour(name, value):
        el = ET.Element("option", name=name, value=value)
        colors[name] = el

    def set_attr(name, fg=None, bg_=None, font=None):
        opt = attrs.get(name)
        if opt is None or opt.find("value") is None:
            opt = ET.Element("option", name=name)
            ET.SubElement(opt, "value")
        opt.attrib.pop("baseAttributes", None)
        val = opt.find("value")
        for field, value in (("FOREGROUND", fg), ("BACKGROUND", bg_), ("FONT_TYPE", font)):
            if value is None:
                continue
            o = next((o for o in val.findall("option") if o.get("name") == field), None)
            if o is None:
                o = ET.SubElement(val, "option", name=field)
            o.attrib.clear()
            o.set("name", field)
            o.set("value", value)
        attrs[name] = opt

    R = lambda role, a=None: solid(roles[role], a)
    for name, val in {
        "CARET_COLOR": R("cursor"), "CARET_ROW_COLOR": R("fg", 0.05),
        "SELECTION_BACKGROUND": R("editor-select"), "GUTTER_BACKGROUND": R("bg"),
        "LINE_NUMBERS_COLOR": R("fg", 0.3), "LINE_NUMBER_ON_CARET_ROW_COLOR": R("fg"),
        "INDENT_GUIDE": R("rule", 0.1), "SELECTED_INDENT_GUIDE": R("rule", 0.3),
        "RIGHT_MARGIN_COLOR": R("rule", 0.1), "WHITESPACES": R("fg", 0.15),
        "CONSOLE_BACKGROUND_KEY": R("term-bg"), "DOCUMENTATION_COLOR": R("bg-raised"),
        "ADDED_LINES_COLOR": R("success"), "MODIFIED_LINES_COLOR": R("warn"),
        "DELETED_LINES_COLOR": R("error"), "TEARLINE_COLOR": R("rule", 0.2),
        "METHOD_SEPARATORS_COLOR": R("rule", 0.2),
    }.items():
        set_colour(name, val)

    italic, plain = "2", "0"
    syntax = {
        "TEXT": (R("fg"), R("bg"), None),
        "DEFAULT_KEYWORD": ("syn-keyword", None, plain), "DEFAULT_LABEL": ("syn-keyword", None, None),
        "DEFAULT_STRING": ("syn-string", None, None),
        "DEFAULT_VALID_STRING_ESCAPE": ("syn-regex", None, None),
        "DEFAULT_INVALID_STRING_ESCAPE": ("error", None, None),
        "DEFAULT_NUMBER": ("syn-number", None, None), "DEFAULT_CONSTANT": ("syn-number", None, None),
        "DEFAULT_PREDEFINED_SYMBOL": ("syn-number", None, None),
        "DEFAULT_LINE_COMMENT": ("syn-comment", None, italic),
        "DEFAULT_BLOCK_COMMENT": ("syn-comment", None, italic),
        "DEFAULT_DOC_COMMENT": ("syn-comment", None, italic),
        "DEFAULT_DOC_COMMENT_TAG": ("syn-attr", None, None),
        "DEFAULT_DOC_MARKUP": ("syn-comment", None, None),
        "DEFAULT_FUNCTION_DECLARATION": ("syn-function", None, None),
        "DEFAULT_FUNCTION_CALL": ("syn-function", None, None),
        "DEFAULT_INSTANCE_METHOD": ("syn-function", None, None),
        "DEFAULT_STATIC_METHOD": ("syn-function", None, None),
        "DEFAULT_CLASS_NAME": ("syn-type", None, None), "DEFAULT_CLASS_REFERENCE": ("syn-type", None, None),
        "DEFAULT_INTERFACE_NAME": ("syn-type", None, None),
        "DEFAULT_IDENTIFIER": ("fg", None, None), "DEFAULT_LOCAL_VARIABLE": ("syn-variable", None, None),
        "DEFAULT_GLOBAL_VARIABLE": ("syn-variable", None, None),
        "DEFAULT_PARAMETER": ("syn-param", None, italic),
        "DEFAULT_INSTANCE_FIELD": ("syn-param", None, None), "DEFAULT_STATIC_FIELD": ("syn-param", None, None),
        "DEFAULT_METADATA": ("syn-attr", None, None), "DEFAULT_ATTRIBUTE": ("syn-attr", None, None),
        "DEFAULT_TAG": ("syn-tag", None, None), "DEFAULT_ENTITY": ("syn-regex", None, None),
        "DEFAULT_OPERATION_SIGN": ("syn-param", None, None), "DEFAULT_BRACES": ("syn-param", None, None),
        "DEFAULT_BRACKETS": ("syn-param", None, None), "DEFAULT_PARENTHS": ("syn-param", None, None),
        "DEFAULT_COMMA": ("syn-param", None, None), "DEFAULT_SEMICOLON": ("syn-param", None, None),
        "DEFAULT_DOT": ("syn-param", None, None),
        "CONSOLE_NORMAL_OUTPUT": ("term-fg", None, None), "CONSOLE_ERROR_OUTPUT": ("error", None, None),
        "CONSOLE_SYSTEM_OUTPUT": ("syn-comment", None, None), "CONSOLE_USER_INPUT": ("success", None, italic),
        "CONSOLE_BLACK_OUTPUT": ("t-black", None, None), "CONSOLE_RED_OUTPUT": ("t-red", None, None),
        "CONSOLE_GREEN_OUTPUT": ("t-green", None, None), "CONSOLE_YELLOW_OUTPUT": ("t-yellow", None, None),
        "CONSOLE_BLUE_OUTPUT": ("t-blue", None, None), "CONSOLE_MAGENTA_OUTPUT": ("t-magenta", None, None),
        "CONSOLE_CYAN_OUTPUT": ("t-cyan", None, None), "CONSOLE_GRAY_OUTPUT": ("t-white", None, None),
        "CONSOLE_DARKGRAY_OUTPUT": ("t-bright-black", None, None),
        "CONSOLE_RED_BRIGHT_OUTPUT": ("t-bright-red", None, None),
        "CONSOLE_GREEN_BRIGHT_OUTPUT": ("t-bright-green", None, None),
        "CONSOLE_YELLOW_BRIGHT_OUTPUT": ("t-bright-yellow", None, None),
        "CONSOLE_BLUE_BRIGHT_OUTPUT": ("t-bright-blue", None, None),
        "CONSOLE_MAGENTA_BRIGHT_OUTPUT": ("t-bright-magenta", None, None),
        "CONSOLE_CYAN_BRIGHT_OUTPUT": ("t-bright-cyan", None, None),
        "CONSOLE_WHITE_OUTPUT": ("t-bright-white", None, None),
    }
    for name, (fg, bgc, font) in syntax.items():
        fg_hex = fg if fg and re.fullmatch(r"[0-9a-f]{6}", fg) else (R(fg) if fg else None)
        set_attr(name, fg_hex, bgc, font)
    for name, a in (("SEARCH_RESULT_ATTRIBUTES", 0.35), ("TEXT_SEARCH_RESULT_ATTRIBUTES", 0.45),
                    ("WRITE_SEARCH_RESULT_ATTRIBUTES", 0.35)):
        set_attr(name, bg_=R("find", a))
    set_attr("IDENTIFIER_UNDER_CARET_ATTRIBUTES", bg_=R("fg", 0.12))

    scheme = ET.Element("scheme", name=v["name"], version="142", parent_scheme=parent)
    meta = ET.SubElement(scheme, "metaInfo")
    ET.SubElement(meta, "property", name="ide").text = "idea"
    c_el = ET.SubElement(scheme, "colors")
    for k in sorted(colors):
        c_el.append(colors[k])
    a_el = ET.SubElement(scheme, "attributes")
    for k in sorted(attrs):
        a_el.append(attrs[k])
    ET.indent(scheme, space="  ")
    return ET.tostring(scheme, encoding="unicode") + "\n", len(colors), len(attrs)


def build_jetbrains(pal, refresh, required):
    up = jetbrains_upstream(refresh)
    if not up:
        msg = "no JetBrains IDE found (set JETBRAINS_IDE=/path/to/ide)"
        if required:
            sys.exit(f"error: {msg}")
        print(f"  skipping JetBrains ({msg})")
        return
    variants = {k: v for k, v in json.loads((JETBRAINS_SRC / "variants.json").read_text()).items()
                if not k.startswith("_")}
    if DIST_JETBRAINS.exists():
        shutil.rmtree(DIST_JETBRAINS)
    out = DIST_JETBRAINS / "plugin"
    (out / "themes").mkdir(parents=True)
    (out / "META-INF").mkdir()

    providers = []
    for name, v in variants.items():
        v = {**v, "name": name}
        where = f"jetbrains/variants.json [{v['id']}]"
        roles = load_roles(v["roles"], v.get("role_overrides"))
        ui_ramps = Ramps(v["ramps"]["ui"], pal, where)
        syn_ramps = Ramps(v["ramps"]["syntax"], pal, where)
        theme = jb_theme(v, pal, up, ui_ramps)
        (out / "themes" / f"{v['id']}.theme.json").write_text(json.dumps(theme, indent=2) + "\n")
        scheme, nc, na = jb_scheme(v, pal, up, syn_ramps, roles)
        (out / "themes" / f"{v['id']}.xml").write_text(scheme)
        providers.append(f'    <themeProvider id="{v["id"]}" path="/themes/{v["id"]}.theme.json" targetUi="islands"/>')
        print(f"    {name}: {len(theme['colors'])} colours, scheme {nc} colours / {na} attributes")

    upstream = (up / "VERSION").read_text().strip()
    plugin = (JETBRAINS_SRC / "plugin.xml").read_text()
    plugin = plugin.replace("{{themes}}", "\n".join(providers)).replace("{{upstream}}", escape_xml(upstream))
    (out / "META-INF" / "plugin.xml").write_text(plugin)
    version = re.search(r"<version>([^<]+)</version>", plugin)[1]
    jar = DIST_JETBRAINS / f"cynosure-theme-{version}.jar"
    with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out).as_posix())
    print(f"  {jar.relative_to(ROOT)}  (from {upstream})")


def escape_xml(text):
    from xml.sax.saxutils import escape
    return escape(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true",
                    help="re-extract the upstream Shell stylesheet (after a GNOME upgrade)")
    ap.add_argument("--only", choices=["gtk", "shell", "sway", "icons", "vscode", "firefox", "jetbrains"], action="append",
                    help="build only these targets (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every upstream colour and what it was mapped to")
    args = ap.parse_args()
    targets = set(args.only or ["gtk", "shell", "sway", "icons", "vscode", "firefox", "jetbrains"])

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
    if "jetbrains" in targets:
        build_jetbrains(pal, args.refresh, required=bool(args.only))
    print("Done -> dist/")


if __name__ == "__main__":
    main()
