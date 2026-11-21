# tests/unit/test_core_imports_without_qt.py
"""The core packages import without PyQt6 (v1.5.6).

The headless export and morph CLIs (``python main.py export|morph``)
dispatch before any Qt import, so everything they reach must stay
Qt-free. The Qt-facing classes moved to the GUI side: the Auto Mode
widgets to ``gui/widgets/auto/``, the waveform widget to
``timeline_ui/audio_waveform_widget.py``, the spectral feature bridge to
``gui/live_feature_bridge.py`` and the LTC signal boundary to
``gui/ltc_input_service.py`` (the LTC core stays in
``audio/ltc_input.py``).

A subprocess installs a meta-path finder that refuses every PyQt6
module, then imports each core package and every submodule in it.

One known exception: ``auto.dmx_output`` imports ``utils.artnet``,
whose ``__init__`` eagerly imports the Qt-based
``ShowsArtNetController``. utils/ is outside this move, so that module
is excluded here (and pinned as the only exclusion).
"""

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

CORE_PACKAGES = ["audio", "auto", "timeline", "autogen", "config",
                 "effects", "riffs", "rudiments", "scenes"]

#: Submodules that still need Qt, for reasons outside the core package.
KNOWN_QT_DEPENDENT = {"auto.dmx_output"}   # via utils.artnet.__init__

_PROBE = r"""
import importlib, json, pkgutil, sys

class _BlockQt:
    def find_spec(self, name, path=None, target=None):
        if name == "PyQt6" or name.startswith("PyQt6."):
            raise ImportError("PyQt6 is blocked: " + name)

sys.meta_path.insert(0, _BlockQt())
packages, skip = json.loads(sys.argv[1]), set(json.loads(sys.argv[2]))
imported, failed = [], {}
for pkg in packages:
    try:
        module = importlib.import_module(pkg)
    except Exception as exc:
        failed[pkg] = repr(exc)
        continue
    imported.append(pkg)
    for info in pkgutil.walk_packages(module.__path__, pkg + "."):
        if info.name in skip:
            continue
        try:
            importlib.import_module(info.name)
            imported.append(info.name)
        except Exception as exc:
            failed[info.name] = repr(exc)
qt = sorted(m for m in sys.modules if m.split(".")[0] == "PyQt6")
print(json.dumps({"imported": imported, "failed": failed, "qt": qt}))
"""


def _run_probe(packages, skip=()):
    out = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps(packages),
         json.dumps(sorted(skip))],
        cwd=REPO, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_core_packages_import_with_pyqt6_blocked():
    result = _run_probe(CORE_PACKAGES, KNOWN_QT_DEPENDENT)
    assert result["failed"] == {}
    assert result["qt"] == []
    imported = set(result["imported"])
    # The walk really reached the submodules (config is a namespace
    # package, the LTC core and the audio analysis are the CLI's path).
    for name in ("config.models", "config.compact_serializer",
                 "audio.ltc_input", "audio.live_input",
                 "audio.spectral_analysis", "audio.waveform_analyzer",
                 "auto.engine", "timeline.light_lane",
                 "autogen.generator", "effects.dimmer_effects",
                 "riffs.riff_library", "rudiments.registry",
                 "scenes.scene_library"):
        assert name in imported, name


def test_the_moved_qt_modules_are_gone_from_core():
    # Source files only: a stale __pycache__ may outlive a checkout.
    for path in ("auto/widgets/__init__.py",
                 "audio/audio_waveform_widget.py",
                 "audio/live_feature_bridge.py"):
        assert not os.path.exists(os.path.join(REPO, path)), path


def test_known_exclusion_still_needs_qt():
    """If utils.artnet stops importing Qt eagerly, drop the exclusion
    so auto.dmx_output is covered too."""
    result = _run_probe(["auto"])
    assert set(result["failed"]) == KNOWN_QT_DEPENDENT
