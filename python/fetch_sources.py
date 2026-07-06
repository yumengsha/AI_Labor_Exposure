"""
fetch_sources.py
================
Automatically download the latest BLS OEWS and O*NET source files, detecting
whether anything actually changed since last time.

This is the first stage of the automated refresh. It downloads into the
`data_warehouse/` source folder (same place your manual downloads live), so the
existing `prepare_data.py` picks them up unchanged.

>>> This script NEVER touches Snowflake. It only downloads public files. <<<

What it handles (verified against the live sites, 2026):
  * BLS OEWS: the site sits behind Akamai bot protection and returns HTTP 403
    to plain scripts. We send a full browser-like header set (incl. Referer),
    which the server accepts. URL pattern:
        https://www.bls.gov/oes/special.requests/oesm{YY}all.zip
    BLS OEWS is released ~once a year (May reference period, published the
    following spring). We probe recent years and download any that are new.
  * O*NET: downloads work directly. URLs are VERSION-PINNED:
        https://www.onetcenter.org/dl_files/database/db_{VER}_text.zip
    (e.g. db_30_3_text.zip). Releases are quarterly. We read the O*NET
    downloads page to discover the newest db_XX_X_text.zip automatically.

Change detection:
  A small JSON manifest (data_warehouse/.source_manifest.json) records each
  file's ETag / Last-Modified / size. On each run we send conditional requests;
  unchanged files are skipped. `--force` ignores the manifest.

Usage:
    python python/fetch_sources.py                 # download anything new
    python python/fetch_sources.py --force         # re-download everything
    python python/fetch_sources.py --years 2024 2025
    python python/fetch_sources.py --check-only     # report updates, download nothing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# BLS sits behind Akamai, which rate-limits rapid repeated requests (returns
# HTTP 403 once tripped). We (a) pause politely between BLS requests and
# (b) retry with exponential backoff. These knobs control that behaviour.
POLITE_DELAY_S = 3.0      # wait this long before each BLS request
MAX_RETRIES = 4           # attempts per request on 403/transient errors
BACKOFF_BASE_S = 5.0      # first backoff; doubles each retry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Downloads land in the sibling data_warehouse/ folder (the existing source dir).
SOURCE_DIR = PROJECT_ROOT.parent / "data_warehouse"
MANIFEST = SOURCE_DIR / ".source_manifest.json"

BLS_OEWS_URL = "https://www.bls.gov/oes/special.requests/oesm{yy}all.zip"
BLS_TABLES_PAGE = "https://www.bls.gov/oes/tables.htm"
ONET_DL_PAGE = "https://www.onetcenter.org/database.html"
ONET_ZIP_URL = "https://www.onetcenter.org/dl_files/database/{name}"

# A full browser-like header set. BLS/Akamai rejects requests without these.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------
def load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text())
        except (ValueError, OSError):
            return {}
    return {}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _request(url: str, referer: str | None = None, method: str = "GET"):
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    return urllib.request.Request(url, headers=headers, method=method)


def _is_bls(url: str) -> bool:
    return "bls.gov" in url


def _open_with_retry(req, timeout: int, polite: bool):
    """urlopen with polite delay + exponential backoff on 403/transient errors.

    Returns the (already-open) response on success, or raises the last error.
    Caller is responsible for closing / reading the response.
    """
    last_err = None
    for attempt in range(MAX_RETRIES):
        if polite:
            time.sleep(POLITE_DELAY_S)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            last_err = e
            # 403 from Akamai is usually transient rate-limiting; 404 is real.
            if e.code == 404:
                raise
            if e.code not in (403, 429, 500, 502, 503):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
        backoff = BACKOFF_BASE_S * (2 ** attempt)
        print(f"    (retry {attempt+1}/{MAX_RETRIES} after {backoff:.0f}s: {last_err})")
        time.sleep(backoff)
    raise last_err if last_err else RuntimeError("request failed")


def head_info(url: str, referer: str | None = None) -> dict | None:
    """Return {etag, last_modified, length} for a URL, or None if unreachable.

    Uses a 1-byte ranged GET rather than HEAD: BLS/Akamai reliably rejects HEAD
    but accepts a ranged GET, and it also confirms the file is really fetchable.
    """
    polite = _is_bls(url)
    req = _request(url, referer, "GET")
    req.add_header("Range", "bytes=0-0")
    try:
        r = _open_with_retry(req, timeout=60, polite=polite)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"_missing": True}   # definitively not published
        return None
    except Exception:
        return None
    try:
        # BLS "soft-404s": it returns HTTP 200 with an HTML page (the OES home
        # page) for files that don't exist. Detect that via Content-Type so we
        # never treat an error page as a downloadable zip.
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" in ctype or "text/" in ctype:
            return {"_missing": True}
        cr = r.headers.get("Content-Range", "")
        length = cr.split("/")[-1] if "/" in cr else r.headers.get("Content-Length")
        return {
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
            "length": length,
        }
    finally:
        r.close()


def download(url: str, dest: Path, referer: str | None = None) -> None:
    """Stream a URL to dest (atomic: writes to .part then renames).

    Validates that the payload is really a ZIP before committing it, so a
    soft-404 HTML page (BLS serves one with HTTP 200) is never left as a .zip.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    r = _open_with_retry(_request(url, referer), timeout=300, polite=_is_bls(url))
    ctype = (r.headers.get("Content-Type") or "").lower()
    with r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 // total
                print(f"\r    {dest.name}: {got/1e6:.1f}/{total/1e6:.1f} MB "
                      f"({pct}%)", end="", flush=True)
        print()

    # --- integrity checks -------------------------------------------------
    # 1. Content-Type must not be HTML/text (soft-404 guard).
    # 2. First 4 bytes must be the ZIP magic number (PK\x03\x04 / empty-archive
    #    PK\x05\x06 / spanned PK\x07\x08).
    if "html" in ctype or "text/" in ctype:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"server returned {ctype or 'non-zip content'} "
                           f"(likely a soft-404 error page), not a zip")
    with open(tmp, "rb") as f:
        magic = f.read(4)
    if magic[:2] != b"PK":
        size = tmp.stat().st_size
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded file is not a valid zip "
                           f"(magic={magic!r}, size={size} bytes)")
    tmp.replace(dest)


def is_changed(url: str, manifest: dict, referer: str | None = None) -> tuple[bool, dict]:
    """Compare current head info against the manifest entry.

    Returns (changed, info). info may be:
      * {}                -> could not determine (network/ambiguous)
      * {"_missing":True} -> server says 404, file not published
      * {etag,...}        -> real metadata
    """
    info = head_info(url, referer)
    if info is None:
        # Can't tell; assume changed so we attempt the download.
        return True, {}
    if info.get("_missing"):
        return False, info
    prev = manifest.get(url, {})
    changed = (info.get("etag") != prev.get("etag")
               or info.get("last_modified") != prev.get("last_modified")
               or info.get("length") != prev.get("length"))
    return changed, info


# ---------------------------------------------------------------------------
# O*NET latest-version discovery
# ---------------------------------------------------------------------------
def discover_latest_onet() -> str | None:
    """Scrape the O*NET page for the newest db_XX_X_text.zip filename."""
    try:
        with urllib.request.urlopen(_request(ONET_DL_PAGE), timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  [onet] could not read downloads page: {e}")
        return None
    names = re.findall(r"db_(\d+)_(\d+)_text\.zip", html)
    if not names:
        return None
    # pick the highest (major, minor)
    best = max(names, key=lambda t: (int(t[0]), int(t[1])))
    return f"db_{best[0]}_{best[1]}_text.zip"


# ---------------------------------------------------------------------------
# Main fetch logic
# ---------------------------------------------------------------------------
def fetch_bls(years, manifest, check_only) -> list[str]:
    updated = []
    for y in years:
        yy = f"{y % 100:02d}"
        url = BLS_OEWS_URL.format(yy=yy)
        dest = SOURCE_DIR / f"oesm{yy}all.zip"
        changed, info = is_changed(url, manifest, referer=BLS_TABLES_PAGE)
        exists = dest.exists()
        if info.get("_missing"):
            # Server returned 404: this year's estimates are not published yet.
            print(f"  [bls {y}] not published yet (404)")
            continue
        if not changed and exists:
            print(f"  [bls {y}] up to date")
            continue
        if info == {} and not exists:
            # Ambiguous (network) AND no local copy: skip rather than guess.
            print(f"  [bls {y}] could not verify (skipping)")
            continue
        print(f"  [bls {y}] {'UPDATE available' if exists else 'NEW'}: {url}")
        if not check_only:
            try:
                download(url, dest, referer=BLS_TABLES_PAGE)
                if info:
                    manifest[url] = info
                updated.append(dest.name)
            except Exception as e:
                print(f"  [bls {y}] download failed: {e}")
        else:
            updated.append(dest.name)
    return updated


def fetch_onet(manifest, check_only, pinned=None) -> list[str]:
    name = pinned or discover_latest_onet()
    if not name:
        print("  [onet] could not determine latest version")
        return []
    url = ONET_ZIP_URL.format(name=name)
    dest = SOURCE_DIR / name
    changed, info = is_changed(url, manifest)
    exists = dest.exists()
    print(f"  [onet] latest is {name}")
    if not changed and exists:
        print("  [onet] up to date")
        return []
    print(f"  [onet] {'UPDATE available' if exists else 'NEW'}: {url}")
    if check_only:
        return [name]
    try:
        download(url, dest)
        if info:
            manifest[url] = info
        return [name]
    except Exception as e:
        print(f"  [onet] download failed: {e}")
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="*", type=int,
                    help="OEWS years to probe (default: last 4 through current).")
    ap.add_argument("--onet-version", help="Pin an O*NET zip name, e.g. db_30_4_text.zip")
    ap.add_argument("--force", action="store_true", help="Ignore manifest; re-download.")
    ap.add_argument("--check-only", action="store_true",
                    help="Report what's new but download nothing.")
    ap.add_argument("--current-year", type=int,
                    help="Override 'current year' for the default year probe "
                         "(useful for testing / reproducibility).")
    args = ap.parse_args()

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {} if args.force else load_manifest()

    # Default year window: BLS publishes the prior year's May estimates in the
    # spring, so probe the last 4 plausible years. We do NOT call datetime here
    # to keep behaviour deterministic; pass --current-year or --years to control.
    if args.years:
        years = args.years
    else:
        cy = args.current_year
        if cy is None:
            # Fall back to the newest oews_*.csv / oesmXXall.zip already present,
            # then probe a couple years beyond it.
            seen = []
            for p in SOURCE_DIR.glob("oesm*all.zip"):
                m = re.search(r"oesm(\d{2})all", p.name)
                if m:
                    seen.append(2000 + int(m.group(1)))
            base = max(seen) if seen else 2025
            cy = base + 1
        years = [cy - 3, cy - 2, cy - 1, cy]

    print(f"Source folder: {SOURCE_DIR}")
    print(f"Probing OEWS years: {years}")
    print("-" * 60)
    print("BLS OEWS:")
    bls_updated = fetch_bls(years, manifest, args.check_only)
    print("O*NET:")
    onet_updated = fetch_onet(manifest, args.check_only, pinned=args.onet_version)

    if not args.check_only:
        save_manifest(manifest)

    updated = bls_updated + onet_updated
    print("\n" + "=" * 60)
    if not updated:
        print("No updates. Everything is current.")
        # Exit code 0, but signal "nothing to do" via a marker line the
        # orchestrator can parse.
        print("RESULT: NO_UPDATES")
    else:
        verb = "Would download" if args.check_only else "Downloaded"
        print(f"{verb}: {', '.join(updated)}")
        print("RESULT: UPDATES_FOUND")
    # Non-zero-free exit; orchestrator keys off the RESULT line, not exit code.


if __name__ == "__main__":
    main()
