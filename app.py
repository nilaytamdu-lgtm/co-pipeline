from pathlib import Path

import streamlit as st

from core.config import gemini_key, sheet_id
from core.ui import apply_branding, BRAND_DARK, BRAND_GREEN, FAVICON_PATH, LOGO_PATH

_page_icon = str(FAVICON_PATH) if FAVICON_PATH.exists() else (str(LOGO_PATH) if LOGO_PATH.exists() else None)

st.set_page_config(
    page_title="180DC NITW — Client Outreach",
    page_icon=_page_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_branding()

st.markdown(
    f"""
    <div style="padding:8px 0 4px 0;">
      <div style="font-family:'Lexend',sans-serif; font-size:0.75rem; font-weight:600;
                  color:{BRAND_GREEN}; letter-spacing:0.22em; text-transform:uppercase;
                  margin-bottom:6px;">Summer Cycle · 2026</div>
      <h1 style="margin:0;">Client Outreach Pipeline</h1>
      <p style="color:{BRAND_GREEN}; font-weight:500; font-size:1rem; margin-top:4px;">
        Prospect, enrich, draft, and track outreach across 15 sectors.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

st.markdown("### What lives where")
st.markdown(
    f"""
| Page | What it does |
|---|---|
| **Dashboard** | Leads per analyst, status breakdown, recent activity |
| **Keywords** | Generate Apollo / LinkedIn / Google query strings for your sector × signal |
| **Discover** | Find companies via Brave search → Gemini extraction (signal-driven) |
| **Enrich** | Find POCs and emails one by one (Hunter → Snov chain) |
| **Email** | Draft a single LinkedIn note / DM / cold email |
| **Tracker** | View / edit the shared Google Sheet, dedupe |
| **Apollo Import** | Upload an Apollo CSV → review → bulk import + enrich + draft |
| **Settings** | API keys, sector default, connection test |
"""
)

st.divider()

st.markdown("### Status")

cols = st.columns(2)
cols[0].metric("Gemini configured", "Yes" if gemini_key() else "No")
cols[1].metric("Sheet configured", "Yes" if sheet_id() else "No")

if not sheet_id():
    st.warning(
        "Google Sheet not configured. Open **Settings** (or edit `.streamlit/secrets.toml`) "
        "and set the Sheet ID + service-account JSON. README has the full walkthrough."
    )
