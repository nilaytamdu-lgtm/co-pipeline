"""Rule-based keyword/query generator for prospecting.

Produces ready-to-paste strings for:
- Apollo: industries, keywords, titles, location, employee range
- LinkedIn: boolean search query (works in free LinkedIn and Sales Navigator)
- Google: dorks to surface news / lists / accelerator cohorts

Optional Gemini polish layer expands the rule-based output with sector-niche
terms the static map can't anticipate.
"""
from __future__ import annotations

from core.config import POC_HIERARCHY

# Industries here use Apollo's display names. Tweak as you find what
# actually returns volume in your account.
SECTOR_PROFILE = {
    "SaaS + AI + Automation": {
        "industries": ["Computer Software", "Information Technology and Services", "Internet"],
        "keywords": ["SaaS", "B2B software", "AI platform", "machine learning", "automation", "developer tools"],
        "linkedin_boolean": '("SaaS" OR "B2B software" OR "AI platform" OR "automation") AND ("founder" OR "CEO" OR "Head of Growth")',
        "google_seed": "SaaS startup India",
    },
    "FMCG / Food & Beverage / Consumer Brands / Consumer E-commerce": {
        "industries": ["Consumer Goods", "Food & Beverages", "Retail", "Food Production", "Consumer Services"],
        "keywords": ["D2C", "direct-to-consumer", "FMCG", "consumer brand", "food brand", "F&B", "QSR", "packaged food", "personal care", "beauty"],
        "linkedin_boolean": '("D2C" OR "direct-to-consumer" OR "FMCG" OR "consumer brand" OR "food brand" OR "QSR") AND ("founder" OR "co-founder" OR "Head of Growth")',
        "google_seed": "D2C brand India OR FMCG startup",
    },
    "Logistics & Supply Chain + Climate-tech / Sustainability": {
        "industries": ["Logistics and Supply Chain", "Transportation/Trucking/Railroad", "Renewables & Environment", "Environmental Services"],
        "keywords": ["logistics", "supply chain", "last mile", "fleet", "warehouse", "climate tech", "cleantech", "sustainability", "carbon", "EV"],
        "linkedin_boolean": '("logistics" OR "supply chain" OR "climate tech" OR "cleantech" OR "EV") AND ("founder" OR "CEO" OR "Head of Operations")',
        "google_seed": "logistics startup India OR climate-tech",
    },
    "Fintech + Edtech": {
        "industries": ["Financial Services", "Banking", "Education Management", "E-Learning", "Investment Management"],
        "keywords": ["fintech", "neobank", "payments", "lending", "wealth", "insurtech", "edtech", "online learning", "K-12", "upskilling"],
        "linkedin_boolean": '("fintech" OR "neobank" OR "payments" OR "edtech" OR "online learning") AND ("founder" OR "CEO" OR "Head of Product")',
        "google_seed": "fintech startup India OR edtech",
    },
    "Healthtech + NGOs / Social Impact": {
        "industries": ["Hospital & Health Care", "Medical Practice", "Health, Wellness and Fitness", "Non-profit Organization Management", "Civic & Social Organization"],
        "keywords": ["healthtech", "digital health", "telemedicine", "diagnostics", "wellness", "NGO", "social impact", "non-profit", "social enterprise"],
        "linkedin_boolean": '("healthtech" OR "digital health" OR "telemedicine" OR "social impact" OR "non-profit") AND ("founder" OR "CEO" OR "Executive Director")',
        "google_seed": "healthtech startup India OR social-impact NGO",
    },
}

SIGNAL_PROFILE = {
    "Recent funding": {
        "keywords": ["raised", "seed round", "Series A", "Series B", "pre-seed", "funding round"],
        "google_dorks": [
            'site:inc42.com "{sector}" "raised"',
            'site:entrackr.com "{sector}" funding',
            'site:yourstory.com "{sector}" raises',
            'site:vccircle.com "{sector}"',
        ],
    },
    "Hiring activity": {
        "keywords": ["we're hiring", "join us", "growth team", "operations team", "now hiring"],
        "google_dorks": [
            'site:wellfound.com "{sector}" India',
            'site:linkedin.com/jobs "{sector}" India',
            '"we are hiring" "{sector}" India',
        ],
    },
    "Product / feature launch": {
        "keywords": ["launching", "introducing", "new product", "now live", "beta launch"],
        "google_dorks": [
            'site:producthunt.com "{sector}" India',
            'site:betalist.com "{sector}"',
            '"introducing" "{sector}" India',
        ],
    },
    "Accelerator / incubator participation": {
        "keywords": ["Y Combinator", "Sequoia Surge", "Antler", "100X.VC", "Axilor", "Techstars India"],
        "google_dorks": [
            'site:ycombinator.com/companies "{sector}" India',
            '"Sequoia Surge" cohort "{sector}"',
            '"Antler India" "{sector}"',
        ],
    },
    "Expansion activity": {
        "keywords": ["expanding to", "now in", "launches in", "international expansion", "new market"],
        "google_dorks": [
            '"{sector}" "expanding to" India',
            '"{sector}" "launches in" India',
        ],
    },
    "Increased founder activity": {
        "keywords": ["founder", "co-founder", "building", "thoughts on"],
        "google_dorks": [
            'site:linkedin.com/posts "{sector}" India founder',
            'site:twitter.com "{sector}" India founder',
        ],
    },
}

SIZE_BANDS = {
    "Seed (1-20)": "1,11",          # Apollo bucket "1,10" + "11,20"
    "Early (20-100)": "21,50,51,100",
    "Growth (100-500)": "101,200,201,500",
    "Late (500+)": "501,1000,1001,5000",
}


def build_apollo(sector: str, signal: str, region: str, size_band: str) -> dict:
    s = SECTOR_PROFILE.get(sector, {})
    sig = SIGNAL_PROFILE.get(signal, {})
    titles = [h.split(" / ")[0] for h in POC_HIERARCHY]  # primary title per tier
    return {
        "industries": ", ".join(s.get("industries", [])),
        "keywords": ", ".join(s.get("keywords", []) + sig.get("keywords", [])),
        "person_titles": ", ".join(titles),
        "locations": region,
        "employee_ranges": SIZE_BANDS.get(size_band, ""),
    }


def build_linkedin(sector: str, signal: str, region: str) -> str:
    s = SECTOR_PROFILE.get(sector, {})
    base = s.get("linkedin_boolean", "")
    sig_kw = SIGNAL_PROFILE.get(signal, {}).get("keywords", [])
    sig_clause = " OR ".join(f'"{k}"' for k in sig_kw[:3])
    return f'{base} AND ({sig_clause}) AND "{region}"' if sig_clause else f'{base} AND "{region}"'


def build_google_dorks(sector: str, signal: str) -> list[str]:
    s = SECTOR_PROFILE.get(sector, {})
    seed = s.get("google_seed", sector)
    dorks = SIGNAL_PROFILE.get(signal, {}).get("google_dorks", [])
    return [d.format(sector=seed) for d in dorks]


GEMINI_POLISH_PROMPT = """\
You expand and refine prospecting search queries for an Indian student-consulting org.

Sector: {sector}
Signal to detect: {signal}
Region focus: {region}

Existing rule-based output (treat as a starting point, not a ceiling):
- LinkedIn boolean: {linkedin}
- Google dorks: {dorks}
- Apollo keywords: {apollo_keywords}

Generate, as strict JSON:
{{
  "niche_keywords": ["...", "..."],          // 6 sub-segment terms specific to {sector} in India
  "linkedin_variants": ["...", "...", "..."],// 3 alternative LinkedIn boolean queries with different angles
  "google_dorks": ["...", "...", "...", "...", "..."],  // 5 fresh Google dorks for this signal
  "negative_terms": ["...", "..."]           // 4 terms to exclude to cut noise (e.g. "case study", "intern")
}}

Output JSON only. No prose.
"""
