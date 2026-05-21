"""Brave Search API wrapper.

Free tier: 1 req/sec, basic plan free without card. We use it for two jobs:
1. Resolve "company name" → official domain (one query each).
2. Execute Google-style dorks for Discover.

Docs: https://api.search.brave.com/app/documentation/web-search/get-started
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlparse

import requests

from core.config import secret

_BASE = "https://api.search.brave.com/res/v1/web/search"
_HEADERS_BASE = {"Accept": "application/json", "Accept-Encoding": "gzip"}
_MIN_INTERVAL_S = 1.05  # safety pad over the 1 req/s free-tier limit
_last_call_ts = 0.0


def _key() -> str:
    k = secret("apis", "brave_api_key")
    if not k:
        raise RuntimeError("Brave API key missing. Set apis.brave_api_key in secrets.toml.")
    return k


def _throttle() -> None:
    global _last_call_ts
    delta = time.time() - _last_call_ts
    if delta < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - delta)
    _last_call_ts = time.time()


def search(query: str, count: int = 10, country: str = "IN") -> list[dict]:
    """Return a list of web result dicts: {title, url, description, hostname}."""
    _throttle()
    headers = {**_HEADERS_BASE, "X-Subscription-Token": _key()}
    params = {"q": query, "count": count, "country": country, "safesearch": "moderate"}
    r = requests.get(_BASE, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    out = []
    for item in (payload.get("web", {}) or {}).get("results", []) or []:
        url = item.get("url", "")
        out.append(
            {
                "title": item.get("title"),
                "url": url,
                "description": item.get("description"),
                "hostname": urlparse(url).hostname or "",
                "age": item.get("age"),
            }
        )
    return out


_BLOCKLIST_HOSTS = {
    "linkedin.com", "www.linkedin.com", "in.linkedin.com",
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "www.youtube.com",
    "crunchbase.com", "www.crunchbase.com",
    "tracxn.com", "www.tracxn.com",
    "inc42.com", "www.inc42.com",
    "yourstory.com", "www.yourstory.com",
    "entrackr.com", "www.entrackr.com",
    "wikipedia.org", "en.wikipedia.org",
    "indiamart.com", "www.indiamart.com",
    "amazon.in", "www.amazon.in", "flipkart.com", "www.flipkart.com",
}


def find_domain(company: str, hint: Optional[str] = None) -> Optional[str]:
    """Best-effort: company name → primary domain.

    Strategy: query "<company> official site India" and walk the results
    until we find a hostname that isn't a directory/social site.
    """
    query = f'"{company}" official site' + (f" {hint}" if hint else " India")
    try:
        results = search(query, count=10)
    except Exception:
        return None
    for r in results:
        host = (r.get("hostname") or "").lower()
        if not host or host in _BLOCKLIST_HOSTS:
            continue
        # Strip www.
        if host.startswith("www."):
            host = host[4:]
        return host
    return None
