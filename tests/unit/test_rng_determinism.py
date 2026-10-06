# tests/unit/test_rng_determinism.py
"""RNG determinism (v1.5.5 hardening, group G3).

Before: the live sparkle effect (effects/dimmer_effects.py, evaluated on
the 44 Hz arbiter thread) and the export sparkle paths
(utils/to_xml/unified_sequence.py, shows_to_xml.py) reseeded the GLOBAL
`random` module for every sample, clobbering the state any other code
(autogen, another thread) relied on. The master-preset sparkle chaser
(preset_scenes_to_xml.create_sparkle_chaser) drew from the global RNG
UNSEEDED, so a .qxw export was only reproducible when the caller seeded
the global RNG first (scripts/export_hash_check.py had to).

Now every random draw in effect/export code goes through a local
`random.Random` instance: the global RNG is never touched, and an
export is byte-identical whatever state the global RNG is in. The
per-sample values are unchanged (Random(seed).random() draws the same
number as seed() + random()), which the parity tests pin.
"""

import ast
import hashlib
import os
import random
from types import SimpleNamespace

import pytest

from config.models import Configuration, DimmerBlock
from effects.dimmer_effects import sparkle
from effects.types import DimmerContext
from utils.to_xml.preset_scenes_to_xml import create_sparkle_chaser
from utils.to_xml.unified_sequence import sample_dimmer_at_time


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Every Python file in the repo is production code except these trees:
# scripts and demo generators seed the global RNG on purpose.
EXCLUDED_DIRS = {"tests", "scripts", "demos", "profiling"}

GLOBAL_DRAWS = {"seed", "random", "randint", "randrange", "choice",
                "choices", "sample", "shuffle", "uniform", "gauss",
                "getrandbits", "triangular", "betavariate", "expovariate"}


def _md5_variation(seed_str):
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed_hash).random() * 0.7 + 0.3


def _ctx(**kw):
    base = dict(
        time_in_block=1.37, block_duration=8.0, intensity=255.0,
        speed_multiplier=1.0, bpm=120.0, fixture_index=0,
        total_fixtures=4, num_segments=3, fixture_name="Bar 1",
        block_start_time=0.0, is_segmented=True,
    )
    base.update(kw)
    return DimmerContext(**base)


@pytest.fixture
def seeded_global():
    """Seed the global RNG and hand back its state for comparison."""
    saved = random.getstate()
    random.seed(123456)
    yield random.getstate()
    random.setstate(saved)


class TestLiveSparkle:
    def test_does_not_touch_global_rng(self, seeded_global):
        sparkle(_ctx())
        assert random.getstate() == seeded_global

    def test_values_unchanged(self):
        ctx = _ctx()
        step_duration = 0.2 / ctx.speed_multiplier
        step_float = ctx.time_in_block / step_duration
        cur = int(step_float)
        t = step_float - cur
        smooth = t * t * (3 - 2 * t)
        expected = []
        for seg in range(ctx.num_segments):
            a = _md5_variation(f"{ctx.fixture_name}_seg{seg}_{cur}")
            b = _md5_variation(f"{ctx.fixture_name}_seg{seg}_{cur + 1}")
            expected.append(a + (b - a) * smooth)
        assert sparkle(ctx).segment_intensities == pytest.approx(expected)

    def test_independent_of_global_state(self):
        random.seed(1)
        first = sparkle(_ctx()).segment_intensities
        random.seed(2)
        second = sparkle(_ctx()).segment_intensities
        assert first == second


class TestExportSparkle:
    def _block(self):
        return DimmerBlock(start_time=0.0, end_time=8.0, intensity=255.0,
                           effect_type="sparkle", effect_speed="1")

    def test_does_not_touch_global_rng(self, seeded_global):
        sample_dimmer_at_time(1.37, [self._block()], 2, 4, 5, 40)
        assert random.getstate() == seeded_global

    def test_values_unchanged(self):
        time_s, fixture_idx = 1.37, 2
        step_float = time_s / 0.2
        cur = int(step_float)
        t = step_float - cur
        smooth = t * t * (3 - 2 * t)
        a = _md5_variation(f"fixture_{fixture_idx}_{cur}")
        b = _md5_variation(f"fixture_{fixture_idx}_{cur + 1}")
        expected = int(255 * (a + (b - a) * smooth))
        got = sample_dimmer_at_time(time_s, [self._block()], fixture_idx, 4, 5, 40)
        assert got == expected


class TestSparkleChaser:
    """The master-preset sparkle chaser picks its bright fixtures from a
    local fixed-seed RNG."""

    @pytest.fixture(autouse=True)
    def one_dimmer_channel_each(self, monkeypatch):
        import utils.to_xml.preset_scenes_to_xml as psx
        monkeypatch.setattr(
            psx, "get_fixture_channels_for_preset",
            lambda fixture, defs, presets: (
                {"IntensityDimmer": [fixture.channel]}, 1))

    def _build(self):
        import xml.etree.ElementTree as ET
        fixtures = [(i, SimpleNamespace(channel=i)) for i in range(12)]
        engine = ET.Element("Engine")
        create_sparkle_chaser(engine, 1, fixtures, {}, {})
        return ET.tostring(engine)

    def test_does_not_touch_global_rng(self, seeded_global):
        self._build()
        assert random.getstate() == seeded_global

    def test_same_scenes_under_different_global_seeds(self):
        saved = random.getstate()
        try:
            random.seed(1)
            a = self._build()
            random.seed(987654)
            b = self._build()
        finally:
            random.setstate(saved)
        assert a == b


class TestNoGlobalRngInProductionCode:
    """Guard: production code must draw from local random.Random instances."""

    def _offences(self, path):
        with open(path, encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=path)
            except SyntaxError:
                return []
        # Names bound to the random MODULE in this file (import random,
        # import random as rng_module).
        module_names = set()
        offences = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "random":
                        module_names.add(alias.asname or "random")
            elif (isinstance(node, ast.ImportFrom)
                    and node.module == "random"):
                # from random import random/choice/... binds a global draw
                offences += [f"{os.path.relpath(path, REPO_ROOT)}:"
                             f"{node.lineno} from random import {a.name}"
                             for a in node.names
                             if a.name in GLOBAL_DRAWS or a.name == "*"]
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in module_names
                    and node.func.attr in GLOBAL_DRAWS):
                offences.append(f"{os.path.relpath(path, REPO_ROOT)}:"
                                f"{node.lineno} {node.func.value.id}."
                                f"{node.func.attr}()")
        return offences

    def test_no_global_random_draws(self):
        offences = []
        for dirpath, dirs, files in os.walk(REPO_ROOT):
            if dirpath == REPO_ROOT:
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    offences += self._offences(os.path.join(dirpath, name))
        assert offences == [], "global RNG use:\n" + "\n".join(offences)


class TestExportReproducible:
    """A full .qxw export no longer depends on the global RNG state."""

    def _export(self, tmp_path, name):
        from utils.create_workspace import create_qlc_workspace
        config = Configuration.load(
            os.path.join(REPO_ROOT, "demos", "rigs", "club_band.lms"))
        out = tmp_path / f"{name}.qxw"
        create_qlc_workspace(config, {
            "generate_vc": True, "group_controls": True,
            "scene_presets": True, "movement_presets": True,
            "show_buttons": True, "speed_dial": True,
            "master_presets": True, "dark_mode": False,
        }, output_path=str(out))
        return out.read_bytes()

    def test_same_bytes_under_different_global_seeds(self, tmp_path):
        saved = random.getstate()
        try:
            random.seed(1)
            a = self._export(tmp_path, "a")
            random.seed(987654)
            b = self._export(tmp_path, "b")
        finally:
            random.setstate(saved)
        assert a == b

    def test_export_leaves_global_rng_alone(self, tmp_path, seeded_global):
        self._export(tmp_path, "c")
        assert random.getstate() == seeded_global
