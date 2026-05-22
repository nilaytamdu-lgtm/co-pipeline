import streamlit as st

# Individual sectors for prospecting. The combined groupings (e.g. Swaroop's
# SaaS + AI + Automation) are tracked separately in ANALYST_SECTORS below
# for team-level task management.
SECTORS = [
    "SaaS",
    "AI",
    "Automation",
    "FMCG",
    "Food & Beverage",
    "Consumer Brands",
    "Consumer E-commerce",
    "Logistics & Supply Chain",
    "Climate-tech",
    "Sustainability",
    "Fintech",
    "Edtech",
    "Healthtech",
    "NGOs",
    "Social Impact Organizations",
]

ANALYSTS = ["Swaroop", "Nilay", "Praneel", "Pranav", "Purav"]

# Which analyst owns which sectors (the combined buckets, broken out).
ANALYST_SECTORS = {
    "Swaroop": ["SaaS", "AI", "Automation"],
    "Nilay": ["FMCG", "Food & Beverage", "Consumer Brands", "Consumer E-commerce"],
    "Praneel": ["Logistics & Supply Chain", "Climate-tech", "Sustainability"],
    "Pranav": ["Fintech", "Edtech"],
    "Purav": ["Healthtech", "NGOs", "Social Impact Organizations"],
}

# Inverse mapping: sector -> analyst.
OWNERS = {sector: analyst for analyst, sectors in ANALYST_SECTORS.items() for sector in sectors}

QUOTA = 600  # per analyst, not per individual sector

POC_HIERARCHY = [
    "Founder / Co-founder",
    "Operations / Growth Lead",
    "Product / Strategy Lead",
    "Hiring / TA Lead",
]

# Concrete job titles per POC tier. These are what Apollo's title filter
# actually wants (Apollo doesn't match "Founder / Co-founder" as one query,
# it wants "Founder" OR "Co-founder" as separate entries).
JOB_TITLES = {
    "Founder / Co-founder": [
        "Founder",
        "Co-founder",
        "Cofounder",
        "CEO",
        "Chief Executive Officer",
        "Founder & CEO",
        "Founding Partner",
        "Managing Director",
    ],
    "Operations / Growth Lead": [
        "COO",
        "Chief Operating Officer",
        "Head of Operations",
        "VP Operations",
        "Director of Operations",
        "Head of Growth",
        "VP Growth",
        "Growth Lead",
        "Head of Business",
        "Business Head",
        "Director of Growth",
    ],
    "Product / Strategy Lead": [
        "CPO",
        "Chief Product Officer",
        "Head of Product",
        "VP Product",
        "Product Lead",
        "Director of Product",
        "Head of Strategy",
        "VP Strategy",
        "Director of Strategy",
        "Chief Strategy Officer",
    ],
    "Hiring / TA Lead": [
        "Head of Talent",
        "Talent Acquisition Lead",
        "TA Manager",
        "Talent Acquisition Manager",
        "Head of People",
        "Head of HR",
        "HR Head",
        "VP People",
        "Recruiting Lead",
        "Head of Recruiting",
    ],
}

SIGNALS = [
    "Recent funding",
    "Hiring activity",
    "Product / feature launch",
    "Accelerator / incubator participation",
    "Expansion activity",
    "Increased founder activity",
]

CONNECTION_STATUSES = ["Not Sent", "Sent", "Accepted", "Rejected", "Pending"]
MESSAGE_STATUSES = ["Not Sent", "Sent", "Replied", "No Reply"]
FOLLOWUP_STATUSES = ["Not Needed", "Follow-up 1 Sent", "Follow-up 2 Sent", "Closed - No Reply"]

# Tab names in the shared Google Sheet — must match exactly.
TAB_MASTER = "Engagement Led Outreach"
TAB_SIGNAL = "Signal Based Outreach"
TAB_ORG = "Organization Based Outreach"
TAB_PERSONAL = "Personal Outreach"

# Tab 1 — master overview
MASTER_SCHEMA = [
    "Organisation",
    "POC",
    "POC LinkedIn",
    "POC Connection Status",
    "Message to POC",
    "POC Message Status",
    "Follow Up Status (if no reply)",
    "Follow Up Message",
    "Meet Scheduled (if replied)",
]

# Tab 2 — Signal Based Outreach (Channel-2A), primary tab for the app.
# Adds POC Job Title + POC Email vs the team's existing tab (needed for Nilay's personal-sheet spec
# and for the email-finder chain).
SIGNAL_SCHEMA = [
    "Sr No.",
    "180DC POC",
    "Date of Entry",
    "Name of Organisation",
    "Organisation Website",
    "Organisation Sector",
    "Signal Observed",
    "Signal Details",
    "Source of Signal",
    "POC Name",
    "POC Job Title",
    "POC LinkedIn",
    "POC Email",
    "POC Connection Status",
    "Message",
    "POC Message Status",
    "Follow Up Status (if no reply)",
    "Follow Up Message",
    "Meet Scheduled (if replied)",
]

# Tab 4 — Personal / handpicked startup outreach
PERSONAL_SCHEMA = [
    "Sr No.",
    "180DC POC",
    "Date of Entry",
    "Organisation Name",
    "Sector",
    "Organisation Stage",
    "Activity Observed",
    "Founder Name",
    "Founder (or POC) LinkedIn",
    "Connection Status",
    "Message",
    "Message Status",
    "Follow Up Status",
    "Follow Up Message",
    "Meet Scheduled",
]

# The 6 columns Nilay's personal sheet must always carry (per his org's spec).
PERSONAL_SHEET_REQUIRED = [
    "POC Name",
    "POC Job Title",
    "Company Name",
    "POC LinkedIn",
    "Email",
    "Sector",
]


def secret(section: str, key: str, default: str = "") -> str:
    try:
        return st.secrets.get(section, {}).get(key, default) or default
    except Exception:
        return default


def gemini_key() -> str:
    return st.session_state.get("gemini_override") or secret("llm", "gemini_api_key")


def sheet_id() -> str:
    return secret("sheets", "spreadsheet_id")
