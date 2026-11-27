# Light-O-Rama S6 show builder (an AI agent skill)

This gives an AI agent (Claude Code, Claude desktop with a folder connected, or another
agent that can run Python) what it needs to build **Light-O-Rama S6** light shows:

- **In:** your layout file (`.lorprev`), a song, and what you want ("calm and icy for the
  verses, go big on the chorus, red and white only, keep the mega tree on the whole time").
- **Out:** a `.loredit` sequence you open in the LOR Sequencer, plus an **HTML preview**
  of the show over your house photo, with the music, that plays in any browser.

The agent never writes LOR's XML by hand. The scripts in `scripts/` do, with backups,
and they check every file before saving it.

## Just want to watch a show? Use the app

The **Papa Russ** app (from Papa Russ Light Co.) also runs on its own, no assistant needed:
[open it in your browser](https://dylanlane061.github.io/lightorama-sequencer/app/), or
download `papa-russ.html` from the [latest release](https://github.com/dylanlane061/lightorama-sequencer/releases/latest)
to use offline. Drop in any S6 sequence (`.loredit`, plus the `.lorprev` if the sequence
doesn't include its layout, and the song). Your files are read in the browser and never
uploaded. Leave notes on the show, then press **Send to assistant** to have the skill below
fix them.

## Download the assistant add-on (the skill)

[![Download the latest version](https://img.shields.io/badge/Download-latest%20version-2ea44f?style=for-the-badge)](https://github.com/dylanlane061/lightorama-sequencer/releases/latest/download/lightorama-sequencer.zip)

1. Click **Download** above. You get `lightorama-sequencer.zip`, the latest version.
2. Install that zip as a skill in your assistant (ChatGPT, Codex or Claude). Some
   assistants want the folder instead: unzip it and you'll get a `lightorama-sequencer`
   folder. [`ONBOARDING.md`](ONBOARDING.md) has the steps for each assistant, plus a
   prompt to try it.
3. **To update later:** download it again and replace the old skill or folder. Every
   version and what changed in it is on the [Releases page](https://github.com/dylanlane061/lightorama-sequencer/releases).

## What's inside

```
lightorama-sequencer/
  SKILL.md                    the agent's operating manual (Agent Skills format: ChatGPT, Codex, Claude)
  AGENTS.md                   short pointer to SKILL.md for agents that look for AGENTS.md
  ONBOARDING.md               how to install it in ChatGPT / Codex / Claude, and how to ask for a show
  README.md                   this file
  requirements.txt            Python packages
  scripts/
    lor_new.py                new empty sequence for your layout + song
    lor_audio.py              finds beats, bars, sections and loud hits in the song
    lor_plan.py               show plan -> sequence (and an automatic first draft)
    lor_show.py               HTML preview + snapshots
    build_app.py              makes the standalone app (docs/app/, papa-russ.html)
    check_app_reader.py       checks the app reads shows exactly like lor_show.py
    lor_helper.py             inspect / validate / add single effects / pixel art tools
    lor_layout.py             reads the layout (where every light is)
    selftest.py               checks the setup and builds a tiny test show
    make_test_fixture.py      tiny fake sequence for testing
  assets/viewer_template.html the preview player
  references/                 file-format notes, plan format, example sprite
```

## Setup on Windows (about 10 minutes)

1. **Python 3.10 or newer:** https://www.python.org/downloads/ (tick "Add Python to PATH").
2. **ffmpeg**, so mp3s can be read. Open PowerShell and run: `winget install ffmpeg`
3. **Python packages.** In PowerShell, inside this folder:
   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
   (Playwright is only used for preview snapshots. Without it, everything else works.)
4. **Give it to your assistant:**
   - **ChatGPT:** install it as a skill. `ONBOARDING.md` has the steps and a backup
     prompt. ChatGPT runs the scripts in its own environment, so steps 1–3 above are only
     needed if you run things on your own PC.
   - **Claude Code:** copy the `lightorama-sequencer` folder into
     `%USERPROFILE%\.claude\skills\`.
   - **Codex / other agents:** install it as a skill, or open the folder (they read
     `AGENTS.md`, which points to `SKILL.md`).
   - Check the setup any time with `python scripts/selftest.py`.

## Using it

1. In S6, open the **Previews** panel and click **Export** to save your layout as a
   `.lorprev`.
2. Put the layout, your song (mp3) and a sentence or two of direction in a folder, and
   ask the agent, for example:
   *"Using the lightorama-sequencer skill, make a show for Carol of the Bells with
   my layout. Moody blue and white at the start, explode into red and gold at
   1:10, flash the rooflines on the big hits."*
3. The agent reports what it heard in the song (tempo and sections; correct it if it's
   off), builds the show and checks the preview. It hands back:
   - `Song.loredit`: copy it to `Documents\Light-O-Rama\Sequences`, and copy the song to
     `Documents\Light-O-Rama\Audio`;
   - `Song preview.html`: double-click to watch;
   - `plan.json`: the show plan, in plain words. Ask for changes ("slower chase in the
     verse", "less purple") and it rebuilds in seconds.
4. **Always play it in S6 before show night.** The preview is accurate for timing and for
   which lights do what, but LOR's fancier pixel effects (spirals, meteors, ...) are
   lookalikes in the preview, not LOR's exact rendering.

## Good to know

- Your original files are never changed. New files are written, and every edit leaves a
  backup in `_lor_backups/` next to the sequence.
- Close the sequence in S6 before the agent edits it.
- Singing faces are left dark (they need lyric timing).
- First time you use pictures on a matrix: open the result in S6 and check the picture
  shows. If it doesn't, place one Picture XY effect by hand, save, and tell the agent to
  run `learn-template`. It copies LOR's exact settings and uses them from then on.
- Tested against LOR's free "New Years Eve Countdown" sequences and the free "Full of
  Cheer" / "Christmas Joy" compact layouts (S6 6.2–6.3). Not affiliated with
  Light-O-Rama.
- Format knowledge also draws on two open-source projects: MikeAllen1's
  light-o-rama-sequence-builder and the xLights LOR importer.

## Publishing a new version (for the maintainer)

Write what changed in `release-notes/v1.1.0.md` (it becomes the release text that the
website shows), then push a tag, and GitHub builds and attaches the zip itself:

```
git tag v1.1.0 && git push origin v1.1.0
```

Or run the **Release** workflow from the Actions tab with a tag name. It runs the
self-test, zips the folder as `lightorama-sequencer/`, and publishes a release. The
download button always points at the newest release.
