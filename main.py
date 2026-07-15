import sys

# Increase recursion limit for loading large YAML configuration files
# PyYAML uses recursive descent parsing which can exceed Python's default limit (1000)
# for deeply nested structures like timeline data with many light blocks
sys.setrecursionlimit(10000)

# Dump the Python stack to stderr on native crashes (SIGSEGV / Windows
# STATUS_STACK_BUFFER_OVERRUN etc.). Without this, native fatals exit the
# process silently and there's no way to know which Python call site led
# into the offending C extension.
import faulthandler
faulthandler.enable()

import os
from utils import app_identity

# Handle --version flag early
if '--version' in sys.argv:
    print(app_identity.version_string())
    sys.exit(0)

# Headless subcommands run BEFORE any PyQt import so they work with no
# display: `lichtmaschine export config.yaml --out workspace.qxw
# --qlc-version 5.2.1` (utils/export_cli.py).
if len(sys.argv) > 1 and sys.argv[1] == 'export':
    from utils.export_cli import run_export_cli
    sys.exit(run_export_cli(sys.argv[2:]))

# Headless morph (v1.5b): compile a setlist onto a target rig without a
# window (utils/morph_cli.py). Keep above the Qt imports like export.
if len(sys.argv) > 1 and sys.argv[1] == 'morph':
    from utils.morph_cli import run_morph_cli
    sys.exit(run_morph_cli(sys.argv[2:]))

from PyQt6 import QtWidgets
from PyQt6.QtGui import QIcon
from gui import MainWindow
from utils.paths import get_project_root

# Performance profiling - enable with --profile flag
PROFILING_ENABLED = '--profile' in sys.argv
if PROFILING_ENABLED:
    from profiling import profile_playback
    profile_playback.install_all_patches()
    profile_playback.enable_profiling()
    print("\n*** PROFILING ENABLED - Press Ctrl+P in console to print report ***\n")

def main():
    try:
        # Get the project root directory
        project_root = get_project_root()

        # Start the application
        app = QtWidgets.QApplication(sys.argv)
        app.setOrganizationName(app_identity.SETTINGS_ORG)
        app.setApplicationName(app_identity.SETTINGS_APP)
        app.setApplicationDisplayName(app_identity.APP_NAME)
        app.setApplicationVersion(app_identity.APP_VERSION)

        # Structured local logging plus the crash reporter dialog.
        # Installed right after QApplication creation so any startup
        # failure below already lands in the log file.
        from utils.app_logging import setup_logging, install_exception_hooks
        from gui.dialogs.crash_dialog import install_crash_dialog
        setup_logging()
        install_exception_hooks(install_crash_dialog())

        # One-shot copy of persisted settings from the pre-rebrand
        # QLCShowCreator store (theme, splitter sizes, ...).
        from utils.app_settings import migrate_legacy_settings
        migrate_legacy_settings()

        # UI language (i18n scaffolding): installs a translator only if
        # ui/language is set and its compiled catalog exists; must run
        # before any widget is created so shell strings translate.
        from utils.translations import install_translator
        install_translator(app)

        # Brand fonts must register before any widget is created so the
        # stylesheet's font families resolve on first paint.
        from gui.fonts import register_brand_fonts
        register_brand_fonts()

        # Set application icon
        icon_path = app_identity.app_icon_path()
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon)

        # Apply the persisted theme (or the default) before showing the window
        # so the first paint already uses the correct palette.
        from gui.theme_manager import ThemeManager
        theme_manager = ThemeManager()
        theme_manager.apply(app, theme_manager.current() or "dark")

        window = MainWindow()
        window.showMaximized()

        # A project path on the command line - or a file the OS handed us
        # from a .lms double-click once the extension is associated - opens
        # that project as soon as the window is up. Runs after the export
        # subcommand dispatch above, so only GUI launches reach here.
        launch_project = app_identity.project_path_from_argv(sys.argv[1:])
        if launch_project and os.path.isfile(launch_project):
            window.open_project_on_launch(os.path.abspath(launch_project))

        # If profiling, set up periodic report printing
        if PROFILING_ENABLED:
            from PyQt6.QtCore import QTimer
            def print_profile_report():
                profile_playback.print_timings(min_total_ms=10.0)
                profile_playback.reset_timings()

            # Print report every 15 seconds
            profile_timer = QTimer()
            profile_timer.timeout.connect(print_profile_report)
            profile_timer.start(15000)
            print("Profiling report will print every 15 seconds during playback")

        sys.exit(app.exec())

    except Exception as e:
        import logging
        logging.getLogger("crash").exception("Error starting application")
        print(f"Error starting application: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
