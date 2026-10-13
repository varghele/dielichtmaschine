#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a given version - used as GitHub Release notes.

The release workflow calls this with the tag's version so the published notes are
exactly the curated CHANGELOG entry, keeping the changelog and the release notes
in sync from a single source.

Usage:
    python scripts/changelog_release_notes.py 1.0.0
    python scripts/changelog_release_notes.py v1.0.0          # leading v ok
    python scripts/changelog_release_notes.py 1.0.0 --changelog path/to/CHANGELOG.md

Exit code 1 (with a message on stderr) if the version's section isn't found, so
the workflow can fall back rather than publish empty notes.
"""
import argparse
import os
import re
import sys

# A markdown link-reference definition, e.g. "[1.0.0]: https://...".
_LINK_DEF = re.compile(r"^\[[^\]]+\]:\s")


def extract(changelog_text: str, version: str) -> str:
    version = version.lstrip("vV")
    # A dev version (e.g. "1.5.0-dev", the in-between-releases marker
    # on a milestone branch) has no released section yet - its notes
    # ARE the [Unreleased] section. The release ritual drops the -dev
    # suffix, at which point the renamed section matches as usual.
    if version.endswith("-dev"):
        header = "## [Unreleased]"
    else:
        header = f"## [{version}]"
    lines = changelog_text.splitlines()

    start = next((i for i, ln in enumerate(lines) if ln.startswith(header)), None)
    if start is None:
        return ""

    body = []
    for ln in lines[start + 1:]:
        if ln.startswith("## ") or _LINK_DEF.match(ln):
            break
        body.append(ln)

    return "\n".join(body).strip("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract a CHANGELOG section as release notes.")
    parser.add_argument("version", help="Version to extract (e.g. 1.0.0 or v1.0.0).")
    parser.add_argument("--changelog", default=None, help="Path to CHANGELOG.md (default: repo root).")
    args = parser.parse_args(argv)

    path = args.changelog or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CHANGELOG.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"error: cannot read {path}: {e}", file=sys.stderr)
        return 1

    notes = extract(text, args.version)
    if not notes:
        print(f"error: no changelog section for version '{args.version}' in {path}", file=sys.stderr)
        return 1

    # Force UTF-8 out in case a changelog entry contains non-ASCII that a
    # Windows console's default cp1252 can't encode. CI (Linux) is UTF-8 already.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
