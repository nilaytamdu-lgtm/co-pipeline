"""Apollo CSV → tracker pipeline.

Works with both:
- Apollo native CSV export (includes POC Email when Apollo has it)
- Instant Data Scraper CSV (no email — Hunter/Snov fills the gap)

Expected columns (any subset — auto-detected, manually overridable):
- POC Name
- POC Email            (Apollo native — used as-is when present)
- Designation / Title
- Company Name
- POC Linkedin
- POC Apollo URL       (Apollo profile URL of the person)
- Company Apollo URL   (Apollo profile URL of the company)
- Location
- Sector / Industry

Workflow:
1. Upload CSV.
2. Confirm column mapping (auto-detected).
3. Pick a batch sector from our 15-sector list (drives analyst routing).
4. Review + tick rows. Import to Signal Based Outreach.
5. For rows missing an email, the app resolves the domain (Brave if
   configured, free DNS fallback otherwise) then calls Hunter → Snov
   to find one. Rows that already have an email from Apollo skip this
   entirely — no API credit spent.
6. Bulk draft generation for the imported batch.

Apollo URLs + Location + CSV sector are preserved in the Signal Details column
so the granular info isn't lost.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from core.config import (
    ANALYST_SECTORS,
    AUTOMATION_ANALYSTS,
    CHANNEL_AUTOMATION,
    CHANNEL_LINKEDIN,
    OWNERS,
    RELATIONSHIP_ANALYSTS,
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

# Heads-up for users whose primary work isn't automation outreach
_current_user_top = st.session_state.get("current_user")
if _current_user_top and _current_user_top in RELATIONSHIP_ANALYSTS:
    st.info(
        f"Hey {_current_user_top} — this page is for the **automation (email) channel**, which the "
        f"sector analysts ({', '.join(AUTOMATION_ANALYSTS)}) primarily run. "
        "Your work on **Engagement Led** and **Organization Based** outreach lives in the "
        "**Tracker** tab. You can still use this page if you want — just flagging."
    )


# ---------- Target field definitions ----------
# Direct fields go straight to their tracker column.
# Context fields get composed into Signal Details with a label prefix.
# POC Email is direct now because Apollo native exports include it.
DIRECT_FIELDS = [
    "POC Name",
    "POC Job Title",
    "Name of Organisation",
    "POC LinkedIn",
    "POC Email",
]
CONTEXT_FIELDS = {
    # field -> label used in Signal Details
    "Location": "Location",
    "CSV Sector": "Sector (from CSV)",
    "POC Apollo URL": "Apollo POC",
    "Company Apollo URL": "Apollo Co",
}
OPTIONAL_FIELDS = [
    "Organisation Website",
    "First Name",
    "Last Name",
]
TARGET_FIELDS = DIRECT_FIELDS + list(CONTEXT_FIELDS.keys()) + OPTIONAL_FIELDS


def _guess_field(csv_col: str) -> str:
    c = csv_col.lower().strip()
    # Apollo URL columns first (more specific than plain "linkedin"/"website")
    if "apollo" in c:
        if "company" in c or "co " in c or "org" in c:
            return "Company Apollo URL"
        return "POC Apollo URL"
    # Email first — Apollo native uses just "Email" or "Personal Email"
    if "email" in c:
        return "POC Email"
    # Person/Company LinkedIn URL (Apollo native split)
    if "linkedin" in c:
        if "company" in c or "organization" in c or "organisation" in c:
            return ""  # ignore — we don't track company LinkedIn
        return "POC LinkedIn"
    if c in ("first name", "firstname", "given name"):
        return "First Name"
    if c in ("last name", "lastname", "surname", "family name"):
        return "Last Name"
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
    if "website" in c or c == "domain":
        return "Organisation Website"
    return ""


# ---------- Step 1: upload ----------
uploaded = st.file_uploader("CSV file (Apollo native export or Instant Data Scraper)", type=["csv"])
if not uploaded:
    st.info(
        "Run your search in Apollo (use filters from the **Keywords** page). "
        "Export as CSV (Apollo native gives you POC emails when it has them) "
        "or scrape with the **Instant Data Scraper** extension. "
        "Useful columns: POC Name (or First/Last Name), Title, Company, "
        "Email, Person LinkedIn URL, Location, Industry, Apollo URLs. "
        "Drop the CSV here."
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

with st.expander("Also map (if your CSV has them) — Website / split First+Last Name", expanded=False):
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

# If the CSV split the name into First + Last (Apollo native does this),
# stitch them together into POC Name where POC Name itself wasn't mapped.
if "First Name" in mapping or "Last Name" in mapping:
    needs_combine = normalized["POC Name"].str.strip() == ""
    combined = (normalized["First Name"].fillna("") + " " + normalized["Last Name"].fillna("")).str.strip()
    normalized.loc[needs_combine, "POC Name"] = combined[needs_combine]

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
current_user = st.session_state.get("current_user")
suggested_owner = OWNERS.get(default_sector, "")

scol1, scol2 = st.columns([3, 2])
sector = scol1.selectbox(
    "Sector",
    SECTORS,
    index=SECTORS.index(default_sector) if default_sector in SECTORS else 0,
    label_visibility="collapsed",
)
suggested = OWNERS.get(sector, "")

scol2.markdown(f"**180DC POC:** :green[{current_user or '—'}]")

if not current_user:
    st.warning("Pick yourself in the **I am** dropdown at the top of the sidebar first. Imported rows get tagged with whoever's logged in.")
else:
    msg = f"Rows will be tagged with sector **{sector}** and 180DC POC **{current_user}**."
    if suggested and suggested != current_user and current_user in ANALYST_SECTORS:
        # Only show the cross-allocation hint for Analysts who have an allocation
        my_sectors = ", ".join(ANALYST_SECTORS.get(current_user, []))
        msg += (
            f" Heads up: sector **{sector}** is normally **{suggested}**'s allocation. "
            f"You're tagged as the 180DC POC regardless, but if this is a mistake, "
            f"your sectors are: {my_sectors}."
        )
    st.caption(msg)

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
st.caption(
    f"{n_selected} selected · **{n_with_email} already have email** (kept as-is) · "
    f"**{n_need_enrich} missing email** (will be enriched via Hunter → Snov if you enable below)"
)

# ---------- Step 4: import ----------
st.divider()

has_hunter = bool(secret("apis", "hunter_api_key"))
has_snov = bool(secret("apis", "snov_user_id")) and bool(secret("apis", "snov_secret"))
has_brave = bool(secret("apis", "brave_api_key"))

providers = []
if has_hunter:
    providers.append("Hunter")
if has_snov:
    providers.append("Snov")

if not providers:
    st.warning(
        "Neither Hunter nor Snov is configured. Rows already containing an "
        "email will still import; rows without one will go in blank."
    )
else:
    chain = " → ".join(providers)
    if has_brave:
        st.info(f"Enrichment chain for missing emails: {chain}. Domain resolution: Brave → free DNS guesser fallback.")
    else:
        st.info(
            f"Enrichment chain for missing emails: {chain}. "
            "Brave not configured, so domains will be guessed via a free DNS check "
            "(catches most common Indian brand patterns like `slurrpfarm.com`). "
            "Rows where domain resolution fails will import without emails — fill "
            "them in manually via the **Enrich** page."
        )

do_enrich = st.checkbox(
    "Enrich rows that are missing an email (Hunter → Snov)",
    value=bool(providers),
    disabled=not providers,
    help=(
        "Only rows where the POC Email cell is empty go through enrichment. "
        "Rows that already have an Apollo email are kept as-is and cost no API credits."
    ),
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

    # Pre-build dedupe lookups. LinkedIn and Email are the strongest keys;
    # name+company is the fallback when both are missing on either side. One read.
    existing_linkedin: set = set()
    existing_email: set = set()
    existing_name_company: set = set()
    try:
        df_existing = read_df(TAB_SIGNAL)
        if not df_existing.empty:
            for _, r in df_existing.iterrows():
                li = str(r.get("POC LinkedIn", "")).strip().lower()
                em = str(r.get("POC Email", "")).strip().lower()
                p = str(r.get("POC Name", "")).strip().lower()
                c = str(r.get("Name of Organisation", "")).strip().lower()
                if li:
                    existing_linkedin.add(li)
                if em:
                    existing_email.add(em)
                if p and c:
                    existing_name_company.add((p, c))
    except Exception as e:
        st.warning(f"Couldn't read existing rows for dedupe: {e}. Proceeding without dedupe.")

    # Phase 1: dedupe + enrich in memory. NO Sheets writes here.
    skipped = 0
    enriched = 0
    failures: list[str] = []
    to_append: list[dict] = []
    # Providers that fatally died this batch (auth / quota). Once a provider
    # lands here, every subsequent row skips it instead of burning the same
    # 401 / 402 over and over.
    dead_providers: set[str] = set()
    provider_deaths: dict[str, dict] = {}  # provider -> {kind, message}
    progress = st.progress(0.0)
    log = st.empty()

    for i, (_, row) in enumerate(selected.iterrows(), 1):
        poc_name = str(row.get("POC Name", "")).strip()
        company = str(row.get("Name of Organisation", "")).strip()
        poc_li = str(row.get("POC LinkedIn", "")).strip()
        poc_email_in = str(row.get("POC Email", "")).strip()

        candidate = {
            "Name of Organisation": company,
            "Organisation Website": str(row.get("Organisation Website", "")).strip(),
            "Organisation Sector": sector,
            "POC Name": poc_name,
            "POC Job Title": str(row.get("POC Job Title", "")).strip(),
            "POC LinkedIn": poc_li,
            "POC Email": poc_email_in,
            "Signal Details": _compose_signal_details(row),
            "Source of Signal": "Apollo",
            "180DC POC": current_user or OWNERS.get(sector, ""),
            "Date of Entry": dt.date.today().isoformat(),
        }

        # Dedupe: LinkedIn → Email → name+company fallback
        if poc_li and poc_li.lower() in existing_linkedin:
            skipped += 1
            log.caption(f"({i}/{n_selected}) skipped duplicate LinkedIn: {poc_name}")
            progress.progress(i / n_selected)
            continue
        if poc_email_in and poc_email_in.lower() in existing_email:
            skipped += 1
            log.caption(f"({i}/{n_selected}) skipped duplicate email: {poc_name} <{poc_email_in}>")
            progress.progress(i / n_selected)
            continue
        nc_key = (poc_name.lower(), company.lower())
        if nc_key in existing_name_company:
            skipped += 1
            log.caption(f"({i}/{n_selected}) skipped duplicate (name+company): {poc_name} @ {company}")
            progress.progress(i / n_selected)
            continue

        # Enrich if needed (external APIs, not Google Sheets)
        # If every enrichment provider is already dead this batch, skip the
        # domain lookup entirely — saves time and stops spinning.
        all_providers_dead = (
            ("hunter" in dead_providers or not has_hunter)
            and ("snov" in dead_providers or not has_snov)
        )
        if not candidate["POC Email"] and do_enrich and not all_providers_dead:
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
                    result = find_email(
                        domain,
                        first or None,
                        last or None,
                        skip_providers=dead_providers,
                    )
                except Exception as e:
                    # Should be rare — find_email handles its own provider errors
                    failures.append(f"{poc_name}: enrichment crashed ({e})")
                    result = {}

                # Mark any provider that just fatally died (auth / quota)
                fe = result.get("fatal_error") if isinstance(result, dict) else None
                if fe:
                    prov = fe.get("provider")
                    if prov and prov not in dead_providers:
                        dead_providers.add(prov)
                        provider_deaths[prov] = {
                            "kind": fe.get("kind"),
                            "message": fe.get("message"),
                        }
                        failures.append(
                            f"PROVIDER DOWN: {prov} ({fe.get('kind')}) — {fe.get('message')}. "
                            f"Skipping {prov} for the rest of this batch."
                        )

                if result.get("email"):
                    candidate["POC Email"] = result["email"]
                    if result.get("position") and not candidate["POC Job Title"]:
                        candidate["POC Job Title"] = result["position"]
                    enriched += 1

        # Decide outreach channel based on final email state.
        # Email present (from CSV or enriched) → Automation. Otherwise LinkedIn.
        candidate["Outreach Channel"] = (
            CHANNEL_AUTOMATION if candidate.get("POC Email") else CHANNEL_LINKEDIN
        )

        to_append.append(candidate)
        if poc_li:
            existing_linkedin.add(poc_li.lower())
        # Track the email we end up with (CSV or enriched) so subsequent rows
        # in the same batch don't duplicate it.
        final_email = candidate.get("POC Email", "").strip().lower()
        if final_email:
            existing_email.add(final_email)
        existing_name_company.add(nc_key)
        log.caption(f"({i}/{n_selected}) queued {poc_name} @ {company} → {candidate['Outreach Channel']}")
        progress.progress(i / n_selected)

    # Phase 2: single batch write to the Sheet (1 API call for all rows).
    added = 0
    if to_append:
        with st.spinner(f"Writing {len(to_append)} rows to Sheet..."):
            try:
                added = append_rows(TAB_SIGNAL, to_append, SIGNAL_SCHEMA, sector=sector)
            except Exception as e:
                failures.append(f"Batch append failed: {e}")

    n_automation = sum(1 for r in to_append[:added] if r.get("Outreach Channel") == CHANNEL_AUTOMATION)
    n_linkedin = sum(1 for r in to_append[:added] if r.get("Outreach Channel") == CHANNEL_LINKEDIN)

    # Show the provider-death banner FIRST — it explains why so many rows
    # might have landed in LinkedIn outreach instead of being enriched.
    if provider_deaths:
        for prov, info in provider_deaths.items():
            kind = info.get("kind", "")
            message = info.get("message", "")
            if "Auth" in kind:
                title = f"{prov.title()} API key was rejected"
                advice = (
                    f"Your **{prov} key looks invalid or revoked**. "
                    f"Open Settings, regenerate the key on {prov}.io, and paste it into "
                    f"`.streamlit/secrets.toml` (or the Streamlit Cloud secrets manager). "
                    f"Until that's fixed, every row will route to LinkedIn outreach."
                )
            elif "Quota" in kind:
                title = f"{prov.title()} credits are exhausted"
                advice = (
                    f"Your **{prov} monthly quota is gone**. Either wait for the next "
                    f"reset, swap in a different account's key, or upgrade the plan. "
                    f"Until that's fixed, every row will route to LinkedIn outreach. "
                    f"See the workarounds section on the **Settings** page."
                )
            elif "Rate" in kind:
                title = f"{prov.title()} rate-limited"
                advice = f"{prov} returned 429. Wait a minute and re-run the import."
            else:
                title = f"{prov.title()} failed"
                advice = f"Provider error: {message}"
            st.error(f"**{title}.** {advice}", icon="⚠️")

    st.success(
        f"Added **{added}** rows · enriched **{enriched}** emails · skipped **{skipped}** duplicates\n\n"
        f"→ **{n_automation}** ready for email automation · **{n_linkedin}** for LinkedIn outreach"
    )
    if failures:
        with st.expander(f"{len(failures)} failures / warnings", expanded=bool(provider_deaths)):
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
