#!/usr/bin/env python3
"""lor_layout.py: turn an LOR S6 preview (.lorprev, or the copy embedded in a .loredit)
into lights with positions, for the HTML viewer and for planning.

Coordinates (verified by drawing two LOR compact layouts over their own background
photos):
  * Preview space runs from -1 to 1 on both axes, with y pointing UP. It maps onto
    the background image as px = (x+1)/2*W, py = (1-y)/2*H.
  * A shape with OffsetX/OffsetY/ScaleX/ScaleY/Radians has a local box from -1 to 1;
    the Offset is its centre and the Scale is HALF its width/height.
  * Point shapes (Lines-*, Matrix-*-Quad, Advanced, Bulbs) list their points in
    preview space directly.

Every light ("node") gets:
  x, y  position in preview space (where it is drawn)
  u, v  position in the prop's effect buffer, 0..1 with v=0 at the bottom (what a
        motion effect samples). Grid shapes (matrix, tree) use strand/node indices,
        so effects wrap correctly; other shapes use their position inside the
        prop's bounding box.

Node layouts for each shape are approximations of LOR's own drawing, close enough to
judge a show, but not a pixel-exact copy of S6's preview.

    python lor_layout.py inspect file.lorprev|file.loredit
    python lor_layout.py draw file.lorprev out.png      # lights drawn over the photo
"""
from __future__ import annotations

import base64
import io
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

COLOR_NAMES = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 230),
    "warm white": (255, 200, 120), "warmwhite": (255, 200, 120), "yellow": (255, 230, 0),
    "orange": (255, 120, 0), "purple": (160, 0, 255), "pink": (255, 80, 160), "multi": (255, 255, 255),
    "gold": (255, 180, 0), "aqua": (0, 255, 255), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
}
MAX_DRAWN_NODES = 600
# LOR's tree box reaches above the apex: in the LOR compact layouts the tree's own star
# topper sits ~20% below the box top, so strands run from y=-1 up to y=+0.6.
TREE_APEX_SPAN = 1.6   # per prop; huge custom props are thinned for drawing only


@dataclass
class Prop:
    id: str
    name: str
    kind: str                 # pixel | dumb_rgb | traditional
    shape: str
    nodes: list               # [x, y, u, v]
    channels: list = field(default_factory=list)   # [{"nodes": [...]|None, "color": [r,g,b]|None}]
    bulb: float = 2.0
    note: str = ""


# --------------------------------------------------------------------------- helpers
def _f(el, name, default=0.0):
    try:
        return float(el.get(name, default))
    except (TypeError, ValueError):
        return default


def _parms(pc) -> list[int]:
    out = []
    for i in range(1, 12):
        v = pc.get(f"Parm{i}")
        if v is None:
            break
        try:
            out.append(int(float(v)))
        except ValueError:
            out.append(0)
    return out


def _grid_entries(pc) -> list[list[str]]:
    grid = pc.get("ChannelGrid") or ""
    return [part.split(",") for part in grid.split(";") if part.strip()]


def _pixel_count(pc) -> int:
    total = 0
    for bits in _grid_entries(pc):
        if len(bits) >= 4:
            try:
                total += (int(bits[3]) - int(bits[2]) + 1) // 3
            except ValueError:
                pass
    return total


def _entry_color(bits, pc) -> tuple[int, int, int]:
    name = (bits[5] if len(bits) > 5 else "").strip().lower()
    if name in COLOR_NAMES:
        return COLOR_NAMES[name]
    c = pc.get("CustomBulbColor") or "FFFFFFFF"
    try:
        return int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16)
    except ValueError:
        return 255, 255, 255


def kind_of(pc) -> str:
    st = pc.get("StringType") or ""
    if st == "RGB":
        return "pixel"
    if st == "DumbRGB":
        return "dumb_rgb"
    return "traditional"


class Box:
    """Local [-1,1]^2 -> preview space for offset/scale shapes."""

    def __init__(self, sh):
        self.ox, self.oy = _f(sh, "OffsetX"), _f(sh, "OffsetY")
        self.sx, self.sy = _f(sh, "ScaleX", 0.1), _f(sh, "ScaleY", 0.1)
        self.r = _f(sh, "Radians")

    def __call__(self, lx, ly):
        x, y = lx * self.sx, ly * self.sy
        if self.r:
            c, s = math.cos(self.r), math.sin(self.r)
            x, y = x * c - y * s, x * s + y * c
        return self.ox + x, self.oy + y


def _along(points, n, closed=False):
    """n points evenly spaced along a polyline."""
    pts = list(points) + ([points[0]] if closed and points else [])
    if len(pts) < 2 or n <= 0:
        return [pts[0]] * max(n, 0) if pts else []
    seg = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    total = sum(seg) or 1
    out = []
    for i in range(n):
        d = total * (i / (n - 1) if n > 1 and not closed else i / n)
        for (a, b), L in zip(zip(pts, pts[1:]), seg):
            if d <= L or (a, b) == (pts[-2], pts[-1]):
                t = 0 if L == 0 else min(1, d / L)
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
            d -= L
    return out


def _bbox_uv(nodes):
    xs = [n[0] for n in nodes]
    ys = [n[1] for n in nodes]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = (x1 - x0) or 1, (y1 - y0) or 1
    return [[x, y, (x - x0) / w, (y - y0) / h] for x, y in nodes]


def _grid(strands, length, place):
    """place(u, v) -> (x, y); returns nodes strand-major, v=0 at bottom."""
    out = []
    for i in range(strands):
        u = i / (strands - 1) if strands > 1 else 0.5
        for j in range(length):
            v = j / (length - 1) if length > 1 else 0.5
            x, y = place(u, v)
            out.append([x, y, u, v])
    return out


# --------------------------------------------------------------------------- shapes
def layout_prop(pc) -> Prop:
    sh = pc.find("shape")
    shape = sh.get("ShapeName", "") if sh is not None else ""
    kind = kind_of(pc)
    parms = _parms(pc)
    pts = [(_f(p, "x"), _f(p, "y")) for p in sh.findall("point")] if sh is not None else []
    has_box = sh is not None and sh.get("OffsetX") is not None
    box = Box(sh) if has_box else None
    px = _pixel_count(pc) if kind == "pixel" else 0
    n_default = px or (parms[1] if len(parms) > 1 and parms[1] > 0 else 50)
    s = shape.lower()
    nodes: list = []
    note = ""

    if s.startswith("matrix") or s.startswith("tree"):
        strings = max(parms[0] if parms else 1, 1)
        per_string = parms[1] if len(parms) > 1 and parms[1] > 0 else 50
        folds = parms[2] if len(parms) > 2 and s.startswith("matrix") else 0
        if s.startswith("tree 360 wedges") and len(parms) > 2:
            folds = parms[2]
        strands, length = strings * (folds + 1), max(per_string // (folds + 1), 1)
        if s.startswith("matrix"):
            vertical = "horizontal" not in s
            if len(pts) >= 4:  # quad corners TL, TR, BR, BL
                tl, tr, br, bl = pts[:4]

                def quad(a, b):  # a across 0..1 (left->right), b up 0..1 (bottom->top)
                    top = (tl[0] + (tr[0] - tl[0]) * a, tl[1] + (tr[1] - tl[1]) * a)
                    bot = (bl[0] + (br[0] - bl[0]) * a, bl[1] + (br[1] - bl[1]) * a)
                    return bot[0] + (top[0] - bot[0]) * b, bot[1] + (top[1] - bot[1]) * b
                place = quad
            elif box:
                place = lambda a, b: box(-1 + 2 * a, -1 + 2 * b)  # noqa: E731
            else:
                place = lambda a, b: (a, b)  # noqa: E731
            if vertical:
                nodes = _grid(strands, length, place)
            else:
                nodes = [[*place(v, u), v, u] for (_, _, u, v) in _grid(strands, length, lambda a, b: (0, 0))]
        elif s.startswith("tree 360 spiral"):
            n = n_default if kind == "pixel" else min(parms[1] if len(parms) > 1 else 120, 240)
            turns = 3.0
            for k in range(n):
                v = k / max(n - 1, 1)
                a = 2 * math.pi * turns * v
                r = 1 - v
                x, y = box(math.sin(a) * r, -1 + 2 * v) if box else (0, 0)
                nodes.append([x, y, (a / (2 * math.pi)) % 1, v])
        else:  # Tree 180 / Tree 360 wedges: strands fan from the base up to the apex
            full = "360" in s
            for i in range(strands):
                if full:
                    ang = 2 * math.pi * i / strands
                    bx, depth = math.sin(ang), math.cos(ang)
                    u = i / strands
                else:
                    bx, depth = -1 + 2 * i / max(strands - 1, 1), 1
                    u = i / max(strands - 1, 1)
                for j in range(length):
                    v = j / max(length - 1, 1)
                    lx, ly = bx * (1 - v * 0.97), -1 + TREE_APEX_SPAN * v
                    x, y = box(lx, ly) if box else (lx, ly)
                    nodes.append([x, y, u, v] + ([0] if full and depth < -0.05 else []))
            if full:
                note = "360 tree: back strands flagged (drawn dim)"
    elif s == "star":
        n = n_default
        points = parms[2] if len(parms) > 2 and parms[2] >= 3 else 5
        verts = []
        for k in range(points * 2):
            r = 1.0 if k % 2 == 0 else 0.42
            a = math.pi / 2 + math.pi * k / points
            verts.append(box(r * math.cos(a), r * math.sin(a)) if box else (r * math.cos(a), r * math.sin(a)))
        nodes = _bbox_uv(_along(verts, n, closed=True))
    elif s == "arch":
        n = n_default
        raw = []
        for k in range(n):
            t = math.pi * (1 - k / max(n - 1, 1))
            raw.append(box(math.cos(t), -1 + 2 * math.sin(t)) if box else (math.cos(t), math.sin(t)))
        nodes = [[x, y, k / max(n - 1, 1), 0.5] for k, (x, y) in enumerate(raw)]
    elif s == "firestick" or s.startswith("line") and box and not pts:
        n = n_default
        nodes = [[*box(0, -1 + 2 * k / max(n - 1, 1)), 0.5, k / max(n - 1, 1)] for k in range(n)] if box else []
    elif s == "sphere":
        n = min(n_default if kind == "pixel" else (parms[1] if len(parms) > 1 else 80), 300)
        ga = math.pi * (3 - math.sqrt(5))
        raw = [(math.sqrt((k + 0.5) / n) * math.cos(k * ga), math.sqrt((k + 0.5) / n) * math.sin(k * ga)) for k in range(n)]
        nodes = _bbox_uv([box(a, b) if box else (a, b) for a, b in raw])
    elif s in ("advanced", "custom"):
        grid = sh.get("CustomGrid") or ""
        W, H = int(_f(sh, "CustomWidth", 1)), int(_f(sh, "CustomHeight", 1))
        cells: dict[int, tuple[int, int]] = {}
        for r, row in enumerate(grid.split(";")):
            for c, val in enumerate(row.split(",")):
                if val not in ("", "0"):
                    try:
                        cells.setdefault(int(val), (c, r))
                    except ValueError:
                        pass
        order = sorted(cells)
        if s == "advanced" and pts:
            # points are the bulbs in node order; buffer position from the grid
            for k, (x, y) in enumerate(pts):
                c, r = cells[order[k]] if k < len(order) else (k % max(W, 1), k // max(W, 1))
                nodes.append([x, y, c / max(W - 1, 1), 1 - r / max(H - 1, 1)])
        else:
            for nnum in order:
                c, r = cells[nnum]
                lx, ly = -1 + 2 * (c + 0.5) / max(W, 1), 1 - 2 * (r + 0.5) / max(H, 1)
                x, y = box(lx, ly) if box else (lx, ly)
                nodes.append([x, y, c / max(W - 1, 1), 1 - r / max(H - 1, 1)])
    elif pts:
        n = n_default if kind == "pixel" else min(16 * max(len(pts) - 1, 1), 100)  # non-pixel: bulbs are cosmetic
        if s == "bulbs" or len(pts) == 1:
            raw = pts
        elif s == "lines-unconnected":
            pairs = list(zip(pts[0::2], pts[1::2]))
            per = max(n // max(len(pairs), 1), 2)
            raw = [q for a, b in pairs for q in _along([a, b], per)]
        else:
            raw = _along(pts, n)
        nodes = [[x, y, k / max(len(raw) - 1, 1), 0.5] for k, (x, y) in enumerate(raw)]
        if s not in ("lines-connected", "lines-unconnected", "bulbs"):
            note = f"unknown shape {shape!r}: drawn along its points"
    elif box:
        nodes = _grid(5, 5, lambda a, b: box(-1 + 2 * a, -1 + 2 * b))
        note = f"unknown shape {shape!r}: drawn as a box"

    prop = Prop(id=pc.get("id"), name=pc.get("Name") or pc.get("id"), kind=kind, shape=shape,
                nodes=[[round(c, 5) for c in nd] for nd in nodes], bulb=_f(pc, "PreviewBulbSize", 2), note=note)
    prop.channels = channel_map(pc, kind, len(prop.nodes))
    return prop


def channel_map(pc, kind, n_nodes) -> list[dict]:
    """Which nodes each sequence channel lights, and in what colour (None = RGB value)."""
    if kind == "pixel":
        return []
    entries = _grid_entries(pc)
    if kind == "dumb_rgb":
        return [{"nodes": None, "color": None}]
    if len(entries) <= 1:
        return [{"nodes": None, "color": list(_entry_color(entries[0] if entries else [], pc))}]
    per_color = (pc.get("TraditionalType") == "Channel_per_color" or
                 len({(e[5] if len(e) > 5 else "") for e in entries}) == len(entries))
    out = []
    k = len(entries)
    for i, bits in enumerate(entries):
        if per_color:   # interleaved bulbs, one colour per channel (multi-colour strings, bushes)
            idx = list(range(i, n_nodes, k))
        else:           # contiguous sections (curtain strands, segments)
            idx = list(range(i * n_nodes // k, (i + 1) * n_nodes // k))
        out.append({"nodes": idx, "color": list(_entry_color(bits, pc))})
    return out


# --------------------------------------------------------------------------- whole preview
def load_preview(path: Path):
    root = etree.parse(str(path), etree.XMLParser(huge_tree=True)).getroot()
    if root.tag == "sequence":
        root = root.find("PreviewClass")
        if root is None:
            raise SystemExit("this .loredit has no embedded PreviewClass")
    if root.tag != "PreviewClass":
        raise SystemExit(f"unexpected root <{root.tag}>")
    return root


def build_layout(preview) -> dict:
    props = {}
    for pc in preview.iter("PropClass"):
        if pc.get("id"):
            props[pc.get("id")] = layout_prop(pc)
    groups = {}
    for g in preview.iter("PropGroup"):
        groups[g.get("id")] = {"name": g.get("Name"), "arrangement": g.get("Arrangement") or "None",
                               "members": [m.get("id") for m in g.findall("member")]}
    masters = {pc.get("id"): pc.get("MasterPropId") for pc in preview.iter("PropClass") if pc.get("MasterPropId")}
    bg = preview.find("BackgroundImage")
    bg_size = None
    if bg is not None and (bg.text or "").strip():
        try:
            from PIL import Image
            bg_size = Image.open(io.BytesIO(base64.b64decode(bg.text))).size
        except Exception:  # noqa: BLE001
            bg_size = None
    return {"name": preview.get("Name"), "props": props, "groups": groups, "masters": masters,
            "background": bg.text.strip() if bg is not None and bg.text else None, "background_size": bg_size}


def flatten_group(layout, gid, seen=None) -> list[str]:
    seen = seen or set()
    out = []
    for m in layout["groups"].get(gid, {}).get("members", []):
        if m in seen:
            continue
        seen.add(m)
        if m in layout["groups"]:
            out += flatten_group(layout, m, seen)
        elif m in layout["props"]:
            out.append(m)
    return out


# --------------------------------------------------------------------------- CLI
def _draw(path: Path, out: Path):
    from PIL import Image, ImageDraw
    lay = build_layout(load_preview(path))
    if lay["background"]:
        img = Image.open(io.BytesIO(base64.b64decode(lay["background"]))).convert("RGB")
        img = Image.eval(img, lambda c: int(c * 0.35))
    else:
        img = Image.new("RGB", (1600, 900), (10, 10, 20))
    W, H = img.size
    d = ImageDraw.Draw(img)
    palette = {"pixel": (0, 255, 255), "dumb_rgb": (255, 0, 255), "traditional": (255, 220, 60)}
    for p in lay["props"].values():
        col = palette[p.kind]
        step = max(1, len(p.nodes) // MAX_DRAWN_NODES)
        for nd in p.nodes[::step]:
            x, y = (nd[0] + 1) / 2 * W, (1 - nd[1]) / 2 * H
            r = 1.6 if len(nd) < 5 else 1.0
            d.ellipse([x - r, y - r, x + r, y + r], fill=col if len(nd) < 5 else tuple(c // 3 for c in col))
    img.save(out)
    print(f"wrote {out}: {len(lay['props'])} props, {sum(len(p.nodes) for p in lay['props'].values())} lights "
          "(cyan=pixel, magenta=dumb RGB, yellow=traditional)")


def _inspect(path: Path):
    lay = build_layout(load_preview(path))
    by = {}
    for p in lay["props"].values():
        by.setdefault((p.kind, p.shape), []).append(p)
    print(f"{lay['name']}: {len(lay['props'])} props, {len(lay['groups'])} groups, background={lay['background_size']}")
    for (k, s), ps in sorted(by.items()):
        n = sum(len(p.nodes) for p in ps)
        notes = {p.note for p in ps if p.note}
        print(f"  {k:12} {s:28} props={len(ps):3} lights={n:6}  e.g. {ps[0].name}" + (f"  [{'; '.join(notes)}]" if notes else ""))


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("inspect", "draw", "json"):
        sys.exit(__doc__)
    cmd, src = sys.argv[1], Path(sys.argv[2])
    if cmd == "inspect":
        _inspect(src)
    elif cmd == "draw":
        _draw(src, Path(sys.argv[3] if len(sys.argv) > 3 else "layout.png"))
    else:
        lay = build_layout(load_preview(src))
        lay["props"] = {k: v.__dict__ for k, v in lay["props"].items()}
        lay["background"] = bool(lay["background"])
        print(json.dumps(lay)[:2000])
