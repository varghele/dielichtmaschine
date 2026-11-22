"""i18n beyond the shell: every translate() call in the UI packages has
a German entry in translations/lichtmaschine_de.ts, and every call is
one pylupdate6 can actually see.

The AST half walks gui/, timeline_ui/ and visualizer/ (the same trees
scripts/update_translations.py hands pylupdate6). The rules:

- the context argument is always a string literal;
- the source argument is a string literal, or a plain reference
  (name, attribute, subscript, ``.get``) to a constant marked with
  ``QT_TRANSLATE_NOOP`` under the same context (in any UI module: the
  morph screen shows the patchbay's sub-lane labels). Constants cannot
  call translate() at import time (the translator is installed later),
  so they are marked for pylupdate6 and translated where shown;
- never an f-string, a concatenation, a ``%`` or a ``.format`` INSIDE
  the call (format after translate, so the catalog key is the template);
- no alias (``_translate = QCoreApplication.translate``): pylupdate6
  cannot follow it.

The runtime half installs a translator built from the .ts itself (no
compiled .qm needed) and checks the screens that used to read their
displayed text back still behave in German.
"""

import ast
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI_PACKAGES = ("gui", "timeline_ui", "visualizer")
TS_PATH = os.path.join(ROOT, "translations", "lichtmaschine_de.ts")
_RECEIVERS = {"QCoreApplication", "QtCore.QCoreApplication"}


def _ui_files():
    for package in UI_PACKAGES:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, package)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def _is_qt_translate(func) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "translate"
            and ast.unparse(func.value) in _RECEIVERS)


def _is_noop(func) -> bool:
    return isinstance(func, ast.Name) and func.id == "QT_TRANSLATE_NOOP"


def _literal(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _plain_reference(node) -> bool:
    """A name, attribute or subscript chain, or a ``.get(...)`` lookup
    on one: what reading a marked constant looks like."""
    if isinstance(node, (ast.Name, ast.Attribute)):
        return True
    if isinstance(node, ast.Subscript):
        return _plain_reference(node.value)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"):
        return _plain_reference(node.func.value)
    return False


def _scan():
    """(literal pairs, violations) over every UI module."""
    pairs = {}
    violations = []
    noop_contexts = set()
    dynamic = []
    for path in _ui_files():
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=rel)
        call_funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "translate"
                    and ast.unparse(node.value) in _RECEIVERS
                    and id(node) not in call_funcs):
                violations.append(f"{rel}:{node.lineno}: translate aliased or "
                                  f"passed around (pylupdate6 cannot see it)")
            if not isinstance(node, ast.Call):
                continue
            noop = _is_noop(node.func)
            if not (noop or _is_qt_translate(node.func)):
                continue
            where = f"{rel}:{node.lineno}"
            args = node.args
            if node.keywords or len(args) < 2:
                violations.append(f"{where}: expected (context, source) positional args")
                continue
            context, source = args[0], args[1]
            if not _literal(context):
                violations.append(f"{where}: context is not a string literal")
                continue
            for extra in args[2:3]:
                if not (_literal(extra) or (isinstance(extra, ast.Constant)
                                            and extra.value is None)):
                    violations.append(f"{where}: disambiguation is not a literal")
            if _literal(source):
                pairs.setdefault((context.value, source.value), where)
                if noop:
                    noop_contexts.add(context.value)
            elif noop:
                violations.append(f"{where}: QT_TRANSLATE_NOOP source is not a literal")
            elif _plain_reference(source):
                dynamic.append((where, context.value))
            else:
                violations.append(f"{where}: source is built inside translate() "
                                  f"({type(source).__name__}); format after it")
    for where, context in dynamic:
        if context not in noop_contexts:
            violations.append(f"{where}: non-literal source in context "
                              f"'{context}' but no QT_TRANSLATE_NOOP "
                              f"constant is marked for it")
    return pairs, violations


def _catalog():
    root = ET.parse(TS_PATH).getroot()
    entries = {}
    for ctx in root.findall("context"):
        name = ctx.findtext("name")
        for message in ctx.findall("message"):
            translation = message.find("translation")
            entries[(name, message.findtext("source"))] = (
                translation.text or "", translation.get("type"))
    return entries


@pytest.fixture(scope="module")
def scan():
    return _scan()


@pytest.fixture(scope="module")
def catalog():
    return _catalog()


def test_every_translate_call_is_visible_to_pylupdate(scan):
    _, violations = scan
    assert not violations, "\n".join(violations)


def test_the_ui_beyond_the_shell_is_wrapped(scan):
    pairs, _ = scan
    contexts = {ctx for ctx, _ in pairs}
    # A floor, not a census: the big screens and dialogs all carry
    # their own context now, alongside the shell.
    for expected in ("Shell", "MainWindow", "StructureTab", "ShowsTab",
                     "StageTab", "LiveTab", "AutoTab", "FixturesTab",
                     "MorphScreen", "MovementBlockDialog"):
        assert expected in contexts, expected
    assert len(pairs) > 1500


def test_every_source_has_a_german_translation(scan, catalog):
    pairs, _ = scan
    missing = []
    for key, where in sorted(pairs.items(), key=lambda kv: kv[1]):
        text, kind = catalog.get(key, ("", "missing"))
        if kind in ("missing", "unfinished", "vanished", "obsolete") or not text.strip():
            missing.append(f"{where}: [{key[0]}] {key[1]!r} ({kind or 'empty'})")
    assert not missing, (
        "run scripts/update_translations.py and translate:\n" + "\n".join(missing))


_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def test_german_keeps_placeholders_and_accelerators(catalog):
    bad = []
    for (ctx, source), (text, kind) in catalog.items():
        if kind in ("vanished", "obsolete") or not text:
            continue
        if Counter(_PLACEHOLDER.findall(source)) != Counter(_PLACEHOLDER.findall(text)):
            bad.append(f"[{ctx}] {source!r}: placeholders differ")
        if source.count("&") != text.count("&"):
            bad.append(f"[{ctx}] {source!r}: accelerators differ")
    assert not bad, "\n".join(bad)


def test_german_uses_no_em_dash_and_no_du_form(catalog):
    du = re.compile(r"\b(du|dein\w*|dich|dir|willst|kannst|musst)\b", re.IGNORECASE)
    bad = [f"[{ctx}] {source!r}" for (ctx, source), (text, kind) in catalog.items()
           if kind not in ("vanished", "obsolete")
           and ("—" in text or du.search(text))]
    assert not bad, "\n".join(bad)


_LOGGER_NAMES = {"logger", "_logger", "_audio_logger", "log", "logging"}
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception",
                "critical", "log"}


def _is_english_sink(func) -> bool:
    """user_warnings.warn / .operation and logger calls: their text lands
    in the file log and Help > Warnings, which stay English on purpose
    (one language for bug reports, whatever the UI shows)."""
    if not isinstance(func, ast.Attribute):
        return False
    receiver = ast.unparse(func.value)
    if func.attr in ("warn", "operation") and (
            receiver == "user_warnings" or receiver.endswith("get_log()")):
        return True
    return receiver in _LOGGER_NAMES and func.attr in _LOG_METHODS


def _contains_translate(node) -> bool:
    return any(isinstance(n, ast.Call) and _is_qt_translate(n.func)
               for n in ast.walk(node))


def test_warnings_and_log_messages_stay_english():
    """No translate() reaches user_warnings or a logger, directly or via
    a local name assigned from a translate() in the same function."""
    offenders = []
    for path in _ui_files():
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=rel)
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for scope in scopes:
            translated = {t.id for n in ast.walk(scope)
                          if isinstance(n, ast.Assign) and _contains_translate(n.value)
                          for t in n.targets if isinstance(t, ast.Name)}
            for node in ast.walk(scope):
                if not (isinstance(node, ast.Call) and _is_english_sink(node.func)):
                    continue
                for arg in list(node.args) + [k.value for k in node.keywords]:
                    if _contains_translate(arg) or any(
                            isinstance(n, ast.Name) and n.id in translated
                            for n in ast.walk(arg)):
                        offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, ("user_warnings entries and log messages stay "
                           "English: " + ", ".join(sorted(set(offenders))))


def test_english_sink_rule_catches_direct_and_indirect_translate():
    """The rule above is only as good as its matcher: prove it fires."""
    src = (
        "def f(e):\n"
        "    user_warnings.warn(QCoreApplication.translate('X', 'a {0}').format(e))\n"
        "def g():\n"
        "    msg = QCoreApplication.translate('X', 'b')\n"
        "    logger.warning(msg)\n"
        "def h():\n"
        "    with user_warnings.operation(QCoreApplication.translate('X', 'c')):\n"
        "        pass\n"
        "def ok(e):\n"
        "    user_warnings.warn(f'fine {e}')\n"
    )
    hits = [node.lineno for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call) and _is_english_sink(node.func)
            and any(_contains_translate(a) or (isinstance(a, ast.Name) and a.id == "msg")
                    for a in node.args)]
    assert hits == [2, 5, 7]


# -- runtime: German installed ------------------------------------------------

@pytest.fixture
def german(qapp):
    """Install a translator served straight from the .ts."""
    from PyQt6.QtCore import QTranslator

    entries = {key: text for key, (text, kind) in _catalog().items()
               if text and kind not in ("vanished", "obsolete", "unfinished")}

    class TsTranslator(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):
            return entries.get((context, source))

        def isEmpty(self):  # noqa: N802 (Qt API)
            return False

    translator = TsTranslator(qapp)
    qapp.installTranslator(translator)
    try:
        yield
    finally:
        qapp.removeTranslator(translator)


def test_translator_fixture_serves_german(german):
    from PyQt6.QtCore import QCoreApplication
    assert QCoreApplication.translate("Shell", "Stage") == "Bühne"
    assert QCoreApplication.translate("UndoCommands", "Add Block") == "Block hinzufügen"


def test_autogen_key_survives_german_labels(german):
    """The key combo used to compare its displayed text with AUTO_KEY;
    it now carries item data, so a German label cannot leak a key."""
    from gui.dialogs.autogen_dialog import AUTO_KEY, AutogenDialog
    dlg = AutogenDialog(None)
    try:
        assert dlg.key_combo.itemText(0) != AUTO_KEY  # translated label
        dlg.key_combo.setCurrentIndex(0)
        dlg._on_accepted()
        assert dlg.result_key_signature is None
        index = dlg.key_combo.findData("D major")
        assert index > 0
        dlg.key_combo.setCurrentIndex(index)
        dlg._on_accepted()
        assert dlg.result_key_signature == "D major"
    finally:
        dlg.deleteLater()


def test_structure_play_button_widens_for_german_instead_of_clipping(
        qapp, sample_configuration, german):
    from gui.tabs.structure_tab import StructureTab
    tab = StructureTab(sample_configuration)
    try:
        btn = tab.play_btn
        assert btn.text() == "Abspielen"
        metrics = btn.fontMetrics()
        widest = max(metrics.horizontalAdvance(t) for t in ("Abspielen", "Pause"))
        english = max(metrics.horizontalAdvance(t) for t in ("Play", "Pause"))
        assert btn.maximumWidth() == 70 + (widest - english)
    finally:
        tab.deleteLater()


def test_structure_play_button_keeps_its_english_width(qapp, sample_configuration):
    from gui.tabs.structure_tab import StructureTab
    tab = StructureTab(sample_configuration)
    try:
        assert tab.play_btn.maximumWidth() == 70
        assert tab.stop_btn.maximumWidth() == 70
    finally:
        tab.deleteLater()


def test_no_translate_runs_at_import_time():
    """A translate() in a module or class body runs before main.py
    installs the translator, so it would freeze the English text."""
    offenders = []

    def visit(node, in_function, rel):
        for child in ast.iter_child_nodes(node):
            inside = in_function or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            if (not inside and isinstance(child, ast.Call)
                    and _is_qt_translate(child.func)):
                offenders.append(f"{rel}:{child.lineno}")
            visit(child, inside, rel)

    for path in _ui_files():
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding="utf-8") as fh:
            visit(ast.parse(fh.read(), filename=rel), False, rel)
    assert not offenders, "use QT_TRANSLATE_NOOP: " + ", ".join(offenders)


@pytest.mark.parametrize("count, expected", [
    (1, "Auf Universum 2 ist noch 1 Fixture gepatcht."),
    (2, "Auf Universum 2 sind noch 2 Fixtures gepatcht."),
])
def test_remove_universe_confirmation_agrees_with_the_count_in_german(
        qapp, german, monkeypatch, count, expected):
    """Whole singular and plural templates, not a translated noun in a
    shared one: German changes the verb with the count (ist / sind)."""
    from PyQt6 import QtWidgets
    from gui.tabs.configuration_tab import ConfigurationTab
    asked = {}

    def no(parent, title, text, *a, **k):
        asked["text"] = text
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", staticmethod(no))
    assert ConfigurationTab._confirm_remove_with_fixtures(None, 2, count) is False
    assert asked["text"].startswith(expected)
    assert "{" not in asked["text"]
