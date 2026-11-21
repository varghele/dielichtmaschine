# utils/midi_utils.py
# MIDI input profile discovery for QLC+ trigger assignment

import logging
import os
import sys
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def get_midi_profile_directories() -> List[str]:
    """Get platform-specific QLC+ InputProfiles directories."""
    dirs = []

    if sys.platform == 'win32':
        # User profiles
        user_dir = os.path.join(os.path.expanduser('~'), 'QLC+', 'InputProfiles')
        dirs.append(user_dir)
        # System installs
        dirs.append(r'C:\QLC+\InputProfiles')
        dirs.append(r'C:\QLC+5\InputProfiles')
    elif sys.platform == 'darwin':
        dirs.append(os.path.expanduser('~/Library/Application Support/QLC+/InputProfiles'))
        dirs.append('/Applications/QLC+.app/Contents/Resources/InputProfiles')
    else:
        # Linux
        dirs.append(os.path.expanduser('~/.qlcplus/InputProfiles'))
        dirs.append('/usr/share/qlcplus/InputProfiles')

    return [d for d in dirs if os.path.isdir(d)]


def discover_midi_profiles() -> List[Dict[str, str]]:
    """Discover available MIDI input profiles from QLC+ installation.

    Returns:
        List of dicts with keys: 'name' (display name), 'manufacturer', 'model',
        'type', 'file_path'
    """
    profiles = []
    seen_names = set()

    for profile_dir in get_midi_profile_directories():
        for filename in os.listdir(profile_dir):
            if not filename.endswith('.qxi'):
                continue

            file_path = os.path.join(profile_dir, filename)
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                # Strip namespace
                ns = ''
                if root.tag.startswith('{'):
                    ns = root.tag.split('}')[0] + '}'

                manufacturer = root.findtext(f'{ns}Manufacturer', '')
                model = root.findtext(f'{ns}Model', '')
                profile_type = root.findtext(f'{ns}Type', '')

                if not manufacturer or not model:
                    continue

                name = f"{manufacturer} {model}"
                if name in seen_names:
                    continue
                seen_names.add(name)

                profiles.append({
                    'name': name,
                    'manufacturer': manufacturer,
                    'model': model,
                    'type': profile_type,
                    'file_path': file_path,
                })
            except (ET.ParseError, OSError):
                continue

    # Sort by name
    profiles.sort(key=lambda p: p['name'])
    return profiles


def ensure_midi_device_in_config(config, profile_name, midi_profiles=None):
    """Ensure a MidiInputDevice exists in config for the given profile name.

    Args:
        config: Configuration object
        profile_name: MIDI profile name (e.g. "Akai APC Mini mk2")
        midi_profiles: Optional list of discovered profiles (from discover_midi_profiles()).
                       If None, will be discovered automatically.
    """
    from config.models import MidiInputDevice

    # Check if already exists
    for dev in config.midi_input_devices:
        if dev.name == profile_name:
            return

    # Find the profile info for the UID
    model_name = profile_name
    if midi_profiles is None:
        try:
            midi_profiles = discover_midi_profiles()
        except Exception:
            logger.debug("MIDI profile discovery failed", exc_info=True)
            midi_profiles = []
    for p in midi_profiles:
        if p['name'] == profile_name:
            model_name = p['model']
            break

    # Assign next available universe ID (after existing output universes)
    used_ids = set()
    for u in config.universes.values():
        used_ids.add(u.id - 1)  # Convert to 0-based
    for d in config.midi_input_devices:
        used_ids.add(d.universe_id)
    next_id = 0
    while next_id in used_ids:
        next_id += 1

    device = MidiInputDevice(
        name=profile_name,
        uid=model_name.lower(),
        profile=profile_name,
        universe_id=next_id,
        line=1
    )
    config.midi_input_devices.append(device)
