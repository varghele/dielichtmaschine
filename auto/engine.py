"""
Auto Show Engine — real-time riff generation driven by live audio.

Accumulates audio features into a sliding window, synthesizes a
SectionAnalysis-compatible profile, and runs a groove+fill riff cycle
that auto-generates lighting blocks matching the incoming sound.
"""

import time
import threading
import colorsys
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List, Set, Callable

from audio.realtime_spectral import LiveFeatureFrame
from audio.spectral_analysis import SectionAnalysis
from autogen.matcher import select_rudiments_per_group, match_rudiments_to_section
from autogen.spatial import (
    classify_fixture_groups, apply_vocal_rule, compute_richness_weights,
    assign_group_roles, get_gobo_prism_groups, ActivationRole,
)
from rudiments.block_converter import rudiment_to_dimmer_block, rudiment_to_movement_block
from config.models import DimmerBlock, ColourBlock, MovementBlock, SpecialBlock, Configuration


# How many feature frames to keep (~86 frames/sec at 44100/512)
_WINDOW_SECONDS = 45
_FRAMES_PER_SEC = 86  # approximate
_MAX_WINDOW = _WINDOW_SECONDS * _FRAMES_PER_SEC

# Energy-tiered movement shape pools (from autogen/generator.py)
_HIGH_ENERGY_SHAPES = ["circle", "figure_8", "lissajous", "diamond"]
_MEDIUM_ENERGY_SHAPES = ["bounce", "linear_sweep", "square", "triangle"]
_LOW_ENERGY_SHAPES = ["linear_sweep", "fan", "circle"]
_VERY_LOW_SHAPES = ["linear_sweep"]


@dataclass
class AutoCycleState:
    """Tracks where we are in the current groove cycle.

    The engine grooves continuously: every ``_cycle_bars`` bars, fresh
    riffs are selected from the audio profile. ``is_fill`` is no longer
    set automatically — it's a transient one-shot toggled by
    :meth:`AutoShowEngine.force_fill` and cleared on the next bar
    boundary, so the user can punch a fill manually without the engine
    auto-filling on its own.
    """
    cycle_start_time: float = 0.0
    bar_index: int = 0          # 0..cycle_bars-1
    is_fill: bool = False       # transient: only set by force_fill()
    groove_rudiment: str = "static"
    fill_rudiment: str = "stroke"  # selected for force_fill use


class AutoShowEngine:
    """Core engine for live audio-reactive lighting.

    Thread model:
    - on_feature_frame() called from analysis thread
    - tick() called from DMX thread at 30Hz
    - UI setters called from Qt main thread
    All shared state protected by _lock.
    """

    def __init__(self, config: Configuration, fixture_definitions: dict):
        self.config = config
        self.fixture_definitions = fixture_definitions

        # Audio feature sliding window
        self._window: deque = deque(maxlen=_MAX_WINDOW)
        self._lock = threading.Lock()

        # Classify fixture groups once
        self._group_classifications = classify_fixture_groups(config)
        self._group_names = list(config.groups.keys())

        # Riff cycle state
        self._bpm: float = 120.0
        # Bars per riff-reselection cycle. Fixed at 4 — the previous
        # auto-fill behaviour (groove for N bars, then a fill bar) is
        # gone; the engine now grooves continuously and just picks new
        # riffs every cycle. Fill is purely manual via force_fill().
        self._cycle_bars: int = 4
        self._cycle = AutoCycleState()
        self._per_group_rudiments: Dict[str, Tuple[str, str]] = {}
        self._previous_rudiments: Dict[str, str] = {}
        self._running = False
        self._engine_time: float = 0.0  # monotonic engine clock

        # User controls
        self._energy_sensitivity: float = 0.7
        self._color_override: Optional[Tuple[int, int, int]] = None
        self._group_submasters: Dict[str, float] = {g: 1.0 for g in self._group_names}
        self._group_constraints: Dict[str, Optional[Set[str]]] = {g: None for g in self._group_names}

        # Movement state
        self._target_plane = None  # Optional[StagePlane]
        self._movement_cycle_index: int = 0

        # Auto color state
        self._auto_color_rgb: Tuple[int, int, int] = (255, 255, 255)

        # Active block tracking (lane_key -> block_type -> registered)
        self._active_lanes: set = set()

        # DMX manager reference (set by AutoDMXController)
        self._dmx_manager = None

        # Callbacks for UI updates
        self._on_riffs_updated: Optional[Callable[[Dict[str, Tuple[str, str]]], None]] = None
        # Riff selection queued for the UI callback. The selection runs
        # under _lock; the callback fires only after the lock is released
        # (_flush_riffs_updated), so a callback that reads an engine
        # property cannot deadlock on the non-reentrant lock.
        self._pending_riffs: Optional[Dict[str, Tuple[str, str]]] = None

    # ── Public setters (called from Qt main thread) ──

    def set_dmx_manager(self, dmx_manager):
        """Set the DMXManager to register blocks with."""
        self._dmx_manager = dmx_manager

    def set_bpm(self, bpm: float):
        with self._lock:
            self._bpm = max(30.0, min(300.0, bpm))

    def set_energy_sensitivity(self, value: float):
        with self._lock:
            self._energy_sensitivity = max(0.0, min(1.0, value))

    def set_color_override(self, rgb: Optional[Tuple[int, int, int]]):
        with self._lock:
            self._color_override = rgb

    def set_group_submaster(self, group_name: str, value: float):
        with self._lock:
            if group_name in self._group_submasters:
                self._group_submasters[group_name] = max(0.0, min(1.0, value))

    def set_group_constraints(self, group_name: str, allowed: Optional[Set[str]]):
        """Set allowed rudiments for a group. None or empty = all allowed."""
        with self._lock:
            if group_name in self._group_constraints:
                self._group_constraints[group_name] = allowed if allowed else None

    def set_target_plane(self, plane):
        """Set the target plane for moving heads. None = no targeting."""
        with self._lock:
            self._target_plane = plane

    def refresh_from_config(self, config: Configuration) -> None:
        """Re-snapshot group classifications and names from ``config``.

        Called when the user edits fixture/stage state mid-show; the
        engine otherwise holds the snapshot taken at construction time
        and would keep targeting the old fixture set. New groups get a
        default 1.0 submaster and unconstrained riff set; removed
        groups have their submaster/constraint entries dropped.
        """
        with self._lock:
            self.config = config
            self._group_classifications = classify_fixture_groups(config)
            new_group_names = list(config.groups.keys())
            self._group_names = new_group_names
            self._group_submasters = {
                g: self._group_submasters.get(g, 1.0) for g in new_group_names
            }
            self._group_constraints = {
                g: self._group_constraints.get(g, None) for g in new_group_names
            }

    def set_max_movement_speed(self, degrees_per_sec: float):
        """Set max pan/tilt speed. Forwarded to DMX manager."""
        if self._dmx_manager:
            self._dmx_manager.set_max_pan_tilt_speed(degrees_per_sec)

    def set_on_riffs_updated(self, callback: Optional[Callable[[Dict[str, Tuple[str, str]]], None]]):
        self._on_riffs_updated = callback

    # ── Properties for UI reading ──

    @property
    def bpm(self) -> float:
        with self._lock:
            return self._bpm

    @property
    def current_bar(self) -> int:
        with self._lock:
            return self._cycle.bar_index

    @property
    def is_fill(self) -> bool:
        with self._lock:
            return self._cycle.is_fill

    @property
    def current_groove_name(self) -> str:
        with self._lock:
            return self._cycle.groove_rudiment

    @property
    def cycle_bars(self) -> int:
        """Bars per riff-reselection cycle (fixed at 4)."""
        with self._lock:
            return self._cycle_bars

    @property
    def per_group_rudiments(self) -> Dict[str, Tuple[str, str]]:
        with self._lock:
            return dict(self._per_group_rudiments)

    # ── Audio feature input (called from analysis thread) ──

    def on_feature_frame(self, frame: LiveFeatureFrame):
        """Append a feature frame to the sliding window."""
        with self._lock:
            self._window.append(frame)

    # ── Engine tick (called from DMX thread at 30Hz) ──

    def start(self):
        """Start the engine cycle."""
        with self._lock:
            self._running = True
            self._engine_time = time.monotonic()
            self._start_new_cycle()
        self._flush_riffs_updated()

    def stop(self):
        """Stop the engine and clear all blocks."""
        with self._lock:
            self._running = False
            self._end_all_blocks()

    def tick(self, current_time: float):
        """Advance the engine. Called at 30Hz from DMX thread.

        Args:
            current_time: monotonic time
        """
        try:
            self._tick_locked(current_time)
        finally:
            self._flush_riffs_updated()

    def _tick_locked(self, current_time: float):
        with self._lock:
            if not self._running:
                return

            self._engine_time = current_time
            beat_duration = 60.0 / self._bpm
            bar_duration = 4.0 * beat_duration

            elapsed = current_time - self._cycle.cycle_start_time
            current_bar = int(elapsed / bar_duration)

            if current_bar >= self._cycle_bars:
                # Cycle complete → re-select riffs and loop. There's no
                # auto-fill bar at the end of the cycle anymore — the
                # engine just keeps grooving.
                self._end_all_blocks()
                self._start_new_cycle()
                return

            if current_bar != self._cycle.bar_index:
                # Bar boundary crossed
                self._cycle.bar_index = current_bar
                # Clear any transient force_fill state — fill lasts one
                # bar; once we cross into the next bar we go back to the
                # groove rudiment.
                self._cycle.is_fill = False

                # End previous bar blocks and start new ones
                self._end_all_blocks()
                bar_start = self._cycle.cycle_start_time + current_bar * bar_duration
                bar_end = bar_start + bar_duration
                self._create_all_blocks(bar_start, bar_end)

    def force_fill(self):
        """Punch a one-shot fill on the current bar.

        Sets ``is_fill`` so :meth:`_create_all_blocks` uses the fill
        rudiment for the current bar; ``tick`` clears the flag on the
        next bar boundary so we return to grooving without any cycle
        manipulation. The fill is purely a manual override now —
        nothing in the engine triggers it automatically.
        """
        with self._lock:
            if not self._running:
                return

            beat_duration = 60.0 / self._bpm
            bar_duration = 4.0 * beat_duration

            self._end_all_blocks()
            self._cycle.is_fill = True

            # Recreate the current bar's blocks using the fill rudiment.
            bar_start = (self._cycle.cycle_start_time
                         + self._cycle.bar_index * bar_duration)
            bar_end = bar_start + bar_duration
            self._create_all_blocks(bar_start, bar_end)

    # ── Internal methods ──

    def _start_new_cycle(self):
        """Select new riffs and start a fresh groove+fill cycle."""
        self._cycle.cycle_start_time = self._engine_time
        self._cycle.bar_index = 0
        self._cycle.is_fill = False
        self._movement_cycle_index += 1

        # Build profile from sliding window
        profile = self._build_window_profile()

        # Select riffs per group
        self._select_next_riffs(profile)

        # Update auto color from centroid
        self._update_auto_color(profile)

        # Create first bar blocks
        beat_duration = 60.0 / self._bpm
        bar_duration = 4.0 * beat_duration
        bar_start = self._cycle.cycle_start_time
        bar_end = bar_start + bar_duration
        self._create_all_blocks(bar_start, bar_end)

    def _build_window_profile(self) -> SectionAnalysis:
        """Synthesize a SectionAnalysis from the sliding window."""
        if not self._window:
            return SectionAnalysis(
                name="live", start_time=0.0, end_time=1.0,
                spectral_flux_avg=0.5, transient_sharpness=0.5,
                spectral_richness=0.5, vocal_presence=0.0,
                rms_energy=0.5, spectral_contrast_avg=0.5,
                spectral_centroid_avg=1000.0,
                spectral_flux_envelope=[0.5] * 32,
            )

        frames = list(self._window)
        flux_vals = [f.flux for f in frames]
        transient_vals = [f.transient for f in frames]
        richness_vals = [f.richness for f in frames]
        vocal_vals = [f.vocal for f in frames]
        centroid_hz_vals = [f.centroid_hz for f in frames]
        rms_vals = [f.rms for f in frames]
        contrast_vals = [f.contrast for f in frames]

        # Resample flux to 32-point envelope
        flux_arr = np.array(flux_vals, dtype=np.float32)
        if len(flux_arr) >= 32:
            indices = np.linspace(0, len(flux_arr) - 1, 32).astype(int)
            envelope = flux_arr[indices].tolist()
        else:
            envelope = flux_vals + [0.0] * (32 - len(flux_vals))

        return SectionAnalysis(
            name="live",
            start_time=0.0,
            end_time=float(len(frames)) / _FRAMES_PER_SEC,
            spectral_flux_avg=float(np.mean(flux_vals)),
            spectral_flux_envelope=envelope,
            transient_sharpness=float(np.mean(transient_vals)),
            spectral_richness=float(np.mean(richness_vals)),
            vocal_presence=float(np.mean(vocal_vals)),
            spectral_centroid_avg=float(np.mean(centroid_hz_vals)),  # real Hz, matches offline pipeline
            rms_energy=float(np.mean(rms_vals)),
            spectral_contrast_avg=float(np.mean(contrast_vals)),
        )

    def _select_next_riffs(self, profile: SectionAnalysis):
        """Use the autogen matcher to select riffs per group."""
        from rudiments.registry import get_intensity_rudiments

        scores = match_rudiments_to_section(
            profile, self._bpm,
            previous_section_rudiments=self._previous_rudiments,
            section_type="generic",
        )
        ranked = list(scores.keys())
        intensity_rudiments = get_intensity_rudiments()

        # Build allowed_per_group from constraints, handle locked groups separately
        allowed_per_group = {}
        locked_result = {}
        auto_groups = []

        for group_name in self._group_names:
            allowed = self._group_constraints.get(group_name)
            if allowed is None:
                # Unconstrained
                auto_groups.append(group_name)
            elif len(allowed) == 1:
                # Locked — force this riff, pick a fill from ranked
                forced = next(iter(allowed))
                forced_flux = intensity_rudiments[forced].average_flux if forced in intensity_rudiments else 0.5
                fill = forced  # fallback
                for candidate in ranked:
                    if candidate == forced:
                        continue
                    if intensity_rudiments[candidate].average_flux > forced_flux:
                        fill = candidate
                        break
                locked_result[group_name] = (forced, fill)
            else:
                # Curated — pass constraint to matcher
                auto_groups.append(group_name)
                allowed_per_group[group_name] = allowed

        # Select riffs for auto/curated groups via matcher
        if auto_groups:
            matcher_result = select_rudiments_per_group(
                profile, self._bpm, auto_groups,
                previous_section_rudiments=self._previous_rudiments,
                section_type="generic",
                allowed_per_group=allowed_per_group if allowed_per_group else None,
            )
        else:
            matcher_result = {}

        # Merge locked + matcher results
        self._per_group_rudiments = {**matcher_result, **locked_result}

        # Store for next cycle's contrast
        self._previous_rudiments = {
            g: r[0] for g, r in self._per_group_rudiments.items()
        }

        # Set cycle state from first group (for display)
        if self._per_group_rudiments:
            first = next(iter(self._per_group_rudiments.values()))
            self._cycle.groove_rudiment = first[0]
            self._cycle.fill_rudiment = first[1]

        # Queue the UI notification; the public entry points deliver it
        # once _lock is released (_flush_riffs_updated).
        self._pending_riffs = dict(self._per_group_rudiments)

    def _flush_riffs_updated(self):
        """Deliver a queued riff selection to the UI callback, OUTSIDE
        the engine lock. Called by start() and tick() after they release
        it."""
        if self._pending_riffs is None:
            return   # the common tick: nothing selected, no lock taken
        with self._lock:
            pending, self._pending_riffs = self._pending_riffs, None
        callback = self._on_riffs_updated
        if pending is None or callback is None:
            return
        try:
            callback(pending)
        except Exception:
            pass

    def _update_auto_color(self, profile: SectionAnalysis):
        """Generate color from spectral centroid."""
        # Map centroid (0-8000 Hz range) to hue (0-1)
        centroid_normalized = min(1.0, profile.spectral_centroid_avg / 8000.0)
        hue = centroid_normalized * 0.8  # Stay in 0-288 degree range (avoid wrapping red-red)
        saturation = 0.7 + 0.3 * profile.spectral_richness
        value = 0.8 + 0.2 * profile.rms_energy

        r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
        self._auto_color_rgb = (int(r * 255), int(g * 255), int(b * 255))

    def _get_color_for_block(self) -> Tuple[int, int, int]:
        """Get current color (override or auto)."""
        if self._color_override is not None:
            return self._color_override
        return self._auto_color_rgb

    def _create_all_blocks(self, bar_start: float, bar_end: float):
        """Create and register blocks for all groups for the current bar."""
        if not self._dmx_manager:
            return

        profile = self._build_window_profile()
        relative_energy = profile.rms_energy * self._energy_sensitivity

        # Spatial rules
        vocal_weights = apply_vocal_rule(self._group_classifications, profile.vocal_presence)
        richness_weights = compute_richness_weights(
            self._group_classifications, profile.spectral_richness,
            profile.spectral_flux_avg, relative_energy,
        )
        roles = assign_group_roles(
            self._per_group_rudiments, relative_energy, self._group_classifications,
        )
        gobo_prism = get_gobo_prism_groups(
            self._group_classifications, profile.spectral_richness,
        )

        color = self._get_color_for_block()

        for group_name in self._group_names:
            if group_name not in self._per_group_rudiments:
                continue

            groove_name, fill_name = self._per_group_rudiments[group_name]
            role = roles.get(group_name, ActivationRole.FULL)

            # Determine which rudiment to use this bar.
            #
            # FILL_ONLY semantics in continuous-groove mode: the engine
            # never auto-fills (is_fill is only set by manual FILL NOW),
            # so a strict skip would mute accent / SPIKE-envelope groups
            # for the entire session. Instead we play the punchier
            # ``fill_name`` rudiment and let the energy-threshold weight
            # from ``compute_richness_weights`` gate when the group
            # actually fires — accent at energy>=0.60, etc.
            if self._cycle.is_fill:
                if role == ActivationRole.GROOVE_ONLY:
                    continue  # Skip groove-only groups during manual fill
                rudiment_name = fill_name
            else:
                rudiment_name = fill_name if role == ActivationRole.FILL_ONLY else groove_name

            # Compute intensity with weights and submaster.
            # Richness weight drives activation (0.0 = muted by energy
            # threshold, 0.1-1.0 = active intensity); vocal weight is a
            # subtle modifier (compressed to 0.7-1.0 to avoid crushing
            # intensity); submaster is the user's per-group trim.
            base_weight = richness_weights.get(group_name, 1.0)
            vocal_raw = vocal_weights.get(group_name, 1.0)
            vocal_weight = 0.7 + 0.3 * vocal_raw  # compress 0-1 → 0.7-1.0
            submaster = self._group_submasters.get(group_name, 1.0)
            # FILL_ONLY groups must respect the raw weight (0.0 →
            # silent) — that's the whole point of the "accent" role.
            # Other groups get a 0.3 floor so they don't drop fully
            # dark at low energy, keeping the show visually present.
            if role == ActivationRole.FILL_ONLY:
                intensity = base_weight * vocal_weight * submaster
                if intensity <= 0.001:
                    continue
            else:
                intensity = max(0.3, base_weight) * vocal_weight * submaster

            # Create dimmer block
            params = {"intensity": intensity, "speed": 1.0}
            dimmer_block = rudiment_to_dimmer_block(
                rudiment_name, params, bar_start, bar_end,
            )

            # Create colour block
            colour_block = ColourBlock(
                start_time=bar_start,
                end_time=bar_end,
                red=color[0],
                green=color[1],
                blue=color[2],
            )

            # Get fixtures for this group
            group = self.config.groups.get(group_name)
            if not group:
                continue

            lane_key = f"live_{group_name}"

            # Register blocks with DMX manager
            self._dmx_manager.block_started(
                lane_key, group.fixtures, dimmer_block, 'dimmer', bar_start,
            )
            self._dmx_manager.block_started(
                lane_key, group.fixtures, colour_block, 'colour', bar_start,
            )
            self._active_lanes.add(lane_key)

            # Special blocks (gobo/prism)
            gp = gobo_prism.get(group_name, {})
            if gp.get("gobo") or gp.get("prism"):
                special_block = SpecialBlock(
                    start_time=bar_start,
                    end_time=bar_end,
                    gobo_index=3 if gp.get("gobo") else 0,
                    prism_enabled=gp.get("prism", False),
                )
                self._dmx_manager.block_started(
                    lane_key, group.fixtures, special_block, 'special', bar_start,
                )

            # Movement block for groups with moving heads
            gc = self._group_classifications.get(group_name)
            if gc and gc.has_moving_heads:
                # Select shape from energy-tiered pool, rotating across cycles
                if relative_energy >= 0.7:
                    pool = _HIGH_ENERGY_SHAPES
                elif relative_energy >= 0.4:
                    pool = _MEDIUM_ENERGY_SHAPES
                elif relative_energy >= 0.15:
                    pool = _LOW_ENERGY_SHAPES
                else:
                    pool = _VERY_LOW_SHAPES
                movement_name = pool[self._movement_cycle_index % len(pool)]

                amplitude = 25.0 + 55.0 * relative_energy
                speed = "1/2" if relative_energy < 0.4 else "1"
                mov_params = {
                    "amplitude": amplitude,
                    "speed": speed,
                }
                try:
                    plane_name = self._target_plane.name if self._target_plane else None
                    movement_block = rudiment_to_movement_block(
                        movement_name, mov_params, bar_start, bar_end,
                        target_plane_name=plane_name,
                    )
                    self._dmx_manager.block_started(
                        lane_key, group.fixtures, movement_block, 'movement', bar_start,
                    )
                except Exception:
                    pass  # Not all movement rudiments may be registered

    def _end_all_blocks(self):
        """Unregister all active blocks from DMXManager."""
        if not self._dmx_manager:
            return

        for lane_key in list(self._active_lanes):
            for block_type in ('dimmer', 'colour', 'movement', 'special'):
                try:
                    self._dmx_manager.block_ended(lane_key, block_type)
                except Exception:
                    pass

        self._active_lanes.clear()
