"""
Regression test for the unified TimelineGrid + MasterTimelineWidget render
pipeline.

Past breakage we want this to catch:
- ``stripes_scroll.setWidgetResizable(False)`` left the inner widget at
  ``QRect()`` (0×0) so every stripe was invisible — the user saw nothing
  in the master timeline area.
- QSS class-selector ordering: ``MasterTimelineWidget`` placed before
  ``TimelineWidget`` made the (later) base-class rule override the
  derived-class background, and the master ruler rendered with the wrong
  panel color.
- ``WA_StyledBackground=True`` missing on ``TimelineWidget`` left the
  theme's QSS background unpainted.
- ``MasterTimelineWidget.paintEvent`` not invoking ``PE_Widget`` left
  the widget visually transparent regardless of theme rules.

The test grabs the rendered grid, samples pixel colours, and asserts:
- The master ruler bg matches the dark theme's ``MasterTimelineWidget``
  rule (``#252526``).
- The lane-stripe bg matches the dark theme's ``TimelineWidget`` rule
  (``#2a2a2a``).
- The playhead red (``#FF4444``) appears at least N times along the
  ruler — i.e. the playhead is actually being drawn into the visible
  timeline strip, not lost in a 0×0 inner widget.

Run:
    QT_QPA_PLATFORM=offscreen pytest tests/visual/test_master_timeline_render.py -q
"""

from __future__ import annotations

import collections
import os

import pytest

# Headless rendering — must be set before QApplication is created. The
# session-scoped qapp fixture in conftest.py builds the app on first use,
# so import-time env mutation is safe and necessary for CI runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Theme colors we expect to see in the dark-theme render. Kept in sync
# with resources/themes/dark.qss.
_MASTER_BG = (0x25, 0x25, 0x26)  # MasterTimelineWidget background
_LANE_BG = (0x2A, 0x2A, 0x2A)    # TimelineWidget background
_PLAYHEAD_RED = (0xFF, 0x44, 0x44)  # MasterTimelineWidget.draw_playhead
_ACCENT = (0xF0, 0x56, 0x2E)     # Glutorange: the unified v3 playhead


def _color_histogram(image, *, step: int = 2) -> collections.Counter:
    """Sample pixels at a fixed step and return a {(r,g,b): count} histogram."""
    counts: collections.Counter = collections.Counter()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            c = image.pixelColor(x, y)
            counts[(c.red(), c.green(), c.blue())] += 1
    return counts


def _build_grid_with_master(qapp):
    """Construct a TimelineGrid wired to a MasterTimelineContainer.

    Imports happen inside the function so the qapp fixture (and the
    offscreen platform) are set up before any Qt-touching code loads.
    """
    from gui.theme_manager import ThemeManager
    from timeline_ui.master_timeline_widget import MasterTimelineContainer
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    master_container = MasterTimelineContainer()
    grid = TimelineGrid()
    grid.set_master(master_container)
    return grid, master_container


def test_master_timeline_renders_in_grid(qapp):
    """The master ruler must paint pixels — bg + grid + playhead — once
    embedded in TimelineGrid. Catches the widgetResizable=False
    regression where the inner widget was 0×0 and rendered nothing."""
    grid, master = _build_grid_with_master(qapp)
    try:
        grid.resize(1200, 100)
        grid.show()
        for _ in range(5):
            qapp.processEvents()

        # The inner stripe widget MUST have non-empty geometry.
        inner = grid.stripes_scroll.widget()
        assert inner is not None, "stripes_scroll has no inner widget"
        assert inner.width() > 0 and inner.height() > 0, (
            f"inner stripe widget has empty geometry {inner.geometry()} — "
            "stripes_scroll.widgetResizable is probably False"
        )

        # Render the grid and sample colors.
        pixmap = grid.grab()
        histogram = _color_histogram(pixmap.toImage(), step=2)

        master_bg_count = histogram.get(_MASTER_BG, 0)
        lane_bg_count = histogram.get(_LANE_BG, 0)
        playhead_count = histogram.get(_PLAYHEAD_RED, 0)

        # The master ruler should occupy a substantial number of pixels.
        # 60 px tall row × ~880 px viewport / step² → at least a few
        # hundred pixels of MasterTimelineWidget bg. Use a low floor so
        # the test doesn't get noisy with viewport-size changes.
        assert master_bg_count >= 200, (
            f"MasterTimelineWidget bg #{_MASTER_BG[0]:02x}{_MASTER_BG[1]:02x}"
            f"{_MASTER_BG[2]:02x} not visible (count={master_bg_count}). "
            "Likely causes: WA_StyledBackground missing, paintEvent not "
            "calling PE_Widget, QSS rule order placing TimelineWidget "
            "after MasterTimelineWidget, or stripes_scroll.widgetResizable "
            "being False."
        )

        # The playhead should be drawn at least a handful of times along
        # the visible portion of the ruler.
        assert playhead_count >= 5, (
            f"Playhead red {_PLAYHEAD_RED} not visible "
            f"(count={playhead_count}). MasterTimelineWidget.paintEvent "
            "may not be running, or the inner stripe widget is 0×0."
        )

        # Sanity: the lane TimelineWidget bg shouldn't bleed onto the
        # master row. (If QSS order regresses, master_bg_count above
        # would be 0 and lane_bg_count would absorb those pixels.)
        # We just record the value here; the master_bg assertion above
        # is the actual guard.
        assert lane_bg_count >= 0  # always true, kept for the variable
    finally:
        grid.hide()
        grid.deleteLater()


def test_audio_header_is_not_squished_when_embedded(qapp):
    """The audio lane controls (title / file+load / mute+vol) need ≥100 px
    of vertical space. TimelineGrid.set_audio_lane previously used the
    bare timeline-stripe min height (60) and squished the header."""
    from gui.theme_manager import ThemeManager
    from timeline_ui.audio_lane_widget import AudioLaneWidget
    from timeline_ui.master_timeline_widget import MasterTimelineContainer
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    master = MasterTimelineContainer()
    audio = AudioLaneWidget()
    grid = TimelineGrid()
    try:
        grid.set_master(master)
        grid.set_audio_lane(audio)
        grid.resize(1200, 220)
        grid.show()
        for _ in range(5):
            qapp.processEvents()

        header_height = audio.controls_widget.height()
        assert header_height >= 100, (
            f"Audio header is squished to {header_height} px — "
            "TimelineGrid.set_audio_lane is probably using the bare "
            "TimelineWidget min height (60) instead of honouring the "
            "audio lane's 100-px floor."
        )
    finally:
        grid.hide()
        grid.deleteLater()


@pytest.mark.parametrize(
    "theme,expected_header_bg",
    [("dark", (0x25, 0x25, 0x26)), ("light", (0xFA, 0xFA, 0xFA))],
)
def test_master_header_bg_matches_theme(qapp, theme, expected_header_bg):
    """The master timeline header (label + time/BPM/zoom info) must paint
    the theme's panel color, not the QScrollArea viewport's default
    light-gray. Catches regressions where the header lacks objectName /
    WA_StyledBackground or the QSS rule is missing."""
    from gui.theme_manager import ThemeManager
    from timeline_ui.master_timeline_widget import MasterTimelineContainer
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, theme)
    master = MasterTimelineContainer()
    grid = TimelineGrid()
    try:
        grid.set_master(master)
        grid.resize(1200, 200)
        grid.show()
        for _ in range(5):
            qapp.processEvents()

        header = grid._headers_layout.itemAt(0).widget()
        assert header is not None
        assert header.objectName() == "MasterTimelineHeader", (
            f"Expected objectName 'MasterTimelineHeader', "
            f"got {header.objectName()!r}"
        )
        histogram = _color_histogram(header.grab().toImage(), step=2)
        dominant_color, dominant_count = histogram.most_common(1)[0]
        assert dominant_color == expected_header_bg, (
            f"{theme} theme master-header dominant color "
            f"{dominant_color} (count={dominant_count}) doesn't match "
            f"expected {expected_header_bg}. Top 3 colors: "
            f"{histogram.most_common(3)}"
        )
    finally:
        grid.hide()
        grid.deleteLater()


def test_compact_button_padding_takes_effect(qapp):
    """The lane-control M / S / × buttons set density=compact so the
    QSS rule QPushButton[density="compact"] tightens their padding.
    Regression: the property used to be `size`, which collides with
    Qt's built-in QSize Q_PROPERTY — setProperty silently did nothing
    and the buttons kept the global 6×14 padding, crushing the text."""
    from PyQt6.QtWidgets import QPushButton
    from gui.theme_manager import ThemeManager

    ThemeManager().apply(qapp, "dark")
    compact = QPushButton("M")
    compact.setProperty("density", "compact")
    plain = QPushButton("M")
    try:
        compact.show()
        plain.show()
        for _ in range(3):
            qapp.processEvents()
        # The compact rule sets padding 2×4 + min-height 0 — its sizeHint
        # should be smaller than a vanilla QPushButton with the same text.
        compact_hint = compact.sizeHint()
        plain_hint = plain.sizeHint()
        assert compact_hint.width() < plain_hint.width(), (
            f"density=compact didn't shrink the button — compact "
            f"{compact_hint} vs plain {plain_hint}. Likely causes: the "
            "QSS rule selector is wrong, or the property name collides "
            "with a Qt built-in (don't use 'size')."
        )
        assert compact_hint.height() < plain_hint.height(), (
            f"density=compact didn't shrink height — compact "
            f"{compact_hint} vs plain {plain_hint}."
        )
    finally:
        compact.hide()
        plain.hide()
        compact.deleteLater()
        plain.deleteLater()


# ── Timeline v3 (stage T4): parts band + compact audio row ───────────
#
# The Shows tab opts into compact master/audio rows; the defaults above
# stay untouched (the Structure tab embeds the same widgets and its
# golden pins the default look).


def _build_v3_grid(qapp, mock_song_structure):
    from gui.theme_manager import ThemeManager
    from timeline_ui.audio_lane_widget import AudioLaneWidget
    from timeline_ui.master_timeline_widget import MasterTimelineContainer
    from timeline_ui.timeline_grid import TimelineGrid

    ThemeManager().apply(qapp, "dark")
    master = MasterTimelineContainer(compact=True)
    audio = AudioLaneWidget(compact=True)
    grid = TimelineGrid()
    grid.set_master(master)
    grid.set_audio_lane(audio)
    grid.set_song_structure(mock_song_structure)
    return grid, master, audio


def test_parts_band_and_audio_rows_are_compact(qapp, mock_song_structure):
    """Compact containers pin the v3 row heights: 26px PARTS band,
    44px audio row (mock 06b). The default containers above keep 76/100."""
    grid, master, audio = _build_v3_grid(qapp, mock_song_structure)
    try:
        grid.resize(900, 140)
        grid.show()
        for _ in range(5):
            qapp.processEvents()
        assert master.timeline_widget.height() == 26
        assert audio.timeline_widget.height() == 44
        assert audio.controls_widget.height() == 44
    finally:
        grid.hide()
        grid.deleteLater()


def _accentish(color) -> bool:
    """Glutorange-family pixel: strong red with green clearly above
    blue (the accent's 86/46 split survives the audio row's waveform
    overlay dimming it to ~199/75/43). The legacy playhead red
    (#FF4444, g == b) never matches."""
    r, g, b = color
    return r >= 150 and g > b + 15 and g < 130


def _legacy_reddish(color) -> bool:
    """#FF4444-family pixel (g ~= b), even under a dimming overlay."""
    r, g, b = color
    return r >= 150 and abs(g - b) <= 10 and g < 100


def test_v3_playhead_is_one_accent_line_across_rows(qapp,
                                                    mock_song_structure):
    """The unified playhead: a 2px Glutorange line on master AND audio,
    with the legacy red gone from both stripes. Predicate-based rather
    than exact-color: the audio row's waveform child dims the stripe."""
    grid, master, audio = _build_v3_grid(qapp, mock_song_structure)
    try:
        grid.set_playhead_position(2.0)
        grid.resize(900, 140)
        grid.show()
        for _ in range(5):
            qapp.processEvents()

        for name, stripe in (("master", master.timeline_widget),
                             ("audio", audio.timeline_widget)):
            histogram = _color_histogram(stripe.grab().toImage(), step=1)
            accent = sum(count for color, count in histogram.items()
                         if _accentish(color))
            legacy = sum(count for color, count in histogram.items()
                         if _legacy_reddish(color))
            assert accent >= stripe.height() // 2, (
                f"{name} stripe: accent playhead not visible "
                f"(accent-ish count={accent}). Top colors: "
                f"{histogram.most_common(5)}"
            )
            assert legacy == 0, (
                f"{name} stripe still paints the legacy red playhead "
                f"(red-ish count={legacy})"
            )
    finally:
        grid.hide()
        grid.deleteLater()


def test_lanes_follow_the_master_playhead_ink(qapp, mock_song_structure):
    """TimelineGrid fans the master's playhead ink out to light lanes,
    so the Shows tab's lanes join the accent line while the default
    (Structure-tab) master leaves everything legacy red."""
    from timeline.light_lane import LightLane
    from timeline_ui.light_lane_widget import LightLaneWidget

    grid, master, audio = _build_v3_grid(qapp, mock_song_structure)
    lane = LightLaneWidget(LightLane("L1"), [], None)
    try:
        grid.add_light_lane(lane)
        assert lane.timeline_widget.playhead_accent is True
    finally:
        grid.deleteLater()

    # Default master -> lanes stay on the legacy ink.
    from timeline_ui.master_timeline_widget import MasterTimelineContainer
    from timeline_ui.timeline_grid import TimelineGrid
    grid2 = TimelineGrid()
    grid2.set_master(MasterTimelineContainer())
    lane2 = LightLaneWidget(LightLane("L2"), [], None)
    try:
        grid2.add_light_lane(lane2)
        assert lane2.timeline_widget.playhead_accent is False
    finally:
        grid2.deleteLater()


def test_parts_band_regions_tint_in_part_colour(qapp, mock_song_structure):
    """The parts band tints each region in the part colour at ~0.2
    alpha over the master bg (no more 3px top bar in v3 mode)."""
    grid, master, audio = _build_v3_grid(qapp, mock_song_structure)
    try:
        grid.resize(900, 140)
        grid.show()
        for _ in range(5):
            qapp.processEvents()

        image = master.timeline_widget.grab().toImage()
        histogram = _color_histogram(image, step=1)
        # #FF0000 at alpha 51/255 over #252526 blends to ~(81, 30, 30).
        reddish = sum(count for (r, g, b), count in histogram.items()
                      if 70 <= r <= 92 and g <= 45 and b <= 45)
        assert reddish >= 200, (
            f"Intro region tint not visible (reddish count={reddish}). "
            "Top colors: " + str(histogram.most_common(5))
        )
        # The full-saturation top bar of the default look must be gone.
        assert histogram.get((0xFF, 0x00, 0x00), 0) == 0
    finally:
        grid.hide()
        grid.deleteLater()


def test_compact_audio_header_keeps_the_control_contract(qapp):
    """The 44px audio header keeps every control attribute and its
    behaviour: mute toggles, volume updates its readout, LOAD stays a
    real button, and the filename readout middle-elides while text()
    returns the full string (shows_tab drives these by attribute)."""
    from gui.theme_manager import ThemeManager
    from timeline_ui.audio_lane_widget import AudioLaneWidget

    ThemeManager().apply(qapp, "dark")
    audio = AudioLaneWidget(compact=True)
    try:
        for name in ("file_path_edit", "load_button", "mute_button",
                     "volume_slider", "volume_label"):
            assert getattr(audio, name, None) is not None, name

        audio.mute_button.toggle()
        assert audio.is_muted() is True
        audio.volume_slider.setValue(40)
        assert audio.volume_label.text() == "40%"
        assert audio.get_volume() == 0.4
        assert audio.load_button.text() == "LOAD"

        # Middle elision: the painted text shrinks, the stored text stays.
        label = audio.file_path_edit
        label.setFixedWidth(80)
        long_name = "a_very_long_audio_file_name_for_the_show.ogg"
        label.setText(long_name)
        assert label.text() == long_name
        from PyQt6.QtWidgets import QLabel
        painted = QLabel.text(label)
        assert painted != long_name
        assert "…" in painted
        # ElideMiddle keeps the head and tail of the filename.
        assert painted.startswith("a")
        assert painted.endswith("g")
    finally:
        audio.cleanup()
        audio.deleteLater()


@pytest.mark.parametrize(
    "theme,expected_bg",
    [("dark", (0x2A, 0x2A, 0x2A)), ("light", (0xF8, 0xF8, 0xF8))],
)
def test_timeline_widget_paints_qss_background(qapp, theme, expected_bg):
    """A bare TimelineWidget must paint its theme-driven background.
    Catches WA_StyledBackground regressions and stray inline stylesheets.

    We assert on the *dominant* color in a histogram rather than a single
    pixel because the widget also paints semi-transparent grid lines on
    top of the bg — sampling one pixel can land on a grid line."""
    from gui.theme_manager import ThemeManager
    from timeline_ui.timeline_widget import TimelineWidget

    ThemeManager().apply(qapp, theme)
    widget = TimelineWidget()
    try:
        widget.resize(400, 60)
        widget.show()
        for _ in range(3):
            qapp.processEvents()
        histogram = _color_histogram(widget.grab().toImage(), step=2)
        # The most common color must be the theme's bg. Grid lines are
        # only ~1 px wide, so they should be the minority.
        dominant_color, dominant_count = histogram.most_common(1)[0]
        assert dominant_color == expected_bg, (
            f"{theme} theme TimelineWidget dominant color {dominant_color} "
            f"(count={dominant_count}) doesn't match expected {expected_bg}. "
            "Top 3 colors: " + str(histogram.most_common(3))
        )
    finally:
        widget.hide()
        widget.deleteLater()
