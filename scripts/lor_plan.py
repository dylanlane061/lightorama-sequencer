#!/usr/bin/env python3
"""lor_plan.py: turn a readable show plan (JSON) into an S6 sequence.

    python lor_plan.py targets BASE.loredit                    # what you can aim cues at
    python lor_plan.py draft BASE.loredit --analysis song.analysis.json --out plan.json [--palette red,green,white,gold]
    python lor_plan.py compile plan.json --base BASE.loredit --out "My Song.loredit"

BASE is an empty sequence for the layout (lor_new.py) with the song's timing grids
(lor_audio.py --write-grids). compile never edits BASE: it copies it to --out, then adds
every effect in one pass with the same checks lor_helper uses.

PLAN FORMAT (see references/plan_format.md for the full reference)
{
  "title": "Carol of the Bells",
  "analysis": "song.analysis.json",          # beats/bars/accents come from here
  "palettes": {"main": ["red", "white"], "accent": ["gold"]},
  "aliases":  {"windows": ["*Window*"], "trees": ["RGB Tree*"], "arches": ["LOR Group-RGB Arches"]},
  "defaults": {"on_overlap": "skip"},
  "sections": [
    {"start": "0:00", "end": "0:15.3", "label": "intro",
     "cues": [
       {"targets": "windows", "type": "fade", "from": 0, "to": 100},
       {"targets": "arches", "preset": "wash", "colors": "main", "intensity": [0, 100]},
       {"targets": "mini_trees", "type": "pulse", "rhythm": "chase", "every": "beat", "order": "left_to_right"},
       {"targets": "matrix", "picture": "art/snowman.gif"}
     ]}
  ],
  "accents": [{"targets": "rooflines", "type": "pulse", "colors": "accent", "min_strength": 0.9, "length": 0.3}]
}

Cue keys
  targets   alias, prop/group name, or glob ("*Arch*"); a list mixes them
  type      channel look for traditional / dumb-RGB props: on | fade | pulse | shimmer | twinkle
  preset    motion look for pixel props and groups (lor_helper presets, e.g. wash, bars, spiral_left)
  picture   image or GIF for pixel props / groups (PictureXY, embedded)
            A cue can give both type and preset: each target gets the one that fits it.
            Give only one and the other is derived (preset -> on in colours[0];
            type -> wash).
  colors    palette name or list (dumb RGB uses colors[0], cycling per step; motion uses all)
  intensity number or [from, to]; from/to for fades (channel)
  rhythm    hold (default: one effect for the whole span) | pulse | chase | alternate | random
  every     beat | bar | half (2 beats) | 2bars | <seconds>s   (for non-hold rhythms)
  length    fraction of each step that is lit (default 0.85) or "<sec>s"
  order     file | left_to_right | right_to_left | bottom_to_top | top_to_bottom (chase order)
  row       motion row name for pixel targets (default: first free whole-prop row)
  start/end override the section times for this cue
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import random
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lor_helper as H  # noqa: E402
import lor_layout as L  # noqa: E402

PALETTES = {
    "classic": ["red", "green", "white", "gold"],
    "candy": ["red", "white"],
    "icy": ["ice blue", "white", "blue"],
    "warm": ["warm white", "gold", "orange"],
    "patriotic": ["red", "white", "blue"],
    "halloween": ["orange", "purple", "green"],
    "party": ["magenta", "cyan", "gold", "blue"],
}
FACE_WORDS = ("face", "mouth", "eyes", "singing")


def t_of(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().lower()
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec.rstrip("s"))
    return float(s.rstrip("s"))


# --------------------------------------------------------------------------- targets
class Show:
    def __init__(self, path: Path):
        self.doc = H.LorDoc(path)
        self.seq_props = self.doc.seq_props()
        pcs = self.doc.preview_props()
        groups = self.doc.preview_groups()
        preview = self.doc.root.find("PreviewClass")
        self.layout = L.build_layout(preview) if preview is not None else {"props": {}, "groups": {}}
        self.info = {}
        for sp in self.seq_props:
            sid = sp.get("id")
            kind = self.doc.kind_of(sp)
            if sid in self.layout["props"]:
                nodes = self.layout["props"][sid].nodes
                shape = self.layout["props"][sid].shape
            elif sid in self.layout.get("groups", {}):
                members = L.flatten_group(self.layout, sid)
                nodes = [nd for m in members for nd in self.layout["props"][m].nodes]
                shape = "group"
            else:
                nodes, shape = [], ""
            cx = sum(n[0] for n in nodes) / len(nodes) if nodes else 0
            cy = sum(n[1] for n in nodes) / len(nodes) if nodes else 0
            rows = [t for t in sp.findall("track")]
            channel_kind = kind in ("traditional", "dumb_rgb")
            self.info[sid] = {"sp": sp, "name": sp.get("name") or "", "kind": kind, "shape": shape,
                              "x": cx, "y": cy, "lights": len(nodes), "motion": bool(rows) and not channel_kind,
                              "rows": len(rows),
                              "channel": channel_kind, "pc": pcs.get(sid),
                              "face": any(w in (sp.get("name") or "").lower() for w in FACE_WORDS)}
        self.order = [sp.get("id") for sp in self.seq_props]

    def resolve(self, spec, aliases, seen=None) -> list[str]:
        seen = seen or set()
        items = spec if isinstance(spec, list) else [spec]
        out: list[str] = []
        for it in items:
            it = str(it)
            if it in aliases and it not in seen:
                out += self.resolve(aliases[it], aliases, seen | {it})
                continue
            exact = [sid for sid in self.order if self.info[sid]["name"] == it]
            hits = exact or [sid for sid in self.order if fnmatch.fnmatch(self.info[sid]["name"].lower(), it.lower())]
            if not hits:
                raise H.LorError(f"target {it!r} matches nothing (run `lor_plan.py targets` to see names)")
            out += hits
        seen_ids, uniq = set(), []
        for sid in out:
            if sid not in seen_ids:
                seen_ids.add(sid)
                uniq.append(sid)
        return uniq

    def ordered(self, ids, how):
        how = (how or "file").lower()
        key = {"left_to_right": lambda s: self.info[s]["x"], "right_to_left": lambda s: -self.info[s]["x"],
               "bottom_to_top": lambda s: self.info[s]["y"], "top_to_bottom": lambda s: -self.info[s]["y"]}.get(how)
        return sorted(ids, key=key) if key else list(ids)


# --------------------------------------------------------------------------- compile
class Compiler:
    def __init__(self, show: Show, plan: dict, plan_dir: Path):
        self.s, self.plan, self.dir = show, plan, plan_dir
        self.aliases = plan.get("aliases", {})
        self.palettes = {**PALETTES, **plan.get("palettes", {})}
        self.defaults = {"on_overlap": "skip", "length": 0.85, **plan.get("defaults", {})}
        self.analysis = {}
        if plan.get("analysis"):
            ap = (plan_dir / plan["analysis"]) if not Path(plan["analysis"]).is_absolute() else Path(plan["analysis"])
            self.analysis = json.loads(ap.read_text(encoding="utf-8"))
        self.warnings: list[str] = []
        self.count = 0
        self.rng = random.Random(7)
        self.pictures: dict[str, str] = {}

    def colors(self, spec):
        if spec is None:
            return list(self.palettes.get("main", PALETTES["classic"]))
        if isinstance(spec, str):
            return list(self.palettes.get(spec, [spec]))
        return list(spec)

    def steps(self, a: float, b: float, every) -> list[tuple[float, float]]:
        every = str(every or "beat").lower()
        beats = [t for t in self.analysis.get("beats", [])]
        bars = [t for t in self.analysis.get("downbeats", [])]
        marks = None
        if every in ("beat", "half", "2beats"):
            marks = beats[::2] if every != "beat" else beats
        elif every in ("bar", "2bars"):
            marks = bars[::2] if every == "2bars" else bars
        if marks:
            inside = [t for t in marks if a - 1e-3 <= t < b - 0.05]
            if inside:
                pts = inside + [b]
                if pts[0] > a + 0.05:
                    pts = [a] + pts
                return list(zip(pts[:-1], pts[1:]))
        step = t_of(every) if re.match(r"^[\d.]+s?$", every) else (60 / self.analysis.get("tempo", 120)) * (4 if "bar" in every else 1)
        out, t = [], a
        while t < b - 0.05:
            out.append((t, min(b, t + step)))
            t += step
        return out

    def lit_len(self, cue, a, b):
        ln = cue.get("length", self.defaults["length"])
        if isinstance(ln, str) and ln.endswith("s"):
            return min(b - a, float(ln[:-1]))
        return max(0.05, (b - a) * float(ln))

    # -- one effect on one target ----------------------------------------------------------
    def put(self, sid, cue, a, b, step_i=0, level=None):
        info = self.s.info[sid]
        doc = self.s.doc
        cs0, cs1 = int(round(a * 100)), int(round(b * 100))
        if doc.total:
            cs1 = min(cs1, doc.total)
        if cs1 - cs0 < 3:
            return
        cols = self.colors(cue.get("colors"))
        policy = cue.get("on_overlap", self.defaults["on_overlap"])
        lv = level or cue.get("intensity", 100)
        i0, i1 = (lv if isinstance(lv, list) else [lv, lv])
        if info["channel"]:
            typ = cue.get("type") or "on"
            sp = info["sp"]
            chans = H.ensure_channels(doc, sp, info["pc"], only=set(range(len(H.expected_channels(info["pc"])) or 1)))
            for ch in [c for c in chans if c is not None]:
                settings = {"on": "INTENSITY", "fade": "INTENSITY", "pulse": "INTENSITY",
                            "shimmer": "SHIMMER", "twinkle": "TWINKLE"}.get(typ, "INTENSITY")
                if typ == "fade":
                    a_, b_ = cue.get("from", i0 if isinstance(lv, list) else 100), cue.get("to", i1 if isinstance(lv, list) else 0)
                elif typ == "pulse":
                    a_, b_ = cue.get("from", 100), cue.get("to", 0)
                else:
                    a_, b_ = i0, i1
                if info["kind"] == "dumb_rgb":
                    col = H.parse_color(cols[step_i % len(cols)])
                    if settings == "TWINKLE":
                        settings = "SHIMMER"
                    v0, v1 = H.argb_signed(col, a_), H.argb_signed(col, b_)
                    lvl = {"intensity": str(v0)} if v0 == v1 and settings == "INTENSITY" else {"startIntensity": str(v0), "endIntensity": str(v1)}
                elif settings == "SHIMMER":
                    lvl = {"startIntensity": str(a_), "endIntensity": str(b_)}
                else:
                    lvl = H.level_attrs(None, a_, b_) if a_ != b_ else {"intensity": str(a_)}
                self._place(ch, H.new_effect(cs0, cs1, settings, lvl), policy, info["name"])
        elif info["motion"]:
            track = self._row(info, cue, cs0, cs1)
            if track is None:
                return
            if cue.get("picture"):
                side = self._picture_side(cue["picture"])
                if side is None:
                    return
            else:
                preset = cue.get("preset") or "wash"
                learned = H.load_templates().get("presets", {})
                if preset in learned:
                    name, opts = learned[preset]["effect"], learned[preset]["options"]
                elif preset in H.PRESETS:
                    name, opts = H.PRESETS[preset]
                else:
                    self.warnings.append(f"unknown preset {preset!r} (cue on {info['name']}): skipped")
                    return
                use = cols if len(cols) <= 5 else cols[:5]
                if cue.get("rhythm", "hold") != "hold" and cue.get("cycle_colors", True) and len(cols) > 1 and preset in ("wash",):
                    use = [cols[step_i % len(cols)]]
                side = f"lightorama_{name}:{H.palette(use)}:{opts}"
            if cue.get("rhythm", "hold") != "hold" and not isinstance(lv, list) and cue.get("type") == "pulse":
                i0, i1 = 100, 0
            lvl = H.level_attrs(None, i0, i1) if i0 != i1 else {"intensity": str(i0)}
            eff = H.new_effect(cs0, cs1, f"{H.MIX_ONE_SIDED}|{side}|{H.NONE_SIDE}", lvl)
            self._place(track, eff, policy, f"{info['name']}/{track.get('name')}")
        else:
            self.warnings.append(f"{info['name']}: no channels or motion rows; skipped")

    def _row(self, info, cue, cs0, cs1):
        tracks = info["sp"].findall("track")
        if cue.get("row"):
            for t in tracks:
                if (t.get("name") or "").lower() == str(cue["row"]).lower():
                    return t
            self.warnings.append(f"{info['name']}: no row {cue['row']!r}")
            return None
        whole = [t for t in tracks if H.track_type(t) == "none"] or tracks
        for t in whole:
            if not any(H.span(x)[0] < cs1 and cs0 < H.span(x)[1] for x in H.effects_in(t)):
                return t
        return whole[0] if whole else None

    def _picture_side(self, path_s):
        p = Path(path_s)
        p = p if p.is_absolute() else self.dir / p
        if not p.is_file():
            self.warnings.append(f"picture {path_s} not found")
            return None
        if str(p) not in self.pictures:
            self.pictures[str(p)] = H.embed_picture(self.s.doc, p)
        opts, _ = H._picture_options("picturexy", self.pictures[str(p)])
        return f"lightorama_picturexy:{H.palette(None)}:{opts}"

    def _place(self, container, eff, policy, label):
        try:
            H.place_effect(self.s.doc, container, eff, "replace" if policy == "replace" else "error", label)
            self.count += 1
        except H.LorError as exc:
            if policy == "error":
                raise
            self.warnings.append(f"skipped: {exc}")

    # -- a cue over a span ------------------------------------------------------------------
    def run_cue(self, cue, a, b):
        ids = self.s.ordered(self.s.resolve(cue["targets"], self.aliases), cue.get("order"))
        if not cue.get("include_faces"):
            ids = [i for i in ids if not self.s.info[i]["face"]] or ids
        rhythm = cue.get("rhythm", "hold")
        if rhythm == "hold":
            for sid in ids:
                self.put(sid, cue, a, b)
            return
        for k, (s0, s1) in enumerate(self.steps(a, b, cue.get("every", "beat"))):
            e1 = s0 + self.lit_len(cue, s0, s1)
            if rhythm == "pulse":
                chosen = ids
            elif rhythm == "chase":
                width = int(cue.get("width", 1))
                chosen = [ids[(k + j) % len(ids)] for j in range(width)]
            elif rhythm == "alternate":
                chosen = ids[k % 2::2]
            elif rhythm == "random":
                chosen = self.rng.sample(ids, max(1, int(len(ids) * float(cue.get("share", 0.4)))))
            else:
                raise H.LorError(f"unknown rhythm {rhythm!r}")
            for sid in chosen:
                self.put(sid, cue, s0, e1, step_i=k)

    def run(self):
        for sec in self.plan.get("sections", []):
            a0, b0 = t_of(sec["start"]), t_of(sec["end"])
            for cue in sec.get("cues", []):
                a = t_of(cue["start"]) if "start" in cue else a0
                b = t_of(cue["end"]) if "end" in cue else b0
                try:
                    self.run_cue(cue, a, b)
                except H.LorError as exc:
                    self.warnings.append(f"section {sec.get('label', a0)}: {exc}")
        for acc in self.plan.get("accents", []):
            ms = float(acc.get("min_strength", 0.9))
            ln = t_of(acc.get("length", 0.3))
            for hit in self.analysis.get("accents", []):
                if hit["strength"] >= ms and (("start" not in acc) or hit["t"] >= t_of(acc["start"])) and \
                        (("end" not in acc) or hit["t"] < t_of(acc["end"])):
                    try:
                        cue = {"type": "pulse", **acc, "rhythm": "hold"}
                        for sid in self.s.resolve(acc["targets"], self.aliases):
                            self.put(sid, cue, hit["t"], hit["t"] + ln)
                    except H.LorError as exc:
                        self.warnings.append(f"accent: {exc}")


def cmd_compile(args):
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    out = Path(args.out)
    if out.resolve() == Path(args.base).resolve():
        sys.exit("--out must differ from --base (compile never edits the base sequence)")
    if out.exists() and not args.force:
        sys.exit(f"{out} exists; pass --force to overwrite it")
    shutil.copy2(args.base, out)
    show = Show(out)
    c = Compiler(show, plan, plan_path.parent)
    c.run()
    data = show.doc.to_bytes()
    out.write_bytes(data)
    print(f"wrote {out}: {c.count} effects from {len(plan.get('sections', []))} sections")
    seen = set()
    for w in c.warnings:
        k = re.sub(r"\d", "#", w)[:90]
        if k in seen:
            continue
        seen.add(k)
        print("warning:", w)
    if len(c.warnings) > len(seen):
        print(f"({len(c.warnings) - len(seen)} similar warnings hidden)")
    return 0


# --------------------------------------------------------------------------- targets / draft
CATEGORIES = [  # (alias, name keywords) - first match wins; used for drafts and `targets`
    ("faces", FACE_WORDS),
    ("mega_trees", ("tree 16x", "tree 32x", "mega", "rgb tree")),
    ("matrix", ("matrix",)),
    ("windows", ("window", "frame")),
    ("rooflines", ("roof", "eave", "gutter", "outline", "vertical")),
    ("arches", ("arch",)),
    ("canes", ("cane",)),
    ("stars", ("star",)),
    ("snowflakes", ("snowflake", "spinner", "mandala")),
    ("mini_trees", ("mini tree", "minitree", "mini-tree")),
    ("bushes", ("bush", "shrub", "hedge")),
    ("stakes", ("stake", "firestick")),
    ("floods", ("flood",)),
    ("columns", ("column", "pillar", "post")),
    ("curtains", ("curtain", "icicle")),
]


def categorize(show: Show):
    cats: dict[str, dict[str, list[str]]] = {}
    for sid in show.order:
        inf = show.info[sid]
        n = inf["name"].lower()
        cat = next((c for c, words in CATEGORIES if any(w in n for w in words)), "other")
        sub = "groups" if inf["kind"] == "group" else ("pixel" if inf["kind"] == "pixel" or inf["motion"] else "channel")
        cats.setdefault(cat, {}).setdefault(sub, []).append(inf["name"])
    return cats


def cmd_targets(args):
    show = Show(Path(args.base))
    cats = categorize(show)
    print(f"{len(show.order)} targets. Aliases a draft would use (edit freely in the plan):")
    for cat, subs in sorted(cats.items()):
        for sub, names in subs.items():
            ex = ", ".join(names[:4]) + (" ..." if len(names) > 4 else "")
            print(f"  {cat:12} {sub:8} x{len(names):3}  {ex}")
    return 0


def cmd_draft(args):
    show = Show(Path(args.base))
    a = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    cats = categorize(show)
    aliases: dict[str, list[str]] = {}
    for cat, subs in cats.items():
        if cat in ("faces", "other"):
            continue
        # pixel looks: prefer groups (one effect covers every member, like LOR's own sequences)
        # only groups that have motion rows can be sequenced directly (S6 copies the group's
        # MotionRowDefaults; groups without them have none)
        groups = [g for g in subs.get("groups", []) if any(show.info[s]["motion"] for s in show.resolve(g, {}))]
        pix = [n for n in subs.get("pixel", []) if any(show.info[s]["motion"] for s in show.resolve(n, {}))]
        if groups:
            aliases[f"{cat}_px"] = groups[:1] if len(groups) > 1 and cat in ("mini_trees",) else groups[:3]
        elif pix:
            aliases[f"{cat}_px"] = pix
        if subs.get("channel"):
            aliases[f"{cat}_ac"] = subs["channel"]
    pal = args.palette.split(",") if args.palette else PALETTES.get(args.style, PALETTES["classic"])
    px = [k for k in aliases if k.endswith("_px")]
    ac = [k for k in aliases if k.endswith("_ac")]
    big = [k for k in px if k.startswith(("mega_trees", "matrix"))]
    small_px = [k for k in px if k not in big]
    sections = []
    looks_mid = ["twinkle", "garland_up", "blend_up", "lines"]
    looks_high = ["bars", "meteors_down", "spiral_left", "ripple", "blend_expand", "spiral_right"]
    secs = a["sections"]
    for i, sec in enumerate(secs):
        lvl, cues = sec["level"], []
        first, last = i == 0, i == len(secs) - 1
        if lvl == "low":
            for k in ac[:4]:
                cues.append({"targets": k, "type": "fade" if first else "on", "from": 0, "to": 60, "intensity": 60})
            for k in small_px[:3]:
                cues.append({"targets": k, "preset": "wash", "colors": [pal[i % len(pal)]], "intensity": [0, 60] if first else 50})
            for k in big:
                cues.append({"targets": k, "preset": "twinkle", "colors": "main", "intensity": 70})
        elif lvl == "mid":
            for j, k in enumerate(ac):
                cues.append({"targets": k, "type": "pulse" if j % 2 == 0 else "on", "rhythm": "chase" if j % 2 == 0 else "hold",
                             "every": "beat", "order": "left_to_right", "intensity": 80})
            for j, k in enumerate(small_px):
                cues.append({"targets": k, "preset": looks_mid[(i + j) % len(looks_mid)], "colors": "main"})
            for k in big:
                cues.append({"targets": k, "preset": "spiral_left" if i % 2 else "garland_up", "colors": "main"})
        else:
            for j, k in enumerate(ac):
                cues.append({"targets": k, "type": "pulse", "rhythm": "pulse" if j % 2 == 0 else "alternate", "every": "beat"})
            for j, k in enumerate(small_px):
                cues.append({"targets": k, "preset": looks_high[(i + j) % len(looks_high)], "colors": "main",
                             "rhythm": "pulse", "every": "bar", "length": 1.0})
            for k in big:
                cues.append({"targets": k, "preset": looks_high[(i + 2) % len(looks_high)], "colors": "main",
                             "rhythm": "pulse", "every": "bar", "length": 1.0})
        if last and lvl != "high":
            for c in cues:
                if c.get("type") in ("on", None) and "preset" not in c:
                    c.update({"type": "fade", "from": 80, "to": 0})
                elif "preset" in c and c.get("rhythm", "hold") == "hold":
                    c["intensity"] = [70, 0]
        sections.append({"start": round(sec["start"], 2), "end": round(sec["end"], 2),
                         "label": f"{sec['label']} [{sec['group']}] energy {sec['energy']}", "cues": cues})
    accents = []
    roof = next((k for k in px if k.startswith("rooflines")), None) or next((k for k in ac if k.startswith(("rooflines", "windows"))), None)
    if roof:
        accents.append({"targets": roof, "type": "pulse", "preset": "wash", "colors": ["white"], "min_strength": 1.0,
                        "length": 0.25, "on_overlap": "skip"})
    plan = {"title": a.get("file", "show"), "analysis": str(Path(args.analysis).resolve()) if args.absolute else
            str(Path(args.analysis)), "palettes": {"main": pal, "accent": [pal[-1]]}, "aliases": aliases,
            "defaults": {"on_overlap": "skip"}, "sections": sections, "accents": accents,
            "_notes": ["Auto-drafted from the song analysis: a starting point.",
                       "Edit palettes/aliases/cues to follow the creative direction, then compile.",
                       "Faces are left out (singing faces need lyric timing)."]}
    Path(args.out).write_text(json.dumps(plan, indent=1), encoding="utf-8")
    n = sum(len(s["cues"]) for s in sections)
    print(f"wrote {args.out}: {len(sections)} sections, {n} cues, aliases: {', '.join(aliases)}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("targets")
    s.add_argument("base")
    s.set_defaults(fn=cmd_targets)
    s = sub.add_parser("draft")
    s.add_argument("base")
    s.add_argument("--analysis", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--style", default="classic", choices=sorted(PALETTES))
    s.add_argument("--palette", help="comma list of colours (overrides --style)")
    s.add_argument("--absolute", action="store_true", help="store the analysis path as absolute")
    s.set_defaults(fn=cmd_draft)
    s = sub.add_parser("compile")
    s.add_argument("plan")
    s.add_argument("--base", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_compile)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except H.LorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
