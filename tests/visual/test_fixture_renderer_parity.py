"""Visual regression harness for legacy vs composable fixture renderer (Phase D Stage 3).

Renders each of the 6 fixtures in ``custom_fixtures/`` with both renderer
modes (``FIXTURE_RENDERER=legacy`` and ``FIXTURE_RENDERER=composable``)
into an offscreen ModernGL framebuffer, then compares RGB histograms.

The infrastructure stands alone — Stage 4 will tighten tolerances and
remove xfail markers as the composable renderer is tuned to legacy parity.

How it works:
1. Module-scoped standalone GL context (NVIDIA / Mesa via moderngl).
2. ``_render_with_mode`` flips ``FIXTURE_RENDERER`` env var, reloads
   ``visualizer.renderer.fixtures`` so ``USE_COMPOSABLE_RENDERER`` picks
   up the change, then constructs a FixtureManager + drives a render
   pass to a 256×256 RGBA framebuffer.
3. Histograms are 16-bin per-channel, normalized to total pixel count,
   so the L1 distance is in [0, 2] (sum of 3 channel diffs / 3 channels).

What the harness catches:
- Color regressions (wrong RGB on chassis, beam, or floor projection).
- Intensity regressions (wrong dimmer, wrong brightness scaling).
- Missing visual elements (e.g. beam disappears entirely, or new
  unintended bright pixels).

What the harness does NOT catch — handled by manual inspection in
Stage 4:
- Beam *spatial* misalignment. A beam shooting up vs sideways at
  full intensity produces the same set of colored pixels, just in
  different positions; the histogram is unchanged.
- Per-pixel structural differences (would need SSIM / block-mean
  comparison, deferred).

Known Stage 4 work that is *not* surfaced here:
- Composable beam cone is built along +Z with identity local_transform,
  so it emerges from the chassis origin pointing up rather than from
  the lens along the head's local +X. Floor projection is unaffected
  because it computes its own world transform.
- Static-chassis renderers (PAR / BAR cells) use simpler geometry
  than the legacy renderers; spatial layout differs, but colors match.
"""

from __future__ import annotations

import importlib
import os

import moderngl
import numpy as np
import pytest

from config.models import (
    Configuration,
    Fixture,
    FixtureGroup,
    FixtureMode,
    Universe,
)
from utils.fixture_capabilities import clear_capabilities_cache
from utils.tcp.protocol import VisualizerProtocol
from visualizer.renderer.camera import OrbitCamera


# ---------------------------------------------------------------------------
# Fixtures (pytest) — GL context, offscreen FBO
# ---------------------------------------------------------------------------


FBO_SIZE = 256


@pytest.fixture(scope="module")
def gl_context():
    """Module-scoped standalone moderngl context.

    On the dev machine this uses the NVIDIA / Mesa driver via WGL/GLX/CGL.
    If the environment can't create one (rare CI setups), the test module
    is skipped wholesale.
    """
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as e:  # pragma: no cover — environment-specific
        pytest.skip(f"Could not create standalone GL context: {e}")
    yield ctx
    ctx.release()


@pytest.fixture
def offscreen_fbo(gl_context):
    """Per-test offscreen framebuffer (color + depth)."""
    color = gl_context.texture((FBO_SIZE, FBO_SIZE), 4)
    depth = gl_context.depth_renderbuffer((FBO_SIZE, FBO_SIZE))
    fbo = gl_context.framebuffer(color_attachments=[color], depth_attachment=depth)
    yield fbo
    fbo.release()
    color.release()
    depth.release()


# ---------------------------------------------------------------------------
# Helpers — build a Configuration for one fixture, render with either mode
# ---------------------------------------------------------------------------


def _make_single_fixture_config(
    manufacturer: str,
    model: str,
    mode_name: str,
    channels: int,
    *,
    legacy_type: str = "PAR",
) -> Configuration:
    """A minimal Configuration with one fixture, one group, one universe."""
    f = Fixture(
        universe=1,
        address=1,
        manufacturer=manufacturer,
        model=model,
        name="F1",
        group="g1",
        current_mode=mode_name,
        available_modes=[FixtureMode(name=mode_name, channels=channels)],
        type=legacy_type,
        x=0.0,
        y=0.0,
        z=3.0,
        mounting="hanging",
        yaw=0.0,
        pitch=90.0,  # hanging — fixture points down
        roll=0.0,
        orientation_uses_group_default=False,
        z_uses_group_default=False,
    )
    return Configuration(
        fixtures=[f],
        groups={"g1": FixtureGroup(name="g1", fixtures=[f], default_z_height=3.0)},
        universes={1: Universe(id=1, name="Universe 1", output={})},
        stage_width=10.0,
        stage_height=6.0,
    )


def _render_with_mode(
    ctx: moderngl.Context,
    fbo,
    config: Configuration,
    dmx_data: bytes,
    *,
    renderer_mode: str,
) -> np.ndarray:
    """Build a FixtureManager in the given mode, render once, return the pixels."""
    # Flip the env var and reload so module-level USE_COMPOSABLE_RENDERER is fresh.
    os.environ["FIXTURE_RENDERER"] = renderer_mode
    from visualizer.renderer import fixtures as fixtures_module
    importlib.reload(fixtures_module)

    # Camera mimics the visualizer's default view.
    camera = OrbitCamera()
    camera.set_aspect(1.0)  # Square FBO
    camera.set_stage_size(config.stage_width, config.stage_height)
    mvp = camera.get_view_projection_matrix()

    fm = fixtures_module.FixtureManager(ctx)

    # Make sure capabilities cache isn't holding stale data across fixtures.
    clear_capabilities_cache()
    payload = VisualizerProtocol.build_fixtures_payload(config)
    fm.update_fixtures(payload)
    fm.update_dmx(universe=1, dmx_data=dmx_data)

    fbo.use()
    ctx.viewport = (0, 0, FBO_SIZE, FBO_SIZE)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.clear(0.05, 0.05, 0.10, 1.0)  # dark blue-grey background
    fm.render(mvp)

    raw = fbo.read(components=3, dtype="f1")
    image = np.frombuffer(raw, dtype="u1").reshape(FBO_SIZE, FBO_SIZE, 3)

    fm.release()
    return image.copy()  # detach from the buffer


# ---------------------------------------------------------------------------
# Histogram comparison
# ---------------------------------------------------------------------------


def _histogram(image: np.ndarray, bins: int = 16) -> np.ndarray:
    """Normalized per-channel histogram with shape (3, bins)."""
    out = np.zeros((3, bins), dtype=np.float64)
    pixel_count = image.shape[0] * image.shape[1]
    for ch in range(3):
        h, _ = np.histogram(image[:, :, ch], bins=bins, range=(0, 256))
        out[ch] = h / pixel_count
    return out


def histogram_l1_distance(a: np.ndarray, b: np.ndarray) -> float:
    """L1 distance between two normalized RGB histograms.

    Each channel histogram sums to 1.0, so per-channel L1 diff is in [0, 2].
    Average across 3 channels → returned value in [0, 2].
    """
    return float(np.abs(a - b).sum() / 3.0)


def _block_means(image: np.ndarray, blocks: int = 8) -> np.ndarray:
    """Average RGB per ``blocks × blocks`` grid cell. Spatial-sensitive.

    Returns array of shape (blocks, blocks, 3) of float64 mean values
    in [0, 255]. Detects regressions like "beam now appears top-left
    instead of bottom-right" that histograms miss.
    """
    h, w = image.shape[:2]
    bh, bw = h // blocks, w // blocks
    out = np.zeros((blocks, blocks, 3), dtype=np.float64)
    for r in range(blocks):
        for c in range(blocks):
            tile = image[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw, :]
            out[r, c] = tile.mean(axis=(0, 1))
    return out


def block_mean_distance(a: np.ndarray, b: np.ndarray) -> float:
    """RMS difference between block means, normalized to [0, 1].

    Each block contributes its per-channel mean difference; we square,
    average, sqrt, then divide by 255 so the result is unitless.
    """
    diff = (a - b) / 255.0
    return float(np.sqrt((diff ** 2).mean()))


# ---------------------------------------------------------------------------
# Test cases — one per custom_fixture, all channels at 255
# ---------------------------------------------------------------------------


FIXTURE_CASES = [
    pytest.param("Varytec", "Hero Spot 60", "14 Channel", 14, "MH",
                 id="hero-spot-60-14ch"),
    pytest.param("Varytec", "Giga Bar 5 LED RGBW", "5 Channels", 5, "BAR",
                 id="giga-bar-5ch"),
    pytest.param("Showtec", "Sunstrip Active", "10 Channels Mode", 10, "SUNSTRIP",
                 id="sunstrip-10ch"),
    pytest.param("Varghele", "LED BAR", "40 Channels Mode", 40, "PIXELBAR",
                 id="varghele-led-bar-40ch"),
    pytest.param("Stairville", "Wild Wash Pro 648 RGB LED", "6 Channel", 6, "WASH",
                 id="wild-wash-648-6ch"),
    pytest.param("Stairville", "Retro Flat Par 18x12W RGBW ", "8 Channel", 8, "PAR",
                 id="retro-flat-par-8ch"),
    # Phase E archetype unlocks — real QXFs added to custom_fixtures/.
    pytest.param("Martin", "MAC Aura", "Standard", 14, "MH",
                 id="mac-aura-standard-moving-wash"),
    pytest.param("Ayrton", "MagicBlade-R", "Ex (44ch)", 44, "MH",
                 id="magicblade-r-ex-moving-cell-bar"),
    pytest.param("Stairville", "LED Matrix Blinder 5x5", "26-Channel", 26, "PIXELBAR",
                 id="led-matrix-blinder-5x5-26ch"),
]


# Tolerances chosen to fire on regressions but tolerate AA / blend / driver-
# version drift AND two known intentional divergences:
#
# 1. Stage 4's beam-origin fix — the composable cone emerges from the
#    proper lens position; lens emissive bleeds slightly more into the
#    beam region for moving heads.
# 2. The chassis-on-top two-pass + real glDepthMask fix (May 2026) — the
#    composable chassis silhouette renders opaque on top of the beam
#    contribution instead of being additively brightened by it, which is
#    visually correct (user-reported "fixtures vanishing under beams")
#    but diverges from legacy at the lens area, especially for moving
#    washes like the MAC Aura.
#
# Observed maxes across all archetype + legacy fixtures at full-DMX
# (after the Option B chassis port — most fixtures now match legacy
# tightly; only the moving wash still diverges at the lens area):
#   histogram L1:   0.136  (Martin MAC Aura Standard — moving wash)
#   block-mean RMS: 0.078  (Martin MAC Aura Standard — chassis-on-top fix)
HISTOGRAM_TOLERANCE = 0.15
BLOCK_MEAN_TOLERANCE = 0.085


@pytest.mark.parametrize(
    "manufacturer,model,mode,channels,legacy_type",
    FIXTURE_CASES,
)
def test_renderer_parity_full_intensity(
    gl_context,
    offscreen_fbo,
    manufacturer: str,
    model: str,
    mode: str,
    channels: int,
    legacy_type: str,
):
    """Render the fixture with every channel at 255 in both modes; compare histograms."""
    config = _make_single_fixture_config(
        manufacturer, model, mode, channels, legacy_type=legacy_type,
    )
    dmx = bytes([255] * 512)

    legacy = _render_with_mode(gl_context, offscreen_fbo, config, dmx, renderer_mode="legacy")
    composable = _render_with_mode(gl_context, offscreen_fbo, config, dmx, renderer_mode="composable")

    hist_a = _histogram(legacy)
    hist_b = _histogram(composable)
    hist_dist = histogram_l1_distance(hist_a, hist_b)

    blocks_a = _block_means(legacy)
    blocks_b = _block_means(composable)
    block_dist = block_mean_distance(blocks_a, blocks_b)

    # Diagnostic line — pytest captures it for surfacing on failure.
    print(
        f"[{manufacturer}/{model}/{mode}] "
        f"hist L1={hist_dist:.4f}, block RMS={block_dist:.4f}"
    )

    assert hist_dist <= HISTOGRAM_TOLERANCE, (
        f"Histogram divergence too large: {hist_dist:.4f} > {HISTOGRAM_TOLERANCE} "
        f"({manufacturer} {model}, mode={mode})"
    )
    assert block_dist <= BLOCK_MEAN_TOLERANCE, (
        f"Block-mean divergence too large: {block_dist:.4f} > {BLOCK_MEAN_TOLERANCE} "
        f"({manufacturer} {model}, mode={mode})"
    )


# ---------------------------------------------------------------------------
# Sanity tests — the harness itself produces consistent output (no xfail)
# ---------------------------------------------------------------------------


def test_blackout_renders_only_background(gl_context, offscreen_fbo):
    """With all-zero DMX, both renderers should produce ~background-only output.

    This is a smoke test for the harness itself: confirms the GL context,
    offscreen FBO, payload pipeline, and renderer-mode toggle all work
    end-to-end. No xfail because background fill is independent of fixture
    rendering quirks.
    """
    config = _make_single_fixture_config(
        "Varytec", "Hero Spot 60", "14 Channel", 14, legacy_type="MH",
    )
    dmx = bytes(512)  # all zero

    legacy = _render_with_mode(gl_context, offscreen_fbo, config, dmx, renderer_mode="legacy")
    composable = _render_with_mode(gl_context, offscreen_fbo, config, dmx, renderer_mode="composable")

    # Background is (0.05, 0.05, 0.10) → uint8 (12, 12, 25). Most pixels should
    # match this (the chassis itself is dark too). Histograms should be very close.
    hist_a = _histogram(legacy)
    hist_b = _histogram(composable)
    distance = histogram_l1_distance(hist_a, hist_b)
    print(f"[blackout] histogram L1 distance: {distance:.4f}")

    # With matching chassis compound geometry the histograms should be very
    # close. Observed first-run distance was 0.0003; 0.05 catches regressions.
    assert distance <= 0.05, f"Blackout divergence unexpectedly large: {distance:.4f}"


def test_renderer_flag_module_reload_picks_up_change(gl_context, offscreen_fbo):
    """Confirm the importlib.reload pattern actually flips USE_COMPOSABLE_RENDERER."""
    config = _make_single_fixture_config(
        "Varytec", "Hero Spot 60", "14 Channel", 14, legacy_type="MH",
    )
    dmx = bytes(512)
    _render_with_mode(gl_context, offscreen_fbo, config, dmx, renderer_mode="legacy")
    from visualizer.renderer import fixtures as fm_after_legacy
    assert fm_after_legacy.USE_COMPOSABLE_RENDERER is False

    _render_with_mode(gl_context, offscreen_fbo, config, dmx, renderer_mode="composable")
    from visualizer.renderer import fixtures as fm_after_composable
    assert fm_after_composable.USE_COMPOSABLE_RENDERER is True

    # Restore default for downstream tests.
    os.environ.pop("FIXTURE_RENDERER", None)
    importlib.reload(fm_after_composable)
