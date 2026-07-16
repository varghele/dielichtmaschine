# tests/unit/test_morph_preview_ui.py
"""The morph wizard's side-by-side preview scrub (v1.5b phase 3
consumption of utils/morph/preview.render_pair): renders ON CLICK ONLY
(construction and review never render, slider ticks never render), the
worker runs off-thread (monkeypatched synchronous here, same pattern as
test_gdtf_share), a None side shows the unavailable placeholder, and
the slider bounds follow the selected song's duration. Offscreen;
render_pair is stubbed to write real tiny PNGs - no GL."""

import pytest

from PyQt6 import QtGui

from config.models import (ColourBlock, Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, ShowPart,
                           Song, TimelineData, Universe)


def _fixture(name, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _group(name, fixtures, caps):
    group = FixtureGroup(name, fixtures)
    group.capabilities = FixtureGroupCapabilities(
        has_dimmer="dimmer" in caps, has_colour="colour" in caps,
        has_movement="movement" in caps, has_special="special" in caps)
    return group


def _config(groups, songs=None):
    fixtures = [f for g in groups for f in g.fixtures]
    cfg = Configuration(fixtures=fixtures,
                        groups={g.name: g for g in groups},
                        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = songs or {}
    return cfg


def _song(name, num_bars=8):
    """4/4 at 120 BPM: one bar = 2 s, so num_bars=8 -> 16 s."""
    lane = LightLane(
        name="Pars", fixture_targets=["PARS"],
        light_blocks=[LightBlock(
            start_time=0.0, end_time=16.0, effect_name="x",
            dimmer_blocks=[DimmerBlock(0.0, 16.0, intensity=200.0)],
            colour_blocks=[ColourBlock(0.0, 16.0, red=255.0)])])
    return Song(name=name,
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=num_bars,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[lane]))


@pytest.fixture
def source_and_target():
    songs = {"S": _song("S", num_bars=8),     # 16 s
             "T": _song("T", num_bars=4)}     # 8 s
    source = _config([_group("PARS", [_fixture("p1")],
                             {"dimmer", "colour"})], songs=songs)
    target = _config([_group("WASH", [_fixture("w1", group="WASH")],
                             {"dimmer", "colour"})])
    return source, target


def sync_start(worker):
    """Run the preview worker inline: signals fire immediately."""
    worker.run()
    worker.finished.emit()


@pytest.fixture
def synchronous_workers(monkeypatch):
    from gui.dialogs import morph_wizard as mod
    monkeypatch.setattr(mod._PreviewWorker, "start", sync_start)


def _wizard(source, target):
    from gui.dialogs.morph_wizard import MorphWizard
    wizard = MorphWizard(source, source_path="master.lms")
    wizard.set_target_config(target, "venue.lms")
    lane = source.songs["S"].timeline_data.lanes[0]
    wizard.patchbay.add_edge(lane.lane_id, "dimmer", "WASH")
    wizard.patchbay.add_edge(lane.lane_id, "colour", "WASH")
    return wizard


def _write_png(path):
    image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(10, 20, 30))
    assert image.save(path)
    return path


def _stub_render_pair(monkeypatch, calls, sides=("src", "dst")):
    """render_pair stand-in writing real tiny PNGs; None per side on
    demand. Records every call's kwargs-of-interest."""
    import os

    def fake(source_config, source_song, target_config, morphed_song,
             time_s, output_dir, **kwargs):
        calls.append({"source_config": source_config,
                      "source_song": source_song,
                      "target_config": target_config,
                      "morphed_song": morphed_song,
                      "time_s": time_s,
                      "output_dir": output_dir})
        src = (_write_png(os.path.join(output_dir, "src.png"))
               if "src" in sides else None)
        dst = (_write_png(os.path.join(output_dir, "dst.png"))
               if "dst" in sides else None)
        return src, dst

    monkeypatch.setattr("utils.morph.preview.render_pair", fake)
    return fake


class TestNoImplicitRenders:
    def test_construction_and_review_never_render(
            self, qapp, source_and_target, synchronous_workers,
            monkeypatch):
        calls = []
        _stub_render_pair(monkeypatch, calls)
        source, target = source_and_target
        wizard = _wizard(source, target)
        wizard._enter_review()
        assert calls == []
        # ... but the scrub is armed: songs listed, button live.
        names = {wizard.preview_song_combo.itemData(i)
                 for i in range(wizard.preview_song_combo.count())}
        assert names == {"S", "T"}
        assert wizard.preview_btn.isEnabled()

    def test_slider_ticks_never_render(self, qapp, source_and_target,
                                       synchronous_workers, monkeypatch):
        calls = []
        _stub_render_pair(monkeypatch, calls)
        source, target = source_and_target
        wizard = _wizard(source, target)
        wizard._enter_review()
        wizard.preview_btn.click()
        assert len(calls) == 1
        wizard.preview_slider.setValue(40)
        wizard.preview_slider.setValue(80)
        assert len(calls) == 1               # click-only, never per tick

    def test_slider_bounds_follow_song_duration(
            self, qapp, source_and_target, synchronous_workers,
            monkeypatch):
        _stub_render_pair(monkeypatch, [])
        source, target = source_and_target
        wizard = _wizard(source, target)
        wizard._enter_review()
        combo = wizard.preview_song_combo
        combo.setCurrentIndex(combo.findData("S"))
        assert wizard.preview_slider.maximum() == 160   # 16 s * 10
        combo.setCurrentIndex(combo.findData("T"))
        assert wizard.preview_slider.maximum() == 80    # 8 s * 10


class TestRenderOnClick:
    def test_click_renders_both_sides(self, qapp, source_and_target,
                                      synchronous_workers, monkeypatch):
        calls = []
        _stub_render_pair(monkeypatch, calls)
        source, target = source_and_target
        wizard = _wizard(source, target)
        wizard._enter_review()
        combo = wizard.preview_song_combo
        combo.setCurrentIndex(combo.findData("S"))
        wizard.preview_slider.setValue(45)              # 4.5 s

        wizard.preview_btn.click()

        assert len(calls) == 1
        call = calls[0]
        assert call["time_s"] == pytest.approx(4.5)
        assert call["source_config"] is source
        assert call["source_song"] is source.songs["S"]
        # The morphed side renders the dry-run copy, NEVER the real
        # (uncommitted) target.
        assert call["morphed_song"] is wizard._dry_result.songs["S"]
        assert call["target_config"] is wizard._dry_target
        assert call["target_config"] is not target

        assert wizard.preview_src_image.pixmap() is not None
        assert not wizard.preview_src_image.pixmap().isNull()
        assert not wizard.preview_dst_image.pixmap().isNull()
        assert "master.lms" in wizard.preview_src_caption.text()
        assert wizard.preview_src_caption.text().startswith("SOURCE - ")
        assert "venue.lms" in wizard.preview_dst_caption.text()
        assert wizard.preview_dst_caption.text().startswith("MORPHED - ")
        # Button re-armed after the worker finished.
        assert wizard.preview_btn.isEnabled()

    def test_button_disabled_while_rendering(
            self, qapp, source_and_target, synchronous_workers,
            monkeypatch):
        source, target = source_and_target
        wizard = _wizard(source, target)
        seen = {}

        def fake(*args, **kwargs):
            seen["enabled_during_render"] = wizard.preview_btn.isEnabled()
            return None, None

        monkeypatch.setattr("utils.morph.preview.render_pair", fake)
        wizard._enter_review()
        wizard.preview_btn.click()
        assert seen["enabled_during_render"] is False
        assert wizard.preview_btn.isEnabled()

    def test_none_side_shows_unavailable_placeholder(
            self, qapp, source_and_target, synchronous_workers,
            monkeypatch):
        from gui.dialogs.morph_wizard import PREVIEW_UNAVAILABLE
        calls = []
        _stub_render_pair(monkeypatch, calls, sides=("src",))
        source, target = source_and_target
        wizard = _wizard(source, target)
        wizard._enter_review()
        wizard.preview_btn.click()
        assert not wizard.preview_src_image.pixmap().isNull()
        assert wizard.preview_dst_image.text() == PREVIEW_UNAVAILABLE

    def test_render_failure_degrades_to_placeholders(
            self, qapp, source_and_target, synchronous_workers,
            monkeypatch):
        from gui.dialogs.morph_wizard import PREVIEW_UNAVAILABLE

        def boom(*args, **kwargs):
            raise RuntimeError("no GL")

        monkeypatch.setattr("utils.morph.preview.render_pair", boom)
        source, target = source_and_target
        wizard = _wizard(source, target)
        wizard._enter_review()
        wizard.preview_btn.click()
        assert wizard.preview_src_image.text() == PREVIEW_UNAVAILABLE
        assert wizard.preview_dst_image.text() == PREVIEW_UNAVAILABLE
        assert "no GL" in wizard.preview_status.text()
        assert wizard.preview_btn.isEnabled()
