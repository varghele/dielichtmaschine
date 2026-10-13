# tests/unit/test_changelog_release_notes.py
"""Tests for the CHANGELOG -> release-notes extractor used by the release workflow."""

import os

from scripts.changelog_release_notes import extract

_SAMPLE = """\
# Changelog

## [Unreleased]

_Nothing yet._

## [1.2.0] - 2026-08-01

Summary line.

### Added

- A new thing.
- Another thing.

### Fixed

- A bug.

## [1.1.0] - 2026-07-01

### Added

- Older thing.

[Unreleased]: https://example.com/compare/v1.2.0...HEAD
[1.2.0]: https://example.com/releases/tag/v1.2.0
"""


class TestExtract:

    def test_extracts_section_body_without_header(self):
        out = extract(_SAMPLE, "1.2.0")
        assert out.startswith("Summary line.")
        assert "- A new thing." in out
        assert "- A bug." in out

    def test_stops_before_next_version(self):
        out = extract(_SAMPLE, "1.2.0")
        assert "Older thing" not in out
        assert "## [1.1.0]" not in out

    def test_stops_before_link_definitions(self):
        # The final section must not swallow the trailing [x]: link refs.
        out = extract(_SAMPLE, "1.1.0")
        assert "Older thing" in out
        assert "https://example.com" not in out

    def test_strips_leading_v(self):
        assert extract(_SAMPLE, "v1.2.0") == extract(_SAMPLE, "1.2.0")

    def test_missing_version_returns_empty(self):
        assert extract(_SAMPLE, "9.9.9") == ""

    def test_unreleased_section(self):
        assert extract(_SAMPLE, "Unreleased").strip() == "_Nothing yet._"


def test_real_changelog_has_current_version():
    """The repo CHANGELOG must contain the section for the current _version."""
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    version = open(os.path.join(root, "_version.py")).read().split('"')[1]
    text = open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8").read()
    notes = extract(text, version)
    assert notes, f"CHANGELOG.md has no section for current version {version}"


def test_dev_version_reads_the_unreleased_section():
    """A milestone branch carries "X.Y.Z-dev" between releases
    (2026-07-20): its notes ARE the [Unreleased] section, so the
    current-version invariant holds mid-cycle and the release ritual
    only drops the suffix."""
    text = ("# Changelog\n\n## [Unreleased]\n\n- next thing\n\n"
            "## [1.4.0] - 2026-07-15\n\n- shipped thing\n")
    assert extract(text, "1.5.0-dev") == "- next thing"
    assert extract(text, "v1.5.0-dev") == "- next thing"
    assert extract(text, "1.4.0") == "- shipped thing"
