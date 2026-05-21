import datetime as dt

import pandas as pd
import streamlit as st

from core.config import (
    ANALYSTS,
    ANALYST_SECTORS,
    OWNERS,
    QUOTA,
    SECTORS,
    TAB_SIGNAL,
    TAB_PERSONAL,
    sheet_id,
)
from core.ui import apply_branding

apply_branding()

st.title("Dashboard")
st.caption("Quota progress · status breakdown · follow-ups due")

if not sheet_id():
    st.warning("Configure the Sheet (Settings) to see live data.")
    st.stop()

try:
    from core.sheets import read_df
except Exception as e:
    st.error(f"Sheets module not loadable: {e}")
    st.stop()


@st.cache_data(ttl=120, show_spinner=False)
def _load() -> pd.DataFrame:
    frames = []
    for tab in (TAB_SIGNAL, TAB_PERSONAL):
        try:
            df = read_df(tab)
            if not df.empty:
                df["_tab"] = tab
                frames.append(df)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


df = _load()
if df.empty:
    st.info("No leads yet. Add some via the Discover or Enrich pages, or directly in the Sheet.")
    st.stop()

# Normalize sector column across the two tabs (Tab 2 uses "Organisation Sector", Tab 4 uses "Sector")
if "Organisation Sector" in df.columns and "Sector" in df.columns:
    df["__sector"] = df["Sector"].fillna("").where(df["Sector"].astype(bool), df["Organisation Sector"])
elif "Organisation Sector" in df.columns:
    df["__sector"] = df["Organisation Sector"]
elif "Sector" in df.columns:
    df["__sector"] = df["Sector"]
else:
    df["__sector"] = ""

# Map each row's sector to its owning analyst.
df["__analyst"] = df["__sector"].map(OWNERS).fillna("Unassigned")

total = len(df)
today = dt.date.today().isoformat()
today_count = int((df.get("Date of Entry", pd.Series(dtype=str)) == today).sum())

m1, m2 = st.columns(2)
m1.metric("Total leads", total)
m2.metric("Added today", today_count)

st.divider()

st.subheader("Leads per analyst")
analyst_counts = df.groupby("__analyst").size().reindex(ANALYSTS, fill_value=0).rename("count")
prog = pd.DataFrame({"analyst": analyst_counts.index, "count": analyst_counts.values})
prog["sectors"] = prog["analyst"].map(lambda a: ", ".join(ANALYST_SECTORS.get(a, [])))
st.dataframe(prog, width="stretch", hide_index=True)
st.bar_chart(prog.set_index("analyst")["count"])

st.subheader("Per-sector breakdown")
sector_counts = df.groupby("__sector").size().reindex(SECTORS, fill_value=0).rename("count")
sect_df = pd.DataFrame({"sector": sector_counts.index, "count": sector_counts.values})
sect_df["analyst"] = sect_df["sector"].map(OWNERS)
sect_df = sect_df[["analyst", "sector", "count"]].sort_values(["analyst", "sector"])
st.dataframe(sect_df, width="stretch", hide_index=True)

st.subheader("Status breakdown")
status_col = None
for c in ("POC Message Status", "Message Status", "Status"):
    if c in df.columns:
        status_col = c
        break
if status_col:
    counts = df[status_col].fillna("(blank)").value_counts()
    st.bar_chart(counts)
else:
    st.caption("No status column found in either tab.")

st.subheader("Last 7 days")
if "Date of Entry" in df.columns:
    df["_d"] = pd.to_datetime(df["Date of Entry"], errors="coerce")
    since = pd.Timestamp.today().normalize() - pd.Timedelta(days=7)
    recent = df[df["_d"] >= since]
    by_day = recent.groupby(recent["_d"].dt.date).size()
    st.line_chart(by_day)
else:
    st.caption("No Date of Entry column found.")
