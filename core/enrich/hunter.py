"""Hunter.io v2 API wrapper.

Free tier: 25 searches/mo + 50 verifications/mo. We treat searches as
precious — always prefer Email Finder (you know the name) over Domain
Search (broad sweep). Verify only when downstream cares.

Endpoints used:
- /v2/email-finder?domain=X&first_name=A&last_name=B
- /v2/domain-search?domain=X (+ optional &type=personal&limit=N)
- /v2/email-verifier?email=X
- /v2/account  (free, useful for quota checks)
"""
from __future__ import annotations

from typing import Optional

import requests

from core.config import secret

_BASE = "https://api.hunter.io/v2"


def _key() -> str:
    k = secret("apis", "hunter_api_key")
    if not k:
        raise RuntimeError("Hunter API key missing. Set apis.hunter_api_key in secrets.toml.")
    return k


def account() -> dict:
    """Quota/account info. Doesn't consume credits."""
    r = requests.get(f"{_BASE}/account", params={"api_key": _key()}, timeout=15)
    r.raise_for_status()
    return r.json().get("data", {})


def email_finder(domain: str, first_name: str, last_name: str) -> dict:
    """Most credit-efficient path: one named POC at a known domain."""
    params = {
        "api_key": _key(),
        "domain": domain,
        "first_name": first_name,
        "last_name": last_name,
    }
    r = requests.get(f"{_BASE}/email-finder", params=params, timeout=20)
    r.raise_for_status()
    data = r.json().get("data", {}) or {}
    return {
        "email": data.get("email"),
        "score": data.get("score"),
        "position": data.get("position"),
        "linkedin": data.get("linkedin"),
        "verification_status": (data.get("verification") or {}).get("status"),
        "sources_count": len(data.get("sources") or []),
        "raw": data,
    }


def domain_search(domain: str, limit: int = 10, seniority: Optional[str] = None, department: Optional[str] = None) -> list[dict]:
    """All discoverable emails for a domain. Expensive — call when no POC name is known."""
    params = {"api_key": _key(), "domain": domain, "limit": limit}
    if seniority:
        params["seniority"] = seniority  # junior, senior, executive
    if department:
        params["department"] = department  # executive, it, finance, management, sales, legal, support, hr, marketing, communication
    r = requests.get(f"{_BASE}/domain-search", params=params, timeout=20)
    r.raise_for_status()
    data = r.json().get("data", {}) or {}
    out = []
    for e in data.get("emails", []) or []:
        out.append(
            {
                "email": e.get("value"),
                "first_name": e.get("first_name"),
                "last_name": e.get("last_name"),
                "position": e.get("position"),
                "seniority": e.get("seniority"),
                "department": e.get("department"),
                "confidence": e.get("confidence"),
                "linkedin": e.get("linkedin"),
            }
        )
    return out


def verify(email: str) -> dict:
    r = requests.get(f"{_BASE}/email-verifier", params={"api_key": _key(), "email": email}, timeout=20)
    r.raise_for_status()
    data = r.json().get("data", {}) or {}
    return {
        "status": data.get("status"),       # valid | invalid | accept_all | webmail | disposable | unknown
        "result": data.get("result"),
        "score": data.get("score"),
        "regexp": data.get("regexp"),
        "gibberish": data.get("gibberish"),
        "disposable": data.get("disposable"),
        "webmail": data.get("webmail"),
        "mx_records": data.get("mx_records"),
        "smtp_server": data.get("smtp_server"),
        "smtp_check": data.get("smtp_check"),
        "accept_all": data.get("accept_all"),
        "block": data.get("block"),
        "sources_count": len(data.get("sources") or []),
    }
