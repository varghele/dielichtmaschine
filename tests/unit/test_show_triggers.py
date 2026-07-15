# tests/unit/test_show_triggers.py
"""Unit tests for show trigger configuration and export."""

import os
import pytest
import tempfile
import xml.etree.ElementTree as ET
from config.models import (
    Configuration, Song, ShowPart, MidiInputDevice,
    Fixture, FixtureMode, FixtureGroup, Universe
)


class TestMidiInputDevice:

    def test_creation(self):
        dev = MidiInputDevice(
            name="Akai APC Mini mk2",
            uid="apc mini mk2",
            profile="Akai APC Mini mk2",
            universe_id=2,
            line=1
        )
        assert dev.name == "Akai APC Mini mk2"
        assert dev.universe_id == 2
        assert dev.line == 1

    def test_default_line(self):
        dev = MidiInputDevice(name="Test", uid="test", profile="Test", universe_id=0)
        assert dev.line == 1


class TestShowTriggerFields:

    def test_defaults(self):
        show = Song(name="Test")
        assert show.trigger_device == ""
        assert show.trigger_channel == -1

    def test_with_trigger(self):
        show = Song(name="Test", trigger_device="Akai APC Mini mk2", trigger_channel=184)
        assert show.trigger_device == "Akai APC Mini mk2"
        assert show.trigger_channel == 184


class TestTriggerSerialization:

    def _make_config(self):
        fixture = Fixture(
            universe=1, address=1, manufacturer="Test", model="Par",
            name="F1", group="G1", current_mode="Std",
            available_modes=[FixtureMode("Std", 4)]
        )
        config = Configuration(
            fixtures=[fixture],
            groups={"G1": FixtureGroup("G1", [fixture])},
            universes={1: Universe(id=1, name="Uni 1", output={"plugin": "ArtNet"})},
            songs={
                "ShowA": Song(
                    name="ShowA",
                    trigger_device="Akai APC Mini mk2",
                    trigger_channel=184,
                    parts=[ShowPart(name="Intro", color="#ff0000", signature="4/4",
                                   bpm=120.0, num_bars=4, transition="instant")]
                ),
                "ShowB": Song(
                    name="ShowB",
                    parts=[ShowPart(name="Intro", color="#00ff00", signature="4/4",
                                   bpm=120.0, num_bars=4, transition="instant")]
                ),
            },
            midi_input_devices=[
                MidiInputDevice(name="Akai APC Mini mk2", uid="apc mini mk2",
                                profile="Akai APC Mini mk2", universe_id=2, line=1)
            ]
        )
        return config

    def test_save_load_roundtrip(self):
        config = self._make_config()
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            tmp_path = f.name

        try:
            config.save(tmp_path)
            loaded = Configuration.load(tmp_path)

            # Check show triggers
            assert loaded.songs["ShowA"].trigger_device == "Akai APC Mini mk2"
            assert loaded.songs["ShowA"].trigger_channel == 184
            assert loaded.songs["ShowB"].trigger_device == ""
            assert loaded.songs["ShowB"].trigger_channel == -1

            # Check MIDI devices
            assert len(loaded.midi_input_devices) == 1
            dev = loaded.midi_input_devices[0]
            assert dev.name == "Akai APC Mini mk2"
            assert dev.uid == "apc mini mk2"
            assert dev.universe_id == 2
        finally:
            os.unlink(tmp_path)

    def test_save_without_triggers(self):
        """Config with no triggers should save/load cleanly."""
        config = Configuration(
            songs={"S1": Song(name="S1", parts=[
                ShowPart(name="P1", color="#fff", signature="4/4", bpm=120, num_bars=4, transition="instant")
            ])}
        )
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            tmp_path = f.name
        try:
            config.save(tmp_path)
            loaded = Configuration.load(tmp_path)
            assert loaded.songs["S1"].trigger_device == ""
            assert loaded.songs["S1"].trigger_channel == -1
            assert len(loaded.midi_input_devices) == 0
        finally:
            os.unlink(tmp_path)


class TestTriggerExportXML:

    def _make_config_with_trigger(self):
        fixture = Fixture(
            universe=1, address=1, manufacturer="Test", model="Par",
            name="F1", group="G1", current_mode="Std",
            available_modes=[FixtureMode("Std", 4)]
        )
        return Configuration(
            fixtures=[fixture],
            groups={"G1": FixtureGroup("G1", [fixture])},
            universes={1: Universe(id=1, name="Uni 1", output={"plugin": "ArtNet"})},
            songs={
                "TestShow": Song(
                    name="TestShow",
                    trigger_device="Akai APC Mini mk2",
                    trigger_channel=184,
                    parts=[ShowPart(name="P", color="#f00", signature="4/4",
                                   bpm=120, num_bars=4, transition="instant")]
                ),
            },
            midi_input_devices=[
                MidiInputDevice(name="Akai APC Mini mk2", uid="apc mini mk2",
                                profile="Akai APC Mini mk2", universe_id=2, line=1)
            ]
        )

    def test_midi_universe_exported(self):
        """MIDI input universe should appear in InputOutputMap."""
        config = self._make_config_with_trigger()
        from utils.to_xml.setup_to_xml import create_universe_elements

        iom = ET.Element("InputOutputMap")
        create_universe_elements(iom, config)

        universes = iom.findall("Universe")
        midi_universes = [u for u in universes if u.find("Input") is not None]
        assert len(midi_universes) == 1

        midi_u = midi_universes[0]
        assert midi_u.get("ID") == "2"
        midi_input = midi_u.find("Input")
        assert midi_input.get("Plugin") == "MIDI"
        assert midi_input.get("UID") == "apc mini mk2"
        assert midi_input.get("Profile") == "Akai APC Mini mk2"

    def test_no_midi_universe_when_no_devices(self):
        """No MIDI universe when no devices configured."""
        config = Configuration(
            universes={1: Universe(id=1, name="Uni", output={"plugin": "ArtNet"})}
        )
        iom = ET.Element("InputOutputMap")
        from utils.to_xml.setup_to_xml import create_universe_elements
        create_universe_elements(iom, config)

        for u in iom.findall("Universe"):
            assert u.find("Input") is None
