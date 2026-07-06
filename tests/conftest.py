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
# (GDTF Share downloads, gitignored, contents vary per machine). GDTF wins
# identity clashes by design, so a downloaded file would otherwise shadow
# the bundled .qxf definitions that tests are written against. GDTF tests
# opt back in by monkeypatching fixture_search_dirs themselves.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _exclude_local_gdtf_library():
    from utils import fixture_library as fl
    real = fl.fixture_search_dirs
    fl.fixture_search_dirs = lambda: [
        (path, source) for path, source in real() if source != "gdtf"
    ]
    fl.clear_library_cache()
    yield
    fl.fixture_search_dirs = real
    fl.clear_library_cache()


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
