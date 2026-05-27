"""Snov.io API wrapper.

OAuth2 client_credentials flow:
1. POST /v1/oauth/access_token with user_id + secret -> access token (1h TTL)
2. Use token in subsequent calls
3. Cache the token in-memory; refresh when expired

Free tier: 50 credits/mo. Email finder ~ 1 credit per name + domain.
Docs: https://snov.io/api

Errors: this module raises typed exceptions from core.enrich.errors so the
orchestrator can tell apart 'creds bad' / 'credits gone' / 'no match' and
warn the user instead of silently routing to LinkedIn outreach.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from core.config import secret
from core.enrich.errors import (
    AuthError,
    ProviderUnreachable,
    QuotaExhaustedError,
    RateLimitError,
)

_BASE = "https://api.snov.io"
_TOKEN_TTL_PAD_S = 60
_token_cache: dict = {"value": None, "expires_at": 0.0}


def _creds() -> tuple[str, str]:
    uid = secret("apis", "snov_user_id")
    sec = secret("apis", "snov_secret")
    if not (uid and sec):
        raise RuntimeError("Snov credentials missing. Set apis.snov_user_id and apis.snov_secret in secrets.toml.")
    return uid, sec


def _raise_typed(provider: str, status_code: int, body_msg: str) -> None:
    low = (body_msg or "").lower()
    if status_code in (401, 403) or "auth" in low or "token" in low or "invalid" in low or "unauthorized" in low:
        err = AuthError(f"Snov rejected the credentials: {body_msg}")
        err.provider = provider
        raise err
    if status_code in (402, 451) or "limit" in low or "credit" in low or "quota" in low or "exhaust" in low:
        err = QuotaExhaustedError(f"Snov credits / plan limit hit: {body_msg}")
        err.provider = provider
        raise err
    if status_code == 429 or "rate" in low or "too many" in low:
        err = RateLimitError(f"Snov rate-limited: {body_msg}")
        err.provider = provider
        raise err
    err = ProviderUnreachable(f"Snov error (HTTP {status_code}): {body_msg}")
    err.provider = provider
    raise err


def _token() -> str:
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]
    uid, sec = _creds()
    try:
        r = requests.post(
            f"{_BASE}/v1/oauth/access_token",
            data={"grant_type": "client_credentials", "client_id": uid, "client_secret": sec},
            timeout=15,
        )
    except requests.RequestException as e:
        err = ProviderUnreachable(f"Snov OAuth network error: {e}")
        err.provider = "snov"
        raise err from e

    try:
        data = r.json()
    except Exception:
        data = {}

    if r.status_code >= 400 or not data.get("access_token"):
        msg = data.get("error_description") or data.get("error") or data.get("message") or f"HTTP {r.status_code}"
        _raise_typed("snov", r.status_code, str(msg))

    tok = data["access_token"]
    ttl = int(data.get("expires_in", 3600))
    _token_cache["value"] = tok
    _token_cache["expires_at"] = time.time() + ttl - _TOKEN_TTL_PAD_S
    return tok


def _post(path: str, data: dict, timeout: int = 20) -> dict:
    """POST wrapper that translates HTTP + body-level Snov errors into typed exceptions.

    Snov has a habit of returning HTTP 200 with {"success": false, "message": "limit reached"}
    when credits are gone, so we need to inspect both status code AND body.
    """
    try:
        r = requests.post(f"{_BASE}{path}", data=data, timeout=timeout)
    except requests.RequestException as e:
        err = ProviderUnreachable(f"Snov network error: {e}")
        err.provider = "snov"
        raise err from e

    try:
        body = r.json()
    except Exception:
        body = {}

    # Body-level failure (most common path on quota exhaustion)
    if isinstance(body, dict) and body.get("success") is False:
        msg = body.get("message") or body.get("error") or "Snov refused the call"
        _raise_typed("snov", r.status_code, str(msg))

    if r.status_code >= 400:
        msg = (
            (body.get("message") if isinstance(body, dict) else None)
            or (body.get("error") if isinstance(body, dict) else None)
            or f"HTTP {r.status_code}"
        )
        _raise_typed("snov", r.status_code, str(msg))

    return body if isinstance(body, dict) else {"raw": body}


def balance() -> dict:
    """Credits remaining. Free; doesn't consume credits."""
    body = _post("/v1/get-balance", {"access_token": _token()}, timeout=15)
    return body.get("data", {}) or body


def email_finder(domain: str, first_name: str, last_name: str) -> dict:
    """Find a single email by name + domain. Consumes ~1 credit."""
    body = _post(
        "/v1/get-emails-from-names",
        {
            "access_token": _token(),
            "firstName": first_name,
            "lastName": last_name,
            "domain": domain,
        },
    )
    data = body.get("data", {}) or {}
    emails = data.get("emails", []) or []
    if not emails:
        return {"email": None}
    best = emails[0]
    return {
        "email": best.get("email"),
        "status": best.get("emailStatus"),
        "score": _status_to_score(best.get("emailStatus")),
        "raw": data,
    }


def domain_search(domain: str, limit: int = 10) -> list[dict]:
    """All discoverable emails for a domain. Consumes ~1 credit per 10."""
    body = _post(
        "/v2/domain-emails-with-info",
        {"access_token": _token(), "domain": domain, "limit": limit, "lastId": 0},
    )
    emails = body.get("emails", []) or []
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
    body = _post(
        "/v1/get-emails-verification-status",
        {"access_token": _token(), "emails[]": email},
    )
    data = body.get("data", [{}])
    first = data[0] if data else {}
    return {
        "status": first.get("status"),
        "score": _status_to_score(first.get("status")),
    }


def _status_to_score(status: Optional[str]) -> int:
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
