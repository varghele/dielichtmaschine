# tests/unit/test_master_presets.py
"""Unit tests for master preset generation and virtual console export."""

import pytest
import xml.etree.ElementTree as ET
from config.models import (
    Configuration, Fixture, FixtureMode, FixtureGroup, Universe, Song, ShowPart
)


@pytest.fixture
def rgb_fixture():
    return Fixture(
        universe=1, address=1, manufacturer="Generic", model="RGBW",
        name="F1", group="Wash", current_mode="4ch",
        available_modes=[FixtureMode("4ch", 4)]
    )


@pytest.fixture
def simple_config(rgb_fixture):
    return Configuration(
        fixtures=[rgb_fixture],
        groups={"Wash": FixtureGroup("Wash", [rgb_fixture])},
        universes={1: Universe(id=1, name="Uni 1", output={"plugin": "ArtNet"})},
        songs={"S1": Song(name="S1", parts=[
            ShowPart(name="P1", color="#fff", signature="4/4", bpm=120, num_bars=4, transition="instant")
        ])}
    )


class TestMasterPresetsStructure:

    def test_returns_flat_dict(self):
        """create_master_presets should return a flat Dict[str, int]."""
        from utils.to_xml.preset_scenes_to_xml import create_master_presets

        engine = ET.Element("Engine")
        config = Configuration(
            groups={"G": FixtureGroup("G", [])},
        )
        result, next_id = create_master_presets(engine, 100, config, {}, {})
        assert isinstance(result, dict)
        # All values should be ints (function IDs)
        for k, v in result.items():
            assert isinstance(k, str)
            assert isinstance(v, int)

    def test_key_prefixes(self):
        """Keys should have Scene_, Color_, or Effect_ prefixes."""
        from utils.to_xml.preset_scenes_to_xml import create_master_presets

        engine = ET.Element("Engine")
        config = Configuration(
            groups={"G": FixtureGroup("G", [])},
        )
        result, _ = create_master_presets(engine, 100, config, {}, {})
        valid_prefixes = ("Scene_", "Color_", "Effect_")
        for k in result:
            assert any(k.startswith(p) for p in valid_prefixes), \
                f"Key '{k}' doesn't start with a valid prefix"

    def test_no_movement_keys(self):
        """Movement_ keys should not be generated (removed feature)."""
        from utils.to_xml.preset_scenes_to_xml import create_master_presets

        engine = ET.Element("Engine")
        config = Configuration(
            groups={"G": FixtureGroup("G", [])},
        )
        result, _ = create_master_presets(engine, 100, config, {}, {})
        for k in result:
            assert not k.startswith("Movement_"), f"Unexpected movement key: {k}"


class TestVirtualConsoleConstants:

    def test_button_size(self):
        from utils.to_xml.virtual_console_to_xml import BUTTON_SIZE
        assert BUTTON_SIZE == 40

    def test_show_button_size(self):
        from utils.to_xml.virtual_console_to_xml import SHOW_BUTTON_SIZE
        assert SHOW_BUTTON_SIZE == 75


class TestProgressDialogWithLog:

    def test_import(self):
        from gui.progress_manager import ProgressDialogWithLog, _LogWriter
        assert ProgressDialogWithLog is not None
        assert _LogWriter is not None

    def test_log_writer_buffers_lines(self):
        """LogWriter should buffer until newline."""
        from gui.progress_manager import _LogWriter

        mock_dialog = type('MockDialog', (), {
            'append_log': lambda self, text: collected.append(text)
        })()
        collected = []

        writer = _LogWriter(mock_dialog)
        writer.write("hello ")
        assert len(collected) == 0  # No newline yet

        writer.write("world\n")
        assert len(collected) == 1
        assert collected[0] == "hello world"

    def test_log_writer_flush(self):
        from gui.progress_manager import _LogWriter

        collected = []
        mock_dialog = type('MockDialog', (), {
            'append_log': lambda self, text: collected.append(text)
        })()

        writer = _LogWriter(mock_dialog)
        writer.write("partial")
        writer.flush()
        assert len(collected) == 1
        assert collected[0] == "partial"
