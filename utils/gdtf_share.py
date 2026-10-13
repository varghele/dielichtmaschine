"""GDTF Share API client and account credential store.

Phase 4 of docs/gdtf-integration-plan.md: the in-app path from a user's
own GDTF Share account to a .gdtf file in the user GDTF directory. The
API flow (login session, catalog list, download by revision id) was
proven by scripts/gdtf_share_fetch.py; this module is the app-facing
version - exceptions instead of sys.exit, an injectable HTTP session
for tests, a catalog cache that keeps working offline, and credentials
that are NEVER written in plaintext (username in QSettings, password in
the OS credential store via keyring, or session-only when keyring is
unavailable).

Terms of use: downloaded definitions are fetched per-user and cached
locally, never bundled or committed (docs/gdtf-integration-plan.md #2).

API doc: https://github.com/mvrdevelopment/tools (GDTF Share API).
"""

import json
import os
import re
import time

BASE_URL = "https://gdtf-share.com/apis/public"
CATALOG_CACHE_MAX_AGE_H = 24.0

# OS credential-store identity. The username is not a secret and lives
# in QSettings next to the rest of the app state; only the password
# goes to keyring, keyed by service + username.
KEYRING_SERVICE = "dielichtmaschine-gdtf-share"
_USERNAME_KEY = "gdtf_share/user"


class GDTFShareError(Exception):
    """Any failure talking to GDTF Share, with a user-presentable message."""


class GDTFShareCancelled(GDTFShareError):
    """The caller's cancel event was set mid-operation."""


DOWNLOAD_CHUNK = 64 * 1024


def default_catalog_cache_path() -> str:
    from utils.app_identity import user_data_dir
    return os.path.join(user_data_dir(), "gdtf_share_catalog.json")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "-", str(name)).strip()


def entry_filename(entry: dict) -> str:
    """Local filename for a catalog entry; the rid pins the revision so
    a re-download of a newer revision never overwrites silently."""
    return (f"{_safe(entry.get('manufacturer', ''))}@"
            f"{_safe(entry.get('fixture', ''))}@rid{entry['rid']}.gdtf")


def rank_key(entry: dict, fixture_term: str = ""):
    """Sort key, best first when sorted descending: manufacturer uploads
    beat user uploads, then exact name match, rating, recency."""
    fixture = (entry.get("fixture") or "").lower()
    try:
        rating = float(entry.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0.0
    manufacturer_upload = (entry.get("uploader") or "").lower() != "user"
    exact = bool(fixture_term) and fixture == fixture_term.lower()
    return (manufacturer_upload, exact, rating, entry.get("lastModified") or 0)


class GDTFShareClient:
    """Login session + catalog + downloads against the Share API.

    All methods are synchronous and may block on the network; the GUI
    runs them on a worker thread. ``session`` is anything with
    requests' get/post signature (tests pass a fake); ``cache_path``
    overrides where the catalog JSON lands (tests use a tmp dir).
    """

    def __init__(self, session=None, cache_path=None, clock=time.time,
                 cancel=None):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._cache_path = cache_path or default_catalog_cache_path()
        self._clock = clock
        # Anything with is_set() (a threading.Event): a download stops
        # between chunks once it is set and leaves no file behind.
        self._cancel = cancel
        self.logged_in = False
        self._catalog = None

    def _check_cancel(self):
        if self._cancel is not None and self._cancel.is_set():
            raise GDTFShareCancelled("Cancelled.")

    # -- API calls --------------------------------------------------------

    def login(self, user: str, password: str) -> None:
        """Open a Share session; raises GDTFShareError on any failure."""
        if not user or not password:
            raise GDTFShareError("Enter your GDTF Share username and password.")
        payload = self._request("post", "login.php",
                                data={"user": user, "password": password},
                                timeout=30)
        if not payload.get("result"):
            raise GDTFShareError(
                payload.get("error") or "GDTF Share rejected the login.")
        self.logged_in = True

    def catalog(self, refresh: bool = False) -> list:
        """The full revision list, from a <24h local cache when possible.

        Offline-graceful: when the network fails, a stale cache still
        serves (the caller may be browsing already-known fixtures);
        only no-cache-and-no-network raises.
        """
        if self._catalog is not None and not refresh:
            return self._catalog
        cached = self._read_cache()
        if cached is not None and not refresh and not self._cache_stale():
            self._catalog = cached
            return cached
        try:
            payload = self._request("get", "getList.php", timeout=180)
        except GDTFShareError:
            if cached is not None:
                self._catalog = cached
                return cached
            raise
        if not payload.get("result"):
            raise GDTFShareError(
                payload.get("error") or "GDTF Share refused the catalog list.")
        entries = payload.get("list") or []
        self._write_cache(entries)
        self._catalog = entries
        return entries

    def load_cached_catalog(self):
        """The locally cached catalog regardless of age, or None. Never
        touches the network - browsing while offline stays possible."""
        if self._catalog is None:
            self._catalog = self._read_cache()
        return self._catalog

    def search(self, term: str, limit: int = 100) -> list:
        """Ranked catalog matches: every space-separated word of ``term``
        must appear in manufacturer+fixture (case-insensitive)."""
        words = [w for w in (term or "").lower().split() if w]
        matches = []
        for entry in self.catalog():
            haystack = (f"{entry.get('manufacturer') or ''} "
                        f"{entry.get('fixture') or ''}").lower()
            if all(word in haystack for word in words):
                matches.append(entry)
        matches.sort(key=lambda e: rank_key(e, term), reverse=True)
        return matches[:limit]

    def download(self, entry: dict, dest_dir: str) -> str:
        """Fetch one revision into ``dest_dir``; returns the file path.

        Streamed in chunks (the cancel event is checked between them)
        into a ``.part`` file that only an atomic rename turns into the
        ``.gdtf``: the library scans that directory, so a cancelled,
        failed or killed download must never leave a torn archive
        there."""
        rid = entry["rid"]
        self._check_cancel()
        try:
            response = self._session.get(
                f"{BASE_URL}/downloadFile.php", params={"rid": rid},
                timeout=180, stream=True)
            response.raise_for_status()
            iter_content = getattr(response, "iter_content", None)
            if iter_content is None:
                content = response.content
            else:
                chunks = []
                for chunk in iter_content(DOWNLOAD_CHUNK):
                    self._check_cancel()
                    chunks.append(chunk)
                content = b"".join(chunks)
        except GDTFShareError:
            raise
        except Exception as exc:
            raise GDTFShareError(f"Download of rid {rid} failed: {exc}") from exc
        if content[:2] != b"PK":  # a .gdtf is a zip archive
            raise GDTFShareError(
                f"GDTF Share did not return a .gdtf archive for rid {rid} "
                "(is the session still logged in?).")
        self._check_cancel()
        os.makedirs(dest_dir, exist_ok=True)
        out_path = os.path.join(dest_dir, entry_filename(entry))
        _write_atomic(out_path, content)
        return out_path

    # -- internals --------------------------------------------------------

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        try:
            response = getattr(self._session, method)(
                f"{BASE_URL}/{endpoint}", **kwargs)
            response.raise_for_status()
            return response.json()
        except GDTFShareError:
            raise
        except ValueError as exc:
            raise GDTFShareError(
                f"GDTF Share returned an unreadable response: {exc}") from exc
        except Exception as exc:
            raise GDTFShareError(f"Cannot reach GDTF Share: {exc}") from exc

    def _read_cache(self):
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _cache_stale(self) -> bool:
        try:
            age_h = (self._clock() - os.path.getmtime(self._cache_path)) / 3600.0
        except OSError:
            return True
        return age_h >= CATALOG_CACHE_MAX_AGE_H

    def _write_cache(self, entries: list) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(entries, f)
        except OSError:
            pass  # a cacheless catalog still works this session


def _write_atomic(path: str, content: bytes) -> None:
    """``content`` to ``path`` via ``path.part`` + rename. The library
    only picks up ``.gdtf``/``.qxf`` names, so a leftover ``.part``
    from a killed process is inert."""
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(content)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


# -- credential store ---------------------------------------------------------
# Username: QSettings (not a secret). Password: OS credential store via
# keyring only - when keyring is missing or its backend fails, the
# password is session-only and save_password reports False so the UI
# can say so. Plaintext persistence does not exist in any branch.

def keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        return not isinstance(keyring.get_keyring(), FailKeyring)
    except Exception:
        return False


def stored_username() -> str:
    from utils.app_settings import app_settings
    return app_settings().value(_USERNAME_KEY, "", type=str)


def store_username(user: str) -> None:
    from utils.app_settings import app_settings
    settings = app_settings()
    if user:
        settings.setValue(_USERNAME_KEY, user)
    else:
        settings.remove(_USERNAME_KEY)
    settings.sync()


def stored_password(user: str) -> str:
    """The remembered password for ``user``, or '' (absent or no keyring)."""
    if not user:
        return ""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, user) or ""
    except Exception:
        return ""


def save_password(user: str, password: str) -> bool:
    """Remember the password in the OS credential store. Returns False
    when there is no usable keyring backend (session-only fallback)."""
    if not user or not password:
        return False
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, user, password)
        return True
    except Exception:
        return False


def clear_password(user: str) -> None:
    if not user:
        return
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, user)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auto-pull (2026-07-16): fetch GDTF definitions for the fixtures a
# project actually uses, so the visualizer renders native models
# without a manual browser trip. gui.py runs pull_missing_gdtf on a
# worker thread after a project load, gated on stored credentials and
# the gdtf_share/auto_pull setting; every failure path is quiet - a
# venue laptop without internet must behave exactly as before.
# ---------------------------------------------------------------------------

AUTO_PULL_KEY = "gdtf_share/auto_pull"


def auto_pull_enabled() -> bool:
    from utils.app_settings import app_settings
    return app_settings().value(AUTO_PULL_KEY, True, type=bool)


def set_auto_pull_enabled(enabled: bool) -> None:
    from utils.app_settings import app_settings
    settings = app_settings()
    settings.setValue(AUTO_PULL_KEY, bool(enabled))
    settings.sync()


def _norm_identity(text: str) -> str:
    return " ".join((text or "").lower().replace("_", " ").split())


def missing_gdtf_identities(config) -> list:
    """(manufacturer, model) pairs used by the config whose resolved
    definition carries no GDTF geometry (i.e. would render as a
    procedural chassis)."""
    from utils.fixture_library import get_definition
    missing = []
    for manufacturer, model in sorted({(f.manufacturer, f.model)
                                       for f in config.fixtures}):
        if not manufacturer or not model:
            continue
        defn = get_definition(manufacturer, model)
        if defn is None or defn.gdtf is None:
            missing.append((manufacturer, model))
    return missing


def autopull_candidates(catalog: list, identities: list) -> dict:
    """{identity: best catalog entry} for entries whose manufacturer +
    fixture name match an identity exactly (case / underscore / extra
    whitespace insensitive - anything looser risks shadowing a fixture
    with a DIFFERENT product, which would silently change its channel
    map)."""
    wanted = {(_norm_identity(m), _norm_identity(mo)): (m, mo)
              for m, mo in identities}
    hits = {}
    for entry in catalog:
        key = (_norm_identity(entry.get("manufacturer")),
               _norm_identity(entry.get("fixture")))
        identity = wanted.get(key)
        if identity is not None:
            hits.setdefault(identity, []).append(entry)
    return {identity: sorted(entries, key=rank_key, reverse=True)[0]
            for identity, entries in hits.items()}


def _footprints_for_identity(config, manufacturer: str, model: str) -> set:
    """The channel footprints the config's fixtures of this identity
    are patched with (from their stored available_modes)."""
    footprints = set()
    for fixture in config.fixtures:
        if fixture.manufacturer != manufacturer or fixture.model != model:
            continue
        for mode in fixture.available_modes or []:
            if mode.name == fixture.current_mode:
                footprints.add(int(mode.channels))
    return footprints


def autopull_snapshot(config):
    """The part of ``config`` that pull_missing_gdtf reads (each
    fixture's identity and patched mode footprint), copied for the
    auto-pull worker thread. The pull runs for seconds over the
    network while the user keeps editing the live project; walking the
    live fixture list from that thread could skip, double or crash on a
    fixture added, removed or re-moded mid-pull."""
    from types import SimpleNamespace
    return SimpleNamespace(fixtures=[
        SimpleNamespace(
            manufacturer=f.manufacturer,
            model=f.model,
            current_mode=f.current_mode,
            available_modes=[SimpleNamespace(name=m.name, channels=m.channels)
                             for m in (f.available_modes or [])],
        )
        for f in list(config.fixtures)
    ])


def pull_missing_gdtf(config, dest_dir: str, client=None,
                      cancel=None) -> list:
    """Download exact-identity GDTFs for the config's non-GDTF
    fixtures. Returns the file paths KEPT.

    Safety gates, in order: stored credentials must exist; the
    downloaded file's INTERNAL identity must match (that is what the
    library keys on - a catalog name match alone does not shadow);
    and the GDTF must offer a mode matching every affected fixture's
    patched channel footprint (a shadow swaps the whole definition,
    so a footprint mismatch would silently re-map the wire). Downloads
    land in a private staging directory and only a file that passed
    every gate is moved into ``dest_dir``, so a pull that is killed or
    cancelled mid-way never leaves an unchecked file where the library
    would load it. All network/parse failures return what was kept so
    far, quietly.

    ``cancel`` (a threading.Event) stops the pull between steps and a
    download between chunks; nothing is moved into ``dest_dir`` once it
    is set."""
    import shutil
    import tempfile

    def cancelled():
        return cancel is not None and cancel.is_set()

    identities = missing_gdtf_identities(config)
    if not identities or cancelled():
        return []
    user = stored_username()
    password = stored_password(user)
    if not user or not password:
        return []

    kept = []
    try:
        if client is None:
            client = GDTFShareClient(cancel=cancel)
        client.login(user, password)
        if cancelled():
            return []
        candidates = autopull_candidates(client.catalog(), identities)
    except Exception:
        return []

    from utils.gdtf_loader import parse_gdtf_file
    staging = tempfile.mkdtemp(prefix="lm-gdtf-pull-")
    try:
        for (manufacturer, model), entry in sorted(candidates.items()):
            if cancelled():
                break
            try:
                staged = client.download(entry, staging)
                defn = parse_gdtf_file(staged)
            except Exception:
                continue
            internal = (_norm_identity(defn.manufacturer),
                        _norm_identity(defn.model))
            if internal != (_norm_identity(manufacturer),
                            _norm_identity(model)):
                continue
            gdtf_footprints = {len(m.channels) for m in defn.modes}
            needed = _footprints_for_identity(config, manufacturer, model)
            if needed and not needed <= gdtf_footprints:
                continue
            if defn.gdtf is None:
                continue              # no geometry: nothing gained
            if cancelled():
                break
            try:
                os.makedirs(dest_dir, exist_ok=True)
                path = os.path.join(dest_dir, os.path.basename(staged))
                with open(staged, "rb") as f:
                    _write_atomic(path, f.read())
            except OSError:
                continue
            kept.append(path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return kept
