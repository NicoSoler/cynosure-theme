# Cynosure

A desktop theme modelled on the Cynosure terminals from Cyberpunk 2077's
*Somewhat Damaged* (screenshots in [reference/](reference/)). Targets:

| target          | what                                                         |
|-----------------|--------------------------------------------------------------|
| **GTK 4**       | libadwaita apps, light (parchment) + dark (breach) variants   |
| **GNOME Shell** | parchment menus/quick settings, navy top bar (GNOME 50)      |
| **Sway**        | WM + Waybar, mako, fuzzel, foot, swaylock, swaynag, wallpaper |
| **Icons**       | olive "datafile" folder icons; everything else from Adwaita   |
| **VS Code**     | Cynosure Breach (dark) + Cynosure Parchment (light)          |
| **Firefox**     | tabs, toolbars, menus, New Tab page (userChrome/userContent) |
| **JetBrains**   | Cynosure Breach / Parchment UI + editor schemes, all IDEs     |

The look:

- **Light**: the parchment "CONTROL PANEL" terminals. Aged paper, navy header
  strips, hard ink-ruled boxes, red error rows, striped progress bars.
- **Dark**: the breach-protocol / messages screens. Near-black navy, cream
  rules, cream header strips with dark text, khaki selection.
- Square corners everywhere.

## Install

```sh
./install.sh theme            # GTK 4 + Shell + icon themes; nothing gets switched on
./install.sh sway             # theme + the Sway setup
./install.sh vscode           # VS Code colour themes (select with Ctrl+K Ctrl+T)
./install.sh firefox          # Firefox styles (restart Firefox; FIREFOX_PROFILE=... to pick a profile)
./install.sh jetbrains        # JetBrains themes into every installed IDE (restart, then pick the theme)
./install.sh theme fonts      # ...plus Rajdhani & Share Tech Mono (OFL) from Google Fonts
./install.sh uninstall theme  # or sway | vscode | firefox | jetbrains | all
```

`theme` installs Cynosure as regular themes, so you switch it on and off yourself:

| part          | where to toggle                                                  |
|---------------|------------------------------------------------------------------|
| GTK 4 apps    | Refine → Appearance → **GTK 3/4 Theme** → Cynosure               |
| Icons         | Refine → Appearance → **Icons** → Cynosure                       |
| GNOME Shell   | Extensions → User Themes → settings → Cynosure                   |
| from a shell  | `gsettings set org.gnome.desktop.interface gtk-theme Cynosure`   |

Restart apps after switching (`nautilus -q` for Files).

The Sway setup expects `sudo dnf install waybar mako fuzzel playerctl`. The
installer lists anything missing.

- **Where**: `~/.local/share/themes/Cynosure` and `~/.local/share/icons/Cynosure`.
  Older versions used `~/.themes`; the installer moves away from it.
- **GTK 4 toggle**: libadwaita apps ignore the GTK theme setting; their only hook is
  `~/.config/gtk-4.0/gtk.css`. A user service, `cynosure-gtk-sync`, watches the
  setting. While it says `Cynosure` it links that file to the theme's
  `gtk-4.0/libadwaita.css`; otherwise it removes the link. A `gtk.css` of your own
  is set aside and put back. Works under GNOME and Sway alike.
- **GTK 3 apps** have no full Cynosure style yet. So that picking Cynosure doesn't
  drop them to old Adwaita, the watcher writes the theme's `gtk-3.0/gtk.css` as
  **adw-gtk3** (or adw-gtk3-dark, following the light/dark setting) plus a small
  Cynosure layer, `gtk/gtk-3.0/cynosure-{light,dark}.css`. For now the layer only
  restyles tooltips. That matters for Firefox too: its toolbar tooltips are
  native anonymous content that `userChrome.css` can't reach, so they're drawn
  with the GTK 3 tooltip style.
- **Refine** is a Flatpak and can't see `~/.local/share/themes` on its own. The
  installer adds a read-only override (`flatpak override --user
  --filesystem=xdg-data/themes:ro page.tesk.Refine`). A system-wide copy in
  `/usr/share/themes` wouldn't help: the sandbox doesn't expose that either.
  Icons need nothing; Refine already sees `~/.local/share/icons`.
- **Shell**: needs the *User Themes* extension.
- **Uninstall** switches anything set to Cynosure back to what it was before,
  then removes the service, the override and the files.
- **Sway**: configs are copied to `~/.config/{sway,waybar,mako,fuzzel,foot,swaylock,swaynag}`.
  Existing configs that the installer didn't create are moved to `*.bak-<timestamp>`.
  Machine-specific settings go in `~/.config/sway/config.d/*.conf` (e.g. `outputs.conf`
  for monitors, `local.conf` for the rest). The installer never overwrites that folder,
  keeps it on uninstall, and carries it over when it backs up an old config.
  Check output names with `swaymsg -t get_outputs`. Prefer the "make model serial"
  identifiers over `DP-n`, which can change between cables and boots.

### Sway keys

`Super` is the modifier; the rest are the Sway defaults.

| keys                    | action                                       |
|-------------------------|----------------------------------------------|
| `Super+Return`          | foot terminal                                |
| `Super+d`               | fuzzel launcher (or click **CYNOSURE** in the bar) |
| `Super+Shift+q`         | close window                                 |
| `Super+h/j/k/l`, arrows | focus; add `Shift` to move                   |
| `Super+1…0`             | workspaces; add `Shift` to move window       |
| `Super+b` / `Super+v`   | split horizontal / vertical                  |
| `Super+s/w/e`           | stacking / tabbed / toggle split             |
| `Super+f`               | fullscreen                                   |
| `Super+Shift+space`     | toggle floating                              |
| `Super+r`               | resize mode                                  |
| `Super+Shift+t`         | toggle GTK apps between parchment and breach |
| `Print`, `Shift+Print` / `Super+Shift+s` | screenshot screen / area (saved + clipboard) |
| `Super+Escape`          | lock                                         |
| `Super+Shift+c`         | reload config                                |
| `Super+Shift+e`         | exit prompt                                  |

## Layout

```
common/
  _palette.scss        all colours (single source of truth)
  editor-roles.json    syntax / terminal roles shared by VS Code and JetBrains
  _fonts.scss          font stacks
gtk/
  gtk.scss             libadwaita tokens + widget rules -> gtk-4.0/libadwaita.css
  cynosure-gtk-sync    watcher: links ~/.config/gtk-4.0/gtk.css while Cynosure is selected
  cynosure-gtk-sync.service   systemd user unit for it
gnome-shell/
  gnome-shell.scss     Shell overrides (on top of recoloured upstream CSS)
sway/                  mirrors ~/.config; {{colour}} placeholders filled at build
  sway/config, sway/wallpaper{,-portrait}.svg, sway/scripts/, sway/config.d/
  waybar/  mako/  fuzzel/  foot/  swaylock/  swaynag/
icons/
  folder.svg           folder template (slanted datafile, palette placeholders)
  glyphs/*.svg         symbols printed on the folder face (32x32 box)
  manifest.json        icon name -> glyph / label colour / face colours; aliases
vscode/
  theme.jsonc          colour theme template, written in roles (bg, strip-bg, syn-keyword...)
  variants.json        role -> palette colour, one entry per theme (Breach, Parchment)
  package.json         extension metadata; build.py adds the themes and packs a .vsix
jetbrains/
  variants.json        per theme: colour ramps, pinned Islands tokens, UI keys
  plugin.xml           plugin descriptor (theme entries filled in by build.py)
firefox/
  userChrome.css       browser frame: tabs, toolbars, URL bar, menus, panels
  userContent.css      New Tab / Home / blank pages only (websites untouched)
build.py               builds dist/Cynosure/ (GTK + Shell), dist/sway/, dist/icons/, dist/vscode/, dist/firefox/
install.sh
tools/
  check-gtk-css.py     parse the built gtk.css with GTK, report errors
  preview-gtk.py       render a sample window -> build/preview/gtk-{light,dark}.png
  preview-icons.py     icon contact sheet, dark + parchment -> build/preview/icons.png
  check-firefox-css.py list Firefox variables/selectors we use that Firefox dropped
  preview-jetbrains.py mock IDE window from the built themes -> build/preview/jetbrains.png
reference/             screenshots
```

### Palette placeholders (Sway side)

Every file under `sway/` is a template. Each config format wants colours in
a different shape:

| placeholder          | output        | used by                 |
|----------------------|---------------|-------------------------|
| `{{cream}}`          | `#e3d8ab`     | sway, waybar, mako, SVG |
| `{{cream\|bare}}`    | `e3d8ab`      | foot, swaylock, swaynag |
| `{{cream\|bare\|ff}}`| `e3d8abff`    | fuzzel                  |
| `{{cream\|66}}`      | `#e3d8ab66`   | anything with alpha     |

An unknown colour name fails the build with the file and line.

### How the GTK side works

`gtk/gtk.scss` sets libadwaita's CSS variables (`--window-bg-color`, `--accent-bg-color`, …)
once per colour scheme, plus a few of our own:

| token               | light          | dark          | used for                  |
|---------------------|----------------|---------------|---------------------------|
| `--cyn-strip-bg/fg` | navy / cream   | cream / void  | header bars, tooltips     |
| `--cyn-rule`        | ink            | cream         | box outlines              |
| `--cyn-rule-soft`   | ink 40%        | cream 30%     | dividers                  |
| `--cyn-select-bg/fg`| navy / paper   | khaki / cream | selected rows, menu hover |

Widget rules only reference variables, so one set of rules serves both schemes.
The stylesheet loads at user priority, above libadwaita, so plain selectors win
regardless of specificity. Keep new rules scoped.

### How the Shell side works

`build.py` extracts GNOME's own **light** stylesheet from the installed
`gnome-shell-theme.gresource` (cached in `build/upstream/`), recolours it (greys
by luminance onto an ink → paper ramp, reds/oranges onto red/amber, system
accent onto navy; `-v` prints every mapping), flattens every `border-radius`,
then appends `gnome-shell/gnome-shell.scss`. After a GNOME upgrade:
`./build.py --refresh && ./install.sh theme`. On machines without GNOME Shell
this step is skipped.

### How the icons work

The folders copy the slanted olive datafile icons that frame the terminal
screens: a face with two tabs, a side edge and a filing label. `icons/folder.svg`
is drawn upright and skewed 20°. `build.py` renders one SVG per entry in
`icons/manifest.json`, filling palette colours plus per-icon values:

```json
"user-trash": { "glyph": "trash", "label": "red" }
```

- **New folder type**: add `icons/glyphs/<name>.svg` (paths in a 32×32 box; strokes
  inherit the ink colour, use `fill="currentColor"` for solid parts) and a manifest entry.
- **Other icon names** for an existing design go under `aliases`.
- Only folders/places are drawn. The theme inherits `Adwaita`, so symbolic icons
  (sidebars, toolbars) and file types stay stock.
- Rendered icons have comments stripped. File-type sniffing only looks for `<svg`
  near the start of the file, so a long header comment makes the SVG unrecognisable.

Preview: `./build.py --only icons && ./tools/preview-icons.py`.

### How the VS Code themes work

`vscode/theme.jsonc` is written in *roles*, not colours: the title bar is
`strip-bg`/`strip-fg` (the header strip), the activity and status bars are
`frame-*`, syntax uses `syn-*`, the terminal `t-*`. `vscode/variants.json`
maps each role to a palette colour per theme, so both variants share one
template. Alpha goes after a pipe (`{{rule|4d}}` in the template,
`"khaki|99"` in a variant). The build validates the JSON and fails on any
unknown colour, then zips a `.vsix` (no Node or `vsce` needed).

Dark syntax reuses the terminal's ANSI palette, and the light variant uses the
`print-*` colours, so the editor and foot agree. To follow the system
light/dark setting, see `vscode/README.md`.

### How the Firefox styles work

Firefox's release builds only install signed extensions, and a theme extension
can only change colours. So Cynosure uses `userChrome.css` / `userContent.css`
instead, which also gives square tabs, the outlined-tab look and the fonts:

- The tab strip is the header strip. Tabs are outlined boxes, and the selected
  tab is filled with the strip's text colour, like the pressed buttons
  elsewhere. Tab titles are uppercase; delete `text-transform` in
  `.tab-label` if that's too much.
- The URL bar is a ruled box with the address in Share Tech Mono.
- Light/dark follows Firefox's colour scheme (with the default "System theme —
  auto" it follows the desktop): Parchment or Breach.
- The installer copies the files to `<profile>/chrome/cynosure/` and adds an
  `@import` line at the top of `chrome/userChrome.css` / `userContent.css`, so a
  stylesheet of your own stays intact. It also makes sure
  `toolkit.legacyUserProfileCustomizations.stylesheets` is on (via `user.js`).
  Uninstall removes exactly those lines and files.
- Profile: the most recently used one, or `FIREFOX_PROFILE=/path ./install.sh firefox`.
- It mostly overrides Firefox's own CSS variables (`--toolbar-background-color`,
  `--tab-background-color-selected`...), plus the pre-"Nova" names for older
  versions. Firefox renames these now and then. After an update, run
  `./tools/check-firefox-css.py`: it reads the installed Firefox's built-in CSS
  (from `omni.ja`) and lists every variable or selector it no longer uses. The
  Browser Toolbox (`Ctrl+Alt+Shift+I`) shows what replaced them.
- Firefox 15x quirks handled: the URL bar is `.urlbar` and declares its radius
  variables on itself, and client-side decorations round `<body>`.

### How the JetBrains themes work

JetBrains' current UI, *Islands*, is built on semantic colour tokens
(`main-window-bg`, `tool-window-bg`, `selection-bg-active`...). As with the
Shell, the theme is generated from the installed IDE so it covers every key
of that version:

1. `build.py` finds an IDE (Toolbox apps, `/opt`, or `JETBRAINS_IDE=/path`) and
   extracts its Islands themes, their parents, the Default and Darcula editor
   schemes and every per-language scheme add-on (`XmlDarcula.xml`, ...), cached
   in `build/upstream/jetbrains/`.
2. It merges each chain and **recolours every colour** with the ramps in
   `jetbrains/variants.json`. Greys map by luminance onto the grey ramp, other
   colours onto their hue family's ramp. The UI and the editor use different
   ramps, so blue *code* stays blue while blue *UI* (Islands' accent) turns khaki.
3. It pins the important tokens to exact palette colours, applies the shared
   syntax roles (`common/editor-roles.json`, same as VS Code and foot), and
   zeroes every corner radius, so the islands become square panels.
4. It packs `cynosure-theme-<version>.jar`, a platform-only plugin, so it works in
   every JetBrains IDE.

After an IDE upgrade, run `./build.py --refresh && ./install.sh jetbrains`. To
check colours without restarting an IDE: `./tools/preview-jetbrains.py`.

## Iterating

```sh
./build.py --only gtk && ./tools/check-gtk-css.py && ./tools/preview-gtk.py
./install.sh sway          # inside Sway: reloads sway + mako automatically
sway --validate -c dist/sway/sway/config
```

Shell debugging: Looking Glass (`Alt+F2` → `lg`), pick an actor, then grep
`build/upstream/gnome-shell-light.css` for the upstream rule to out-specify.

## Known gaps / next steps

- Fonts: without `./install.sh fonts` everything falls back to Barlow / Nimbus
  Sans Narrow / sans. Rajdhani runs small, so consider ~12pt.
- GTK 3 apps (Waybar's own popups aside) keep Adwaita.
- The Shell has a single (parchment) style; User Themes loads one stylesheet.
- Sway title bars can't be uppercased; Waybar text is uppercased in the formats.
- Wallpapers: `wallpaper.svg` (16:9) is the default; `wallpaper-portrait.svg` is for
  rotated screens. Assign it per output in `config.d`, e.g.
  `output <id> bg ~/.config/sway/wallpaper-portrait.svg fill #0d171c`.
- Ideas: a parchment "SYSTEM CONSOLE" power menu, a lock screen with the
  "AUTHORIZING" panel, an animated scan line on the wallpaper.

## License note

The generated `gnome-shell.css` is derived from GNOME Shell's stylesheet
(GPL-2.0-or-later), so distributed builds inherit that licence.
