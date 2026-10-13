import xml.etree.ElementTree as ET
from config.models import Configuration
from utils import user_warnings


def add_steps_to_sequence(sequence, steps):
    """Adds steps to a sequence"""
    for step in steps:
        sequence.append(step)

def create_sequence(root, sequence_id, sequence_name, bound_scene_id, bpm=120):
    """
    Creates a Sequence function element
    Parameters:
        root: The root XML element to add the sequence to
        sequence_id: ID of the sequence
        sequence_name: Name of the sequence
        bound_scene_id: ID of the bound scene
        bpm: Beats per minute for timing
    Returns:
        Element: The created sequence element
    """
    sequence = ET.SubElement(root, "Function")
    sequence.set("ID", str(sequence_id))
    sequence.set("Type", "Sequence")
    sequence.set("Name", sequence_name)
    sequence.set("BoundScene", str(bound_scene_id))

    # Calculate default timing based on BPM
    ms_per_beat = 60000 / float(bpm)

    speed = ET.SubElement(sequence, "Speed")
    speed.set("FadeIn", str(int(ms_per_beat * 0.1)))  # 10% of beat time
    speed.set("FadeOut", "0")
    speed.set("Duration", str(int(ms_per_beat)))

    direction = ET.SubElement(sequence, "Direction")
    direction.text = "Forward"

    run_order = ET.SubElement(sequence, "RunOrder")
    run_order.text = "SingleShot"

    speed_modes = ET.SubElement(sequence, "SpeedModes")
    speed_modes.set("FadeIn", "PerStep")
    speed_modes.set("FadeOut", "PerStep")
    speed_modes.set("Duration", "PerStep")

    return sequence


def create_tracks_from_timeline(show_function, engine, show, config, fixture_id_map,
                                function_id_counter, fixture_definitions,
                                export_overrides: dict = None):
    """
    Creates Track elements from timeline_data (new timeline-based format).

    Parameters:
        show_function: The show Function element to add tracks to
        engine: The engine element for adding scenes
        show: Show object containing show data with timeline_data
        config: Configuration object
        fixture_id_map: Dictionary mapping fixture object IDs to their sequential IDs
        function_id_counter: Current function ID counter
        fixture_definitions: Dictionary of fixture definitions loaded from QLC+
        export_overrides: Optional dict with export-time overrides
    Returns:
        int: Next available function ID
    """
    if export_overrides is None:
        export_overrides = {}
    from timeline.song_structure import SongStructure
    from utils.target_resolver import resolve_targets_unique, validate_targets, detect_targets_capabilities

    # Debug: Show export info
    print(f"\n=== Exporting show: {show.name} ===")
    print(f"  Number of lanes: {len(show.timeline_data.lanes)}")
    print(f"  Available groups: {list(config.groups.keys())}")
    print(f"  fixture_id_map keys: {list(fixture_id_map.keys())[:10]}...")  # First 10

    # Build song structure for timing calculations
    song_structure = SongStructure()
    song_structure.load_from_show_parts(show.parts)

    track_id = 0
    fixture_start_id = 0

    for lane_idx, lane in enumerate(show.timeline_data.lanes):
        # Debug: Lane info
        print(f"\n  Lane {lane_idx}: '{lane.name}'")
        print(f"    fixture_targets attr: {getattr(lane, 'fixture_targets', 'NOT_FOUND')}")
        print(f"    light_blocks count: {len(lane.light_blocks)}")

        # Get fixture targets (with backward compatibility for old fixture_group field)
        targets = getattr(lane, 'fixture_targets', [])
        if not targets and hasattr(lane, 'fixture_group') and lane.fixture_group:
            targets = [lane.fixture_group]

        print(f"    Resolved targets: {targets}")

        if not targets:
            user_warnings.warn(
                f"Lane '{lane.name}' has no targets and was left out of "
                f"the export",
                category="export")
            continue

        # Validate and warn about invalid targets
        for warning in validate_targets(targets, config):
            user_warnings.warn(f"Lane '{lane.name}': {warning}",
                               category="export")

        # Resolve targets to unique fixtures
        resolved_fixtures = resolve_targets_unique(targets, config)
        print(f"    Resolved fixtures count: {len(resolved_fixtures)}")
        for f in resolved_fixtures:
            print(f"      - {f.name}: group='{f.group}', universe={f.universe}, address={f.address}")

        if not resolved_fixtures:
            user_warnings.warn(
                f"No valid fixtures for lane '{lane.name}'; the lane was "
                f"left out of the export",
                category="export")
            continue

        # Sort all fixtures in the lane by position (x coordinate) for cross-group effects
        # This ensures ping-pong, waterfall, etc. work correctly across fixture groups
        sorted_lane_fixtures = sorted(resolved_fixtures, key=lambda f: f.x)

        # Group fixtures by their fixture group for separate track processing
        # This handles multi-target lanes by creating one track per fixture group
        fixtures_by_group = {}
        for fixture in resolved_fixtures:
            group_name = fixture.group
            if group_name not in fixtures_by_group:
                fixtures_by_group[group_name] = []
            fixtures_by_group[group_name].append(fixture)

        print(f"    fixtures_by_group: {list(fixtures_by_group.keys())}")

        # Process each fixture group as a separate track
        for group_name, group_fixtures in fixtures_by_group.items():
            print(f"\n    Creating track for group: '{group_name}' with {len(group_fixtures)} fixtures")
            # Calculate number of fixtures in this group
            fixture_num = len(group_fixtures)

            # Create a display name for this track
            lane_display_name = group_name

            # Create Track
            track = ET.SubElement(show_function, "Track")
            track.set("ID", str(track_id))
            track.set("Name", lane_display_name.upper())
            track.set("SceneID", str(function_id_counter))
            track.set("isMute", "1" if lane.muted else "0")

            # Create Scene
            scene = ET.SubElement(engine, "Function")
            scene.set("ID", str(function_id_counter))
            scene.set("Type", "Scene")
            scene.set("Name", f"Scene for {show.name} - {lane_display_name}")
            scene.set("Hidden", "True")

            # Add Scene properties
            speed = ET.SubElement(scene, "Speed")
            speed.set("FadeIn", "0")
            speed.set("FadeOut", "0")
            speed.set("Duration", "0")

            # Add ChannelGroupsVal
            ET.SubElement(scene, "ChannelGroupsVal").text = f"{track_id},0"

            # Add FixtureVal for this group's fixtures only
            for fixture in group_fixtures:
                fixture_val = ET.SubElement(scene, "FixtureVal")
                fixture_val.set("ID", str(fixture_id_map[(fixture.universe, fixture.address)]))

                num_channels = next((mode.channels for mode in fixture.available_modes
                                    if mode.name == fixture.current_mode), 0)
                channel_values = ",".join([f"{i},0" for i in range(num_channels)])
                fixture_val.text = channel_values

            function_id_counter += 1

            # Get fixture definition from the first fixture in this group
            first_fixture = group_fixtures[0]
            fixture_key = f"{first_fixture.manufacturer}_{first_fixture.model}"
            fixture_def = fixture_definitions.get(fixture_key)

            # Check capabilities for this specific fixture group
            from utils.fixture_utils import detect_fixture_group_capabilities
            group_capabilities = detect_fixture_group_capabilities(group_fixtures, fixture_definitions)
            has_dimmer = group_capabilities.has_dimmer if group_capabilities else True
            has_colour = group_capabilities.has_colour if group_capabilities else False
            has_movement = group_capabilities.has_movement if group_capabilities else False

            # Build per-group export overrides with group-specific intensity scaling
            track_overrides = dict(export_overrides)
            group_intensity = export_overrides.get('group_intensities', {}).get(group_name, 255)
            track_overrides['group_max_intensity'] = group_intensity

            # Process light blocks using unified sequence approach
            # This creates ONE sequence per LightBlock with ALL effects combined
            from utils.to_xml.unified_sequence import generate_unified_sequence_steps

            print(f"    Processing {len(lane.light_blocks)} light blocks for group '{group_name}' (export intensity: {group_intensity})")

            for block_idx, block in enumerate(lane.light_blocks):
                # Check if this block has any sublane blocks
                has_any_blocks = (
                    block.dimmer_blocks or
                    block.colour_blocks or
                    block.movement_blocks or
                    block.special_blocks
                )

                print(f"      Block {block_idx}: dimmer={len(block.dimmer_blocks)}, colour={len(block.colour_blocks)}, movement={len(block.movement_blocks)}, special={len(block.special_blocks)}, has_any={has_any_blocks}")

                if not has_any_blocks:
                    print(f"      Skipping block {block_idx} - no sublane blocks")
                    continue

                # Find the time range of all blocks in this LightBlock
                all_sublane_blocks = (
                    list(block.dimmer_blocks) +
                    list(block.colour_blocks) +
                    list(block.movement_blocks) +
                    list(block.special_blocks)
                )

                block_start_time = min(b.start_time for b in all_sublane_blocks)
                block_end_time = max(b.end_time for b in all_sublane_blocks)
                block_start_time_ms = int(block_start_time * 1000)

                # Find BPM and song part at block start
                part_at_block = song_structure.get_part_at_time(block_start_time)
                block_bpm = part_at_block.bpm if part_at_block else 120
                block_signature = part_at_block.signature if part_at_block else "4/4"

                # Generate unified sequence steps
                # Pass all_lane_fixtures (sorted by position) for cross-group effects like ping-pong
                print(f"      Generating unified steps: bpm={block_bpm}, signature={block_signature}")
                print(f"        fixtures count: {len(group_fixtures)}, fixture_id_map has {len(fixture_id_map)} entries")
                print(f"        fixture_definitions has {len(fixture_definitions)} entries")
                try:
                    steps = generate_unified_sequence_steps(
                        fixtures=group_fixtures,
                        fixture_id_map=fixture_id_map,
                        fixture_definitions=fixture_definitions,
                        light_block=block,
                        bpm=block_bpm,
                        signature=block_signature,
                        all_lane_fixtures=sorted_lane_fixtures,  # All fixtures in lane for cross-group effects
                        config=config,  # Pass config for spot targeting
                        export_overrides=track_overrides
                    )

                    print(f"      Generated {len(steps) if steps else 0} steps")

                    if not steps:
                        user_warnings.warn(
                            f"Block at {block_start_time_ms}ms in lane "
                            f"'{lane_display_name}' produced no steps and "
                            f"was left out of the export",
                            category="export")
                        continue

                except Exception as e:
                    user_warnings.warn(
                        f"Block at {block_start_time_ms}ms in lane "
                        f"'{lane_display_name}' failed to export and was "
                        f"skipped: {e}",
                        category="export")
                    import traceback
                    traceback.print_exc()
                    continue

                # Create sequence for this unified block
                sequence_name = f"{show.name}_{lane_display_name}_unified_{block_start_time_ms}"
                sequence = create_sequence(engine, function_id_counter, sequence_name,
                                          scene.get("ID"), block_bpm)
                add_steps_to_sequence(sequence, steps)

                # Create ShowFunction for this block
                show_func = ET.SubElement(track, "ShowFunction")
                show_func.set("ID", str(function_id_counter))
                show_func.set("StartTime", str(block_start_time_ms))

                # Use color based on which effects are present
                if block.movement_blocks:
                    color = "#6496FF"  # Blue for movement
                elif block.colour_blocks:
                    color = "#FF6496"  # Pink for color
                else:
                    color = "#4CAF50"  # Green for dimmer

                show_func.set("Color", color)

                function_id_counter += 1

            fixture_start_id += fixture_num
            track_id += 1

    return function_id_counter


def create_shows(engine, config: Configuration, fixture_id_map: dict, fixture_definitions: dict,
                  export_overrides: dict = None):
    """
    Creates show function elements from Configuration data

    Parameters:
        engine: The engine XML element to add the show functions to
        config: Configuration object containing show data
        fixture_id_map: Dictionary mapping fixture object IDs to their sequential IDs
        fixture_definitions: Dictionary of fixture definitions loaded from QLC+
        export_overrides: Optional dict with export-time overrides (e.g. group_intensities)
    Returns:
        int: Next available function ID
    """
    if export_overrides is None:
        export_overrides = {}
    function_id_counter = 0

    # Process each show in the configuration
    for show_name, show in config.songs.items():
        # Debug info
        has_timeline = show.timeline_data is not None
        has_lanes = has_timeline and len(show.timeline_data.lanes) > 0 if has_timeline else False
        print(f"\n>>> Processing show: {show_name}")
        print(f"    timeline_data exists: {has_timeline}")
        print(f"    lanes count: {len(show.timeline_data.lanes) if has_timeline else 0}")
        print(f"    has_lanes (non-empty): {has_lanes}")

        # Create Function element for the show
        show_function = ET.SubElement(engine, "Function")
        show_function.set("ID", str(function_id_counter))
        show_function.set("Type", "Show")
        show_function.set("Name", show_name)
        function_id_counter += 1

        # Create TimeDivision element
        time_division = ET.SubElement(show_function, "TimeDivision")
        time_division.set("Type", "Time")
        # Use BPM from first show part, or default to 120
        time_division.set("BPM", str(show.parts[0].bpm if show.parts else 120))

        if show.timeline_data and show.timeline_data.lanes:
            print(f"    Using TIMELINE export path")
            function_id_counter = create_tracks_from_timeline(
                show_function,
                engine,
                show,
                config,
                fixture_id_map,
                function_id_counter,
                fixture_definitions,
                export_overrides=export_overrides
            )
            print(f"Successfully created show from timeline: {show_name}")
        else:
            # The Show function above is already in the workspace (VC
            # show buttons point at it), so say what really happens.
            user_warnings.warn(
                f"Song '{show_name}' has no timeline lanes; it exports "
                f"as an empty show",
                category="export")

    return function_id_counter




