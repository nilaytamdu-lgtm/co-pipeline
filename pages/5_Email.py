import streamlit as st

from core.config import SECTORS, POC_HIERARCHY, SIGNALS
from core.llm.drafts import (
    FORMAT_EMAIL,
    FORMAT_LINKEDIN_NOTE,
    FORMAT_LINKEDIN_DM,
    draft,
)
from core.ui import apply_branding

apply_branding()

st.title("Draft Generator")
st.caption("LinkedIn note · LinkedIn DM · Cold email — Gemini, metrics-driven, no templates")

fmt_label = st.radio(
    "Format",
    ["LinkedIn connection note (≤300 chars)", "LinkedIn DM (≤800 chars)", "Cold email (≤120 words)"],
    horizontal=False,
)
fmt = {
    "LinkedIn connection note (≤300 chars)": FORMAT_LINKEDIN_NOTE,
    "LinkedIn DM (≤800 chars)": FORMAT_LINKEDIN_DM,
    "Cold email (≤120 words)": FORMAT_EMAIL,
}[fmt_label]

st.divider()
st.subheader("Lead inputs")

c1, c2 = st.columns(2)
company = c1.text_input("Company name", placeholder="e.g. Slurrp Farm")
poc_name = c2.text_input("POC name", placeholder="e.g. Meghana Narayan")

c3, c4 = st.columns(2)
poc_role = c3.selectbox("POC role", POC_HIERARCHY)
default_sector = st.session_state.get("default_sector", SECTORS[0])
sector = c4.selectbox("Sector", SECTORS, index=SECTORS.index(default_sector))

c5, c6 = st.columns(2)
signal = c5.selectbox("Signal observed", SIGNALS)
signal_details = c6.text_input("Signal details", placeholder="e.g. raised $4M Series A from Fireside in March 2026")

st.divider()
st.subheader("Tone controls")

t1, t2, t3 = st.columns(3)
tone = t1.select_slider("Tone", options=["formal", "neutral", "casual"], value="neutral")
length = t2.select_slider("Length", options=["short", "medium"], value="medium")
emphasis = t3.select_slider("Signal emphasis", options=["subtle", "balanced", "explicit"], value="balanced")

st.divider()

if st.button("Generate draft", type="primary"):
    if not (company and poc_name and signal_details):
        st.warning("Fill company, POC name, and signal details — those are the personalization hooks.")
    else:
        inputs = {
            "company": company,
            "poc_name": poc_name,
            "poc_role": poc_role,
            "sector": sector,
            "signal": signal,
            "signal_details": signal_details,
            "tone": tone,
            "length": length,
            "emphasis": emphasis,
        }
        try:
            with st.spinner("Drafting..."):
                result = draft(fmt, inputs)
            st.success("Draft ready.")
            if fmt == FORMAT_EMAIL:
                st.markdown("**Subject**")
                st.code(result.get("subject", ""), language="text")
                st.markdown("**Body**")
                st.text_area("body", value=result.get("body", ""), height=250, label_visibility="collapsed")
            else:
                msg = result.get("message", "")
                st.markdown(f"**Message** · {len(msg)} chars")
                st.text_area("message", value=msg, height=200, label_visibility="collapsed")
        except Exception as e:
            st.error(f"Draft failed: {e}")
