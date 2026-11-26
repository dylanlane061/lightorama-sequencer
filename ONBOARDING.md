# Onboarding an AI assistant

This folder is an **Agent Skill** (a `SKILL.md` plus scripts), the open format that
ChatGPT, Codex and Claude all support. Installing it as a skill is the best route: the
assistant then picks it up whenever you ask for a light show, with no prompt pasting.

The assistant needs to be able to run code (Python) and, ideally, use a browser so it can
look at its own preview. ChatGPT's Work mode can do both.

---

## Option A (best): install it as a skill

- **ChatGPT:** in the desktop app, open **Skills** in the sidebar and add this skill from
  the zip or folder. Or attach `lightorama-sequencer.zip` in a chat and ask:
  *"Install this as a skill. Keep the whole folder (SKILL.md, scripts, assets,
  references)."* Menus change, so if you can't find it, ask ChatGPT how to install a
  skill from a zip.
- **Codex:** put the `lightorama-sequencer` folder in your skills folder, or ask Codex to
  install it with its built-in skill installer.
- **Claude Code:** copy the folder into `%USERPROFILE%\.claude\skills\`.

Then, in a new chat, test it with:

```
Use the lightorama-sequencer skill. Run its self-test and tell me if everything passed.
```

## Option B (if skills aren't available): a Project or a single chat

Create a Project (or a single chat), add `lightorama-sequencer.zip`, and use this as the
project instructions or your first message:

```
lightorama-sequencer.zip is an Agent Skill for building Light-O-Rama S6 light shows.
Unzip it and read lightorama-sequencer/SKILL.md completely. It is your operating
manual; follow it exactly (only its scripts write .loredit files; never write the XML
yourself). Start by running its self-test and telling me the result in one line.
```

---

## Asking for a show

Attach your **layout** (export it from S6's Previews panel as a `.lorprev`) and your
**song** (mp3 or wav), then say:

```
Use the lightorama-sequencer skill to build a show from my layout and this song.
Tell me the tempo and sections you hear before you plan. Here's what I want:
<paste the filled-in template below>
When it's done, look at the preview yourself, then give me the .loredit, the preview
.html and plan.json.
```

## Show direction template (copy, fill in, paste)

```
Song: <title>  (length about <m:ss>)
Overall feel: <e.g. elegant and warm / high-energy party / spooky>
Colours: <e.g. red, white and gold only; no blue>
Sections:
  - Intro: <e.g. slow fade-in on windows and rooflines, tree twinkling white>
  - Verses: <e.g. calm, chases left to right on the beat, mini trees alternate>
  - Chorus: <e.g. everything on, pulses on every beat, mega tree spirals>
  - Big moment at <m:ss>: <e.g. all white flash, then fireworks on the matrix>
  - Ending: <e.g. fade to warm white, then dark>
Must-haves: <e.g. keep the star on the whole song; flash rooflines on the big hits>
Avoid: <e.g. strobing; anything on the singing faces>
Props to feature: <e.g. the mega tree and the arches>
```

---

## After you get the files

1. Copy the `.loredit` into `Documents\Light-O-Rama\Sequences` and the song into
   `Documents\Light-O-Rama\Audio` (S6 finds it there by file name).
2. Double-click the preview `.html` to watch it with the music. It's a quick check, but
   fancy pixel effects (spirals, meteors) are lookalikes there.
3. **Open the sequence in S6 and play it.** That's the real test. Report anything odd
   back to the assistant, and keep `plan.json`, since changes are fast from it.
4. The first time pictures are used on a matrix, check in S6 that they show. If they
   don't, place one Picture XY effect by hand, save, upload that sequence, and ask the
   assistant to run `learn-template` (AGENTS.md explains how).
