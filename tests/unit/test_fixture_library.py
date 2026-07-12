# tests/unit/test_fixture_library.py
"""Unit tests for utils/fixture_library.py (Phase 0 fixture-definition
unification, docs/gdtf-integration-plan.md).

The equivalence tests embed the pre-unification QXF parser verbatim as a
reference implementation and assert the canonical parse reproduces its
output for every bundled fixture (modulo the documented junk-channel wart:
the old ``.//Channel`` XPath swept up per-mode channel references as
``{'name': None, ...}`` entries that no consumer could match).
"""
import os
import xml.etree.ElementTree as ET

import pytest

from utils import fixture_library as fl
from utils.fixture_library import (
    FixtureDefinition,
    all_fixture_files,
    clear_library_cache,
    find_fixture_file,
    fixture_search_dirs,
    get_definition,
    iter_definitions,
    parse_fixture_file,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CUSTOM_FIXTURES = os.path.join(REPO_ROOT, "custom_fixtures")

BUNDLED_QXFS = sorted(
    os.path.join(CUSTOM_FIXTURES, f)
    for f in os.listdir(CUSTOM_FIXTURES)
    if f.endswith(".qxf")
)

# The bundled par's model string carries a trailing space; identity is verbatim.
TRAILING_SPACE_MODEL = ("Stairville", "Retro Flat Par 18x12W RGBW ")


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_library_cache()
    yield
    clear_library_cache()


@pytest.fixture()
def bundled_only(monkeypatch):
    """Restrict the search to custom_fixtures/ so tests stay hermetic and
    do not depend on a QLC+ install being present (or absent)."""
    monkeypatch.setattr(
        fl, "fixture_search_dirs", lambda: [(CUSTOM_FIXTURES, "bundled")]
    )


# ---------------------------------------------------------------------------
# Reference implementation: the pre-unification parser, verbatim
# ---------------------------------------------------------------------------

def _reference_parse(fixture_path):
    """utils/fixture_utils.py::_parse_fixture_file as it was before Phase 0."""
    ns = {"": "http://www.qlcplus.org/FixtureDefinition"}
    color_name_to_rgb = {
        "White": "#FFFFFF", "Red": "#FF0000", "Green": "#00FF00",
        "Blue": "#0000FF", "Cyan": "#00FFFF", "Magenta": "#FF00FF",
        "Yellow": "#FFFF00", "Amber": "#FFBF00", "Orange": "#FF7F00",
        "Purple": "#7F00FF", "Pink": "#FF007F", "UV": "#8000FF",
        "Lime": "#BFFF00",
    }
    tree = ET.parse(fixture_path)
    root = tree.getroot()
    manufacturer = root.find(".//Manufacturer", ns).text
    model = root.find(".//Model", ns).text

    channels_info = []
    for channel in root.findall(".//Channel", ns):
        channel_data = {
            "name": channel.get("Name"),
            "preset": channel.get("Preset"),
            "group": channel.find("Group", ns).text if channel.find("Group", ns) is not None else None,
            "capabilities": [],
        }
        for capability in channel.findall("Capability", ns):
            cap_data = {
                "min": int(capability.get("Min")),
                "max": int(capability.get("Max")),
                "preset": capability.get("Preset"),
                "name": capability.text,
            }
            if capability.get("Color1") or capability.get("Color2"):
                cap_data["color"] = capability.get("Color1")
            elif capability.get("Res1"):
                cap_data["color"] = capability.get("Res1")
            elif capability.text and any(color in capability.text for color in color_name_to_rgb):
                for color_name, hex_value in color_name_to_rgb.items():
                    if color_name.lower() in capability.text.lower():
                        cap_data["color"] = hex_value
                        break
            channel_data["capabilities"].append(cap_data)
        channels_info.append(channel_data)

    modes_info = []
    for mode in root.findall(".//Mode", ns):
        mode_data = {"name": mode.get("Name"), "channels": []}
        for channel in mode.findall("Channel", ns):
            mode_data["channels"].append({
                "number": int(channel.get("Number")),
                "name": channel.text,
            })
        modes_info.append(mode_data)

    return {
        "manufacturer": manufacturer,
        "model": model,
        "channels": channels_info,
        "modes": modes_info,
    }


# ---------------------------------------------------------------------------
# Parse equivalence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("qxf_path", BUNDLED_QXFS, ids=os.path.basename)
def test_legacy_dict_matches_reference_parser(qxf_path):
    reference = _reference_parse(qxf_path)
    # Drop the junk entries the old .//Channel XPath swept up from
    # <Mode>/<Head> channel references (no Name attribute).
    reference["channels"] = [
        ch for ch in reference["channels"] if ch["name"] is not None
    ]

    legacy = parse_fixture_file(qxf_path).to_legacy_dict()
    # 'physical' (pan/tilt focus ranges) is additive surface the reference
    # parser never produced; it gets its own tests.
    legacy.pop("physical")
    assert legacy == reference


@pytest.mark.parametrize("qxf_path", BUNDLED_QXFS, ids=os.path.basename)
def test_canonical_parse_has_no_junk_channels(qxf_path):
    defn = parse_fixture_file(qxf_path)
    assert all(ch.name is not None for ch in defn.channels)
    assert defn.modes, "every bundled fixture has at least one mode"
    for mode in defn.modes:
        assert all(isinstance(ref.number, int) for ref in mode.channels)


def test_parse_carries_focus_ranges():
    # A mover's <Physical><Focus PanMax TiltMax> lands on the canonical
    # model and rides the legacy dict's additive 'physical' key (the
    # live/playback aiming reads it via FixtureChannelMap).
    defn = parse_fixture_file(
        os.path.join(CUSTOM_FIXTURES, "Martin-MAC-Aura.qxf"))
    assert defn.pan_max > 0
    assert defn.tilt_max > 0
    legacy = defn.to_legacy_dict()
    assert legacy["physical"] == {"pan_max": defn.pan_max,
                                  "tilt_max": defn.tilt_max}


def test_parse_carries_type_layout_and_root():
    defn = parse_fixture_file(
        os.path.join(CUSTOM_FIXTURES, "Showtec-Sunstrip-Active.qxf"))
    assert defn.manufacturer == "Showtec"
    assert defn.qlc_type != ""
    assert defn.legacy_type in {"MH", "PIXELBAR", "WASH", "BAR", "SUNSTRIP", "PAR"}
    assert defn.layout[0] >= 1 and defn.layout[1] >= 1
    assert defn.root is not None  # analysis passes (capabilities) reuse it


def test_summary_shape():
    defn = parse_fixture_file(
        os.path.join(CUSTOM_FIXTURES, "Martin-MAC-Aura.qxf"))
    summary = defn.summary()
    assert summary["manufacturer"] == "Martin"
    assert summary["type"] == defn.legacy_type
    assert summary["modes"], "modes list must not be empty"
    name, count = summary["modes"][0]
    assert isinstance(name, str) and isinstance(count, int)


# ---------------------------------------------------------------------------
# Discovery, index, caching
# ---------------------------------------------------------------------------

def test_search_dirs_priority_order_and_tags():
    """gdtf_fixtures/ (if present) first, then bundled custom_fixtures/,
    then the QLC+ library dirs. The gdtf dir only appears when it exists
    on the machine, so assert order, not absolute positions."""
    dirs = fixture_search_dirs()
    assert dirs, "search dirs must not be empty"
    sources = [source for _path, source in dirs]
    assert "bundled" in sources
    if "gdtf" in sources:
        assert sources.index("gdtf") < sources.index("bundled")
        assert dirs[sources.index("gdtf")][0].endswith("gdtf_fixtures")
    bundled_idx = sources.index("bundled")
    assert dirs[bundled_idx][0].endswith("custom_fixtures")
    assert all(s == "library" for s in sources[bundled_idx + 1:])


def test_find_fixture_file_verbatim_identity(bundled_only):
    path = find_fixture_file(*TRAILING_SPACE_MODEL)
    assert path is not None and path.endswith(".qxf")
    # Stripped model must NOT match: identity is verbatim.
    assert find_fixture_file("Stairville", "Retro Flat Par 18x12W RGBW") is None


def test_find_fixture_file_negative_cached(bundled_only):
    assert find_fixture_file("Nobody", "No Such Fixture") is None
    # Second lookup is a pure cache hit (full scan already done).
    assert find_fixture_file("Nobody", "No Such Fixture") is None


def test_get_definition_cached_and_cleared(bundled_only):
    d1 = get_definition("Martin", "MAC Aura")
    assert d1 is not None
    assert get_definition("Martin", "MAC Aura") is d1  # cache hit
    clear_library_cache()
    d2 = get_definition("Martin", "MAC Aura")
    assert d2 is not None and d2 is not d1  # re-parsed after clear


def test_iter_definitions_unique_and_complete(bundled_only):
    defs = list(iter_definitions())
    assert len(defs) == len(BUNDLED_QXFS)
    keys = [d.key for d in defs]
    assert len(keys) == len(set(keys))
    assert TRAILING_SPACE_MODEL in keys


def test_all_fixture_files_shape(bundled_only):
    entries = all_fixture_files()
    assert len(entries) == len(BUNDLED_QXFS)
    entry = entries[0]
    assert set(entry) == {"manufacturer", "model", "path", "source"}
    assert entry["source"] == "bundled"


# ---------------------------------------------------------------------------
# fixture_utils delegation keeps its public surface
# ---------------------------------------------------------------------------

def test_fixture_utils_reexports_and_legacy_loader(bundled_only):
    from utils.fixture_utils import (
        determine_fixture_type,          # noqa: F401 - re-export must exist
        load_fixture_definitions_from_qlc,
        get_fixture_layout,
    )

    defs = load_fixture_definitions_from_qlc({("Martin", "MAC Aura")})
    assert set(defs) == {"Martin_MAC Aura"}
    assert defs["Martin_MAC Aura"]["manufacturer"] == "Martin"
    assert defs["Martin_MAC Aura"]["channels"], "channels present"
    assert defs["Martin_MAC Aura"]["modes"], "modes present"

    layout = get_fixture_layout("Showtec", "Sunstrip Active")
    assert set(layout) == {"width", "height"}
    assert layout["width"] >= 1


def test_fixture_utils_cache_clear_clears_library(bundled_only):
    from utils import fixture_utils

    fixture_utils.get_cached_fixture_definitions({("Martin", "MAC Aura")})
    assert fixture_utils._fixture_definitions_cache
    d1 = get_definition("Martin", "MAC Aura")
    fixture_utils.clear_fixture_definitions_cache()
    assert not fixture_utils._fixture_definitions_cache
    assert get_definition("Martin", "MAC Aura") is not d1  # library cache dropped
