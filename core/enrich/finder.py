"""Orchestrates email discovery across providers.

Order of operations:
1. If domain + first/last name → Hunter Email Finder → fall back to Snov Email Finder.
2. Else if domain only → Hunter Domain Search → fall back to Snov Domain Search,
   then pick the best POC by the org's hierarchy (Founder → Ops/Growth → Product → TA).
3. Verify the chosen email if `verify=True`.

Snov/Skrapp/Dropcontact slot in here as their keys arrive. Each provider
module is independent — if its credentials are absent we skip it silently.
"""
from __future__ import annotations

from typing import Optional

from core.config import secret
from core.enrich import hunter, snov

_HIERARCHY_KEYWORDS = [
    # tier 1 — Founder / Co-founder
    ["founder", "co-founder", "cofounder", "ceo", "chief executive"],
    # tier 2 — Ops / Growth
    ["coo", "chief operating", "head of growth", "growth lead", "head of operations", "vp operations"],
    # tier 3 — Product / Strategy
    ["chief product", "cpo", "head of product", "head of strategy", "vp product"],
    # tier 4 — Hiring / TA
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


def find_email(
    domain: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    verify: bool = False,
) -> dict:
    """Try named-finder providers first (1 credit each), then broad domain search."""
    # Named-finder chain
    if first_name and last_name:
        if _has_hunter():
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
                    }
            except Exception as e:
                # fall through to Snov
                pass
        if _has_snov():
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
                    }
            except Exception:
                pass

    # Broad domain search chain
    candidates: list[dict] = []
    if _has_hunter():
        try:
            candidates.extend(hunter.domain_search(domain, limit=10))
        except Exception:
            pass
    if not candidates and _has_snov():
        try:
            candidates.extend(snov.domain_search(domain, limit=10))
        except Exception:
            pass

    best = pick_best_poc(candidates)
    if best:
        return {
            "email": best["email"],
            "score": best.get("confidence"),
            "position": best.get("position"),
            "linkedin": best.get("linkedin"),
            "source": "hunter:domain_search" if best in candidates[: len(candidates)] else "snov:domain_search",
            "verification": (hunter.verify(best["email"]) if _has_hunter() and verify else None) if best.get("email") else None,
            "alternates": [c for c in candidates if c is not best][:3],
        }

    return {"email": None, "source": "no_match", "alternates": []}
