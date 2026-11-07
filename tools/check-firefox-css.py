#!/usr/bin/env python3
"""Check the Firefox styles against the installed Firefox's own CSS.

Firefox renames its internal CSS variables and selectors from time to time
(e.g. the "Nova" redesign turned --toolbox-bgcolor into
--toolbox-background-color). This extracts Firefox's built-in stylesheets
from its omni.ja archives and lists every variable / id / class used in
firefox/userChrome.css that Firefox no longer knows. Run it after a Firefox
update when something stops being styled.

    ./tools/check-firefox-css.py [/usr/lib64/firefox]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OURS = ROOT / "firefox" / "userChrome.css"
FIREFOX = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/lib64/firefox")


def firefox_css():
    """All .css from omni.ja + browser/omni.ja, concatenated."""
    chunks = []
    with tempfile.TemporaryDirectory() as tmp:
        for jar in (FIREFOX / "omni.ja", FIREFOX / "browser" / "omni.ja"):
            if not jar.exists():
                sys.exit(f"not found: {jar} (pass the Firefox directory as an argument)")
            out = Path(tmp) / jar.parent.name
            out.mkdir()
            # omni.ja is an "optimized" jar: Python's zipfile rejects it, unzip copes.
            subprocess.run(["unzip", "-qq", "-o", str(jar), "*.css", "-d", str(out)],
                           check=False, stderr=subprocess.DEVNULL)
            chunks += [f.read_text(errors="ignore") for f in out.rglob("*.css")]
    if not chunks:
        sys.exit("could not extract any CSS (is `unzip` installed?)")
    return "\n".join(chunks)


def main():
    ff = firefox_css()
    ours = re.sub(r"/\*.*?\*/", "", OURS.read_text(), flags=re.S)

    variables = sorted(set(re.findall(r"(--(?!cyn-)[\w-]+)\s*:", ours)))
    selectors = sorted(set(re.findall(r"[#.]([a-zA-Z][\w-]+)", re.sub(r"\{[^{}]*\}", "{}", ours))))
    gone_vars = [v for v in variables if not re.search(re.escape(v) + r"(?![\w-])", ff)]
    gone_sels = [s for s in selectors if not re.search(r"[#.]" + re.escape(s) + r"(?![\w-])", ff)]

    print(f"{len(variables)} Firefox variables, {len(selectors)} ids/classes in {OURS.relative_to(ROOT)}")
    print("variables Firefox doesn't use:", ", ".join(gone_vars) or "none")
    print("ids/classes Firefox doesn't use:", ", ".join(gone_sels) or "none")
    print("(the 'older names' block is expected to show up here on new Firefox versions)")


if __name__ == "__main__":
    main()
