import streamlit as st

# Five sector buckets for the summer cycle, mapped to their analyst owners.
SECTORS = [
    "SaaS + AI + Automation",
    "FMCG / Food & Beverage / Consumer Brands / Consumer E-commerce",
    "Logistics & Supply Chain + Climate-tech / Sustainability",
    "Fintech + Edtech",
    "Healthtech + NGOs / Social Impact",
]

OWNERS = {
    "SaaS + AI + Automation": "Swaroop",
    "FMCG / Food & Beverage / Consumer Brands / Consumer E-commerce": "Nilay",
    "Logistics & Supply Chain + Climate-tech / Sustainability": "Praneel",
    "Fintech + Edtech": "Pranav",
    "Healthtech + NGOs / Social Impact": "Purav",
}

QUOTA = 600

POC_HIERARCHY = [
    "Founder / Co-founder",
    "Operations / Growth Lead",
    "Product / Strategy Lead",
    "Hiring / TA Lead",
]

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
