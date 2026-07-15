"""Diagnostics report for bug reports (ROADMAP v1.4).

One markdown block a user can paste into a GitHub issue: app version,
Python/Qt, platform, OpenGL renderer, audio host APIs, ArtNet output
state, project path, log folder. Every probe is individually guarded -
a machine where one subsystem is broken is exactly the machine that
needs this report, so a failing probe reports its error string instead
of taking the panel down. Qt-free except for the version constants so
it stays importable headlessly; the GL probe spins up (and releases) a
standalone context only when asked.
"""

import os
import platform
import sys


def _guarded(probe):
    try:
        return probe()
    except Exception as exc:
        return f"unavailable ({exc.__class__.__name__}: {exc})"


def _app_section() -> list:
    from utils.app_identity import APP_VERSION, PROJECT_EXT

    def qt_versions():
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        return f"Qt {QT_VERSION_STR} · PyQt {PYQT_VERSION_STR}"

    return [
        ("Version", _guarded(lambda: APP_VERSION)),
        ("Python", f"{platform.python_version()} "
                   f"({platform.architecture()[0]})"),
        ("Qt", _guarded(qt_versions)),
        ("Platform", f"{platform.system()} {platform.release()} "
                     f"({platform.version()})"),
        ("Frozen", "yes (packaged)" if getattr(sys, "frozen", False)
         else "no (source)"),
        ("Project format", PROJECT_EXT),
    ]


def _gl_probe() -> str:
    """Renderer string from a throwaway standalone context."""
    import moderngl
    ctx = moderngl.create_standalone_context()
    try:
        info = ctx.info
        return (f"{info.get('GL_RENDERER', '?')} · "
                f"{info.get('GL_VENDOR', '?')} · "
                f"GL {info.get('GL_VERSION', '?')}")
    finally:
        ctx.release()


def _audio_probe() -> str:
    import sounddevice as sd
    apis = [a["name"] for a in sd.query_hostapis()]
    return ", ".join(apis) if apis else "none detected"


def _output_section(main_window) -> list:
    def arbiter_state():
        arbiter = main_window.output_arbiter()
        status = arbiter.status()
        if not status["running"]:
            return "idle (loop not running)"
        mapping = status["universe_mapping"]
        universes = ", ".join(
            f"{k}->{v}" for k, v in sorted(mapping.items())) or "none"
        return (f"streaming · {status['frames_sent']} frames sent · "
                f"universes {universes}")

    rows = [("ArtNet output",
             _guarded(arbiter_state) if main_window is not None
             else "unavailable (no main window)")]
    if main_window is not None:
        def universe_count():
            return str(len(main_window.config.universes))
        rows.append(("Configured universes", _guarded(universe_count)))
    return rows


def _project_section(main_window) -> list:
    from utils.app_logging import log_dir

    def project_path():
        path = getattr(main_window, "config_path", None)
        return path or "untitled (never saved)"

    return [
        ("Project", _guarded(project_path) if main_window is not None
         else "unavailable (no main window)"),
        ("Log folder", _guarded(log_dir)),
    ]


def gather(main_window=None, gl_probe=_gl_probe,
           audio_probe=_audio_probe) -> list:
    """[(section, [(name, value), ...]), ...] - the report data.

    ``main_window`` supplies the live state (output arbiter, project
    path); None degrades those rows. The GL/audio probes are injectable
    because both touch real drivers.
    """
    return [
        ("Application", _app_section()),
        ("Graphics", [("OpenGL", _guarded(gl_probe))]),
        ("Audio", [("Host APIs", _guarded(audio_probe))]),
        ("Output", _output_section(main_window)),
        ("Project", _project_section(main_window)),
    ]


def to_markdown(sections: list) -> str:
    """The copy-paste block for a bug report."""
    from utils.app_identity import APP_NAME
    lines = [f"### {APP_NAME} diagnostics", ""]
    for title, rows in sections:
        lines.append(f"**{title}**")
        lines.append("")
        for name, value in rows:
            lines.append(f"- {name}: `{value}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def report(main_window=None, **kwargs) -> str:
    return to_markdown(gather(main_window, **kwargs))
