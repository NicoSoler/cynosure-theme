#!/usr/bin/env bash
# Install / uninstall Cynosure for the current user.
#
#   ./install.sh theme         GTK 4, GNOME Shell and icon themes, installed as regular
#                              themes: nothing is switched on. Pick them in Refine
#                              (GTK 3/4 Theme, Icons) or the User Themes extension (Shell).
#   ./install.sh sway          theme + Sway, Waybar, mako, fuzzel, foot, swaylock, swaynag
#   ./install.sh vscode        VS Code colour themes (Cynosure Breach / Parchment);
#                              pick them with Ctrl+K Ctrl+T
#   ./install.sh firefox       Firefox userChrome/userContent styles (restart Firefox);
#                              profile: newest one, or FIREFOX_PROFILE=/path/to/profile
#   ./install.sh fonts         download Rajdhani + Share Tech Mono (OFL)
#   ./install.sh uninstall theme|sway|vscode|firefox|all
#
# Targets can be combined:  ./install.sh theme fonts
#
# Theme:  ~/.local/share/themes/Cynosure and ~/.local/share/icons/Cynosure.
#         libadwaita apps ignore the GTK theme setting, so a small user service
#         (cynosure-gtk-sync) links ~/.config/gtk-4.0/gtk.css to Cynosure while
#         "Cynosure" is the selected GTK theme, and unlinks it otherwise.
#         Refine is a Flatpak that can't see ~/.local/share/themes, so it gets a
#         read-only override for that folder. Restart apps after switching.
# Sway:   configs are copied into ~/.config/<app>/. An existing config that this
#         script didn't install is moved to <dir>.bak-<timestamp> first.
#         ~/.config/sway/config.d/ is yours (monitors, local.conf): never overwritten,
#         kept on uninstall, carried over when an old config is backed up.
set -euo pipefail

NAME=Cynosure
ROOT="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
THEME_DIR="$DATA/themes/$NAME"
ICON_DIR="$DATA/icons/$NAME"
LEGACY_THEME_DIR="$HOME/.themes/$NAME"          # where older versions installed
LIBEXEC="$DATA/cynosure"
UNIT=cynosure-gtk-sync.service
UNIT_DIR="$CONFIG/systemd/user"
GTK4_CSS="$CONFIG/gtk-4.0/gtk.css"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/cynosure"
FONT_DIR="$DATA/fonts/cynosure"
IFACE_SCHEMA=org.gnome.desktop.interface
USER_THEME_SCHEMA=org.gnome.shell.extensions.user-theme
REFINE=page.tesk.Refine
REFINE_FS=xdg-data/themes:ro
SWAY_APPS=(sway waybar mako fuzzel foot swaylock swaynag)
SWAY_DEPS=(sway waybar mako fuzzel foot swaylock swayidle swaybg swaynag grim slurp wl-copy wpctl playerctl lxpolkit nm-applet notify-send)
MARKER=.cynosure-managed
STAMP="$(date +%Y%m%d%H%M%S)"

FONTS=(
  "https://github.com/google/fonts/raw/main/ofl/rajdhani/Rajdhani-Regular.ttf"
  "https://github.com/google/fonts/raw/main/ofl/rajdhani/Rajdhani-Medium.ttf"
  "https://github.com/google/fonts/raw/main/ofl/rajdhani/Rajdhani-SemiBold.ttf"
  "https://github.com/google/fonts/raw/main/ofl/rajdhani/Rajdhani-Bold.ttf"
  "https://github.com/google/fonts/raw/main/ofl/sharetechmono/ShareTechMono-Regular.ttf"
)

say()  { printf '\033[1;33m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*"; }
usage() { sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 1; }

# (no `grep -q` after a pipe: with pipefail, grep exiting early makes the producer
# die of SIGPIPE and the whole check "fail" even though it matched.)
has_user_theme() { gsettings list-schemas 2>/dev/null | grep -x "$USER_THEME_SCHEMA" >/dev/null; }
has_refine() { command -v flatpak >/dev/null && flatpak info "$REFINE" >/dev/null 2>&1; }
setting() { gsettings get "$1" "$2" | tr -d "'"; }

# --- fonts -------------------------------------------------------------------
install_fonts() {
  say "Downloading fonts to $FONT_DIR"
  mkdir -p "$FONT_DIR"
  for url in "${FONTS[@]}"; do
    curl -fsSL -o "$FONT_DIR/$(basename "$url")" "$url"
  done
  fc-cache -f "$FONT_DIR" >/dev/null
}

check_fonts() {
  fc-list -q 'Rajdhani' ||
    warn "Rajdhani isn't installed; text will use a fallback font. Run: ./install.sh fonts"
}

# --- Theme (GTK 4 + Shell + icons) -------------------------------------------
install_theme() {
  say "Installing themes to $THEME_DIR and $ICON_DIR"
  rm -rf "$THEME_DIR" "$ICON_DIR"
  mkdir -p "$(dirname "$THEME_DIR")" "$(dirname "$ICON_DIR")"
  cp -r "$ROOT/dist/$NAME" "$THEME_DIR"
  cp -r "$ROOT/dist/icons/$NAME" "$ICON_DIR"

  # Older versions installed to ~/.themes and force-linked gtk.css.
  if [[ -d "$LEGACY_THEME_DIR" ]]; then
    rm -rf "$LEGACY_THEME_DIR"
    say "Removed old copy in $LEGACY_THEME_DIR"
  fi

  say "Installing the GTK theme watcher ($UNIT)"
  mkdir -p "$LIBEXEC" "$UNIT_DIR"
  install -m 755 "$ROOT/gtk/cynosure-gtk-sync" "$LIBEXEC/cynosure-gtk-sync"
  install -m 644 "$ROOT/gtk/$UNIT" "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload
  systemctl --user enable "$UNIT" >/dev/null 2>&1
  systemctl --user restart "$UNIT"     # re-syncs: picks up the new stylesheet

  if has_refine; then
    flatpak override --user --filesystem="$REFINE_FS" "$REFINE"
    say "Refine can now list themes in $DATA/themes (read-only)"
  fi

  say "Installed. Nothing was switched on:"
  say "  GTK 4 + icons:  Refine > Appearance > 'GTK 3/4 Theme' / 'Icons' > $NAME"
  say "  GNOME Shell:    Extensions > User Themes > settings > $NAME"
  say "  (or: gsettings set $IFACE_SCHEMA gtk-theme $NAME)"
}

uninstall_theme() {
  local previous
  if [[ "$(setting "$IFACE_SCHEMA" gtk-theme)" == "$NAME" ]]; then
    previous="$(cat "$STATE_DIR/previous-gtk-theme" 2>/dev/null || echo Adwaita)"
    gsettings set "$IFACE_SCHEMA" gtk-theme "$previous"
    say "GTK theme switched back to $previous"
  fi
  if [[ "$(setting "$IFACE_SCHEMA" icon-theme)" == "$NAME" ]]; then
    previous="$(cat "$STATE_DIR/previous-icon-theme" 2>/dev/null | tr -d "'" || true)"
    gsettings set "$IFACE_SCHEMA" icon-theme "${previous:-Adwaita}"
    say "Icon theme switched back to ${previous:-Adwaita}"
  fi
  if has_user_theme && [[ "$(setting "$USER_THEME_SCHEMA" name)" == "$NAME" ]]; then
    gsettings reset "$USER_THEME_SCHEMA" name
    say "Shell theme reset to default"
  fi

  # Let the watcher unlink gtk.css (and restore an own gtk.css) before stopping it.
  [[ -x "$LIBEXEC/cynosure-gtk-sync" ]] && "$LIBEXEC/cynosure-gtk-sync" --once
  systemctl --user disable --now "$UNIT" >/dev/null 2>&1 || true
  rm -f "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload
  if [[ -L "$GTK4_CSS" && "$(readlink "$GTK4_CSS")" == */"$NAME"/* ]]; then
    rm "$GTK4_CSS"
  fi

  # Drop Refine's override only if ours is the only thing in it.
  if has_refine; then
    local overrides
    overrides="$(flatpak override --user --show "$REFINE" 2>/dev/null | grep -v '^\s*$' || true)"
    if [[ "$overrides" == $'[Context]\n'"filesystems=$REFINE_FS;" ]]; then
      flatpak override --user --reset "$REFINE"
      say "Removed Refine's access to $DATA/themes"
    elif [[ "$overrides" == *"$REFINE_FS"* ]]; then
      say "Refine has other overrides; remove ours with: flatpak override --user --nofilesystem=${REFINE_FS%:ro} $REFINE"
    fi
  fi

  rm -rf "$THEME_DIR" "$ICON_DIR" "$LEGACY_THEME_DIR" "$LIBEXEC"
  say "Removed $THEME_DIR, $ICON_DIR and the watcher"
}

# --- Sway ----------------------------------------------------------------------
install_sway() {
  local app src dest
  for app in "${SWAY_APPS[@]}"; do
    src="$ROOT/dist/sway/$app"
    dest="$CONFIG/$app"
    [[ -d "$src" ]] || continue
    if [[ -e "$dest" && ! -e "$dest/$MARKER" ]]; then
      mv "$dest" "$dest.bak-$STAMP"
      say "Existing $dest backed up to $dest.bak-$STAMP"
      # sway/config.d holds per-machine settings (monitors...): carry it over.
      if [[ "$app" == sway && -d "$dest.bak-$STAMP/config.d" ]]; then
        mkdir -p "$dest"
        cp -r "$dest.bak-$STAMP/config.d" "$dest/"
      fi
    fi
    mkdir -p "$dest"
    cp -r "$src/." "$dest/"
    touch "$dest/$MARKER"
  done
  if [[ ! -e "$CONFIG/sway/config.d/local.conf" ]]; then
    cp "$CONFIG/sway/config.d/local.conf.example" "$CONFIG/sway/config.d/local.conf"
  fi
  say "Sway configs installed to $CONFIG/{$(IFS=,; echo "${SWAY_APPS[*]}")}"

  local missing=()
  for bin in "${SWAY_DEPS[@]}"; do command -v "$bin" >/dev/null || missing+=("$bin"); done
  if ((${#missing[@]})); then
    warn "Missing programs: ${missing[*]}"
    warn "On Fedora: sudo dnf install waybar mako fuzzel playerctl (others as needed)"
  fi

  # Live-reload if we're inside Sway.
  if [[ -n "${SWAYSOCK:-}" ]]; then
    swaymsg reload >/dev/null && say "Sway reloaded"
    pgrep -x mako >/dev/null && makoctl reload && say "mako reloaded"
  fi
  return 0
}

uninstall_sway() {
  local app dest
  for app in "${SWAY_APPS[@]}"; do
    dest="$CONFIG/$app"
    [[ -e "$dest/$MARKER" ]] || continue
    if [[ "$app" == sway && -d "$dest/config.d" ]]; then
      # config.d is the user's (monitors, local.conf...): keep it, remove the rest.
      find "$dest" -mindepth 1 -not -path "$dest/config.d" -not -path "$dest/config.d/*" -delete
      rm -f "$dest/config.d/local.conf.example"
    else
      rm -rf "$dest"
    fi
    say "Removed $dest"
  done
  ls -d "$CONFIG"/{sway,waybar,mako,fuzzel,foot,swaylock,swaynag}.bak-* 2>/dev/null |
    sed 's/^/   backup: /' || true
}

# --- VS Code -------------------------------------------------------------------
VSCODE_EXT=local.cynosure-theme

code_cli() {
  if command -v code >/dev/null; then code "$@"
  elif command -v flatpak >/dev/null && flatpak info com.visualstudio.code >/dev/null 2>&1; then
    flatpak run --command=code com.visualstudio.code "$@"
  else
    warn "VS Code ('code') not found"; return 1
  fi
}

install_vscode() {
  local vsix
  vsix="$(ls "$ROOT"/dist/vscode/*.vsix | head -n1)"
  code_cli --install-extension "$vsix" --force >/dev/null &&
    say "VS Code extension installed. Pick a theme: Ctrl+K Ctrl+T > Cynosure Breach / Parchment"
}

uninstall_vscode() {
  code_cli --uninstall-extension "$VSCODE_EXT" >/dev/null 2>&1 && say "VS Code extension removed" || true
}

# --- Firefox -------------------------------------------------------------------
FF_PREF='user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true); // cynosure'

firefox_profile() {
  if [[ -n "${FIREFOX_PROFILE:-}" ]]; then
    [[ -f "$FIREFOX_PROFILE/prefs.js" ]] || { warn "Not a Firefox profile: $FIREFOX_PROFILE"; return 1; }
    echo "$FIREFOX_PROFILE"; return
  fi
  # The most recently used profile (prefs.js is rewritten on every run).
  local newest
  newest="$(ls -1t "$HOME"/.mozilla/firefox/*/prefs.js "$CONFIG"/mozilla/firefox/*/prefs.js 2>/dev/null | head -n1)"
  [[ -n "$newest" ]] || { warn "No Firefox profile found"; return 1; }
  dirname "$newest"
}

# Make sure <file> starts with `@import "cynosure/<name>";` (imports must come first).
ff_add_import() {
  local file="$1" line="@import \"cynosure/$(basename "$1")\";"
  if [[ -f "$file" ]] && grep -Fx "$line" "$file" >/dev/null; then return; fi
  {
    echo "$line"
    if [[ -f "$file" ]]; then cat "$file"; fi
  } > "$file.tmp"
  mv "$file.tmp" "$file"
}

ff_remove_import() {
  local file="$1" line="@import \"cynosure/$(basename "$1")\";"
  [[ -f "$file" ]] || return 0
  grep -Fvx "$line" "$file" > "$file.tmp" || true
  mv "$file.tmp" "$file"
  [[ -s "$file" ]] || rm "$file"          # nothing else in it: it was ours
}

install_firefox() {
  local profile chrome
  profile="$(firefox_profile)" || return 0
  chrome="$profile/chrome"
  say "Installing Firefox styles to $chrome/cynosure"
  rm -rf "$chrome/cynosure"
  mkdir -p "$chrome/cynosure"
  cp "$ROOT"/dist/firefox/*.css "$chrome/cynosure/"
  ff_add_import "$chrome/userChrome.css"
  ff_add_import "$chrome/userContent.css"
  # Firefox only reads chrome/*.css with this pref on. Skip if it already is.
  local pref='toolkit.legacyUserProfileCustomizations.stylesheets", true'
  # (one grep per file: grep exits 2 if *any* file is unreadable, match or not)
  if grep -F "$pref" "$profile/prefs.js" >/dev/null 2>&1 ||
     { [[ -f "$profile/user.js" ]] && grep -F "$pref" "$profile/user.js" >/dev/null 2>&1; }; then
    :
  elif [[ -L "$profile/user.js" && ! -e "$profile/user.js" ]]; then
    warn "$profile/user.js is a broken link ($(readlink "$profile/user.js")); not touching it."
    warn "Enable toolkit.legacyUserProfileCustomizations.stylesheets in about:config instead."
  else
    echo "$FF_PREF" >> "$profile/user.js"
  fi
  pgrep -x firefox >/dev/null && say "Restart Firefox to apply (userChrome.css is read at start-up)."
  return 0
}

uninstall_firefox() {
  local profile chrome
  profile="$(firefox_profile)" || return 0
  chrome="$profile/chrome"
  ff_remove_import "$chrome/userChrome.css"
  ff_remove_import "$chrome/userContent.css"
  rm -rf "$chrome/cynosure"
  rmdir "$chrome" 2>/dev/null || true
  if [[ -f "$profile/user.js" && ! -L "$profile/user.js" ]]; then
    grep -Fvx "$FF_PREF" "$profile/user.js" > "$profile/user.js.tmp" || true
    mv "$profile/user.js.tmp" "$profile/user.js"
    [[ -s "$profile/user.js" ]] || rm "$profile/user.js"
  fi
  say "Removed Cynosure from $profile (restart Firefox)"
}

# --- main ----------------------------------------------------------------------
[[ $# -gt 0 ]] || usage

if [[ "$1" == uninstall ]]; then
  case "${2:-}" in
    theme) uninstall_theme ;;
    sway)   uninstall_sway ;;
    vscode)  uninstall_vscode ;;
    firefox) uninstall_firefox ;;
    all)     uninstall_sway; uninstall_vscode; uninstall_firefox; uninstall_theme ;;
    *)     usage ;;
  esac
  say "Done."
  exit 0
fi

want_theme=0 want_sway=0 want_fonts=0 want_vscode=0 want_firefox=0
for target in "$@"; do
  case "$target" in
    theme) want_theme=1 ;;
    sway)  want_theme=1; want_sway=1 ;;
    fonts) want_fonts=1 ;;
    vscode) want_vscode=1 ;;
    firefox) want_firefox=1 ;;
    gtk|gnome|icons)
      warn "'$target' was replaced by 'theme' (installs everything, enables nothing)."
      want_theme=1 ;;
    *)     usage ;;
  esac
done

((want_fonts)) && install_fonts
((want_theme || want_vscode || want_firefox)) && "$ROOT/build.py"
if ((want_theme)); then
  install_theme
  check_fonts
fi
((want_sway)) && install_sway
((want_vscode)) && install_vscode
((want_firefox)) && install_firefox

if ((want_theme)); then
  say "Done. Restart GTK apps (e.g. nautilus -q) to pick up the changes."
else
  say "Done."
fi
