"""Tests for the North Star stage-plot symbol set (slice S1).

The design handoff's line symbols (resources/stageplot/*.svg) replace
the hand-painted 2D fixture icons for every mapped legacy fixture type;
unmapped types keep the legacy chassis primitives. See
gui/widgets/fixture_icons.py.
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen

from gui.widgets.fixture_icons import (
    STAGEPLOT_SYMBOL_BY_TYPE,
    _symbol_pixmap,
    clear_symbol_caches,
    paint_fixture_icon,
    stageplot_symbol_path,
    symbol_for_fixture_type,
)
from utils.fixture_capabilities import Chassis, chassis_from_legacy_type


IMAGE_SIZE = 120
ICON_SIZE = 30

# Full fixture-type symbol set from the handoff README (Assets section);
# shipped now even where the legacy type enum has no string yet.
FIXTURE_TYPE_SYMBOLS = [
    "par", "moving-head-spot", "moving-wash", "moving-head-multi",
    "led-bar", "pixel-bar", "sunstrip", "pixel-matrix",
    "blinder", "strobe", "scanner", "laser",
]

STAGE_ELEMENT_SYMBOLS = [
    "drum-riser", "riser", "wedge", "amp", "cab-4x12", "mic-stand",
    "mic-boom", "keys", "di-box", "distro", "foh", "backdrop", "stairs",
    "hazer", "truss-straight", "truss-tower", "truss-corner",
    "truss-circle",
]


def _paint(fixture_type: str | None, *, color: QColor = QColor(255, 0, 0),
           rotate: float = 0.0, chassis: Chassis | None = None) -> QImage:
    """Paint one icon the way FixtureItem / StagePlotRenderer do: pen +
    brush preset, painter rotated, icon centered at the origin."""
    if chassis is None:
        chassis = chassis_from_legacy_type(fixture_type)
    image = QImage(IMAGE_SIZE, IMAGE_SIZE,
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.translate(IMAGE_SIZE / 2, IMAGE_SIZE / 2)
        painter.rotate(rotate)
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(QBrush(color))
        paint_fixture_icon(painter, chassis, ICON_SIZE,
                           fixture_type=fixture_type)
    finally:
        painter.end()
    return image


def _visible_pixels(image: QImage) -> int:
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    )


def _images_differ(a: QImage, b: QImage) -> bool:
    assert a.size() == b.size()
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixelColor(x, y) != b.pixelColor(x, y):
                return True
    return False


# ---------------------------------------------------------------------------
# Symbol files + mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURE_TYPE_SYMBOLS + STAGE_ELEMENT_SYMBOLS)
def test_symbol_file_shipped(name):
    """Every handoff symbol was copied into resources/stageplot/."""
    assert os.path.isfile(stageplot_symbol_path(name)), name


@pytest.mark.parametrize("fixture_type,expected", [
    ("PAR", "par"),
    ("MH", "moving-head-spot"),
    ("WASH", "moving-wash"),
    ("BAR", "led-bar"),
    ("PIXELBAR", "pixel-bar"),
    ("SUNSTRIP", "sunstrip"),
])
def test_legacy_type_maps_to_expected_symbol(fixture_type, expected):
    assert symbol_for_fixture_type(fixture_type) == expected


def test_every_mapped_symbol_file_exists():
    for fixture_type, symbol in STAGEPLOT_SYMBOL_BY_TYPE.items():
        path = stageplot_symbol_path(symbol)
        assert os.path.isfile(path), f"{fixture_type} -> {path} missing"


def test_unknown_and_missing_types_map_to_none():
    assert symbol_for_fixture_type("SMOKE") is None
    assert symbol_for_fixture_type("") is None
    assert symbol_for_fixture_type(None) is None


# ---------------------------------------------------------------------------
# Rendering: color substitution, rotation, fallback, caching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_type", sorted(STAGEPLOT_SYMBOL_BY_TYPE))
def test_mapped_types_paint_visible_pixels(qapp, fixture_type):
    image = _paint(fixture_type)
    assert _visible_pixels(image) > 0, f"{fixture_type} painted nothing"


def test_paint_returns_true_for_symbol_false_for_fallback(qapp):
    image = QImage(IMAGE_SIZE, IMAGE_SIZE,
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.translate(IMAGE_SIZE / 2, IMAGE_SIZE / 2)
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(QBrush(QColor(255, 0, 0)))
        assert paint_fixture_icon(painter, Chassis.PAR, ICON_SIZE,
                                  fixture_type="PAR") is True
        assert paint_fixture_icon(painter, Chassis.PAR, ICON_SIZE,
                                  fixture_type=None) is False
        assert paint_fixture_icon(painter, Chassis.OTHER, ICON_SIZE,
                                  fixture_type="SMOKE") is False
    finally:
        painter.end()


def test_color_substitution_group_color_drives_stroke(qapp):
    """The same symbol rendered in two group colors differs, and the
    rendered strokes actually carry the requested color (not the raw
    #8d9299 token)."""
    red = _paint("PAR", color=QColor(220, 40, 40))
    blue = _paint("PAR", color=QColor(40, 80, 220))
    assert _images_differ(red, blue)

    reddish = bluish = token_gray = 0
    for y in range(red.height()):
        for x in range(red.width()):
            c = red.pixelColor(x, y)
            if c.alpha() < 200:
                continue
            if c.red() > c.blue() + 60:
                reddish += 1
            b = blue.pixelColor(x, y)
            if b.alpha() >= 200 and b.blue() > b.red() + 60:
                bluish += 1
            if abs(c.red() - 0x8D) < 8 and abs(c.green() - 0x92) < 8 \
                    and abs(c.blue() - 0x99) < 8:
                token_gray += 1
    assert reddish > 0, "no red strokes in the red render"
    assert bluish > 0, "no blue strokes in the blue render"
    assert token_gray == 0, "raw #8d9299 token survived substitution"


def test_rotation_rotates_symbol(qapp):
    """Painter rotation (the callers' yaw handling) visibly rotates the
    symbol - the beam tick breaks the par circle's symmetry."""
    upright = _paint("PAR", rotate=0.0)
    rotated = _paint("PAR", rotate=90.0)
    assert _visible_pixels(rotated) > 0
    assert _images_differ(upright, rotated)


def test_bar_symbol_reads_elongated(qapp):
    """BAR variants keep the 2*size length contract of the legacy icons."""
    def horizontal_extent(img: QImage) -> int:
        xs = [x for y in range(img.height()) for x in range(img.width())
              if img.pixelColor(x, y).alpha() > 0]
        return (max(xs) - min(xs)) if xs else 0

    bar_extent = horizontal_extent(_paint("BAR"))
    par_extent = horizontal_extent(_paint("PAR"))
    assert bar_extent > par_extent


def test_unknown_type_falls_back_to_legacy_painting(qapp):
    """Unmapped types keep the old primitives: no crash, visible output."""
    image = _paint("SMOKE")  # chassis_from_legacy_type -> OTHER, "?" square
    assert _visible_pixels(image) > 0


def test_translucent_brush_dims_symbol(qapp):
    """A brush with alpha (the selected state) renders translucently."""
    translucent = QColor(220, 40, 40)
    translucent.setAlpha(160)
    image = _paint("PAR", color=translucent)
    max_alpha = 0
    for y in range(image.height()):
        for x in range(image.width()):
            max_alpha = max(max_alpha, image.pixelColor(x, y).alpha())
    assert 0 < max_alpha < 220


def test_pixmap_cache_reuses_render(qapp):
    clear_symbol_caches()
    first = _symbol_pixmap("par", QColor(220, 40, 40), 90)
    second = _symbol_pixmap("par", QColor(220, 40, 40), 90)
    assert first is second
    other_size = _symbol_pixmap("par", QColor(220, 40, 40), 180)
    other_color = _symbol_pixmap("par", QColor(40, 80, 220), 90)
    assert other_size is not first
    assert other_color is not first
    clear_symbol_caches()


def test_missing_symbol_file_falls_back(qapp, monkeypatch):
    """A mapped type whose SVG vanished still paints (legacy fallback)."""
    import gui.widgets.fixture_icons as fi
    clear_symbol_caches()
    monkeypatch.setitem(fi.STAGEPLOT_SYMBOL_BY_TYPE, "PAR", "no-such-symbol")
    try:
        image = _paint("PAR")
        assert _visible_pixels(image) > 0
    finally:
        clear_symbol_caches()
