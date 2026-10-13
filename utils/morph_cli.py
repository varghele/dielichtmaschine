# utils/morph_cli.py
"""Headless morph: `python main.py morph <source.lms> --plan <p> ...`.

The venue-day batch path from the design doc (section 2): compile a
setlist against a target rig without a window. Like export_cli, this
must stay importable and runnable BEFORE any PyQt import - main.py
dispatches to it above the Qt imports.

    python main.py morph gig.lms --plan venue_a.morphplan.yaml \
        --target venue_a.lms --out venue_a_gig.lms [--report r.md]
        [--force]

Exit codes: 0 = morphed and written; 1 = bad input; 2 = the plan
failed validation or the compile reported errors (the report says
why); 3 = hand-edited blocks would be destroyed (re-run with --force
after reading the manifest on stderr).
"""

import argparse
import sys


def run_morph_cli(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="lichtmaschine morph",
        description="Compile a setlist onto a target rig (show morphing).")
    parser.add_argument("source", help="Source project (.lms/.yaml)")
    parser.add_argument("--plan", required=True,
                        help="Patch plan (*.morphplan.yaml)")
    parser.add_argument("--target", required=True,
                        help="Target rig project (.lms/.yaml)")
    parser.add_argument("--out", required=True,
                        help="Where to write the morphed project")
    parser.add_argument("--report", default=None,
                        help="Also write the morph report as markdown")
    parser.add_argument("--force", action="store_true",
                        help="Destroy hand-edited blocks on re-morph")
    args = parser.parse_args(argv)

    from config.models import Configuration
    from utils.morph.compile import apply_morph, compile_setlist
    from utils.morph.plan import MorphPlan, PlanError

    def _load(path, what):
        try:
            return Configuration.load(path)
        except Exception as exc:
            print(f"error: could not load {what} {path}: {exc}",
                  file=sys.stderr)
            return None

    source = _load(args.source, "source")
    target = _load(args.target, "target")
    if source is None or target is None:
        return 1
    try:
        plan = MorphPlan.load(args.plan)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    from _version import __version__
    result = compile_setlist(source, plan, target,
                             stamp={"app_version": __version__})
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(result.report.to_markdown(
                title=f"Morph report: {args.source} -> {args.target}"))
    for entry in result.report.entries:
        stream = sys.stderr if entry.kind in ("error", "destroyed") \
            else sys.stdout
        print(entry.format(), file=stream)
    if result.report.has_errors:
        print("error: the plan did not compile cleanly; nothing written",
              file=sys.stderr)
        return 2

    try:
        apply_morph(result, target, plan, force=args.force)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("re-run with --force to accept the destruction manifest",
              file=sys.stderr)
        return 3

    target.save(args.out)
    print(f"Morphed {len(result.songs)} song(s) into {args.out}")
    return 0
