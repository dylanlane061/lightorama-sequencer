# Pixel art on a mega tree (or any pixel grid)

The tree is the show's screen. Dylan and Papa Russ both rated its pictures as the best
part of the Polar Express show, so give the tree a picture in nearly every scene. Use
generic looks (spirals, bars) only as a short break between pictures.

## The canvas

- A tree's effect buffer is **strands × lights per strand**: a 16-strand Tree 180 with
  75 lights is a 16 × 75 image. Column = strand (left to right as the preview draws
  them), row 0 = the **top** of the tree. `lor_helper.py inspect --filter tree` and
  `lor_layout.py` give the size; a matrix reports width × height.
- **The top is squeezed.** Every row spans the full width of the cone at that height,
  so things drawn near the top come out physically tiny. Put the subject in the lower
  two thirds. Faces, small text and fine detail near the top get lost.
- **Strands are spread far wider than lights.** A circle drawn in the buffer needs to be
  about 2.2× taller than wide to look round on the tree (`disk(..., aspect=2.2)` in
  `lor_pixelart.py`). Objects should be at least 2 to 4 lights tall to read from the
  street.
- Black = off. Saturated colours on black read best. A dim background (a night sky
  gradient at 10–20%) keeps the tree from going dark, but keep it dim.
- Horizontal motion wraps around the cone. Up, down and zigzag motion reads best.

## What makes a scene land

- **Tell a small story with a payoff:** pressure builds, then the whistle releases it;
  a snowman builds itself; a present shakes, then bursts; a mug fills, then the
  marshmallows drop in. "Snow falls" alone is weaker than "snow falls and piles up".
- **Time it to the music from the analysis.** Compute event times from
  `song.analysis.json` (beats, downbeats, accents) or from marks you measured. Examples:
  a hole punched on each downbeat, the bell striking each beat, flames leaping on each
  "hot hot", firework shells timed to burst on the hit.
- **Land the moment on frame one.** A whistle picture must be at full strength in its
  very first frame. Anything that "builds up" from the base reads as late. Start the
  effect about 0.1 s before the sound. Find onsets in the audio rather than trusting
  section times (the whistles in the medley were 0.2 s earlier than the section marks).
- **Movement in the pixels, not rigid lines.** Slosh, flicker, drift, wobble. Rigid
  bars and slow fills read as "not obvious".
- **Make it fast enough to see.** The first mug took the whole verse to fill and nobody
  could tell what it was. 13 s to fill, with a bold red outline from the first frame,
  read clearly.
- **Hand off cleanly.** One picture effect per scene, never split (a split GIF
  restarts). Fade the neighbouring looks in and out on another row around it, or end
  the picture on a frame that leads into the next scene (the lantern fades out as the
  mug outline appears).
- **Tie the tree to the rest of the house:** the drive wheel turns one spoke per eighth
  note, exactly like the snowflake wheels; the boiler surges on the same chugs that move
  the trim.

## Tools

`scripts/lor_pixelart.py` has the scenes from the Polar Express show, ready to time to
any song:

```bash
python $S/lor_pixelart.py scenes
python $S/lor_pixelart.py render <scene> --start S --end E --analysis song.analysis.json [--hits t1,t2] [--size 16x75] --out art/x.gif
python $S/lor_pixelart.py sheet art/x.gif --out look.png      # always look before placing
```

Scenes: boiler, steam_blast (whistle), drive_wheel, snowfall, snowman, ticket, present,
train_climb, steam_stop, lantern, cup_fill, cup_hold, flames, fireworks, bell, taillight.
They're drawn at 16 × 75 and resampled to `--size`, which suits tall grids. For a wide
matrix, write a new scene: import the module and reuse `add`, `blob`, `disk`, `line`,
`frames_for` and `save`.

Then use a `"picture"` cue over exactly `--start`..`--end`, on a row above the tree's
other looks (for example `"row": "Effects 03"`).

## Checking

- Sample a GIF by **time**, not frame index: Pillow merges identical frames, so frame
  90 isn't 4.5 s in (`lor_pixelart.py sheet` and `gif_at()` do this right).
- Look at the tree in viewer snapshots, cropped to the tree. The preview draws the
  real cone, so you see the top squeeze and the aspect for real.
- Pictures are the least verified part in S6 (the PictureXY option string). Say so the
  first time, and use `lor_helper.py learn-template` if S6 shows nothing.

## Ideas that fit a scene

| Moment in the song | Picture |
| --- | --- |
| Intro building | Pressure or energy building: a boiler, a fuse, a charging glow |
| A sound effect (whistle, bell, horn) | The thing itself, at full strength on the sound |
| Steady verse | A gentle scene with a slow payoff (snow piling, a snowman) |
| Downbeats in a groove | Something that clicks on each bar (a ticket punch, ornaments popping) |
| The peak | A burst: a present exploding, fireworks, a star |
| Dialogue or a lull | Slowing down: steam puffs spacing out, a lantern swinging |
| Lyric hook ("hot hot") | Flames, sparks or flashes on exactly those words |
| The ending | Something leaving or settling: a taillight shrinking away, the star last |
