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

    def __init__(self, session=None, cache_path=None, clock=time.time):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._cache_path = cache_path or default_catalog_cache_path()
        self._clock = clock
        self.logged_in = False
        self._catalog = None

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
        """Fetch one revision into ``dest_dir``; returns the file path."""
        rid = entry["rid"]
        try:
            response = self._session.get(
                f"{BASE_URL}/downloadFile.php", params={"rid": rid},
                timeout=180)
            response.raise_for_status()
        except Exception as exc:
            raise GDTFShareError(f"Download of rid {rid} failed: {exc}") from exc
        content = response.content
        if content[:2] != b"PK":  # a .gdtf is a zip archive
            raise GDTFShareError(
                f"GDTF Share did not return a .gdtf archive for rid {rid} "
                "(is the session still logged in?).")
        os.makedirs(dest_dir, exist_ok=True)
        out_path = os.path.join(dest_dir, entry_filename(entry))
        with open(out_path, "wb") as f:
            f.write(content)
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
