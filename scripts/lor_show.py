#!/usr/bin/env python3
"""lor_show.py: build a self-contained HTML viewer for an LOR S6 sequence, and take
snapshots of it so an agent can look at a show without S6.

    python lor_show.py build SEQ.loredit [--preview X.lorprev] [--audio song.mp3] --out show.html
    python lor_show.py snapshots show.html --times 0:05,0:12.5,30s --out frames/   (or --every 2s)
    python lor_show.py report SEQ.loredit         # which effects render exactly / approximately

How faithful it is:
  exact        channel effects (on, fade, shimmer, twinkle; dumb-RGB colours), timing,
               which props and motion rows are lit, intensity ramps, regions
  close        Picture/PictureXY (the embedded image, stretched to the prop), colour wash,
               countdown
  approximate  every other motion effect: a lookalike in the same colours and direction,
               not LOR's renderer
  fallback     unknown effects: a dim wash in the first palette colour (listed in the HUD)

S6's own playback stays the final check before anything goes on a real house.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import urllib.parse
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lor_layout as L  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "assets" / "viewer_template.html"

FIDELITY = {
    "colorwash": "close", "picture": "close", "picturexy": "close", "countdown": "close",
    "twinkle": "approx", "bars": "approx", "blendedbars": "approx", "meteors": "approx",
    "spirals": "approx", "straightlines": "approx", "ripple": "approx", "garland": "approx",
    "fireworks": "approx", "butterfly": "approx", "plasma": "approx", "fire": "approx",
    "singleblock": "approx", "curtain": "approx", "snowflakes": "approx", "pinwheel": "approx",
    "spinner": "approx", "marquee": "approx", "wave": "approx", "starfield": "approx",
    "text": "approx", "simpleshape": "approx", "spinfade": "approx", "movingshapes": "approx",
}
CHANNEL_CODES = {"INTENSITY": 0, "SHIMMER": 1, "TWINKLE": 2, "DMX_INTENSITY": 0}


def argb_rgb(v: int) -> list[int]:
    u = int(v) & 0xFFFFFFFF
    return [(u >> 16) & 255, (u >> 8) & 255, u & 255]


def parse_side(side: str):
    """'lightorama_name:palette:options' -> dict, or None for lightorama_none/empty."""
    if not side.startswith("lightorama_") or side.startswith("lightorama_none"):
        return None
    bits = side.split(":", 2)
    name = bits[0][len("lightorama_"):]
    pal = []
    if len(bits) > 1:
        for slot in bits[1].split(";"):
            c = slot.split(",")
            if len(c) == 2 and c[1] == "1" and len(c[0]) == 8:
                pal.append([int(c[0][2:4], 16), int(c[0][4:6], 16), int(c[0][6:8], 16)])
    opts = bits[2].split(",") if len(bits) > 2 else []
    return {"n": name, "pal": pal or [[255, 255, 255]], "opt": opts}


def _level(e, rgb=False):
    if e.get("intensity") is not None:
        a = b = int(e.get("intensity"))
    else:
        a, b = int(e.get("startIntensity", 100)), int(e.get("endIntensity", 100))
    return a, b


class Builder:
    def __init__(self, seq_path: Path, preview_path: Path | None):
        self.seq = etree.parse(str(seq_path), etree.XMLParser(huge_tree=True)).getroot()
        if self.seq.tag != "sequence":
            raise SystemExit("not a .loredit")
        preview = L.load_preview(preview_path) if preview_path else self.seq.find("PreviewClass")
        if preview is None:
            raise SystemExit("no preview: pass --preview")
        self.layout = L.build_layout(preview)
        self.prop_ids = list(self.layout["props"])
        self.pindex = {pid: i for i, pid in enumerate(self.prop_ids)}
        self.pictures = {p.get("name"): (p.text or "").strip() for p in self.seq.iterfind("pictures/picture")}
        self.used_pictures: dict[str, dict] = {}
        self.stats: dict[str, int] = {}
        self.warnings: list[str] = []

    # ---------------------------------------------------------------- targets
    def _target_nodes(self, sid):
        """(prop_index, node_index, u, v) for a SeqProp id (prop or group)."""
        lay = self.layout
        if sid in lay["props"]:
            pi = self.pindex[sid]
            return [(pi, k, nd[2], nd[3]) for k, nd in enumerate(lay["props"][sid].nodes)]
        if sid in lay["groups"]:
            g = lay["groups"][sid]
            members = L.flatten_group(lay, sid)
            arr = (g["arrangement"] or "None").lower()
            out = []
            M = max(len(members), 1)
            if arr == "preview":
                pts = [nd for m in members for nd in lay["props"][m].nodes]
                if not pts:
                    return []
                x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
                y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
            for mi, m in enumerate(members):
                pi = self.pindex[m]
                for k, nd in enumerate(lay["props"][m].nodes):
                    u, v = nd[2], nd[3]
                    if arr == "horizontal":
                        u = (mi + u) / M
                    elif arr == "vertical":
                        v = (M - 1 - mi + v) / M
                    elif arr == "preview":
                        u = (nd[0] - x0) / ((x1 - x0) or 1)
                        v = (nd[1] - y0) / ((y1 - y0) or 1)
                    out.append((pi, k, u, v))
            return out
        # a master prop's followers share its data
        return []

    def _region(self, track, nodes):
        """Indices into nodes + local u,v for a motion row's region."""
        if track.get("subx") is not None:
            x, y = float(track.get("subx", 0)), float(track.get("suby", 0))
            w, h = float(track.get("subw", 1)) or 1, float(track.get("subh", 1)) or 1
            sel, uu, vv = [], [], []
            for i, (_, _, u, v) in enumerate(nodes):
                top = 1 - v
                if x - 1e-6 <= u <= x + w + 1e-6 and y - 1e-6 <= top <= y + h + 1e-6:
                    sel.append(i)
                    uu.append(round((u - x) / w, 4))
                    vv.append(round((v - (1 - y - h)) / h, 4))
            return sel, uu, vv
        subc = track.get("subc") or track.get("subc2")
        if subc:
            pts = []
            for p in subc.split(";"):
                try:
                    a, b = p.split(",")
                    pts.append((float(a), 1 - float(b)))
                except ValueError:
                    pass
            sel, uu, vv = [], [], []
            n = len(pts)
            for j, (px, py) in enumerate(pts):
                best = min(range(len(nodes)), key=lambda i: (nodes[i][2] - px) ** 2 + (nodes[i][3] - py) ** 2,
                           default=None)
                if best is not None:
                    sel.append(best)
                    uu.append(round(j / max(n - 1, 1), 4))
                    vv.append(0.5)
            return sel, uu, vv
        return None, None, None

    def _picture(self, ref: str) -> str | None:
        name = urllib.parse.unquote(ref)
        if name in self.used_pictures:
            return name
        data = self.pictures.get(name)
        if data is None:
            self.warnings.append(f"picture {name!r} is not embedded (external file): drawn as a wash")
            return None
        frames, durs = [], []
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(base64.b64decode(data)))
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                f = im.convert("RGBA")
                if max(f.size) > 160:  # props are small; keep the file light
                    f.thumbnail((160, 160))
                buf = io.BytesIO()
                f.save(buf, "PNG")
                frames.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
                durs.append(im.info.get("duration", 100) or 100)
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"picture {name!r} could not be decoded: {exc}")
            return None
        self.used_pictures[name] = {"frames": frames, "durations": durs}
        return name

    # ---------------------------------------------------------------- build
    def build(self) -> dict:
        lay = self.layout
        props_out = []
        for pid in self.prop_ids:
            p = lay["props"][pid]
            props_out.append({"name": p.name, "kind": p.kind, "bulb": p.bulb,
                              "x": [nd[0] for nd in p.nodes], "y": [nd[1] for nd in p.nodes],
                              "back": [k for k, nd in enumerate(p.nodes) if len(nd) > 4]})
        channels, motion = [], []
        seqprops = self.seq.find("SequenceProps")
        for sp in (seqprops if seqprops is not None else []):
            sid = sp.get("id")
            # ---- channel effects
            chans = sp.findall("channel")
            if chans and sid in lay["props"]:
                p = lay["props"][sid]
                cmap = p.channels or [{"nodes": None, "color": [255, 255, 255]}]
                per_color = any(c.get("color") not in (None, "0") for c in chans) and len(cmap) > 1
                for ci, ch in enumerate(chans):
                    effs = [e for e in ch if e.tag == "effect"]
                    if not effs:
                        continue
                    try:
                        k = int(ch.get("color" if per_color else "col") or ci)
                    except ValueError:
                        k = ci
                    m = cmap[min(k, len(cmap) - 1)] if cmap else {"nodes": None, "color": None}
                    rgb = m["color"] is None
                    fx = []
                    for e in effs:
                        code = CHANNEL_CODES.get(e.get("settings") or "INTENSITY", 0)
                        a, b = _level(e)
                        s0, s1 = int(e.get("startCentisecond", 0)), int(e.get("endCentisecond", 0))
                        if rgb:
                            fx.append([s0, s1, code] + argb_rgb(a) + argb_rgb(b))
                        else:
                            fx.append([s0, s1, code, a, b])
                        self.stats["ch:" + (e.get("settings") or "?")] = self.stats.get("ch:" + (e.get("settings") or "?"), 0) + 1
                    fx.sort(key=lambda f: f[0])
                    channels.append({"p": self.pindex[sid], "nodes": m["nodes"], "color": m["color"], "fx": fx})
            # ---- motion rows
            tracks = [t for t in sp.findall("track") if any(e.tag == "effect" for e in t)]
            if not tracks:
                continue
            nodes = self._target_nodes(sid)
            if not nodes:
                self.warnings.append(f"{sp.get('name')}: motion effects on a prop/group not in the preview")
                continue
            tgt = {"name": sp.get("name"), "pi": [n[0] for n in nodes], "ni": [n[1] for n in nodes],
                   "u": [round(n[2], 4) for n in nodes], "v": [round(n[3], 4) for n in nodes], "tracks": []}
            for t in tracks:
                sel, uu, vv = self._region(t, nodes)
                fx = []
                for e in t:
                    if e.tag != "effect":
                        continue
                    parts = (e.get("settings") or "").split("|")
                    if len(parts) < 7:
                        continue
                    a, b = _level(e)
                    sides = []
                    for raw in parts[5:7]:
                        side = parse_side(raw)
                        if side:
                            self.stats[side["n"]] = self.stats.get(side["n"], 0) + 1
                            if side["n"] in ("picture", "picturexy") and side["opt"]:
                                side["img"] = self._picture(side["opt"][0])
                        sides.append(side)
                    fx.append({"s": int(e.get("startCentisecond", 0)), "e": int(e.get("endCentisecond", 0)),
                               "i0": a, "i1": b, "mix": parts[0], "L": sides[0], "R": sides[1]})
                fx.sort(key=lambda f: f["s"])
                tgt["tracks"].append({"name": t.get("name"), "sel": sel, "u": uu, "v": vv, "fx": fx})
            motion.append(tgt)
        timing = []
        for g in self.seq.iterfind("TimingGrids/TimingGridFree"):
            marks = [int(x.get("centisecond")) for x in g.iter("timing")]
            if marks:
                timing.append({"name": g.get("name"), "marks": marks})
        return {
            "meta": {"name": self.seq.get("musicTitle") or self.layout["name"], "total": int(self.seq.get("totalCentiseconds", 0)),
                     "preview": self.layout["name"], "bgSize": self.layout["background_size"] or [1600, 900],
                     "stats": self.stats, "fidelity": FIDELITY, "warnings": self.warnings[:50]},
            "props": props_out, "channels": channels, "motion": motion, "pictures": self.used_pictures,
            "timing": timing,
        }


def cmd_build(args):
    b = Builder(Path(args.sequence), Path(args.preview) if args.preview else None)
    show = b.build()
    html = TEMPLATE.read_text(encoding="utf-8")
    bg = b.layout["background"]
    if args.background:  # a house photo for layouts whose preview only points at a file on another PC
        from PIL import Image
        im = Image.open(args.background).convert("RGB")
        im.thumbnail((2000, 2000))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        bg = base64.b64encode(buf.getvalue()).decode()
        show["meta"]["bgSize"] = list(im.size)
    audio = ""
    if args.audio:
        ap = Path(args.audio)
        mime = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}.get(ap.suffix.lower(), "audio/mpeg")
        audio = f"data:{mime};base64," + base64.b64encode(ap.read_bytes()).decode()
    stem = Path(args.sequence).stem
    base_name = re.sub(r"[\s_-]*v\d+$", "", stem, flags=re.I) or stem     # "Song v3" -> "Song"
    show["meta"]["name"] = args.title or base_name
    show["meta"]["version"] = args.version or stem
    show["meta"]["sequenceFile"] = Path(args.sequence).name          # named in the viewer's "Send to assistant" message
    if args.audio:
        show["meta"]["audioFile"] = Path(args.audio).name
    show["meta"]["showKey"] = re.sub(r"[^A-Za-z0-9_-]+", "-", base_name).strip("-").lower()[:60] or "show"
    if args.scenes:   # [{"start": s, "end": s, "name": "..."}] - labels notes and the timeline
        show["meta"]["scenes"] = [{"start": float(x["start"]), "end": float(x["end"]), "name": str(x["name"])}
                                  for x in json.loads(Path(args.scenes).read_text(encoding="utf-8"))]
    payload = json.dumps(show, separators=(",", ":")).replace("<", "\\u003c")
    html = (html.replace("/*__SHOW__*/null", payload)
                .replace("__BG__", (("data:image/jpeg;base64," if args.background else "data:image/png;base64,") + bg) if bg else "")
                .replace("__AUDIO__", audio)
                .replace("__TITLE__", (show["meta"]["name"] or "LOR show").replace("<", "").replace("&", "and")))
    Path(args.out).write_text(html, encoding="utf-8")
    n_lights = sum(len(p["x"]) for p in show["props"])
    n_fx = sum(len(t["fx"]) for m in show["motion"] for t in m["tracks"]) + sum(len(c["fx"]) for c in show["channels"])
    print(f"wrote {args.out} ({Path(args.out).stat().st_size / 1e6:.1f} MB): {len(show['props'])} props, "
          f"{n_lights} lights, {n_fx} effects, audio={'yes' if audio else 'no'}")
    _print_fidelity(show["meta"]["stats"])
    for w in b.warnings[:10]:
        print("warning:", w)


def _print_fidelity(stats):
    rows = []
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
        if k.startswith("ch:"):
            rows.append(f"{k[3:]} x{v} (exact)")
        else:
            rows.append(f"{k} x{v} ({FIDELITY.get(k, 'fallback')})")
    print("effects:", ", ".join(rows) or "none")


def cmd_report(args):
    b = Builder(Path(args.sequence), Path(args.preview) if args.preview else None)
    show = b.build()
    _print_fidelity(show["meta"]["stats"])
    for w in b.warnings:
        print("warning:", w)


def cmd_storyboard(args):
    """Pure-Python check (no browser): one row per lit prop/group/row, time across, cell colour =
    what that row shows (channel colour x level, or the motion effect's palette x intensity).
    Section starts (from the 'Sections' timing grid) are drawn as white lines, beats as ticks."""
    from PIL import Image, ImageDraw
    b = Builder(Path(args.sequence), Path(args.preview) if args.preview else None)
    show = b.build()
    total = show["meta"]["total"] or 1
    rows = []   # (label, [(s, e, c0, c1)])  colours as (r,g,b) at start/end
    by_prop: dict[int, list] = {}
    for ch in show["channels"]:
        spans = by_prop.setdefault(ch["p"], [])
        for f in ch["fx"]:
            if ch["color"]:
                c = ch["color"]
                spans.append((f[0], f[1], [x * f[3] / 100 for x in c], [x * f[4] / 100 for x in c], f[2]))
            else:
                spans.append((f[0], f[1], f[3:6], f[6:9], f[2]))
    for pi, spans in by_prop.items():
        rows.append((show["props"][pi]["name"], spans))
    for tg in show["motion"]:
        for tr in tg["tracks"]:
            spans = []
            for f in tr["fx"]:
                side = f["L"] or f["R"]
                pal = side["pal"] if side else [[255, 255, 255]]
                avg = [sum(c[i] for c in pal) / len(pal) for i in range(3)]
                spans.append((f["s"], f["e"], [x * f["i0"] / 100 for x in avg], [x * f["i1"] / 100 for x in avg], side["n"] if side else "?"))
            rows.append((f"{tg['name']} / {tr['name']}", spans))
    if not rows:
        raise SystemExit("nothing is sequenced yet")
    W, rh, lw = args.width, max(4, min(14, 1800 // len(rows))), 260
    H = 40 + rh * len(rows) + 60
    img = Image.new("RGB", (lw + W + 10, H), (14, 16, 22))
    d = ImageDraw.Draw(img)
    X = lambda cs: lw + int(cs / total * W)  # noqa: E731
    for i, (label, spans) in enumerate(rows):
        y = 40 + i * rh
        if rh >= 8:
            d.text((4, y), label[:40], fill=(170, 176, 190))
        d.rectangle([lw, y, lw + W, y + rh - 2], fill=(24, 27, 36))
        for s0, s1, c0, c1, kind in spans:
            x0, x1 = X(s0), max(X(s0) + 1, X(s1))
            for x in range(x0, x1):
                t = (x - x0) / max(1, x1 - x0)
                c = tuple(int(min(255, c0[k] + (c1[k] - c0[k]) * t)) for k in range(3))
                d.line([(x, y), (x, y + rh - 2)], fill=c)
    grids = {g["name"]: g["marks"] for g in show["timing"]}
    for cs in grids.get("Beats", [])[::1]:
        d.line([(X(cs), 30), (X(cs), 36)], fill=(90, 96, 110))
    for cs in grids.get("Sections", []):
        d.line([(X(cs), 28), (X(cs), H - 50)], fill=(255, 255, 255))
    for sec in range(0, int(total / 100) + 1, 10):
        d.text((X(sec * 100) + 2, 12), f"{sec // 60}:{sec % 60:02d}", fill=(200, 200, 200))
    # lit share across time (how busy the yard is)
    pts = []
    for x in range(0, W, 2):
        cs = x / W * total
        n = sum(1 for _, spans in rows if any(s0 <= cs < s1 for s0, s1, *_ in spans))
        pts.append((lw + x, H - 10 - int(40 * n / len(rows))))
    d.line(pts, fill=(255, 201, 77), width=2)
    d.text((4, H - 40), "rows lit over time", fill=(255, 201, 77))
    img.save(args.out)
    print(f"wrote {args.out}: {len(rows)} rows x {total / 100:.1f}s (white lines = section starts)")


def _parse_t(s: str) -> float:
    s = s.strip().lower()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec.rstrip("s"))
    return float(s.rstrip("s"))


def _launch(pw, chrome=None):
    """Playwright's own Chromium if installed, else the system's Chrome or Edge (Windows always has Edge)."""
    flags = ["--autoplay-policy=no-user-gesture-required"]
    tries = []
    if chrome:
        tries.append({"executable_path": chrome})
    tries += [{}, {"channel": "chrome"}, {"channel": "msedge"}]
    if Path("/usr/bin/google-chrome").exists():
        tries.append({"executable_path": "/usr/bin/google-chrome"})
    last = None
    for kw in tries:
        try:
            return pw.chromium.launch(args=flags, **kw)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise SystemExit(f"no browser for snapshots ({last}). Run: python -m playwright install chromium")


def cmd_snapshots(args):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("snapshots need playwright: pip install playwright && python -m playwright install chromium")
    from PIL import Image, ImageDraw
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    url = Path(args.html).resolve().as_uri() + "?snap=1"
    shots = []
    with sync_playwright() as pw:
        browser = _launch(pw, args.chrome)
        page = browser.new_page(viewport={"width": args.width, "height": int(args.width * 0.75)})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function("window.SHOW_READY === true", timeout=60000)
        total = page.evaluate("SHOW.meta.total") / 100
        times = [_parse_t(t) for t in args.times.split(",")] if args.times else []
        if args.every:
            step = _parse_t(args.every)
            t = 0.0
            while t < total:
                times.append(round(t, 2))
                t += step
        for t in times:
            info = page.evaluate(f"window.renderAt({t})")
            path = out / f"frame_{t:07.2f}s.png"
            page.locator("#stage").screenshot(path=str(path))
            shots.append((t, path, info))
            print(f"{t:7.2f}s  lit={info['lit']:5.1%}  active={', '.join(info['active'][:6])}")
        browser.close()
    if errors:
        print("page errors:", errors[:5])
    if shots and args.sheet:
        thumbs = []
        for t, p, info in shots:
            im = Image.open(p).convert("RGB")
            im.thumbnail((480, 480))
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, im.width, 18], fill=(0, 0, 0))
            d.text((4, 3), f"{int(t // 60)}:{t % 60:05.2f}  lit {info['lit']:.0%}", fill=(255, 255, 255))
            thumbs.append(im)
        cols = min(args.columns, len(thumbs))
        rows = (len(thumbs) + cols - 1) // cols
        w, h = thumbs[0].size
        sheet = Image.new("RGB", (cols * w, rows * h), (30, 30, 30))
        for i, im in enumerate(thumbs):
            sheet.paste(im, ((i % cols) * w, (i // cols) * h))
        sp = out / "contact_sheet.png"
        sheet.save(sp)
        print(f"wrote {sp}")


def cmd_notes(args):
    """Print review notes (the viewer's Download JSON, or a list of note objects) as a work list."""
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    notes = data.get("notes", data) if isinstance(data, dict) else data
    if args.version:
        notes = [n for n in notes if n.get("version") == args.version]
    if not args.all:
        notes = [n for n in notes if n.get("status", "open") != "addressed"]
    notes.sort(key=lambda n: float(n.get("t", 0)))
    if not notes:
        print("no open notes")
        return
    for n in notes:
        t = float(n.get("t", 0))
        print(f"[{int(t // 60)}:{t % 60:05.2f}] {n.get('scene', '')}  ({n.get('version', '')})")
        print(f"   note: {n.get('text', '')}")
        if n.get("props"):
            print(f"   props: {', '.join(n['props'])}")
        if n.get("active") and args.active:
            print(f"   on screen: {'; '.join(n['active'][:12])}")
        print()
    print(f"{len(notes)} note(s). Fix each, then mark it addressed with a one-line reply (status/reply fields).")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build")
    s.add_argument("sequence")
    s.add_argument("--preview", help="use this .lorprev instead of the copy inside the sequence")
    s.add_argument("--audio")
    s.add_argument("--background", help="house photo, if the preview doesn't embed one (BackgroundFile points at the owner's PC)")
    s.add_argument("--out", required=True)
    s.add_argument("--version", help="label stored with review notes (default: the sequence file name)")
    s.add_argument("--title", help="title shown in the viewer (default: the sequence file name without a trailing v2/v3)")
    s.add_argument("--scenes", help='JSON list of {"start","end","name"} (seconds) to label scenes in the viewer and notes')
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser("report")
    s.add_argument("sequence")
    s.add_argument("--preview")
    s.set_defaults(fn=cmd_report)
    s = sub.add_parser("storyboard", help="no-browser check: rows x time image")
    s.add_argument("sequence")
    s.add_argument("--preview")
    s.add_argument("--out", default="storyboard.png")
    s.add_argument("--width", type=int, default=1400)
    s.set_defaults(fn=cmd_storyboard)
    s = sub.add_parser("snapshots")
    s.add_argument("html")
    s.add_argument("--times", help="comma list: 5, 12.5s, 1:02.5")
    s.add_argument("--every", help="e.g. 2s")
    s.add_argument("--out", default="frames")
    s.add_argument("--width", type=int, default=1200)
    s.add_argument("--columns", type=int, default=4)
    s.add_argument("--no-sheet", dest="sheet", action="store_false")
    s.add_argument("--chrome", help="path to a Chrome/Chromium binary")
    s.set_defaults(fn=cmd_snapshots)
    s = sub.add_parser("notes", help="list review notes exported from the viewer")
    s.add_argument("file")
    s.add_argument("--version", help="only notes left on this version")
    s.add_argument("--all", action="store_true", help="include notes already addressed")
    s.add_argument("--active", action="store_true", help="also show the effects that were on screen")
    s.set_defaults(fn=cmd_notes)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
