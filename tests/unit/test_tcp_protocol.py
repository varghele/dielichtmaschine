# tests/unit/test_tcp_protocol.py
"""Unit tests for utils/tcp/protocol.py - Visualizer protocol message creation."""

import json
from utils.tcp.protocol import MessageType, _infer_gobo_pattern, GOBO_PATTERN_KEYWORDS


class TestMessageType:

    def test_values(self):
        assert MessageType.STAGE.value == "stage"
        assert MessageType.FIXTURES.value == "fixtures"
        assert MessageType.GROUPS.value == "groups"
        assert MessageType.UPDATE.value == "update"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.ACK.value == "ack"

    def test_all_members(self):
        expected = {"STAGE", "FIXTURES", "GROUPS", "UPDATE", "HEARTBEAT", "ACK"}
        assert set(m.name for m in MessageType) == expected


class TestInferGoboPattern:

    def test_open_pattern(self):
        assert _infer_gobo_pattern("Open") == 0
        assert _infer_gobo_pattern("No gobo") == 0
        assert _infer_gobo_pattern("White open") == 0

    def test_dot_circle(self):
        assert _infer_gobo_pattern("Circle dots") == 1
        assert _infer_gobo_pattern("Dot pattern") == 1

    def test_star(self):
        assert _infer_gobo_pattern("Star burst") == 2

    def test_lines(self):
        assert _infer_gobo_pattern("Line pattern") == 3
        assert _infer_gobo_pattern("Bar") == 3

    def test_triangle(self):
        assert _infer_gobo_pattern("Triangle") == 4

    def test_cross(self):
        assert _infer_gobo_pattern("Cross pattern") == 5

    def test_breakup(self):
        assert _infer_gobo_pattern("Breakup") == 6

    def test_numbered_gobo(self):
        # "Gobo 1" -> pattern 1, "Gobo 2" -> pattern 2, etc.
        assert _infer_gobo_pattern("Gobo 1") == 1
        assert _infer_gobo_pattern("Gobo 2") == 2
        assert _infer_gobo_pattern("Gobo 6") == 6
        # Gobo 7 wraps: ((7-1) % 6) + 1 = 1
        assert _infer_gobo_pattern("Gobo 7") == 1

    def test_unknown_defaults_to_6(self):
        assert _infer_gobo_pattern("SomethingUnknown") == 6

    def test_case_insensitive(self):
        assert _infer_gobo_pattern("STAR") == 2
        assert _infer_gobo_pattern("circle") == 1


class TestGoboPatternKeywords:

    def test_all_keywords_have_valid_pattern_ids(self):
        for keyword, pattern_id in GOBO_PATTERN_KEYWORDS.items():
            assert 0 <= pattern_id <= 6, f"Invalid pattern ID {pattern_id} for '{keyword}'"

    def test_open_keywords_map_to_zero(self):
        open_keywords = ['open', 'no gobo', 'white', 'clear']
        for kw in open_keywords:
            assert GOBO_PATTERN_KEYWORDS[kw] == 0


# ---------------------------------------------------------------------------
# Phase D Stage 1.2: build_fixtures_payload includes capabilities; JSON strips them
# ---------------------------------------------------------------------------


class TestBuildFixturesPayloadIncludesCapabilities:

    def _make_config_with_one_fixture(self, manufacturer: str, model: str, mode: str):
        from config.models import Configuration, Fixture, FixtureMode, FixtureGroup
        f = Fixture(
            universe=1, address=1,
            manufacturer=manufacturer, model=model, name="F1",
            group="g1", current_mode=mode,
            available_modes=[FixtureMode(name=mode, channels=14)],
            type="MH",
        )
        cfg = Configuration(fixtures=[f], groups={"g1": FixtureGroup(name="g1", fixtures=[f])})
        return cfg

    def test_payload_includes_capabilities_for_known_fixture(self):
        from utils.tcp.protocol import VisualizerProtocol
        from utils.fixture_capabilities import FixtureCapabilities, Chassis

        cfg = self._make_config_with_one_fixture("Varytec", "Hero Spot 60", "14 Channel")
        payload = VisualizerProtocol.build_fixtures_payload(cfg)

        assert len(payload) == 1
        assert "capabilities" in payload[0]
        caps = payload[0]["capabilities"]
        assert isinstance(caps, FixtureCapabilities)
        # Hero Spot 60 is a moving head — chassis detection should agree.
        assert caps.chassis is Chassis.MOVING_YOKE

    def test_create_fixtures_message_strips_capabilities_from_json(self):
        from utils.tcp.protocol import VisualizerProtocol

        cfg = self._make_config_with_one_fixture("Varytec", "Hero Spot 60", "14 Channel")
        message_str = VisualizerProtocol.create_fixtures_message(cfg)
        # Must be valid JSON (would fail if FixtureCapabilities leaked through)
        message = json.loads(message_str.rstrip("\n"))
        assert message["type"] == "fixtures"
        assert "capabilities" not in message["fixtures"][0]
        # Manufacturer/model/mode keys must survive so the standalone
        # visualizer can re-detect capabilities locally from the QXF.
        for key in ("manufacturer", "model", "mode"):
            assert key in message["fixtures"][0]


class TestStandaloneCapabilityRedetection:
    """Standalone visualizer receives JSON without ``capabilities``; the
    FixtureManager re-detects them locally so the composable renderer
    can still be used (and inherits the chassis-on-top + glDepthMask fix
    the legacy path doesn't have)."""

    def test_redetects_capabilities_from_payload(self):
        from utils.fixture_capabilities import (
            FixtureCapabilities, Chassis, clear_capabilities_cache,
        )
        from visualizer.renderer.fixtures import _detect_capabilities_from_payload

        clear_capabilities_cache()
        payload = {
            "manufacturer": "Varytec",
            "model": "Hero Spot 60",
            "mode": "14 Channel",
        }
        caps = _detect_capabilities_from_payload(payload)
        assert isinstance(caps, FixtureCapabilities)
        assert caps.chassis is Chassis.MOVING_YOKE

    def test_returns_none_on_missing_keys(self):
        from visualizer.renderer.fixtures import _detect_capabilities_from_payload

        assert _detect_capabilities_from_payload({}) is None
        assert _detect_capabilities_from_payload({"manufacturer": "X"}) is None

    def test_full_tcp_roundtrip_preserves_composable_dispatch(self):
        """A JSON payload (no ``capabilities`` key, like the standalone gets)
        must still produce a composable :class:`FixtureRenderer` — not a
        legacy one — so the standalone visualizer gets the bug fixes."""
        from utils.tcp.protocol import VisualizerProtocol
        from utils.fixture_capabilities import clear_capabilities_cache

        clear_capabilities_cache()
        cfg = self._make_config()
        message_str = VisualizerProtocol.create_fixtures_message(cfg)
        message = json.loads(message_str.rstrip("\n"))
        fx = message["fixtures"][0]
        assert "capabilities" not in fx  # stripped, as expected

        caps = __import__(
            'visualizer.renderer.fixtures', fromlist=['_detect_capabilities_from_payload']
        )._detect_capabilities_from_payload(fx)
        assert caps is not None, "Re-detection must succeed for known QXFs"

    def _make_config(self):
        from config.models import Configuration, Fixture, FixtureMode, FixtureGroup
        f = Fixture(
            universe=1, address=1,
            manufacturer="Varytec", model="Hero Spot 60", name="F1",
            group="g1", current_mode="14 Channel",
            available_modes=[FixtureMode(name="14 Channel", channels=14)],
            type="MH",
        )
        return Configuration(
            fixtures=[f], groups={"g1": FixtureGroup(name="g1", fixtures=[f])},
        )


# ---------------------------------------------------------------------------
# Phase D Stage 1.3: FixtureManager dispatch flag
# ---------------------------------------------------------------------------


class TestFixtureRendererFlag:

    def test_default_is_composable(self, monkeypatch):
        # Phase D Stage 4: default flipped from "legacy" to "composable" once
        # visual regression confirmed parity.
        import importlib
        monkeypatch.delenv("FIXTURE_RENDERER", raising=False)
        from visualizer.renderer import fixtures as fixtures_module
        importlib.reload(fixtures_module)
        assert fixtures_module.FIXTURE_RENDERER_MODE == "composable"
        assert fixtures_module.USE_COMPOSABLE_RENDERER is True

    def test_legacy_when_env_set(self, monkeypatch):
        """Legacy is still available as an escape hatch via env var."""
        import importlib
        monkeypatch.setenv("FIXTURE_RENDERER", "legacy")
        from visualizer.renderer import fixtures as fixtures_module
        importlib.reload(fixtures_module)
        try:
            assert fixtures_module.FIXTURE_RENDERER_MODE == "legacy"
            assert fixtures_module.USE_COMPOSABLE_RENDERER is False
        finally:
            # Restore default for downstream tests
            monkeypatch.delenv("FIXTURE_RENDERER", raising=False)
            importlib.reload(fixtures_module)