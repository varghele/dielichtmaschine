"""Fetch GDTF fixture definitions from GDTF Share into gdtf_fixtures/.

Early groundwork for the Phase 4 Share integration
(docs/gdtf-integration-plan.md): login with the user's own account, pull
a wanted-list of fixtures, cache locally. Downloaded files land in
gdtf_fixtures/ which is gitignored - GDTF Share terms do not permit
redistributing the files, so they must never be committed.

Credentials come from GDTF_SHARE_USER / GDTF_SHARE_PASSWORD (environment
first, then the persistent user environment in the Windows registry, so
`setx`-stored values work without a new shell).

Usage:
    python scripts/gdtf_share_fetch.py                 # fetch the default wanted list
    python scripts/gdtf_share_fetch.py --search aura   # explore the catalog
    python scripts/gdtf_share_fetch.py --rid 12345     # fetch one exact revision
    python scripts/gdtf_share_fetch.py --refresh       # force a fresh catalog

API: https://github.com/mvrdevelopment/tools (GDTF Share API doc).
"""
import argparse
import json
import os
import re
import sys
import time

import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GDTF_DIR = os.path.join(REPO_ROOT, "gdtf_fixtures")
LIST_CACHE = os.path.join(GDTF_DIR, ".share_list.json")
BASE_URL = "https://gdtf-share.com/apis/public"

# The spike-gate wanted list: GDTF equivalents of the demo-rig fixtures
# (manufacturer substring, fixture-name substring), case-insensitive.
DEFAULT_WANTED = [
    ("Martin", "MAC Aura"),
    ("Ayrton", "MagicBlade"),
    ("Showtec", "Sunstrip"),
    ("Stairville", "Retro Flat Par"),
    ("Stairville", "LED Matrix Blinder"),
    ("Stairville", "Wild Wash"),
    ("Varytec", "Hero Spot 60"),
    ("Varytec", "Giga Bar"),
]


def _credentials():
    user = os.environ.get("GDTF_SHARE_USER")
    password = os.environ.get("GDTF_SHARE_PASSWORD")
    if (not user or not password) and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                if not user:
                    user = winreg.QueryValueEx(key, "GDTF_SHARE_USER")[0]
                if not password:
                    password = winreg.QueryValueEx(key, "GDTF_SHARE_PASSWORD")[0]
        except OSError:
            pass
    if not user or not password:
        sys.exit("Set GDTF_SHARE_USER and GDTF_SHARE_PASSWORD (env or setx).")
    return user, password


def login(session: requests.Session) -> None:
    user, password = _credentials()
    r = session.post(f"{BASE_URL}/login.php",
                     data={"user": user, "password": password}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("result"):
        sys.exit(f"GDTF Share login failed: {payload}")


def get_catalog(session: requests.Session, refresh: bool = False) -> list:
    if not refresh and os.path.exists(LIST_CACHE):
        age_h = (time.time() - os.path.getmtime(LIST_CACHE)) / 3600.0
        if age_h < 24.0:
            with open(LIST_CACHE, encoding="utf-8") as f:
                return json.load(f)
    r = session.get(f"{BASE_URL}/getList.php", timeout=180)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("result"):
        sys.exit(f"getList failed: {payload}")
    entries = payload["list"]
    os.makedirs(GDTF_DIR, exist_ok=True)
    with open(LIST_CACHE, "w", encoding="utf-8") as f:
        json.dump(entries, f)
    return entries


def find_matches(catalog: list, manufacturer_term: str, fixture_term: str) -> list:
    m_term = manufacturer_term.lower()
    f_term = fixture_term.lower()
    matches = [
        e for e in catalog
        if m_term in (e.get("manufacturer") or "").lower()
        and f_term in (e.get("fixture") or "").lower()
    ]

    def rank(e):
        fixture = (e.get("fixture") or "").lower()
        exact = fixture == f_term
        try:
            rating = float(e.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        # Manufacturer-uploaded files first, then exact name, rating, recency
        manufacturer_upload = (e.get("uploader") or "").lower() != "user"
        return (manufacturer_upload, exact, rating, e.get("lastModified") or 0)

    return sorted(matches, key=rank, reverse=True)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "-", name).strip()


def download(session: requests.Session, entry: dict) -> str:
    rid = entry["rid"]
    r = session.get(f"{BASE_URL}/downloadFile.php", params={"rid": rid},
                    timeout=180)
    r.raise_for_status()
    if r.content[:2] != b"PK":  # .gdtf is a zip
        sys.exit(f"rid {rid}: response is not a .gdtf archive: {r.content[:200]!r}")
    os.makedirs(GDTF_DIR, exist_ok=True)
    fname = f"{_safe(entry['manufacturer'])}@{_safe(entry['fixture'])}@rid{rid}.gdtf"
    out_path = os.path.join(GDTF_DIR, fname)
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def _describe(e: dict) -> str:
    modes = ", ".join(f"{m['name']}({m['dmxfootprint']}ch)"
                      for m in (e.get("modes") or [])[:4])
    more = "..." if len(e.get("modes") or []) > 4 else ""
    return (f"rid={e['rid']:>6}  {e['manufacturer']} | {e['fixture']} | "
            f"rating={e.get('rating')} uploader={e.get('uploader')} "
            f"gdtf={e.get('version')} size={e.get('filesize', 0) // 1024}KB "
            f"modes: {modes}{more}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--search", help="print catalog matches for a term, no download")
    ap.add_argument("--rid", type=int, help="download one exact revision id")
    ap.add_argument("--refresh", action="store_true", help="force fresh catalog fetch")
    ap.add_argument("--top", type=int, default=8, help="matches shown per search")
    args = ap.parse_args()

    session = requests.Session()
    login(session)
    catalog = get_catalog(session, refresh=args.refresh)
    print(f"catalog: {len(catalog)} revisions")

    if args.search:
        for e in find_matches(catalog, "", args.search)[:args.top]:
            print(_describe(e))
        return

    if args.rid:
        entry = next((e for e in catalog if e["rid"] == args.rid), None)
        if entry is None:
            sys.exit(f"rid {args.rid} not in catalog")
        print("downloaded:", download(session, entry))
        return

    for manufacturer_term, fixture_term in DEFAULT_WANTED:
        matches = find_matches(catalog, manufacturer_term, fixture_term)
        if not matches:
            print(f"NOT FOUND on Share: {manufacturer_term} {fixture_term}")
            continue
        best = matches[0]
        print(f"{manufacturer_term} {fixture_term} -> {_describe(best)}")
        path = download(session, best)
        print(f"  -> {os.path.basename(path)}")


if __name__ == "__main__":
    main()
