"""Apollo (via Instant Data Scraper) → tracker pipeline.

Expects a CSV with these 8 columns (after trimming inside the extension):
- POC Name
- POC Apollo        (Apollo profile URL of the person)
- Designation
- Company Apollo    (Apollo profile URL of the company)
- Company Name
- POC Linkedin
- Location
- Sector

Workflow:
1. Upload CSV.
2. Confirm column mapping (auto-detected, manual override available).
3. Pick a batch sector from our 15-sector list (drives analyst routing).
4. Review + tick rows. Import to Signal Based Outreach.
5. If Brave is configured, the app resolves each company's domain via Brave
   and then calls Hunter to find the email. Without Brave, rows go in with
   blank emails (you can fill them later via the Enrich page).
6. Bulk draft generation for the imported batch.

Apollo URLs + Location + CSV sector are preserved in the Signal Details column
so the granular info isn't lost.
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
st.caption("Instant Data Scraper CSV → review → import → enrich → bulk drafts")


# ---------- Target field definitions ----------
# Direct fields go straight to their tracker column.
# Context fields get composed into Signal Details with a label prefix.
DIRECT_FIELDS = [
    "POC Name",
    "POC Job Title",
    "Name of Organisation",
    "POC LinkedIn",
]
CONTEXT_FIELDS = {
    # field -> label used in Signal Details
    "Location": "Location",
    "CSV Sector": "Sector (from CSV)",
    "POC Apollo URL": "Apollo POC",
    "Company Apollo URL": "Apollo Co",
}
OPTIONAL_FIELDS = [
    "POC Email",
    "Organisation Website",
]
TARGET_FIELDS = DIRECT_FIELDS + list(CONTEXT_FIELDS.keys()) + OPTIONAL_FIELDS


def _guess_field(csv_col: str) -> str:
    c = csv_col.lower().strip()
    # Apollo URL columns first (more specific than plain "linkedin"/"website")
    if "apollo" in c:
        if "company" in c or "co " in c or "org" in c:
            return "Company Apollo URL"
        return "POC Apollo URL"
    if "linkedin" in c:
        return "POC LinkedIn"
    if c in ("poc name", "name", "full name", "contact name", "person name"):
        return "POC Name"
    if c in ("designation", "title", "job title", "position") or "title" in c or "designation" in c:
        return "POC Job Title"
    if c in ("company name", "company", "account name", "account", "organisation", "organization", "employer"):
        return "Name of Organisation"
    if c == "location" or "location" in c or "city" in c or "country" in c:
        return "Location"
    if c == "sector" or "sector" in c or "industry" in c:
        return "CSV Sector"
    if c.endswith("-href") or c.endswith("_href"):
        if "company" in c:
            return "Organisation Website"
        return "POC LinkedIn"
    if "email" in c:
        return "POC Email"
    if "website" in c or c == "domain":
        return "Organisation Website"
    return ""


# ---------- Step 1: upload ----------
uploaded = st.file_uploader("CSV file (Instant Data Scraper export)", type=["csv"])
if not uploaded:
    st.info(
        "Run your search in Apollo (use filters from the **Keywords** page). "
        "Scrape with the **Instant Data Scraper** Chrome extension. "
        "Trim the CSV to: POC Name, POC Apollo, Designation, Company Apollo, "
        "Company Name, POC Linkedin, Location, Sector. Drop the CSV here."
    )
    st.stop()

try:
    df_raw = pd.read_csv(uploaded)
except Exception as e:
    st.error(f"Couldn't parse CSV: {e}")
    st.stop()

if df_raw.empty:
    st.warning("CSV has 0 rows.")
    st.stop()

csv_cols = list(df_raw.columns)
st.success(f"Loaded {len(df_raw)} rows, {len(csv_cols)} columns.")

with st.expander("Show the raw CSV columns", expanded=False):
    st.write(csv_cols)

# ---------- Step 2: column mapping ----------
st.divider()
st.subheader("Map columns")
st.caption("Auto-detected where possible. Override anything wrong, or set to (none) to skip a field.")

fingerprint = f"{uploaded.name}::{','.join(csv_cols)}"
if st.session_state.get("apollo_csv_fingerprint") != fingerprint:
    st.session_state["apollo_csv_fingerprint"] = fingerprint
    auto = {f: "" for f in TARGET_FIELDS}
    for col in csv_cols:
        guess = _guess_field(col)
        if guess and not auto.get(guess):
            auto[guess] = col
    for f, c in auto.items():
        st.session_state[f"col_map_{f}"] = c if c else "(none)"

options = ["(none)"] + csv_cols
mapping: dict[str, str] = {}

st.markdown("**Tracker columns**")
cols = st.columns(2)
for i, field in enumerate(DIRECT_FIELDS):
    current = st.session_state.get(f"col_map_{field}", "(none)")
    sel = cols[i % 2].selectbox(
        field,
        options=options,
        index=options.index(current) if current in options else 0,
        key=f"col_map_{field}",
    )
    if sel != "(none)":
        mapping[field] = sel

st.markdown("**Context fields** (preserved in Signal Details, not their own column)")
ccols = st.columns(2)
for i, field in enumerate(CONTEXT_FIELDS.keys()):
    current = st.session_state.get(f"col_map_{field}", "(none)")
    sel = ccols[i % 2].selectbox(
        field,
        options=options,
        index=options.index(current) if current in options else 0,
        key=f"col_map_{field}",
    )
    if sel != "(none)":
        mapping[field] = sel

with st.expander("Also map (if your CSV has them) — Email / Website", expanded=False):
    ocols = st.columns(2)
    for i, field in enumerate(OPTIONAL_FIELDS):
        current = st.session_state.get(f"col_map_{field}", "(none)")
        sel = ocols[i % 2].selectbox(
            field,
            options=options,
            index=options.index(current) if current in options else 0,
            key=f"col_map_{field}",
        )
        if sel != "(none)":
            mapping[field] = sel

# Build the normalized dataframe
normalized = pd.DataFrame(index=df_raw.index)
for field, csv_col in mapping.items():
    normalized[field] = df_raw[csv_col].astype(str).fillna("").str.strip()
for col in TARGET_FIELDS:
    if col not in normalized.columns:
        normalized[col] = ""

clean = normalized[
    (normalized["POC Name"].str.strip() != "")
    & (normalized["Name of Organisation"].str.strip() != "")
].copy()

c1, c2, c3 = st.columns(3)
c1.metric("Rows in CSV", len(df_raw))
c2.metric("Usable rows", len(clean))
c3.metric("With LinkedIn", int((clean["POC LinkedIn"].str.strip() != "").sum()))

if clean.empty:
    st.error("No usable rows. Need at least **POC Name** and **Name of Organisation** mapped.")
    st.stop()

# ---------- Step 3: batch sector + review ----------
st.divider()
st.subheader("Batch sector")
st.caption("Drives analyst routing. The CSV's specific sector value is preserved separately in Signal Details.")

default_sector = st.session_state.get("default_sector", SECTORS[0])
scol1, scol2 = st.columns([3, 2])
sector = scol1.selectbox(
    "Sector",
    SECTORS,
    index=SECTORS.index(default_sector) if default_sector in SECTORS else 0,
    label_visibility="collapsed",
)
analyst = OWNERS.get(sector, "—")
scol2.markdown(
    f"**180DC POC:** :green[{analyst}]"
    if analyst != "—"
    else f"**180DC POC:** :red[unassigned]"
)
st.caption(
    f"All imported rows will be tagged with sector **{sector}** and routed to **{analyst}**. "
    "If that's wrong, change the sector above before importing."
)

st.subheader("Review and select")
preview_cols = ["POC Name", "POC Job Title", "Name of Organisation", "POC LinkedIn", "Location", "CSV Sector"]
for opt in ("POC Email", "POC Apollo URL", "Company Apollo URL", "Organisation Website"):
    if (clean[opt].str.strip() != "").any():
        preview_cols.append(opt)

preview = clean[preview_cols].copy()
preview.insert(0, "import", True)

edited = st.data_editor(
    preview,
    width="stretch",
    hide_index=True,
    column_config={"import": st.column_config.CheckboxColumn(required=True)},
    key="apollo_editor",
)

selected = edited[edited["import"] == True]
n_selected = len(selected)
n_with_email = int(selected["POC Email"].astype(str).str.contains("@", na=False).sum()) if "POC Email" in selected.columns else 0
n_need_enrich = n_selected - n_with_email
st.caption(f"{n_selected} selected · {n_with_email} already have email · {n_need_enrich} would need enrichment")

# ---------- Step 4: import ----------
st.divider()

has_hunter = bool(secret("apis", "hunter_api_key"))
has_brave = bool(secret("apis", "brave_api_key"))

if not has_hunter:
    st.warning("Hunter not configured. Rows will import without emails.")
else:
    if has_brave:
        st.info("Domain resolution: Brave (best) → free DNS guesser fallback.")
    else:
        st.info(
            "Brave not configured, so domains will be guessed via a free DNS check "
            "(catches most common Indian brand patterns like `slurrpfarm.com`). "
            "Rows where the guess fails will import without emails — fill them in "
            "manually via the **Enrich** page."
        )

do_enrich = st.checkbox(
    "Find email via Hunter for each row (resolves domain first)",
    value=has_hunter,
    disabled=not has_hunter,
    help="One Hunter call per row that needs enrichment. Domain resolution is free.",
)


def _extract_domain(website: str) -> str:
    if not website:
        return ""
    d = website.strip().replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]
    return d.replace("www.", "")


def _compose_signal_details(row: pd.Series) -> str:
    parts = []
    for field, label in CONTEXT_FIELDS.items():
        v = str(row.get(field, "")).strip()
        if v:
            parts.append(f"{label}: {v}")
    return " | ".join(parts)


if st.button("Import selected to Signal Based Outreach", type="primary"):
    if not sheet_id():
        st.error("Sheet not configured. Open Settings.")
        st.stop()
    if selected.empty:
        st.warning("Nothing selected.")
        st.stop()

    from core.sheets import append_rows, read_df
    from core.enrich.finder import find_email
    from core.sources.domain_guess import guess_domain as dns_guess_domain
    if has_brave:
        from core.sources.brave import find_domain as brave_find_domain
    else:
        brave_find_domain = None

    # Pre-build dedupe lookups. LinkedIn is the strongest key; name+company
    # is the fallback when LinkedIn is missing on either side. One read.
    existing_linkedin: set = set()
    existing_name_company: set = set()
    try:
        df_existing = read_df(TAB_SIGNAL)
        if not df_existing.empty:
            for _, r in df_existing.iterrows():
                li = str(r.get("POC LinkedIn", "")).strip().lower()
                p = str(r.get("POC Name", "")).strip().lower()
                c = str(r.get("Name of Organisation", "")).strip().lower()
                if li:
                    existing_linkedin.add(li)
                if p and c:
                    existing_name_company.add((p, c))
    except Exception as e:
        st.warning(f"Couldn't read existing rows for dedupe: {e}. Proceeding without dedupe.")

    # Phase 1: dedupe + enrich in memory. NO Sheets writes here.
    skipped = 0
    enriched = 0
    failures: list[str] = []
    to_append: list[dict] = []
    progress = st.progress(0.0)
    log = st.empty()

    for i, (_, row) in enumerate(selected.iterrows(), 1):
        poc_name = str(row.get("POC Name", "")).strip()
        company = str(row.get("Name of Organisation", "")).strip()
        poc_li = str(row.get("POC LinkedIn", "")).strip()

        candidate = {
            "Name of Organisation": company,
            "Organisation Website": str(row.get("Organisation Website", "")).strip(),
            "Organisation Sector": sector,
            "POC Name": poc_name,
            "POC Job Title": str(row.get("POC Job Title", "")).strip(),
            "POC LinkedIn": poc_li,
            "POC Email": str(row.get("POC Email", "")).strip(),
            "Signal Details": _compose_signal_details(row),
            "Source of Signal": "Apollo (Instant Data Scraper)",
            "180DC POC": OWNERS.get(sector, ""),
            "Date of Entry": dt.date.today().isoformat(),
        }

        # Dedupe: LinkedIn first, then name+company fallback
        if poc_li and poc_li.lower() in existing_linkedin:
            skipped += 1
            log.caption(f"({i}/{n_selected}) skipped duplicate LinkedIn: {poc_name}")
            progress.progress(i / n_selected)
            continue
        nc_key = (poc_name.lower(), company.lower())
        if nc_key in existing_name_company:
            skipped += 1
            log.caption(f"({i}/{n_selected}) skipped duplicate (name+company): {poc_name} @ {company}")
            progress.progress(i / n_selected)
            continue

        # Enrich if needed (external APIs, not Google Sheets)
        if not candidate["POC Email"] and do_enrich:
            domain = _extract_domain(candidate["Organisation Website"])
            if not domain and brave_find_domain is not None:
                try:
                    domain = brave_find_domain(company) or ""
                except Exception as e:
                    failures.append(f"{poc_name}: Brave domain lookup failed ({e})")
            if not domain:
                try:
                    domain = dns_guess_domain(company) or ""
                except Exception as e:
                    failures.append(f"{poc_name}: DNS guess failed ({e})")
            if domain:
                candidate["Organisation Website"] = f"https://{domain}"
                parts = poc_name.split(" ", 1)
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
                    failures.append(f"{poc_name}: Hunter failed ({e})")

        to_append.append(candidate)
        if poc_li:
            existing_linkedin.add(poc_li.lower())
        existing_name_company.add(nc_key)
        log.caption(f"({i}/{n_selected}) queued {poc_name} @ {company}")
        progress.progress(i / n_selected)

    # Phase 2: single batch write to the Sheet (1 API call for all rows).
    added = 0
    if to_append:
        with st.spinner(f"Writing {len(to_append)} rows to Sheet..."):
            try:
                added = append_rows(TAB_SIGNAL, to_append, SIGNAL_SCHEMA, sector=sector)
            except Exception as e:
                failures.append(f"Batch append failed: {e}")

    st.success(f"Added **{added}** · enriched **{enriched}** · skipped **{skipped}**")
    if failures:
        with st.expander(f"{len(failures)} failures / warnings"):
            for f in failures:
                st.text(f)

    st.session_state["apollo_imported"] = to_append[:added] if added else []
    st.session_state["apollo_imported_sector"] = sector

# ---------- Step 5: bulk drafts ----------
imported = st.session_state.get("apollo_imported")
if imported:
    st.divider()
    st.subheader("Draft messages for the just-imported batch")
    st.caption("One Gemini call per lead. Review each below, edit in place, copy what works.")

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

    sc = st.columns(2)
    signal = sc[0].selectbox("Signal observed (applies to all drafts)", SIGNALS, index=0)
    signal_details_override = sc[1].text_input(
        "Signal details (leave blank to use the per-row Location + CSV sector)",
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
                "signal_details": (
                    signal_details_override
                    or row.get("Signal Details")
                    or f"Apollo flagged them as a fit for {imported_sector}"
                ),
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
