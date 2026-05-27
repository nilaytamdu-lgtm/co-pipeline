"""Hunter.io v2 API wrapper.

Free tier: 25 searches/mo + 50 verifications/mo. We treat searches as
precious — always prefer Email Finder (you know the name) over Domain
Search (broad sweep). Verify only when downstream cares.

Endpoints used:
- /v2/email-finder?domain=X&first_name=A&last_name=B
- /v2/domain-search?domain=X (+ optional &type=personal&limit=N)
- /v2/email-verifier?email=X
- /v2/account  (free, useful for quota checks)

Errors: instead of bubbling up raw HTTPError, this module raises typed
exceptions from core.enrich.errors so the orchestrator can tell apart
'key bad' / 'quota gone' / 'no match' and surface the right warning.
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

_BASE = "https://api.hunter.io/v2"


def _key() -> str:
    k = secret("apis", "hunter_api_key")
    if not k:
        raise RuntimeError("Hunter API key missing. Set apis.hunter_api_key in secrets.toml.")
    return k


def _request(path: str, params: dict, timeout: int = 20) -> dict:
    """GET wrapper that translates HTTP / body errors into typed exceptions."""
    try:
        r = requests.get(f"{_BASE}{path}", params=params, timeout=timeout)
    except requests.RequestException as e:
        err = ProviderUnreachable(f"Hunter network error: {e}")
        err.provider = "hunter"
        raise err from e

    # Try to parse JSON body for richer error info (Hunter sends errors[] inside JSON)
    try:
        body = r.json()
    except Exception:
        body = {}

    errors = body.get("errors") or []
    error_ids = " ".join((e.get("id") or "") for e in errors).lower()
    detail = (errors[0].get("details") if errors else "") or f"HTTP {r.status_code}"

    if r.status_code in (401, 403) or "invalid_api_key" in error_ids or "unauthorized" in error_ids:
        err = AuthError(f"Hunter rejected the API key: {detail}")
        err.provider = "hunter"
        raise err
    if r.status_code in (402, 451) or "exceeded" in error_ids or "quota" in error_ids or "limit" in error_ids:
        err = QuotaExhaustedError(f"Hunter quota / plan limit hit: {detail}")
        err.provider = "hunter"
        raise err
    if r.status_code == 429:
        err = RateLimitError(f"Hunter rate-limited: {detail}")
        err.provider = "hunter"
        raise err
    if r.status_code >= 400:
        err = ProviderUnreachable(f"Hunter HTTP {r.status_code}: {detail}")
        err.provider = "hunter"
        raise err
    return body


def account() -> dict:
    """Quota/account info. Doesn't consume credits."""
    return _request("/account", {"api_key": _key()}).get("data", {})


def email_finder(domain: str, first_name: str, last_name: str) -> dict:
    """Most credit-efficient path: one named POC at a known domain."""
    body = _request(
        "/email-finder",
        {"api_key": _key(), "domain": domain, "first_name": first_name, "last_name": last_name},
    )
    data = body.get("data", {}) or {}
    return {
        "email": data.get("email"),
        "score": data.get("score"),
        "position": data.get("position"),
        "linkedin": data.get("linkedin"),
        "verification_status": (data.get("verification") or {}).get("status"),
        "sources_count": len(data.get("sources") or []),
        "raw": data,
    }


def domain_search(
    domain: str,
    limit: int = 10,
    seniority: Optional[str] = None,
    department: Optional[str] = None,
) -> list[dict]:
    """All discoverable emails for a domain. Expensive — call when no POC name is known."""
    params = {"api_key": _key(), "domain": domain, "limit": limit}
    if seniority:
        params["seniority"] = seniority  # junior, senior, executive
    if department:
        params["department"] = department
    body = _request("/domain-search", params)
    data = body.get("data", {}) or {}
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
    body = _request("/email-verifier", {"api_key": _key(), "email": email})
    data = body.get("data", {}) or {}
    return {
        "status": data.get("status"),
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
