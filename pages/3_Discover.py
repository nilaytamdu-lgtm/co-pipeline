import datetime as dt

import pandas as pd
import streamlit as st

from core.config import (
    OWNERS,
    SECTORS,
    SIGNALS,
    SIGNAL_SCHEMA,
    TAB_SIGNAL,
    secret,
    sheet_id,
)
from core.keywords import build_google_dorks
from core.ui import apply_branding

apply_branding()

st.title("Discover Companies")
st.caption("Brave-search dorks → Gemini extraction → candidate leads")

if not secret("apis", "brave_api_key"):
    st.error("Brave API key missing. Sign up at https://api.search.brave.com and paste the token in `.streamlit/secrets.toml` (`apis.brave_api_key`).")
    st.stop()

c1, c2, c3 = st.columns(3)
default_sector = st.session_state.get("default_sector", SECTORS[0])
sector = c1.selectbox("Sector", SECTORS, index=SECTORS.index(default_sector))
signal = c2.selectbox("Signal", SIGNALS)
region = c3.text_input("Region", value="India")

st.caption("Dorks that will run:")
dorks = build_google_dorks(sector, signal)
for d in dorks:
    st.code(d, language="text")

cfg1, cfg2 = st.columns(2)
max_dorks = cfg1.slider("Max dorks to run", min_value=1, max_value=min(6, len(dorks)) if dorks else 1, value=min(4, len(dorks)) if dorks else 1)
per_dork = cfg2.slider("Results per dork", min_value=4, max_value=10, value=8)

if st.button("Run Discover", type="primary"):
    from core.sources.discover import run_dorks

    with st.spinner("Searching..."):
        raw = run_dorks(sector, signal, region, max_dorks=max_dorks, per_dork=per_dork)
    errors = [r for r in raw if r.get("_error")]
    hits = [r for r in raw if not r.get("_error")]
    for e in errors:
        st.warning(e["_error"])
    st.session_state["discover_raw"] = hits
    st.session_state["discover_meta"] = {"sector": sector, "signal": signal, "region": region}
    st.success(f"{len(hits)} unique SERP entries.")

raw_results = st.session_state.get("discover_raw")
if not raw_results:
    st.stop()

with st.expander(f"Raw search results ({len(raw_results)})", expanded=False):
    st.dataframe(pd.DataFrame(raw_results)[["title", "url", "description", "_dork"]], hide_index=True, width="stretch")

st.divider()
st.subheader("Extract structured leads with Gemini")
st.caption("Sends the batch through one LLM call. Returns {company, signal_summary, source_url}.")

if st.button("Extract"):
    from core.sources.discover import extract_companies

    meta = st.session_state.get("discover_meta", {})
    with st.spinner("Extracting..."):
        leads = extract_companies(raw_results, meta.get("sector", sector), meta.get("signal", signal), meta.get("region", region))
    st.session_state["discover_leads"] = leads
    st.success(f"Extracted {len(leads)} leads.")

leads = st.session_state.get("discover_leads", [])
if not leads:
    st.stop()

leads_df = pd.DataFrame(leads)
leads_df.insert(0, "add", False)
edited = st.data_editor(
    leads_df,
    width="stretch",
    hide_index=True,
    column_config={"add": st.column_config.CheckboxColumn(required=True)},
    key="leads_editor",
)

st.caption("Tick the leads you want to push to **Signal Based Outreach**. Domain lookup runs at append time (one Brave query per row).")

if st.button("Append selected to Sheet", type="primary"):
    if not sheet_id():
        st.error("Sheet not configured. Open Settings.")
        st.stop()

    selected = edited[edited["add"] == True]
    if selected.empty:
        st.warning("Nothing selected.")
        st.stop()

    from core.sheets import append_rows, read_df
    from core.sources.discover import domain_for

    meta = st.session_state.get("discover_meta", {})

    # Pre-build dedupe set in one read (avoids quota burn from per-row checks)
    existing_companies: set = set()
    try:
        df_existing = read_df(TAB_SIGNAL)
        if not df_existing.empty and "Name of Organisation" in df_existing.columns:
            existing_companies = {str(c).strip().lower() for c in df_existing["Name of Organisation"] if str(c).strip()}
    except Exception:
        pass

    to_append: list[dict] = []
    skipped = 0
    progress = st.progress(0.0)
    for i, (_, row) in enumerate(selected.iterrows(), 1):
        company = str(row.get("company", "")).strip()
        if not company:
            skipped += 1
            progress.progress(i / len(selected))
            continue
        if company.lower() in existing_companies:
            skipped += 1
            progress.progress(i / len(selected))
            continue
        domain = domain_for(company)
        candidate = {
            "Name of Organisation": company,
            "Organisation Website": f"https://{domain}" if domain else "",
            "Organisation Sector": meta.get("sector", sector),
            "Signal Observed": meta.get("signal", signal),
            "Signal Details": row.get("signal_summary", ""),
            "Source of Signal": row.get("source_url", ""),
            "180DC POC": OWNERS.get(meta.get("sector", sector), ""),
            "Date of Entry": dt.date.today().isoformat(),
        }
        to_append.append(candidate)
        existing_companies.add(company.lower())
        progress.progress(i / len(selected))

    added = 0
    if to_append:
        try:
            with st.spinner(f"Writing {len(to_append)} rows..."):
                added = append_rows(TAB_SIGNAL, to_append, SIGNAL_SCHEMA, sector=meta.get("sector", sector))
        except Exception as e:
            st.error(f"Batch append failed: {e}")

    st.success(f"Added {added} leads · skipped {skipped}.")
