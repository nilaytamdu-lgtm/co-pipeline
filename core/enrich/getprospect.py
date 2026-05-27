"""GetProspect API wrapper.

Free tier: 100 finder credits + 50 verifications per month. Auth is the raw
API key in the Authorization header (NOT 'Bearer <key>', just the key).

Docs: https://docs.getprospect.com/api

Errors: typed exceptions from core.enrich.errors so the orchestrator can
distinguish 'creds bad' / 'credits gone' / 'no match' from each other.
"""
from __future__ import annotations

from typing import Optional

import requests

from core.config import secret
from core.enrich.errors import (
    AuthError,
    ProviderUnreachable,
    QuotaExhaustedError,
    RateLimitError,
)

_BASE = "https://api.getprospect.com/public/v1"


def _key() -> str:
    k = secret("apis", "getprospect_api_key")
    if not k:
        raise RuntimeError("GetProspect API key missing. Set apis.getprospect_api_key in secrets.toml.")
    return k


def _request(method: str, path: str, params: Optional[dict] = None, timeout: int = 20) -> dict:
    headers = {"Authorization": _key()}
    try:
        r = requests.request(
            method,
            f"{_BASE}{path}",
            headers=headers,
            params=params or {},
            timeout=timeout,
        )
    except requests.RequestException as e:
        err = ProviderUnreachable(f"GetProspect network error: {e}")
        err.provider = "getprospect"
        raise err from e

    try:
        body = r.json()
    except Exception:
        body = {}

    detail = (
        (body.get("message") if isinstance(body, dict) else None)
        or (body.get("error") if isinstance(body, dict) else None)
        or f"HTTP {r.status_code}"
    )
    low = str(detail).lower()

    if r.status_code in (401, 403) or "unauthorized" in low or "invalid" in low or "token" in low:
        err = AuthError(f"GetProspect rejected the API key: {detail}")
        err.provider = "getprospect"
        raise err
    if r.status_code in (402, 451) or "quota" in low or "credit" in low or "limit" in low:
        err = QuotaExhaustedError(f"GetProspect quota / plan limit hit: {detail}")
        err.provider = "getprospect"
        raise err
    if r.status_code == 429:
        err = RateLimitError(f"GetProspect rate-limited: {detail}")
        err.provider = "getprospect"
        raise err
    if r.status_code >= 400:
        err = ProviderUnreachable(f"GetProspect HTTP {r.status_code}: {detail}")
        err.provider = "getprospect"
        raise err

    return body if isinstance(body, dict) else {"raw": body}


def account() -> dict:
    """Quota / account info. Free."""
    return _request("GET", "/user")


def _verified_to_score(status: Optional[str]) -> int:
    if not status:
        return 50
    return {
        "verified": 95,
        "valid": 90,
        "ok": 88,
        "risky": 40,
        "catchall": 55,
        "catch_all": 55,
        "unknown": 50,
        "invalid": 5,
    }.get(status.lower(), 50)


def email_finder(domain: str, first_name: str, last_name: str) -> dict:
    body = _request(
        "GET",
        "/email/find",
        {"firstName": first_name, "lastName": last_name, "domain": domain},
    )
    # GetProspect indicates a miss via status='not_found' or missing email
    status = (body.get("verifiedStatus") or body.get("status") or "").lower()
    email = body.get("email")
    if not email or status == "not_found":
        return {"email": None}
    return {
        "email": email,
        "score": _verified_to_score(body.get("verifiedStatus")),
        "position": body.get("position") or body.get("title"),
        "linkedin": body.get("linkedin"),
        "raw": body,
    }
