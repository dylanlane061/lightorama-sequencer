#!/usr/bin/env python3
"""lor_audio.py: find the beats, bars, sections, energy and accents in a song (numpy only).

    python lor_audio.py analyze song.mp3 --out song.analysis.json
    python lor_audio.py analyze song.mp3 --out song.analysis.json --write-grids show.loredit
    python lor_audio.py summary song.analysis.json

Reads WAV directly; anything else (mp3, m4a, ...) is decoded with ffmpeg, which must be
on PATH (Windows: `winget install ffmpeg`).

Output (all times in seconds):
  duration, tempo (BPM), beats[], downbeats[] (bar starts, 4/4 assumed),
  sections[]: {start, end, energy 0..1, level low|mid|high, label, group A/B/C...}
              (repeats of similar material share a group letter),
  energy: {step, values[]} (loudness per step, 0..1),
  accents[]: {t, strength} (the hardest hits, good for flashes).

--write-grids adds free timing grids "Beats", "Bars" and "Sections" to a sequence (with a
backup), so they show in S6's timing bar and work with lor_helper --snap.

These are estimates. Always tell the user the tempo and section times so they can fix
them; a wrong downbeat shifts every bar-based cue.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 22050
HOP = 512
NFFT = 2048


# --------------------------------------------------------------------------- decoding
def load_audio(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path)) as w:
                sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
                raw = w.readframes(n)
            dt = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
            y = np.frombuffer(raw, dt).astype(np.float32)
            if sw == 1:
                y = y - 128
            y /= float(np.abs(y).max() or 1)
            y = y.reshape(-1, ch).mean(axis=1)
            if sr != SR:
                t_old = np.arange(len(y)) / sr
                t_new = np.arange(int(len(y) * SR / sr)) / SR
                y = np.interp(t_new, t_old, y).astype(np.float32)
            return y
        except (wave.Error, KeyError):
            pass
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("ffmpeg is needed to read this file (Windows: winget install ffmpeg), or convert it to WAV")
    out = subprocess.run([exe, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, np.float32).copy()


# --------------------------------------------------------------------------- features
def mel_filterbank(n_mels=64, fmin=30.0, fmax=8000.0):
    def hz2mel(f):
        return 2595 * np.log10(1 + f / 700)

    def mel2hz(m):
        return 700 * (10 ** (m / 2595) - 1)
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    pts = mel2hz(np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2))
    fb = np.zeros((n_mels, len(freqs)), np.float32)
    for i in range(n_mels):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        up = (freqs - lo) / (c - lo)
        down = (hi - freqs) / (hi - c)
        fb[i] = np.maximum(0, np.minimum(up, down))
    return fb


def stft_mag(y):
    pad = NFFT // 2
    y = np.pad(y, (pad, pad))
    n = 1 + (len(y) - NFFT) // HOP
    win = np.hanning(NFFT).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(y, (n, NFFT), (y.strides[0] * HOP, y.strides[0]))
    return np.abs(np.fft.rfft(frames * win, axis=1)).astype(np.float32)   # (frames, bins)


def smooth(x, n):
    if n <= 1:
        return x
    k = np.hanning(n + 2)[1:-1]
    k /= k.sum()
    return np.convolve(x, k, mode="same")


# --------------------------------------------------------------------------- tempo & beats
def estimate_tempo(onset, fps):
    o = onset - onset.mean()
    ac = np.correlate(o, o, mode="full")[len(o) - 1:]
    lags = np.arange(len(ac))
    bpm = np.where(lags > 0, 60 * fps / np.maximum(lags, 1), 0)
    valid = (bpm >= 60) & (bpm <= 200)
    weight = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1) / 120) / 0.9) ** 2)
    score = np.where(valid, ac * weight, -np.inf)
    lag = int(np.argmax(score))
    # parabolic refinement
    if 1 <= lag < len(ac) - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        denom = a - 2 * b + c
        lag_f = lag + (0.5 * (a - c) / denom if denom else 0)
    else:
        lag_f = lag
    return 60 * fps / lag_f


def track_beats(onset, fps, bpm, tightness=100.0):
    """Dynamic-programming beat tracker (Ellis 2007)."""
    period = fps * 60 / bpm
    o = onset / (onset.std() or 1)
    n = len(o)
    score = o.copy()
    back = np.full(n, -1)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    offsets = np.arange(-hi, -lo + 1)
    penalty = -tightness * (np.log(-offsets / period)) ** 2
    for t in range(hi, n):
        cand = score[t + offsets] + penalty
        j = int(np.argmax(cand))
        score[t] = o[t] + cand[j]
        back[t] = t + offsets[j]
    # start from the best score in the last period
    t = int(np.argmax(score[-int(period) - 1:])) + n - int(period) - 1
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    beats = np.array(beats[::-1])
    # trim weak beats at the very start/end (silence)
    strong = o[beats] > 0.15 * np.median(o[beats]) if len(beats) else beats
    return beats if not len(beats) else beats[np.argmax(strong):len(beats) - np.argmax(strong[::-1])]


# --------------------------------------------------------------------------- sections
def novelty_curve(feat, kernel):
    """Foote novelty: checkerboard kernel along the diagonal of a cosine self-similarity matrix."""
    f = feat / (np.linalg.norm(feat, axis=1, keepdims=True) + 1e-9)
    S = f @ f.T
    k = kernel
    g = np.outer(np.hanning(2 * k), np.hanning(2 * k))
    sign = np.ones((2 * k, 2 * k))
    sign[:k, k:] = -1
    sign[k:, :k] = -1
    K = g * sign
    n = len(S)
    Sp = np.pad(S, k, mode="edge")
    nov = np.array([(Sp[i:i + 2 * k, i:i + 2 * k] * K).sum() for i in range(n)])
    nov = np.maximum(nov, 0)
    return nov / (nov.max() or 1)


def pick_peaks(x, min_gap, thresh):
    peaks = []
    for i in np.argsort(x)[::-1]:
        if x[i] < thresh:
            break
        if all(abs(i - p) >= min_gap for p in peaks):
            peaks.append(int(i))
    return sorted(peaks)


def analyze(path: Path) -> dict:
    y = load_audio(path)
    if len(y) < SR:
        raise SystemExit("audio is shorter than a second")
    dur = len(y) / SR
    mag = stft_mag(y)
    fps = SR / HOP
    mel = mag @ mel_filterbank().T
    logmel = np.log1p(10 * mel)
    flux = np.maximum(0, np.diff(logmel, axis=0, prepend=logmel[:1])).sum(axis=1)
    onset = smooth(flux, 3)
    onset = np.maximum(0, onset - smooth(onset, int(fps)))     # remove slow trend
    rms = np.sqrt((mag ** 2).mean(axis=1))
    loud = smooth(20 * np.log10(rms + 1e-6), int(fps))

    bpm = estimate_tempo(onset, fps)
    beats = track_beats(onset, fps, bpm)
    if len(beats) > 8:
        bpm = 60 * fps / float(np.median(np.diff(beats)))
    beat_t = beats / fps + 0.9 * HOP / SR   # the smoothed onset peak lands ~1 hop early (measured on a click track)

    # downbeats: the phase (of 4) whose beats carry the most low-frequency attack
    bass = np.maximum(0, np.diff(logmel[:, :12].sum(axis=1), prepend=0))
    phase_score = [bass[beats[p::4]].mean() if len(beats[p::4]) else 0 for p in range(4)]
    phase = int(np.argmax(phase_score))
    downbeats = beat_t[phase::4]

    # beat-synchronous features for sections
    if len(beats) >= 16:
        edges = np.concatenate([beats, [len(logmel)]])
        feat = np.array([logmel[a:max(b, a + 1)].mean(axis=0) for a, b in zip(edges[:-1], edges[1:])])
        loud_b = np.array([loud[a:max(b, a + 1)].mean() for a, b in zip(edges[:-1], edges[1:])])
        # z-score each band so timbre changes count, not just overall level; loudness weighted in
        fz = (feat - feat.mean(axis=0)) / (feat.std(axis=0) + 1e-9)
        lz = (loud_b - loud_b.mean()) / (loud_b.std() + 1e-9)
        feat = np.hstack([fz, lz[:, None] * 4])
        nov = novelty_curve(feat, kernel=8)
        min_gap = max(8, int(round(6 * bpm / 60)))          # >= 6 s and >= 2 bars
        cuts = pick_peaks(nov, min_gap, 0.25)
        # snap to bar starts
        bar_idx = np.arange(phase, len(beats), 4)
        cuts = sorted({int(bar_idx[np.argmin(np.abs(bar_idx - c))]) for c in cuts if 0 < c < len(beats) - 4})
        bounds = [0.0] + [float(beat_t[c]) for c in cuts] + [dur]
    else:
        bounds = [0.0, dur]
    # energy per section
    t_frames = np.arange(len(loud)) / fps
    loud_n = (loud - np.percentile(loud, 5)) / ((np.percentile(loud, 98) - np.percentile(loud, 5)) or 1)
    loud_n = np.clip(loud_n, 0, 1)
    sections = []
    sec_feats = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 0.5:
            continue
        m = (t_frames >= a) & (t_frames < b)
        e = float(loud_n[m].mean()) if m.any() else 0.0
        sections.append({"start": round(a, 2), "end": round(b, 2), "energy": round(e, 3)})
        sec_feats.append(logmel[m].mean(axis=0) if m.any() else np.zeros(logmel.shape[1]))
    # repeat groups (A, B, C...) by spectral similarity
    letters = []
    reps: list[np.ndarray] = []
    for f in sec_feats:
        f = f / (np.linalg.norm(f) + 1e-9)
        sims = [float(f @ r) for r in reps]
        if sims and max(sims) > 0.985:
            letters.append(chr(65 + int(np.argmax(sims))))
        else:
            reps.append(f)
            letters.append(chr(65 + len(reps) - 1) if len(reps) <= 26 else "Z")
    emax = max((s["energy"] for s in sections), default=1) or 1
    for i, s in enumerate(sections):
        s["group"] = letters[i]
        rel = s["energy"] / emax
        s["level"] = "high" if rel >= 0.8 else ("low" if rel <= 0.45 else "mid")
        if i == 0 and s["level"] != "high":
            s["label"] = "intro"
        elif i == len(sections) - 1 and s["level"] != "high":
            s["label"] = "outro"
        else:
            s["label"] = {"high": "chorus/peak", "mid": "verse/build", "low": "breakdown/quiet"}[s["level"]]
    # accents: strongest onsets, at least 0.25 s apart
    on_n = onset / (np.percentile(onset, 99.5) or 1)
    cand = [i for i in range(1, len(on_n) - 1) if on_n[i] >= on_n[i - 1] and on_n[i] > on_n[i + 1] and on_n[i] > 0.6]
    cand.sort(key=lambda i: -on_n[i])
    acc = []
    for i in cand:
        if all(abs(i - j) > 0.25 * fps for j in acc):
            acc.append(i)
        if len(acc) >= max(8, int(dur / 4)):
            break
    acc.sort()
    step = 0.5
    grid = np.arange(0, dur, step)
    energy = [round(float(np.interp(t, t_frames, loud_n)), 3) for t in grid]
    return {
        "file": path.name, "duration": round(dur, 2), "tempo": round(float(bpm), 1),
        "beats": [round(float(t), 3) for t in beat_t], "downbeats": [round(float(t), 3) for t in downbeats],
        "sections": sections, "energy": {"step": step, "values": energy},
        "accents": [{"t": round(i / fps, 3), "strength": round(float(min(on_n[i], 1.5)), 2)} for i in acc],
        "notes": "estimates: check tempo/sections by ear; 4/4 assumed for bars",
    }


def summary(a: dict) -> str:
    def f(t):
        return f"{int(t // 60)}:{t % 60:05.2f}"
    lines = [f"{a['file']}: {f(a['duration'])}, ~{a['tempo']} BPM, {len(a['beats'])} beats, "
             f"{len(a['downbeats'])} bars, {len(a['accents'])} accents"]
    for s in a["sections"]:
        bar = "#" * int(round(s["energy"] * 20))
        lines.append(f"  {f(s['start'])}-{f(s['end'])}  [{s['group']}] {s['label']:<16} energy {s['energy']:.2f} {bar}")
    return "\n".join(lines)


def write_grids(seq: Path, a: dict) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lor_helper as H
    from lxml import etree
    doc = H.LorDoc(seq)
    grids = doc.section("TimingGrids", create=True)
    for name, marks in (("Beats", a["beats"]), ("Bars", a["downbeats"]),
                        ("Sections", [s["start"] for s in a["sections"]])):
        for g in grids.findall("TimingGridFree"):
            if g.get("name") == name:
                H.remove_keep_indent(g)
        g = etree.Element("TimingGridFree")
        g.set("name", name)
        doc.insert(grids, len(grids.findall("TimingGridFree")), g)
        for cs in sorted({int(round(t * 100)) for t in marks if 0 <= t * 100 <= doc.total}):
            el = etree.Element("timing")
            el.set("centisecond", str(cs))
            doc.insert(g, len(g), el)
    backup = doc.save()
    print(f"added timing grids Beats/Bars/Sections to {seq} (backup: {backup})")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("analyze")
    s.add_argument("audio", type=Path)
    s.add_argument("--out", type=Path)
    s.add_argument("--write-grids", type=Path, metavar="SEQ.loredit")
    s = sub.add_parser("summary")
    s.add_argument("analysis", type=Path)
    a = p.parse_args(argv)
    if a.cmd == "summary":
        print(summary(json.loads(a.analysis.read_text(encoding="utf-8"))))
        return 0
    res = analyze(a.audio)
    out = a.out or a.audio.with_suffix(".analysis.json")
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(summary(res))
    print(f"wrote {out}")
    if a.write_grids:
        write_grids(a.write_grids, res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
