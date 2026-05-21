import datetime as dt

import pandas as pd
import streamlit as st

from core.config import (
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

# Top-line metrics
total = len(df)
today = dt.date.today().isoformat()
today_count = int((df.get("Date of Entry", pd.Series(dtype=str)) == today).sum())
m1, m2, m3 = st.columns(3)
m1.metric("Total leads", total)
m2.metric("Added today", today_count)
m3.metric("Team quota", f"{total} / {QUOTA * len(SECTORS)}")

st.divider()

st.subheader("Per-sector progress vs 600")
sector_counts = df.groupby("__sector").size().reindex(SECTORS, fill_value=0).rename("count")
prog = pd.DataFrame({"sector": sector_counts.index, "count": sector_counts.values})
prog["quota"] = QUOTA
prog["owner"] = prog["sector"].map(OWNERS)
prog["pct"] = (prog["count"] / prog["quota"] * 100).round(1)
st.dataframe(prog, width="stretch", hide_index=True)
st.bar_chart(prog.set_index("sector")["count"])

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
