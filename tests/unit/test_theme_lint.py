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
   below, by file, enclosing scope and count, which exists only for
   DATA colours: fixture/group/song data
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

def _in(scope, *literals):
    """Allow each literal once in ``scope`` (repeat one to allow it
    twice). Literals are upper-cased hex, as the scanner reports them."""
    return {(lit, scope): literals.count(lit) for lit in literals}


#: The default group/song data palette (the Fixtures-screen palette and
#: its copies).
DATA_PALETTE = ("#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C",
                "#5F86C9", "#C96A5F", "#9A7FD0", "#8D9299")

#: Hex literals allowed in UI string constants, DATA ONLY, as
#: {relpath: {(LITERAL, scope): count}}. The scope is the dotted chain
#: of enclosing classes/functions, or the target of a module- or
#: class-level assignment (see ``_scopes``). Keying by location, not by
#: value, matters: many data colours equal chrome literals the sweep
#: removed (#FFFFFF contrast ink vs the old white "/" separator, the
#: #8D9299 palette entry vs the old patchbay neutral, the accent in a
#: lane palette), so a value-only list would let those come back.
HEX_ALLOWLIST = {
    # The group palette, and the "no colour set" group default.
    "gui/tabs/fixtures_tab.py": {
        **_in("GROUP_PALETTE", *DATA_PALETTE),
        **_in("FixturesTab._ensure_group_color", "#808080"),
        **_in("FixturesTab._update_groups", "#808080"),
        **_in("FixturesTab._update_groups.build_group", "#808080")},
    "gui/tabs/structure_tab.py": {
        **_in("SONG_COLOR_PALETTE", *DATA_PALETTE),
        # ColorButton: its default colour, and the black/white contrast
        # ink picked from the user's part colour.
        **_in("ColorButton.__init__", "#FFFFFF"),
        **_in("ColorButton._update_style", "#000000", "#FFFFFF"),
        # The default part colour of a new part / song.
        **_in("StructureTab._build_part_section", "#4CAF50"),
        **_in("StructureTab._add_new_part", "#4CAF50"),
        **_in("StructureTab._create_new_show", "#4CAF50")},
    "gui/tabs/auto_tab.py": {
        **_in("GROUP_PALETTE", *DATA_PALETTE),
        **_in("VOCAL_COLOR", "#4ECBD4"),
        **_in("INPUT_LEVEL_COLOR", "#D9A441"),
        **_in("AutoTab._group_color", "#808080"),
        # Colour-override presets + the hue-ring gradient (light colours).
        **_in("COLOR_PRESETS", "#FF2850", "#C95FD0", "#4ECBD4"),
        **_in("_ColorWheelButton.paintEvent", "#FF4040", "#F0562E",
              "#40FF70", "#40C8FF", "#8040FF", "#FF40C0", "#FF4040")},
    "gui/tabs/live_tab.py": {
        **_in("GROUP_PALETTE", *DATA_PALETTE),
        **_in("DEFAULT_GROUP_COLOR", "#808080"),
        # The busk COLOUR pool: light colours sent to fixtures.
        **_in("COLOUR_SWATCHES", "#FFFFFF", "#FFB43C", "#FF2850",
              "#C95FD0", "#4ECBD4", "#4060FF", "#40FF70", "#FF2850",
              "#4ECBD4", "#C95FD0", "#FFB43C")},
    # Source-lane wire colours of the morph patchbay (data palette, one
    # per source group, cycled).
    "gui/dialogs/morph_patchbay.py": {
        **_in("LANE_COLOURS", "#D9A441", "#4ECBD4", "#C95FD0", "#6F9E4C",
              "#F0562E", "#8D9299")},
    # Group data-colour default when a fixture's group has none.
    "gui/StageView.py": _in("StageView.update_from_config", "#808080"),
    "visualizer/tcp/client.py": _in(
        "VisualizerTCPClient._handle_groups", "#808080"),
    # Contrast ink on a user-picked colour preset (black/white by
    # lightness of the DATA fill), and the initial black preview.
    "timeline_ui/colour_block_dialog.py": {
        **_in("ColorPresetButton.__init__", "#000000", "#FFFFFF"),
        **_in("ColorPreviewWidget.__init__", "#000000"),
        **_in("ColourBlockDialog.setup_ui", "#000000")},
    # The autogen white swatch: the white light every generated palette
    # carries (data, shown next to the three picked fills).
    "gui/dialogs/autogen_dialog.py": _in(
        "AutogenDialog._build_palette_block", "#FFFFFF"),
    # Developer analysis plot with its own fixed dark data-viz palette;
    # the rich-text role spans mirror ROLE_COLORS.
    "gui/dialogs/generation_inspector.py": _in(
        "GenerationInspector._update_info",
        "#666", "#4B4", "#48C", "#E84", "#888", "#888"),
    # The fixture icon SVGs ship with this stroke colour (both cases);
    # it is the placeholder the loader substitutes with the fixture's
    # data colour.
    "gui/widgets/fixture_icons.py": _in(
        "_SYMBOL_COLOR_TOKENS", "#8D9299", "#8D9299"),
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


def _scopes(tree: ast.AST) -> dict:
    """{id(node): scope} for every node: the dotted chain of enclosing
    classes and functions, plus the assignment target when the string
    sits in a module- or class-level assignment (``LANE_COLOURS``,
    ``ColorButton.__init__``). ``<module>`` for anything else at the
    top level."""
    scopes = {}

    def targets(stmt):
        if isinstance(stmt, ast.Assign):
            nodes = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            nodes = [stmt.target]
        else:
            return []
        return [n.id for t in nodes for n in ast.walk(t)
                if isinstance(n, ast.Name)]

    def visit(node, chain, top_level):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            chain = chain + [node.name]
            top_level = isinstance(node, ast.ClassDef)
        elif top_level and isinstance(node, ast.stmt):
            names = targets(node)
            if names:
                chain = chain + ["/".join(names)]
            top_level = False
        scopes[id(node)] = ".".join(chain) or "<module>"
        for child in ast.iter_child_nodes(node):
            visit(child, chain, top_level)

    visit(tree, [], True)
    return scopes


def _strings(tree: ast.AST):
    """(node, lineno, text) of every string in the module, docstrings
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
            yield node, node.lineno, "".join(text)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs and id(node) not in inside_fstring):
            yield node, node.lineno, node.value


def named_colour_violations():
    out = []
    for path in _ui_sources():
        rel = _rel(path)
        for _node, line, text in _strings(_parse(path)):
            for prop, value in DECL_RE.findall(text):
                if not COLOUR_PROPS.match(prop):
                    continue
                for m in NAMED_RE.finditer(value):
                    name = m.group(1).lower()
                    if (rel, name) not in NAMED_ALLOWLIST:
                        out.append(f"{rel}:{line}: {prop}: {name}")
    return out


def hex_sites_in(tree: ast.AST) -> dict:
    """{(LITERAL, scope): [lineno, ...]} over non-docstring strings."""
    scopes = _scopes(tree)
    found = {}
    for node, line, text in _strings(tree):
        for m in HEX_RE.finditer(text):
            key = ("#" + m.group(1).upper(), scopes[id(node)])
            found.setdefault(key, []).append(line)
    return found


def hex_sites():
    """{relpath: {(LITERAL, scope): [lineno, ...]}} over the UI sources."""
    found = {}
    for path in _ui_sources():
        sites = hex_sites_in(_parse(path))
        if sites:
            found[_rel(path)] = sites
    return found


def hex_offenders(rel: str, sites: dict) -> list:
    """Occurrences beyond what HEX_ALLOWLIST grants ``rel``: a literal
    in a scope the allowlist does not name, or more occurrences of it
    there than the listed count."""
    allowed = HEX_ALLOWLIST.get(rel, {})
    out = []
    for (literal, scope), lines in sorted(sites.items()):
        extra = len(lines) - allowed.get((literal, scope), 0)
        if extra > 0:
            where = ",".join(str(n) for n in sorted(lines))
            out.append(f"{rel}:{where}: {literal} in {scope} "
                       f"({len(lines)} found, {len(lines) - extra} allowed)")
    return out


def test_no_named_colours_in_qss():
    violations = named_colour_violations()
    assert not violations, (
        "QSS must not spell colours by name; read a theme token "
        "(gui.theme_style.active_tokens / bind_style) or add a template "
        "rule. Offenders:\n  " + "\n  ".join(violations))


def test_hex_literals_only_for_allowlisted_data_colours():
    offenders = [o for rel, sites in sorted(hex_sites().items())
                 for o in hex_offenders(rel, sites)]
    assert not offenders, (
        "hex colour literal outside gui/theme_tokens.py: chrome colours "
        "are theme tokens; only DATA colours may be allowlisted (per "
        "file, scope and count) in tests/unit/test_theme_lint.py. "
        "Offenders:\n  " + "\n  ".join(offenders))


def test_allowlists_have_no_stale_entries():
    """Exact: a listed (literal, scope) that occurs fewer times than its
    count fails too, so the list only ever shrinks with the code."""
    present = hex_sites()
    stale = []
    for rel, allowed in sorted(HEX_ALLOWLIST.items()):
        sites = present.get(rel, {})
        for (lit, scope), count in sorted(allowed.items()):
            found = len(sites.get((lit, scope), []))
            if found < count:
                stale.append(f"{rel}: {lit} in {scope} "
                             f"({count} allowed, {found} found)")
    assert not stale, ("allowlisted hex literal no longer in the code; "
                       "lower or drop it in HEX_ALLOWLIST:\n  "
                       + "\n  ".join(stale))
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


def _offenders_after(rel: str, old: str, new: str) -> list:
    """hex_offenders for ``rel`` with ``old`` replaced by ``new`` (once,
    in memory): what the lint would say about that edit."""
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        source = f.read()
    assert source.count(old) == 1, f"{rel}: anchor {old!r} not unique"
    return hex_offenders(rel, hex_sites_in(ast.parse(source.replace(old, new))))


@pytest.mark.parametrize("rel,old,new", [
    # The white time-signature "/" the sweep exists for. #FFFFFF is
    # allowlisted in this file, but only as ColorButton's ink/default.
    ("gui/tabs/structure_tab.py",
     'separator.setObjectName("TimeSignatureSeparator")',
     'separator.setStyleSheet("color: #FFFFFF;")'),
    # A second #FFFFFF QSS declaration inside an allowlisted scope: the
    # count grows past what the allowlist grants.
    ("gui/tabs/structure_tab.py",
     'text_color = "#000000" if luminance > 0.5 else "#FFFFFF"',
     'text_color = "#000000" if luminance > 0.5 else "#FFFFFF"\n'
     '        self.setStyleSheet("border: 1px solid #FFFFFF;")'),
    # The dark-only patchbay neutral d824bcb fixed for light; #8D9299 is
    # allowlisted here only as the last LANE_COLOURS entry.
    ("gui/dialogs/morph_patchbay.py",
     "colour = NEUTRAL", 'colour = "#8d9299"'),
    # The accent, allowlisted only in the lane palette and the hue ring.
    ("gui/dialogs/morph_patchbay.py",
     "colour = NEUTRAL", 'colour = "#F0562E"'),
    ("gui/tabs/structure_tab.py",
     'separator.setObjectName("TimeSignatureSeparator")',
     'separator.setStyleSheet("color: #4CAF50;")'),
])
def test_allowlisted_value_in_a_new_place_is_rejected(rel, old, new):
    """Self-test: the allowlist is keyed by location, not by value, so
    a chrome literal that happens to equal a data colour of the same
    file is still caught."""
    assert not _offenders_after(rel, old, old)
    assert _offenders_after(rel, old, new)


def test_scopes_name_assignment_targets_and_defs():
    tree = ast.parse(
        'A = ("#111111",)\n'
        'class K:\n'
        '    B = "#222222"\n'
        '    def f(self):\n'
        '        x = "#333333"\n'
        '        def g():\n'
        '            return "#444444"\n'
        'print("#555555")\n')
    assert sorted(hex_sites_in(tree)) == [
        ("#111111", "A"), ("#222222", "K.B"), ("#333333", "K.f"),
        ("#444444", "K.f.g"), ("#555555", "<module>")]


# --- One theme sniff -------------------------------------------------

#: The one module allowed to read the applied stylesheet for the theme.
SNIFF_HOME = "gui/theme_style.py"
#: Helper names that mean "a private copy of active_tokens".
SNIFF_NAME_RE = re.compile(r"^_*(active|current|theme|applied)_tokens$")


def _tracked_sources():
    """Every tracked production .py file (tests excluded)."""
    import subprocess
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if not p.startswith("tests/")]


def sniff_copies_in(tree: ast.AST) -> list:
    """Functions that are (or look like) a private copy of
    gui.theme_style.active_tokens: named like it, or reading the app
    stylesheet (``.styleSheet()``) and the THEMES table together."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if SNIFF_NAME_RE.match(node.name):
            found.append((node.lineno, node.name))
            continue
        reads_sheet = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "styleSheet" and not n.args
            for n in ast.walk(node))
        reads_themes = any(isinstance(n, ast.Name) and n.id == "THEMES"
                           for n in ast.walk(node))
        if reads_sheet and reads_themes:
            found.append((node.lineno, node.name))
    return found


def test_no_private_copy_of_the_theme_sniff():
    """The v1.5.6 follow-up folded a dozen per-module ``_active_tokens``
    copies onto gui.theme_style.active_tokens; keep it the only one."""
    offenders = []
    for rel in _tracked_sources():
        if rel == SNIFF_HOME:
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        for line, name in sniff_copies_in(_parse(path)):
            offenders.append(f"{rel}:{line}: {name}")
    assert not offenders, (
        "read the active theme through gui.theme_style.active_tokens "
        "(deferred import inside timeline_ui, which the gui package "
        "imports); no private copies:\n  " + "\n  ".join(offenders))


def test_sniff_scanner_finds_a_copy():
    """Self-test: both shapes of copy are caught, the real one is the
    reference, and an unrelated styleSheet() read is not a copy."""
    copy = ast.parse(
        "def _active_tokens():\n    return {}\n"
        "def pick():\n"
        "    qss = QApplication.instance().styleSheet()\n"
        "    return THEMES['light'] if 'x' in qss else THEMES['dark']\n"
        "def unrelated(w):\n"
        "    w.setStyleSheet(w.styleSheet() + 'padding: 2px;')\n")
    assert [n for _l, n in sniff_copies_in(copy)] == ["_active_tokens",
                                                       "pick"]
    home = _parse(os.path.join(ROOT, SNIFF_HOME))
    assert [n for _l, n in sniff_copies_in(home)] == ["active_tokens"]
