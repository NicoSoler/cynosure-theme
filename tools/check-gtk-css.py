#!/usr/bin/env python3
"""Parse dist/Cynosure/gtk-4.0/libadwaita.css with GTK's own CSS parser and report errors."""
import sys
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

path = Path(__file__).resolve().parent.parent / "dist/Cynosure/gtk-4.0/libadwaita.css"
errors = []
provider = Gtk.CssProvider()
provider.connect("parsing-error", lambda _p, section, err: errors.append(
    f"{section.get_start_location().lines + 1}:{section.get_start_location().line_chars + 1}: {err.message}"))
provider.load_from_path(str(path))
for e in errors:
    print(f"{path.name}:{e}")
print(f"{len(errors)} error(s) in {path}")
sys.exit(1 if errors else 0)
