import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import os
from typing import Dict, Optional
from config.models import Configuration, FixtureGroupCapabilities
from utils.to_xml.setup_to_xml import (create_universe_elements, create_fixture_elements,
                                       create_channels_groups)
from utils.to_xml.shows_to_xml import create_shows
from utils.to_xml.preset_scenes_to_xml import generate_all_preset_functions, create_master_presets
from utils.to_xml.virtual_console_to_xml import build_virtual_console
from utils.fixture_utils import load_fixture_definitions_from_qlc, detect_fixture_group_capabilities


def create_qlc_workspace(config: Configuration, vc_options: Optional[Dict[str, bool]] = None):
    """
    Create QLC+ workspace file using Configuration data

    Args:
        config: Configuration object containing fixtures, groups, shows, and universes
        vc_options: Optional dict with Virtual Console generation options:
            - generate_vc: bool - Master toggle for VC generation
            - group_controls: bool - Include fixture group controls (sliders, XY pads)
            - scene_presets: bool - Include color/intensity preset scenes
            - movement_presets: bool - Include movement EFX patterns
            - show_buttons: bool - Include show trigger buttons in SoloFrame
            - speed_dial: bool - Include tap BPM SpeedDial
            - master_presets: bool - Include master presets (scenes/chasers for all fixtures)
            - dark_mode: bool - Use dark/black background
            - qlc_target_version: str - Version stamped into <Creator><Version>.
              Cosmetic only; the workspace XML schema is identical between
              QLC+ 4.x and 5.x. Default: "4.14.4".
    """
    # Set up base dir
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace_path = os.path.join(base_dir, 'workspace.qxw')

    # Get set of models we need definitions for
    models_in_config = {(fixture.manufacturer, fixture.model)
                        for group in config.groups.values()
                        for fixture in group.fixtures}

    # Load fixture definitions
    fixture_definitions = load_fixture_definitions_from_qlc(models_in_config)

    # Create the root element with namespace
    root = ET.Element("Workspace")
    root.set("xmlns", "http://www.qlcplus.org/Workspace")
    root.set("CurrentWindow", "VirtualConsole")

    # Create Creator section
    qlc_version = (vc_options or {}).get('qlc_target_version', '4.14.4')
    creator = ET.SubElement(root, "Creator")
    ET.SubElement(creator, "Name").text = "Q Light Controller Plus"
    ET.SubElement(creator, "Version").text = qlc_version
    ET.SubElement(creator, "Author").text = "Auto Generated"

    # Create Engine section
    engine = ET.SubElement(root, "Engine")

    # Create InputOutputMap and add universes
    input_output_map = ET.SubElement(engine, "InputOutputMap")
    create_universe_elements(input_output_map, config)

    # Create Fixtures and get fixture ID mapping
    fixture_id_map = create_fixture_elements(engine, config)

    # Create ChannelsGroups using Configuration data and fixture ID mapping
    create_channels_groups(engine, config, fixture_id_map, fixture_definitions)

    # Detect fixture group capabilities (needed for PAUSE show and VC generation)
    capabilities_map = {}
    for group_name, group in config.groups.items():
        if group.fixtures:
            capabilities_map[group_name] = detect_fixture_group_capabilities(
                group.fixtures, fixture_definitions
            )

    # Generate PAUSE show if configured
    _injected_pause = False
    if config.pause_show and config.pause_show.enabled:
        from utils.pause_show_generator import generate_pause_show
        from utils.midi_utils import ensure_midi_device_in_config
        pause_show = generate_pause_show(config, fixture_definitions, capabilities_map)
        if pause_show:
            config.songs["PAUSE"] = pause_show
            _injected_pause = True
            # Ensure MIDI device exists for the pause trigger
            if config.pause_show.trigger_device:
                ensure_midi_device_in_config(config, config.pause_show.trigger_device)

    # Create Shows using Configuration data and collect show function IDs
    export_overrides = {}
    if vc_options and 'group_intensities' in vc_options:
        export_overrides['group_intensities'] = vc_options['group_intensities']
    function_id_counter = create_shows(engine, config, fixture_id_map, fixture_definitions,
                                       export_overrides=export_overrides)

    # Collect show function IDs for show buttons
    show_function_ids = {}
    # Find show functions in the engine
    for func in engine.findall("Function"):
        if func.get("Type") == "Show":
            show_function_ids[func.get("Name")] = int(func.get("ID"))

    # Generate preset functions if requested
    preset_function_map = {}
    master_presets = {}
    if vc_options and vc_options.get('generate_vc') and vc_options.get('scene_presets'):
        preset_function_map, function_id_counter = generate_all_preset_functions(
            engine, config, fixture_id_map, fixture_definitions,
            capabilities_map, function_id_counter,
            include_color=True,
            include_intensity=False,  # Intensity controlled via dimmer slider
            include_movement=vc_options.get('movement_presets', True)
        )

    # Generate master presets (scenes and chasers for all fixtures)
    if vc_options and vc_options.get('generate_vc') and vc_options.get('master_presets'):
        master_presets, function_id_counter = create_master_presets(
            engine, function_id_counter, config, fixture_id_map, fixture_definitions
        )

    # Create VirtualConsole section
    if vc_options and vc_options.get('generate_vc'):
        # Use the new VC builder
        build_virtual_console(
            root, engine, config, fixture_id_map, fixture_definitions,
            capabilities_map, vc_options, show_function_ids, preset_function_map, master_presets
        )
    else:
        # Create minimal VirtualConsole section (backwards compatibility)
        vc = ET.SubElement(root, "VirtualConsole")
        frame = ET.SubElement(vc, "Frame")
        frame.set("Caption", "")

        # Add Appearance
        appearance = ET.SubElement(frame, "Appearance")
        ET.SubElement(appearance, "FrameStyle").text = "None"
        ET.SubElement(appearance, "ForegroundColor").text = "Default"
        ET.SubElement(appearance, "BackgroundColor").text = "Default"
        ET.SubElement(appearance, "BackgroundImage").text = "None"
        ET.SubElement(appearance, "Font").text = "Default"

        # Add Properties
        properties = ET.SubElement(vc, "Properties")
        size = ET.SubElement(properties, "Size")
        size.set("Width", "1920")
        size.set("Height", "1080")

        # Add GrandMaster properties
        grandmaster = ET.SubElement(properties, "GrandMaster")
        grandmaster.set("ChannelMode", "Intensity")
        grandmaster.set("ValueMode", "Reduce")
        grandmaster.set("SliderMode", "Normal")

    # Remove injected PAUSE show from config (it's ephemeral, only for export)
    if _injected_pause:
        del config.songs["PAUSE"]

    # Create SimpleDesk section
    simple_desk = ET.SubElement(engine, "SimpleDesk")
    ET.SubElement(simple_desk, "Engine")

    # Create the XML tree
    tree = ET.ElementTree(root)

    # Pretty print the XML
    rough_string = ET.tostring(root, encoding='UTF-8')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ")

    # Write to file with proper formatting
    with open(workspace_path, "w", encoding='UTF-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE Workspace>\n')
        f.write('\n'.join(pretty_xml.split('\n')[1:]))

    _write_gdtf_companion_qxfs(models_in_config, os.path.dirname(workspace_path))


def _write_gdtf_companion_qxfs(models_in_config, out_dir: str):
    """QLC+ interop for GDTF-sourced fixtures (GDTF plan Phase 2).

    QLC+ cannot read .gdtf. For every patched fixture whose definition
    came from a GDTF file and has no same-identity .qxf anywhere in the
    library, serialize the transpiled definition into
    ``<out_dir>/gdtf_companion_fixtures/`` and tell the user to drop the
    files into QLC+'s fixture folder; with them installed the exported
    workspace patches identically in QLC+.
    """
    from utils.fixture_library import (
        companion_qxf_filename, find_qxf_twin, get_definition,
        serialize_definition_to_qxf,
    )

    matched, generated = [], []
    for manufacturer, model in sorted(models_in_config):
        defn = get_definition(manufacturer, model)
        if defn is None or defn.source != 'gdtf':
            continue
        if find_qxf_twin(manufacturer, model) is not None:
            matched.append(f"{manufacturer} {model}")
            continue
        companion_dir = os.path.join(out_dir, 'gdtf_companion_fixtures')
        os.makedirs(companion_dir, exist_ok=True)
        out_path = os.path.join(companion_dir,
                                companion_qxf_filename(manufacturer, model))
        with open(out_path, 'w', encoding='UTF-8') as f:
            f.write(serialize_definition_to_qxf(defn))
        generated.append(out_path)

    if matched:
        print("GDTF fixtures with a same-identity .qxf in the QLC+ library "
              "(no companion needed): " + ", ".join(matched))
    if generated:
        print("GDTF fixtures unknown to QLC+; companion .qxf files written. "
              "Copy them into QLC+'s user fixture folder so the workspace "
              "patches correctly:")
        for path in generated:
            print(f"  {path}")
