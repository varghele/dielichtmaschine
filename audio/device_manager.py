"""
Audio device management for Die Lichtmaschine.

Handles device enumeration, classification, filtering, and selection.
Uses sounddevice for cross-platform ASIO (Windows) / JACK (Linux) support.

Why classification exists
-------------------------
PortAudio on Windows enumerates each physical device once per host API
it supports (MME / DirectSound / WASAPI / WDM-KS / ASIO), so a single
microphone can appear 4-5 times in the raw device list. WDM-KS also
surfaces telephony-grade Bluetooth Hands-Free profiles with raw driver
paths like ``@System32\\drivers\\bthhfenum.sys``. MME and DirectSound
add abstract "mapper" devices that just route to the system default.

The classifier here labels each raw device by category (PHYSICAL,
MAPPER, TELEPHONY, VIRTUAL_DRIVER) and assigns a quality rank so the UI
can present a curated list by default while keeping a "show all" escape
hatch for power users.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import sounddevice as sd


# ── Classification constants ──────────────────────────────────────────


class DeviceCategory(Enum):
    """High-level role a raw PortAudio device plays.

    PHYSICAL — real audio hardware (or virtual driver acting as one).
    MAPPER — abstract routing endpoint (e.g. Microsoft Sound Mapper).
    TELEPHONY — Bluetooth Hands-Free Profile / SCO (8-16 kHz mono, useless
                for music analysis).
    VIRTUAL_DRIVER — software driver with no physical backing (e.g.
                     Steam Streaming, virtual cable). Treated as PHYSICAL
                     for UX since the user may genuinely want them.
    UNKNOWN — default when classification fails.
    """
    PHYSICAL = "physical"
    MAPPER = "mapper"
    TELEPHONY = "telephony"
    VIRTUAL_DRIVER = "virtual"
    UNKNOWN = "unknown"


# Quality ranking — lower wins both for sort order and for dedup tiebreak.
# Rationale: WDM-KS has lower raw latency than WASAPI on paper, but is
# more brittle and harder to share, so WASAPI ranks higher as the "what
# the user should pick first" choice. ASIO beats everything when present.
_QUALITY_RANK: Dict[str, int] = {
    "ASIO":                       0,
    "Windows WASAPI":             10,
    "Windows WDM-KS":             20,
    "Core Audio":                 30,
    "JACK Audio Connection Kit":  40,
    "ALSA":                       50,
    "Windows DirectSound":        60,
    "MME":                        70,
}
_UNKNOWN_QUALITY = 99


# Abstract mapper / system-default device names. Match is substring-based
# because PortAudio sometimes appends host-API suffixes or has locale
# variations (German Windows: "Primärer Soundtreiber").
_MAPPER_PATTERNS: Tuple[str, ...] = (
    "Microsoft Sound Mapper",
    "Primärer Soundtreiber",
    "Primärer Soundaufnahmetreiber",
    "Primary Sound Driver",
    "Primary Sound Capture Driver",
    "default",       # ALSA "default"
    "sysdefault",    # ALSA "sysdefault"
    "pulse",         # PulseAudio default sink
)

# Substrings/markers identifying telephony-grade Bluetooth profiles.
# ``bthhfenum.sys`` appears in raw WDM-KS device paths. ``Hands-Free``
# and ``HFP``/``HSP`` appear in friendly names across host APIs even
# when the device's reported sample rate is misleading (DirectSound
# software-mixes everything to 44.1 kHz regardless of the underlying
# HFP profile, so a SR-only check misses those entries).
_TELEPHONY_NAME_MARKERS: Tuple[str, ...] = (
    "bthhfenum.sys",
    "Hands-Free",
    "Handsfree",
    "(HFP)",
    "(HSP)",
)

# Sample-rate / channel ceiling below which we treat a device as
# telephony-grade even without a name marker. SCO is 8 kHz mono;
# HFP A2DP is up to 16 kHz mono. Anything that low is unusable for
# music analysis.
_TELEPHONY_MAX_SR = 16000
_TELEPHONY_MAX_CH = 1

# Stream-variant decorations that are *safe* to strip when computing
# the dedup key — they don't change which physical device is meant.
# We intentionally keep things like "Mic Array input" vs "Stereomix"
# distinct because they're meaningfully different signal paths on the
# same physical card; users may pick between them deliberately.
_STREAM_VARIANT_PATTERNS: Tuple[str, ...] = (
    r"\(R\)",                              # Realtek "(R)" trademark
    r"\s+Wave(?=\))",                      # " Wave" before closing paren
    r"\s+Wave$",                           # " Wave" at end
)

# MME truncates device names to 31 characters with no trailing
# indicator. Any MME name at exactly 31 chars without a closing paren
# is a truncation candidate; we match it against full-length names from
# other host APIs by prefix.
_MME_TRUNCATION_LENGTH = 31

# Trailing host-API decoration that some sounddevice display strings end
# up with (e.g. "Realtek Audio (Windows WASAPI)") — never present in the
# raw PortAudio name, but in case any consumer passes a pre-formatted
# string we strip it from the physical_id.
_HOST_API_DECORATION = re.compile(r"\s*\([^()]*(?:WASAPI|WDM-KS|MME|DirectSound|ASIO|JACK|ALSA)[^()]*\)\s*$", re.IGNORECASE)


# ── Data class ────────────────────────────────────────────────────────


@dataclass
class AudioDevice:
    """Represents an audio device with classification metadata.

    ``name`` is the raw PortAudio device string and is kept verbatim for
    compatibility with code that round-trips device identity via name.
    ``display_name`` is the cleaned label safe to put in UI. ``physical_id``
    is the dedup key — same physical device across multiple host APIs
    shares one ``physical_id``.
    """
    index: int
    name: str
    max_output_channels: int
    max_input_channels: int
    default_sample_rate: float
    host_api: str
    host_api_index: int

    # Classification metadata (defaults so old call sites that construct
    # AudioDevice directly don't crash; the enumerate_* methods always
    # populate these).
    quality_rank: int = _UNKNOWN_QUALITY
    category: DeviceCategory = DeviceCategory.UNKNOWN
    display_name: str = ""
    physical_id: str = ""

    def __str__(self):
        label = self.display_name or self.name
        return (f"{label} ({self.max_output_channels}out/"
                f"{self.max_input_channels}in @ "
                f"{int(self.default_sample_rate)} Hz, {self.host_api})")


# ── Classification helpers ────────────────────────────────────────────


def _strip_system32_path(raw_name: str) -> str:
    """Pull a friendly name out of a WDM-KS ``@System32\\drivers\\*`` string.

    The raw form looks like::

        Output (@System32\\drivers\\bthhfenum.sys,#4;%1 Hands-Free HF Audio%0
        ;(Galaxy S22))

    The trailing ``(Galaxy S22)`` is the human-friendly name. If we find
    it we return that with an explicit Bluetooth-Handsfree tag so the
    user knows what they're looking at; otherwise we return a generic
    fallback so the @System32 path doesn't leak into the UI.
    """
    if "bthhfenum.sys" not in raw_name:
        return raw_name

    # The raw form is e.g.::
    #   Output (@System32\drivers\bthhfenum.sys,#4;%1 Hands-Free HF Audio%0
    #   ;(Galaxy S22))
    # The friendly name lives inside ";(...)" near the end. We search
    # for that inner paren group anywhere (not anchored to end-of-string
    # because the whole thing is wrapped in an outer "(...)").
    m = re.search(r";\(([^()]+)\)", raw_name)
    if m:
        return f"{m.group(1).strip()} (Bluetooth Handsfree)"

    # No human name embedded — generic label.
    direction = "Output" if raw_name.startswith("Output") else "Input"
    return f"Bluetooth Handsfree ({direction})"


def _clean_display_name(raw_name: str) -> str:
    """Return a UI-safe label for ``raw_name``."""
    name = _strip_system32_path(raw_name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _physical_id(display_name: str) -> str:
    """Compute a dedup key for collapsing the same device across host APIs.

    Strips stream-variant suffixes (WDM-KS exposes one card as
    "Mic Array input" / "Mic input" / "Stereo input"; we want them to
    share an id) and lowercases the result for case-insensitive match.
    """
    pid = display_name
    # Strip host-API decoration if any consumer pre-formatted it.
    pid = _HOST_API_DECORATION.sub("", pid)
    # Strip WDM-KS stream-variant suffixes (repeated until stable so
    # multiple suffixes get peeled).
    prev = None
    while prev != pid:
        prev = pid
        for pattern in _STREAM_VARIANT_PATTERNS:
            pid = re.sub(pattern, "", pid, flags=re.IGNORECASE)
    return pid.strip().lower()


def _classify(raw_name: str, default_sr: float, max_in: int,
              max_out: int) -> DeviceCategory:
    """Assign a category based on name + capabilities."""
    if any(p in raw_name for p in _MAPPER_PATTERNS):
        return DeviceCategory.MAPPER
    # Telephony: explicit name markers (catches DirectSound HFP entries
    # that report a misleading 44.1 kHz) OR low-rate-mono heuristic
    # (catches anything generic that's clearly SCO-grade).
    if any(m in raw_name for m in _TELEPHONY_NAME_MARKERS):
        return DeviceCategory.TELEPHONY
    total_ch = max(max_in, max_out)
    if default_sr <= _TELEPHONY_MAX_SR and total_ch <= _TELEPHONY_MAX_CH:
        return DeviceCategory.TELEPHONY
    # Steam virtual / VB-Audio Cable / etc. — we don't bother
    # distinguishing virtual from physical for UX; treat as PHYSICAL.
    return DeviceCategory.PHYSICAL


def _classify_device(info: dict, api_name: str) -> Tuple[
        DeviceCategory, str, str, int]:
    """Run the full classification pipeline.

    Returns ``(category, display_name, physical_id, quality_rank)``.
    Pure function — testable without touching sounddevice.
    """
    raw_name = info.get("name", "")
    display_name = _clean_display_name(raw_name)
    category = _classify(
        raw_name,
        info.get("default_samplerate", 0.0),
        info.get("max_input_channels", 0),
        info.get("max_output_channels", 0),
    )
    pid = _physical_id(display_name)
    rank = _QUALITY_RANK.get(api_name, _UNKNOWN_QUALITY)
    return category, display_name, pid, rank


# ── ASIO registry probe (Windows-only) ────────────────────────────────


def get_registered_asio_drivers() -> List[str]:
    """Return the list of ASIO driver names registered on this Windows
    install.

    Reads ``HKLM\\SOFTWARE\\ASIO`` (and ``WOW6432Node`` for 32-bit
    drivers in a 64-bit process). Empty on non-Windows or if no drivers
    are registered. Safe to call always — catches ``ImportError`` for
    ``winreg`` and returns ``[]``.
    """
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    names: List[str] = []
    for hive_path in (r"SOFTWARE\ASIO", r"SOFTWARE\WOW6432Node\ASIO"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hive_path) as root:
                i = 0
                while True:
                    try:
                        names.append(winreg.EnumKey(root, i))
                        i += 1
                    except OSError:
                        break
        except OSError:
            # Key doesn't exist — no ASIO drivers under this path.
            continue
    # Dedup while preserving order (a driver can appear under both hive
    # paths if it ships 32- and 64-bit shims).
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def asio_status() -> Dict[str, object]:
    """Summarise ASIO availability on the current system.

    Returns a dict with::

        {
            'in_portaudio': bool,         # ASIO host API exposed by sounddevice
            'registered_drivers': List[str],  # from the Windows registry
            'message': str,               # human-readable summary for the UI
            'level': str,                 # 'ok' | 'warn' | 'info'
        }

    The ``message`` is intended for direct display in a hint label.
    ``level`` lets the UI pick a colour without re-deriving state.
    """
    try:
        apis = [a["name"] for a in sd.query_hostapis()]
    except Exception:
        apis = []
    in_portaudio = "ASIO" in apis
    registered = get_registered_asio_drivers()

    if in_portaudio:
        if registered:
            msg = (f"ASIO ready — {len(registered)} driver(s) detected: "
                   f"{', '.join(registered)}.")
        else:
            msg = "ASIO host API available."
        return {
            "in_portaudio": True,
            "registered_drivers": registered,
            "message": msg,
            "level": "ok",
        }

    if registered:
        return {
            "in_portaudio": False,
            "registered_drivers": registered,
            "message": (
                f"ASIO drivers registered ({', '.join(registered)}) but no "
                "ASIO host API is exposed. Plug in your audio interface "
                "and click Refresh."
            ),
            "level": "warn",
        }

    # No ASIO at all.
    if sys.platform == "win32":
        hint = ("For low-latency on Windows, install a vendor ASIO driver "
                "or ASIO4ALL (https://asio4all.org).")
    elif sys.platform == "linux":
        hint = "For low-latency on Linux, configure JACK."
    else:
        hint = "No ASIO host API on this platform."
    return {
        "in_portaudio": False,
        "registered_drivers": [],
        "message": hint,
        "level": "info",
    }


# ── Enumeration ───────────────────────────────────────────────────────


def _propagate_mme_categories(devices: List[AudioDevice]) -> None:
    """Fix up MME entries truncated at the 31-char cap.

    The Hands-Free / @System32 / mapper markers used by :func:`_classify`
    can fall off the end of an MME name (e.g. ``"Kopfhörer (IE PRO BT
    Module Han"`` is the truncated form of a Hands-Free entry). Once
    the truncation has hidden the marker the device gets PHYSICAL even
    though its longer siblings on other host APIs were correctly
    classified as TELEPHONY or MAPPER.

    Walk the list and, for each MME entry at the truncation cap, copy
    the category from the longest non-MME entry whose display name
    starts with this MME entry's display name.
    """
    # Build name → category index from non-MME entries first.
    non_mme: List[AudioDevice] = [d for d in devices if d.host_api != "MME"]

    for d in devices:
        if d.host_api != "MME":
            continue
        if len(d.display_name) < _MME_TRUNCATION_LENGTH:
            continue
        if d.display_name.endswith(")"):
            # Already balanced parens — not a truncation.
            continue
        # Pick the longest matching sibling so we get the most specific
        # classification (rarely matters, but stable).
        candidates = [o for o in non_mme
                      if o.display_name.startswith(d.display_name)]
        if not candidates:
            continue
        match = max(candidates, key=lambda o: len(o.display_name))
        d.category = match.category


def _build_audio_device(index: int, info: dict, api_name: str,
                       api_index: int) -> AudioDevice:
    """Construct a fully-classified AudioDevice from a raw info dict."""
    category, display_name, pid, rank = _classify_device(info, api_name)
    return AudioDevice(
        index=index,
        name=info["name"],
        max_output_channels=info["max_output_channels"],
        max_input_channels=info["max_input_channels"],
        default_sample_rate=info["default_samplerate"],
        host_api=api_name,
        host_api_index=api_index,
        quality_rank=rank,
        category=category,
        display_name=display_name,
        physical_id=pid,
    )


def _filter_and_sort(devices: List[AudioDevice], *,
                     host_api_filter: Optional[str],
                     include_mappers: bool,
                     include_telephony: bool,
                     dedup_physical: bool) -> List[AudioDevice]:
    """Apply filter args and final sort.

    Sort key is ``(quality_rank, display_name)`` so the best host API
    wins and devices within an API are alphabetised.
    """
    if host_api_filter is not None:
        devices = [d for d in devices if d.host_api == host_api_filter]
    if not include_mappers:
        devices = [d for d in devices if d.category != DeviceCategory.MAPPER]
    if not include_telephony:
        devices = [d for d in devices if d.category != DeviceCategory.TELEPHONY]

    devices = sorted(devices, key=lambda d: (d.quality_rank, d.display_name.lower()))

    if dedup_physical:
        devices = _dedup_devices(devices)

    return devices


def _dedup_devices(devices: List[AudioDevice]) -> List[AudioDevice]:
    """Collapse the same physical device across host APIs.

    Two-pass:

    1. Group by ``physical_id`` (matching display name after stripping
       safe stream-variant decorations) — keep the best-quality entry
       per group.
    2. Catch MME 31-char truncations: any MME entry whose display name
       length is at ``_MME_TRUNCATION_LENGTH`` and which is a strict
       prefix of another host API's display name is treated as a
       duplicate of that fuller entry.

    Devices are assumed already sorted best-first (quality_rank ascending)
    so taking the first occurrence per key keeps the highest-quality
    host API representative.
    """
    # Pass 1: physical_id dedup.
    seen: Dict[str, AudioDevice] = {}
    for d in devices:
        key = d.physical_id or f"__no_pid_{d.index}"
        if key not in seen:
            seen[key] = d
    survivors = list(seen.values())

    # Pass 2: MME truncation match. MME entries whose display name
    # length equals the MME truncation cap AND which prefix a longer
    # non-MME display name get dropped.
    non_mme_names = [d.display_name for d in survivors if d.host_api != "MME"]
    final: List[AudioDevice] = []
    for d in survivors:
        if (d.host_api == "MME"
                and len(d.display_name) >= _MME_TRUNCATION_LENGTH
                and not d.display_name.endswith(")")):
            if any(other.startswith(d.display_name) and other != d.display_name
                   for other in non_mme_names):
                continue  # truncation of an entry we already have
        final.append(d)

    return sorted(final, key=lambda d: (d.quality_rank, d.display_name.lower()))


class DeviceManager:
    """Manages audio device enumeration, classification, and selection."""

    def __init__(self):
        # No caching — sd.query_devices() is fast (~10 ms on Windows for
        # 43 devices) and caching across filter combinations is a
        # footgun. Callers that need to avoid duplicate enumeration can
        # call once and apply filters themselves.
        pass

    def initialize(self) -> bool:
        """Initialize device manager (no-op for sounddevice, kept for API compat)."""
        return True

    def cleanup(self):
        """Cleanup resources (no-op for sounddevice, kept for API compat)."""
        pass

    # ── Raw enumeration ───────────────────────────────────────────────

    def _all_devices_classified(self) -> List[AudioDevice]:
        """Pull every device from sounddevice and run classification."""
        out: List[AudioDevice] = []
        try:
            raw_devices = list(sd.query_devices())
            host_apis = list(sd.query_hostapis())
        except Exception as e:
            print(f"Error enumerating devices: {e}")
            return out

        for i, info in enumerate(raw_devices):
            api_index = info.get("hostapi", 0)
            try:
                api_name = host_apis[api_index]["name"]
            except (IndexError, KeyError):
                api_name = "Unknown"
            out.append(_build_audio_device(i, info, api_name, api_index))

        _propagate_mme_categories(out)
        return out

    # ── Public enumeration (curated by default) ───────────────────────

    def enumerate_devices(self, host_api_filter: Optional[str] = None,
                          include_inputs: bool = False,
                          include_mappers: bool = False,
                          include_telephony: bool = False,
                          dedup_physical: bool = True) -> List[AudioDevice]:
        """Enumerate output-capable devices (and inputs if requested).

        Args:
            host_api_filter: Restrict to one host API (e.g. ``"Windows WASAPI"``,
                ``"ASIO"``). ``None`` = all APIs.
            include_inputs: If True, devices with only input channels are
                also returned. Otherwise only output-capable devices.
            include_mappers: Include abstract MME/DirectSound sound-mapper
                endpoints. Default off.
            include_telephony: Include Bluetooth Hands-Free / low-rate
                mono devices. Default off.
            dedup_physical: Collapse the same physical device across
                multiple host APIs to one entry, keeping the highest-
                quality (lowest-rank) host API. Default on.
        """
        devices = self._all_devices_classified()
        if not include_inputs:
            devices = [d for d in devices if d.max_output_channels > 0]
        else:
            devices = [d for d in devices
                       if d.max_output_channels > 0 or d.max_input_channels > 0]
        return _filter_and_sort(
            devices,
            host_api_filter=host_api_filter,
            include_mappers=include_mappers,
            include_telephony=include_telephony,
            dedup_physical=dedup_physical,
        )

    def enumerate_input_devices(self, host_api_filter: Optional[str] = None,
                                include_mappers: bool = False,
                                include_telephony: bool = False,
                                dedup_physical: bool = True
                                ) -> List[AudioDevice]:
        """Enumerate input devices.

        See :meth:`enumerate_devices` for the filter semantics — defaults
        produce the curated list suitable for direct UI display.
        """
        devices = [d for d in self._all_devices_classified()
                   if d.max_input_channels > 0]
        return _filter_and_sort(
            devices,
            host_api_filter=host_api_filter,
            include_mappers=include_mappers,
            include_telephony=include_telephony,
            dedup_physical=dedup_physical,
        )

    # ── Defaults / lookups ────────────────────────────────────────────

    def get_default_device(self) -> Optional[AudioDevice]:
        """Get the system default output device."""
        try:
            default_output_index = sd.default.device[1]
            if default_output_index is None or default_output_index < 0:
                return None
            return self.get_device_by_index(default_output_index)
        except Exception as e:
            print(f"Error getting default device: {e}")
            return None

    def get_default_input_device(self) -> Optional[AudioDevice]:
        """Get the system default input device."""
        try:
            default_input_index = sd.default.device[0]
            if default_input_index is None or default_input_index < 0:
                return None
            return self.get_device_by_index(default_input_index)
        except Exception as e:
            print(f"Error getting default input device: {e}")
            return None

    def get_device_by_index(self, index: int) -> Optional[AudioDevice]:
        """Get device by its index, fully classified."""
        try:
            info = sd.query_devices(index)
            host_apis = sd.query_hostapis()
            api_index = info.get("hostapi", 0)
            try:
                api_name = host_apis[api_index]["name"]
            except (IndexError, KeyError):
                api_name = "Unknown"
            return _build_audio_device(index, info, api_name, api_index)
        except Exception as e:
            print(f"Error getting device {index}: {e}")
            return None

    def get_available_host_apis(self) -> List[Tuple[int, str]]:
        """Get all available host APIs.

        Returns:
            List of (index, name) tuples sorted by quality rank
            (ASIO first if present, MME last).
        """
        try:
            apis = sd.query_hostapis()
            indexed = [(i, api["name"]) for i, api in enumerate(apis)]
            indexed.sort(key=lambda t: _QUALITY_RANK.get(t[1], _UNKNOWN_QUALITY))
            return indexed
        except Exception as e:
            print(f"Error querying host APIs: {e}")
            return []

    def validate_device(self, device_index: int) -> bool:
        """Check if a device index is valid and available for output."""
        try:
            info = sd.query_devices(device_index)
            return info["max_output_channels"] > 0
        except Exception:
            return False

    def validate_input_device(self, device_index: int) -> bool:
        """Check if an input device index is valid and available."""
        try:
            info = sd.query_devices(device_index)
            return info["max_input_channels"] > 0
        except Exception:
            return False

    # ── Preferences persistence ───────────────────────────────────────

    def save_preferences(self, config_path: str, device_index: Optional[int],
                         sample_rate: int, buffer_size: int,
                         input_device_index: Optional[int] = None):
        """Save audio preferences to config file."""
        config = {
            'device_index': device_index,
            'sample_rate': sample_rate,
            'buffer_size': buffer_size,
            'input_device_index': input_device_index,
        }

        # Store device name for relocation if index changes across sessions.
        if device_index is not None:
            device = self.get_device_by_index(device_index)
            if device:
                config['device_name'] = device.name
                config['device_host_api'] = device.host_api

        if input_device_index is not None:
            device = self.get_device_by_index(input_device_index)
            if device:
                config['input_device_name'] = device.name
                config['input_device_host_api'] = device.host_api

        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving audio config: {e}")
            return False

    def load_preferences(self, config_path: str) -> Dict:
        """Load audio preferences from config file."""
        default_config = {
            'device_index': None,
            'sample_rate': 44100,
            'buffer_size': 512,
            'input_device_index': None,
        }

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            if config.get('device_index') is not None:
                if not self.validate_device(config['device_index']):
                    relocated = self._find_device_by_name(
                        config.get('device_name'), config.get('device_host_api'))
                    if relocated is not None:
                        print(f"Output device index changed, relocated to {relocated}")
                        config['device_index'] = relocated
                    else:
                        print("Configured output device not available, using default")
                        config['device_index'] = None

            if config.get('input_device_index') is not None:
                if not self.validate_input_device(config['input_device_index']):
                    relocated = self._find_device_by_name(
                        config.get('input_device_name'), config.get('input_device_host_api'))
                    if relocated is not None:
                        print(f"Input device index changed, relocated to {relocated}")
                        config['input_device_index'] = relocated
                    else:
                        print("Configured input device not available, using default")
                        config['input_device_index'] = None

            return {**default_config, **config}
        except FileNotFoundError:
            return default_config
        except Exception as e:
            print(f"Error loading audio config: {e}")
            return default_config

    def _find_device_by_name(self, name: Optional[str],
                             host_api: Optional[str]) -> Optional[int]:
        """Try to find a device by name and host API (for index relocation)."""
        if not name:
            return None
        try:
            all_devices = sd.query_devices()
            host_apis = sd.query_hostapis()
            for i, info in enumerate(all_devices):
                if info['name'] != name:
                    continue
                if host_api:
                    api_index = info.get('hostapi', 0)
                    try:
                        api_name = host_apis[api_index]['name']
                    except (IndexError, KeyError):
                        api_name = ""
                    if api_name == host_api:
                        return i
                else:
                    return i
        except Exception:
            pass
        return None
