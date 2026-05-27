"""Orchestrates email discovery across providers.

Order of operations:
1. If domain + first/last name -> Hunter Email Finder -> fall back to Snov Email Finder.
2. Else if domain only -> Hunter Domain Search -> fall back to Snov Domain Search,
   then pick the best POC by the org's hierarchy (Founder -> Ops/Growth -> Product -> TA).
3. Verify the chosen email if `verify=True`.

Caller can pass `skip_providers={"hunter", "snov"}` to disable providers
that already died in this batch (auth/quota). The returned dict carries a
`fatal_error` field whenever a provider just died — the caller should add
that provider to its skip-set so we don't keep hammering a dead key.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.config import secret
from core.enrich import hunter, snov
from core.enrich.errors import (
    AuthError,
    EnrichmentError,
    ProviderUnreachable,
    QuotaExhaustedError,
    RateLimitError,
)

_HIERARCHY_KEYWORDS = [
    ["founder", "co-founder", "cofounder", "ceo", "chief executive"],
    ["coo", "chief operating", "head of growth", "growth lead", "head of operations", "vp operations"],
    ["chief product", "cpo", "head of product", "head of strategy", "vp product"],
    ["talent", "recruiting", "people", "hr"],
]


def _tier(position: Optional[str]) -> int:
    p = (position or "").lower()
    for i, words in enumerate(_HIERARCHY_KEYWORDS):
        if any(w in p for w in words):
            return i
    return 99


def pick_best_poc(candidates: list[dict]) -> Optional[dict]:
    if not candidates:
        return None
    scored = sorted(candidates, key=lambda c: (_tier(c.get("position")), -(c.get("confidence") or 0)))
    return scored[0]


def _has_snov() -> bool:
    return bool(secret("apis", "snov_user_id")) and bool(secret("apis", "snov_secret"))


def _has_hunter() -> bool:
    return bool(secret("apis", "hunter_api_key"))


def _is_fatal(e: Exception) -> bool:
    """Auth + quota errors mean the provider is dead for the rest of the batch.
    Rate limits and network blips are NOT fatal — retry next row."""
    return isinstance(e, (AuthError, QuotaExhaustedError))


def find_email(
    domain: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    verify: bool = False,
    skip_providers: Optional[Iterable[str]] = None,
) -> dict:
    """Try named-finder providers first (1 credit each), then broad domain search.

    Returns a dict that always has `email` (str or None). When a provider
    fatally fails (auth or quota), `fatal_error` is set to
    `{provider, kind, message}` so the caller can mark that provider as
    dead for the remainder of the batch.

    `errors` lists non-fatal hiccups (rate-limit, network) — informational only.
    """
    skip = set(skip_providers or ())
    errors: list[dict] = []
    fatal_error: Optional[dict] = None

    # Named-finder chain (cheapest path)
    if first_name and last_name:
        if _has_hunter() and "hunter" not in skip:
            try:
                hit = hunter.email_finder(domain, first_name, last_name)
                if hit.get("email"):
                    return {
                        "email": hit["email"],
                        "score": hit.get("score"),
                        "position": hit.get("position"),
                        "linkedin": hit.get("linkedin"),
                        "source": "hunter:email_finder",
                        "verification": hunter.verify(hit["email"]) if verify else None,
                        "errors": errors,
                    }
            except EnrichmentError as e:
                if _is_fatal(e):
                    fatal_error = {"provider": "hunter", "kind": type(e).__name__, "message": str(e)}
                    skip = skip | {"hunter"}
                else:
                    errors.append({"provider": "hunter", "kind": type(e).__name__, "message": str(e)})

        if _has_snov() and "snov" not in skip:
            try:
                hit = snov.email_finder(domain, first_name, last_name)
                if hit.get("email"):
                    return {
                        "email": hit["email"],
                        "score": hit.get("score"),
                        "position": None,
                        "linkedin": None,
                        "source": "snov:email_finder",
                        "verification": snov.verify(hit["email"]) if verify else None,
                        "errors": errors,
                        "fatal_error": fatal_error,
                    }
            except EnrichmentError as e:
                if _is_fatal(e):
                    snov_fatal = {"provider": "snov", "kind": type(e).__name__, "message": str(e)}
                    fatal_error = fatal_error or snov_fatal
                    skip = skip | {"snov"}
                else:
                    errors.append({"provider": "snov", "kind": type(e).__name__, "message": str(e)})

    # Broad domain-search chain (expensive — only if no email yet)
    candidates: list[dict] = []
    if _has_hunter() and "hunter" not in skip:
        try:
            candidates.extend(hunter.domain_search(domain, limit=10))
        except EnrichmentError as e:
            if _is_fatal(e):
                fatal_error = fatal_error or {"provider": "hunter", "kind": type(e).__name__, "message": str(e)}
                skip = skip | {"hunter"}
            else:
                errors.append({"provider": "hunter", "kind": type(e).__name__, "message": str(e)})
    if not candidates and _has_snov() and "snov" not in skip:
        try:
            candidates.extend(snov.domain_search(domain, limit=10))
        except EnrichmentError as e:
            if _is_fatal(e):
                fatal_error = fatal_error or {"provider": "snov", "kind": type(e).__name__, "message": str(e)}
                skip = skip | {"snov"}
            else:
                errors.append({"provider": "snov", "kind": type(e).__name__, "message": str(e)})

    best = pick_best_poc(candidates)
    if best and best.get("email"):
        return {
            "email": best["email"],
            "score": best.get("confidence"),
            "position": best.get("position"),
            "linkedin": best.get("linkedin"),
            "source": "domain_search",
            "verification": (hunter.verify(best["email"]) if _has_hunter() and verify else None),
            "alternates": [c for c in candidates if c is not best][:3],
            "errors": errors,
            "fatal_error": fatal_error,
        }

    return {"email": None, "source": "no_match", "alternates": [], "errors": errors, "fatal_error": fatal_error}
