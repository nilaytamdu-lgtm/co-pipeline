import pandas as pd
import streamlit as st

from core.config import (
    ALL_USERS,
    CHANNEL_AUTOMATION,
    CHANNEL_LINKEDIN,
    CSV_SECTOR_DEFAULTS,
    RELATIONSHIP_ANALYSTS,
    SECTORS,
    TAB_SIGNAL,
    TAB_PERSONAL,
    TAB_MASTER,
    TAB_ORG,
    sheet_id,
)
from core.ui import apply_branding


def _normalize_linkedin(url: str) -> str:
    """Extract the LinkedIn slug for matching (the part after /in/)."""
    if not url:
        return ""
    u = str(url).lower().strip()
    u = u.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
    if "/in/" in u:
        return u.split("/in/")[-1].split("?")[0].split("/")[0]
    return u

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

# Keep the unfiltered data around for the backfill action — the filter section
# below mutates `df` for display.
df_full = df.copy()

# Bulk fix sector + 180DC POC from CSV. Handles mixed-sector files by reading
# each CSV row's own Sector value and mapping it (with auto-suggested
# defaults + override per unique value) to one of the 15 app sectors.
if tab == TAB_SIGNAL:
    with st.expander("🔧 Bulk fix sector + 180DC POC from CSV", expanded=False):
        st.caption(
            "Upload a CSV (Instant Data Scraper format). Each row's sector comes from the CSV's own "
            "**Sector** column — you map each unique CSV sector value to an app sector once, then the "
            "tool applies per-row. Matches tracker rows by **POC LinkedIn URL** first, then by "
            "**POC Name + Company Name**."
        )

        bulk_csv = st.file_uploader("CSV", type=["csv"], key="bulk_fix_csv")

        default_user = st.session_state.get("current_user", "")
        all_user_options = [""] + ALL_USERS
        bulk_user = st.selectbox(
            "Target 180DC POC (applies to ALL matched rows)",
            options=all_user_options,
            index=all_user_options.index(default_user) if default_user in all_user_options else 0,
            key="bulk_fix_user",
        )

        if bulk_csv is not None:
            try:
                csv_df = pd.read_csv(bulk_csv)
            except Exception as e:
                st.error(f"Couldn't parse CSV: {e}")
                csv_df = None

            if csv_df is not None and not csv_df.empty:
                csv_li_col = next((c for c in csv_df.columns if "linkedin" in c.lower()), None)
                csv_name_col = next((c for c in csv_df.columns if c.lower().strip() in ("poc name", "name", "full name")), None)
                csv_company_col = next((c for c in csv_df.columns if c.lower().strip() in ("company name", "company")), None)
                csv_sector_col = next((c for c in csv_df.columns if c.lower().strip() in ("sector", "industry")), None)

                if not (csv_name_col and csv_company_col):
                    st.error("CSV must have POC Name and Company Name columns to match.")
                else:
                    # Build per-CSV-sector mapping table
                    sector_mapping: dict[str, str] = {}
                    fallback_sector: str = SECTORS[0]

                    if csv_sector_col:
                        unique_csv_sectors = sorted(
                            csv_df[csv_sector_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
                        )
                        if unique_csv_sectors:
                            st.markdown("**Map each CSV sector to an app sector**")
                            for csv_sec in unique_csv_sectors:
                                n_rows = int((csv_df[csv_sector_col].astype(str).str.strip() == csv_sec).sum())
                                default_app_sec = CSV_SECTOR_DEFAULTS.get(csv_sec.lower().strip(), SECTORS[0])
                                idx = SECTORS.index(default_app_sec) if default_app_sec in SECTORS else 0
                                sector_mapping[csv_sec] = st.selectbox(
                                    f"`{csv_sec}` — {n_rows} rows",
                                    SECTORS,
                                    index=idx,
                                    key=f"bulk_map_{csv_sec}",
                                )
                            fallback_sector = st.selectbox(
                                "Fallback sector (used for rows with blank Sector in the CSV)",
                                SECTORS,
                                index=SECTORS.index(st.session_state.get("default_sector", SECTORS[0])) if st.session_state.get("default_sector", SECTORS[0]) in SECTORS else 0,
                                key="bulk_fallback_sector",
                            )
                    else:
                        st.warning("No `Sector` (or `Industry`) column in this CSV. Pick a single target sector for all rows.")
                        fallback_sector = st.selectbox(
                            "Target sector for all rows",
                            SECTORS,
                            index=SECTORS.index(st.session_state.get("default_sector", SECTORS[0])) if st.session_state.get("default_sector", SECTORS[0]) in SECTORS else 0,
                            key="bulk_single_sector",
                        )

                    # Build CSV row → target sector map
                    csv_row_sector: dict[int, str] = {}
                    for csv_idx, r in csv_df.iterrows():
                        if csv_sector_col:
                            v = str(r.get(csv_sector_col, "")).strip()
                            csv_row_sector[csv_idx] = sector_mapping.get(v, fallback_sector) if v else fallback_sector
                        else:
                            csv_row_sector[csv_idx] = fallback_sector

                    # Index CSV rows by LinkedIn slug + (name, company) for matching
                    li_to_csv_idx: dict[str, int] = {}
                    nc_to_csv_idx: dict[tuple, int] = {}
                    for csv_idx, r in csv_df.iterrows():
                        if csv_li_col:
                            slug = _normalize_linkedin(str(r.get(csv_li_col, "")))
                            if slug and slug not in li_to_csv_idx:
                                li_to_csv_idx[slug] = csv_idx
                        n = str(r.get(csv_name_col, "")).strip().lower()
                        c = str(r.get(csv_company_col, "")).strip().lower()
                        if n and c:
                            nc_to_csv_idx.setdefault((n, c), csv_idx)

                    # Walk the tracker; for each row, find matching CSV row's sector
                    row_to_sector: dict[int, str] = {}
                    for df_idx, trow in df_full.iterrows():
                        matched_csv_idx = None
                        tracker_slug = _normalize_linkedin(str(trow.get("POC LinkedIn", "")))
                        if tracker_slug and tracker_slug in li_to_csv_idx:
                            matched_csv_idx = li_to_csv_idx[tracker_slug]
                        else:
                            tn = str(trow.get("POC Name", "")).strip().lower()
                            tc = str(trow.get("Name of Organisation", "")).strip().lower()
                            if (tn, tc) in nc_to_csv_idx:
                                matched_csv_idx = nc_to_csv_idx[(tn, tc)]
                        if matched_csv_idx is not None:
                            sheet_row = int(df_idx) + 2
                            row_to_sector[sheet_row] = csv_row_sector[matched_csv_idx]

                    st.write(f"**{len(row_to_sector)}** tracker rows matched out of **{len(csv_df)}** CSV rows.")

                    # Show per-target-sector breakdown
                    if row_to_sector:
                        breakdown = pd.Series(list(row_to_sector.values())).value_counts()
                        with st.expander("Breakdown by target sector", expanded=False):
                            for sec, cnt in breakdown.items():
                                st.write(f"- **{sec}**: {cnt} rows")

                        if st.button("Apply bulk fix", type="primary"):
                            from core.sheets import batch_update_column

                            with st.spinner(f"Updating {len(row_to_sector)} rows..."):
                                try:
                                    batch_update_column(TAB_SIGNAL, "Organisation Sector", row_to_sector)
                                    if bulk_user:
                                        row_to_owner = {r: bulk_user for r in row_to_sector}
                                        batch_update_column(TAB_SIGNAL, "180DC POC", row_to_owner)
                                    st.success(f"Updated {len(row_to_sector)} rows. Refreshing...")
                                    _load.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Bulk fix failed: {e}")

# Backfill blank Outreach Channel rows (one API call, batch update)
if "Outreach Channel" in df_full.columns:
    blank_mask = df_full["Outreach Channel"].fillna("").str.strip() == ""
    n_blank_total = int(blank_mask.sum())
    if n_blank_total > 0:
        with st.expander(f"⚠️ {n_blank_total} rows have blank Outreach Channel — auto-categorize?", expanded=False):
            st.caption(
                "Rows with a populated **POC Email** get tagged as **Automation (email)**. "
                "Rows without get tagged as **LinkedIn (manual)**. One Sheets API call total."
            )
            # Show preview of what will happen
            blank_df = df_full[blank_mask]
            n_to_auto = int(blank_df["POC Email"].astype(str).str.contains("@", na=False).sum()) if "POC Email" in blank_df.columns else 0
            n_to_li = n_blank_total - n_to_auto
            st.write(f"After backfill: **{n_to_auto}** → Automation, **{n_to_li}** → LinkedIn")

            if st.button("Backfill now", type="primary"):
                from core.sheets import batch_update_column

                row_to_value: dict[int, str] = {}
                for df_idx, row in blank_df.iterrows():
                    # df_idx is 0-based; +2 for 1-based sheet row plus header row
                    sheet_row = int(df_idx) + 2
                    email = str(row.get("POC Email", "")).strip()
                    new_val = CHANNEL_AUTOMATION if email and "@" in email else CHANNEL_LINKEDIN
                    row_to_value[sheet_row] = new_val

                with st.spinner(f"Updating {len(row_to_value)} cells..."):
                    try:
                        updated = batch_update_column(tab, "Outreach Channel", row_to_value)
                        st.success(f"Backfilled {updated} rows. Refreshing...")
                        _load.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Backfill failed: {e}")

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
