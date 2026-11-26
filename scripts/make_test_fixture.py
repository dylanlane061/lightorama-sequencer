#!/usr/bin/env python3
"""Write a SYNTHETIC S6-style .loredit for testing lor_helper.py without a real show.

It follows the structure in references/schema_examples.md: CRLF line endings,
2-space indent and ' />' self-closing tags, like the .NET writer S6 uses. It is
not a real LOR file. Test against a copy of a real sequence before trusting
the output on the show.

    python make_test_fixture.py out.loredit
"""
import sys
from pathlib import Path

NONE = ("lightorama_none:FFFF0000,0;FF00FF00,0;FF0000FF,0;FFFFFF00,0;FFFFFFFF,0;FF000000,0:")
WASH = ("Mix_Average|0|0|full|20|lightorama_colorwash:FFFF0000,1;FF00FF00,0;FF0000FF,0;FFFFFF00,0;"
        "FFFFFFFF,0;FF000000,0:full,full,single_color|" + NONE)

XML = f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<sequence saveFileVersion="15" AppVersion="6.6.0.12" id="00000000-0000-4000-8000-0000000000aa" totalCentiseconds="6000" WaveHeight="1" TimingGridIdx="0" DragEventsWithTimings="True" ChaseClearFirst="True" ChaseSameRowType="True" ChaseType="0" AudioAnalysisLevel="0" NameAreaWidth="344" ZoomWidth="15" ZoomHeight="16" musicFilename="Test\\test.mp3" GridView="Show All Items" GridViewSource="Sequence" StartColor="FFFF0000" EndColor="FF00FF00">
  <PreviewClass id="00000000-0000-4000-8000-000000000001" Name="Synthetic Display" Revision="1" EmbedBackgrounds="False">
    <PropClass id="00000000-0000-4000-8000-000000000101" Name="Matrix" DeviceType="DMX" StringType="RGB" ChannelGrid="Regular,1,1,300,0,;Regular,1,301,600,0,;Regular,1,1,300,0,;Regular,1,301,600,0,;Regular,2,1,300,0,;Regular,2,301,600,0,;Regular,2,1,300,0,;Regular,2,301,600,0,;Regular,3,1,300,0,;Regular,3,301,600,0,;Regular,3,1,300,0,;Regular,3,301,600,0,;Regular,4,1,300,0,;Regular,4,301,600,0,;Regular,4,1,300,0,;Regular,4,301,600,0," BulbShape="Circle" Parm1="16" Parm2="100" Parm3="1" MaxChannels="4800" MasterPropId="">
      <shape ShapeName="Matrix-Vertical-Rectangle" OffsetX="0" OffsetY="0.2" ScaleX="0.25" ScaleY="0.4" Radians="0" />
      <MotionRowDefaults>
        <MotionRowDefault id="00000000-0000-4000-8000-000000000201" name="Effects 01" />
        <MotionRowDefault id="00000000-0000-4000-8000-000000000202" name="Effects 02" />
      </MotionRowDefaults>
    </PropClass>
    <PropClass id="00000000-0000-4000-8000-000000000102" Name="Mini Tree 1" DeviceType="LOR" TraditionalType="Single Color" ChannelGrid="Regular,1,1,1,0,Green" BulbShape="Circle" MaxChannels="1" MasterPropId="" Parm1="1" Parm2="20">
      <shape ShapeName="Lines-Connected"><point x="-0.8" y="-0.6" /><point x="-0.6" y="-0.2" /><point x="-0.4" y="-0.6" /></shape>
    </PropClass>
    <PropClass id="00000000-0000-4000-8000-000000000103" Name="Garage Flood" DeviceType="LOR" StringType="DumbRGB" TraditionalType="Channel_per_color" ChannelGrid="Regular,1,2,2,0,Red;Regular,1,3,3,0,Green;Regular,1,4,4,0,Blue" BulbShape="Circle" MaxChannels="3" MasterPropId="">
      <shape ShapeName="Bulbs"><point x="0.6" y="-0.5" /></shape>
    </PropClass>
  </PreviewClass>
  <BeatChannels MaxDisplayedRows="10" />
  <Subsequences />
  <SequenceProps>
    <SeqProp id="00000000-0000-4000-8000-000000000101" name="Matrix" EnablePixelChannels="0" OverlayMotionRows="1">
      <track id="00000000-0000-4000-8000-000000000201" name="Effects 01">
        <effect startCentisecond="0" endCentisecond="500" intensity="100" settings="{WASH}" />
      </track>
      <track id="00000000-0000-4000-8000-000000000202" name="Effects 02" />
    </SeqProp>
    <SeqProp id="00000000-0000-4000-8000-000000000102" name="Mini Tree 1" EnablePixelChannels="0" OverlayMotionRows="0">
      <channel row="0" col="0" color="0">
        <effect startCentisecond="0" endCentisecond="100" intensity="100" settings="INTENSITY" />
      </channel>
    </SeqProp>
    <SeqProp id="00000000-0000-4000-8000-000000000103" name="Garage Flood" EnablePixelChannels="0" OverlayMotionRows="0">
      <channel row="0" col="0" color="0" />
    </SeqProp>
  </SequenceProps>
  <ArchivedProps />
  <RgbAggregates />
  <TimingGrids>
    <TimingGridFixed name="Fixed Grid: 0.05" spacing="5" />
    <TimingGridFree name="Beats">
      <timing centisecond="0" />
      <timing centisecond="52" />
      <timing centisecond="104" />
      <timing centisecond="156" />
      <timing centisecond="208" />
      <timing centisecond="1000" />
      <timing centisecond="1500" />
    </TimingGridFree>
  </TimingGrids>
  <BeatView />
  <PropViews />
  <MotionPaks />
  <pictures />
</sequence>
"""

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic_test.loredit")
    out.write_bytes(XML.replace("\n", "\r\n").encode("utf-8"))
    print(f"wrote {out}")
