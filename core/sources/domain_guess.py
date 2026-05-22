"""Free DNS-based domain guesser.

Given a company name like "Slurrp Farm", tries common slug + TLD combinations
and returns the first one that resolves via DNS. No API key, no rate limit,
no cost. Catches the obvious cases (most Indian D2C / FMCG brands use
predictable domains). Falls back to None for tricky names — the user
types the domain by hand in that case.
"""
from __future__ import annotations

import re
import socket
from typing import Iterable, Optional

# Order matters: cheapest, most-common TLDs first to short-circuit faster.
_DEFAULT_TLDS: tuple[str, ...] = ("com", "in", "co.in", "io", "co", "net", "org")

# Business suffixes we strip before slugging
_NOISE_PATTERNS = [
    r"\b(private|pvt\.?|pvt\.?\s*ltd\.?|ltd\.?|inc\.?|llc|llp|corp\.?|corporation|company|co\.?)\b",
    r"\bthe\b",
]


def _slug_candidates(company: str) -> list[str]:
    """Return candidate slug variations for a company name, most-likely first."""
    s = company.lower()
    for pat in _NOISE_PATTERNS:
        s = re.sub(pat, "", s)
    # Keep alphanumerics, spaces, hyphens; drop everything else
    s = re.sub(r"[^\w\s-]", "", s).strip()
    words = [w for w in s.split() if w]
    if not words:
        return []

    no_space = "".join(words)
    hyphenated = "-".join(words)
    first = words[0]

    out = [no_space]
    if hyphenated != no_space:
        out.append(hyphenated)
    if first not in out and len(first) > 2:
        out.append(first)
    return out


def _resolves(domain: str, timeout: float = 2.0) -> bool:
    """True if the domain has at least one resolving A record."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(domain)
        return True
    except (socket.gaierror, socket.timeout, OSError):
        return False
    finally:
        socket.setdefaulttimeout(None)


def guess_domain(company: str, tlds: Iterable[str] = _DEFAULT_TLDS) -> Optional[str]:
    """Return the first plausible domain that resolves, or None."""
    if not company or not company.strip():
        return None
    for slug in _slug_candidates(company):
        for tld in tlds:
            d = f"{slug}.{tld}"
            if _resolves(d):
                return d
    return None
