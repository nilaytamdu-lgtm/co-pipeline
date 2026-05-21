import pandas as pd
import streamlit as st

from core.config import (
    TAB_SIGNAL,
    TAB_PERSONAL,
    TAB_MASTER,
    sheet_id,
)
from core.ui import apply_branding

apply_branding()

st.title("Tracker")
st.caption("Shared Google Sheet · filter · dedupe")

if not sheet_id():
    st.warning("Configure the Sheet (Settings) to see live data.")
    st.stop()

from core.sheets import read_df


tab = st.selectbox("Tab", [TAB_SIGNAL, TAB_PERSONAL, TAB_MASTER])


@st.cache_data(ttl=60, show_spinner=False)
def _load(tab_name: str) -> pd.DataFrame:
    try:
        return read_df(tab_name)
    except Exception as e:
        st.error(f"Read failed: {e}")
        return pd.DataFrame()


df = _load(tab)

if df.empty:
    st.info("Tab is empty (or doesn't exist yet). Use Settings → Test connection to create headers.")
    st.stop()

# Filter controls
f1, f2 = st.columns([2, 1])
query = f1.text_input("Search (any column, case-insensitive)")
if query:
    mask = df.apply(lambda r: r.astype(str).str.contains(query, case=False, na=False)).any(axis=1)
    df = df[mask]

st.dataframe(df, use_container_width=True, hide_index=True, height=500)

st.divider()

st.subheader("Dedupe")
dedupe_col = None
for c in ("POC LinkedIn", "POC Email", "Founder (or POC) Linkedin", "Organisation"):
    if c in df.columns:
        dedupe_col = c
        break

if dedupe_col:
    st.caption(f"Checking duplicates on column: **{dedupe_col}**")
    norm = df[dedupe_col].astype(str).str.strip().str.lower()
    dup_mask = norm.duplicated(keep=False) & norm.astype(bool)
    dups = df[dup_mask].sort_values(dedupe_col)
    if dups.empty:
        st.success("No duplicates found.")
    else:
        st.warning(f"{len(dups)} duplicate rows.")
        st.dataframe(dups, use_container_width=True, hide_index=True)
else:
    st.caption("No identifiable key column for dedupe on this tab.")

if st.button("Refresh cache"):
    _load.clear()
    st.rerun()
