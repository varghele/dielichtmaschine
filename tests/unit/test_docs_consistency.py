# tests/unit/test_docs_consistency.py
"""Cross-checks between the working docs (ROADMAP.md, CLAUDE.md) and the
facts they quote from elsewhere in the repo (v1.5.5 G11).

The docs are read by people and by future sessions to decide what to do
next, so a quoted release date or a stated requirement that drifted from
the source of truth costs real time. Only claims that are checkable
against a file in the repo are pinned here.
"""

import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
WORKING_DOCS = ["ROADMAP.md", "CLAUDE.md"]

_HEADING = re.compile(r"^## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})", re.M)
# A quoted section heading, e.g. `[1.5.0] - 2026-08-09` inside prose.
_QUOTED = re.compile(r"\[(\d+\.\d+\.\d+[^\]]*)\] - (\d{4}-\d{2}-\d{2})")


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_quoted_changelog_dates_match_the_changelog():
    """A doc quoting a CHANGELOG section heading must quote its date.
    ROADMAP's release ritual said `[1.5.0] - 2026-08-08` while the
    CHANGELOG had been re-dated to 2026-08-09 when the desktop-check
    work was folded in. Versions the CHANGELOG no longer carries as a
    section (the folded 1.5.0-alpha) are history and not checked."""
    released = dict(_HEADING.findall(_read("CHANGELOG.md")))
    assert released, "CHANGELOG.md has no dated version sections"
    mismatches = []
    for doc in WORKING_DOCS:
        for version, date in _QUOTED.findall(_read(doc)):
            if version in released and released[version] != date:
                mismatches.append(
                    f"{doc}: [{version}] - {date}, CHANGELOG says "
                    f"{released[version]}")
    assert not mismatches, "\n".join(mismatches)


def test_docs_do_not_require_seeding_the_global_rng_for_export():
    """Since v1.5.5 G3 the export draws only from local random.Random
    instances (tests/unit/test_rng_determinism.py) and
    scripts/export_hash_check.py needs PYTHONHASHSEED=0 only. The working
    docs used to say the hash check also needs a seeded global RNG."""
    stale = re.compile(
        r"seeded\s+RNG|pinned\s+RNG\s+seed|samples\s+the\s+global\s+RNG",
        re.I)
    hits = [f"{doc}: {m.group(0)!r}"
            for doc in WORKING_DOCS
            for m in stale.finditer(_read(doc))]
    assert not hits, "\n".join(hits)
