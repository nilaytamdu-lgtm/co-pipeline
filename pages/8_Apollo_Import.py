"""Apollo CSV → tracker pipeline.

Workflow:
1. User uploads an Apollo CSV export (typically 25 rows on free tier).
2. App normalizes columns (Apollo's column names) and shows a preview table
   with checkboxes per row.
3. User ticks which leads to keep, picks a sector for the batch.
4. App appends to Signal Based Outreach. Rows missing emails get sent to
   Hunter for enrichment (skipped if Apollo already provided the email).
5. After import, app offers bulk draft generation for the just-imported batch.
   User reviews each draft in an expandable card, edits in place, copies what
   they want.
"""
from __future__ import annotations

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
from core.ui import apply_branding

apply_branding()

st.title("Apollo Import")
st.caption("Apollo CSV → review → import → enrich blanks → draft messages in one pass")

# --- Apollo CSV column → tracker column ---
# Apollo's column names vary slightly across exports. We map every plausible
# header to our internal field. Multiple Apollo headers can map to the same
# field (first match wins).
COLUMN_MAP = {
    "First Name": "_first",
    "Last Name": "_last",
    "Title": "POC Job Title",
    "Job Title": "POC Job Title",
    "Position": "POC Job Title",
    "Company": "Name of Organisation",
    "Company Name": "Name of Organisation",
    "Account Name": "Name of Organisation",
    "Email": "POC Email",
    "Work Email": "POC Email",
    "Email Address": "POC Email",
    "Person LinkedIn URL": "POC LinkedIn",
    "Person Linkedin Url": "POC LinkedIn",
    "LinkedIn URL": "POC LinkedIn",
    "Linkedin Url": "POC LinkedIn",
    "Company Website": "Organisation Website",
    "Website": "Organisation Website",
    "Company Domain": "Organisation Website",
}


def _normalize(df_raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df_raw.index)
    for src, dst in COLUMN_MAP.items():
        if src in df_raw.columns:
            if dst in out.columns:
                out[dst] = out[dst].where(out[dst].astype(bool), df_raw[src])
            else:
                out[dst] = df_raw[src]
    # Build POC Name from first + last
    if "_first" in out.columns or "_last" in out.columns:
        f = out.get("_first", pd.Series([""] * len(df_raw))).fillna("").astype(str)
        l = out.get("_last", pd.Series([""] * len(df_raw))).fillna("").astype(str)
        out["POC Name"] = (f + " " + l).str.strip()
        out = out.drop(columns=[c for c in ("_first", "_last") if c in out.columns])
    return out.fillna("")


def _extract_domain(website: str) -> str:
    if not website:
        return ""
    d = website.strip().replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]
    return d.replace("www.", "")


# ---------- Step 1: upload ----------
uploaded = st.file_uploader("Apollo CSV export", type=["csv"])
if not uploaded:
    st.info(
        "Run your search in Apollo (paste filters from the **Keywords** page). "
        "Click Apollo's **Export → CSV** button. Drop the file here."
    )
    st.stop()

try:
    df_raw = pd.read_csv(uploaded)
except Exception as e:
    st.error(f"Couldn't parse CSV: {e}")
    st.stop()

normalized = _normalize(df_raw)

# Drop rows that don't have at least a POC name + company
need_cols = ["POC Name", "Name of Organisation"]
for c in need_cols:
    if c not in normalized.columns:
        normalized[c] = ""
clean = normalized[(normalized["POC Name"].str.strip() != "") & (normalized["Name of Organisation"].str.strip() != "")].copy()

c1, c2, c3 = st.columns(3)
c1.metric("Rows in CSV", len(df_raw))
c2.metric("Usable rows", len(clean))
c3.metric("Already have email", int((clean.get("POC Email", "").astype(str).str.contains("@", na=False)).sum()))

if clean.empty:
    st.error("No usable rows. CSV must include at least a name (First/Last) and a company column.")
    st.stop()

# ---------- Step 2: sector pick + preview ----------
st.divider()
default_sector = st.session_state.get("default_sector", SECTORS[0])
sector = st.selectbox(
    "Sector for this batch (all imported rows get tagged with this)",
    SECTORS,
    index=SECTORS.index(default_sector) if default_sector in SECTORS else 0,
)

st.subheader("Review and select")
st.caption("Tick rows to import. Rows where Apollo gave you an email skip the Hunter step automatically.")

preview = clean.copy()
preview.insert(0, "import", True)
display_cols = ["import", "POC Name", "POC Job Title", "Name of Organisation", "POC Email", "POC LinkedIn", "Organisation Website"]
preview = preview[[c for c in display_cols if c in preview.columns]]

edited = st.data_editor(
    preview,
    width="stretch",
    hide_index=True,
    column_config={
        "import": st.column_config.CheckboxColumn(required=True),
        "POC Email": st.column_config.TextColumn("POC Email"),
    },
    key="apollo_editor",
)

selected = edited[edited["import"] == True]
n_selected = len(selected)
n_with_email = int(selected["POC Email"].astype(str).str.contains("@", na=False).sum())
n_need_enrich = n_selected - n_with_email

st.caption(f"{n_selected} selected · {n_with_email} already have email · {n_need_enrich} would go through Hunter")

# ---------- Step 3: import ----------
st.divider()
do_enrich = st.checkbox(
    "Enrich missing emails via Hunter (skips rows that already have one)",
    value=True,
    disabled=not secret("apis", "hunter_api_key"),
    help=(
        "Each Hunter call uses 1 credit (free tier = 25/month). "
        "Disabled if Hunter isn't configured in secrets."
    ),
)

if st.button("Import selected to Signal Based Outreach", type="primary"):
    if not sheet_id():
        st.error("Sheet not configured. Open Settings.")
        st.stop()
    if selected.empty:
        st.warning("Nothing selected.")
        st.stop()

    from core.sheets import append_row, dedupe_against
    from core.enrich.finder import find_email

    has_hunter = bool(secret("apis", "hunter_api_key"))
    added, skipped, enriched = 0, 0, 0
    failures: list[str] = []
    progress = st.progress(0.0)
    log = st.empty()
    imported_rows: list[dict] = []  # capture for the drafts section

    for i, (_, row) in enumerate(selected.iterrows(), 1):
        candidate = {
            "Name of Organisation": str(row.get("Name of Organisation", "")).strip(),
            "Organisation Website": str(row.get("Organisation Website", "")).strip(),
            "Organisation Sector": sector,
            "POC Name": str(row.get("POC Name", "")).strip(),
            "POC Job Title": str(row.get("POC Job Title", "")).strip(),
            "POC LinkedIn": str(row.get("POC LinkedIn", "")).strip(),
            "POC Email": str(row.get("POC Email", "")).strip(),
            "Source of Signal": "Apollo CSV",
            "180DC POC": OWNERS.get(sector, ""),
            "Date of Entry": dt.date.today().isoformat(),
        }

        # Dedupe by LinkedIn/email/name (first hit wins)
        existing = dedupe_against(
            TAB_SIGNAL,
            candidate,
            keys=("POC LinkedIn", "POC Email", "POC Name"),
        )
        if existing:
            skipped += 1
            log.caption(f"({i}/{n_selected}) skipped duplicate: {candidate['POC Name']} @ {candidate['Name of Organisation']}")
            progress.progress(i / n_selected)
            continue

        # Enrich if we don't have an email yet
        if not candidate["POC Email"] and do_enrich and has_hunter:
            domain = _extract_domain(candidate["Organisation Website"])
            if domain:
                parts = candidate["POC Name"].split(" ", 1)
                first = parts[0] if parts else ""
                last = parts[1] if len(parts) > 1 else ""
                try:
                    result = find_email(domain, first or None, last or None)
                    if result.get("email"):
                        candidate["POC Email"] = result["email"]
                        if result.get("position") and not candidate["POC Job Title"]:
                            candidate["POC Job Title"] = result["position"]
                        enriched += 1
                except Exception as e:
                    failures.append(f"{candidate['POC Name']}: {e}")

        try:
            append_row(TAB_SIGNAL, candidate, SIGNAL_SCHEMA, sector=sector)
            added += 1
            imported_rows.append(candidate)
            log.caption(f"({i}/{n_selected}) added {candidate['POC Name']} @ {candidate['Name of Organisation']}")
        except Exception as e:
            failures.append(f"Append failed for {candidate['POC Name']}: {e}")
            skipped += 1

        progress.progress(i / n_selected)

    st.success(f"Added **{added}** · enriched **{enriched}** · skipped **{skipped}**")
    if failures:
        with st.expander(f"{len(failures)} failures"):
            for f in failures:
                st.text(f)

    # Stash for the bulk-draft section
    st.session_state["apollo_imported"] = imported_rows
    st.session_state["apollo_imported_sector"] = sector

# ---------- Step 4: bulk drafts ----------
imported = st.session_state.get("apollo_imported")
if imported:
    st.divider()
    st.subheader("Draft messages for the just-imported batch")
    st.caption("Generates a draft per lead in one batch. Review each below, edit in place, copy what works.")

    fmt_label = st.radio(
        "Format",
        ["LinkedIn connection note (≤300 chars)", "LinkedIn DM (≤800 chars)", "Cold email (≤120 words)"],
        horizontal=False,
    )
    from core.llm.drafts import FORMAT_EMAIL, FORMAT_LINKEDIN_DM, FORMAT_LINKEDIN_NOTE

    fmt = {
        "LinkedIn connection note (≤300 chars)": FORMAT_LINKEDIN_NOTE,
        "LinkedIn DM (≤800 chars)": FORMAT_LINKEDIN_DM,
        "Cold email (≤120 words)": FORMAT_EMAIL,
    }[fmt_label]

    cols = st.columns(2)
    signal = cols[0].selectbox("Signal observed (applies to all drafts)", SIGNALS, index=0)
    signal_details_default = cols[1].text_input(
        "Signal details (or leave blank for a generic Apollo-fit framing)",
        placeholder="e.g. raised $4M Series A from Fireside in March 2026",
    )

    t1, t2, t3 = st.columns(3)
    tone = t1.select_slider("Tone", options=["formal", "neutral", "casual"], value="neutral")
    length = t2.select_slider("Length", options=["short", "medium"], value="medium")
    emphasis = t3.select_slider("Signal emphasis", options=["subtle", "balanced", "explicit"], value="balanced")

    if st.button("Generate drafts for all imported leads", type="primary"):
        from core.llm.drafts import draft

        imported_sector = st.session_state.get("apollo_imported_sector", sector)
        drafts: list[dict] = []
        progress = st.progress(0.0)
        log = st.empty()
        for i, row in enumerate(imported, 1):
            inputs = {
                "company": row.get("Name of Organisation", ""),
                "poc_name": row.get("POC Name", ""),
                "poc_role": row.get("POC Job Title") or "Founder / Co-founder",
                "sector": imported_sector,
                "signal": signal,
                "signal_details": signal_details_default or f"Apollo flagged them as a fit for {imported_sector}",
                "tone": tone,
                "length": length,
                "emphasis": emphasis,
            }
            try:
                result = draft(fmt, inputs)
                drafts.append({"poc": row["POC Name"], "company": row["Name of Organisation"], **result})
                log.caption(f"({i}/{len(imported)}) drafted for {row['POC Name']}")
            except Exception as e:
                drafts.append({"poc": row["POC Name"], "company": row["Name of Organisation"], "error": str(e)})
            progress.progress(i / len(imported))
        st.session_state["apollo_drafts"] = drafts

    drafts = st.session_state.get("apollo_drafts", [])
    if drafts:
        st.markdown(f"**{len(drafts)} drafts ready.** Edit in place, copy what you want.")
        for idx, d in enumerate(drafts):
            with st.expander(f"{d['poc']} — {d['company']}", expanded=False):
                if d.get("error"):
                    st.error(f"Draft failed: {d['error']}")
                elif "subject" in d:
                    st.markdown("**Subject**")
                    st.code(d.get("subject", ""), language="text")
                    st.markdown("**Body**")
                    st.text_area("body", value=d.get("body", ""), height=240, key=f"body_{idx}", label_visibility="collapsed")
                else:
                    msg = d.get("message", "")
                    st.markdown(f"**Message** · {len(msg)} chars")
                    st.text_area("message", value=msg, height=160, key=f"msg_{idx}", label_visibility="collapsed")
