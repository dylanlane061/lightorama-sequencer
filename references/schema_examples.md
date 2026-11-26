# LOR S6 `.loredit` schema reference

This is everything `lor_helper.py` relies on, with how sure each item is. Read it
before editing a sequence by hand or changing the helper.

**Confidence labels**

- **Observed**: seen in real S6 files by an open-source tool that reads and writes them.
- **Inferred**: deduced from importer code. The meaning is clear, but no file
  written by our helper has been opened in S6 yet.
- **Unverified**: a guess the helper uses until `learn-template` replaces it with
  a string copied from the user's own file.

**Sources**

- MikeAllen1/light-o-rama-sequence-builder: `docs/S6_FORMAT.md`, `pixels.py`,
  `rgb.py`, `new_sequence.py`. It reads and writes S6 6.6 sequences. (MIT +
  Commons Clause.)
- xLightsSequencer/xLights: `src-core/import_export/LOREdit.cpp` and
  `plans/loredit-import.md`, an importer audited against two real LOR 6.6 vendor
  sequences (`saveFileVersion` 15 and 16, about 100k effects in total).
- LOR help: Motion Effect Reference, Manage Picture Effects dialog.

> The snippets below are reconstructions (synthetic ids and values), not copies
> of anyone's sequence. After the user's first real sequence has been inspected,
> add a "From the user's file" section at the bottom with sanitized snippets.

---

## 1. Root and section order (Observed)

```xml
<?xml version="1.0" encoding="utf-8"?>
<sequence saveFileVersion="15" AppVersion="6.6.0.12" id="…guid…"
          totalCentiseconds="20925" musicFilename="Folder\song.mp3" …editor attrs…>
  <PreviewClass …>      <!-- embedded copy of the preview: PropClass / PropGroup -->
  <BeatChannels MaxDisplayedRows="10" />
  <Subsequences />
  <SequenceProps>       <!-- the sequenced data -->
  <ArchivedProps />     <!-- same shape as SequenceProps (ArchiveProp) -->
  <RgbAggregates />
  <TimingGrids>
  <BeatView />
  <PropViews />
  <MotionPaks />
  <pictures />          <!-- embedded images for Picture/PictureXY -->
</sequence>
```

- `saveFileVersion` is 15 or 16 in LOR 6.6. Keep whatever the file has.
- All times are integer **centiseconds** (1/100 s). `totalCentiseconds` is the
  sequence length.

## 2. Props: preview side (Observed, plus Inferred for matrix size)

```xml
<PreviewClass id="…" Name="My Display" …>
  <PropClass id="P1" Name="Matrix" DeviceType="DMX" StringType="RGB"
             ChannelGrid="Regular,1,1,510,0,;Regular,2,1,510,0,;…"
             Parm1="32" Parm2="50" Parm3="0" MasterPropId="" …>
    <shape ShapeName="Matrix…" …><point x=… y=…/>…</shape>
    <MotionRowDefaults><MotionRowDefault …/></MotionRowDefaults>
  </PropClass>
  <PropClass id="P2" Name="Mini Tree 1" DeviceType="LOR" TraditionalType="Single Color" ChannelGrid="…" />
  <PropClass id="P3" Name="Flood" DeviceType="LOR" StringType="DumbRGB" TraditionalType="Channel_per_color" … />
  <PropGroup id="G1" Name="Arches" Arrangement="Preview"><member id="…"/>…</PropGroup>
</PreviewClass>
```

- **Pixel prop**: `StringType="RGB"` with `DeviceType` `DMX` or `LOR`. The
  `ChannelGrid` has one `Regular,<universe>,<first>,<last>,0,` entry per string,
  at 3 channels per pixel.
- **Dumb RGB**: `StringType="DumbRGB"`. The preview has 3 grid entries, but the
  sequence has only **one** channel.
- **Matrix size (Inferred from xLights' LOR preview importer)**: `ShapeName`
  starts with `Matrix`. `Parm1` is the number of strings, `Parm2` is nodes per
  string, and `Parm3` is folds (strands per string = folds + 1). If `ShapeName`
  contains `Vertical`, strands are columns; otherwise strands are rows. The
  helper reports this as an *estimate*. Confirm it against the Preview Design
  screen and pass `--size WxH` when they differ.
- A prop whose `MasterPropId` is set has **no** `SeqProp`. It follows its master.

## 3. Sequenced data (Observed)

```xml
<SequenceProps>
  <!-- traditional / AC / dumb-RGB prop -->
  <SeqProp id="P2" name="Mini Tree 1" EnablePixelChannels="0" OverlayMotionRows="0">
    <channel row="0" col="0" color="0">
      <effect settings="INTENSITY" startCentisecond="0"   endCentisecond="150" intensity="100" />
      <effect settings="INTENSITY" startCentisecond="150" endCentisecond="300" startIntensity="100" endIntensity="0" />
      <effect settings="SHIMMER"   startCentisecond="300" endCentisecond="400" startIntensity="100" endIntensity="100" />
      <effect settings="TWINKLE"   startCentisecond="400" endCentisecond="500" intensity="100" />
    </channel>
  </SeqProp>

  <!-- pixel prop: motion-effect rows ("track"), no channel -->
  <SeqProp id="P1" name="Matrix" EnablePixelChannels="0" OverlayMotionRows="1">
    <track id="…guid…" name="Effects 01">
      <effect startCentisecond="1000" endCentisecond="1500" intensity="100"
              settings="Mix_Average|0|0|full|20|lightorama_colorwash:…|lightorama_none:…" />
    </track>
    <track id="…" name="Effects 02" />
    <track id="…" name="Tier 1" type="rectangle" subx="0" suby="0" subw="1" subh="0.25" />
  </SeqProp>
</SequenceProps>
```

- Level is either `intensity` (constant, 0–100) or `startIntensity` plus
  `endIntensity` (a ramp).
- Channel effect `settings` values: `INTENSITY` (on or fade), `SHIMMER` (seen
  only in the start/end form), `TWINKLE`.
- **Dumb RGB**: the intensity fields hold a **signed 32-bit ARGB** colour, not a
  percentage. Black is `-16777216`, white `-1`, blue `-16776961`, green
  `-16711936`. Dimming means scaling R, G and B. A colour fade uses
  start/end ARGB. RGB twinkles are written as `SHIMMER`.
- Effects on one channel or one track do not overlap. The helper refuses to
  create an overlap.

### Track `type` (Observed by xLights)

| type | extra attrs | meaning |
|---|---|---|
| (absent) / `none` | – | whole prop |
| `rectangle` | `subx suby subw subh` (fractions 0–1, **y measured from the top**) | rectangular region |
| `custom` | `subc="x,y;x,y;…"` | set of nodes |
| `custom_horizontal_buffer` | `subc` / `subc2` | ordered node path |

With `OverlayMotionRows="1"`, **later tracks draw on top of earlier ones**.

## 4. Motion effect `settings` string (Observed)

```
<mix>|<a>|<b>|<c>|<d>|<left effect>|<right effect>[|<extra>]
```

- `Mix_Average|0|0|full|20` is the observed one-sided form, with the right side
  set to `lightorama_none`. LOR renders a one-sided effect fully opaque whatever
  the mix (xLights confirmed this against video).
- Other mixes seen: `Mix_Overlay|<0..100>`, `Mix_Maximum`, `Dissolve_Left_Right`,
  `Dissolve_Bottom_Top`, `Mix_Alpha_Blend`, `Mix_Rt_Reveals_Lt`, `Mix_Rt_Hides_Lt`,
  `Mix_Bottom_Top`, `Mix_Left-Right`.
- Each side has the form `lightorama_<name>:<palette>:<options>`.
  - Palette: six slots `AARRGGBB,<0|1>` joined by `;`. The reference tool always
    wrote the 6th as `FF000000,0`, but LOR's own files use it as a normal colour slot.
  - Options: comma-separated, specific to the effect.
- Empty side:
  `lightorama_none:FFFF0000,0;FF00FF00,0;FF0000FF,0;FFFFFF00,0;FFFFFFFF,0;FF000000,0:`

### Option strings copied from real files (Observed)

| preset | effect | options |
|---|---|---|
| wash | colorwash | `full,full,single_color` |
| gradient | colorwash | `full,full,horizontal_gradient` |
| twinkle | twinkle | `50,25,twinkle,random,0,255` |
| bars | bars | `H_expand,1,False,False,12,0` |
| blend_up | blendedbars | `up,10,10,0` |
| blend_expand | blendedbars | `V_expand,10,12,0` |
| meteors_down | meteors | `palette,19,35,down,0,16,pixel_rate,oscillate` |
| meteors_up | meteors | `palette,100,25,up,0,12,pixel_rate,linear2` |
| spiral_left | spirals | `2,left_to_right,100,18,0,False,none,5` |
| spiral_right | spirals | `2,left_to_right,-100,18,0,False,none,5` |
| lines | straightlines | `default,4,12,1,21` |
| lines_across | straightlines | `Left_to_Right,3,12,1,21` |
| ripple | ripple | `circle,1,25,A12A50A1.00,4,3,1,13,False,50` |
| garland_up / _down / _across | garland | `0,0,once_fit_to_duration,12,bottom_to_top` (`top_to_bottom`, `left_to_right`) |

A parameter can also be a **ramp** instead of a number: `R<start>R<end>`, or
`R<start>R<end>R<curve>` (for example `R32R0R1.00`).

## 5. Picture effects (Inferred: field order from xLights; formats seen in real files)

**PictureXY**: always fit-to-duration; plays animated GIFs.

```
lightorama_picturexy:<palette>:<file>,<width%>,<height%>,<left>,<top>,<…>,<…>,<…>,<…>,<anchor>[,<…>]
observed: file.jpg,71,104,0,R32R0R1.00,100,100,100,100,FFFF
observed: file.jpg,58,136,0,0,100,100,100,100,FFFF,0
```

- Width 100 and height 100 at left 0, top 0 **stretches the image over the whole
  prop** (xLights checked this against video). This is the helper's default: a
  PNG or GIF rendered at exactly the matrix resolution maps one image pixel to
  one light.
- Fields 6–9 are probably the rotation/RGB/opacity group (LOR's help lists
  Rotation, Flip, Red, Green, Blue and Opacity), but the exact order is
  **unverified**. The helper copies `100,100,100,100,FFFF,0` as observed.

**Picture** (moving or scrolling picture):

```
S5:     file.jpg,True,none,0,10,19,12
LOR 6:  *name*guid*.gif,fit_both,none,0,10,,12
fields: file, prescale(True|fit_both|fit_width|fit_height|…), movement(none|up|down|left|right|peekaboo_bottom|…), offset(-50..50), ?, ?, speed(0..50)
```

- LOR 6 may add more fields at the end (flip, R/G/B, opacity). The template is
  **unverified**. Run `learn-template` on a Picture effect the user made in S6
  before relying on it.

**File reference**

- External file: the path is **URL-percent-encoded** inside the options. A
  colon would otherwise break the `:` split.
- Embedded file: the name has the form `*<stem>*<guid>*<.ext>`, for example
  `*guitar*f526c123-50dc-48ea-8238-5c2a4855f32e*.png`. The image lives in the
  root `pictures` section:

```xml
<pictures>
  <picture name="*guitar*f526c123-50dc-48ea-8238-5c2a4855f32e*.png">iVBORw0KGgo…base64…</picture>
</pictures>
```

The helper embeds by default, so the sequence keeps working when it is copied to
the show computer.

## 6. Timing grids (Observed)

```xml
<TimingGrids>
  <TimingGridFixed name="Fixed Grid: 0.05" spacing="5" />
  <TimingGridFree name="Beats">
    <timing centisecond="112" />
    <timing centisecond="161" />
  </TimingGridFree>
</TimingGrids>
```

Keep grid names exactly as they are, and never merge grids. The first fixed grid
is usually present.

## 7. Open questions to settle against the user's first real file

1. The exact PictureXY and Picture option layout in the user's S6 version. Fix:
   make one effect by hand, then run `learn-template`.
2. Whether S6 needs `type="none"` on new tracks. The helper copies the
   attributes of an existing sibling track when one exists.
3. Whether S6 accepts the `<x/>` self-closing style. The helper writes `<x />`
   if the source file does.

## Verified against LOR's own files (Nov 2026)

These were checked against two LOR store sequences, "New Years Eve Countdown" RGBPlus
(S6 6.2.0.18 and 6.3.0.6), and two LOR Compact Layout previews (Full of Cheer,
Christmas Joy).

- The file starts with a **UTF-8 BOM**, uses **CRLF** line endings and writes self-closing
  tags as ` />`. The helper keeps all three, and loading then saving an unedited file
  gives back identical bytes.
- `Mix_Average|0|0|full|20` appears on every one-sided motion effect (41 of 41).
- Channel effect settings seen: `INTENSITY` (1005), `TWINKLE` (96) and `SHIMMER` (32).
- Option strings are **percent-encoded** (`Times%20New%20Roman`).
- **Correction:** the 6th palette slot is *not* always black. LOR's files use it as a
  normal colour slot (`FFFF0000,1`).
- **Correction:** rectangle rows often have **no `type`** attribute; `subx/suby/subw/subh`
  alone mark them. `subc` rows (point lists such as `0.0417,0.2857;…`) are custom regions.
- Every `track` has `DefaultId` equal to its `id`, and both equal a `MotionRowDefault id`
  in the prop's `PreviewClass` definition. Rows created outside S6 have no matching
  default and are untested, so prefer an existing empty row (`inspect --summary` lists them).
- **Groups are sequenced:** a `PropGroup` can have its own `SeqProp` with motion rows
  (for example "All Arches 01"). Effects spread across the members according to
  `Arrangement` (Horizontal, Vertical, Preview or None). Groups can contain groups.
- The preview's `ChannelGrid` uses `Aux A,<unit>,<first>,<last>,…` for LOR-network pixels
  and `Regular,<universe>,…` for E1.31. The 6th field is a bulb colour name for
  traditional channels.
- **Matrix naming:** "RGB Matrix 20x40" is 8 strings × 100 nodes with 4 folds, which
  makes 40 vertical strands of 20, so it is **40 wide × 20 tall**. LOR names matrices
  rows × columns, so trust `inspect`'s size, not the prop name.
- Effects seen in these files: `countdown` (options `start,font,size,…`) and `fireworks`.
  Still **not seen**: any Picture/PictureXY effect, so §5 stays unverified until one
  S6 test.

### Preview geometry (drawn over each layout's own photo; matches)

- Preview space runs from -1 to 1 on both axes with **y up**:
  `px = (x+1)/2*W, py = (1-y)/2*H` on the `BackgroundImage` (base64 PNG in the
  `.lorprev` and in the `.loredit` copy).
- Offset shapes: `OffsetX/Y` is the centre and `ScaleX/Y` is **half** the size;
  `Radians` rotates.
- Point shapes: `Lines-Connected` (polyline), `Lines-Unconnected` (pairs of points),
  `Matrix-*-Quad` (corners TL, TR, BR, BL), `Advanced` (one point per bulb, in node order,
  with `CustomGrid` giving buffer positions), `Bulbs`.
- Grid shapes: `Matrix-Vertical-Rectangle` and `Tree 180/360` use `Parm1` strings,
  `Parm2` nodes per string and `Parm3` folds. The tree apex sits about 20% below the
  top of its box.
- `Custom`: `CustomGrid` holds rows separated by `;` and cells separated by `,`. A cell
  holds its node number, or 0 for an empty cell.

## From the user's file

_(fill in after the first `inspect` of the user's own sequence)_
