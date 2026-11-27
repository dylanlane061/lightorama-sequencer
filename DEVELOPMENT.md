# Working on the skill (handoff notes)

For a new working session, human or agent. Read this after `SKILL.md`.

## Start a session

1. Get the repo (in a Claude session: attach `dylanlane061/lightorama-sequencer`).
2. `pip install -r requirements.txt` then `python scripts/selftest.py`: it must pass.
3. Show files (layouts, songs, `.loredit`) are gitignored and never committed: the repo
   is public.

## Where things live

| What | Where |
| --- | --- |
| Skill manual | `SKILL.md` (agents), `ONBOARDING.md` (installing), `README.md` (people) |
| Scripts | `scripts/` (`lor_plan.py` compiles show plans; `lor_show.py` builds the viewer) |
| Viewer | `assets/viewer_template.html` (review notes: N key; db when published as a Claude artifact) |
| Website | `docs/index.html`, served by GitHub Pages from `main` `/docs` |
| Standalone app | the viewer template with no show embedded. `python scripts/build_app.py` copies it to `docs/app/index.html` (selftest fails if you forget). Its JS show reader mirrors `lor_layout.py` + `lor_show.py`'s Builder: change both, then run `check_app_reader.py` |
| Assistant hand-offs | the app never calls an AI: it shows a hand-off card (message to paste, files, what happens, the way back). The messages are in the viewer template's "assistant hand-offs" section; `SKILL.md` Workflow 5 says how the skill answers each one, including `notes-reply.json`. Change both together |
| Releases | `.github/workflows/release.yml` + `release-notes/<tag>.md` |

## Releasing

1. Write `release-notes/vX.Y.Z.md`: it becomes the release text the website shows.
2. Push a tag `vX.Y.Z`, or run the Release workflow by hand with that tag.
   - Claude sessions can't push tags or edit releases. Run the workflow through the API:
     `gh api -X POST repos/dylanlane061/lightorama-sequencer/actions/workflows/release.yml/dispatches -f ref=main -f 'inputs[tag]=vX.Y.Z'`
3. The workflow runs the self-test, zips the skill as `lightorama-sequencer/` (without
   `docs/`, `release-notes/` or `.github/`) and publishes it.

## Still unverified in real S6

- Picture effects (PictureXY option string); fix with `lor_helper.py learn-template`.
- Bars as a spaced-group chase (black palette slots) and the cycles-as-speed reading.
- Line props: buffer assumed to run along the string (direction words follow wiring).
- No generated sequence has been opened in S6 yet.

## Learned the hard way

- Palette order matters (bars cycle enabled slots in slot order); `palette()` keeps it.
- Pillow merges identical GIF frames; sample GIFs by time, not by frame index.
- Rhythm phase is song-wide, so separate cues stay in step (snowflake wheels).
- Speed changes in a chase: split into pieces that each move whole group periods.

## Current show project (not in this repo)

Polar Express / Hot Chocolate Medley for Papa Russ's "Christmas 2025 - COPY" layout, at
v4. The working files (song, layout, analysis, plan and art scripts) are in a private zip
that Dylan keeps: attach it and unzip it to continue. The beat-sheet doc and the preview
artifact (with review notes in its `notes` collection) are in Dylan's Claude artifacts.
