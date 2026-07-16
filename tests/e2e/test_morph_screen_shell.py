# tests/e2e/test_morph_screen_shell.py
"""Tools > Morph to Venue as a page-stack screen (rehosted from the
modal wizard 2026-07-16): opening shows the screen with no active
shell section, navigating away KEEPS the in-progress morph, re-opening
resumes the SAME screen, closing tears it down, and a swapped project
config (a load) discards the stale screen instead of resuming it."""

import pytest

from config.models import (Configuration, DimmerBlock, Fixture,
                           FixtureGroup, FixtureGroupCapabilities,
                           FixtureMode, LightBlock, LightLane, ShowPart,
                           Song, TimelineData, Universe)


def _fixture(name, group="G"):
    return Fixture(universe=1, address=1, manufacturer="M", model="X",
                   current_mode="Std",
                   available_modes=[FixtureMode(name="Std", channels=1)],
                   name=name, group=group)


def _target_config():
    group = FixtureGroup("WASH", [_fixture("w1", group="WASH")])
    group.capabilities = FixtureGroupCapabilities(
        has_dimmer=True, has_colour=True,
        has_movement=False, has_special=False)
    cfg = Configuration(fixtures=list(group.fixtures),
                        groups={"WASH": group},
                        universes={1: Universe(id=1, name="U1", output={})})
    cfg.songs = {}
    return cfg


def _add_song(window):
    """Give the open project one wireable song; returns its lane."""
    lane = LightLane(
        name="Pars", fixture_targets=["PARS"],
        light_blocks=[LightBlock(
            start_time=0.0, end_time=16.0, effect_name="x",
            dimmer_blocks=[DimmerBlock(0.0, 16.0, intensity=200.0)])])
    song = Song(name="S",
                parts=[ShowPart(name="All", color="#fff", signature="4/4",
                                bpm=120.0, num_bars=8,
                                transition="instant")],
                timeline_data=TimelineData(lanes=[lane]))
    window.config.songs["S"] = song
    return lane


class TestMorphScreenShell:

    def test_no_songs_shows_info_and_no_screen(self, main_window,
                                               monkeypatch):
        from PyQt6.QtWidgets import QMessageBox
        told = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: told.append(a)))
        main_window.open_morph_screen()
        assert told, "empty project must explain itself"
        assert getattr(main_window, "_morph_screen", None) is None

    def test_open_shows_the_screen_like_home(self, main_window):
        _add_song(main_window)
        main_window.open_morph_screen()
        screen = main_window._morph_screen
        assert screen is not None
        assert main_window.page_stack.currentWidget() is screen
        # Stack screens carry no active shell section; the subnav hides.
        assert not main_window.subnav.isVisibleTo(main_window)

    def test_navigate_away_keeps_reopen_resumes(self, main_window):
        lane = _add_song(main_window)
        main_window.open_morph_screen()
        screen = main_window._morph_screen
        screen.set_target_config(_target_config(), "venue.lms")
        assert screen.patchbay.add_edge(lane.lane_id, "dimmer", "WASH")

        # The user checks something on the tabs mid-morph...
        main_window.show_pages()
        assert main_window.page_stack.currentWidget() is \
            main_window.tabWidget
        # ...and the menu brings the SAME flow back, plan intact.
        main_window.open_morph_screen()
        assert main_window._morph_screen is screen
        assert main_window.page_stack.currentWidget() is screen
        assert len(screen.plan.edges) == 1

    def test_close_tears_the_screen_down(self, main_window):
        _add_song(main_window)
        main_window.open_morph_screen()
        screen = main_window._morph_screen
        stack_count = main_window.page_stack.count()
        screen.request_exit()          # empty flow: closes silently
        assert main_window._morph_screen is None
        assert main_window.page_stack.count() == stack_count - 1
        assert main_window.page_stack.currentWidget() is \
            main_window.tabWidget

    def test_swapped_project_discards_the_stale_screen(self, main_window):
        lane = _add_song(main_window)
        main_window.open_morph_screen()
        stale = main_window._morph_screen
        stale.set_target_config(_target_config(), "venue.lms")
        assert stale.patchbay.add_edge(lane.lane_id, "dimmer", "WASH")

        # A project load swaps the config reference (rebind ladder).
        fresh = Configuration(fixtures=[], groups={}, universes={})
        fresh.songs = {}
        main_window.config = fresh
        _add_song(main_window)
        main_window.open_morph_screen()
        assert main_window._morph_screen is not stale
        assert main_window._morph_screen.plan.edges == []
