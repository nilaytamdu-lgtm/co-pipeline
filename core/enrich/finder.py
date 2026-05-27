"""Orchestrates email discovery across providers.

Provider chain for the named-finder path (when first + last + domain known):
1. Hunter (25 free/mo)
2. Snov (50 free/mo)
3. Skrapp (150 free/mo)
4. GetProspect (100 free/mo)

Total free capacity per analyst account: 325 finder credits/mo. If five team
analysts each sign up, that's 1,625/mo before anyone pays.

Domain-search fallback (no name known): Hunter + Snov only — Skrapp and
GetProspect's domain search endpoints aren't worth the complexity for our
use case.

Caller passes `skip_providers={"hunter", "snov"}` to disable providers that
already died in this batch (auth / quota). The returned dict has a
`fatal_error` field whenever a provider just fatally died — caller should
add that provider to its skip-set so we don't keep hammering a dead key.
"""
from __future__ import annotations

from typing import Iterable, Optional

from core.config import secret
from core.enrich import getprospect, hunter, skrapp, snov
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


def _has_hunter() -> bool:
    return bool(secret("apis", "hunter_api_key"))


def _has_snov() -> bool:
    return bool(secret("apis", "snov_user_id")) and bool(secret("apis", "snov_secret"))


def _has_skrapp() -> bool:
    return bool(secret("apis", "skrapp_api_key"))


def _has_getprospect() -> bool:
    return bool(secret("apis", "getprospect_api_key"))


def _is_fatal(e: Exception) -> bool:
    """Auth + quota errors mean the provider is dead for the rest of the batch.
    Rate limits and network blips are NOT fatal — retry next row."""
    return isinstance(e, (AuthError, QuotaExhaustedError))


def _try_named_finder(
    provider_name: str,
    has_fn,
    finder_fn,
    domain: str,
    first_name: str,
    last_name: str,
    skip: set,
    errors: list,
    fatal_holder: list,
):
    """Call a single named-email-finder provider, handling errors uniformly.

    Returns the result dict (with 'email' possibly set) or None if the
    provider was skipped / errored. Mutates `skip`, `errors`, `fatal_holder`.
    """
    if provider_name in skip or not has_fn():
        return None
    try:
        hit = finder_fn(domain, first_name, last_name)
        if hit.get("email"):
            return hit
    except EnrichmentError as e:
        if _is_fatal(e):
            if not fatal_holder:
                fatal_holder.append({
                    "provider": provider_name,
                    "kind": type(e).__name__,
                    "message": str(e),
                })
            skip.add(provider_name)
        else:
            errors.append({
                "provider": provider_name,
                "kind": type(e).__name__,
                "message": str(e),
            })
    return None


def find_email(
    domain: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    verify: bool = False,
    skip_providers: Optional[Iterable[str]] = None,
) -> dict:
    """Try named-finder providers first (1 credit each), then broad domain search.

    Returns a dict with `email` (str or None). When a provider fatally
    fails (auth or quota), `fatal_error` is set to
    `{provider, kind, message}` so caller marks the provider as dead.
    `errors` lists non-fatal hiccups (rate-limit, network) — informational.
    """
    skip = set(skip_providers or ())
    errors: list[dict] = []
    fatal_holder: list[dict] = []  # one-element list used as mutable cell

    # ----- Named-finder chain (cheapest path) -----
    if first_name and last_name:
        chain = [
            ("hunter", _has_hunter, hunter.email_finder),
            ("snov", _has_snov, snov.email_finder),
            ("skrapp", _has_skrapp, skrapp.email_finder),
            ("getprospect", _has_getprospect, getprospect.email_finder),
        ]
        for provider_name, has_fn, finder_fn in chain:
            hit = _try_named_finder(
                provider_name, has_fn, finder_fn, domain, first_name, last_name,
                skip, errors, fatal_holder,
            )
            if hit:
                # Choose a verifier that's still alive (Hunter preferred, falls back to Snov)
                verification = None
                if verify:
                    try:
                        if _has_hunter() and "hunter" not in skip:
                            verification = hunter.verify(hit["email"])
                        elif _has_snov() and "snov" not in skip:
                            verification = snov.verify(hit["email"])
                    except EnrichmentError:
                        verification = None
                return {
                    "email": hit["email"],
                    "score": hit.get("score"),
                    "position": hit.get("position"),
                    "linkedin": hit.get("linkedin"),
                    "source": f"{provider_name}:email_finder",
                    "verification": verification,
                    "errors": errors,
                    "fatal_error": fatal_holder[0] if fatal_holder else None,
                }

    # ----- Broad domain-search fallback (Hunter + Snov only) -----
    candidates: list[dict] = []
    if _has_hunter() and "hunter" not in skip:
        try:
            candidates.extend(hunter.domain_search(domain, limit=10))
        except EnrichmentError as e:
            if _is_fatal(e):
                if not fatal_holder:
                    fatal_holder.append({"provider": "hunter", "kind": type(e).__name__, "message": str(e)})
                skip.add("hunter")
            else:
                errors.append({"provider": "hunter", "kind": type(e).__name__, "message": str(e)})
    if not candidates and _has_snov() and "snov" not in skip:
        try:
            candidates.extend(snov.domain_search(domain, limit=10))
        except EnrichmentError as e:
            if _is_fatal(e):
                if not fatal_holder:
                    fatal_holder.append({"provider": "snov", "kind": type(e).__name__, "message": str(e)})
                skip.add("snov")
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
            "fatal_error": fatal_holder[0] if fatal_holder else None,
        }

    return {
        "email": None,
        "source": "no_match",
        "alternates": [],
        "errors": errors,
        "fatal_error": fatal_holder[0] if fatal_holder else None,
    }
