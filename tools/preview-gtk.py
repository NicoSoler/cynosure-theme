#!/usr/bin/env python3
"""Render a sample libadwaita window with the built Cynosure GTK stylesheet.

Writes build/preview/gtk-light.png and build/preview/gtk-dark.png. The
stylesheet is loaded straight from dist/, so nothing needs to be installed.
A window flashes on screen briefly while it is captured.

    ./build.py --only gtk && ./tools/preview-gtk.py
"""
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "dist/Cynosure/gtk-4.0/libadwaita.css"
OUT = ROOT / "build/preview"


def build_window(app):
    win = Adw.ApplicationWindow(application=app, title="Sector 3 Gate")
    win.set_default_size(820, 780)

    header = Adw.HeaderBar()
    header.pack_start(Gtk.Button(icon_name="go-previous-symbolic"))
    toggle = Gtk.ToggleButton(label="Dataterms", active=True)
    header.pack_start(toggle)
    header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic"))

    view = Adw.ToolbarView()
    view.add_top_bar(header)

    page = Adw.PreferencesPage()
    console = Adw.PreferencesGroup(title="System console",
                                   description="Remote control via dataterminals")
    for name, online in (("Alpha", True), ("Bravo", True), ("Sierra", False)):
        row = Adw.SwitchRow(title=name, subtitle="Online" if online else "Offline",
                            active=online)
        console.add(row)
    victor = Adw.ActionRow(title="Victor", subtitle="Error", activatable=True)
    victor.add_suffix(Gtk.Button(label="Reboot", valign=Gtk.Align.CENTER,
                                 css_classes=["destructive-action"]))
    console.add(victor)
    page.add(console)

    gate = Adw.PreferencesGroup(title="Gate status")
    gate.add(Adw.EntryRow(title="Daemon code sequence", text="BD 55 1C E9"))
    combo = Adw.ComboRow(title="Sector", model=Gtk.StringList.new(["Sector 1", "Sector 3"]))
    gate.add(combo)
    page.add(gate)

    controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=6, margin_bottom=18)
    buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
    buttons.append(Gtk.Button(label="Detailed information"))
    buttons.append(Gtk.Button(label="Authorize", css_classes=["suggested-action"]))
    buttons.append(Gtk.Button(label="Gate closed", css_classes=["flat"]))
    controls.append(buttons)

    bar = Gtk.ProgressBar(fraction=0.6, show_text=True, text="AUTHORIZING 60%")
    controls.append(bar)
    controls.append(Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1))

    checks = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
    checks.append(Gtk.CheckButton(label="Breach protocol", active=True))
    radio_a = Gtk.CheckButton(label="Course 0-360", active=True)
    radio_b = Gtk.CheckButton(label="Warp", group=radio_a)
    checks.append(radio_a)
    checks.append(radio_b)
    controls.append(checks)

    extra = Adw.PreferencesGroup()
    extra.add(controls)
    page.add(extra)

    view.set_content(page)
    win.set_content(view)
    return win


def capture(win, path):
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(win).snapshot(snap, w, h)
    node = snap.to_node()
    tex = win.get_native().get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
    tex.save_to_png(str(path))
    print(f"wrote {path.relative_to(ROOT)}")


def main():
    if not CSS.exists():
        sys.exit("build first: ./build.py --only gtk")
    OUT.mkdir(parents=True, exist_ok=True)
    app = Adw.Application(application_id="ar.cynosure.Preview")

    def on_activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS))
        # A standalone provider doesn't follow the colour scheme on its own
        # (GTK does this for the real ~/.config/gtk-4.0/gtk.css), so bind it.
        Gtk.Settings.get_default().bind_property(
            "gtk-interface-color-scheme", provider, "prefers-color-scheme",
            gi.repository.GObject.BindingFlags.SYNC_CREATE)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        sm = Adw.StyleManager.get_default()
        win = build_window(app)
        win.present()
        schemes = [("light", Adw.ColorScheme.FORCE_LIGHT), ("dark", Adw.ColorScheme.FORCE_DARK)]

        def step():
            if not schemes:
                app.quit()
                return False
            name, scheme = schemes.pop(0)
            sm.set_color_scheme(scheme)
            GLib.timeout_add(700, lambda: (capture(win, OUT / f"gtk-{name}.png"), step())[0] and False)
            return False

        GLib.timeout_add(600, step)

    app.connect("activate", on_activate)
    app.run([])


if __name__ == "__main__":
    main()
