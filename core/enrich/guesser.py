"""Pattern-based email guesser — no API, no quota, no credits.

Last-resort fallback when every paid provider in the chain has died or
come up empty. Generates the most likely email format given a first
name + last name + domain. Top candidate goes into POC Email; alternates
are returned so the analyst can try them manually if the first bounces.

Default pattern order is tuned for Indian D2C / consumer-brand founders,
where `firstname@domain` is the dominant pattern at small companies
(< 50 employees). For larger orgs, `firstname.lastname@domain` is the
safer bet — caller can flip `prefer_founder_format=False`.

THESE ARE GUESSES. They will bounce sometimes. Use at your own
bounce-rate risk. Bounce > 5% damages sender reputation.
"""
from __future__ import annotations

from typing import Optional


def _clean_domain(domain: str) -> str:
    if not domain:
        return ""
    d = domain.strip().lower()
    for p in ("https://", "http://"):
        if d.startswith(p):
            d = d[len(p):]
    d = d.rstrip("/").split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


# Business-suffix words to strip when deriving a domain slug from a company name
_BIZ_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llp", "inc", "incorporated",
    "corp", "corporation", "co", "company", "group", "industries",
    "enterprises", "ventures", "holdings", "international", "global",
    "technologies", "technology", "tech", "solutions", "services",
    "systems", "labs", "studio", "studios", "the", "and", "&",
}


def derive_domain_from_name(company: str, tld: str = "com") -> str:
    """Last-resort: build a plausible domain from a company name without DNS check.

    For 'Slurrp Farm Pvt Ltd' returns 'slurrpfarm.com'. For 'Sleepy Owl Coffee'
    returns 'sleepyowlcoffee.com'. We strip business suffixes and join the
    remaining words, lowercase.

    These are guesses. Will sometimes be wrong. Use only when DNS resolution
    has already failed and you need *something*.
    """
    if not company:
        return ""
    # Replace punctuation with spaces
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in company.lower())
    tokens = [t for t in cleaned.split() if t and t not in _BIZ_SUFFIXES]
    if not tokens:
        return ""
    slug = "".join(tokens)
    return f"{slug}.{tld}"


def _slugify_name(name: Optional[str]) -> str:
    """Strip non-alphanumeric chars + lowercase. Handles names like
    'Meghana N.', 'A.K. Reddy', "O'Connor"."""
    if not name:
        return ""
    return "".join(c for c in name.lower() if c.isalnum())


def guess_email(
    first_name: Optional[str],
    last_name: Optional[str],
    domain: str,
    prefer_founder_format: bool = True,
) -> dict:
    """Build the most likely email candidate for `<name>@<domain>`.

    Returns a dict shaped like the provider results so callers can treat
    it uniformly:
      {
        "email": "first@domain",        # top guess
        "alternates": [...],            # next 4 most likely patterns
        "method": "guess",
        "confidence": "pattern_guess",
        "score": 30,                    # low — not verified
        "source": "guess:pattern",
      }
    or `{"email": None}` if we don't have enough to guess.
    """
    domain_clean = _clean_domain(domain)
    if not domain_clean:
        return {"email": None}

    first = _slugify_name(first_name)
    last = _slugify_name(last_name)

    if not first:
        return {"email": None}

    if last:
        founder_first_order = [
            f"{first}@{domain_clean}",
            f"{first}.{last}@{domain_clean}",
            f"{first[0]}.{last}@{domain_clean}",
            f"{first}{last}@{domain_clean}",
            f"{first}_{last}@{domain_clean}",
            f"{first[0]}{last}@{domain_clean}",
            f"{last}.{first}@{domain_clean}",
        ]
        standard_first_order = [
            f"{first}.{last}@{domain_clean}",
            f"{first}@{domain_clean}",
            f"{first[0]}.{last}@{domain_clean}",
            f"{first}{last}@{domain_clean}",
            f"{first}_{last}@{domain_clean}",
            f"{first[0]}{last}@{domain_clean}",
        ]
        candidates = founder_first_order if prefer_founder_format else standard_first_order
    else:
        candidates = [f"{first}@{domain_clean}"]

    return {
        "email": candidates[0],
        "alternates": candidates[1:5],
        "method": "guess",
        "confidence": "pattern_guess",
        "score": 30,
        "source": "guess:pattern",
    }
