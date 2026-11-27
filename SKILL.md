---
name: lightorama-sequencer
description: Create, edit and preview Light-O-Rama S6 light shows (.loredit) from a layout (.lorprev), a song and creative direction. Use for generating a whole show, adding effects, pictures or animations to a sequence, reading an LOR layout, or previewing a show in a browser without S6.
---

# Light-O-Rama S6 show builder

This skill takes a layout, a song and creative direction and produces an S6 sequence
that opens in the LOR Sequencer, plus an HTML preview to check it. The creative choices
live in a **show plan** that a person can read (you write and edit it). Scripts handle
everything fiddly: the S6 XML, timing and safety.

Light-O-Rama (LOR) is a brand of Christmas/holiday light controllers. **S6** is version 6 of
its "ShowTime" software suite. Shows are built in its **Sequencer**, which saves them as
`.loredit` files and saves layouts (where every light is) as `.lorprev` exports.

## Step 0: set up and self-test (every new environment, before anything else)

```bash
python scripts/selftest.py
```

It checks the Python packages and builds a tiny show from a fake layout and a click-track
song. Report the result to the user in one or two lines.
- **Required:** `lxml`, `pillow` (PIL) and `numpy`. If one is missing, try
  `pip install lxml pillow numpy`. If installing is impossible (a sandbox without
  internet), tell the user which package is missing and stop.
- **ffmpeg** is needed to read mp3/m4a songs. Without it, ask the user for a **WAV** copy
  of the song.
- **playwright** is used for viewer snapshots, which is how you look at your work. If
  it's missing, install it (`pip install playwright` then `python -m playwright install
  chromium`); it falls back to an installed Chrome or Edge. Only if no browser can run
  at all, use the fallback `lor_show.py storyboard`.

If your environment can't hand files back through a folder, give the user the outputs
(`.loredit`, preview `.html`, `plan.json`) as downloads.

Scripts are in `scripts/`. They need `lxml`, `pillow` and `numpy`, plus `ffmpeg` for
mp3s; snapshots also need `playwright` (see `requirements.txt` and `README.md`). Use
`-h` on any script for its options.

| script | job |
|---|---|
| `lor_new.py` | new empty sequence for a layout and song (exactly as S6 builds it) |
| `lor_audio.py` | beats, bars, sections, energy and accents; writes timing grids into the sequence |
| `lor_plan.py` | `targets` (what can be lit), `draft` (a plan from the analysis), `compile` (plan → .loredit) |
| `lor_show.py` | `build` an HTML viewer (house photo, lights, song); `snapshots` for you to look at |
| `lor_helper.py` | inspect, validate, and add single effects (pictures, presets, channel effects) |
| `lor_layout.py` | read a layout; `draw` all lights over the house photo |

## Hard rules

1. **Never write or rewrite .loredit XML yourself.** Only the scripts touch sequences.
   They back up to `_lor_backups/`, keep untouched parts byte-for-byte, re-parse before
   saving and refuse overlapping effects.
2. **Never edit the user's original files.** Build into new files: `lor_new` and
   `compile --out` write fresh files, and the helper backs up before every edit.
3. **Inspect before you plan.** Prop names, groups, rows and matrix sizes come from the
   files (`lor_plan.py targets`, `lor_helper.py inspect --summary`), never from memory.
4. **Look before you hand over.** Build the viewer and look at snapshots of every
   section. Say plainly what the viewer can't promise (below).
5. S6 must have the sequence **closed** while scripts write to it.

## Workflow 1: whole show from layout + song + direction

```bash
S=path/to/lightorama-sequencer/scripts
python $S/lor_new.py from-preview "Layout.lorprev" --audio "Song.mp3" --out base.loredit
python $S/lor_audio.py analyze "Song.mp3" --out song.analysis.json --write-grids base.loredit
python $S/lor_plan.py targets base.loredit
python $S/lor_plan.py draft base.loredit --analysis song.analysis.json --out plan.json --palette red,white,gold
#   ... edit plan.json to match the creative direction (see below) ...
python $S/lor_plan.py compile plan.json --base base.loredit --out "Song.loredit"
python $S/lor_helper.py validate "Song.loredit"
python $S/lor_show.py build "Song.loredit" --audio "Song.mp3" --out "Song preview.html"
python $S/lor_show.py snapshots "Song preview.html" --every 6s --out frames   # then view frames/contact_sheet.png
```

1. **Read the song back to the user.** After `analyze`, report the tempo and the
   section list (times, labels, energy). The analysis is an estimate, and the user can
   correct a section time or the tempo before you build on it. It was tested on a click
   track (beats within 20 ms, all section changes found), but real songs vary.
2. **Turn the direction into the plan.** The draft is a reasonable baseline: quiet
   sections sparse, peaks full, looks changing on bars, pulses on beats. Your job is to
   make it *this* song:
   - Colours: `palettes`, per section if the mood shifts.
   - Which families lead each section: the `targets` of each cue.
   - Energy: rhythm and intensity. Calm sections use `hold` and lower levels; peaks use
     `pulse` or `chase` on beats.
   - Signature moments: a picture on the matrix, a chase left to right on a key
     phrase, `accents` on the big hits.
   - Respect requests like "keep the tree on the whole song" or "nothing blue" exactly.
   Full format and design tips: `references/plan_format.md`.
3. **Compile, validate, look.** View `frames/contact_sheet.png` (each frame lists its
   time and how much of the yard is lit). Check that each section looks different from
   its neighbours, that the peaks are fuller and brighter than the verses, and that
   nothing important stays dark. Fallback only when no browser can run:
   `lor_show.py storyboard SEQ --out storyboard.png` draws rows × time with section lines.
   Skipped-overlap warnings are normal; repeated `matches nothing` warnings mean an alias
   is wrong.
4. **Hand over:** the `.loredit` (tell them to copy the song into
   `Documents\Light-O-Rama\Audio`, where S6 looks for it by file name), the preview HTML
   and `plan.json`. Re-running compile after plan edits is cheap, so offer changes.

**Starting from an existing sequence** for the same layout, with its own setup kept:
`lor_new.py from-sequence old.loredit --audio new.mp3 --out base.loredit` removes all
effects and keeps the structure.

## Workflow 2: add to or edit an existing sequence

```bash
python $S/lor_helper.py inspect show.loredit --summary [--filter matrix]
python $S/lor_helper.py add-motion-effect show.loredit --prop "LOR Group-RGB Arches" --preset bars --colors red white --start 30s --end 38s
python $S/lor_helper.py add-effect show.loredit --prop "Mini Tree 1" --prop "Mini Tree 2" --type fade --start 1:02 --end 1:04
python $S/lor_helper.py add-effect show.loredit --prop "Garage Flood" --type fade --color red --to-color green --start 0 --end 5s
```

- Motion effects go on pixel props **or groups**. One effect on a group covers every
  member, as LOR's own sequences do. Prefer an existing empty row (`inspect --summary`
  lists "free" rows); `--new-row` works but is untested in S6.
- Channel effects (`on`, `fade`, `shimmer`, `twinkle`) go on traditional and dumb-RGB
  props. Channels are created as needed, the way S6 does it.
- Use `--snap Beats` (or `Bars` or `Sections`) after `lor_audio --write-grids`.
- Use `--dry-run` first for anything big, and `--on-overlap replace` only when the user
  wants the old effect gone.

## Workflow 3: pixel art or animation on a matrix

1. Find the size: `inspect --filter matrix` reports **width × height**. LOR names
   matrices rows × columns, so "RGB Matrix 20x40" is 40 wide and 20 tall.
2. Render at exactly that size. Black means off, and saturated colours on black read
   best. Use one of:
   - `lor_helper.py render-ascii spec.json out.gif` for character-grid sprites with a
     palette and frames (example: `references/example_sprite.json`);
   - your own Pillow script;
   - `lor_helper.py fit-image photo.jpg out.png --size 40x20 --mode cover --colors 16`.
3. Look at it: `lor_helper.py preview out.gif look.png`.
4. Place it with `add-picture-effect show.loredit --prop "<matrix or group>" --image
   out.gif --start ... --end ...`, or use a `"picture"` cue in a plan. Images are
   embedded in the sequence (PictureXY, 100/100 = stretched to the prop).

## Workflow 4: review loop (notes left in the viewer)

The viewer has a **✎ Note** button (key **N**). It pauses the show and takes a note about
that moment. While the note is open, clicking lights on the house tags those props. Each
note stores its time, scene, tagged props, the effects that were on screen, and the show
version. Build with labels so notes say where they are:

```bash
python $S/lor_show.py build "Song.loredit" --audio "Song.mp3" --out preview.html --version v3 --scenes scenes.json
#   scenes.json: [{"start": 0, "end": 14, "name": "All aboard"}, ...]   (seconds)
```

Where the notes end up:
- **Published as a Claude artifact with the `db` capability** (`{"db": {}, "user": {}}`):
  notes go to the artifact's shared store, collection `notes`. Next pass, read them with
  the artifact tools (`db_query` collection `notes`, `version == "v3"`). When a note is
  fixed, write back `status: "addressed"` and a one-line `reply`. The viewer then greys
  the note out and shows the reply.
- **Anywhere else** (a local file, ChatGPT, Codex): notes stay in that browser. The
  reviewer uses **Download JSON** or **Copy as text** and gives you the file or text.
  `python $S/lor_show.py notes notes.json --active` turns it into a work list.

Work through every open note. If a note conflicts with the written direction, ask
before changing anything. Rebuild the viewer with the next `--version` so new notes stay
separate from old ones; the viewer's "All versions" filter shows the history.

## Workflow 5: messages from the Papa Russ app

The viewer is also a standalone app (the hosted `docs/app/`, or `papa-russ.html` from a
release; `scripts/build_app.py` makes it). It never calls an AI itself: wherever one would
help, it writes a message for the user to paste into a chat with you, lists the files to
attach, and tells them what you will ask and hand back. Every message starts "Use the
lightorama-sequencer skill". The app then waits for your files to be opened in it, so
**always end a job with the files as downloads, named exactly as the message asks.**

**"I reviewed my show …" (fix notes).** Lists the notes as
`[m:ss.cc] scene {tagged props}: note`, may add wishes "For the whole show", and names the
next version ("Build v2 as a new file, "Song v2.loredit""). The `.loredit` (and maybe a
`.lorprev`, a song, `plan.json`) is attached.

1. The show may not be one you built: there may be no `plan.json`. Don't rebuild it from
   scratch. Copy the sequence to the new file the message names, inspect it, and fix each
   note there with Workflow 2's commands; keep everything the notes don't mention.
2. If `plan.json` is attached (or you built it), edit the plan and recompile instead.
3. Wishes without notes ("more sparkle in the chorus"): propose two or three concrete
   changes with times and props, and make the ones the user agrees to.
4. Validate, build the next preview with `--version` (Workflow 4), look at snapshots, and
   hand back the new `.loredit`, the preview and `plan.json`.
5. When the message asks for it, also hand back **`notes-reply.json`**, one entry per note.
   The app matches each entry to the note (by time and text) and shows your answer on it:
   ```json
   {"show": "Carol of the Bells", "from": "v1", "to": "v2",
    "replies": [
      {"t": 42.1, "note": "Snowflakes should spin like train wheels here.",
       "status": "fixed", "reply": "The snowflakes now spin on every beat from 0:40 to 0:52."},
      {"t": 151.5, "note": "Less purple in the chorus.",
       "status": "not changed", "reply": "There's no purple there; the blue arches look purple over the photo. Say if you want white instead."}]}
   ```
   `t` is the note's time in seconds (`[2:31.50]` is 151.5); `note` is its text as sent;
   `status` is `fixed`, `not changed` or `question`; `reply` is one plain sentence a
   non-technical person understands. Copy `from` from the message ("(v1)"), and use the new
   version for `to`.

**"… build a new show."** Layout and song attached, with the feel, colours (and colours to
never use), props to feature, big moments, must-haves and things to avoid. Run Workflow 1.
The message asks you to report the tempo and sections and wait for an OK: do that, because the
app has told the user to expect it. Name the files as asked (`Song.loredit`, v1).

**"Start a new show from my old sequence …".** Workflow 1's "Starting from an existing
sequence" (`lor_new.py from-sequence`), then the same tempo and section check.

**"Make an animated picture for my matrix …".** Workflow 3. Show the preview image and wait
for a yes before placing it. Write the result as the new file the message names.

**"I played … in Light-O-Rama S6 and it looked different."** Explain in plain words which
part of the preview is a lookalike (see below) and what S6 does. If something in the
sequence is wrong, fix it in the next version as named.

**Setup and updates.** "Install the attached lightorama-sequencer.zip as a skill …" or
"Replace the lightorama-sequencer skill …": install it (keep the whole folder), run Step 0
and answer in one line whether everything passed, because the app asks the user exactly that.

## What the viewer can and can't promise

- **Exact:** timing, which props and rows are lit, channel effects, dumb-RGB colours,
  intensity ramps, row regions, group spreading.
- **Close:** PictureXY, colour wash, countdown.
- **Approximate:** other motion effects (bars, spirals, meteors, ...) are lookalikes in
  the right colours and direction, not LOR's renderer.
- The viewer's side panel shows this for every effect. S6 playback is the final check.

## Verified vs. still unverified (details in references/schema_examples.md)

- **Verified against LOR's own files:** file structure; new-sequence structure (matches
  an LOR store sequence prop-for-prop and row-for-row); channel and motion settings
  strings; layout geometry over the house photo; round-trip byte identity.
- **Unverified:** the Picture/PictureXY option string, because no LOR sample used one.
  The first time a picture goes in, ask the user to open the sequence in S6 and confirm
  it shows. If it doesn't, have them place one PictureXY by hand and run
  `lor_helper.py learn-template SEQ --prop X --row Y --at <time>`, which saves S6's
  exact string to `references/templates.json` for every future use. Use the same
  command to capture any motion effect the user likes (`--save-as name`), so plans can
  use it as a preset.

## Out of scope (say so rather than improvising)

- Editing the layout itself (props, wiring, universes). Do that in S6 Preview Design.
- Singing-face lyric syncing. Faces are left dark by default.
- Raw DMX channel data, and live playback control. The LOR Control Panel REST API
  could be added later.
