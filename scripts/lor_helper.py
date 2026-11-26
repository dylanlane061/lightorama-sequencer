#!/usr/bin/env python3
"""lor_helper.py: inspect and safely edit Light-O-Rama S6 .loredit sequences.

Every editing command:
  * makes a timestamped backup in <sequence folder>/_lor_backups/ before writing,
  * changes only the elements it adds (the rest of the file keeps its formatting),
  * refuses overlapping effects unless --on-overlap replace is given,
  * accepts --dry-run to show the XML it would insert without writing anything.

Times can be given as centiseconds (1234), seconds (12.34s) or m:ss.cc (1:02.5).
See ../references/schema_examples.md for the format and how sure each part is.

Commands
  inspect             props, motion rows, channels, matrix sizes, timing grids, pictures
  timings             list a timing grid's marks (for snapping)
  validate            structural checks (ids, overlaps, bounds, picture references)
  render-ascii        pixel-art spec (JSON) -> PNG, or an animated GIF if it has several frames
  fit-image           resize/crop any image to an exact WxH for a matrix
  preview             upscale a PNG/GIF so the agent can look at it (pixel grid, contact sheet)
  add-picture-effect  put a PNG/GIF on a pixel prop's motion row (PictureXY, embedded by default)
  add-motion-effect   put a preset motion effect (wash, twinkle, bars, ...) on a motion row
  add-effect          put on/fade/shimmer/twinkle effects on traditional or dumb-RGB channels
  learn-template      copy an existing effect's exact settings string into templates.json
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import re
import shutil
import sys
import urllib.parse
import uuid
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    sys.exit("lor_helper needs lxml:  pip install lxml pillow")

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_FILE = SKILL_DIR / "references" / "templates.json"

# --------------------------------------------------------------------------- format constants
# Observed in real S6 files (see schema_examples.md section 4).
MIX_ONE_SIDED = "Mix_Average|0|0|full|20"
DEFAULT_SLOTS = ("FFFF0000", "FF00FF00", "FF0000FF", "FFFFFF00", "FFFFFFFF")
NONE_SIDE = "lightorama_none:" + ";".join(f"{c},0" for c in DEFAULT_SLOTS) + ";FF000000,0:"

PRESETS: dict[str, tuple[str, str]] = {
    "wash": ("colorwash", "full,full,single_color"),
    "gradient": ("colorwash", "full,full,horizontal_gradient"),
    "twinkle": ("twinkle", "50,25,twinkle,random,0,255"),
    "bars": ("bars", "H_expand,1,False,False,12,0"),
    "blend_up": ("blendedbars", "up,10,10,0"),
    "blend_expand": ("blendedbars", "V_expand,10,12,0"),
    "meteors_down": ("meteors", "palette,19,35,down,0,16,pixel_rate,oscillate"),
    "meteors_up": ("meteors", "palette,100,25,up,0,12,pixel_rate,linear2"),
    "spiral_left": ("spirals", "2,left_to_right,100,18,0,False,none,5"),
    "spiral_right": ("spirals", "2,left_to_right,-100,18,0,False,none,5"),
    "lines": ("straightlines", "default,4,12,1,21"),
    "lines_across": ("straightlines", "Left_to_Right,3,12,1,21"),
    "ripple": ("ripple", "circle,1,25,A12A50A1.00,4,3,1,13,False,50"),
    "garland_up": ("garland", "0,0,once_fit_to_duration,12,bottom_to_top"),
    "garland_down": ("garland", "0,0,once_fit_to_duration,12,top_to_bottom"),
    "garland_across": ("garland", "0,0,once_fit_to_duration,12,left_to_right"),
    # seen in LOR's own "New Years Eve Countdown" sequence (S6 6.3)
    "fireworks": ("fireworks", "25,60,2,30,normal,continuous"),
    # blended bars that keep a prop fully lit while colour bands travel along it.
    # "right,10,36,0" is quoted from a real LOR file in xLights' importer; "left" is the
    # same field's opposite value (also mapped by that importer). Direction follows the
    # prop's own pixel order, so pick per prop to move the same way physically.
    "blend_right": ("blendedbars", "right,10,36,0"),
    "blend_left": ("blendedbars", "left,10,36,0"),
}

# Picture option templates. {file} is replaced by the (encoded) file reference.
# picturexy: observed form at 100/100/0/0 = stretched over the whole prop.
# picture:   LOR 6 form reported by xLights; trailing fields may be missing -> learn-template.
PICTURE_TEMPLATES = {
    "picturexy": {"options": "{file},100,100,0,0,100,100,100,100,FFFF,0", "verified": False},
    "picture": {"options": "{file},fit_both,none,0,10,,12", "verified": False},
}

COLORS = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255),
    "warm white": (255, 180, 100), "warmwhite": (255, 180, 100), "gold": (255, 176, 0),
    "yellow": (255, 255, 0), "orange": (255, 96, 0), "purple": (176, 2, 176),
    "magenta": (255, 0, 255), "pink": (255, 64, 128), "cyan": (0, 255, 255),
    "teal": (0, 176, 176), "ice blue": (64, 128, 255), "black": (0, 0, 0),
}

SECTION_ORDER = ["PreviewClass", "BeatChannels", "Subsequences", "SequenceProps", "ArchivedProps",
                 "RgbAggregates", "TimingGrids", "BeatView", "PropViews", "MotionPaks", "pictures"]


class LorError(Exception):
    pass


# --------------------------------------------------------------------------- small utilities
def parse_color(value: str) -> tuple[int, int, int]:
    v = value.strip().lower()
    if v in COLORS:
        return COLORS[v]
    v = v.lstrip("#")
    if re.fullmatch(r"[0-9a-f]{6}", v):
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    if re.fullmatch(r"[0-9a-f]{8}", v):  # AARRGGBB
        return int(v[2:4], 16), int(v[4:6], 16), int(v[6:8], 16)
    raise LorError(f"unknown colour {value!r} (use a name like 'red' or #RRGGBB)")


def argb_signed(rgb: tuple[int, int, int], percent: float = 100) -> int:
    share = max(0.0, min(100.0, percent)) / 100
    r, g, b = (round(c * share) for c in rgb)
    return ((0xFF << 24) | (r << 16) | (g << 8) | b) - (1 << 32)


def argb_to_text(value: int) -> str:
    u = value & 0xFFFFFFFF
    return f"#{(u >> 16) & 255:02X}{(u >> 8) & 255:02X}{u & 255:02X}"


def parse_time(text: str) -> int:
    """'1234' centiseconds, '12.34s' seconds, '1:02.5' minutes:seconds -> centiseconds."""
    t = str(text).strip().lower()
    try:
        if ":" in t:
            m, s = t.split(":", 1)
            return round((int(m) * 60 + float(s.rstrip("s"))) * 100)
        if t.endswith("ms"):
            return round(float(t[:-2]) / 10)
        if t.endswith("s"):
            return round(float(t[:-1]) * 100)
        if t.endswith("cs"):
            t = t[:-2]
        return int(t)
    except ValueError as exc:
        raise LorError(f"can't read time {text!r}; use 1234 (cs), 12.34s, or 1:02.5") from exc


def fmt_time(cs: int) -> str:
    return f"{cs // 6000}:{(cs % 6000) / 100:05.2f}"


def palette(colors: list[str] | None) -> str:
    """Six palette slots 'AARRGGBB,<0|1>' joined by ';' (sixth always black)."""
    slots = [[c, 0] for c in DEFAULT_SLOTS]
    for name in (colors or [])[:5]:
        r, g, b = parse_color(name)
        hexv = f"FF{r:02X}{g:02X}{b:02X}"
        for slot in slots:
            if slot[0] == hexv and not slot[1]:
                slot[1] = 1
                break
        else:
            for slot in slots:
                if not slot[1]:
                    slot[0], slot[1] = hexv, 1
                    break
    return ";".join(f"{c},{u}" for c, u in slots) + ";FF000000,0"


def load_templates() -> dict:
    if TEMPLATES_FILE.is_file():
        try:
            return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: {TEMPLATES_FILE} is not valid JSON; using built-in templates", file=sys.stderr)
    return {}


# --------------------------------------------------------------------------- document I/O
class LorDoc:
    """A .loredit file parsed so that untouched parts are written back unchanged."""

    def __init__(self, path: Path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        body = raw[3:] if self.bom else raw
        m = re.match(rb"\s*<\?xml[^>]*\?>", body)
        self.declaration = m.group(0).strip() if m else b'<?xml version="1.0" encoding="utf-8"?>'
        self.crlf = b"\r\n" in body[:4096]
        self.space_slash = b" />" in body
        self.trailing_newline = body.endswith(b"\n")
        parser = etree.XMLParser(remove_blank_text=False, huge_tree=True, resolve_entities=False)
        try:
            self.root = etree.fromstring(body, parser)
        except etree.XMLSyntaxError as exc:
            raise LorError(f"{self.path} is not well-formed XML: {exc}") from exc
        if self.root.tag != "sequence":
            raise LorError(f"root element is <{self.root.tag}>, expected <sequence> (is this a .loredit?)")
        self.indent_unit, self.pretty = self._detect_indent()

    # -- indentation -----------------------------------------------------------------------
    def _detect_indent(self) -> tuple[str, bool]:
        text = self.root.text or ""
        if "\n" not in text:
            return "", False
        unit = text.rsplit("\n", 1)[1]
        return (unit or "  "), True

    def _depth(self, el) -> int:
        return sum(1 for _ in el.iterancestors())

    def insert(self, parent, index: int, child) -> None:
        """Insert child keeping the document's indentation style."""
        n = len(parent)
        index = max(0, min(index, n))
        parent.insert(index, child)
        if not self.pretty:
            return
        d = self._depth(parent)
        inner = "\n" + self.indent_unit * (d + 1)
        outer = "\n" + self.indent_unit * d
        if n == 0:
            parent.text = inner
            child.tail = outer
        elif index == n:  # appended after the old last child
            prev = parent[index - 1]
            child.tail = prev.tail if prev.tail is not None else outer
            prev.tail = inner
        else:
            child.tail = inner
            if index == 0:
                parent.text = inner

    # -- output -----------------------------------------------------------------------------
    def to_bytes(self) -> bytes:
        enc = "utf-8"
        m = re.search(rb'encoding="([^"]+)"', self.declaration)
        if m:
            enc = m.group(1).decode("ascii")
        out = etree.tostring(self.root, encoding=enc, xml_declaration=False)
        if self.space_slash:
            out = re.sub(rb'(?<=["\w])/>', b" />", out)
        nl = b"\r\n" if self.crlf else b"\n"
        out = self.declaration + nl + out.replace(b"\r\n", b"\n").replace(b"\n", nl)
        if self.trailing_newline and not out.endswith(nl):
            out += nl
        return (b"\xef\xbb\xbf" if self.bom else b"") + out

    def save(self, dry_run: bool = False) -> Path | None:
        data = self.to_bytes()
        # Re-parse what we are about to write: never leave a broken file behind.
        etree.fromstring(data[3:] if self.bom else data, etree.XMLParser(huge_tree=True))
        if dry_run:
            return None
        backup = make_backup(self.path)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(self.path)
        return backup

    # -- lookups ----------------------------------------------------------------------------
    @property
    def total(self) -> int:
        return int(self.root.get("totalCentiseconds", "0") or 0)

    def section(self, name: str, create: bool = False):
        el = self.root.find(name)
        if el is None and create:
            el = etree.Element(name)
            # place it according to SECTION_ORDER
            want = SECTION_ORDER.index(name) if name in SECTION_ORDER else len(SECTION_ORDER)
            idx = len(self.root)
            for i, child in enumerate(self.root):
                if child.tag in SECTION_ORDER and SECTION_ORDER.index(child.tag) > want:
                    idx = i
                    break
            self.insert(self.root, idx, el)
        return el

    def preview_groups(self) -> dict[str, object]:
        return {g.get("id"): g for g in self.root.iter("PropGroup") if g.get("id")}

    def kind_of(self, seq_prop) -> str:
        sid = seq_prop.get("id")
        pc = self.preview_props().get(sid)
        if pc is not None:
            return prop_kind(pc)
        return "group" if sid in self.preview_groups() else "unknown"

    def preview_props(self) -> dict[str, object]:
        res = {}
        for pc in self.root.iter("PropClass"):
            if pc.get("id"):
                res[pc.get("id")] = pc
        return res

    def seq_props(self) -> list:
        sp = self.root.find("SequenceProps")
        return [] if sp is None else sp.findall("SeqProp")

    def find_seq_prop(self, name: str):
        props = self.seq_props()
        exact = [p for p in props if (p.get("name") or "") == name]
        if not exact:
            exact = [p for p in props if (p.get("name") or "").lower() == name.lower()]
        if not exact:
            exact = [p for p in props if name.lower() in (p.get("name") or "").lower()]
        if len(exact) == 1:
            return exact[0]
        names = sorted(p.get("name") or "?" for p in props)
        if not exact:
            raise LorError(f"no sequenced prop matches {name!r}. Props: {', '.join(names[:60])}"
                           + (" ..." if len(names) > 60 else ""))
        raise LorError(f"{name!r} matches several props: {', '.join(p.get('name') for p in exact)}")


def make_backup(path: Path) -> Path:
    folder = path.parent / "_lor_backups"
    folder.mkdir(exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{path.stem}.{stamp}{path.suffix}"
    n = 1
    while dest.exists():
        dest = folder / f"{path.stem}.{stamp}-{n}{path.suffix}"
        n += 1
    shutil.copy2(path, dest)
    return dest


# --------------------------------------------------------------------------- prop analysis
def prop_kind(pc) -> str:
    if pc is None:
        return "unknown"
    st = pc.get("StringType") or ""
    if st == "RGB":
        return "pixel"
    if st == "DumbRGB":
        return "dumb_rgb"
    return "traditional"


def track_type(t) -> str:
    """S6 marks region rows by their attributes, not always with type= (seen in LOR's own files)."""
    if t.get("type"):
        return t.get("type")
    if t.get("subx") is not None:
        return "rectangle"
    if t.get("subc") is not None or t.get("subc2") is not None:
        return "custom"
    return "none"


def matrix_size(pc) -> tuple[int, int, str] | None:
    """(width, height, note) for matrix-shaped pixel props, from Parm1..3 (inferred)."""
    if pc is None:
        return None
    shape = pc.find("shape")
    shape_name = shape.get("ShapeName", "") if shape is not None else ""
    parms = []
    for i in range(1, 10):
        v = pc.get(f"Parm{i}")
        if v is None:
            break
        try:
            parms.append(int(float(v)))
        except ValueError:
            parms.append(0)
    if not shape_name.lower().startswith("matrix") or len(parms) < 2:
        return None
    strings, nodes = parms[0], parms[1]
    folds = parms[2] if len(parms) > 2 else 0
    per = folds + 1
    if strings <= 0 or nodes <= 0 or nodes % per:
        return None
    strands, length = strings * per, nodes // per
    vertical = "vertical" in shape_name.lower()
    w, h = (strands, length) if vertical else (length, strands)
    return w, h, f"estimated from {shape_name} Parm1-3 ({strings} strings x {nodes} nodes, {folds} folds)"


def pixel_count(pc) -> int | None:
    grid = pc.get("ChannelGrid") if pc is not None else None
    if not grid:
        return None
    total = 0
    for part in grid.split(";"):
        bits = part.split(",")
        if len(bits) >= 4:   # "Regular,<universe>,..." (E1.31/DMX) or "Aux A,<unit>,..." (LOR network)
            try:
                first, last = int(bits[2]), int(bits[3])
            except ValueError:
                continue
            total += (last - first + 1) // 3 if last >= first else ((510 - first + 1) + last) // 3
    return total or None


# --------------------------------------------------------------------------- effect placement
def expected_channels(pc) -> list[tuple[str, str, str]]:
    """(row, col, color) of each sequence channel S6 uses for a non-pixel prop (checked against
    LOR's own files): dumb RGB -> one channel; several ChannelGrid entries -> one channel each,
    numbered by `color` for Channel_per_color props and by `col` otherwise."""
    if pc is None:
        return []
    entries = [e for e in (pc.get("ChannelGrid") or "").split(";") if e.strip()]
    if prop_kind(pc) == "dumb_rgb" or len(entries) <= 1:
        return [("0", "0", "0")]
    if pc.get("TraditionalType") == "Channel_per_color":
        return [("0", "0", str(i)) for i in range(len(entries))]
    return [("0", str(i), "0") for i in range(len(entries))]


def ensure_channels(doc, sp, pc, only=None) -> list:
    """The prop's channel elements in S6 order, creating missing ones (S6 only writes a channel
    once it has effects, so a new sequence has none)."""
    want = expected_channels(pc)
    have = {(c.get("row", "0"), c.get("col", "0"), c.get("color", "0")): c for c in sp.findall("channel")}
    if not want:
        return sp.findall("channel")
    out = []
    for i, key in enumerate(want):
        el = have.get(key)
        if el is None and only is not None and i not in only:
            out.append(None)
            continue
        if el is None:
            el = etree.Element("channel")
            el.set("row", key[0]); el.set("col", key[1]); el.set("color", key[2])
            # insert before the first existing channel that comes later in S6 order, else after the last one
            later = [have[k] for k in want[want.index(key) + 1:] if k in have]
            if later:
                idx = list(sp).index(later[0])
            else:
                prev = next((o for o in reversed(out) if o is not None), None)
                idx = list(sp).index(prev) + 1 if prev is not None and prev.getparent() is sp else 0
            doc.insert(sp, idx, el)
            have[key] = el
        out.append(el)
    return out


def effects_in(container) -> list:
    return [e for e in container if e.tag == "effect"]


def span(e) -> tuple[int, int]:
    return int(e.get("startCentisecond", "0")), int(e.get("endCentisecond", "0"))


def place_effect(doc: LorDoc, container, effect, on_overlap: str, label: str) -> list[str]:
    """Insert effect in time order; handle overlaps. Returns notes."""
    s, e = span(effect)
    if s < 0 or e <= s:
        raise LorError(f"{label}: end ({e}) must be after start ({s})")
    if doc.total and e > doc.total:
        raise LorError(f"{label}: ends at {fmt_time(e)} but the sequence is {fmt_time(doc.total)} long")
    notes = []
    clashes = [x for x in effects_in(container) if span(x)[0] < e and s < span(x)[1]]
    if clashes:
        desc = ", ".join(f"{fmt_time(span(x)[0])}-{fmt_time(span(x)[1])}" for x in clashes)
        if on_overlap != "replace":
            raise LorError(f"{label}: overlaps existing effect(s) {desc}. "
                           "Pick another time/row, or pass --on-overlap replace.")
        for x in clashes:
            remove_keep_indent(x)
        notes.append(f"{label}: replaced {len(clashes)} overlapping effect(s) {desc}")
    idx = len(container)
    for i, x in enumerate(container):
        if x.tag == "effect" and span(x)[0] >= e:
            idx = i
            break
    doc.insert(container, idx, effect)
    return notes


def remove_keep_indent(el) -> None:
    """Remove el; the whitespace that followed it takes the place of the whitespace before it."""
    parent = el.getparent()
    prev = el.getprevious()
    if prev is not None:
        prev.tail = el.tail
    else:
        parent.text = el.tail
    parent.remove(el)


def level_attrs(intensity: int | None, start: int | None, end: int | None) -> dict[str, str]:
    if start is not None or end is not None:
        a = 100 if start is None else start
        b = 100 if end is None else end
        if a == b:
            return {"intensity": str(a)}
        return {"startIntensity": str(a), "endIntensity": str(b)}
    return {"intensity": str(100 if intensity is None else intensity)}


def new_effect(start: int, end: int, settings: str, level: dict[str, str]):
    el = etree.Element("effect")
    # attribute order as seen in S6 files written by the reference tools
    el.set("startCentisecond", str(start))
    el.set("endCentisecond", str(end))
    for k, v in level.items():
        el.set(k, v)
    el.set("settings", settings)
    return el


def get_track(doc: LorDoc, seq_prop, row: str | None, new_row: str | None):
    tracks = seq_prop.findall("track")
    if new_row:
        if any((t.get("name") or "") == new_row for t in tracks):
            raise LorError(f"motion row {new_row!r} already exists on {seq_prop.get('name')}; use --row")
        t = etree.Element("track")
        new_id = str(uuid.uuid4())
        t.set("id", new_id)
        t.set("name", new_row)
        if tracks and tracks[-1].get("DefaultId") is not None:
            t.set("DefaultId", new_id)   # S6 rows carry DefaultId == id (from the prop's MotionRowDefaults)
        if tracks and tracks[-1].get("type") is not None:
            t.set("type", "none")
        last = tracks[-1] if tracks else None
        idx = list(seq_prop).index(last) + 1 if last is not None else len(seq_prop)
        doc.insert(seq_prop, idx, t)
        empty = [x.get("name") for x in tracks if not effects_in(x) and track_type(x) == "none"]
        hint = f" Existing empty whole-prop rows you could use instead: {', '.join(empty[:5])}." if empty else ""
        return t, (f"created motion row {new_row!r} (draws on top of earlier rows). UNTESTED: rows made "
                   f"outside S6 have no matching MotionRowDefault.{hint}")
    if not tracks:
        raise LorError(f"{seq_prop.get('name')} has no motion-effect rows. Pass --new-row 'Effects 01' "
                       "to create one (or add rows in S6: right-click the prop > Add/Modify motion effect rows).")
    if row is None:
        return tracks[0], None
    for t in tracks:
        if (t.get("name") or "") == row:
            return t, None
    for t in tracks:
        if (t.get("name") or "").lower() == row.lower():
            return t, None
    if row.isdigit() and 1 <= int(row) <= len(tracks):
        return tracks[int(row) - 1], None
    raise LorError(f"no motion row {row!r} on {seq_prop.get('name')}. Rows: "
                   + ", ".join(t.get("name") or "?" for t in tracks))


def snap(doc: LorDoc, grid_name: str | None, cs: int) -> int:
    if not grid_name:
        return cs
    grids = doc.root.find("TimingGrids")
    if grids is None:
        raise LorError("sequence has no TimingGrids")
    for g in grids:
        if (g.get("name") or "").lower() != grid_name.lower():
            continue
        if g.tag == "TimingGridFixed":
            sp = int(g.get("spacing", "1") or 1)
            return round(cs / sp) * sp
        marks = sorted(int(t.get("centisecond")) for t in g.iter("timing"))
        if not marks:
            raise LorError(f"timing grid {grid_name!r} is empty")
        return min(marks, key=lambda m: abs(m - cs))
    raise LorError(f"no timing grid named {grid_name!r}; run `timings` to list them")


# --------------------------------------------------------------------------- commands
def cmd_inspect(args) -> int:
    doc = LorDoc(args.file)
    pcs = doc.preview_props()
    out = {
        "file": str(doc.path),
        "saveFileVersion": doc.root.get("saveFileVersion"),
        "AppVersion": doc.root.get("AppVersion"),
        "totalCentiseconds": doc.total,
        "length": fmt_time(doc.total),
        "musicFilename": doc.root.get("musicFilename"),
        "props": [],
        "timingGrids": [],
        "embeddedPictures": [],
        "sections": [c.tag for c in doc.root if isinstance(c.tag, str)],
    }
    for sp in doc.seq_props():
        pc = pcs.get(sp.get("id"))
        info = {"name": sp.get("name"), "id": sp.get("id"), "kind": doc.kind_of(sp)}
        if pc is not None:
            info["DeviceType"] = pc.get("DeviceType")
            if pc.get("StringType"):
                info["StringType"] = pc.get("StringType")
            if pc.get("TraditionalType"):
                info["TraditionalType"] = pc.get("TraditionalType")
            px = pixel_count(pc) if info["kind"] == "pixel" else None
            if px:
                info["pixels"] = px
            ms = matrix_size(pc)
            if ms:
                info["matrix"] = {"width": ms[0], "height": ms[1], "note": ms[2]}
            sh = pc.find("shape")
            if sh is not None and sh.get("ShapeName"):
                info["shape"] = sh.get("ShapeName")
        tracks = sp.findall("track")
        if tracks:
            info["motionRows"] = [
                {"name": t.get("name"), "type": track_type(t), "effects": len(effects_in(t)),
                 **({"region": {k: t.get(k) for k in ("subx", "suby", "subw", "subh")}}
                    if track_type(t) == "rectangle" else {})}
                for t in tracks]
        chans = sp.findall("channel")
        if chans:
            info["channels"] = [{"index": i, "row": c.get("row"), "col": c.get("col"),
                                 "color": c.get("color"), "effects": len(effects_in(c))}
                                for i, c in enumerate(chans)]
        out["props"].append(info)
    grids = doc.root.find("TimingGrids")
    if grids is not None:
        for g in grids:
            if not isinstance(g.tag, str):
                continue
            if g.tag == "TimingGridFixed":
                out["timingGrids"].append({"name": g.get("name"), "type": "fixed", "spacing": int(g.get("spacing", "0"))})
            else:
                marks = [int(t.get("centisecond")) for t in g.iter("timing")]
                out["timingGrids"].append({"name": g.get("name"), "type": "free", "marks": len(marks),
                                           "first": marks[:5]})
    pics = doc.root.find("pictures")
    if pics is not None:
        out["embeddedPictures"] = [p.get("name") for p in pics.findall("picture")]
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"{doc.path.name}: S6 saveFileVersion={out['saveFileVersion']} AppVersion={out['AppVersion']} "
          f"length={out['length']} ({doc.total} cs)  music={out['musicFilename']}")
    print(f"\nProps ({len(out['props'])}):")
    shown = [p for p in out["props"] if not args.filter or args.filter.lower() in (p["name"] or "").lower()]
    if args.filter:
        print(f"(showing {len(shown)} matching {args.filter!r})")
    for p in shown:
        extra = []
        if "matrix" in p:
            extra.append(f"matrix ~{p['matrix']['width']}x{p['matrix']['height']}")
        elif "pixels" in p:
            extra.append(f"{p['pixels']} px")
        if "shape" in p:
            extra.append(p["shape"])
        rows = p.get("motionRows", [])
        if args.summary:
            used = [f"{r['name']}({r['effects']})" for r in rows if r["effects"]]
            free = [r["name"] for r in rows if not r["effects"] and r["type"] == "none"]
            ch = p.get("channels", [])
            bits = []
            if rows:
                bits.append(f"rows={len(rows)}" + (f" used: {', '.join(used[:4])}" if used else "")
                            + (f" free: {', '.join(free[:3])}" if free else ""))
            if ch:
                bits.append(f"channels={len(ch)} effects={sum(c['effects'] for c in ch)}")
            print(f"  - {p['name']}  [{p['kind']}{', ' + ', '.join(extra) if extra else ''}]  " + "; ".join(bits))
            continue
        print(f"  - {p['name']}  [{p['kind']}{', ' + ', '.join(extra) if extra else ''}]")
        for r in rows:
            reg = f" region={r['region']}" if "region" in r else ""
            print(f"      row: {r['name']!s:<24} type={r['type']:<10} effects={r['effects']}{reg}")
        ch = p.get("channels", [])
        if ch:
            n = sum(c["effects"] for c in ch)
            print(f"      channels: {len(ch)}  effects={n}")
    print("\nTiming grids:")
    for g in out["timingGrids"]:
        if g["type"] == "fixed":
            print(f"  - {g['name']}  (fixed, every {g['spacing']} cs)")
        else:
            print(f"  - {g['name']}  ({g['marks']} marks; first {g['first']})")
    print(f"\nEmbedded pictures: {len(out['embeddedPictures'])}")
    for n in out["embeddedPictures"]:
        print(f"  - {n}")
    return 0


def cmd_timings(args) -> int:
    doc = LorDoc(args.file)
    grids = doc.root.find("TimingGrids")
    if grids is None:
        print("no timing grids")
        return 0
    for g in grids:
        if not isinstance(g.tag, str):
            continue
        if args.grid and (g.get("name") or "").lower() != args.grid.lower():
            continue
        if g.tag == "TimingGridFixed":
            print(f"{g.get('name')}: fixed every {g.get('spacing')} cs")
            continue
        marks = [int(t.get("centisecond")) for t in g.iter("timing")]
        if args.grid:
            if args.json:
                print(json.dumps(marks))
            else:
                for m in marks:
                    print(f"{m}\t{fmt_time(m)}")
        else:
            print(f"{g.get('name')}: {len(marks)} marks")
    return 0


def cmd_validate(args) -> int:
    doc = LorDoc(args.file)
    problems, warnings = [], []
    order = [c.tag for c in doc.root if isinstance(c.tag, str)]
    known = [t for t in order if t in SECTION_ORDER]
    if known != sorted(known, key=SECTION_ORDER.index):
        problems.append(f"top-level sections out of order: {known}")
    for t in SECTION_ORDER:
        if t not in order:
            warnings.append(f"missing section <{t}>")
    pcs = doc.preview_props()
    pic_names = {p.get("name") for p in doc.root.iterfind("pictures/picture")}
    total = doc.total
    for sp in doc.seq_props():
        name = sp.get("name")
        if pcs and sp.get("id") not in pcs and sp.get("id") not in doc.preview_groups():
            warnings.append(f"SeqProp {name!r} id has no PropClass in the embedded preview (stub/archived?)")
        for cont in list(sp.findall("track")) + list(sp.findall("channel")):
            where = f"{name} / {cont.tag} {cont.get('name') or cont.get('col')}"
            effs = []
            for e in effects_in(cont):
                try:
                    s, en = span(e)
                except ValueError:
                    problems.append(f"{where}: non-integer times {dict(e.attrib)}")
                    continue
                if en <= s:
                    problems.append(f"{where}: effect {s}-{en} has end <= start")
                if total and en > total:
                    problems.append(f"{where}: effect ends at {en} > totalCentiseconds {total}")
                effs.append((s, en))
                st = e.get("settings") or ""
                if cont.tag == "track":
                    parts = st.split("|")
                    if len(parts) < 7:
                        problems.append(f"{where}: motion settings has {len(parts)} '|' fields (need 7+)")
                    for side in parts[5:7]:
                        m = re.match(r"lightorama_(picture|picturexy):[^:]*:([^,]*)", side)
                        if m:
                            ref = urllib.parse.unquote(m.group(2))
                            if ref.startswith("*") and ref not in pic_names:
                                problems.append(f"{where}: embedded picture {ref!r} not in <pictures>")
                if "intensity" not in e.attrib and not ("startIntensity" in e.attrib or "endIntensity" in e.attrib):
                    warnings.append(f"{where}: effect {s}-{en} has no intensity attributes")
            effs.sort()
            for (a0, a1), (b0, b1) in zip(effs, effs[1:]):
                if b0 < a1:
                    problems.append(f"{where}: overlapping effects {a0}-{a1} and {b0}-{b1}")
    for w in warnings[: args.max]:
        print(f"warning: {w}")
    for p in problems[: args.max]:
        print(f"PROBLEM: {p}")
    if len(problems) > args.max:
        print(f"... and {len(problems) - args.max} more problems")
    print(f"{'OK' if not problems else 'FAILED'}: {len(problems)} problem(s), {len(warnings)} warning(s)")
    return 1 if problems else 0


def _need_pil():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise LorError("this command needs Pillow:  pip install pillow")


def cmd_render_ascii(args) -> int:
    """Spec JSON:
    {"width": 32, "height": 50,            # target matrix (output size)
     "palette": {".": "black", "R": "red", "w": "#FFFFFF"},
     "frames": [["..RR..", ".RRRR."], ...],  # rows of characters; one list per frame
     "fps": 8,                              # GIF speed (or "durations_ms": [...])
     "anchor": "center" | "top" | "bottom" | [x, y],
     "scale": 1,                            # integer upscale of the art before placing
     "background": "black"}
    Characters not in the palette are treated as black (off).
    """
    _need_pil()
    from PIL import Image
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    W, H = int(spec["width"]), int(spec["height"])
    pal = {k: parse_color(v) for k, v in spec.get("palette", {}).items()}
    bg = parse_color(spec.get("background", "black"))
    scale = int(spec.get("scale", 1))
    frames = spec["frames"]
    if frames and isinstance(frames[0], str):
        frames = [frames]
    images = []
    for fi, rows in enumerate(frames):
        art_h = len(rows) * scale
        art_w = max((len(r) for r in rows), default=0) * scale
        img = Image.new("RGB", (W, H), bg)
        anchor = spec.get("anchor", "center")
        if isinstance(anchor, list):
            ox, oy = int(anchor[0]), int(anchor[1])
        else:
            ox = (W - art_w) // 2
            oy = {"top": 0, "bottom": H - art_h}.get(anchor, (H - art_h) // 2)
        if art_w > W or art_h > H:
            print(f"warning: frame {fi} art {art_w}x{art_h} is larger than {W}x{H}; it will be clipped",
                  file=sys.stderr)
        px = img.load()
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch not in pal:
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        X, Y = ox + x * scale + dx, oy + y * scale + dy
                        if 0 <= X < W and 0 <= Y < H:
                            px[X, Y] = pal[ch]
        images.append(img)
    out = Path(args.out)
    if len(images) == 1 and out.suffix.lower() != ".gif":
        images[0].save(out)
    else:
        if out.suffix.lower() != ".gif":
            out = out.with_suffix(".gif")
        durs = spec.get("durations_ms") or [round(1000 / float(spec.get("fps", 10)))] * len(images)
        images[0].save(out, save_all=True, append_images=images[1:], duration=durs,
                       loop=0, disposal=1, optimize=False)
    print(f"wrote {out} ({W}x{H}, {len(images)} frame{'s' if len(images) != 1 else ''})")
    return 0


def cmd_fit_image(args) -> int:
    _need_pil()
    from PIL import Image, ImageOps
    W, H = (int(v) for v in args.size.lower().split("x"))
    src = Image.open(args.input)
    resample = Image.NEAREST if args.nearest else Image.LANCZOS
    n = getattr(src, "n_frames", 1)
    frames, durs = [], []
    for i in range(n):
        src.seek(i)
        f = src.convert("RGB")
        if args.mode == "stretch":
            f = f.resize((W, H), resample)
        elif args.mode == "cover":
            f = ImageOps.fit(f, (W, H), method=resample)
        else:  # contain
            f = ImageOps.pad(f, (W, H), method=resample, color=(0, 0, 0))
        if args.colors:
            f = f.quantize(colors=args.colors).convert("RGB")
        frames.append(f)
        durs.append(src.info.get("duration", 100))
    out = Path(args.out)
    if n > 1 or out.suffix.lower() == ".gif":
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=durs, loop=0)
    else:
        frames[0].save(out)
    print(f"wrote {out} ({W}x{H}, {n} frame{'s' if n != 1 else ''}, mode={args.mode})")
    return 0


def cmd_preview(args) -> int:
    """Upscale an image (each light becomes a block) so it can be eyeballed; GIFs -> contact sheet."""
    _need_pil()
    from PIL import Image, ImageDraw
    src = Image.open(args.input)
    n = getattr(src, "n_frames", 1)
    s = args.scale
    tiles = []
    for i in range(min(n, args.max_frames)):
        src.seek(i)
        f = src.convert("RGB")
        big = f.resize((f.width * s, f.height * s), Image.NEAREST)
        if s >= 4:
            d = ImageDraw.Draw(big)
            for x in range(0, big.width, s):
                d.line([(x, 0), (x, big.height)], fill=(40, 40, 40))
            for y in range(0, big.height, s):
                d.line([(0, y), (big.width, y)], fill=(40, 40, 40))
        tiles.append(big)
    cols = min(len(tiles), args.columns)
    rows = (len(tiles) + cols - 1) // cols
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * (tw + 4) + 4, rows * (th + 4) + 4), (90, 90, 90))
    for i, t in enumerate(tiles):
        sheet.paste(t, (4 + (i % cols) * (tw + 4), 4 + (i // cols) * (th + 4)))
    sheet.save(args.out)
    print(f"wrote {args.out} ({len(tiles)} of {n} frame(s), {src.width}x{src.height} lights at x{s})")
    return 0


def _picture_options(kind: str, file_ref: str) -> tuple[str, bool]:
    learned = load_templates().get(kind)
    if learned and "{file}" in learned.get("options", ""):
        return learned["options"].replace("{file}", file_ref), True
    t = PICTURE_TEMPLATES[kind]
    return t["options"].replace("{file}", file_ref), t["verified"]


def embed_picture(doc: LorDoc, image: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", image.stem).strip("_") or "image"
    name = f"*{stem}*{uuid.uuid4()}*{image.suffix.lower()}"
    pics = doc.section("pictures", create=True)
    el = etree.Element("picture")
    el.set("name", name)
    el.text = base64.b64encode(image.read_bytes()).decode("ascii")
    doc.insert(pics, len(pics), el)
    return name


def cmd_add_picture_effect(args) -> int:
    doc = LorDoc(args.file)
    image = Path(args.image)
    if not image.is_file():
        raise LorError(f"image not found: {image}")
    if image.suffix.lower() not in (".png", ".gif", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
        raise LorError("LOR Picture effects take PNG, GIF, JPG, BMP or TIFF")
    sp = doc.find_seq_prop(args.prop)
    pc = doc.preview_props().get(sp.get("id"))
    notes = []
    if doc.kind_of(sp) not in ("pixel", "group", "unknown"):
        raise LorError(f"{sp.get('name')} is a {doc.kind_of(sp)} prop; picture effects need a pixel prop or group")
    # size check
    try:
        from PIL import Image
        with Image.open(image) as im:
            iw, ih = im.size
            frames = getattr(im, "n_frames", 1)
        target = None
        if args.size:
            target = tuple(int(v) for v in args.size.lower().split("x"))
        else:
            ms = matrix_size(pc)
            target = ms[:2] if ms else None
        if target and (iw, ih) != tuple(target):
            notes.append(f"note: image is {iw}x{ih}, prop is ~{target[0]}x{target[1]}; PictureXY 100/100 "
                         "stretches it to fit (use fit-image for exact 1:1 pixels)")
        notes.append(f"image: {iw}x{ih}, {frames} frame(s)")
    except ImportError:
        pass
    start = snap(doc, args.snap, parse_time(args.start))
    end = snap(doc, args.snap, parse_time(args.end))
    track, note = get_track(doc, sp, args.row, args.new_row)
    if note:
        notes.append(note)
    if args.external:
        # Percent-encode so ':' ',' '|' ';' in a Windows path can't break the settings string.
        ref = urllib.parse.quote(args.external_path or str(image.resolve()), safe="")
        notes.append("external file reference (experimental): the image must exist at that path on the "
                     "show computer; embedding (the default) is safer")
    else:
        ref = None  # set after embedding, but only once all checks pass
    # Build the settings with a placeholder first so overlap checks happen before we embed.
    probe = new_effect(start, end, "", level_attrs(args.intensity, args.start_intensity, args.end_intensity))
    clash = [x for x in effects_in(track) if span(x)[0] < end and start < span(x)[1]]
    if clash and args.on_overlap != "replace":
        place_effect(doc, track, probe, args.on_overlap, f"{sp.get('name')}/{track.get('name')}")  # raises
    if ref is None:
        ref = embed_picture(doc, image)
        notes.append(f"embedded image as {ref}")
    options, verified = _picture_options(args.effect, ref)
    mix = load_templates().get(args.effect, {}).get("mix") or MIX_ONE_SIDED
    side = f"lightorama_{args.effect}:{palette(None)}:{options}"
    settings = f"{mix}|{side}|{NONE_SIDE}"
    probe.set("settings", settings)
    notes += place_effect(doc, track, probe, args.on_overlap, f"{sp.get('name')}/{track.get('name')}")
    if not verified:
        notes.append(f"UNVERIFIED {args.effect} option layout - open the sequence in S6 and check this effect "
                     "renders; if not, make one by hand and run learn-template")
    return _finish(doc, args, probe, notes)


def cmd_add_motion_effect(args) -> int:
    doc = LorDoc(args.file)
    sp = doc.find_seq_prop(args.prop)
    pc = doc.preview_props().get(sp.get("id"))
    if doc.kind_of(sp) not in ("pixel", "group", "unknown"):
        raise LorError(f"{sp.get('name')} is a {doc.kind_of(sp)} prop; use add-effect for channel props")
    learned = load_templates().get("presets", {})
    if args.preset:
        if args.preset in learned:
            name, options = learned[args.preset]["effect"], learned[args.preset]["options"]
        elif args.preset in PRESETS:
            name, options = PRESETS[args.preset]
        else:
            raise LorError(f"unknown preset {args.preset!r}; choose from {', '.join(sorted({**PRESETS, **learned}))}")
    else:
        if not (args.effect and args.options is not None):
            raise LorError("give --preset, or both --effect NAME and --options 'a,b,c'")
        name, options = args.effect.removeprefix("lightorama_"), args.options
    start = snap(doc, args.snap, parse_time(args.start))
    end = snap(doc, args.snap, parse_time(args.end))
    track, note = get_track(doc, sp, args.row, args.new_row)
    notes = [note] if note else []
    side = f"lightorama_{name}:{palette(args.colors or ['white'])}:{options}"
    eff = new_effect(start, end, f"{MIX_ONE_SIDED}|{side}|{NONE_SIDE}",
                     level_attrs(args.intensity, args.start_intensity, args.end_intensity))
    notes += place_effect(doc, track, eff, args.on_overlap, f"{sp.get('name')}/{track.get('name')}")
    return _finish(doc, args, eff, notes)


def cmd_add_effect(args) -> int:
    doc = LorDoc(args.file)
    pcs = doc.preview_props()
    start = snap(doc, args.snap, parse_time(args.start))
    end = snap(doc, args.snap, parse_time(args.end))
    notes, added = [], []
    for prop_name in args.prop:
        sp = doc.find_seq_prop(prop_name)
        pc = pcs.get(sp.get("id"))
        kind = prop_kind(pc)
        if kind == "pixel" or (pc is None and sp.findall("track")):
            raise LorError(f"{sp.get('name')} is a pixel prop or group: use add-motion-effect / add-picture-effect")
        n_ch = len(expected_channels(pc)) or len(sp.findall("channel"))
        idx = list(range(n_ch)) if args.channel is None else [int(i) for i in args.channel.split(",")]
        chans = ensure_channels(doc, sp, pc, only=set(idx))
        if not chans:
            raise LorError(f"{sp.get('name')} has no channels")
        for i in idx:
            if not 0 <= i < len(chans):
                raise LorError(f"{sp.get('name')} has channels 0..{len(chans) - 1}")
            ch = chans[i]
            settings = {"on": "INTENSITY", "fade": "INTENSITY", "shimmer": "SHIMMER", "twinkle": "TWINKLE"}[args.type]
            if kind == "dumb_rgb":
                c0 = parse_color(args.color or "white")
                c1 = parse_color(args.to_color) if args.to_color else c0
                a = args.start_intensity if args.start_intensity is not None else (args.intensity or 100)
                b = args.end_intensity if args.end_intensity is not None else (
                    a if args.type != "fade" or args.to_color else 0)
                if args.type == "twinkle":
                    settings = "SHIMMER"  # how S6 stores twinkles on dumb RGB (observed)
                v0, v1 = argb_signed(c0, a), argb_signed(c1, b)
                level = {"intensity": str(v0)} if v0 == v1 and settings == "INTENSITY" else \
                    {"startIntensity": str(v0), "endIntensity": str(v1)}
            else:
                if args.color or args.to_color:
                    notes.append(f"{sp.get('name')}: --color ignored (not an RGB prop)")
                if args.type == "fade":
                    a = 100 if args.start_intensity is None else args.start_intensity
                    b = 0 if args.end_intensity is None else args.end_intensity
                    level = level_attrs(None, a, b)
                elif args.type == "shimmer":
                    a = args.start_intensity if args.start_intensity is not None else (args.intensity or 100)
                    b = args.end_intensity if args.end_intensity is not None else a
                    level = {"startIntensity": str(a), "endIntensity": str(b)}
                else:
                    level = level_attrs(args.intensity, args.start_intensity, args.end_intensity)
            eff = new_effect(start, end, settings, level)
            notes += place_effect(doc, ch, eff, args.on_overlap, f"{sp.get('name')}/ch{i}")
            added.append(eff)
    return _finish(doc, args, added, notes)


def cmd_learn_template(args) -> int:
    doc = LorDoc(args.file)
    sp = doc.find_seq_prop(args.prop)
    track, _ = get_track(doc, sp, args.row, None)
    effs = effects_in(track)
    if not effs:
        raise LorError("that row has no effects")
    if args.at:
        t = parse_time(args.at)
        hits = [e for e in effs if span(e)[0] <= t < span(e)[1]]
        if not hits:
            raise LorError(f"no effect on that row at {fmt_time(t)}")
        eff = hits[0]
    else:
        eff = effs[0]
    settings = eff.get("settings") or ""
    print(f"effect {fmt_time(span(eff)[0])}-{fmt_time(span(eff)[1])} level="
          f"{ {k: v for k, v in eff.attrib.items() if 'ntensity' in k} }")
    print("settings:", settings)
    parts = settings.split("|")
    if len(parts) < 7:
        raise LorError("not a motion-effect settings string")
    side = parts[5] if not parts[5].startswith("lightorama_none") else parts[6]
    bits = side.split(":", 2)
    if len(bits) < 3:
        raise LorError(f"can't split side {side!r}")
    ename = bits[0].removeprefix("lightorama_")
    options = bits[2]
    templates = load_templates()
    templates.setdefault("_learned_from", {})
    if ename in ("picture", "picturexy"):
        opts = options.split(",")
        opts[0] = "{file}"
        templates[ename] = {"options": ",".join(opts), "mix": "|".join(parts[:5])}
        key = ename
    else:
        key = args.save_as or ename
        templates.setdefault("presets", {})[key] = {"effect": ename, "options": options}
    templates["_learned_from"][key] = {"file": doc.path.name, "AppVersion": doc.root.get("AppVersion"),
                                       "date": _dt.date.today().isoformat()}
    if args.dry_run:
        print(json.dumps(templates, indent=2))
        return 0
    TEMPLATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_FILE.write_text(json.dumps(templates, indent=2) + "\n", encoding="utf-8")
    print(f"saved template {key!r} to {TEMPLATES_FILE}")
    return 0


def _finish(doc: LorDoc, args, effects, notes) -> int:
    effs = effects if isinstance(effects, list) else [effects]
    for n in notes:
        print(n)
    for e in effs:
        print(("would add: " if args.dry_run else "added: ") + etree.tostring(e).decode().strip())
    backup = doc.save(dry_run=args.dry_run)
    if args.dry_run:
        print("dry run: nothing written")
    else:
        print(f"saved {doc.path}  (backup: {backup})")
    return 0


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lor_helper.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect", help="list props, rows, grids, pictures")
    s.add_argument("file", type=Path)
    s.add_argument("--json", action="store_true")
    s.add_argument("--summary", action="store_true", help="one line per prop (use on big shows)")
    s.add_argument("--filter", help="only props whose name contains this")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("timings", help="list timing grids or one grid's marks")
    s.add_argument("file", type=Path)
    s.add_argument("--grid")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_timings)

    s = sub.add_parser("validate", help="structural checks")
    s.add_argument("file", type=Path)
    s.add_argument("--max", type=int, default=40)
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("render-ascii", help="pixel-art JSON spec -> PNG/GIF")
    s.add_argument("spec")
    s.add_argument("out")
    s.set_defaults(fn=cmd_render_ascii)

    s = sub.add_parser("fit-image", help="resize an image/GIF to an exact matrix size")
    s.add_argument("input")
    s.add_argument("out")
    s.add_argument("--size", required=True, help="WxH, e.g. 32x50")
    s.add_argument("--mode", choices=["contain", "cover", "stretch"], default="contain")
    s.add_argument("--nearest", action="store_true", help="nearest-neighbour (keeps pixel art crisp)")
    s.add_argument("--colors", type=int, help="reduce to N colours (cleaner on lights)")
    s.set_defaults(fn=cmd_fit_image)

    s = sub.add_parser("preview", help="upscale an image so you can look at it")
    s.add_argument("input")
    s.add_argument("out")
    s.add_argument("--scale", type=int, default=12)
    s.add_argument("--columns", type=int, default=8)
    s.add_argument("--max-frames", type=int, default=32)
    s.set_defaults(fn=cmd_preview)

    def edit_common(s, times=True):
        s.add_argument("file", type=Path)
        if times:
            s.add_argument("--start", required=True, help="1234 | 12.34s | 1:02.5")
            s.add_argument("--end", required=True)
            s.add_argument("--snap", help="snap start/end to this timing grid")
        s.add_argument("--intensity", type=int, help="constant level 0-100 (default 100)")
        s.add_argument("--start-intensity", type=int)
        s.add_argument("--end-intensity", type=int)
        s.add_argument("--on-overlap", choices=["error", "replace"], default="error")
        s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("add-picture-effect", help="PNG/GIF onto a pixel prop motion row")
    edit_common(s)
    s.add_argument("--prop", required=True)
    s.add_argument("--image", required=True)
    s.add_argument("--row", help="motion row name or 1-based number (default: first row)")
    s.add_argument("--new-row", help="create a new motion row with this name")
    s.add_argument("--effect", choices=["picturexy", "picture"], default="picturexy")
    s.add_argument("--size", help="override prop size WxH for the size check")
    s.add_argument("--external", action="store_true", help="reference the file on disk instead of embedding")
    s.add_argument("--external-path", help="path as the show computer sees it (with --external)")
    s.set_defaults(fn=cmd_add_picture_effect)

    s = sub.add_parser("add-motion-effect", help="preset/raw motion effect onto a motion row")
    edit_common(s)
    s.add_argument("--prop", required=True)
    s.add_argument("--preset", help=", ".join(PRESETS))
    s.add_argument("--effect", help="raw LOR effect name (with --options)")
    s.add_argument("--options", help="raw comma-separated option string")
    s.add_argument("--colors", nargs="+", help="up to 5 colours")
    s.add_argument("--row")
    s.add_argument("--new-row")
    s.set_defaults(fn=cmd_add_motion_effect)

    s = sub.add_parser("add-effect", help="on/fade/shimmer/twinkle on channel props")
    edit_common(s)
    s.add_argument("--prop", required=True, action="append", help="repeat for several props")
    s.add_argument("--type", required=True, choices=["on", "fade", "shimmer", "twinkle"])
    s.add_argument("--channel", help="channel index(es), e.g. 0 or 0,2 (default: all)")
    s.add_argument("--color", help="dumb-RGB colour (name or #RRGGBB)")
    s.add_argument("--to-color", help="dumb-RGB colour to fade to")
    s.set_defaults(fn=cmd_add_effect)

    s = sub.add_parser("learn-template", help="save an existing effect's settings as a template")
    s.add_argument("file", type=Path)
    s.add_argument("--prop", required=True)
    s.add_argument("--row")
    s.add_argument("--at", help="time inside the effect (default: first effect on the row)")
    s.add_argument("--save-as", help="preset name for non-picture effects")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_learn_template)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except BrokenPipeError:  # output piped into head etc.
        return 0
    except LorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
