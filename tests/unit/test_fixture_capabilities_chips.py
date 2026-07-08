"""Pure helpers behind the Fixtures-tab inspector (reference screen 02):

- derive_capability_chips: CAPABILITIES chip texts from a mode's
  channel dicts (PAN/TILT, RGB/RGBW/CMY, DIMMER, GOBO xN, PRISM,
  STROBE, ZOOM, FOCUS)
- channel_map_rows: "NN CHANNELNAME" + 'fine' qualifier rows
- mode_channel_dicts: mode resolution against the legacy definition
  dict shape (exact name, channel-count fallback, None when absent)
- format_address_range / type_label / group_role_line: table + groups
  panel formatting

No Qt required - everything here is data in, data out.
"""

from __future__ import annotations

from gui.tabs.fixtures_tab import (
    channel_map_rows,
    derive_capability_chips,
    format_address_range,
    group_role_line,
    mode_channel_dicts,
    type_label,
)


def ch(name, preset=None, caps=()):
    return {
        "name": name,
        "preset": preset,
        "capabilities": [{"name": c} for c in caps],
    }


# ---------------------------------------------------------------------------
# derive_capability_chips
# ---------------------------------------------------------------------------

class TestCapabilityChips:
    def test_full_moving_head(self):
        channels = [
            ch("Pan", "PositionPan"),
            ch("Tilt", "PositionTilt"),
            ch("Dimmer", "IntensityMasterDimmer"),
            ch("Strobe", "ShutterStrobeSlowFast"),
            ch("Red", "IntensityRed"),
            ch("Green", "IntensityGreen"),
            ch("Blue", "IntensityBlue"),
            ch("White", "IntensityWhite"),
            ch("Gobo Wheel", caps=("Open", "Gobo 1", "Gobo 2", "Gobo 3")),
            ch("Prism"),
            ch("Zoom", "BeamZoomSmallBig"),
            ch("Focus", "BeamFocusNearFar"),
        ]
        assert derive_capability_chips(channels) == [
            "PAN/TILT", "RGBW", "DIMMER", "GOBO x3", "PRISM",
            "STROBE", "ZOOM", "FOCUS",
        ]

    def test_rgb_without_white(self):
        channels = [ch("Red"), ch("Green"), ch("Blue")]
        assert derive_capability_chips(channels) == ["RGB"]

    def test_cmy(self):
        channels = [ch("Cyan"), ch("Magenta"), ch("Yellow")]
        assert derive_capability_chips(channels) == ["CMY"]

    def test_pan_alone_is_not_pan_tilt(self):
        assert derive_capability_chips([ch("Pan")]) == []

    def test_shutter_counts_as_strobe(self):
        assert derive_capability_chips([ch("Shutter")]) == ["STROBE"]

    def test_gobo_without_named_slots_has_no_count(self):
        channels = [ch("Gobo Wheel", caps=("Open", "Stars", "Dots"))]
        assert derive_capability_chips(channels) == ["GOBO"]

    def test_gobo_rotation_channel_is_not_a_wheel(self):
        assert derive_capability_chips([ch("Gobo Rotation")]) == []

    def test_dimmer_only(self):
        channels = [ch("Dimmer", "IntensityDimmer")]
        assert derive_capability_chips(channels) == ["DIMMER"]

    def test_empty(self):
        assert derive_capability_chips([]) == []
        assert derive_capability_chips(None) == []

    def test_matches_via_preset_when_names_are_opaque(self):
        channels = [
            ch("Ch 1", "PositionPan"),
            ch("Ch 2", "PositionTilt"),
        ]
        assert derive_capability_chips(channels) == ["PAN/TILT"]


# ---------------------------------------------------------------------------
# channel_map_rows
# ---------------------------------------------------------------------------

class TestChannelMapRows:
    def test_rows_are_zero_padded_caps_with_fine_qualifier(self):
        rows = channel_map_rows([
            ch("Pan"),
            ch("Pan Fine"),
            ch("Dimmer"),
        ])
        assert rows == [
            ("01 PAN", ""),
            ("02 PAN FINE", "fine"),
            ("03 DIMMER", ""),
        ]

    def test_fine_via_preset(self):
        rows = channel_map_rows([ch("Pan low byte", "PositionPanFine")])
        assert rows == [("01 PAN LOW BYTE", "fine")]

    def test_unnamed_channel_gets_placeholder(self):
        assert channel_map_rows([ch("")]) == [("01 CH 1", "")]

    def test_empty(self):
        assert channel_map_rows([]) == []
        assert channel_map_rows(None) == []


# ---------------------------------------------------------------------------
# mode_channel_dicts (legacy definition dict shape)
# ---------------------------------------------------------------------------

def _definition():
    return {
        "manufacturer": "TestMfr",
        "model": "TestModel",
        "channels": [
            ch("Dimmer", "IntensityMasterDimmer"),
            ch("Red", "IntensityRed"),
            ch("Green", "IntensityGreen"),
        ],
        "modes": [
            {"name": "2ch", "channels": [
                {"number": 0, "name": "Dimmer"},
                {"number": 1, "name": "Red"},
            ]},
            {"name": "3ch", "channels": [
                {"number": 0, "name": "Dimmer"},
                {"number": 1, "name": "Red"},
                {"number": 2, "name": "Green"},
            ]},
        ],
    }


class TestModeChannelDicts:
    def test_exact_mode_name_match(self):
        channels = mode_channel_dicts(_definition(), "2ch")
        assert [c["name"] for c in channels] == ["Dimmer", "Red"]
        assert channels[0]["preset"] == "IntensityMasterDimmer"

    def test_channel_count_fallback_when_name_drifts(self):
        channels = mode_channel_dicts(_definition(), "Standard",
                                      channel_count=3)
        assert [c["name"] for c in channels] == ["Dimmer", "Red", "Green"]

    def test_no_match_returns_none(self):
        assert mode_channel_dicts(_definition(), "Standard",
                                  channel_count=7) is None
        assert mode_channel_dicts(None, "2ch") is None
        assert mode_channel_dicts({}, "2ch") is None

    def test_unresolved_ref_keeps_name(self):
        definition = _definition()
        definition["modes"][0]["channels"].append(
            {"number": 2, "name": "Mystery"})
        channels = mode_channel_dicts(definition, "2ch")
        assert channels[2] == {"name": "Mystery", "preset": None,
                               "capabilities": []}

    def test_refs_ordered_by_number(self):
        definition = _definition()
        definition["modes"][0]["channels"] = [
            {"number": 1, "name": "Red"},
            {"number": 0, "name": "Dimmer"},
        ]
        channels = mode_channel_dicts(definition, "2ch")
        assert [c["name"] for c in channels] == ["Dimmer", "Red"]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_address_range_zero_padded_hyphen_minus(self):
        assert format_address_range(1, 8) == "001-008"
        assert format_address_range(9, 8) == "009-016"
        assert format_address_range(505, 16) == "505-520"
        assert format_address_range(7, 1) == "007-007"
        # Degenerate channel counts still render a 1-wide range.
        assert format_address_range(3, 0) == "003-003"

    def test_type_labels(self):
        assert type_label("PAR") == "PAR"
        assert type_label("MH") == "MOVING HEAD"
        assert type_label("WASH") == "WASH"
        assert type_label("BAR") == "LED BAR"
        assert type_label("PIXELBAR") == "PIXEL BAR"
        assert type_label("SUNSTRIP") == "SUNSTRIP"
        # Unknown strings pass through in caps; empty defaults to PAR.
        assert type_label("laser") == "LASER"
        assert type_label("") == "PAR"
        assert type_label(None) == "PAR"

    def test_group_role_line(self):
        from config.models import Fixture, FixtureGroup, FixtureMode

        def fx(name, ftype):
            return Fixture(
                universe=1, address=1, manufacturer="M", model="X",
                name=name, group="G", current_mode="Std",
                available_modes=[FixtureMode(name="Std", channels=1)],
                type=ftype,
            )

        group = FixtureGroup("G", [fx("a", "MH"), fx("b", "MH"),
                                   fx("c", "PAR")],
                             lighting_role="accent")
        assert group_role_line(group) == "Role: accent · MH x2 · PAR x1"

        group_no_role = FixtureGroup("G", [fx("a", "PAR")])
        assert group_role_line(group_no_role) == "PAR x1"

        assert group_role_line(FixtureGroup("G", [])) == ""
