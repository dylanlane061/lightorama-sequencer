#!/usr/bin/env python3
"""check_app_reader.py: check that the app's in-browser show reader (JavaScript, inside
assets/viewer_template.html) reads a sequence exactly like lor_show.py does.

    python check_app_reader.py show.loredit [--preview X.lorprev] [--chrome PATH]

Needs playwright (like snapshots). Prints IDENTICAL or the first differences.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lor_show  # noqa: E402


def compare(a, b, path, out):
    if len(out) > 12:
        return
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 2e-4:
            out.append(f"{path}: {a} vs {b}")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            compare(a.get(k), b.get(k), f"{path}.{k}", out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} items vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, f"{path}[{i}]", out)
        return
    if a != b:
        out.append(f"{path}: {json.dumps(a)[:60]} vs {json.dumps(b)[:60]}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sequence")
    p.add_argument("--preview")
    p.add_argument("--chrome")
    a = p.parse_args(argv)
    want = lor_show.Builder(Path(a.sequence), Path(a.preview) if a.preview else None).build()
    seq = Path(a.sequence).read_text(encoding="utf-8")
    prev = Path(a.preview).read_text(encoding="utf-8") if a.preview else None
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = lor_show._launch(pw, a.chrome)
        page = browser.new_page()
        page.goto(lor_show.TEMPLATE.resolve().as_uri() + "?snap=1")
        got = page.evaluate("async ([s, p]) => (await ShowReader.build(s, p)).show", [seq, prev])
        browser.close()
    for pic in (want.get("pictures") or {}).values():      # frames are re-encoded PNGs: compare counts only
        pic["frames"] = len(pic["frames"])
    for pic in (got.get("pictures") or {}).values():
        pic["frames"] = len(pic["frames"])
    want["meta"].pop("bgSize", None), got["meta"].pop("bgSize", None)   # Python may not know the photo size
    diffs = []
    compare(want, got, "show", diffs)
    if diffs:
        print("DIFFERENT:\n  " + "\n  ".join(diffs))
        return 1
    print(f"IDENTICAL: {len(got['props'])} props, {len(got['channels'])} channel rows, {len(got['motion'])} motion targets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
