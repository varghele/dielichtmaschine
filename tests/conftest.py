# tests/conftest.py
# Shared pytest fixtures for the QLCplusShowCreator test suite

import sys
import os
import pytest
import tempfile
import shutil

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Hermetic fixture library: exclude the machine-local gdtf_fixtures/ folder
# (GDTF Share downloads, gitignored, contents vary per machine) AND the
# user's configured library dirs (user-gdtf / user-qxf, per-machine by
# definition). GDTF wins identity clashes by design, so a downloaded file
# would otherwise shadow the bundled .qxf definitions that tests are
# written against. GDTF tests opt back in by monkeypatching
# fixture_search_dirs themselves.
# ---------------------------------------------------------------------------
_MACHINE_LOCAL_SOURCES = {"gdtf", "user-gdtf", "user-qxf"}


@pytest.fixture(scope="session", autouse=True)
def _exclude_local_gdtf_library():
    from utils import fixture_library as fl
    real = fl.fixture_search_dirs
    # The unwrapped function, for tests OF the search-path logic itself
    # (tests/unit/test_library_paths.py).
    fl._real_fixture_search_dirs = real
    fl.fixture_search_dirs = lambda: [
        (path, source) for path, source in real()
        if source not in _MACHINE_LOCAL_SOURCES
    ]
    fl.clear_library_cache()
    yield
    fl.fixture_search_dirs = real
    fl.clear_library_cache()


# ---------------------------------------------------------------------------
# Hermetic QSettings: tests must NEVER touch the real registry / config
# dir. Without this, any code path that persists a setting during a test
# run (theme changes in golden tests, splitter states saved by tabs, ...)
# silently overwrites the user's real preferences - this is how the
# "app keeps opening in the light theme" bug happened.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _hermetic_autosave_dir(tmp_path_factory):
    """Keep autosave backups out of the real app-data dir during tests."""
    os.environ["QLC_AUTOSAVE_DIR"] = str(tmp_path_factory.mktemp("autosave"))
    yield


@pytest.fixture(scope="session", autouse=True)
def _hermetic_qsettings(tmp_path_factory):
    from PyQt6.QtCore import QSettings
    from utils import app_settings as mod

    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, str(settings_dir))
    real_format = mod._settings_format
    mod._settings_format = QSettings.Format.IniFormat
    # Also route DIRECT QSettings(org, app) constructions (none should
    # exist in app code, but keep the default format ini-bound too).
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    yield
    mod._settings_format = real_format


# ---------------------------------------------------------------------------
# QApplication singleton (session-scoped)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication instance for the entire test session."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Sample data model fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_fixture():
    """A single Fixture with reasonable defaults."""
    from config.models import Fixture, FixtureMode
    return Fixture(
        universe=0,
        address=1,
        manufacturer="TestMfr",
        model="TestModel",
        name="Test Fixture 1",
        group="TestGroup",
        current_mode="Standard",
        available_modes=[FixtureMode(name="Standard", channels=10)],
        type="MH",
        x=1.0,
        y=2.0,
        z=3.0,
        mounting="hanging",
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
    )


@pytest.fixture
def sample_fixture_group(sample_fixture):
    """A FixtureGroup with one fixture and detected capabilities."""
    from config.models import FixtureGroup, FixtureGroupCapabilities
    return FixtureGroup(
        name="TestGroup",
        fixtures=[sample_fixture],
        color="#FF0000",
        capabilities=FixtureGroupCapabilities(
            has_dimmer=True,
            has_colour=True,
            has_movement=True,
            has_special=False,
        ),
        default_mounting="hanging",
        default_yaw=0.0,
        default_pitch=0.0,
        default_roll=0.0,
        default_z_height=3.0,
    )


@pytest.fixture
def sample_configuration(sample_fixture, sample_fixture_group):
    """A minimal Configuration with one fixture, one group, one universe."""
    from config.models import Configuration, Universe
    config = Configuration(
        fixtures=[sample_fixture],
        groups={"TestGroup": sample_fixture_group},
        universes={0: Universe(id=0, name="Universe 0", output={})},
    )
    return config


@pytest.fixture
def mock_song_structure():
    """A SongStructure loaded with a simple two-part show."""
    from config.models import ShowPart
    from timeline.song_structure import SongStructure

    parts = [
        ShowPart(name="Intro", color="#FF0000", signature="4/4",
                 bpm=120.0, num_bars=4, transition="instant"),
        ShowPart(name="Verse", color="#00FF00", signature="4/4",
                 bpm=140.0, num_bars=8, transition="instant"),
    ]
    ss = SongStructure()
    ss.load_from_show_parts(parts)
    return ss


@pytest.fixture
def mock_fixture_def():
    """A dict mimicking a parsed QXF fixture definition with channels and modes."""
    return {
        "manufacturer": "TestMfr",
        "model": "TestModel",
        "channels": [
            {"name": "Dimmer", "preset": "IntensityMasterDimmer", "group": "Intensity", "capabilities": []},
            {"name": "Red", "preset": "IntensityRed", "group": "Colour", "capabilities": []},
            {"name": "Green", "preset": "IntensityGreen", "group": "Colour", "capabilities": []},
            {"name": "Blue", "preset": "IntensityBlue", "group": "Colour", "capabilities": []},
            {"name": "White", "preset": "IntensityWhite", "group": "Colour", "capabilities": []},
            {"name": "Pan", "preset": "PositionPan", "group": "Pan", "capabilities": []},
            {"name": "Tilt", "preset": "PositionTilt", "group": "Tilt", "capabilities": []},
            {"name": "Pan Fine", "preset": "PositionPanFine", "group": "Pan", "capabilities": []},
            {"name": "Tilt Fine", "preset": "PositionTiltFine", "group": "Tilt", "capabilities": []},
            {"name": "Gobo", "preset": "GoboWheel", "group": "Gobo", "capabilities": [
                {"min": 0, "max": 7, "preset": None, "name": "Open"},
                {"min": 8, "max": 15, "preset": None, "name": "Gobo 1"},
                {"min": 16, "max": 23, "preset": None, "name": "Gobo 2"},
            ]},
        ],
        "modes": [
            {
                "name": "Standard",
                "channels": [
                    {"number": 0, "name": "Dimmer"},
                    {"number": 1, "name": "Red"},
                    {"number": 2, "name": "Green"},
                    {"number": 3, "name": "Blue"},
                    {"number": 4, "name": "White"},
                    {"number": 5, "name": "Pan"},
                    {"number": 6, "name": "Tilt"},
                    {"number": 7, "name": "Pan Fine"},
                    {"number": 8, "name": "Tilt Fine"},
                    {"number": 9, "name": "Gobo"},
                ],
            }
        ],
    }


@pytest.fixture
def temp_dir():
    """A temporary directory that is cleaned up after the test."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_blocking_modals(monkeypatch):
    """A modal dialog in a test hangs the whole suite, silently.

    QDialog.exec() spins its own event loop and waits for a human. Under
    the offscreen platform there is nobody to click it, so the process
    sits there until someone notices - which cost hours once, when a
    signal test reached a handler that had just learned to open the
    orientation dialog.

    Any test that legitimately drives a dialog patches it out; this turns
    the ones that forget into an immediate, named failure.
    """
    from PyQt6 import QtWidgets

    def _blocked(self, *args, **kwargs):
        raise RuntimeError(
            f"{type(self).__name__}.exec() would block the test suite. "
            "Patch the dialog out, or call its accept/reject path directly.")

    def _blocked_static(name):
        def _raise(*args, **kwargs):
            raise RuntimeError(
                f"{name} would block the test suite. Patch it out.")
        return _raise

    monkeypatch.setattr(QtWidgets.QDialog, "exec", _blocked, raising=False)
    # QMenu is NOT a QDialog, but its exec() is the same modal trap: a
    # context-menu signal fan-out reached the tab's real menu handler
    # and froze two full -n auto runs before anyone looked at the
    # worker stacks (2026-07-14, qt-gotchas #7). Tests that drive a
    # menu patch exec themselves, like the dialogs.
    monkeypatch.setattr(QtWidgets.QMenu, "exec", _blocked, raising=False)
    for cls, methods in (
        (QtWidgets.QInputDialog,
         ("getText", "getInt", "getDouble", "getItem", "getMultiLineText")),
        (QtWidgets.QFileDialog,
         ("getOpenFileName", "getOpenFileNames", "getSaveFileName",
          "getExistingDirectory")),
        (QtWidgets.QColorDialog, ("getColor",)),
        (QtWidgets.QFontDialog, ("getFont",)),
        (QtWidgets.QMessageBox,
         ("information", "warning", "critical", "question", "about")),
    ):
        for method in methods:
            monkeypatch.setattr(cls, method,
                                staticmethod(_blocked_static(
                                    f"{cls.__name__}.{method}()")),
                                raising=False)
