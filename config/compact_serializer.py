"""Compact config serialization with two-level deduplication.

Deduplicates at two levels:
1. Sublane block templates (dimmer, colour, movement, special)
2. LightBlock templates (combining sublane refs with relative timing)

Templates are global across all shows. The in-memory representation is unchanged;
only the YAML serialization format changes.

Lane format preserves original block ordering (not grouped by template) since
blocks may not be chronologically sorted.
"""
import json
from copy import deepcopy
from typing import Dict, List, Any

# Fields excluded from content comparison for sublane blocks
SUBLANE_EXCLUDE_FIELDS = {'start_time', 'end_time', 'modified'}

# Sublane type prefixes for auto-generated IDs
SUBLANE_PREFIXES = {
    'dimmer': 'd',
    'colour': 'c',
    'movement': 'm',
    'special': 's',
}

SUBLANE_BLOCK_KEYS = ['dimmer_blocks', 'colour_blocks', 'movement_blocks', 'special_blocks']
SUBLANE_TYPE_FOR_KEY = {
    'dimmer_blocks': 'dimmer',
    'colour_blocks': 'colour',
    'movement_blocks': 'movement',
    'special_blocks': 'special',
}


def _round_floats(value: Any, precision: int = 6) -> Any:
    """Round float values to given precision for stable comparison."""
    if isinstance(value, float):
        return round(value, precision)
    if isinstance(value, dict):
        return {k: _round_floats(v, precision) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v, precision) for v in value]
    return value


def _content_key(block_dict: Dict, exclude_fields: set) -> str:
    """Compute a canonical string key for dedup comparison.

    All fields except those in exclude_fields are included.
    Float values are rounded to 6 decimal places for stability.
    """
    filtered = {k: v for k, v in block_dict.items() if k not in exclude_fields}
    filtered = _round_floats(filtered)
    return json.dumps(filtered, sort_keys=True, default=str)


def _normalize_sublane_timing(sublane_blocks: List[Dict], lb_start: float, lb_end: float) -> List[Dict]:
    """Convert absolute sublane times to fractional offsets relative to LightBlock.

    offset=0.0 means block start, end=1.0 means block end.
    Returns list of dicts with {_block, offset, end} - _block is the original dict.
    """
    lb_duration = lb_end - lb_start
    result = []
    for block in sublane_blocks:
        if lb_duration > 0:
            offset = round((block['start_time'] - lb_start) / lb_duration, 6)
            end = round((block['end_time'] - lb_start) / lb_duration, 6)
        else:
            offset = 0.0
            end = 1.0
        result.append({'_block': block, 'offset': offset, 'end': end})
    return result


def _lightblock_content_key(lb_template: Dict) -> str:
    """Compute canonical key for a LightBlock template.

    Uses effect_name, name, riff_source, riff_version, and the sublane ref+timing lists.
    """
    key_parts = {
        'effect_name': lb_template.get('effect_name', ''),
        'name': lb_template.get('name'),
        'riff_source': lb_template.get('riff_source'),
        'riff_version': lb_template.get('riff_version'),
    }
    for sublane_key in SUBLANE_BLOCK_KEYS:
        entries = lb_template.get(sublane_key, [])
        key_parts[sublane_key] = [
            {'ref': e['ref'], 'offset': e['offset'], 'end': e['end']}
            for e in entries
        ]
    return json.dumps(_round_floats(key_parts), sort_keys=True, default=str)


class _Registry:
    """Tracks unique templates and assigns auto-IDs."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.key_to_id: Dict[str, str] = {}
        self.id_to_template: Dict[str, Dict] = {}
        self._counter = 0

    def register(self, content_key: str, template: Dict) -> str:
        """Register a template and return its ID. Returns existing ID if duplicate."""
        if content_key in self.key_to_id:
            return self.key_to_id[content_key]
        tid = f"{self.prefix}{self._counter}"
        self._counter += 1
        self.key_to_id[content_key] = tid
        self.id_to_template[tid] = template
        return tid

    def to_dict(self) -> Dict:
        return dict(self.id_to_template)


def compact_serialize(data: dict) -> dict:
    """Transform a config dict into compact format with deduplicated templates.

    Entry point for save. Walks all shows' timeline data, extracts sublane and
    LightBlock templates, and replaces inline blocks with refs preserving
    original block ordering within each lane.
    """
    data = deepcopy(data)

    songs = data.get('songs')
    if not songs:
        return data

    # Check if any song has timeline_data with lanes
    has_timeline = False
    for show_data in songs.values():
        td = show_data.get('timeline_data')
        if td and td.get('lanes'):
            has_timeline = True
            break
    if not has_timeline:
        return data

    # Registries for sublane block templates
    sublane_registries = {
        sublane_type: _Registry(prefix)
        for sublane_type, prefix in SUBLANE_PREFIXES.items()
    }
    # Registry for LightBlock templates
    lb_registry = _Registry('lb')

    # Process all songs
    for show_name, show_data in songs.items():
        td = show_data.get('timeline_data')
        if not td or not td.get('lanes'):
            continue

        for lane in td['lanes']:
            light_blocks = lane.get('light_blocks', [])
            if not light_blocks:
                continue

            compact_entries = []

            for lb in light_blocks:
                lb_start = lb.get('start_time', 0.0)
                lb_end = lb.get('end_time', 0.0)

                # Build LightBlock template with sublane refs
                lb_template = {
                    'effect_name': lb.get('effect_name', ''),
                    'name': lb.get('name'),
                    'riff_source': lb.get('riff_source'),
                    'riff_version': lb.get('riff_version'),
                }

                for sublane_key in SUBLANE_BLOCK_KEYS:
                    sublane_type = SUBLANE_TYPE_FOR_KEY[sublane_key]
                    registry = sublane_registries[sublane_type]
                    blocks = lb.get(sublane_key, [])
                    normalized = _normalize_sublane_timing(blocks, lb_start, lb_end)

                    ref_entries = []
                    for entry in normalized:
                        block = entry['_block']
                        ckey = _content_key(block, SUBLANE_EXCLUDE_FIELDS)
                        # Template is the block without timing/modified fields
                        template = {k: v for k, v in block.items()
                                    if k not in SUBLANE_EXCLUDE_FIELDS}
                        ref_id = registry.register(ckey, template)
                        ref_entries.append({
                            'ref': ref_id,
                            'offset': entry['offset'],
                            'end': entry['end'],
                        })
                    lb_template[sublane_key] = ref_entries

                # Register the LightBlock template
                lb_key = _lightblock_content_key(lb_template)
                lb_id = lb_registry.register(lb_key, lb_template)

                # Preserve original ordering: one entry per block.
                # Morph provenance ("morphed:<edge>"/"hand_edited") is
                # PER-INSTANCE state, so it rides on the entry - it can
                # never live in the dedup template, where two identical
                # blocks with different provenance share one def. Only
                # written when set, so pre-provenance files are stable.
                compact_entry = {
                    'ref': lb_id,
                    'start': round(lb_start, 6),
                    'end': round(lb_end, 6),
                }
                if lb.get('provenance'):
                    compact_entry['provenance'] = lb['provenance']
                compact_entries.append(compact_entry)

            lane['light_blocks'] = compact_entries

    # Build output with block_defs and light_block_defs at top level
    result = {}
    # Emit block_defs (only types that have entries)
    block_defs = {}
    for sublane_type, registry in sublane_registries.items():
        defs = registry.to_dict()
        if defs:
            block_defs[sublane_type] = defs
    if block_defs:
        result['block_defs'] = block_defs

    # Emit light_block_defs
    lb_defs = lb_registry.to_dict()
    if lb_defs:
        result['light_block_defs'] = lb_defs

    # Add remaining data
    for key, value in data.items():
        result[key] = value

    return result


def expand_compact(data: dict) -> dict:
    """Expand compact format back to inline format for loading.

    Entry point for load. If no block_defs key exists, returns data unchanged
    (backward compatibility with old format).
    """
    if 'block_defs' not in data:
        return data

    data = deepcopy(data)

    block_defs = data.pop('block_defs', {})
    light_block_defs = data.pop('light_block_defs', {})

    # Configuration.load migrates the legacy `shows:` key to `songs`
    # before calling this; accept both anyway for direct callers.
    songs = data.get('songs') or data.get('shows')
    if not songs:
        return data

    for show_name, show_data in songs.items():
        td = show_data.get('timeline_data')
        if not td or not td.get('lanes'):
            continue

        for lane in td['lanes']:
            compact_blocks = lane.get('light_blocks', [])
            expanded_blocks = []

            for entry in compact_blocks:
                if 'ref' not in entry:
                    # Already inline format (shouldn't happen in compact, but be safe)
                    expanded_blocks.append(entry)
                    continue

                lb_id = entry['ref']
                lb_template = light_block_defs.get(lb_id, {})

                # Support both formats:
                # New: {ref, start, end} per entry
                # Old: {ref, placements: [[start, end], ...]} grouped
                if 'placements' in entry:
                    placement_list = entry['placements']
                else:
                    placement_list = [[entry['start'], entry['end']]]

                for placement in placement_list:
                    abs_start, abs_end = placement[0], placement[1]

                    # Build full inline LightBlock dict. Provenance is
                    # per-instance and lives on the ENTRY (absent in
                    # files written before 2026-07-17 -> "").
                    lb_dict = {
                        'start_time': abs_start,
                        'end_time': abs_end,
                        'effect_name': lb_template.get('effect_name', ''),
                        'modified': False,
                        'name': lb_template.get('name'),
                        'riff_source': lb_template.get('riff_source'),
                        'riff_version': lb_template.get('riff_version'),
                        'provenance': entry.get('provenance', ''),
                        'duration': round(abs_end - abs_start, 6),
                        'parameters': {},
                    }

                    # Expand sublane refs to full inline dicts
                    duration = abs_end - abs_start
                    for sublane_key in SUBLANE_BLOCK_KEYS:
                        sublane_type = SUBLANE_TYPE_FOR_KEY[sublane_key]
                        type_defs = block_defs.get(sublane_type, {})
                        template_entries = lb_template.get(sublane_key, [])

                        expanded_sublanes = []
                        for tmpl_entry in template_entries:
                            ref_id = tmpl_entry['ref']
                            sublane_template = type_defs.get(ref_id, {})

                            # Build full sublane block dict with absolute times
                            sublane_dict = dict(sublane_template)
                            sublane_dict['start_time'] = round(
                                abs_start + tmpl_entry['offset'] * duration, 6)
                            sublane_dict['end_time'] = round(
                                abs_start + tmpl_entry['end'] * duration, 6)
                            sublane_dict['modified'] = False
                            expanded_sublanes.append(sublane_dict)

                        lb_dict[sublane_key] = expanded_sublanes

                    expanded_blocks.append(lb_dict)

            lane['light_blocks'] = expanded_blocks

    return data
