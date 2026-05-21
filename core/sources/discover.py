"""Discover companies via Brave search dorks + Gemini extraction.

Pipeline:
1. Build Google dorks from Keyword Builder rules (sector × signal).
2. Run each dork through Brave Search API → SERP entries.
3. Optional: pass the batch through Gemini to extract structured
   {company, signal_summary, source_url} tuples. Heuristic extraction
   gets the long tail wrong; the LLM step is one batched call.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from core.keywords import build_google_dorks
from core.sources import brave

_EXTRACTION_PROMPT = """\
You are extracting startup leads from a batch of search-engine results.

Sector focus: {sector}
Signal of interest: {signal}
Region: {region}

For each result, decide if it describes a real Indian startup hitting the
signal above (e.g. funding round, hire, product launch, accelerator,
expansion). If yes, extract the **company name** and a one-line **signal
summary** (with specific facts: amount, role, product, geography). Ignore
results that are listicles, jobs boards, irrelevant industries, or
non-Indian companies.

Output strict JSON:

{{
  "leads": [
    {{
      "company": "...",
      "signal_summary": "raised $4M Series A from Fireside, March 2026",
      "source_url": "https://..."
    }}
  ]
}}

No prose outside the JSON. If no valid leads, return {{"leads": []}}.

## Search results

{results_block}
"""


def run_dorks(sector: str, signal: str, region: str = "India", max_dorks: int = 4, per_dork: int = 8) -> list[dict]:
    """Execute Google dorks for the given sector × signal. Returns raw SERP entries."""
    dorks = build_google_dorks(sector, signal)[:max_dorks]
    out: list[dict] = []
    seen_urls: set[str] = set()
    for d in dorks:
        try:
            results = brave.search(d, count=per_dork, country="IN" if region.lower() == "india" else "US")
        except Exception as e:
            results = []
            out.append({"_error": f"dork '{d}' failed: {e}"})
            continue
        for r in results:
            url = r.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                out.append({**r, "_dork": d})
    return out


def _format_for_llm(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        if r.get("_error"):
            continue
        lines.append(f"[{i}] {r.get('title', '')}\n    URL: {r.get('url', '')}\n    {r.get('description', '')}")
    return "\n\n".join(lines)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_companies(results: list[dict], sector: str, signal: str, region: str = "India") -> list[dict]:
    """Run Gemini over the SERP batch to pull structured leads."""
    from core.llm.gemini import generate

    block = _format_for_llm(results)
    if not block.strip():
        return []
    prompt = _EXTRACTION_PROMPT.format(sector=sector, signal=signal, region=region, results_block=block)
    raw = generate(prompt, temperature=0.2, max_tokens=1500)
    cleaned = _FENCE.sub("", raw).strip()
    try:
        data = json.loads(cleaned)
        return data.get("leads", []) or []
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0)).get("leads", []) or []
            except Exception:
                pass
        return []


def domain_for(company: str) -> str | None:
    return brave.find_domain(company)
