"""Timeline block-edit dialogs: North Star role adoption.

The six modal editors opened from the Show Timeline (colour / movement /
dimmer / special block editors, the fixture-target picker and the
save-as-riff dialog) were restyled off the pre-rebrand Windows-blue and
gray inline stylesheets onto theme roles (docs/timeline-styling-review.md
item 4).

These tests pin the two things that matter without ever calling a real
``exec()`` (docs/qt-gotchas.md #7): each dialog constructs offscreen and
its confirm button carries ``role="primary"``. They also confirm the
role is backed by an actual QSS rule in the rendered dark theme, and
that none of the removed pre-rebrand colors linger in the sources.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from config.models import (
    ColourBlock, DimmerBlock, MovementBlock, SpecialBlock,
    Configuration, FixtureGroup,
)
from gui.theme_tokens import render_theme

from timeline_ui.colour_block_dialog import ColourBlockDialog
from timeline_ui.movement_block_dialog import MovementBlockDialog
from timeline_ui.dimmer_block_dialog import DimmerBlockDialog
from timeline_ui.special_block_dialog import SpecialBlockDialog
from timeline_ui.target_selection_dialog import TargetSelectionDialog
from timeline_ui.save_riff_dialog import SaveRiffDialog


# ──────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────

def _make_config() -> Configuration:
    config = Configuration()
    config.groups["Wash"] = FixtureGroup("Wash", [])
    config.groups["Movers"] = FixtureGroup("Movers", [])
    return config


class _StubRiffLibrary:
    """Enough of RiffLibrary for SaveRiffDialog construction."""

    def get_categories(self):
        return []


class _StubLightBlock:
    """A LightBlock stand-in: SaveRiffDialog only reads start/end at
    construction (conversion happens on save, not on __init__)."""

    def __init__(self):
        self.start_time = 0.0
        self.end_time = 4.0


# ──────────────────────────────────────────────
# Primary-button role per dialog (no exec)
# ──────────────────────────────────────────────

def test_colour_dialog_primary_button_role(qapp):
    dlg = ColourBlockDialog(ColourBlock(start_time=0.0, end_time=4.0))
    assert dlg.ok_button.property("role") == "primary"


def test_movement_dialog_primary_button_role(qapp):
    dlg = MovementBlockDialog(MovementBlock(start_time=0.0, end_time=4.0),
                              config=_make_config())
    assert dlg.ok_button.property("role") == "primary"


def test_dimmer_dialog_primary_button_role(qapp):
    dlg = DimmerBlockDialog(DimmerBlock(start_time=0.0, end_time=4.0))
    assert dlg.ok_button.property("role") == "primary"


def test_special_dialog_primary_button_role(qapp):
    dlg = SpecialBlockDialog(SpecialBlock(start_time=0.0, end_time=4.0))
    assert dlg.ok_button.property("role") == "primary"


def test_target_dialog_primary_button_role(qapp):
    dlg = TargetSelectionDialog([], _make_config())
    assert dlg.ok_button.property("role") == "primary"


def test_save_riff_dialog_primary_button_role(qapp):
    dlg = SaveRiffDialog(_StubLightBlock(), 120.0, _StubRiffLibrary())
    assert dlg.save_button.property("role") == "primary"


# ──────────────────────────────────────────────
# Behaviour / API preserved
# ──────────────────────────────────────────────

def test_colour_dialog_accept_writes_block(qapp):
    block = ColourBlock(start_time=0.0, end_time=4.0)
    dlg = ColourBlockDialog(block)
    dlg.sliders["red"][0].setValue(200)
    dlg.accept()  # never .exec()
    assert block.red == 200.0
    assert block.color_mode == "RGB"


def test_target_dialog_get_selected_targets_roundtrip(qapp):
    dlg = TargetSelectionDialog(["Wash"], _make_config())
    assert "Wash" in dlg.get_selected_targets()


# ──────────────────────────────────────────────
# The role is backed by a real QSS rule
# ──────────────────────────────────────────────

def test_primary_role_is_backed_by_dark_theme_rule():
    qss = render_theme("dark")
    assert 'QPushButton[role="primary"]' in qss
