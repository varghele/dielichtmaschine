#!/usr/bin/env python3
"""
Profiling script to identify performance bottlenecks in playback.

Run this to see where time is being spent during show playback.
"""

import sys
import time
import cProfile
import pstats
import io
from functools import wraps
from collections import defaultdict

# Timing statistics
_timings = defaultdict(lambda: {'count': 0, 'total': 0.0, 'max': 0.0})
_enabled = False


def enable_profiling():
    """Enable timing collection."""
    global _enabled
    _enabled = True
    print("Playback profiling ENABLED")


def disable_profiling():
    """Disable timing collection."""
    global _enabled
    _enabled = False


def reset_timings():
    """Reset all timing statistics."""
    global _timings, _latency_buckets, _last_timer_time, _last_artnet_time
    _timings.clear()
    _latency_buckets = {'<20ms': 0, '20-50ms': 0, '50-100ms': 0, '100-200ms': 0, '>200ms': 0}
    _last_timer_time = None
    _last_artnet_time = None


def timed(name=None):
    """Decorator to time a function."""
    def decorator(func):
        func_name = name or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _enabled:
                return func(*args, **kwargs)

            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings[func_name]
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)

        return wrapper
    return decorator


def print_timings(min_total_ms=1.0):
    """Print timing statistics."""
    if not _timings:
        print("No timing data collected. Make sure profiling is enabled.")
        return

    print("\n" + "="*80)
    print("PLAYBACK TIMING REPORT")
    print("="*80)
    print(f"{'Function':<50} {'Calls':>8} {'Total(ms)':>10} {'Avg(ms)':>10} {'Max(ms)':>10}")
    print("-"*80)

    # Sort by total time descending
    sorted_timings = sorted(_timings.items(), key=lambda x: x[1]['total'], reverse=True)

    for func_name, stats in sorted_timings:
        total_ms = stats['total'] * 1000
        if total_ms < min_total_ms:
            continue
        avg_ms = total_ms / stats['count'] if stats['count'] > 0 else 0
        max_ms = stats['max'] * 1000

        # Truncate long names
        display_name = func_name[-50:] if len(func_name) > 50 else func_name
        print(f"{display_name:<50} {stats['count']:>8} {total_ms:>10.2f} {avg_ms:>10.3f} {max_ms:>10.3f}")

    print("="*80)

    # Print latency distribution if available
    global _latency_buckets
    if any(_latency_buckets.values()):
        print("\nEVENT LOOP LATENCY DISTRIBUTION:")
        total = sum(_latency_buckets.values())
        for bucket, count in _latency_buckets.items():
            pct = (count / total * 100) if total > 0 else 0
            bar = '#' * int(pct / 2)
            print(f"  {bucket:>10}: {count:>5} ({pct:>5.1f}%) {bar}")
        print()


def profile_for_seconds(seconds=10):
    """Run profiling for a specified number of seconds, then print report."""
    enable_profiling()
    reset_timings()
    print(f"Profiling for {seconds} seconds... Play your show now!")
    time.sleep(seconds)
    disable_profiling()
    print_timings()


# Monkey-patch key functions to add timing
def patch_shows_tab():
    """Patch ShowsTab methods with timing."""
    try:
        from gui.tabs.shows_tab import ShowsTab

        original_update_playback = ShowsTab._update_playback
        def timed_update_playback(self):
            if not _enabled:
                return original_update_playback(self)
            start = time.perf_counter()
            try:
                return original_update_playback(self)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['ShowsTab._update_playback']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        ShowsTab._update_playback = timed_update_playback

        print("Patched ShowsTab._update_playback")
    except Exception as e:
        print(f"Could not patch ShowsTab: {e}")


def patch_artnet_controller():
    """Patch output path methods with timing (arbiter pass: the layer
    render + block scheduling on the controller, the merge-and-send
    tick on the arbiter)."""
    try:
        from utils.artnet.arbiter import OutputArbiter
        from utils.artnet.shows_artnet_controller import ShowsArtNetController

        # Patch the playback layer render
        original_render = ShowsArtNetController.render
        def timed_render(self, now):
            if not _enabled:
                return original_render(self, now)
            start = time.perf_counter()
            try:
                return original_render(self, now)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['ArtNet.render']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        ShowsArtNetController.render = timed_render

        # Patch _process_lane_blocks
        original_process = ShowsArtNetController._process_lane_blocks
        def timed_process(self):
            if not _enabled:
                return original_process(self)
            start = time.perf_counter()
            try:
                return original_process(self)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['ArtNet._process_lane_blocks']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        ShowsArtNetController._process_lane_blocks = timed_process

        # Patch the arbiter tick (render + merge + send)
        original_tick = OutputArbiter.tick_once
        def timed_tick(self, now):
            if not _enabled:
                return original_tick(self, now)
            start = time.perf_counter()
            try:
                return original_tick(self, now)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['Arbiter.tick_once']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        OutputArbiter.tick_once = timed_tick

        print("Patched ShowsArtNetController/OutputArbiter methods")
    except Exception as e:
        print(f"Could not patch ArtNet controller: {e}")


def patch_dmx_manager():
    """Patch DMX manager methods with timing."""
    try:
        from utils.artnet.dmx_manager import DMXManager

        # Patch update_dmx
        original_update = DMXManager.update_dmx
        def timed_update(self, current_time):
            if not _enabled:
                return original_update(self, current_time)
            start = time.perf_counter()
            try:
                return original_update(self, current_time)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['DMXManager.update_dmx']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        DMXManager.update_dmx = timed_update

        # Patch clear_all_dmx
        original_clear = DMXManager.clear_all_dmx
        def timed_clear(self):
            if not _enabled:
                return original_clear(self)
            start = time.perf_counter()
            try:
                return original_clear(self)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['DMXManager.clear_all_dmx']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        DMXManager.clear_all_dmx = timed_clear

        # Patch _set_safe_idle_state
        original_idle = DMXManager._set_safe_idle_state
        def timed_idle(self):
            if not _enabled:
                return original_idle(self)
            start = time.perf_counter()
            try:
                return original_idle(self)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['DMXManager._set_safe_idle_state']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        DMXManager._set_safe_idle_state = timed_idle

        print("Patched DMXManager methods")
    except Exception as e:
        print(f"Could not patch DMX manager: {e}")


def patch_timeline_widgets():
    """Patch timeline widget methods with timing."""
    try:
        from timeline_ui.light_lane_widget import LightLaneWidget

        original_set_playhead = LightLaneWidget.set_playhead_position
        def timed_set_playhead(self, position):
            if not _enabled:
                return original_set_playhead(self, position)
            start = time.perf_counter()
            try:
                return original_set_playhead(self, position)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['LightLaneWidget.set_playhead_position']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        LightLaneWidget.set_playhead_position = timed_set_playhead

        print("Patched LightLaneWidget.set_playhead_position")
    except Exception as e:
        print(f"Could not patch timeline widgets: {e}")


def patch_paint_events():
    """Patch paintEvent methods to measure actual rendering time.

    NOTE: Disabled due to Qt/Python interaction issues causing crashes.
    The event loop latency tracking provides the key metric instead.
    """
    print("Paint event patching disabled (use EVENT_LOOP_LATENCY instead)")


# Track event loop latency
_last_timer_time = None
_last_artnet_time = None
_latency_buckets = {'<20ms': 0, '20-50ms': 0, '50-100ms': 0, '100-200ms': 0, '>200ms': 0}

def patch_event_loop_latency():
    """Measure time between consecutive timer callbacks to detect event loop blocking."""
    try:
        from gui.tabs.shows_tab import ShowsTab

        original_update_playback = ShowsTab._update_playback
        def latency_update_playback(self):
            global _last_timer_time, _latency_buckets
            if _enabled and _last_timer_time is not None:
                latency = time.perf_counter() - _last_timer_time
                latency_ms = latency * 1000
                stats = _timings['EVENT_LOOP_LATENCY']
                stats['count'] += 1
                stats['total'] += latency
                stats['max'] = max(stats['max'], latency)
                # Track distribution
                if latency_ms < 20:
                    _latency_buckets['<20ms'] += 1
                elif latency_ms < 50:
                    _latency_buckets['20-50ms'] += 1
                elif latency_ms < 100:
                    _latency_buckets['50-100ms'] += 1
                elif latency_ms < 200:
                    _latency_buckets['100-200ms'] += 1
                else:
                    _latency_buckets['>200ms'] += 1
            _last_timer_time = time.perf_counter()
            return original_update_playback(self)
        ShowsTab._update_playback = latency_update_playback

        print("Patched event loop latency tracking")
    except Exception as e:
        print(f"Could not patch event loop latency: {e}")


def patch_artnet_timer_latency():
    """Measure arbiter tick-to-tick latency separately."""
    try:
        from utils.artnet.arbiter import OutputArbiter

        original_tick = OutputArbiter.tick_once
        def latency_tick(self, now):
            global _last_artnet_time
            if _enabled and _last_artnet_time is not None:
                latency = time.perf_counter() - _last_artnet_time
                stats = _timings['ARTNET_THREAD_LATENCY']
                stats['count'] += 1
                stats['total'] += latency
                stats['max'] = max(stats['max'], latency)
            _last_artnet_time = time.perf_counter()
            return original_tick(self, now)
        OutputArbiter.tick_once = latency_tick

        print("Patched arbiter tick latency tracking")
    except Exception as e:
        print(f"Could not patch arbiter tick latency: {e}")


def patch_target_resolver():
    """Patch target resolver with timing."""
    try:
        import utils.target_resolver as resolver

        original_resolve = resolver.resolve_targets_unique
        def timed_resolve(targets, config):
            if not _enabled:
                return original_resolve(targets, config)
            start = time.perf_counter()
            try:
                return original_resolve(targets, config)
            finally:
                elapsed = time.perf_counter() - start
                stats = _timings['resolve_targets_unique']
                stats['count'] += 1
                stats['total'] += elapsed
                stats['max'] = max(stats['max'], elapsed)
        resolver.resolve_targets_unique = timed_resolve

        print("Patched resolve_targets_unique")
    except Exception as e:
        print(f"Could not patch target resolver: {e}")


def install_all_patches():
    """Install all timing patches."""
    print("\n" + "="*60)
    print("INSTALLING PROFILING PATCHES")
    print("="*60)
    patch_shows_tab()
    patch_event_loop_latency()  # Must come after patch_shows_tab
    patch_artnet_controller()
    patch_artnet_timer_latency()  # Must come after patch_artnet_controller
    patch_dmx_manager()
    patch_timeline_widgets()
    patch_paint_events()  # Disabled - use EVENT_LOOP_LATENCY instead
    patch_target_resolver()
    print("="*60 + "\n")


if __name__ == "__main__":
    print("""
Playback Profiler
=================

To use this profiler:

1. In your main.py, add BEFORE creating the application:

   import profile_playback
   profile_playback.install_all_patches()

2. When you want to start profiling (e.g., add a button or menu item):

   import profile_playback
   profile_playback.enable_profiling()
   profile_playback.reset_timings()

3. Play your show for 10-30 seconds

4. Stop and print results:

   profile_playback.disable_profiling()
   profile_playback.print_timings()

Or use the convenience function:

   profile_playback.profile_for_seconds(10)
""")
