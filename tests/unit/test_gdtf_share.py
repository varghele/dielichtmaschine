# tests/unit/test_gdtf_share.py
"""GDTF Share Phase 4 (ROADMAP v1.4): utils/gdtf_share client (login,
cached catalog, ranked search, download), the credential rules
(username in QSettings, password only via keyring, never plaintext),
the browse/download pane, the fixture-browser Share tab with rescan,
and the Settings account dialog. Everything runs against a fake HTTP
session and a fake keyring module - no network, no OS vault.
"""

import json
import os
import sys
import types

import pytest

from utils import gdtf_share
from utils.gdtf_share import GDTFShareClient, GDTFShareError, entry_filename

PK = b"PK\x03\x04gdtf-bytes"


class FakeResponse:
    def __init__(self, payload=None, content=b"", status=200):
        self._payload = payload
        self.content = content
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Routes by endpoint name; records every call."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def _respond(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        handler = self.routes.get(endpoint)
        if handler is None:
            raise RuntimeError(f"unexpected call to {endpoint}")
        return handler(**kwargs) if callable(handler) else handler

    def post(self, url, **kwargs):
        return self._respond(url.rsplit("/", 1)[-1], **kwargs)

    def get(self, url, **kwargs):
        return self._respond(url.rsplit("/", 1)[-1], **kwargs)


def catalog_entries():
    return [
        {"rid": 1, "manufacturer": "Ayrton", "fixture": "MagicBlade R",
         "uploader": "Ayrton", "rating": "4.5", "lastModified": 100,
         "modes": [{"name": "Standard", "dmxfootprint": 15}]},
        {"rid": 2, "manufacturer": "Ayrton", "fixture": "MagicBlade R",
         "uploader": "user", "rating": "5.0", "lastModified": 200,
         "modes": []},
        {"rid": 3, "manufacturer": "Martin", "fixture": "MAC Aura",
         "uploader": "user", "rating": "3.0", "lastModified": 50,
         "modes": [{"name": "Std", "dmxfootprint": 25},
                   {"name": "Ext", "dmxfootprint": 31}]},
    ]


def make_client(tmp_path, routes=None, clock=lambda: 1_000_000.0):
    session = FakeSession(routes)
    client = GDTFShareClient(session=session,
                             cache_path=str(tmp_path / "catalog.json"),
                             clock=clock)
    return client, session


LOGIN_OK = FakeResponse({"result": True})


@pytest.fixture
def fake_keyring(monkeypatch):
    """A keyring stand-in so no test ever touches the OS vault."""
    store = {}
    mod = types.ModuleType("keyring")
    mod.get_password = lambda service, user: store.get((service, user))
    mod.set_password = (
        lambda service, user, pw: store.__setitem__((service, user), pw))
    mod.delete_password = (
        lambda service, user: store.pop((service, user), None))
    mod.get_keyring = lambda: object()
    fail_mod = types.ModuleType("keyring.backends.fail")
    fail_mod.Keyring = type("Keyring", (), {})
    backends = types.ModuleType("keyring.backends")
    backends.fail = fail_mod
    mod.backends = backends
    monkeypatch.setitem(sys.modules, "keyring", mod)
    monkeypatch.setitem(sys.modules, "keyring.backends", backends)
    monkeypatch.setitem(sys.modules, "keyring.backends.fail", fail_mod)
    return store


@pytest.fixture(autouse=True)
def _clean_share_settings():
    gdtf_share.store_username("")
    yield
    gdtf_share.store_username("")


# ── client ──────────────────────────────────────────────────────────────


class TestLogin:
    def test_success_opens_the_session(self, tmp_path):
        client, session = make_client(tmp_path, {"login.php": LOGIN_OK})
        client.login("u", "p")
        assert client.logged_in
        assert session.calls[0][1]["data"] == {"user": "u", "password": "p"}

    def test_rejection_raises_with_the_api_message(self, tmp_path):
        client, _ = make_client(tmp_path, {"login.php": FakeResponse(
            {"result": False, "error": "Wrong password"})})
        with pytest.raises(GDTFShareError, match="Wrong password"):
            client.login("u", "p")
        assert not client.logged_in

    def test_network_error_raises_share_error(self, tmp_path):
        def boom(**kwargs):
            raise OSError("no route to host")
        client, _ = make_client(tmp_path, {"login.php": boom})
        with pytest.raises(GDTFShareError, match="Cannot reach"):
            client.login("u", "p")

    def test_empty_credentials_never_hit_the_network(self, tmp_path):
        client, session = make_client(tmp_path)
        with pytest.raises(GDTFShareError):
            client.login("", "")
        assert session.calls == []


class TestCatalog:
    def test_fetches_and_writes_the_cache(self, tmp_path):
        client, session = make_client(tmp_path, {"getList.php": FakeResponse(
            {"result": True, "list": catalog_entries()})})
        entries = client.catalog()
        assert len(entries) == 3
        with open(tmp_path / "catalog.json", encoding="utf-8") as f:
            assert len(json.load(f)) == 3

    def test_fresh_cache_serves_without_network(self, tmp_path):
        (tmp_path / "catalog.json").write_text(
            json.dumps(catalog_entries()), encoding="utf-8")
        client, session = make_client(tmp_path)  # any call would raise
        assert len(client.catalog()) == 3
        assert session.calls == []

    def test_stale_cache_refetches(self, tmp_path):
        cache = tmp_path / "catalog.json"
        cache.write_text("[]", encoding="utf-8")
        stale_clock = lambda: cache.stat().st_mtime + 25 * 3600
        client, session = make_client(
            tmp_path,
            {"getList.php": FakeResponse(
                {"result": True, "list": catalog_entries()})},
            clock=stale_clock)
        assert len(client.catalog()) == 3
        assert session.calls  # went to the network

    def test_offline_falls_back_to_the_stale_cache(self, tmp_path):
        cache = tmp_path / "catalog.json"
        cache.write_text(json.dumps(catalog_entries()), encoding="utf-8")

        def boom(**kwargs):
            raise OSError("offline")
        client, _ = make_client(
            tmp_path, {"getList.php": boom},
            clock=lambda: cache.stat().st_mtime + 25 * 3600)
        assert len(client.catalog()) == 3

    def test_offline_without_cache_raises(self, tmp_path):
        def boom(**kwargs):
            raise OSError("offline")
        client, _ = make_client(tmp_path, {"getList.php": boom})
        with pytest.raises(GDTFShareError):
            client.catalog()

    def test_load_cached_catalog_never_touches_the_network(self, tmp_path):
        client, session = make_client(tmp_path)
        assert client.load_cached_catalog() is None
        assert session.calls == []


class TestSearch:
    def _client(self, tmp_path):
        (tmp_path / "catalog.json").write_text(
            json.dumps(catalog_entries()), encoding="utf-8")
        client, _ = make_client(tmp_path)
        return client

    def test_every_word_must_match_across_both_fields(self, tmp_path):
        client = self._client(tmp_path)
        assert [e["rid"] for e in client.search("ayrton blade")] == [1, 2]
        assert client.search("ayrton aura") == []

    def test_manufacturer_upload_outranks_user_rating(self, tmp_path):
        client = self._client(tmp_path)
        # rid 2 has the better rating but is a user upload
        assert [e["rid"] for e in client.search("magicblade")] == [1, 2]

    def test_empty_term_returns_the_whole_catalog_ranked(self, tmp_path):
        client = self._client(tmp_path)
        assert len(client.search("")) == 3

    def test_limit(self, tmp_path):
        client = self._client(tmp_path)
        assert len(client.search("", limit=1)) == 1


class TestDownload:
    def test_writes_the_revision_pinned_file(self, tmp_path):
        client, _ = make_client(tmp_path, {"downloadFile.php": FakeResponse(
            content=PK)})
        entry = catalog_entries()[0]
        path = client.download(entry, str(tmp_path / "dest"))
        assert path.endswith("Ayrton@MagicBlade R@rid1.gdtf")
        with open(path, "rb") as f:
            assert f.read() == PK

    def test_non_zip_response_raises(self, tmp_path):
        client, _ = make_client(tmp_path, {"downloadFile.php": FakeResponse(
            content=b"<html>login required</html>")})
        with pytest.raises(GDTFShareError, match="did not return"):
            client.download(catalog_entries()[0], str(tmp_path))
        assert not list(tmp_path.glob("*.gdtf"))

    def test_filename_sanitizes_hostile_names(self):
        name = entry_filename({"rid": 9, "manufacturer": "A/B:C",
                               "fixture": "..\\evil"})
        assert "/" not in name and "\\" not in name and ":" not in name
        assert name.endswith("@rid9.gdtf")


class TestCredentials:
    def test_username_round_trip(self):
        gdtf_share.store_username("lichtwart")
        assert gdtf_share.stored_username() == "lichtwart"
        gdtf_share.store_username("")
        assert gdtf_share.stored_username() == ""

    def test_password_lives_only_in_keyring(self, fake_keyring):
        assert gdtf_share.save_password("u", "secret") is True
        assert fake_keyring == {
            (gdtf_share.KEYRING_SERVICE, "u"): "secret"}
        assert gdtf_share.stored_password("u") == "secret"
        gdtf_share.clear_password("u")
        assert gdtf_share.stored_password("u") == ""

    def test_without_keyring_save_reports_session_only(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "keyring", None)
        assert gdtf_share.save_password("u", "secret") is False
        assert gdtf_share.stored_password("u") == ""
        assert gdtf_share.keyring_available() is False

    def test_empty_user_or_password_is_never_stored(self, fake_keyring):
        assert gdtf_share.save_password("", "secret") is False
        assert gdtf_share.save_password("u", "") is False
        assert fake_keyring == {}


# ── pane ────────────────────────────────────────────────────────────────


def sync_start(worker):
    """Run the worker inline: signals fire immediately, finished included."""
    worker.run()
    worker.finished.emit()


@pytest.fixture
def synchronous_workers(monkeypatch):
    from gui.dialogs import gdtf_share_pane as mod
    monkeypatch.setattr(mod._ShareWorker, "start", sync_start)


def make_pane(tmp_path, routes=None, cached=None):
    from gui.dialogs.gdtf_share_pane import GDTFSharePane
    cache_path = tmp_path / "catalog.json"
    if cached is not None:
        cache_path.write_text(json.dumps(cached), encoding="utf-8")
    session = FakeSession(routes)
    client = GDTFShareClient(session=session, cache_path=str(cache_path))
    return GDTFSharePane(client=client), session


class TestPane:
    def test_cold_start_is_disconnected_and_searchless(
            self, qapp, fake_keyring, tmp_path):
        pane, _ = make_pane(tmp_path)
        assert not pane.search_box.isEnabled()
        assert not pane.download_btn.isEnabled()
        assert "Not connected" in pane.account_status.text()

    def test_cached_catalog_is_browsable_offline(
            self, qapp, fake_keyring, tmp_path):
        pane, session = make_pane(tmp_path, cached=catalog_entries())
        assert pane.search_box.isEnabled()
        assert pane.table.rowCount() == 3
        assert "cached catalog" in pane.account_status.text()
        assert session.calls == []
        # but downloads still need the session
        pane.table.selectRow(0)
        assert not pane.download_btn.isEnabled()

    def test_connect_populates_and_persists_credentials(
            self, qapp, fake_keyring, tmp_path, synchronous_workers):
        pane, _ = make_pane(tmp_path, routes={
            "login.php": LOGIN_OK,
            "getList.php": FakeResponse(
                {"result": True, "list": catalog_entries()})})
        pane.account.user_edit.setText("u")
        pane.account.password_edit.setText("p")
        pane.account.remember_check.setChecked(True)
        pane._connect()
        assert "catalog: 3" in pane.account_status.text()
        assert pane.table.rowCount() == 3
        assert gdtf_share.stored_username() == "u"
        assert gdtf_share.stored_password("u") == "p"

    def test_unchecked_remember_clears_the_stored_password(
            self, qapp, fake_keyring, tmp_path, synchronous_workers):
        gdtf_share.save_password("u", "old")
        pane, _ = make_pane(tmp_path, routes={
            "login.php": LOGIN_OK,
            "getList.php": FakeResponse({"result": True, "list": []})})
        pane.account.user_edit.setText("u")
        pane.account.password_edit.setText("new")
        pane.account.remember_check.setChecked(False)
        pane._connect()
        assert gdtf_share.stored_password("u") == ""

    def test_failed_login_shows_the_message_and_stores_nothing(
            self, qapp, fake_keyring, tmp_path, synchronous_workers):
        pane, _ = make_pane(tmp_path, routes={
            "login.php": FakeResponse(
                {"result": False, "error": "Wrong password"})})
        pane.account.user_edit.setText("u")
        pane.account.password_edit.setText("bad")
        pane._connect()
        assert "Wrong password" in pane.account_status.text()
        assert gdtf_share.stored_username() == ""
        assert not pane.search_box.isEnabled()

    def test_search_narrows_the_table(
            self, qapp, fake_keyring, tmp_path):
        pane, _ = make_pane(tmp_path, cached=catalog_entries())
        pane.search_box.setText("aura")
        assert pane.table.rowCount() == 1
        assert pane.table.item(0, 1).text() == "MAC Aura"

    def test_download_lands_in_the_user_gdtf_dir_and_rescans(
            self, qapp, fake_keyring, tmp_path, synchronous_workers):
        from utils import app_settings as aps
        from utils import fixture_library as fl
        dest = tmp_path / "user_gdtf"
        aps.set_user_gdtf_dir(str(dest))
        try:
            pane, _ = make_pane(tmp_path, routes={
                "login.php": LOGIN_OK,
                "getList.php": FakeResponse(
                    {"result": True, "list": catalog_entries()}),
                "downloadFile.php": FakeResponse(content=PK)})
            pane.account.user_edit.setText("u")
            pane.account.password_edit.setText("p")
            pane._connect()
            pane.table.selectRow(0)
            assert pane.download_btn.isEnabled()

            received = []
            pane.fixtures_downloaded.connect(received.extend)
            fl._definition_cache[("Sentinel", "Model")] = None
            pane._download()
            assert len(received) == 1
            assert received[0].startswith(str(dest))
            with open(received[0], "rb") as f:
                assert f.read() == PK
            assert ("Sentinel", "Model") not in fl._definition_cache
            assert str(dest) in pane.status_label.text()
        finally:
            aps.set_user_gdtf_dir("")

    def test_failed_download_reports_instead_of_crashing(
            self, qapp, fake_keyring, tmp_path, synchronous_workers):
        pane, _ = make_pane(tmp_path, routes={
            "login.php": LOGIN_OK,
            "getList.php": FakeResponse(
                {"result": True, "list": catalog_entries()}),
            "downloadFile.php": FakeResponse(content=b"nope")})
        pane.account.user_edit.setText("u")
        pane.account.password_edit.setText("p")
        pane._connect()
        pane.table.selectRow(0)
        pane._download()
        assert "did not return" in pane.status_label.text()


class TestRememberCheckboxWithoutKeyring:
    def test_disabled_with_explanation(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "keyring", None)
        from gui.dialogs.gdtf_share_pane import ShareAccountForm
        form = ShareAccountForm()
        assert not form.remember_check.isEnabled()
        assert "session only" in form.remember_check.toolTip()


# ── fixture browser integration ─────────────────────────────────────────


class TestBrowserShareTab:
    def _files(self, n):
        return [{"manufacturer": f"M{i}", "model": f"F{i}",
                 "path": f"/tmp/f{i}.qxf", "source": "bundled"}
                for i in range(n)]

    def test_share_pane_becomes_the_second_tab(
            self, qapp, fake_keyring, tmp_path):
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        pane, _ = make_pane(tmp_path)
        dialog = FixtureBrowserDialog(
            self._files(2), rescan=lambda: self._files(2), share_pane=pane)
        assert dialog.tabs.count() == 2
        assert dialog.tabs.tabText(1) == "GDTF SHARE"
        assert dialog.list_widget.count() == 2

    def test_download_signal_rescans_the_library_list(
            self, qapp, fake_keyring, tmp_path):
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        pane, _ = make_pane(tmp_path)
        dialog = FixtureBrowserDialog(
            self._files(2), rescan=lambda: self._files(3), share_pane=pane)
        pane.fixtures_downloaded.emit(["x.gdtf"])
        assert dialog.list_widget.count() == 3

    def test_without_a_pane_the_dialog_is_unchanged(self, qapp):
        from gui.dialogs.fixture_browser_dialog import FixtureBrowserDialog
        dialog = FixtureBrowserDialog(self._files(1))
        assert not hasattr(dialog, "tabs")
        assert dialog.list_widget.count() == 1


# ── settings account dialog ─────────────────────────────────────────────


class TestAccountDialog:
    def _dialog(self, tmp_path, routes=None):
        from gui.dialogs.gdtf_share_account_dialog import (
            GDTFShareAccountDialog,
        )
        session = FakeSession(routes)
        client = GDTFShareClient(
            session=session, cache_path=str(tmp_path / "catalog.json"))
        return GDTFShareAccountDialog(client=client), session

    def test_accept_persists_the_account(
            self, qapp, fake_keyring, tmp_path):
        dialog, _ = self._dialog(tmp_path)
        dialog.account.user_edit.setText("u")
        dialog.account.password_edit.setText("p")
        dialog.account.remember_check.setChecked(True)
        dialog.accept()
        assert gdtf_share.stored_username() == "u"
        assert gdtf_share.stored_password("u") == "p"

    def test_test_login_reports_both_ways(
            self, qapp, fake_keyring, tmp_path, synchronous_workers):
        dialog, _ = self._dialog(tmp_path, routes={"login.php": LOGIN_OK})
        dialog.account.user_edit.setText("u")
        dialog.account.password_edit.setText("p")
        dialog._test_login()
        assert dialog.status_label.text() == "Login OK."

        bad, _ = self._dialog(tmp_path, routes={
            "login.php": FakeResponse(
                {"result": False, "error": "Wrong password"})})
        bad.account.user_edit.setText("u")
        bad.account.password_edit.setText("x")
        bad._test_login()
        assert "Wrong password" in bad.status_label.text()

    def test_reject_persists_nothing(self, qapp, fake_keyring, tmp_path):
        dialog, _ = self._dialog(tmp_path)
        dialog.account.user_edit.setText("never")
        dialog.reject()
        assert gdtf_share.stored_username() == ""

    def test_prefills_the_stored_account(
            self, qapp, fake_keyring, tmp_path):
        gdtf_share.store_username("u")
        gdtf_share.save_password("u", "p")
        dialog, _ = self._dialog(tmp_path)
        assert dialog.account.user_edit.text() == "u"
        assert dialog.account.password_edit.text() == "p"
        assert dialog.account.remember_check.isChecked()


class TestAutoPull:
    """The project-load GDTF auto-pull (2026-07-16): exact-identity
    matching only, and three keep gates - internal identity, channel
    footprint, geometry presence. Everything drives fakes; nothing
    touches the network or the real library."""

    def _identity_entries(self):
        return [
            {"rid": 1, "manufacturer": "Varytec", "fixture": "Hero Spot 60",
             "uploader": "Manufacturer", "rating": "5.0"},
            {"rid": 2, "manufacturer": "Varytec", "fixture": "Hero_Spot_60",
             "uploader": "User", "rating": "1.0"},
            {"rid": 3, "manufacturer": "Cameo", "fixture": "Other Thing",
             "uploader": "User", "rating": "5.0"},
        ]

    def test_candidates_match_exact_identity_only(self):
        from utils.gdtf_share import autopull_candidates
        result = autopull_candidates(
            self._identity_entries(),
            [("Varytec", "Hero Spot 60"), ("Stairville", "Wild Wash")])
        assert list(result) == [("Varytec", "Hero Spot 60")]
        # Underscored variant normalizes onto the same identity; the
        # manufacturer upload outranks it.
        assert result[("Varytec", "Hero Spot 60")]["rid"] == 1

    def test_missing_identities_are_the_non_gdtf_ones(self, monkeypatch):
        from types import SimpleNamespace
        import utils.fixture_library as fl
        from utils.gdtf_share import missing_gdtf_identities

        def fake_get_definition(m, mo):
            if mo == "HasGdtf":
                return SimpleNamespace(gdtf=object())
            if mo == "QxfOnly":
                return SimpleNamespace(gdtf=None)
            return None
        monkeypatch.setattr(fl, "get_definition", fake_get_definition)

        from config.models import Configuration, Fixture, FixtureMode, \
            Universe

        def fx(model):
            return Fixture(universe=1, address=1, manufacturer="M",
                           model=model, current_mode="Std",
                           available_modes=[FixtureMode(name="Std",
                                                        channels=5)],
                           name=model, group="G")
        cfg = Configuration(
            fixtures=[fx("HasGdtf"), fx("QxfOnly"), fx("Unknown")],
            groups={}, universes={1: Universe(id=1, name="U", output={})})
        cfg.songs = {}
        assert missing_gdtf_identities(cfg) == [
            ("M", "QxfOnly"), ("M", "Unknown")]

    def _pull_setup(self, tmp_path, monkeypatch, internal_model,
                    mode_channels, has_geometry=True):
        from types import SimpleNamespace
        import utils.gdtf_share as gs
        import utils.fixture_library as fl

        monkeypatch.setattr(gs, "stored_username", lambda: "user")
        monkeypatch.setattr(gs, "stored_password", lambda u: "pw")
        monkeypatch.setattr(fl, "get_definition", lambda m, mo: None)

        class FakeClient:
            def login(self, user, password):
                pass

            def catalog(self, refresh=False):
                return [{"rid": 9, "manufacturer": "Varytec",
                         "fixture": "Hero Spot 60",
                         "uploader": "Manufacturer", "rating": "5.0"}]

            def download(self, entry, dest_dir):
                path = os.path.join(dest_dir, "Varytec@Hero Spot 60.gdtf")
                with open(path, "wb") as f:
                    f.write(b"fake")
                return path

        fake_defn = SimpleNamespace(
            manufacturer="Varytec", model=internal_model,
            modes=[SimpleNamespace(name="14ch",
                                   channels=[object()] * mode_channels)],
            gdtf=object() if has_geometry else None)
        import utils.gdtf_loader as gl
        monkeypatch.setattr(gl, "parse_gdtf_file", lambda p: fake_defn)

        from config.models import Configuration, Fixture, FixtureMode, \
            Universe
        fixture = Fixture(universe=1, address=1, manufacturer="Varytec",
                          model="Hero Spot 60", current_mode="14 Channel",
                          available_modes=[FixtureMode(name="14 Channel",
                                                       channels=14)],
                          name="MH1", group="MH")
        cfg = Configuration(fixtures=[fixture], groups={},
                            universes={1: Universe(id=1, name="U",
                                                   output={})})
        cfg.songs = {}
        return gs, cfg, FakeClient()

    def test_pull_keeps_a_compatible_gdtf(self, tmp_path, monkeypatch):
        gs, cfg, client = self._pull_setup(tmp_path, monkeypatch,
                                           "Hero Spot 60", 14)
        kept = gs.pull_missing_gdtf(cfg, str(tmp_path), client=client)
        assert len(kept) == 1 and os.path.exists(kept[0])

    def test_pull_deletes_identity_mismatch(self, tmp_path, monkeypatch):
        gs, cfg, client = self._pull_setup(tmp_path, monkeypatch,
                                           "Hero Spot 90", 14)
        kept = gs.pull_missing_gdtf(cfg, str(tmp_path), client=client)
        assert kept == []
        assert os.listdir(str(tmp_path)) == []

    def test_pull_deletes_footprint_mismatch(self, tmp_path, monkeypatch):
        """The shadow swaps the whole definition: a GDTF without a mode
        matching the patched channel count would re-map the wire."""
        gs, cfg, client = self._pull_setup(tmp_path, monkeypatch,
                                           "Hero Spot 60", 12)
        kept = gs.pull_missing_gdtf(cfg, str(tmp_path), client=client)
        assert kept == []
        assert os.listdir(str(tmp_path)) == []

    def test_pull_deletes_geometryless_gdtf(self, tmp_path, monkeypatch):
        gs, cfg, client = self._pull_setup(tmp_path, monkeypatch,
                                           "Hero Spot 60", 14,
                                           has_geometry=False)
        kept = gs.pull_missing_gdtf(cfg, str(tmp_path), client=client)
        assert kept == []

    def test_pull_without_credentials_is_quiet(self, tmp_path,
                                               monkeypatch):
        import utils.gdtf_share as gs
        import utils.fixture_library as fl
        monkeypatch.setattr(gs, "stored_username", lambda: "")
        monkeypatch.setattr(fl, "get_definition", lambda m, mo: None)
        from config.models import Configuration, Fixture, FixtureMode, \
            Universe
        fixture = Fixture(universe=1, address=1, manufacturer="V",
                          model="X", current_mode="Std",
                          available_modes=[FixtureMode(name="Std",
                                                       channels=1)],
                          name="f", group="G")
        cfg = Configuration(fixtures=[fixture], groups={},
                            universes={1: Universe(id=1, name="U",
                                                   output={})})
        cfg.songs = {}
        assert gs.pull_missing_gdtf(cfg, str(tmp_path)) == []
