import json

import streamlit as st

from core.config import SECTORS, SIGNALS
from core.keywords import (
    SIZE_BANDS,
    build_apollo,
    build_linkedin,
    build_google_dorks,
    GEMINI_POLISH_PROMPT,
)
from core.ui import apply_branding

apply_branding()

st.title("Keyword Builder")
st.caption("Apollo filters · LinkedIn boolean · Google dorks for your sector × signal")

cols = st.columns(4)
default_sector = st.session_state.get("default_sector", SECTORS[0])
sector = cols[0].selectbox("Sector", SECTORS, index=SECTORS.index(default_sector))
signal = cols[1].selectbox("Signal", SIGNALS)
region = cols[2].text_input("Region", value="India")
size_band = cols[3].selectbox("Company size", list(SIZE_BANDS.keys()), index=1)

apollo = build_apollo(sector, signal, region, size_band)
li_query = build_linkedin(sector, signal, region)
dorks = build_google_dorks(sector, signal)

st.divider()

st.subheader("Apollo — paste into the relevant filter")
st.code(f"Industries:        {apollo['industries']}", language="text")
st.code(f"Keywords:          {apollo['keywords']}", language="text")
st.code(f"Person titles:     {apollo['person_titles']}", language="text")
st.code(f"Locations:         {apollo['locations']}", language="text")
st.code(f"Employee ranges:   {apollo['employee_ranges']}", language="text")

st.subheader("LinkedIn boolean")
st.code(li_query, language="text")
st.caption("Paste into LinkedIn's people-search bar or Sales Navigator.")

st.subheader("Google dorks")
for d in dorks:
    st.code(d, language="text")

st.divider()

st.subheader("Polish with Gemini")
st.caption("Expands with sector-niche terms, alternative LinkedIn angles, fresh Google dorks, and negative terms to cut noise.")
if st.button("Polish"):
    try:
        from core.llm.gemini import generate

        prompt = GEMINI_POLISH_PROMPT.format(
            sector=sector,
            signal=signal,
            region=region,
            linkedin=li_query,
            dorks=" | ".join(dorks),
            apollo_keywords=apollo["keywords"],
        )
        with st.spinner("Polishing..."):
            raw = generate(prompt, temperature=0.7, max_tokens=600)
        # Strip code fences if Gemini wraps the JSON
        cleaned = raw.strip().lstrip("`").rstrip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            data = json.loads(cleaned)
            st.success("Polished output below.")
            st.json(data)
        except json.JSONDecodeError:
            st.warning("Gemini returned non-JSON. Raw output:")
            st.code(raw)
    except Exception as e:
        st.error(f"Polish failed: {e}")
