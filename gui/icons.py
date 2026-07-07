"""Brand line-icon factory.

The North Star icon language is 16x16 line SVGs, stroke 1.5,
``currentColor`` (design_handoff_lichtmaschine_app/README.md). The
files live in resources/icons/ - most extracted verbatim from the
North Star boards, open/import authored in the same style.

Qt's QIcon cannot resolve ``currentColor``, so :func:`line_icon`
substitutes a concrete color into the SVG text and rasterizes it via
QtSvg (at 1x/2x/3x so HiDPI stays crisp). :func:`shell_icon` picks the
color from the active theme's tokens; after a theme switch call the
factory again and re-set the icons (Ui_MainWindow.apply_shell_icons
does that for the topbar).
"""

import os

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap

from utils.paths import get_project_root


def icons_dir() -> str:
    return os.path.join(get_project_root(), "resources", "icons")


def line_icon(name: str, color: str, size: int = 16) -> QIcon:
    """Rasterize resources/icons/<name>.svg with ``color`` for
    currentColor. Returns a null QIcon when the file is missing (the
    button then simply shows nothing rather than crashing)."""
    from PyQt6.QtSvg import QSvgRenderer

    path = os.path.join(icons_dir(), f"{name}.svg")
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except OSError:
        print(f"icons: missing {path}")
        return QIcon()

    svg = svg.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        print(f"icons: invalid SVG {path}")
        return QIcon()

    icon = QIcon()
    for scale in (1, 2, 3):
        px = size * scale
        image = QImage(px, px, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(scale)
        icon.addPixmap(pixmap)
    return icon


def shell_icon(name: str, theme: str = None) -> QIcon:
    """A line icon in the active theme's secondary text color."""
    from gui.theme_manager import ThemeManager
    from gui.theme_tokens import THEMES

    if theme is None:
        theme = ThemeManager().current() or "dark"
    tokens = THEMES.get(theme) or THEMES["dark"]
    return line_icon(name, tokens["text_secondary"])
