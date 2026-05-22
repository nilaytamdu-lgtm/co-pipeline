import pandas as pd
import streamlit as st

from core.config import (
    TAB_SIGNAL,
    TAB_PERSONAL,
    TAB_MASTER,
    TAB_ORG,
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


# Order mirrors the Sheet tabs left-to-right. Default to Signal Based — that's
# where Discover/Enrich do most of their writes, so it's the operational tab.
_TABS = [TAB_MASTER, TAB_SIGNAL, TAB_ORG, TAB_PERSONAL]
tab = st.selectbox("Tab", _TABS, index=1)


@st.cache_data(ttl=180, show_spinner=False)
def _load(tab_name: str) -> pd.DataFrame:
    return read_df(tab_name)


try:
    df = _load(tab)
except Exception as e:
    msg = str(e)
    if "429" in msg or "Quota" in msg or "quota" in msg:
        st.error(
            "Sheets API quota hit (60 reads/min per service account). "
            "Wait ~60 seconds, then click **Refresh cache** below."
        )
    else:
        st.error(f"Read failed: {msg}")
    if st.button("Refresh cache"):
        _load.clear()
        st.rerun()
    st.stop()

if df.empty:
    st.info("Tab is empty (or doesn't exist yet). Use Settings → Test connection to create headers.")
    st.stop()

# Filter controls
f1, f2 = st.columns([2, 1])
query = f1.text_input("Search (any column, case-insensitive)")
if query:
    mask = df.apply(lambda r: r.astype(str).str.contains(query, case=False, na=False)).any(axis=1)
    df = df[mask]

st.dataframe(df, width="stretch", hide_index=True, height=500)

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
        st.dataframe(dups, width="stretch", hide_index=True)
else:
    st.caption("No identifiable key column for dedupe on this tab.")

if st.button("Refresh cache"):
    _load.clear()
    st.rerun()
