"""Skrapp.io API wrapper.

Free tier: 150 finder credits/month (significantly more generous than Hunter
or Snov). Auth: X-Access-Key header. Email finder takes first_name + last_name
+ domain, just like Hunter.

Docs: https://skrapp.io/api/docs

Errors: raises typed exceptions from core.enrich.errors so the orchestrator
can tell apart 'creds bad' / 'credits gone' / 'no match' and stop hammering
a dead key.
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

_BASE = "https://api.skrapp.io/api/v3"


def _key() -> str:
    k = secret("apis", "skrapp_api_key")
    if not k:
        raise RuntimeError("Skrapp API key missing. Set apis.skrapp_api_key in secrets.toml.")
    return k


def _request(method: str, path: str, params: Optional[dict] = None, timeout: int = 20) -> dict:
    """Wrap requests + translate HTTP / body errors into typed exceptions.

    Skrapp returns 404 on 'no match found', which is NOT an error in our
    model — we return a sentinel dict the caller treats as a normal miss.
    """
    headers = {"X-Access-Key": _key()}
    try:
        r = requests.request(
            method,
            f"{_BASE}{path}",
            headers=headers,
            params=params or {},
            timeout=timeout,
        )
    except requests.RequestException as e:
        err = ProviderUnreachable(f"Skrapp network error: {e}")
        err.provider = "skrapp"
        raise err from e

    # 404 = 'no match found', not an actual error
    if r.status_code == 404:
        return {"_no_match": True}

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

    if r.status_code in (401, 403) or "unauthorized" in low or "invalid" in low:
        err = AuthError(f"Skrapp rejected the API key: {detail}")
        err.provider = "skrapp"
        raise err
    if r.status_code in (402, 451) or "quota" in low or "credit" in low or "limit" in low:
        err = QuotaExhaustedError(f"Skrapp quota / plan limit hit: {detail}")
        err.provider = "skrapp"
        raise err
    if r.status_code == 429:
        err = RateLimitError(f"Skrapp rate-limited: {detail}")
        err.provider = "skrapp"
        raise err
    if r.status_code >= 400:
        err = ProviderUnreachable(f"Skrapp HTTP {r.status_code}: {detail}")
        err.provider = "skrapp"
        raise err

    return body if isinstance(body, dict) else {"raw": body}


def account() -> dict:
    """Quota / account info. Free, doesn't consume credits."""
    # Skrapp docs have shifted between /profile and /account historically;
    # try the documented one first, fall back gracefully.
    try:
        return _request("GET", "/profile")
    except ProviderUnreachable:
        return _request("GET", "/account")


def email_finder(domain: str, first_name: str, last_name: str) -> dict:
    body = _request(
        "GET",
        "/find",
        {"first_name": first_name, "last_name": last_name, "domain": domain},
    )
    if body.get("_no_match"):
        return {"email": None}
    email = body.get("email")
    if not email:
        return {"email": None}
    return {
        "email": email,
        "score": body.get("accuracy") or body.get("confidence") or body.get("quality"),
        "position": body.get("position") or body.get("title"),
        "linkedin": body.get("linkedin") or body.get("linkedinUrl"),
        "raw": body,
    }
