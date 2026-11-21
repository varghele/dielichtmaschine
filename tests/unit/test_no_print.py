# tests/unit/test_no_print.py
"""Production code logs through ``logging``, never ``print``.

The app is windowed (the packaged exe has no console), so a print()
goes nowhere; module loggers reach the log file set up by
utils/app_logging.setup_logging(). stdout stays the interface only
where it IS the interface: the headless CLIs main.py dispatches before
any Qt import, and ``if __name__ == "__main__":`` blocks.
"""

import ast
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

# Every production package plus the top-level entry modules. tests/,
# scripts/, demos/ and profiling/ are developer tooling and may print.
PRODUCTION_PACKAGES = (
    "audio", "auto", "autogen", "config", "effects", "gui", "riffs",
    "rudiments", "scenes", "timeline", "timeline_ui", "utils",
    "visualizer",
)
PRODUCTION_MODULES = ("main.py", "_version.py")

# Files whose stdout/stderr is the user interface.
PRINT_ALLOWLIST = {
    "main.py",               # --version, the --profile console report
    "utils/export_cli.py",   # `main.py export` (headless)
    "utils/morph_cli.py",    # `main.py morph` (headless)
}


def _production_files():
    for module in PRODUCTION_MODULES:
        yield module
    for package in PRODUCTION_PACKAGES:
        base = os.path.join(REPO_ROOT, package)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith(".py"):
                    full = os.path.join(dirpath, name)
                    yield os.path.relpath(full, REPO_ROOT).replace(os.sep, "/")


def _parse(rel_path):
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=rel_path)


def _is_main_guard(node):
    test = getattr(node, "test", None)
    return (isinstance(node, ast.If) and isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__")


def _print_calls(tree):
    """Line numbers of print() calls outside ``__main__`` guards."""
    found = []

    def visit(node, in_main):
        if _is_main_guard(node):
            in_main = True
        if (not in_main and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "print"):
            found.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, in_main)

    visit(tree, False)
    return found


def test_production_tree_is_found():
    files = list(_production_files())
    assert len(files) > 150
    for package in PRODUCTION_PACKAGES:
        assert os.path.isdir(os.path.join(REPO_ROOT, package)), package


def test_allowlisted_files_exist():
    for rel_path in PRINT_ALLOWLIST:
        assert os.path.isfile(os.path.join(REPO_ROOT, rel_path)), rel_path


def test_no_print_in_production_code():
    offenders = []
    for rel_path in _production_files():
        if rel_path in PRINT_ALLOWLIST:
            continue
        for line in _print_calls(_parse(rel_path)):
            offenders.append(f"{rel_path}:{line}")
    assert not offenders, (
        "print() in production code; use a module logger "
        "(logging.getLogger(__name__)) instead:\n" + "\n".join(offenders))


@pytest.mark.parametrize("source, expected", [
    ("print('x')\n", [1]),
    ("if __name__ == '__main__':\n    print('x')\n", []),
    ("def f():\n    print('x')\nif __name__ == '__main__':\n    f()\n", [2]),
    ("logger.info('print(x)')\n", []),
])
def test_print_detector(source, expected):
    assert _print_calls(ast.parse(source)) == expected
