"""
Persistence for Auto Mode session state.

Stores ArtNet configuration, audio device choice, BPM/groove settings,
movement target, color override, per-group constraints, submasters, and
the visualiser-broadcast toggle in
`~/.qlcautoshow/auto_mode_settings.json` so the operator does not have
to reconfigure on every launch. The previous filename
(``live_mode_settings.json``) is read once for migration so existing
users don't lose state on the first run after the rename.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple


_SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".qlcautoshow")
_SETTINGS_PATH = os.path.join(_SETTINGS_DIR, "auto_mode_settings.json")
_LEGACY_SETTINGS_PATH = os.path.join(_SETTINGS_DIR, "live_mode_settings.json")


@dataclass
class AutoModeSettings:
    """All persisted Auto Mode state. Sensible defaults match a fresh launch."""

    # ArtNet output
    target_ip: str = "192.168.1.151"
    universe_mapping: Dict[int, int] = field(default_factory=dict)  # config uid -> artnet uid
    mirror_to_visualizer: bool = True

    # Audio input — store device name (indices are unstable across reboots)
    input_device_name: Optional[str] = None
    # Last-selected host API filter in the AutoTab input combo. Special
    # values: "Curated (recommended)" (default) and "All devices (raw)".
    # Anything else is a literal host-API name (e.g. "Windows WASAPI",
    # "ASIO"). Resilient to missing or stale APIs — the AutoTab falls
    # back to "Curated" if the saved API isn't currently available.
    input_host_api: str = "Curated (recommended)"
    # Linear input gain 0.1..10 (= +/-20 dB), applied in the capture
    # callback before analysis. The tab clamps on use - a hand-edited
    # JSON value must never become a 1000x multiplier.
    input_gain: float = 1.0

    # Engine controls
    bpm: int = 120
    energy_sensitivity: int = 70  # 0..100
    # ``target_plane_name`` holds the literal combo-box text, including
    # "None (manual)" — earlier versions stripped that to "" on save
    # which then fell back to "Front" on load, silently re-enabling
    # plane targeting against the user's choice.
    target_plane_name: str = "Front"
    max_movement_speed: int = 0  # degrees/sec, 0 = off

    # Color override
    color_override_active: bool = False
    color_override_hue: float = 0.0       # 0..360
    color_override_saturation: float = 1.0  # 0..1

    # Per-group state — empty/missing means AUTO / default
    group_constraints: Dict[str, List[str]] = field(default_factory=dict)
    group_submasters: Dict[str, int] = field(default_factory=dict)  # 0..100


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def load() -> AutoModeSettings:
    """Read settings from disk. Returns defaults on missing/corrupt file.

    Falls back to the legacy ``live_mode_settings.json`` path if the
    current file is missing — keeps prior session state around through
    the rename. The legacy file is never overwritten; subsequent saves
    go to the new path.
    """
    data = _read_json(_SETTINGS_PATH)
    if data is None:
        data = _read_json(_LEGACY_SETTINGS_PATH)
    if data is None:
        return AutoModeSettings()

    defaults = AutoModeSettings()
    valid_keys = set(asdict(defaults).keys())
    filtered = {k: v for k, v in data.items() if k in valid_keys}

    # JSON turns int keys into strings — restore for universe_mapping.
    if "universe_mapping" in filtered:
        try:
            filtered["universe_mapping"] = {
                int(k): int(v) for k, v in filtered["universe_mapping"].items()
            }
        except (ValueError, AttributeError):
            filtered["universe_mapping"] = {}

    return AutoModeSettings(**{**asdict(defaults), **filtered})


def save(settings: AutoModeSettings) -> None:
    """Write settings to disk. Silently ignores I/O errors — never block window close."""
    try:
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        data = asdict(settings)
        # Stringify int keys for JSON.
        data["universe_mapping"] = {str(k): v for k, v in data["universe_mapping"].items()}
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"Failed to save Auto Mode settings: {e}")
