#!/usr/bin/env python3
"""build_app.py: make the standalone Papa Russ's app from the viewer template.

The viewer template is also the app: with no show embedded it opens on a start screen
and reads .loredit / .lorprev files right in the browser. This copies it with the
title filled in.

    python build_app.py                    # writes docs/app/index.html (the hosted app)
    python build_app.py --out papa-russ.html
    python build_app.py --check            # exit 1 if docs/app/index.html is out of date
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "viewer_template.html"
HOSTED = ROOT / "docs" / "app" / "index.html"


def render() -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("<title>__TITLE__ · Papa Russ's preview</title>", "<title>Papa Russ's</title>", 1)
    return html.replace("__TITLE__", "Papa Russ's")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=HOSTED)
    p.add_argument("--check", action="store_true")
    a = p.parse_args(argv)
    if a.check:
        if not HOSTED.exists():
            print("no docs/app/index.html here (the release zip leaves docs out): nothing to check")
            return 0
        if HOSTED.read_text(encoding="utf-8") != render():
            print("docs/app/index.html is out of date: run python scripts/build_app.py")
            return 1
        print("docs/app/index.html matches the viewer template")
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render(), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
