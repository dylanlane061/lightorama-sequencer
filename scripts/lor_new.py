#!/usr/bin/env python3
"""lor_new.py: start a new, empty S6 sequence for a song.

    python lor_new.py from-preview layout.lorprev --audio song.mp3 --out "My Song.loredit"
    python lor_new.py from-sequence existing.loredit --audio song.mp3 --out "My Song.loredit"

from-preview builds the sequence the way S6 does. This was checked against an LOR
store sequence (S6 6.3), which it reproduces prop-for-prop and row-for-row:
  * one SeqProp per prop (preview order, skipping props that follow a MasterPropId),
    then one per prop group (preview order); EnablePixelChannels="0",
    OverlayMotionRows="1";
  * motion rows (track) copied from each prop's/group's MotionRowDefaults: same name and
    region attributes, DefaultId = the default's id, and id = that same id unless
    another row already uses it (then a new GUID);
  * no channel elements: S6 writes a channel only once it holds an effect (lor_helper
    adds them as needed);
  * the preview is embedded as-is (with its background photo); the empty sections are
    in S6's order; BOM + CRLF + ' />' like S6's own writer.

from-sequence keeps an existing sequence's structure and removes every effect,
channel, embedded picture and timing grid. This is the safest start when the user
already has a sequence for the same layout.

S6 finds the song by file name in its Audio folder (Documents\\Light-O-Rama\\Audio by
default), so copy the song there and pass --music-path if it lives somewhere else.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from lxml import etree

SECTIONS_AFTER = ["BeatChannels", "Subsequences", "SequenceProps", "ArchivedProps", "RgbAggregates",
                  "TimingGrids", "BeatView", "PropViews", "MotionPaks", "pictures"]


def audio_duration_cs(path: Path) -> int | None:
    exe = shutil.which("ffprobe")
    if exe:
        try:
            out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                                 capture_output=True, text=True, timeout=60).stdout
            return int(round(float(json.loads(out)["format"]["duration"]) * 100))
        except Exception:  # noqa: BLE001
            pass
    if path.suffix.lower() == ".wav":
        import wave
        with wave.open(str(path)) as w:
            return int(round(w.getnframes() / w.getframerate() * 100))
    return None


def parse_duration(text: str) -> int:
    t = text.strip().lower()
    if ":" in t:
        m, s = t.split(":", 1)
        return round((int(m) * 60 + float(s)) * 100)
    return round(float(t.rstrip("s")) * 100)


def write_like_s6(root, out: Path) -> None:
    etree.indent(root, space="  ")
    body = etree.tostring(root, encoding="utf-8", xml_declaration=False)
    body = body.replace(b"/>", b" />").replace(b"  />", b" />")
    text = b'<?xml version="1.0" encoding="utf-8"?>\n' + body + b"\n"
    out.write_bytes(b"\xef\xbb\xbf" + text.replace(b"\n", b"\r\n"))


def _track_from_default(mrd, used_ids: set) -> etree._Element:
    t = etree.Element("track")
    did = mrd.get("id") or str(uuid.uuid4())
    tid = did if did not in used_ids else str(uuid.uuid4())
    used_ids.add(tid)
    t.set("id", tid)
    t.set("name", mrd.get("name") or "Effects 01")
    for k, v in mrd.attrib.items():
        if k not in ("id", "name"):
            t.set(k, v)
    t.set("DefaultId", did)
    return t


def from_preview(preview_file: Path, audio: Path, out: Path, duration_cs: int | None, music_path: str | None) -> dict:
    src = etree.parse(str(preview_file), etree.XMLParser(huge_tree=True)).getroot()
    preview = src.find("PreviewClass") if src.tag == "sequence" else src
    if preview is None or preview.tag != "PreviewClass":
        raise SystemExit("expected a .lorprev (PreviewClass) or a .loredit with an embedded preview")
    preview = copy.deepcopy(preview)
    total = duration_cs or audio_duration_cs(audio)
    if not total:
        raise SystemExit("couldn't read the song length (install ffmpeg/ffprobe, or pass --duration 3:21.5)")
    now = _dt.datetime.now()
    root = etree.Element("sequence")
    for k, v in [("saveFileVersion", "15"), ("AppVersion", "6.3.0.6"), ("id", str(uuid.uuid4())),
                 ("totalCentiseconds", str(total)), ("WaveHeight", "1"), ("TimingGridIdx", "0"),
                 ("DragEventsWithTimings", "True"), ("ChaseClearFirst", "True"), ("ChaseSameRowType", "True"),
                 ("ChaseType", "0"), ("AudioAnalysisLevel", "0"), ("author", "lightorama-sequencer skill"),
                 ("createdAt", now.strftime("%m/%d/%Y %I:%M %p").lstrip("0")), ("musicTitle", audio.stem),
                 ("NameAreaWidth", "340"), ("ZoomWidth", "15"), ("ZoomHeight", "18"),
                 ("musicFilename", music_path or audio.name), ("GridView", "Show All Items"),
                 ("StartColor", "FFFFFFFF"), ("EndColor", "FFFFFFFF")]:
        root.set(k, v)
    root.append(preview)
    sections = {name: etree.SubElement(root, name) for name in SECTIONS_AFTER}
    sections["BeatChannels"].set("MaxDisplayedRows", "10")
    used: set = set()
    n_props = n_groups = n_rows = 0
    for pc in preview.iter("PropClass"):
        if pc.get("MasterPropId"):
            continue
        sp = etree.SubElement(sections["SequenceProps"], "SeqProp")
        for k, v in [("id", pc.get("id")), ("name", pc.get("Name") or ""), ("EnablePixelChannels", "0"),
                     ("OverlayMotionRows", "1")]:
            sp.set(k, v)
        for mrd in pc.iterfind("MotionRowDefaults/MotionRowDefault"):
            sp.append(_track_from_default(mrd, used))
            n_rows += 1
        n_props += 1
    for g in preview.iter("PropGroup"):
        sp = etree.SubElement(sections["SequenceProps"], "SeqProp")
        for k, v in [("id", g.get("id")), ("name", g.get("Name") or ""), ("EnablePixelChannels", "0"),
                     ("OverlayMotionRows", "1")]:
            sp.set(k, v)
        for mrd in g.iterfind("MotionRowDefaults/MotionRowDefault"):
            sp.append(_track_from_default(mrd, used))
            n_rows += 1
        n_groups += 1
    etree.SubElement(sections["TimingGrids"], "TimingGridFixed", {"name": "Fixed 0.10", "spacing": "10"})
    write_like_s6(root, out)
    return {"props": n_props, "groups": n_groups, "rows": n_rows, "totalCentiseconds": total}


def from_sequence(seq_file: Path, audio: Path, out: Path, duration_cs: int | None, music_path: str | None) -> dict:
    root = etree.parse(str(seq_file), etree.XMLParser(huge_tree=True)).getroot()
    if root.tag != "sequence":
        raise SystemExit("not a .loredit")
    removed = 0
    for sp in root.iterfind("SequenceProps/SeqProp"):
        for ch in sp.findall("channel"):
            removed += len(ch)
            sp.remove(ch)
        for t in sp.findall("track"):
            for e in list(t):
                removed += 1
                t.remove(e)
            t.text = None
    for name in ("pictures", "TimingGrids", "ArchivedProps", "Subsequences"):
        el = root.find(name)
        if el is not None:
            for c in list(el):
                el.remove(c)
            el.text = None
    tg = root.find("TimingGrids")
    if tg is not None:
        etree.SubElement(tg, "TimingGridFixed", {"name": "Fixed 0.10", "spacing": "10"})
    total = duration_cs or audio_duration_cs(audio)
    if not total:
        raise SystemExit("couldn't read the song length (install ffmpeg/ffprobe, or pass --duration 3:21.5)")
    root.set("totalCentiseconds", str(total))
    root.set("id", str(uuid.uuid4()))
    root.set("musicFilename", music_path or audio.name)
    root.set("musicTitle", audio.stem)
    root.set("TimingGridIdx", "0")
    for el in root.iter():
        if el.text is not None and not el.text.strip():
            el.text = None
        if el.tail is not None and not el.tail.strip():
            el.tail = None
    write_like_s6(root, out)
    return {"effects_removed": removed, "totalCentiseconds": total}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("from-preview", "from-sequence"):
        s = sub.add_parser(name)
        s.add_argument("source", type=Path)
        s.add_argument("--audio", type=Path, required=True)
        s.add_argument("--out", type=Path, required=True)
        s.add_argument("--duration", help="song length if ffprobe isn't installed, e.g. 3:21.5")
        s.add_argument("--music-path", help="musicFilename to store (default: the song's file name)")
        s.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    a = p.parse_args(argv)
    if a.out.exists() and not a.force:
        sys.exit(f"{a.out} exists; pass --force to overwrite (lor_new never edits an existing show)")
    dur = parse_duration(a.duration) if a.duration else None
    fn = from_preview if a.cmd == "from-preview" else from_sequence
    info = fn(a.source, a.audio, a.out, dur, a.music_path)
    print(f"wrote {a.out}: " + ", ".join(f"{k}={v}" for k, v in info.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
