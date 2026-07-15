# Releasing

Releases are cut from a git tag. The GitHub Actions workflow
([`.github/workflows/release.yml`](../.github/workflows/release.yml)) builds the
binaries and drafts the GitHub Release; the release notes come straight from
[`CHANGELOG.md`](../CHANGELOG.md), so there is one place to keep current.

## Day to day

As you land changes, add a bullet under the **`## [Unreleased]`** heading in
`CHANGELOG.md`, grouped under `Added` / `Changed` / `Fixed` / `Removed`. Keep it
short and user-facing (what changed for someone using the app), not a commit log.

## Cutting a release

1. **Pick the version** (`MAJOR.MINOR.PATCH`, [SemVer](https://semver.org)).
2. **Update the changelog:** rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`,
   add a fresh empty `## [Unreleased]` above it, and add a link line at the
   bottom (`[X.Y.Z]: https://github.com/varghele/dielichtmaschine/releases/tag/vX.Y.Z`).
3. **Bump `_version.py`** to `"X.Y.Z"`.
4. **Commit** those together, e.g. `chore(release): vX.Y.Z`.
5. *(Optional, first time / risky changes)* dry-run the build: GitHub -> **Actions**
   -> "Release Build" -> **Run workflow**. This builds artifacts but creates no
   release.
6. **Tag and push:**
   ```sh
   git push
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
7. The workflow builds Windows + Linux, then drafts a GitHub Release whose notes
   are the `## [X.Y.Z]` changelog section (via
   [`scripts/changelog_release_notes.py`](../scripts/changelog_release_notes.py)).
8. **Publish:** GitHub -> **Releases** -> open the `vX.Y.Z` draft -> review -> **Publish**.

## Notes

- The release body is the changelog section verbatim - edit the changelog, not
  the draft, so the two never drift.
- Changelog version headings are **without** the `v` (`## [1.0.0]`); tags have it
  (`v1.0.0`). The extractor strips the `v` when matching.
- If a tag has no matching changelog section, the notes fall back to a link to
  `CHANGELOG.md` (the build still succeeds).
