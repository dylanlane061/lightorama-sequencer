#!/usr/bin/env python3
"""selftest.py: check this machine can run the skill, then build a tiny show end to end.

    python selftest.py            # works in a temp folder, prints PASS/FAIL per step

Run it first in any new environment (ChatGPT, Codex, Claude Code, a fresh PC). It needs no
LOR files or songs: it makes a small fake layout and a 20-second click-track song.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
results = []


def step(name, fn, required=True):
    try:
        note = fn() or ""
        results.append((name, "PASS", note))
    except Exception as exc:  # noqa: BLE001
        results.append((name, "FAIL" if required else "MISSING (optional)", f"{exc}".splitlines()[0][:160]))
        if required and "--verbose" in sys.argv:
            traceback.print_exc()


def run(*args, cwd):
    out = subprocess.run([PY, *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError((out.stderr or out.stdout).strip().splitlines()[-1] if (out.stderr or out.stdout) else "failed")
    return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""


def main():
    print(f"Python {sys.version.split()[0]} at {PY}")
    for mod in ("lxml", "PIL", "numpy"):
        step(f"import {mod}", lambda m=mod: getattr(importlib.import_module(m), "__version__", "ok"))
    step("ffmpeg on PATH (mp3 songs)", lambda: shutil.which("ffmpeg") or (_ for _ in ()).throw(RuntimeError("not found: use WAV songs or install ffmpeg")), required=False)
    step("playwright (viewer snapshots)", lambda: importlib.import_module("playwright") and "ok", required=False)

    work = Path(tempfile.mkdtemp(prefix="lor_selftest_"))
    import numpy as np
    import wave

    def make_song():
        sr, bpm, dur = 22050, 120, 20.0
        t = np.arange(int(sr * dur)) / sr
        y = np.zeros_like(t)
        for k in range(int(dur * bpm / 60)):
            i = int((0.25 + k * 60 / bpm) * sr)
            n = min(len(y) - i, int(0.15 * sr))
            if n <= 0:
                break
            tt = np.arange(n) / sr
            amp = (0.9 if k % 4 == 0 else 0.5) * (1.6 if t[i] > 10 else 0.6)
            y[i:i + n] += amp * np.sin(2 * np.pi * (60 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 14)
        y = y / np.abs(y).max() * 0.8
        with wave.open(str(work / "song.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((y * 32767).astype(np.int16).tobytes())
        return "20 s click track"

    step("make test song", make_song)
    step("make test layout", lambda: run(HERE / "make_test_fixture.py", "layout_source.loredit", cwd=work))
    step("lor_new from-preview", lambda: run(HERE / "lor_new.py", "from-preview", "layout_source.loredit",
                                             "--audio", "song.wav", "--out", "base.loredit", "--force", cwd=work))
    step("lor_audio analyze + grids", lambda: run(HERE / "lor_audio.py", "analyze", "song.wav", "--out", "song.analysis.json",
                                                  "--write-grids", "base.loredit", cwd=work))
    step("lor_plan draft", lambda: run(HERE / "lor_plan.py", "draft", "base.loredit", "--analysis", "song.analysis.json",
                                       "--out", "plan.json", cwd=work))
    step("lor_plan compile", lambda: run(HERE / "lor_plan.py", "compile", "plan.json", "--base", "base.loredit",
                                         "--out", "show.loredit", "--force", cwd=work))
    step("lor_helper validate", lambda: run(HERE / "lor_helper.py", "validate", "show.loredit", cwd=work))
    step("lor_show build (HTML viewer)", lambda: run(HERE / "lor_show.py", "build", "show.loredit", "--audio", "song.wav",
                                                    "--out", "show.html", cwd=work))
    step("lor_show storyboard (no browser)", lambda: run(HERE / "lor_show.py", "storyboard", "show.loredit",
                                                         "--out", "storyboard.png", cwd=work))
    if any(r[0].startswith("playwright") and r[1] == "PASS" for r in results):
        step("lor_show snapshots", lambda: run(HERE / "lor_show.py", "snapshots", "show.html", "--times", "5,15",
                                               "--out", "frames", cwd=work), required=False)

    print()
    for name, status, note in results:
        print(f"  {status:<20} {name:<34} {note}")
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"\n{'ALL REQUIRED STEPS PASSED' if not failed else f'{len(failed)} REQUIRED STEP(S) FAILED'}  (work folder: {work})")
    if failed:
        print("Fix: pip install lxml pillow numpy   (then run this again; add --verbose for details)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
