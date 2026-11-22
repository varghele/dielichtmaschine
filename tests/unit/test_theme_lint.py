"""Theme lint: UI chrome colours come from gui/theme_tokens.py.

The v1.5.6 theme sweep moved every hard-coded chrome colour in the UI
packages onto theme tokens (the light theme had inherited dark-only
literals such as the Structure tab's ``color: white`` separator). Two
static checks keep it that way:

1. No QSS declaration in the UI packages may spell a colour by CSS
   name (``color: white``, ``border: 1px solid red``, ...). Every
   string is scanned, not just literal ``setStyleSheet`` arguments, so
   ``gui.theme_style.bind_style`` builders and rule lists are covered.
   Read a token (``gui.theme_style.active_tokens`` / ``bind_style``) or
   key a template rule by objectName / dynamic property instead.
2. Every hex colour literal anywhere in the UI packages' string
   constants (docstrings excluded) must be listed in ``HEX_ALLOWLIST``
   below, which exists only for DATA colours: fixture/group/song data
   palettes, light colours the user picks or busks, contrast ink chosen
   from a data fill, and self-contained palettes that are deliberately
   theme-independent. A new chrome colour belongs in theme_tokens.py.

``visualizer/renderer/`` is out of scope: its colours are GL scene
colours, not Qt chrome. ``utils/`` is out of scope: its colours are
fixture data and export payloads.

The allowlist must stay exact: a listed literal that no longer occurs
fails too, so the list only ever shrinks with the code.
"""

import ast
import os
import re

import pytest

from utils.paths import get_project_root

ROOT = get_project_root()

#: Packages whose string constants are UI chrome unless allowlisted.
SCAN_DIRS = ("gui", "timeline_ui", "visualizer")
#: The one place chrome colours are spelled out.
TOKENS_FILE = "gui/theme_tokens.py"
#: GL scene colours (not Qt chrome) live here.
EXCLUDED_DIRS = (os.path.join("visualizer", "renderer"),)

HEX_RE = re.compile(
    r"(?<![\w&])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![\w-])")

#: CSS colour keywords that would bypass the tokens inside a QSS string.
#: ``transparent`` is deliberately absent: it is not a colour role.
NAMED_COLOURS = (
    "white", "black", "red", "green", "blue", "yellow", "orange", "gray",
    "grey", "purple", "magenta", "cyan", "pink", "brown", "navy", "silver",
    "lime", "maroon", "olive", "teal", "aqua", "fuchsia", "darkgray",
    "darkgrey", "lightgray", "lightgrey", "darkred", "darkgreen",
    "darkblue", "lightblue", "lightgreen", "gold", "violet", "indigo",
)
NAMED_RE = re.compile(
    r"(?<![\w#-])(" + "|".join(NAMED_COLOURS) + r")(?![\w-])", re.IGNORECASE)
#: ``property: value`` pairs inside a QSS fragment.
DECL_RE = re.compile(r"([A-Za-z-]+)\s*:\s*([^;{}]+)")

#: QSS properties whose value is (or carries) a colour.
COLOUR_PROPS = re.compile(
    r"^(color|background(-color)?|border(-(top|right|bottom|left))?"
    r"(-color)?|outline(-color)?|selection-(background-)?color|"
    r"alternate-background-color|gridline-color)$", re.IGNORECASE)

#: Named colours allowed in a QSS declaration, as (relative path, name).
#: DATA colours only; empty since the v1.5.6 sweep.
NAMED_ALLOWLIST = set()

#: Hex literals allowed in UI string constants, per file. DATA ONLY.
HEX_ALLOWLIST = {
    # Default group/song data palettes (the Fixtures-screen palette and
    # its copies) and the "no colour set" group default.
    "gui/tabs/fixtures_tab.py": {
        "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C", "#5F86C9", "#C96A5F",
        "#9A7FD0", "#8D9299", "#808080"},
    "gui/tabs/structure_tab.py": {
        "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C", "#5F86C9", "#C96A5F",
        "#9A7FD0", "#8D9299",
        # ColorButton: default part colour, and black/white contrast ink
        # picked from the user's part colour.
        "#FFFFFF", "#4CAF50", "#000000"},
    "gui/tabs/auto_tab.py": {
        "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C", "#5F86C9", "#C96A5F",
        "#9A7FD0", "#8D9299", "#808080",
        # Colour-override presets + the hue-ring gradient (light colours).
        "#FF2850", "#FF4040", "#F0562E", "#40FF70", "#40C8FF", "#8040FF",
        "#FF40C0"},
    "gui/tabs/live_tab.py": {
        "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C", "#5F86C9", "#C96A5F",
        "#9A7FD0", "#8D9299", "#808080",
        # The busk COLOUR pool: light colours sent to fixtures.
        "#FFFFFF", "#FFB43C", "#FF2850", "#4060FF", "#40FF70"},
    # Source-lane wire colours of the morph patchbay (data palette, one
    # per source group, cycled).
    "gui/dialogs/morph_patchbay.py": {
        "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C", "#F0562E", "#8D9299"},
    # Group data-colour default when a fixture's group has none.
    "gui/StageView.py": {"#808080"},
    "visualizer/tcp/client.py": {"#808080"},
    # Contrast ink on a user-picked colour preset (black/white by
    # lightness of the DATA fill), and the initial black preview.
    "timeline_ui/colour_block_dialog.py": {"#000000", "#FFFFFF"},
    # The autogen white swatch: the white light every generated palette
    # carries (data, shown next to the three picked fills).
    "gui/dialogs/autogen_dialog.py": {"#FFFFFF"},
    # Developer analysis plots with their own fixed dark data-viz
    # palette (QColor constants at the module top); the rich-text role
    # spans mirror ROLE_COLORS.
    "gui/dialogs/generation_inspector.py": {
        "#666", "#4B4", "#48C", "#E84", "#888"},
    # The fixture icon SVGs ship with this stroke colour; it is the
    # placeholder the loader substitutes with the fixture's data colour.
    "gui/widgets/fixture_icons.py": {"#8D9299"},
}


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _ui_sources():
    for top in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, top)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            rel_dir = os.path.relpath(dirpath, ROOT)
            if any(rel_dir == ex or rel_dir.startswith(ex + os.sep)
                   for ex in EXCLUDED_DIRS):
                continue
            for name in filenames:
                path = os.path.join(dirpath, name)
                if name.endswith(".py") and _rel(path) != TOKENS_FILE:
                    yield path


def _parse(path: str) -> ast.AST:
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _docstring_nodes(tree: ast.AST) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _strings(tree: ast.AST):
    """(lineno, text) of every string in the module, docstrings
    excluded. An f-string is one string with its holes as 'X' (a token
    read), so a declaration split across holes is still seen whole."""
    docs = _docstring_nodes(tree)
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = []
            for part in node.values:
                inside_fstring.add(id(part))
                if isinstance(part, ast.Constant):
                    text.append(str(part.value))
                else:
                    text.append("X")
            yield node.lineno, "".join(text)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs and id(node) not in inside_fstring):
            yield node.lineno, node.value


def named_colour_violations():
    out = []
    for path in _ui_sources():
        rel = _rel(path)
        for line, text in _strings(_parse(path)):
            for prop, value in DECL_RE.findall(text):
                if not COLOUR_PROPS.match(prop):
                    continue
                for m in NAMED_RE.finditer(value):
                    name = m.group(1).lower()
                    if (rel, name) not in NAMED_ALLOWLIST:
                        out.append(f"{rel}:{line}: {prop}: {name}")
    return out


def hex_literals():
    """{relpath: {(LITERAL, lineno), ...}} over non-docstring strings."""
    found = {}
    for path in _ui_sources():
        rel = _rel(path)
        for line, text in _strings(_parse(path)):
            for m in HEX_RE.finditer(text):
                found.setdefault(rel, set()).add(
                    ("#" + m.group(1).upper(), line))
    return found


def test_no_named_colours_in_qss():
    violations = named_colour_violations()
    assert not violations, (
        "QSS must not spell colours by name; read a theme token "
        "(gui.theme_style.active_tokens / bind_style) or add a template "
        "rule. Offenders:\n  " + "\n  ".join(violations))


def test_hex_literals_only_for_allowlisted_data_colours():
    offenders = []
    for rel, hits in sorted(hex_literals().items()):
        allowed = HEX_ALLOWLIST.get(rel, set())
        for literal, line in sorted(hits, key=lambda h: h[1]):
            if literal not in allowed:
                offenders.append(f"{rel}:{line}: {literal}")
    assert not offenders, (
        "hex colour literal outside gui/theme_tokens.py: chrome colours "
        "are theme tokens; only DATA colours may be allowlisted in "
        "tests/unit/test_theme_lint.py. Offenders:\n  "
        + "\n  ".join(offenders))


def test_allowlists_have_no_stale_entries():
    present = {rel: {lit for lit, _ in hits}
               for rel, hits in hex_literals().items()}
    stale = [f"{rel}: {lit}" for rel, lits in sorted(HEX_ALLOWLIST.items())
             for lit in sorted(lits) if lit not in present.get(rel, set())]
    assert not stale, ("allowlisted hex literal no longer in the code; "
                       "drop it from HEX_ALLOWLIST:\n  " + "\n  ".join(stale))
    for rel, _name in NAMED_ALLOWLIST:
        assert os.path.isfile(os.path.join(ROOT, rel)), rel


def test_allowlisted_files_are_scanned():
    scanned = {_rel(p) for p in _ui_sources()}
    missing = sorted(set(HEX_ALLOWLIST) - scanned)
    assert not missing, missing


def _named_in(snippet: str):
    return [m.group(1).lower()
            for prop, value in DECL_RE.findall(snippet)
            if COLOUR_PROPS.match(prop)
            for m in NAMED_RE.finditer(value)]


@pytest.mark.parametrize("snippet,expected", [
    ("color: white;", ["white"]),
    ("QLabel { border: 1px solid Red; }", ["red"]),
    ("QFrame#Card { border: 1px solid X; }", []),
    ("#GroupRow { border-left: 3px solid X; }", []),
    ("background: transparent;", []),
    ("QPushButton:hover { border-color: X; }", []),
    ("font-family: 'Barlow'; font-weight: bold;", []),
])
def test_scanner_reads_colours_not_selectors(snippet, expected):
    """Self-test: objectName selectors, pseudo-states and non-colour
    properties are not colours; f-string holes (X) are token reads."""
    assert _named_in(snippet) == expected


def test_hex_scanner_skips_object_names():
    assert not HEX_RE.search("#GroupRow { } #AutoBpmDisplay { }")
    assert HEX_RE.search("color: #888;")
