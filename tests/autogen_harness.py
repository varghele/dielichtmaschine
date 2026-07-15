"""CLI test harness for autogen pipeline — no PyQt dependency.

Loads a config + audio file, runs the full generation pipeline, and prints
diagnostic tables for rapid iteration on metrics and activation logic.

Usage:
    python -m tests.autogen_harness test_conf.yaml SBD_cycle_of_a_pscho \
        --audio shows/audiofiles/light_track_cycle_of_a_psycho.mp3 \
        --compare
"""

import argparse
import sys
import os
import statistics
from typing import List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.models import Configuration, LightLane
from timeline.song_structure import SongStructure
from audio.spectral_analysis import SongAnalysis, analyze_song
from autogen.generator import generate_show
from autogen.report import GenerationReport


def print_metrics_table(analysis: SongAnalysis, report: GenerationReport):
    """Print per-section audio metrics."""
    print("\n" + "=" * 100)
    print("SECTION METRICS")
    print("=" * 100)
    header = f"{'Section':<16} {'Start':>6} {'End':>6} {'Flux':>6} {'Trans':>6} {'Rich':>6} {'Vocal':>6} {'Cent':>6} {'RMS':>6} {'Contr':>6} {'Energy':>7}"
    print(header)
    print("-" * len(header))

    for sa in analysis.sections:
        # Find matching report section for relative_energy
        rs = None
        for r in report.sections:
            if r.name == sa.name:
                rs = r
                break
        energy = rs.relative_energy if rs else 0.0

        print(
            f"{sa.name:<16} "
            f"{sa.start_time:>6.1f} "
            f"{sa.end_time:>6.1f} "
            f"{sa.spectral_flux_avg:>6.3f} "
            f"{sa.transient_sharpness:>6.3f} "
            f"{sa.spectral_richness:>6.3f} "
            f"{sa.vocal_presence:>6.3f} "
            f"{sa.spectral_centroid_avg:>6.0f} "
            f"{sa.rms_energy:>6.3f} "
            f"{sa.spectral_contrast_avg:>6.3f} "
            f"{energy:>7.3f}"
        )


def print_differentiation_stats(analysis: SongAnalysis, report: GenerationReport):
    """Print range/stddev per metric to expose compression."""
    print("\n" + "=" * 80)
    print("METRIC DIFFERENTIATION (excluding klickintro if present)")
    print("=" * 80)

    # Filter out klickintro (it's a count-in, not music)
    sections = [s for s in analysis.sections if "klick" not in s.name.lower()]
    report_sections = [r for r in report.sections if "klick" not in r.name.lower()]

    if not sections:
        print("No sections to analyze")
        return

    metrics = {
        "flux": [s.spectral_flux_avg for s in sections],
        "transient": [s.transient_sharpness for s in sections],
        "richness": [s.spectral_richness for s in sections],
        "vocal": [s.vocal_presence for s in sections],
        "centroid": [s.spectral_centroid_avg for s in sections],
        "rms": [s.rms_energy for s in sections],
        "contrast": [s.spectral_contrast_avg for s in sections],
        "energy": [r.relative_energy for r in report_sections],
    }

    header = f"{'Metric':<12} {'Min':>8} {'Max':>8} {'Range':>8} {'StdDev':>8} {'Verdict'}"
    print(header)
    print("-" * len(header))

    for name, values in metrics.items():
        mn, mx = min(values), max(values)
        rng = mx - mn
        sd = statistics.stdev(values) if len(values) > 1 else 0.0

        # Verdict based on normalized range
        if name == "centroid":
            # Centroid is in Hz, judge differently
            norm_range = rng / max(mx, 1)
        else:
            norm_range = rng

        if norm_range < 0.05:
            verdict = "!! USELESS"
        elif norm_range < 0.15:
            verdict = "!  WEAK"
        elif norm_range < 0.3:
            verdict = "   OK"
        else:
            verdict = "   GOOD"

        print(f"{name:<12} {mn:>8.3f} {mx:>8.3f} {rng:>8.3f} {sd:>8.3f} {verdict}")


def print_activation_table(report: GenerationReport):
    """Print per-group activation decisions per section."""
    print("\n" + "=" * 120)
    print("GROUP ACTIVATION PER SECTION")
    print("=" * 120)

    if not report.sections or not report.group_names:
        print("No data")
        return

    for sec in report.sections:
        print(f"\n--- {sec.name} (energy={sec.relative_energy:.2f}) ---")
        header = f"  {'Group':<14} {'LitRole':<10} {'Weight':>6} {'VocalW':>6} {'ActRole':<8} {'Groove':<16} {'Fill':<16} {'Cat':<12} {'Speed':<5}"
        print(header)

        for gname in report.group_names:
            gr = sec.group_reports.get(gname)
            if not gr:
                print(f"  {gname:<14} {'':>10} {'N/A':>6}")
                continue

            status = "" if gr.weight > 0 else " [OFF]"
            print(
                f"  {gname:<14} "
                f"{gr.lighting_role or '(none)':<10} "
                f"{gr.weight:>6.2f} "
                f"{gr.vocal_weight:>6.2f} "
                f"{gr.role:<8} "
                f"{gr.groove_rudiment:<16} "
                f"{gr.fill_rudiment:<16} "
                f"{gr.groove_category:<12} "
                f"{gr.effect_speed:<5}"
                f"{status}"
            )


def print_handmade_comparison(
    auto_lanes: List[LightLane],
    handmade_lanes: List[LightLane],
    song_structure: SongStructure,
):
    """Compare block density between auto-generated and hand-made shows."""
    print("\n" + "=" * 100)
    print("HAND-MADE vs AUTO-GENERATED COMPARISON")
    print("=" * 100)

    # Build coverage maps: for each section × group, count blocks and coverage %
    def compute_coverage(lanes: List[LightLane], parts):
        """Returns {(section_name, group_target): (block_count, coverage_pct)}"""
        result = {}
        for lane in lanes:
            # Extract group name from lane name and targets
            targets = lane.fixture_targets if hasattr(lane, 'fixture_targets') else []
            group = targets[0] if targets else lane.name

            for part in parts:
                sec_start = part.start_time
                sec_end = part.start_time + part.duration
                sec_dur = part.duration
                if sec_dur <= 0:
                    continue

                # Count blocks overlapping this section
                block_count = 0
                covered_time = 0.0
                for block in lane.light_blocks:
                    b_start = max(block.start_time, sec_start)
                    b_end = min(block.end_time, sec_end)
                    if b_end > b_start:
                        block_count += 1
                        covered_time += b_end - b_start

                coverage_pct = (covered_time / sec_dur) * 100
                result[(part.name, group)] = (block_count, coverage_pct)

        return result

    auto_cov = compute_coverage(auto_lanes, song_structure.parts)
    hand_cov = compute_coverage(handmade_lanes, song_structure.parts)

    # Collect all groups from both
    auto_groups = set()
    hand_groups = set()
    for lane in auto_lanes:
        targets = lane.fixture_targets if hasattr(lane, 'fixture_targets') else []
        auto_groups.add(targets[0] if targets else lane.name)
    for lane in handmade_lanes:
        targets = lane.fixture_targets if hasattr(lane, 'fixture_targets') else []
        hand_groups.add(targets[0] if targets else lane.name)

    all_groups = sorted(auto_groups | hand_groups)

    header = f"{'Section':<16} {'Group':<14} {'Hand#':>5} {'Hand%':>6} {'Auto#':>5} {'Auto%':>6} {'Delta':>6}"
    print(header)
    print("-" * len(header))

    for part in song_structure.parts:
        for group in all_groups:
            h_count, h_pct = hand_cov.get((part.name, group), (0, 0.0))
            a_count, a_pct = auto_cov.get((part.name, group), (0, 0.0))
            delta = a_pct - h_pct
            marker = " <<" if abs(delta) > 30 else ""
            print(
                f"{part.name:<16} {group:<14} "
                f"{h_count:>5} {h_pct:>5.0f}% "
                f"{a_count:>5} {a_pct:>5.0f}% "
                f"{delta:>+5.0f}%{marker}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Autogen test harness — run generation pipeline from CLI"
    )
    parser.add_argument("config", help="Path to config YAML file")
    parser.add_argument("show", help="Show name within the config")
    parser.add_argument("--audio", help="Path to audio file (overrides config)")
    parser.add_argument("--compare", action="store_true",
                        help="Compare against hand-made lanes in config")
    parser.add_argument("--sections-only", action="store_true",
                        help="Only print metrics, skip generation")
    parser.add_argument("--roles", nargs="*", metavar="GROUP=ROLE",
                        help="Assign lighting roles, e.g. BARS=backbone MH=movement")
    args = parser.parse_args()

    # Load config
    print(f"Loading config: {args.config}")
    config = Configuration.load(args.config)

    # Find show
    if args.show not in config.songs:
        print(f"ERROR: Show '{args.show}' not found. Available shows:")
        for name in config.songs:
            print(f"  - {name}")
        sys.exit(1)

    show = config.songs[args.show]
    print(f"Show: {args.show} ({len(show.parts)} parts)")

    # Apply role overrides from CLI
    if args.roles:
        role_map = {}
        for spec in args.roles:
            if "=" not in spec:
                print(f"WARNING: Invalid role spec '{spec}', expected GROUP=ROLE")
                continue
            group_pattern, role = spec.split("=", 1)
            role_map[group_pattern.upper()] = role

        for name, group in config.groups.items():
            # Match by exact name or by prefix (e.g. "BARS" matches "BARS - Dimmer")
            for pattern, role in role_map.items():
                if name.upper() == pattern or name.upper().startswith(pattern):
                    group.lighting_role = role
                    break

    # Print fixture group roles
    print("\nFixture Groups:")
    for name, group in config.groups.items():
        role = group.lighting_role or "(none)"
        n_fix = len(group.fixtures)
        print(f"  {name:<14} role={role:<12} fixtures={n_fix}")

    # Build song structure
    song_structure = SongStructure()
    song_structure.load_from_show_parts(show.parts)

    # Resolve audio path
    audio_path = args.audio
    if not audio_path:
        # Try to find audio from show or common locations
        candidates = [
            f"shows/audiofiles/{args.show.lower()}.mp3",
            f"light_track_{args.show.lower()}.mp3",
        ]
        for c in candidates:
            if os.path.exists(c):
                audio_path = c
                break

    if not audio_path or not os.path.exists(audio_path):
        print(f"ERROR: Audio file not found. Use --audio <path>")
        if audio_path:
            print(f"  Tried: {audio_path}")
        sys.exit(1)

    print(f"Audio: {audio_path}")

    # Step 1: Analyze audio
    print("\nAnalyzing audio...")
    analysis = analyze_song(audio_path, song_structure)

    if args.sections_only:
        # Just print metrics without full generation
        # Create a minimal report with relative_energy computed inline
        from autogen.report import GenerationReport, SectionReport
        report = GenerationReport()
        all_rms = sorted(s.rms_energy for s in analysis.sections)
        for sa in analysis.sections:
            if len(all_rms) > 1:
                rank = all_rms.index(sa.rms_energy) if sa.rms_energy in all_rms else 0
                rms_rank = rank / (len(all_rms) - 1)
            else:
                rms_rank = 0.5
            rel_e = 0.6 * rms_rank + 0.4 * sa.spectral_contrast_avg
            rel_e = max(0.0, min(1.0, rel_e))
            report.sections.append(SectionReport(
                name=sa.name, start_time=sa.start_time, end_time=sa.end_time,
                spectral_flux=sa.spectral_flux_avg, transient_sharpness=sa.transient_sharpness,
                spectral_richness=sa.spectral_richness, vocal_presence=sa.vocal_presence,
                spectral_centroid=sa.spectral_centroid_avg,
                rms_energy=sa.rms_energy, spectral_contrast=sa.spectral_contrast_avg,
                relative_energy=rel_e,
            ))
        print_metrics_table(analysis, report)
        print_differentiation_stats(analysis, report)
        return

    # Step 2: Generate show
    print("Generating show...")
    auto_lanes, report = generate_show(audio_path, song_structure, config)
    print(f"Generated {len(auto_lanes)} lanes")

    # Print all tables
    print_metrics_table(analysis, report)
    print_differentiation_stats(analysis, report)
    print_activation_table(report)

    # Optional: compare against hand-made
    if args.compare:
        handmade_lanes = show.lanes if hasattr(show, 'lanes') and show.lanes else []
        if not handmade_lanes:
            # Try to get lanes from show's timeline data
            handmade_lanes = getattr(show, 'light_lanes', [])
        if handmade_lanes:
            print_handmade_comparison(auto_lanes, handmade_lanes, song_structure)
        else:
            print("\nNo hand-made lanes found in config for comparison.")

    print("\nDone.")


if __name__ == "__main__":
    main()
