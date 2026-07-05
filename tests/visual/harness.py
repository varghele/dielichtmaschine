"""Shared helpers for visual regression tests.

Two families of checks:

**Ink analysis** (machine-independent, default suite): grab a widget,
find the bounding box of "ink" (pixels that differ from the background),
and assert the ink is neither touching the widget edges nor narrower
than the text's font-metrics advance. This catches the "+ rendered as a
cut-off sliver" class of bug, where QSS padding shrinks a fixed-width
button's content rect below the glyph size — the glyph clips *inside*
the widget, so edge-touch detection alone misses it.

**Golden screenshots** (per-platform, tolerance-based): compare a
QImage against a stored golden PNG under ``goldens/<sys.platform>/``.
Set ``QLC_REGEN_GOLDENS=1`` to (re)write goldens instead of comparing.
Goldens are platform-scoped because the offscreen QPA renders fonts
differently per OS (on Windows it has no font database at all and draws
fallback boxes — stable on one platform, useless across platforms).
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PyQt6.QtGui import QFontMetrics, QImage

GOLDENS_DIR = os.path.join(os.path.dirname(__file__), 'goldens', sys.platform)


def qimage_to_array(image: QImage) -> np.ndarray:
    """QImage -> HxWx4 uint8 RGBA array (copies; row padding stripped)."""
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes())
    raw = np.frombuffer(ptr, dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine())
    return raw[:, : image.width() * 4].reshape(
        image.height(), image.width(), 4).copy()


def ink_bbox(image: QImage, threshold: int = 60):
    """Bounding box of non-background pixels as (left, top, right, bottom),
    or None if the image is blank. Background = the top-left corner pixel;
    a pixel is ink when its summed RGB distance from that exceeds
    ``threshold``."""
    arr = qimage_to_array(image).astype(np.int16)
    bg = arr[0, 0, :3]
    ink = np.abs(arr[:, :, :3] - bg).sum(axis=2) > threshold
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def glyph_ink_bbox(button, threshold: int = 30):
    """Bounding box of the *glyph* ink only, as (left, top, right, bottom).

    Grabs the button with its text, then with the text blanked, and
    diffs the two renders — the changed pixels are exactly the glyph.
    Immune to button chrome (borders, rounded corners, gradients) that
    legitimately touches the widget edges and fooled a naive
    background-distance detector. Returns None when the text paints
    nothing at all.
    """
    text = button.text()
    with_text = qimage_to_array(button.grab().toImage()).astype(np.int16)
    button.setText("")
    try:
        without_text = qimage_to_array(button.grab().toImage()).astype(np.int16)
    finally:
        button.setText(text)
    if with_text.shape != without_text.shape:
        return None
    diff = np.abs(with_text[:, :, :3] - without_text[:, :, :3]).max(axis=2)
    ys, xs = np.nonzero(diff > threshold)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def assert_text_not_clipped(button, *, min_edge_margin: int = 1,
                            metrics_slack: int = 5) -> None:
    """Fail if a text button's glyph renders clipped.

    Two independent conditions on the glyph ink (chrome excluded via
    glyph_ink_bbox):
    1. It must stay ``min_edge_margin`` px away from every widget edge.
    2. Its width must be at least the font-metrics advance of the text
       minus ``metrics_slack`` — this catches QSS-padding clipping,
       where the glyph is truncated *inside* the widget and the
       remaining sliver sits nowhere near an edge.

    Both the render and the metrics use the same font engine, so the
    check is self-consistent on any platform — but only meaningful for
    *fixed-width* buttons whose text is short enough to fit under the
    offscreen fallback font too. Auto-sized buttons can't clip (their
    sizeHint uses the same metrics); keep long-text fixed-width buttons
    out of offscreen sweeps.
    """
    text = button.text()
    assert text, "assert_text_not_clipped needs a text button"

    image_w, image_h = button.width(), button.height()
    bbox = glyph_ink_bbox(button)
    assert bbox is not None, (
        f"Button {text!r}: the text paints no pixels at all "
        f"({image_w}x{image_h})"
    )
    left, top, right, bottom = bbox

    for name, margin in (
        ("left", left),
        ("top", top),
        ("right", image_w - 1 - right),
        ("bottom", image_h - 1 - bottom),
    ):
        assert margin >= min_edge_margin, (
            f"Button {text!r}: glyph ink touches the {name} edge "
            f"(margin {margin}px) — clipped by the widget bounds"
        )

    ink_width = right - left + 1
    expected = QFontMetrics(button.font()).horizontalAdvance(text)
    assert ink_width >= expected - metrics_slack, (
        f"Button {text!r}: rendered glyph is {ink_width}px wide but the "
        f"text should span ~{expected}px — clipped by the QSS-padding "
        f"content rect (fixed width too small; use TOOLBAR_BTN_WIDTH or "
        f"drop the fixed width)"
    )


def compare_to_golden(image: QImage, name: str, *,
                      channel_tolerance: int = 25,
                      max_diff_fraction: float = 0.01) -> None:
    """Compare ``image`` to goldens/<platform>/<name>.png.

    A pixel counts as differing when any RGB channel deviates by more
    than ``channel_tolerance``; the comparison fails when more than
    ``max_diff_fraction`` of pixels differ. QLC_REGEN_GOLDENS=1 rewrites
    the golden instead. Missing golden -> pytest.skip (generate + commit
    goldens on the platform you develop on).
    """
    import pytest

    golden_path = os.path.join(GOLDENS_DIR, f"{name}.png")
    if os.environ.get("QLC_REGEN_GOLDENS") == "1":
        os.makedirs(GOLDENS_DIR, exist_ok=True)
        assert image.save(golden_path), f"could not write {golden_path}"
        pytest.skip(f"golden regenerated: {golden_path}")
    if not os.path.exists(golden_path):
        pytest.skip(
            f"no golden for {sys.platform}: {golden_path} "
            f"(run with QLC_REGEN_GOLDENS=1 to create)"
        )

    golden = QImage(golden_path)
    assert (image.width(), image.height()) == (golden.width(), golden.height()), (
        f"{name}: size {image.width()}x{image.height()} != golden "
        f"{golden.width()}x{golden.height()}"
    )

    actual = qimage_to_array(image).astype(np.int16)[:, :, :3]
    expected = qimage_to_array(golden).astype(np.int16)[:, :, :3]
    differing = (np.abs(actual - expected) > channel_tolerance).any(axis=2)
    fraction = float(differing.mean())
    assert fraction <= max_diff_fraction, (
        f"{name}: {fraction:.2%} of pixels differ from the golden "
        f"(allowed {max_diff_fraction:.2%}). If the change is intended, "
        f"regenerate with QLC_REGEN_GOLDENS=1 and review the diff."
    )
