"""The app boots with NO console std streams (windowed launch).

Found packing for the Stellwerk gig (2026-07-18): the packaged exe
(PyInstaller console=False) died on DOUBLE-CLICK with
``RuntimeError: sys.stderr is None`` from ``faulthandler.enable()`` at
the top of main.py, before any window - while every shell launch
(and thus every CLI smoke test) inherits console handles and works.
``pythonw`` reproduces the None-stderr environment without a frozen
build; the fix routes the fault dumps to the app log dir instead.
"""

import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


@pytest.mark.skipif(sys.platform != "win32",
                    reason="pythonw is the Windows windowed launcher")
def test_main_boots_without_std_streams(tmp_path):
    pythonw = os.path.join(os.path.dirname(sys.executable),
                           "pythonw.exe")
    if not os.path.isfile(pythonw):
        pytest.skip("no pythonw.exe next to this interpreter")
    env = dict(os.environ)
    env["QLC_LOG_DIR"] = str(tmp_path)   # crash dumps land here
    proc = subprocess.run(
        [pythonw, os.path.join(REPO, "main.py"), "--version"],
        cwd=REPO, env=env, timeout=180)
    assert proc.returncode == 0, \
        "windowed boot (sys.stderr None) must not crash before main"
