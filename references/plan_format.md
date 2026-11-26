# Show plan format (`lor_plan.py compile`)

A plan is JSON that a person can read: song sections, each with cues, where a cue says
*what* lights do *how*. `lor_plan.py draft` writes one from the song analysis. You then
edit it to follow the creative direction and compile it.

```json
{
  "title": "Carol of the Bells",
  "analysis": "carol.analysis.json",
  "palettes": {"main": ["red", "white"], "accent": ["gold"], "ice": ["ice blue", "white"]},
  "aliases": {
    "windows": ["*Window*"],
    "big_trees": ["LOR Group-RGB Tree 16x50+Star"],
    "arches": ["LOR Group-RGB Arches"],
    "floods": ["*Flood*"]
  },
  "defaults": {"on_overlap": "skip", "length": 0.85},
  "sections": [
    {"start": "0:00", "end": "0:15.3", "label": "intro: soft, building",
     "cues": [
       {"targets": "windows", "type": "fade", "from": 0, "to": 70},
       {"targets": "big_trees", "preset": "twinkle", "colors": "ice", "intensity": [0, 80]}
     ]},
    {"start": "0:15.3", "end": "0:45.3", "label": "verse",
     "cues": [
       {"targets": "arches", "preset": "wash", "colors": "main", "rhythm": "pulse", "every": "beat"},
       {"targets": "windows", "type": "pulse", "rhythm": "chase", "every": "beat", "order": "left_to_right"},
       {"targets": "floods", "type": "on", "colors": ["red", "green"], "rhythm": "alternate", "every": "bar"}
     ]}
  ],
  "accents": [
    {"targets": "windows", "type": "pulse", "min_strength": 1.0, "length": 0.25}
  ]
}
```

## Top level

| key | meaning |
|---|---|
| `analysis` | Path to `lor_audio.py` output, relative to the plan. It supplies the beats, bars and accents. |
| `palettes` | Named colour lists. Built-in names are `classic`, `candy`, `icy`, `warm`, `patriotic`, `halloween` and `party`. `main` is the default for cues that don't name colours. |
| `aliases` | Your names for sets of targets. Values are prop or group names, or globs (`*Arch*`), and an alias may contain other aliases. |
| `defaults` | `on_overlap`: `skip` (default; warns and keeps the earlier effect), `replace` or `error`. `length`: the default lit fraction of each step. |
| `sections` | `{start, end, label, cues[]}`. Times are `m:ss.cc` strings or seconds. |
| `accents` | Cues fired on the song's strongest hits (`min_strength`, default 0.9; analysis strengths run 0–1.5), each lasting `length`. |

## Cue keys

| key | values | notes |
|---|---|---|
| `targets` | alias, name, glob, or a list | Faces are skipped unless `"include_faces": true`. Singing faces need lyric timing. |
| `type` | `on`, `fade`, `pulse` (100→0 each step), `shimmer`, `twinkle` | For **channel** props (AC/traditional, dumb RGB). |
| `preset` | `wash`, `gradient`, `twinkle`, `bars`, `blend_up`, `blend_expand`, `meteors_down`, `meteors_up`, `spiral_left`, `spiral_right`, `lines`, `lines_across`, `ripple`, `garland_up`, `garland_down`, `garland_across`, or a learned one | For **pixel** props and groups. |
| `picture` | path to a PNG/GIF | Pixel props/groups. Embedded as PictureXY and stretched to the prop. Render it at the prop's size (`lor_helper.py inspect`). |
| `colors` | palette name or list | Dumb RGB uses one colour per step, cycling through the list. Motion effects get up to 5. |
| `intensity` | `80` or `[from, to]` | A ramp across each effect. |
| `from` / `to` | 0–100 | For `fade` and `pulse`. |
| `rhythm` | `hold` (default), `pulse`, `chase`, `alternate`, `random` | `hold` is one effect for the whole span. `pulse` hits all targets each step. `chase` lights one target per step, in `order` (`width` lights several at once). `alternate` swaps between odd and even targets. `random` lights a `share` of the targets each step. |
| `every` | `beat`, `half`, `bar`, `2bars`, or `"0.5s"` | Step size, from the analysis grid. |
| `length` | `0.85` (fraction) or `"0.3s"` | How long each step stays lit. |
| `order` | `file`, `left_to_right`, `right_to_left`, `bottom_to_top`, `top_to_bottom` | Uses each prop's position in the layout. |
| `row` | motion row name | Default: the first whole-prop row free at that time. |
| `start` / `end` | times | Override the section span for this cue. |
| `on_overlap` | `skip`, `replace`, `error` | Per cue. |

A cue can have both `type` and `preset`: channel targets use `type` and pixel targets
use `preset`. With only one given, pixel targets get `wash` and channel props get `on`.

## Design tips that read well on real houses

- **Contrast between sections** matters more than complexity. Keep quiet sections
  sparse: one or two prop families, low intensity, slow looks. Save "everything on"
  for the peaks.
- Use **groups** for pixel looks (one effect sweeps the whole family). Chase across
  separate props with `order: left_to_right`.
- Change the look on **bar** boundaries and pulse on **beats**. Changing on every beat
  reads as noise.
- Use 2–3 colours per section. A palette change is a cheap way to mark a new section.
- Use accents sparingly. White flashes on rooflines at `min_strength` 1.0 or higher
  land well.
- After compiling, look at viewer snapshots across all sections before handing over.
