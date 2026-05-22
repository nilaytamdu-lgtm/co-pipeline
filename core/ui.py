"""Branding helpers: Lexend font + 180DC NITW color palette + logo block.

Apply at the top of every page via `apply_branding()`. Pages keep their
existing st.title / st.caption calls; the CSS restyles them in-place.

Also handles the "I am ..." analyst picker that persists across page
navigations and browser reloads via URL query params. This is what makes
sector defaults stick to the right person so rows don't get tagged
under the wrong analyst on import.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.config import ANALYSTS, ANALYST_SECTORS

# Brand palette (per 180DC NITW guidelines)
BRAND_DARK = "#134f5c"   # dark teal — headers
BRAND_GREEN = "#38761d"  # forest green — medium / accent text
BRAND_BLACK = "#000000"  # body
BRAND_SOFT = "#f5f8f7"   # very light teal — subtle backgrounds
BRAND_RULE = "rgba(19, 79, 92, 0.12)"

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"
FAVICON_PATH = ASSETS_DIR / "favicon.png"


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="st-"], .stMarkdown, .stTextInput, .stButton,
.stSelectbox, .stRadio, .stMetric, .stDataFrame, .stSlider,
[data-testid="stSidebar"], [data-testid="stHeader"] {{
  font-family: 'Lexend', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}}

h1, h2, h3, h4, h5, h6 {{
  font-family: 'Lexend', sans-serif !important;
  color: {BRAND_DARK} !important;
  font-weight: 600 !important;
  letter-spacing: -0.012em;
}}

h1 {{
  font-weight: 700 !important;
  font-size: 2rem !important;
  margin-bottom: 0.25rem !important;
}}

[data-testid="stCaptionContainer"], .stCaption, small {{
  color: {BRAND_GREEN} !important;
  font-weight: 500 !important;
  letter-spacing: 0.01em;
}}

p, li, .stMarkdown p, [data-testid="stMarkdownContainer"] p {{
  color: {BRAND_BLACK};
  font-weight: 400;
}}

[data-testid="stMetricLabel"] p {{
  color: {BRAND_GREEN} !important;
  font-weight: 500 !important;
}}
[data-testid="stMetricValue"] {{
  color: {BRAND_DARK} !important;
  font-weight: 700 !important;
}}

.stButton > button[kind="primary"] {{
  background-color: {BRAND_DARK} !important;
  border-color: {BRAND_DARK} !important;
  color: white !important;
  font-weight: 600 !important;
}}
.stButton > button[kind="primary"]:hover {{
  background-color: {BRAND_GREEN} !important;
  border-color: {BRAND_GREEN} !important;
}}
.stButton > button[kind="secondary"] {{
  border-color: {BRAND_DARK} !important;
  color: {BRAND_DARK} !important;
  font-weight: 500 !important;
}}
.stButton > button[kind="secondary"]:hover {{
  border-color: {BRAND_GREEN} !important;
  color: {BRAND_GREEN} !important;
}}

[data-testid="stSidebar"] {{
  background-color: {BRAND_SOFT};
  border-right: 1px solid {BRAND_RULE};
}}
[data-testid="stSidebarNav"] a {{
  font-family: 'Lexend', sans-serif !important;
  font-weight: 500;
  color: {BRAND_DARK} !important;
}}

a, .stMarkdown a {{
  color: {BRAND_GREEN} !important;
  text-decoration: none;
  border-bottom: 1px dashed {BRAND_GREEN};
}}
a:hover {{
  color: {BRAND_DARK} !important;
  border-bottom-color: {BRAND_DARK};
}}

hr {{
  border-color: {BRAND_RULE} !important;
}}

[data-testid="stDataFrame"] thead tr th {{
  background-color: {BRAND_SOFT} !important;
  color: {BRAND_DARK} !important;
  font-weight: 600;
}}

.stAlert {{
  border-radius: 8px;
  border-left-width: 4px !important;
}}

.brand-tagline {{
  font-family: 'Lexend', sans-serif;
  font-size: 0.72rem;
  font-weight: 500;
  color: {BRAND_GREEN};
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 4px 0 12px 0;
  border-bottom: 1px solid {BRAND_RULE};
  margin-bottom: 12px;
  text-align: center;
}}
</style>
"""

_TEXT_LOGO = f"""
<div style="display:flex; align-items:center; gap:10px; padding:8px 0 4px;">
  <div style="width:38px; height:38px; border-radius:50%;
              background: linear-gradient(135deg, {BRAND_GREEN} 0%, {BRAND_DARK} 100%);
              display:flex; align-items:center; justify-content:center;
              color:white; font-weight:700; font-size:0.78rem;
              font-family:'Lexend',sans-serif; letter-spacing:0.02em;">180°</div>
  <div style="line-height:1.05;">
    <div style="font-family:'Lexend',sans-serif; font-size:0.95rem;
                font-weight:700; color:{BRAND_DARK};">180 Degrees</div>
    <div style="font-family:'Lexend',sans-serif; font-size:0.82rem;
                font-weight:400; color:{BRAND_BLACK}; letter-spacing:0.18em;">CONSULTING</div>
    <div style="font-family:'Lexend',sans-serif; font-size:0.65rem;
                font-weight:600; color:{BRAND_GREEN}; letter-spacing:0.22em; margin-top:2px;">NITW</div>
  </div>
</div>
"""


def _render_logo_in_sidebar() -> None:
    if LOGO_PATH.exists():
        st.sidebar.image(str(LOGO_PATH), width="stretch")
    else:
        st.sidebar.markdown(_TEXT_LOGO, unsafe_allow_html=True)
    st.sidebar.markdown('<div class="brand-tagline">Client Outreach Pipeline</div>', unsafe_allow_html=True)


def _render_analyst_picker() -> None:
    """Sidebar widget that asks 'I am ...' and persists the pick.

    Persistence chain:
    1. URL query param ?analyst=<name> (survives browser reload + bookmarking)
    2. st.session_state["current_analyst"] (survives in-session navigation)
    3. If neither set, default to no selection — user must pick once.

    Side effects when an analyst is selected:
    - st.session_state["current_analyst"] is set
    - URL is rewritten to include ?analyst=<name>
    - st.session_state["default_sector"] is initialized to that analyst's
      first allocated sector IF not already set this session
    """
    qp = st.query_params
    url_val = qp.get("analyst") if hasattr(qp, "get") else None

    # First-load hydration from URL
    if "current_analyst" not in st.session_state and url_val in ANALYSTS:
        st.session_state["current_analyst"] = url_val
        sectors = ANALYST_SECTORS.get(url_val, [])
        if sectors and "default_sector" not in st.session_state:
            st.session_state["default_sector"] = sectors[0]

    current = st.session_state.get("current_analyst")
    options = ["(pick yourself)"] + ANALYSTS
    idx = ANALYSTS.index(current) + 1 if current in ANALYSTS else 0

    selected = st.sidebar.selectbox(
        "I am",
        options=options,
        index=idx,
        key="_analyst_picker",
        help="Pick once per session. Sector dropdowns default to your allocated sectors, and the URL gets updated so a bookmark remembers you.",
    )

    if selected != "(pick yourself)":
        prev = st.session_state.get("current_analyst")
        if prev != selected:
            st.session_state["current_analyst"] = selected
            sectors = ANALYST_SECTORS.get(selected, [])
            if sectors:
                st.session_state["default_sector"] = sectors[0]
            try:
                st.query_params["analyst"] = selected
            except Exception:
                pass
            st.rerun()


def apply_branding() -> None:
    """Inject brand CSS + render the sidebar logo block + analyst picker."""
    st.markdown(_CSS, unsafe_allow_html=True)
    _render_logo_in_sidebar()
    _render_analyst_picker()
