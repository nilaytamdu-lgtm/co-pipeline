"""Branding helpers: Lexend font + 180DC NITW color palette + logo block.

Apply at the top of every page via `apply_branding()`. Pages keep their
existing st.title / st.caption calls; the CSS restyles them in-place.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

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
        st.sidebar.image(str(LOGO_PATH), use_container_width=True)
    else:
        st.sidebar.markdown(_TEXT_LOGO, unsafe_allow_html=True)
    st.sidebar.markdown('<div class="brand-tagline">Client Outreach Pipeline</div>', unsafe_allow_html=True)


_APPLIED_KEY = "_branding_applied"


def apply_branding() -> None:
    """Inject brand CSS + render the sidebar logo block. Safe to call on every page."""
    st.markdown(_CSS, unsafe_allow_html=True)
    _render_logo_in_sidebar()
