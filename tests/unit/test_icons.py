"""Brand line-icon factory: files, rasterization, theme colors."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.icons import icons_dir, line_icon, shell_icon

SHELL_ICONS = ["save", "open", "import", "export", "morph", "audio",
               "settings", "menu"]

# Timeline-chrome icons (Shows tab transport + 3D-pane chevron, North
# Star card 4a). Authored in-repo in the same 16px/stroke-1.5 line
# style; they get the same file/style/render checks as the shell set.
TRANSPORT_ICONS = ["play", "pause", "stop", "chevron-left", "chevron-right"]

ALL_ICONS = SHELL_ICONS + TRANSPORT_ICONS


def _pixels(icon, size=16):
    from tests.visual.harness import qimage_to_array
    return qimage_to_array(icon.pixmap(size, size).toImage())


class TestIconFiles:
    def test_all_shell_icons_shipped(self):
        for name in ALL_ICONS:
            assert os.path.isfile(
                os.path.join(icons_dir(), f"{name}.svg")), name

    def test_svgs_use_current_color_line_style(self):
        for name in ALL_ICONS:
            with open(os.path.join(icons_dir(), f"{name}.svg")) as f:
                svg = f.read()
            assert 'stroke="currentColor"' in svg, name
            assert 'stroke-width="1.5"' in svg, name
            assert 'fill="none"' in svg, name


class TestLineIcon:
    def test_renders_nonempty(self, qapp):
        for name in ALL_ICONS:
            icon = line_icon(name, "#8D9299")
            assert not icon.isNull(), name
            arr = _pixels(icon)
            assert (arr[:, :, 3] > 0).any(), f"{name} rendered no pixels"

    def test_color_is_substituted(self, qapp):
        red = _pixels(line_icon("save", "#FF0000"))
        blue = _pixels(line_icon("save", "#0000FF"))
        opaque = red[:, :, 3] > 200
        assert opaque.any()
        assert red[opaque][:, 0].mean() > 200      # red channel dominates
        assert blue[opaque][:, 2].mean() > 200     # blue channel dominates

    def test_missing_icon_degrades_to_null(self, qapp):
        assert line_icon("does-not-exist", "#fff").isNull()

    def test_hidpi_sizes_present(self, qapp):
        icon = line_icon("menu", "#8D9299")
        sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
        assert (16, 16) in sizes
        assert (32, 32) in sizes


class TestShellIcon:
    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_theme_color_applies(self, qapp, theme):
        icon = shell_icon("save", theme)
        assert not icon.isNull()
        assert (_pixels(icon)[:, :, 3] > 0).any()
