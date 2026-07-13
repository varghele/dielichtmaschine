# visualizer/build_mode.py
"""Synthetic "build look" DMX for previewing a rig without live output.

ONE table and ONE synthesizer, shared by the embedded preview
(gui/widgets/embedded_visualizer.py, "build" mode) and the standalone
viewer's BUILD chip (visualizer/main.py), so the two looks can never
drift apart. GL-free and Qt-free on purpose.

The synthesizer works on the fixtures PAYLOAD shape
(utils/tcp/protocol.build_fixtures_payload): dicts carrying
``universe``, ``address`` and ``channel_mapping`` (channel number ->
function name, numbers may arrive as strings after a JSON round-trip).
"""

from typing import Dict, Iterable

# Per-channel-function defaults. Anything not in the table stays 0.
# Keeps coloured fixtures lit white, mover targets centred on stage,
# shutter open, no gobo/prism/strobe artefacts.
BUILD_MODE_DEFAULTS = {
    "dimmer": 255,
    "red": 255,
    "green": 255,
    "blue": 255,
    "white": 255,
    "amber": 255,
    "pan": 128,
    "tilt": 128,
    "pan_fine": 128,
    "tilt_fine": 128,
    "shutter": 255,  # most fixtures: 255 = open / no strobe
    "focus": 128,
    "zoom": 128,
}


def build_mode_buffers(fixtures: Iterable[dict]) -> Dict[int, bytes]:
    """Synthesise one 512-byte DMX buffer per universe for a build look.

    ``fixtures`` is an iterable of payload dicts (``universe``,
    ``address``, ``channel_mapping``). Unknown functions stay 0;
    unparsable channel numbers are skipped; addresses are 1-based.
    """
    per_universe: Dict[int, bytearray] = {}
    for fixture in fixtures:
        universe = fixture.get("universe", 1)
        buffer = per_universe.setdefault(universe, bytearray(512))
        base_addr = max(0, int(fixture.get("address", 1)) - 1)
        for ch_num, func in (fixture.get("channel_mapping") or {}).items():
            try:
                idx = base_addr + int(ch_num)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < 512:
                buffer[idx] = BUILD_MODE_DEFAULTS.get(func, 0)
    return {universe: bytes(buf) for universe, buf in per_universe.items()}
