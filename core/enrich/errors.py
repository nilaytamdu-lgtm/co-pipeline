"""Typed errors for the email-enrichment chain.

We distinguish 'no match found' (normal — this lead doesn't have a findable
email) from 'provider rejected us' (auth bad, credits gone, rate limited).
The former is silent and routes the row to LinkedIn outreach. The latter
should stop the batch from hammering a dead provider and surface a clear
warning to the user.
"""
from __future__ import annotations


class EnrichmentError(Exception):
    """Base for typed enrichment provider errors. Carries the provider name."""

    provider: str = "unknown"


class AuthError(EnrichmentError):
    """Provider says our credentials are invalid (401 / 403 / OAuth failure).

    Action: user must rotate the key in secrets.toml or the Streamlit Cloud
    secrets manager. Re-trying with the same key will keep failing.
    """


class QuotaExhaustedError(EnrichmentError):
    """Provider says we're out of credits or over a plan limit
    (402 / 451 / body says 'limit reached').

    Action: wait for next monthly reset, upgrade the plan, or swap in
    a different account's key. Re-trying inside the same batch is pointless.
    """


class RateLimitError(EnrichmentError):
    """Provider says we're sending too fast (429).

    Action: wait a minute and re-run. Usually transient, NOT terminal —
    the batch can continue, this row just got unlucky.
    """


class ProviderUnreachable(EnrichmentError):
    """Network failure, timeout, or unexpected response shape.

    Action: check internet / provider status page. Often transient.
    """
