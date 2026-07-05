"""Stage-plane visualization (v1.1): picker UI + highlighted-face overlay.

Covers:
- plane_corners: pure geometry of the 6 cuboid faces in the renderer's
  Y-up world (stage X -> X, height -> Y, stage Y -> Z, front = -Z).
- StagePlaneHighlight state setters are GL-free (mock context) and the
  lazy VBO rebuild writes the right vertices.
- RenderEngine buffers set_highlighted_plane before initializeGL and
  flushes it afterwards (same contract as test_render_engine_pending).
- StageTab's plane picker: 6 entries, hover previews, click toggles the
  persistent highlight, rig height follows the tallest fixture.

The actual GL draw is exercised by the visual harness like the other
overlay components, not here.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visualizer.renderer.stage_planes import (
    PLANE_NAMES,
    StagePlaneHighlight,
    plane_corners,
)


class TestPlaneCorners:

    W, D, H = 10.0, 6.0, 4.0

    def corners(self, name):
        return plane_corners(name, self.W, self.D, self.H)

    def test_all_six_faces_have_four_corners(self):
        for name in PLANE_NAMES:
            assert len(self.corners(name)) == 4

    def test_floor_is_lifted_above_grid(self):
        ys = {c[1] for c in self.corners("Floor")}
        assert len(ys) == 1
        (y,) = ys
        # Above the floor+grid+axes stack (which reaches y=0.003) but
        # visually still "the floor".
        assert 0.003 < y < 0.05

    def test_ceiling_sits_at_rig_height(self):
        assert {c[1] for c in self.corners("Ceiling")} == {self.H}

    def test_front_is_negative_z_wall(self):
        # StageView convention: negative stage-Y = front (audience side),
        # which maps to world -Z.
        assert {c[2] for c in self.corners("Front")} == {-self.D / 2}
        assert {c[2] for c in self.corners("Back")} == {self.D / 2}

    def test_left_right_walls_span_full_height(self):
        for name, x in (("Left", -self.W / 2), ("Right", self.W / 2)):
            corners = self.corners(name)
            assert {c[0] for c in corners} == {x}
            assert {c[1] for c in corners} == {0.0, self.H}

    def test_unknown_plane_raises(self):
        with pytest.raises(ValueError, match="Unknown stage plane"):
            plane_corners("Diagonal", 10, 6, 3)


class TestStagePlaneHighlightState:
    """State setters must be GL-free so the engine can call them from any
    pre/post-init path; only render() touches the buffer."""

    @pytest.fixture
    def component(self):
        return StagePlaneHighlight(MagicMock(), width=10.0, depth=6.0)

    def test_set_highlight_validates_name(self, component):
        with pytest.raises(ValueError):
            component.set_highlight("Sideways")
        component.set_highlight("Floor")
        assert component.highlighted == "Floor"
        component.set_highlight(None)
        assert component.highlighted is None

    def test_setters_mark_geometry_dirty(self, component):
        component.set_highlight("Ceiling")
        component._dirty = False

        component.set_rig_height(5.0)
        assert component._dirty is True
        component._dirty = False

        component.set_stage_size(12.0, 8.0)
        assert component._dirty is True
        component._dirty = False

        # No-op sets stay clean.
        component.set_rig_height(5.0)
        component.set_stage_size(12.0, 8.0)
        component.set_highlight("Ceiling")
        assert component._dirty is False

    def test_rebuild_writes_fill_then_outline_vertices(self, component):
        component.set_highlight("Ceiling")
        component.set_rig_height(4.0)
        component._rebuild_vbo()

        (payload,), _ = component._vbo.write.call_args
        vertices = np.frombuffer(payload, dtype='f4').reshape(-1, 3)
        assert vertices.shape == (10, 3)  # 6 fill + 4 outline
        # Every vertex of the ceiling face sits at rig height.
        assert set(vertices[:, 1].tolist()) == {4.0}

    def test_render_without_highlight_is_a_noop(self, component):
        component.render(MagicMock())
        component._vbo.write.assert_not_called()


class TestEnginePendingPlane:

    @pytest.fixture
    def engine(self, qapp):
        from visualizer.renderer.engine import RenderEngine
        e = RenderEngine(parent=None)
        try:
            e.render_timer.stop()
            assert e.stage_planes is None
            yield e
        finally:
            e.deleteLater()

    def test_set_before_init_is_buffered(self, engine):
        engine.set_highlighted_plane("Back", rig_height=5.5)
        assert engine._pending_plane_highlight == ("Back", 5.5)

    def test_flush_applies_buffered_highlight(self, engine):
        engine.set_highlighted_plane("Back", rig_height=5.5)
        engine.stage_planes = MagicMock()
        engine._flush_pending_state()
        engine.stage_planes.set_rig_height.assert_called_once_with(5.5)
        engine.stage_planes.set_highlight.assert_called_once_with("Back")
        assert engine._pending_plane_highlight is None

    def test_post_init_goes_straight_through(self, engine):
        engine.stage_planes = MagicMock()
        engine.set_highlighted_plane("Floor", rig_height=3.0)
        assert engine._pending_plane_highlight is None
        engine.stage_planes.set_highlight.assert_called_once_with("Floor")

    def test_stage_size_forwarded_to_planes(self, engine):
        engine.stage_planes = MagicMock()
        engine.makeCurrent = MagicMock()
        engine.doneCurrent = MagicMock()
        engine.set_stage_size(12.0, 8.0)
        engine.stage_planes.set_stage_size.assert_called_once_with(12.0, 8.0)


class TestStageTabPicker:

    @pytest.fixture
    def tab(self, qapp, sample_configuration):
        from gui.tabs.stage_tab import StageTab
        tab = StageTab(sample_configuration, parent=None)
        tab.embedded_visualizer = MagicMock()  # spy on the forwarding
        yield tab
        tab.embedded_visualizer = None
        tab.deleteLater()

    def test_picker_lists_all_six_planes(self, tab):
        names = [tab.plane_list.item(i).text() for i in range(tab.plane_list.count())]
        assert names == list(PLANE_NAMES)

    def test_click_selects_then_toggles_off(self, tab):
        item = tab.plane_list.item(0)  # Floor
        tab._on_plane_clicked(item)
        assert tab._selected_plane == "Floor"
        tab.embedded_visualizer.set_highlighted_plane.assert_called_with(
            "Floor", tab._rig_height()
        )

        tab._on_plane_clicked(item)
        assert tab._selected_plane is None
        tab.embedded_visualizer.set_highlighted_plane.assert_called_with(
            None, tab._rig_height()
        )

    def test_hover_previews_without_selecting(self, tab):
        item = tab.plane_list.item(1)  # Ceiling
        tab._on_plane_hovered(item)
        assert tab._selected_plane is None
        tab.embedded_visualizer.set_highlighted_plane.assert_called_with(
            "Ceiling", tab._rig_height()
        )

    def test_rig_height_follows_tallest_fixture(self, tab, sample_configuration):
        # sample fixture uses the group default (3.0 m) -> floor of 3.0.
        assert tab._rig_height() == 3.0
        fixture = sample_configuration.fixtures[0]
        fixture.z = 7.5
        fixture.z_uses_group_default = False
        assert tab._rig_height() == 7.5
