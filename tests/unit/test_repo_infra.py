"""Repository infrastructure contracts: the dependency manifests, the
pytest configuration and the CI workflows agree with each other.

Pins the v1.5.5 G1 findings (2026-10-06):

* ``environment.yml`` did not solve on conda-forge. It asked for
  ``pyqt>=6.5`` (conda-forge's ``pyqt`` is the Qt5 binding; PyQt6 comes
  from pip, as in requirements.txt and CI) and for ``sounddevice`` /
  ``soundfile``, which conda-forge ships as ``python-sounddevice`` /
  ``pysoundfile``. Without ``nodefaults`` an install that lists the
  Anaconda ``defaults`` channels also merged them into the solve.
* requirements.txt and environment.yml drifted apart silently; every
  package and version floor must now appear in both.
* A test that hangs (a modal dialog nobody closes) sat silently for the
  whole CI job timeout; pytest-timeout gives each test a default budget.
* The release workflow built and drafted a release without running the
  suite.
* tests/README.md did not mention the ``e2e/`` tier.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

# requirements.txt name -> conda-forge name, where the two differ.
CONDA_FORGE_NAMES = {
    "sounddevice": "python-sounddevice",
    "soundfile": "pysoundfile",
}

# Packages that must come from pip inside environment.yml: PyQt6 because
# conda-forge's build lags the pip wheel the suite and CI run against,
# pygdtf because conda-forge does not carry it.
PIP_ONLY = {"pyqt6", "pygdtf"}

# Packages environment.yml lists that are not Python requirements.
CONDA_INFRA = {"python", "pip"}

_SPEC = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(?:>=\s*([0-9][0-9.]*))?\s*$")


def _parse_spec(spec):
    match = _SPEC.match(spec)
    assert match, f"unparseable dependency spec: {spec!r}"
    name, floor = match.group(1), match.group(2)
    return name.lower(), floor


def _norm_version(floor):
    """'6.5.0' and '6.5' are the same floor."""
    if floor is None:
        return None
    parts = [int(p) for p in floor.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _requirements():
    reqs = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, floor = _parse_spec(line)
        reqs[name] = floor
    return reqs


def _environment():
    return yaml.safe_load((ROOT / "environment.yml").read_text(encoding="utf-8"))


def _environment_deps():
    """(conda deps, pip deps) as {lower name: floor}."""
    conda, pip = {}, {}
    for dep in _environment()["dependencies"]:
        if isinstance(dep, dict):
            for spec in dep.get("pip", []):
                name, floor = _parse_spec(spec)
                pip[name] = floor
        else:
            name, floor = _parse_spec(dep)
            conda[name] = floor
    return conda, pip


def _workflow(name):
    data = yaml.safe_load(
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on:` as boolean True (YAML 1.1).
    if "on" not in data and True in data:
        data["on"] = data.pop(True)
    return data


class TestEnvironmentYml:
    def test_only_conda_forge_without_defaults(self):
        """`nodefaults` keeps the Anaconda channels out of the solve on
        installs that list them (Miniconda, Anaconda)."""
        channels = _environment()["channels"]
        assert "conda-forge" in channels
        assert "nodefaults" in channels
        assert "defaults" not in channels

    @pytest.mark.parametrize("pypi_name,conda_name", sorted(CONDA_FORGE_NAMES.items()))
    def test_renamed_packages_use_conda_forge_names(self, pypi_name, conda_name):
        conda, _ = _environment_deps()
        assert pypi_name not in conda, (
            f"conda-forge has no '{pypi_name}' package; use '{conda_name}'")
        assert conda_name in conda

    def test_pip_only_packages_are_in_the_pip_block(self):
        conda, pip = _environment_deps()
        for name in PIP_ONLY:
            assert name in pip, f"{name} must be installed by pip"
        # conda-forge's `pyqt` is the Qt5 binding: never ask for it.
        assert "pyqt" not in conda
        assert "pyqt6" not in conda


class TestManifestsAgree:
    def _env_as_pypi(self):
        conda, pip = _environment_deps()
        back = {v: k for k, v in CONDA_FORGE_NAMES.items()}
        merged = {}
        for name, floor in conda.items():
            if name in CONDA_INFRA:
                continue
            merged[back.get(name, name)] = floor
        merged.update(pip)
        return merged

    def test_same_package_set(self):
        reqs = set(_requirements())
        env = set(self._env_as_pypi())
        assert reqs - env == set(), "in requirements.txt only"
        assert env - reqs == set(), "in environment.yml only"

    def test_same_version_floors(self):
        reqs = _requirements()
        env = self._env_as_pypi()
        mismatched = {
            name: (reqs[name], env[name]) for name in reqs.keys() & env.keys()
            if _norm_version(reqs[name]) != _norm_version(env[name])
        }
        assert mismatched == {}

    def test_test_plugins_listed(self):
        reqs = _requirements()
        for plugin in ("pytest", "pytest-xdist", "pytest-timeout"):
            assert plugin in reqs


class TestPytestTimeout:
    def test_default_timeout_configured(self, pytestconfig):
        assert pytestconfig.pluginmanager.hasplugin("timeout"), (
            "pytest-timeout is not installed")
        timeout = float(pytestconfig.getini("timeout") or 0)
        # A budget, not a stopwatch: far above the slowest test (under
        # 1 s on Linux, 2026-10-06), low enough to beat the CI job limit.
        assert 30 <= timeout <= 600

    def test_thread_method(self, pytestconfig):
        """The signal method can only fire when Python bytecode runs; a
        hang inside a C++ Qt event loop (QDialog.exec) never returns to
        it. The thread method dumps every stack and ends the process."""
        assert pytestconfig.getini("timeout_method") == "thread"


class TestReleaseWorkflow:
    def test_tests_workflow_is_reusable(self):
        assert "workflow_call" in _workflow("tests.yml")["on"]

    def test_build_needs_the_test_suite(self):
        jobs = _workflow("release.yml")["jobs"]
        test_jobs = {
            name for name, job in jobs.items()
            if job.get("uses") == "./.github/workflows/tests.yml"
        }
        assert test_jobs, "release.yml never runs the test suite"
        needs = jobs["build"].get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert test_jobs & set(needs)

    def test_called_run_has_its_own_concurrency_group(self):
        """A tag push triggers tests.yml directly AND through release.yml.
        In a called workflow `github.workflow` is the caller's name, so
        keying the group on it stops the two runs cancelling each other
        (cancel-in-progress) and failing the release."""
        group = _workflow("tests.yml")["concurrency"]["group"]
        assert "github.workflow" in group


class TestTestsReadme:
    def test_every_test_tier_is_documented(self):
        readme = (ROOT / "tests" / "README.md").read_text(encoding="utf-8")
        tiers = sorted(
            entry.name for entry in (ROOT / "tests").iterdir()
            if entry.is_dir() and any(entry.glob("test_*.py"))
        )
        assert tiers, "no test tiers found"
        missing = [t for t in tiers if f"`{t}/`" not in readme]
        assert missing == []
