"""Snov.io API wrapper.

OAuth2 client_credentials flow:
1. POST /v1/oauth/access_token with user_id + secret → access token (1h TTL)
2. Use token in subsequent calls
3. Cache the token in-memory; refresh when expired

Free tier: 50 credits/mo. Email finder ≈ 1 credit per name + domain.
Docs: https://snov.io/api
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from core.config import secret

_BASE = "https://api.snov.io"
_TOKEN_TTL_PAD_S = 60  # refresh 1 min before expiry
_token_cache: dict = {"value": None, "expires_at": 0.0}


def _creds() -> tuple[str, str]:
    uid = secret("apis", "snov_user_id")
    sec = secret("apis", "snov_secret")
    if not (uid and sec):
        raise RuntimeError("Snov credentials missing. Set apis.snov_user_id and apis.snov_secret in secrets.toml.")
    return uid, sec


def _token() -> str:
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]
    uid, sec = _creds()
    r = requests.post(
        f"{_BASE}/v1/oauth/access_token",
        data={"grant_type": "client_credentials", "client_id": uid, "client_secret": sec},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError(f"Snov OAuth failed: {data}")
    ttl = int(data.get("expires_in", 3600))
    _token_cache["value"] = tok
    _token_cache["expires_at"] = time.time() + ttl - _TOKEN_TTL_PAD_S
    return tok


def balance() -> dict:
    """Credits remaining. Free; doesn't consume credits."""
    r = requests.post(f"{_BASE}/v1/get-balance", data={"access_token": _token()}, timeout=15)
    r.raise_for_status()
    return r.json().get("data", {})


def email_finder(domain: str, first_name: str, last_name: str) -> dict:
    """Find a single email by name + domain. Consumes ~1 credit."""
    r = requests.post(
        f"{_BASE}/v1/get-emails-from-names",
        data={
            "access_token": _token(),
            "firstName": first_name,
            "lastName": last_name,
            "domain": domain,
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json().get("data", {}) or {}
    emails = data.get("emails", []) or []
    if not emails:
        return {"email": None}
    best = emails[0]
    return {
        "email": best.get("email"),
        "status": best.get("emailStatus"),       # valid / unknown / etc.
        "score": _status_to_score(best.get("emailStatus")),
        "raw": data,
    }


def domain_search(domain: str, limit: int = 10) -> list[dict]:
    """All discoverable emails for a domain. Consumes ~1 credit per 10."""
    r = requests.post(
        f"{_BASE}/v2/domain-emails-with-info",
        data={"access_token": _token(), "domain": domain, "limit": limit, "lastId": 0},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json() or {}
    emails = data.get("emails", []) or []
    out = []
    for e in emails:
        out.append(
            {
                "email": e.get("email"),
                "first_name": e.get("firstName"),
                "last_name": e.get("lastName"),
                "position": e.get("position"),
                "confidence": _status_to_score(e.get("emailStatus")),
                "linkedin": e.get("sourcePage"),
            }
        )
    return out


def verify(email: str) -> dict:
    """Snov verify. Consumes ~0.5 credits."""
    r = requests.post(
        f"{_BASE}/v1/get-emails-verification-status",
        data={"access_token": _token(), "emails[]": email},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json().get("data", [{}])
    first = data[0] if data else {}
    return {
        "status": first.get("status"),
        "score": _status_to_score(first.get("status")),
    }


def _status_to_score(status: Optional[str]) -> int:
    """Map Snov's string status to a numeric confidence for ordering."""
    if not status:
        return 0
    s = status.lower()
    return {
        "valid": 95,
        "verified": 95,
        "ok": 90,
        "unknown": 50,
        "catch_all": 60,
        "webmail": 40,
        "invalid": 5,
        "rejected": 5,
    }.get(s, 30)
