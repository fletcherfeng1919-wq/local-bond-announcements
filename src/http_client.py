"""Polite HTTP fetching with disk caching, delay and retry."""
import hashlib
import random
import time
from pathlib import Path

import requests

from . import config


def _cache_path(url: str, directory: Path, suffix: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return directory / f"{h}{suffix}"


def fetch(url: str, use_cache: bool = True, session: requests.Session | None = None) -> str:
    """Fetch a URL's text (HTML), using an on-disk cache keyed by URL hash.

    Cached responses never re-hit the network, which is what makes repeated
    incremental runs cheap and keeps us from re-hammering already-seen pages.
    """
    cache_file = _cache_path(url, config.RAW_HTML_DIR, ".html")
    if use_cache and cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="ignore")

    sess = session or requests.Session()
    headers = {"User-Agent": config.USER_AGENT}

    last_err = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = sess.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or "utf-8"
            resp.raise_for_status()
            text = resp.text
            cache_file.write_text(text, encoding="utf-8")
            time.sleep(random.uniform(*config.REQUEST_DELAY_RANGE))
            return text
        except requests.RequestException as e:
            last_err = e
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise RuntimeError(f"Failed to fetch {url} after {config.MAX_RETRIES} attempts: {last_err}")


def _is_valid_pdf_bytes(data: bytes) -> bool:
    """Cheap structural sanity check -- a connection drop mid-download can
    leave a short-but-nonzero file on disk without requests ever raising
    (e.g. no Content-Length header, or a close that reads as a clean EOF to
    urllib3). Such a file passes 'exists and size > 0' forever, permanently
    poisoning the cache with something pdfplumber can never open. Real PDFs
    start with the %PDF magic bytes and end with an %%EOF trailer marker
    (allowing a little trailing whitespace/newlines after it)."""
    if not data or not data.startswith(b"%PDF"):
        return False
    return b"%%EOF" in data[-2048:]


def fetch_pdf(url: str, use_cache: bool = True, session: requests.Session | None = None) -> Path:
    """Download a PDF attachment to the on-disk cache (if not already there)
    and return its local path. Never re-downloads a cached *valid* PDF; a
    cached file that fails the structural check is treated as missing and
    re-fetched instead of being trusted forever."""
    cache_file = _cache_path(url, config.RAW_PDF_DIR, ".pdf")
    if use_cache and cache_file.exists() and cache_file.stat().st_size > 0:
        if _is_valid_pdf_bytes(cache_file.read_bytes()):
            return cache_file

    sess = session or requests.Session()
    headers = {"User-Agent": config.USER_AGENT}
    last_err = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = sess.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            content = resp.content
            if not _is_valid_pdf_bytes(content):
                raise requests.RequestException(
                    f"downloaded content failed PDF structural check ({len(content)} bytes)"
                )
            cache_file.write_bytes(content)
            time.sleep(random.uniform(*config.REQUEST_DELAY_RANGE))
            return cache_file
        except requests.RequestException as e:
            last_err = e
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise RuntimeError(f"Failed to fetch PDF {url}: {last_err}")
