# tests/unit/test_gdtf_loader.py
"""Unit tests for the GDTF import (Phase 1 of docs/gdtf-integration-plan.md).

GDTF test fixtures are authored in-test as minimal spec-conform archives
(zip + description.xml): GDTF Share terms do not permit redistributing
downloaded files, so nothing here comes from the Share.

Covers the full chain a definition travels: .gdtf -> pygdtf -> synthesized
QLC-format root -> canonical FixtureDefinition -> legacy dict (export/DMX
preset resolution) -> renderer capability detection.
"""
import os
import zipfile

import pytest

from utils import fixture_library as fl
from utils.effects_utils import get_channels_by_property
from utils.fixture_library import clear_library_cache, get_definition, parse_fixture_file
from utils.gdtf_loader import cie_xyy_to_hex

# ---------------------------------------------------------------------------
# Synthetic GDTF fixtures
# ---------------------------------------------------------------------------

SPOT_DESCRIPTION = """<?xml version="1.0" encoding="UTF-8"?>
<GDTF DataVersion="1.2">
 <FixtureType Name="Test Spot 60" ShortName="TS60" LongName="Testlight Test Spot 60"
              Manufacturer="Testlight" Description="Synthetic test moving head"
              FixtureTypeID="11111111-2222-3333-4444-555555555555">
  <Wheels>
   <Wheel Name="ColorWheel1">
    <Slot Name="Open" Color="0.3127,0.3290,100.0"/>
    <Slot Name="Deep Red" Color="0.7006,0.2993,20.0"/>
    <Slot Name="Blue" Color="0.1355,0.0399,7.0"/>
   </Wheel>
   <Wheel Name="GoboWheel1">
    <Slot Name="Open"/>
    <Slot Name="Stars"/>
    <Slot Name="Circles"/>
   </Wheel>
  </Wheels>
  <Models>
   <Model Name="BaseModel" Length="0.30" Width="0.25" Height="0.40" PrimitiveType="Base"/>
  </Models>
  <Geometries>
   <Geometry Name="Base" Model="BaseModel">
    <Axis Name="Yoke">
     <Axis Name="Head">
      <Beam Name="Beam1" BeamAngle="12" LuminousFlux="8000" ColorTemperature="6500"/>
     </Axis>
    </Axis>
   </Geometry>
  </Geometries>
  <DMXModes>
   <DMXMode Name="Standard" Geometry="Base">
    <DMXChannels>
     <DMXChannel DMXBreak="1" Offset="1,2" Geometry="Yoke">
      <LogicalChannel Attribute="Pan">
       <ChannelFunction Name="Pan" Attribute="Pan" DMXFrom="0/1"
                        PhysicalFrom="-270" PhysicalTo="270"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="3,4" Geometry="Head">
      <LogicalChannel Attribute="Tilt">
       <ChannelFunction Name="Tilt" Attribute="Tilt" DMXFrom="0/1"
                        PhysicalFrom="-135" PhysicalTo="135"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="5" Geometry="Head">
      <LogicalChannel Attribute="Dimmer">
       <ChannelFunction Name="Dim" Attribute="Dimmer" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="6" Geometry="Head">
      <LogicalChannel Attribute="ColorAdd_R">
       <ChannelFunction Name="Red" Attribute="ColorAdd_R" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="7" Geometry="Head">
      <LogicalChannel Attribute="ColorAdd_G">
       <ChannelFunction Name="Green" Attribute="ColorAdd_G" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="8" Geometry="Head">
      <LogicalChannel Attribute="ColorAdd_B">
       <ChannelFunction Name="Blue" Attribute="ColorAdd_B" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="9" Geometry="Head">
      <LogicalChannel Attribute="ColorAdd_W">
       <ChannelFunction Name="White" Attribute="ColorAdd_W" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="10" Geometry="Head">
      <LogicalChannel Attribute="Color1">
       <ChannelFunction Name="Wheel Select" Attribute="Color1" DMXFrom="0/1" Wheel="ColorWheel1">
        <ChannelSet Name="Open" DMXFrom="0/1" WheelSlotIndex="1"/>
        <ChannelSet Name="Deep Red" DMXFrom="64/1" WheelSlotIndex="2"/>
        <ChannelSet Name="Blue" DMXFrom="128/1" WheelSlotIndex="3"/>
       </ChannelFunction>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="11" Geometry="Head">
      <LogicalChannel Attribute="Gobo1">
       <ChannelFunction Name="Gobo Select" Attribute="Gobo1" DMXFrom="0/1" Wheel="GoboWheel1">
        <ChannelSet Name="Open" DMXFrom="0/1" WheelSlotIndex="1"/>
        <ChannelSet Name="Stars" DMXFrom="86/1" WheelSlotIndex="2"/>
        <ChannelSet Name="Circles" DMXFrom="172/1" WheelSlotIndex="3"/>
       </ChannelFunction>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="12" Geometry="Head">
      <LogicalChannel Attribute="Shutter1Strobe">
       <ChannelFunction Name="Strobe" Attribute="Shutter1Strobe" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="13" Geometry="Head">
      <LogicalChannel Attribute="Zoom">
       <ChannelFunction Name="Zoom" Attribute="Zoom" DMXFrom="0/1"
                        PhysicalFrom="10" PhysicalTo="40"/>
      </LogicalChannel>
     </DMXChannel>
    </DMXChannels>
   </DMXMode>
  </DMXModes>
 </FixtureType>
</GDTF>
"""

BAR_DESCRIPTION = """<?xml version="1.0" encoding="UTF-8"?>
<GDTF DataVersion="1.2">
 <FixtureType Name="Test Pixel Bar 5" ShortName="TPB5" LongName="Testlight Test Pixel Bar 5"
              Manufacturer="Testlight" Description="Synthetic test pixel bar"
              FixtureTypeID="66666666-7777-8888-9999-000000000000">
  <Models>
   <Model Name="BarModel" Length="1.0" Width="0.08" Height="0.09" PrimitiveType="Cube"/>
   <Model Name="PixelModel" Length="0.18" Width="0.08" Height="0.09" PrimitiveType="Cube"/>
  </Models>
  <Geometries>
   <Geometry Name="Bar" Model="BarModel">
    <GeometryReference Name="Pixel 1" Geometry="PixelCell" Model="PixelModel">
     <Break DMXBreak="1" DMXOffset="1"/>
    </GeometryReference>
    <GeometryReference Name="Pixel 2" Geometry="PixelCell" Model="PixelModel">
     <Break DMXBreak="1" DMXOffset="4"/>
    </GeometryReference>
    <GeometryReference Name="Pixel 3" Geometry="PixelCell" Model="PixelModel">
     <Break DMXBreak="1" DMXOffset="7"/>
    </GeometryReference>
    <GeometryReference Name="Pixel 4" Geometry="PixelCell" Model="PixelModel">
     <Break DMXBreak="1" DMXOffset="10"/>
    </GeometryReference>
    <GeometryReference Name="Pixel 5" Geometry="PixelCell" Model="PixelModel">
     <Break DMXBreak="1" DMXOffset="13"/>
    </GeometryReference>
   </Geometry>
   <Geometry Name="PixelCell" Model="PixelModel">
    <Beam Name="PixelBeam" BeamAngle="40" LuminousFlux="400"/>
   </Geometry>
  </Geometries>
  <DMXModes>
   <DMXMode Name="16ch" Geometry="Bar">
    <DMXChannels>
     <DMXChannel DMXBreak="1" Offset="1" Geometry="PixelCell">
      <LogicalChannel Attribute="ColorAdd_R">
       <ChannelFunction Name="Red" Attribute="ColorAdd_R" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="2" Geometry="PixelCell">
      <LogicalChannel Attribute="ColorAdd_G">
       <ChannelFunction Name="Green" Attribute="ColorAdd_G" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="3" Geometry="PixelCell">
      <LogicalChannel Attribute="ColorAdd_B">
       <ChannelFunction Name="Blue" Attribute="ColorAdd_B" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
     <DMXChannel DMXBreak="1" Offset="16" Geometry="Bar">
      <LogicalChannel Attribute="Dimmer">
       <ChannelFunction Name="Master" Attribute="Dimmer" DMXFrom="0/1"/>
      </LogicalChannel>
     </DMXChannel>
    </DMXChannels>
   </DMXMode>
  </DMXModes>
 </FixtureType>
</GDTF>
"""

MATCHING_QXF = """<?xml version="1.0" encoding="UTF-8"?>
<FixtureDefinition xmlns="http://www.qlcplus.org/FixtureDefinition">
 <Creator><Name>Test</Name><Version>1</Version><Author>t</Author></Creator>
 <Manufacturer>Testlight</Manufacturer>
 <Model>Test Spot 60</Model>
 <Type>Moving Head</Type>
 <Channel Name="Dimmer" Preset="IntensityDimmer"/>
 <Mode Name="1ch"><Channel Number="0">Dimmer</Channel></Mode>
</FixtureDefinition>
"""


def _write_gdtf(dir_path, filename, description_xml):
    path = os.path.join(str(dir_path), filename)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('description.xml', description_xml)
    return path


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_library_cache()
    yield
    clear_library_cache()


@pytest.fixture()
def gdtf_dir(tmp_path, monkeypatch):
    d = tmp_path / "gdtf"
    d.mkdir()
    _write_gdtf(d, "Testlight@Test_Spot_60.gdtf", SPOT_DESCRIPTION)
    _write_gdtf(d, "Testlight@Test_Pixel_Bar_5.gdtf", BAR_DESCRIPTION)
    monkeypatch.setattr(fl, "fixture_search_dirs", lambda: [(str(d), "gdtf")])
    return d


# ---------------------------------------------------------------------------
# Canonical parse
# ---------------------------------------------------------------------------

def test_spot_parses_to_canonical_definition(gdtf_dir):
    defn = get_definition("Testlight", "Test Spot 60")
    assert defn is not None
    assert defn.source == 'gdtf'
    assert defn.gdtf_fixture_type_id == "11111111-2222-3333-4444-555555555555"
    assert defn.manufacturer == "Testlight"
    assert defn.model == "Test Spot 60"
    assert defn.qlc_type == "Moving Head"
    assert defn.legacy_type == "MH"
    assert defn.root is not None

    assert [m.name for m in defn.modes] == ["Standard"]
    mode = defn.modes[0]
    # 11 GDTF channels, Pan and Tilt 16-bit -> 13 QLC channels
    assert len(mode.channels) == 13
    assert [ref.number for ref in mode.channels] == list(range(13))

    by_number = {ref.number: ref.name for ref in mode.channels}
    assert by_number[0] == "Pan"
    assert by_number[1] == "Pan Fine"
    assert by_number[2] == "Tilt"
    assert by_number[3] == "Tilt Fine"
    assert by_number[4] == "Dimmer"
    assert by_number[5] == "Red"
    assert by_number[8] == "White"
    assert by_number[9] == "Color Wheel"
    assert by_number[10] == "Gobo Wheel"


def test_spot_presets_resolve_for_export_and_dmx(gdtf_dir):
    """The legacy dict + get_channels_by_property path (export, live DMX)."""
    legacy = get_definition("Testlight", "Test Spot 60").to_legacy_dict()
    channels = get_channels_by_property(
        legacy, "Standard",
        ["IntensityDimmer", "IntensityRed", "IntensityGreen", "IntensityBlue",
         "IntensityWhite", "PositionPan", "PositionTilt", "PositionPanFine",
         "PositionTiltFine", "ColorMacro", "GoboWheel",
         "ShutterStrobeSlowFast", "BeamZoomSmallBig"])

    def nums(prop):
        return [c['channel'] for c in channels.get(prop, [])]

    assert nums("PositionPan") == [0]
    assert nums("PositionPanFine") == [1]
    assert nums("PositionTilt") == [2]
    assert nums("PositionTiltFine") == [3]
    assert nums("IntensityDimmer") == [4]
    assert nums("IntensityRed") == [5]
    assert nums("IntensityWhite") == [8]
    assert nums("GoboWheel") == [10]
    assert nums("ShutterStrobeSlowFast") == [11]
    assert nums("BeamZoomSmallBig") == [12]
    # ColorMacro arrives via capability presets, carrying dmx ranges
    macro_entries = channels.get("ColorMacro", [])
    assert {e['channel'] for e in macro_entries} == {9}
    assert any(e.get('min') == 64 for e in macro_entries)  # Deep Red slot


def test_spot_color_wheel_slots_carry_srgb_hex(gdtf_dir):
    legacy = get_definition("Testlight", "Test Spot 60").to_legacy_dict()
    wheel_channel = next(ch for ch in legacy['channels']
                         if ch['name'] == 'Color Wheel')
    colors = [cap.get('color') for cap in wheel_channel['capabilities']]
    assert len(colors) == 3
    assert all(c and c.startswith('#') for c in colors)
    # Deep Red slot must decode to a red-dominant color
    red = colors[1]
    r, g, b = int(red[1:3], 16), int(red[3:5], 16), int(red[5:7], 16)
    assert r > 200 and r > g * 2 and r > b * 2


def test_spot_capability_detection(gdtf_dir):
    """The composable-renderer path: detect_capabilities on the
    synthesized root behaves like on a real QXF."""
    from utils.fixture_capabilities import detect_capabilities, Chassis, MovementType

    defn = get_definition("Testlight", "Test Spot 60")
    caps = detect_capabilities(defn.root, "Standard")

    assert caps.chassis == Chassis.MOVING_YOKE
    assert caps.movement is not None
    assert caps.movement.type == MovementType.YOKE
    assert caps.movement.pan_max_deg == 540.0
    assert caps.movement.tilt_max_deg == 270.0
    assert caps.color_mixing is not None
    assert caps.color_mixing.mode.name == 'RGBW'
    assert caps.color_wheel is not None
    assert len(caps.color_wheel.entries) >= 2
    assert caps.gobo_wheel is not None
    assert caps.dimmer_channel is not None
    assert caps.strobe_channel is not None
    assert caps.zoom_channel is not None
    assert caps.beam is not None
    assert caps.beam.min_deg == 12.0 and caps.beam.max_deg == 12.0
    # Real photometric data from the Beam node, not a power estimate
    assert caps.lumens_estimate == 8000.0
    # Dimensions from the root geometry's model (m -> mm -> m)
    assert caps.body_dims_m == pytest.approx((0.30, 0.40, 0.25))


def test_pixel_bar_heads_and_cells(gdtf_dir):
    from utils.fixture_capabilities import detect_capabilities, CellArray

    defn = get_definition("Testlight", "Test Pixel Bar 5")
    assert defn is not None
    assert defn.qlc_type == "LED Bar (Pixels)"
    assert defn.layout == (5, 1)

    mode = defn.modes[0]
    # 5 cells x RGB + master dimmer
    assert len(mode.channels) == 16
    assert len(mode.heads) == 5
    assert mode.heads[0] == [0, 1, 2]
    assert mode.heads[4] == [12, 13, 14]

    by_number = {ref.number: ref.name for ref in mode.channels}
    assert by_number[0] == "Red 1"
    assert by_number[12] == "Red 5"
    assert by_number[15] == "Dimmer"
    assert defn.legacy_type == "PIXELBAR"

    caps = detect_capabilities(defn.root, "16ch")
    assert isinstance(caps.emitter, CellArray)
    assert caps.emitter.width == 5 and caps.emitter.height == 1
    assert len(caps.emitter.cells) == 5


# ---------------------------------------------------------------------------
# Library integration
# ---------------------------------------------------------------------------

def test_gdtf_header_read_and_discovery(gdtf_dir):
    entries = fl.all_fixture_files()
    assert len(entries) == 2
    assert all(e['source'] == 'gdtf' for e in entries)
    path = fl.find_fixture_file("Testlight", "Test Pixel Bar 5")
    assert path is not None and path.endswith(".gdtf")


def test_gdtf_wins_over_qxf_for_same_identity(tmp_path, monkeypatch):
    gdtf_d = tmp_path / "gdtf"
    qxf_d = tmp_path / "qxf"
    gdtf_d.mkdir()
    qxf_d.mkdir()
    _write_gdtf(gdtf_d, "spot.gdtf", SPOT_DESCRIPTION)
    (qxf_d / "Testlight-Test-Spot-60.qxf").write_text(MATCHING_QXF, encoding="utf-8")

    # GDTF dir first, as in the real fixture_search_dirs ordering
    monkeypatch.setattr(fl, "fixture_search_dirs",
                        lambda: [(str(gdtf_d), "gdtf"), (str(qxf_d), "bundled")])
    defn = get_definition("Testlight", "Test Spot 60")
    assert defn.source == 'gdtf'
    assert len(defn.modes[0].channels) == 13  # not the 1ch qxf

    # And the qxf is used when it is the only definition
    clear_library_cache()
    monkeypatch.setattr(fl, "fixture_search_dirs",
                        lambda: [(str(qxf_d), "bundled")])
    defn = get_definition("Testlight", "Test Spot 60")
    assert defn.source == 'qxf'


def test_broken_gdtf_is_reported_not_fatal(tmp_path, monkeypatch, capsys):
    d = tmp_path / "gdtf"
    d.mkdir()
    (d / "broken.gdtf").write_bytes(b"this is not a zip archive")
    monkeypatch.setattr(fl, "fixture_search_dirs", lambda: [(str(d), "gdtf")])
    assert fl.find_fixture_file("Testlight", "Test Spot 60") is None
    assert list(fl.iter_definitions()) == []


# ---------------------------------------------------------------------------
# End to end: a GDTF-defined fixture is a first-class citizen downstream
# ---------------------------------------------------------------------------

def _config_with_spot():
    from config.models import Configuration, Fixture, FixtureGroup, FixtureMode

    defn = get_definition("Testlight", "Test Spot 60")
    fixture = Fixture(
        universe=1, address=1,
        manufacturer="Testlight", model="Test Spot 60",
        name="Spot 1", group="Movers",
        current_mode="Standard",
        available_modes=[FixtureMode(name=m.name, channels=len(m.channels))
                         for m in defn.modes],
        type=defn.legacy_type,
        x=0.0, y=0.0, z=0.0,
    )
    config = Configuration()
    config.fixtures.append(fixture)
    config.groups["Movers"] = FixtureGroup("Movers", [fixture])
    config.ensure_universes_for_fixtures()
    return config


def test_gdtf_fixture_exports_to_qxw(gdtf_dir, tmp_path):
    """create_qlc_workspace consumes the GDTF definition via the library
    with no format awareness: fixture element + channels groups appear."""
    import xml.etree.ElementTree as ET
    from utils.create_workspace import create_qlc_workspace
    from utils import fixture_utils

    fixture_utils.clear_fixture_definitions_cache()
    # clear_fixture_definitions_cache resets the library caches, which
    # would undo the gdtf_dir monkeypatched search path's cached entries;
    # lookups after it re-scan through the (still patched) search dirs.
    config = _config_with_spot()
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    workspace_out = os.path.join(repo_root, "workspace.qxw")
    try:
        create_qlc_workspace(config, None)
        tree = ET.parse(workspace_out)
    finally:
        fixture_utils.clear_fixture_definitions_cache()
        if os.path.exists(workspace_out):
            os.remove(workspace_out)

    root = tree.getroot()
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    fixture_el = root.find(".//Fixture")
    assert fixture_el is not None
    assert fixture_el.find("Manufacturer").text == "Testlight"
    assert fixture_el.find("Model").text == "Test Spot 60"
    assert fixture_el.find("Mode").text == "Standard"
    assert int(fixture_el.find("Channels").text) == 13

    groups = root.findall(".//ChannelsGroup")
    assert groups, "capability channels groups generated from GDTF presets"


def test_gdtf_fixture_visualizer_payload(gdtf_dir):
    """build_fixtures_payload picks up physical/beam/movement data that
    originated in the GDTF geometry tree."""
    from utils.tcp.protocol import VisualizerProtocol

    config = _config_with_spot()
    payload = VisualizerProtocol.build_fixtures_payload(config)
    assert len(payload) == 1
    entry = payload[0]
    assert entry['fixture_type'] == 'MH'
    assert entry['beam_angle'] == 12.0
    assert entry['pan_max'] == 540.0
    assert entry['tilt_max'] == 270.0
    assert entry['lumens'] == 8000.0
    assert entry['physical']['width'] == pytest.approx(0.30)
    mapping = entry['channel_mapping']
    assert mapping, "semantic channel mapping present"
    functions = set(mapping.values())
    assert {'pan', 'tilt', 'dimmer', 'red', 'green', 'blue'} <= functions


# ---------------------------------------------------------------------------
# Color conversion
# ---------------------------------------------------------------------------

def test_cie_xyy_to_hex_known_points():
    assert cie_xyy_to_hex(0.3127, 0.3290, 100.0) == '#FFFFFF'   # D65 white
    red = cie_xyy_to_hex(0.64, 0.33, 21.26)                     # sRGB red primary
    r, g, b = int(red[1:3], 16), int(red[3:5], 16), int(red[5:7], 16)
    assert r >= 250 and g < 40 and b < 40
    assert cie_xyy_to_hex(None, None, None) == '#FFFFFF'        # degenerate
    assert cie_xyy_to_hex(0.3, 0.0, 50.0) == '#FFFFFF'          # y == 0
