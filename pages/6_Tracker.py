import pandas as pd
import streamlit as st

from core.config import (
    CHANNEL_AUTOMATION,
    CHANNEL_LINKEDIN,
    RELATIONSHIP_ANALYSTS,
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


# Tab order mirrors the Sheet. Default tab depends on the user's specialty:
# automation analysts work in Signal Based; relationship analysts (Shriya,
# Sreeshanth, Nithik, Vinoothna) work in Engagement Led + Organization Based.
_TABS = [TAB_MASTER, TAB_SIGNAL, TAB_ORG, TAB_PERSONAL]
_current_user = st.session_state.get("current_user")
_default_idx = 0 if _current_user in RELATIONSHIP_ANALYSTS else 1
tab = st.selectbox("Tab", _TABS, index=_default_idx)


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

# Outreach Channel filter — only meaningful on the Signal Based tab where the column exists
if "Outreach Channel" in df.columns:
    channel_options = ["All", CHANNEL_AUTOMATION, CHANNEL_LINKEDIN, "(blank)"]
    channel_pick = f2.selectbox("Outreach Channel", channel_options, index=0)
    if channel_pick == CHANNEL_AUTOMATION:
        df = df[df["Outreach Channel"] == CHANNEL_AUTOMATION]
    elif channel_pick == CHANNEL_LINKEDIN:
        df = df[df["Outreach Channel"] == CHANNEL_LINKEDIN]
    elif channel_pick == "(blank)":
        df = df[df["Outreach Channel"].fillna("").str.strip() == ""]

# Channel split summary
if "Outreach Channel" in df.columns and not df.empty:
    n_auto = int((df["Outreach Channel"] == CHANNEL_AUTOMATION).sum())
    n_li = int((df["Outreach Channel"] == CHANNEL_LINKEDIN).sum())
    n_blank = int((df["Outreach Channel"].fillna("").str.strip() == "").sum())
    st.caption(f"Showing **{len(df)}** rows · {n_auto} for Automation · {n_li} for LinkedIn · {n_blank} blank channel")

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
