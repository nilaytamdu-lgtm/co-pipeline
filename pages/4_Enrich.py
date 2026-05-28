import pandas as pd
import streamlit as st

from core.config import (
    OWNERS,
    POC_HIERARCHY,
    SECTORS,
    SIGNAL_SCHEMA,
    TAB_SIGNAL,
    secret,
    sheet_id,
)
from core.ui import apply_branding

apply_branding()

st.title("Enrich Leads")
st.caption("Find POCs and emails — Hunter chain (Snov/Skrapp/Dropcontact slot in when keys arrive)")

_any_finder = (
    bool(secret("apis", "hunter_api_key"))
    or (bool(secret("apis", "snov_user_id")) and bool(secret("apis", "snov_secret")))
    or bool(secret("apis", "skrapp_api_key"))
    or bool(secret("apis", "getprospect_api_key"))
)
if not _any_finder:
    st.error(
        "No email-finder providers configured. Add at least one of: "
        "`apis.hunter_api_key`, `apis.snov_user_id` + `apis.snov_secret`, "
        "`apis.skrapp_api_key`, `apis.getprospect_api_key` to secrets.toml."
    )
    st.stop()

# Quota panel (free, doesn't consume credits)
with st.expander("Provider quota", expanded=False):
    # Hunter
    try:
        from core.enrich import hunter

        acct = hunter.account()
        if acct:
            calls = acct.get("calls", {}) or {}
            st.write(
                {
                    "Hunter plan": acct.get("plan_name"),
                    "Hunter searches used / available": f"{(calls.get('search', {}) or {}).get('used', 0)} / {(calls.get('search', {}) or {}).get('available', 0)}",
                    "Hunter verifications used / available": f"{(calls.get('verify', {}) or {}).get('used', 0)} / {(calls.get('verify', {}) or {}).get('available', 0)}",
                    "Hunter reset": acct.get("reset_date"),
                }
            )
    except Exception as e:
        st.warning(f"Hunter quota fetch failed: {e}")

    # Snov
    if secret("apis", "snov_user_id") and secret("apis", "snov_secret"):
        try:
            from core.enrich import snov

            bal = snov.balance()
            st.write({"Snov balance": bal.get("balance"), "Snov daily limit": bal.get("limit")})
        except Exception as e:
            st.warning(f"Snov quota fetch failed: {e}")
    else:
        st.caption("Snov not configured.")

    # Skrapp
    if secret("apis", "skrapp_api_key"):
        try:
            from core.enrich import skrapp

            st.write({"Skrapp account": skrapp.account()})
        except Exception as e:
            st.warning(f"Skrapp quota fetch failed: {e}")
    else:
        st.caption("Skrapp not configured (free 150/mo at skrapp.io/api).")

    # GetProspect
    if secret("apis", "getprospect_api_key"):
        try:
            from core.enrich import getprospect

            st.write({"GetProspect account": getprospect.account()})
        except Exception as e:
            st.warning(f"GetProspect quota fetch failed: {e}")
    else:
        st.caption("GetProspect not configured (free 100/mo at getprospect.com).")

st.divider()

mode = st.radio("Mode", ["Manual lookup", "From Sheet (Signal Based Outreach)"], horizontal=True)

_brave_ready = bool(secret("apis", "brave_api_key"))


def _lookup_domain(name: str) -> tuple[str | None, str]:
    """Try Brave first if configured, fall back to free DNS guess. Returns (domain, source)."""
    if not name:
        return None, ""
    if _brave_ready:
        try:
            from core.sources.brave import find_domain
            d = find_domain(name)
            if d:
                return d, "Brave"
        except Exception:
            pass
    try:
        from core.sources.domain_guess import guess_domain
        d = guess_domain(name)
        if d:
            return d, "DNS guess"
    except Exception:
        pass
    return None, ""


if mode == "Manual lookup":
    c1, c2 = st.columns(2)
    company = c1.text_input("Company (optional)", placeholder="e.g. Slurrp Farm", key="manual_company")
    domain = c2.text_input("Domain", placeholder="e.g. slurrpfarm.com", key="manual_domain", value=st.session_state.get("manual_domain_resolved", ""))

    if st.button("Guess domain from company name"):
        if not company:
            st.warning("Type a company name first.")
        else:
            label = "Looking up via Brave..." if _brave_ready else "Trying common patterns + DNS check..."
            with st.spinner(label):
                resolved, source = _lookup_domain(company)
            if resolved:
                st.session_state["manual_domain_resolved"] = resolved
                st.success(f"Found: **{resolved}** (via {source}). Saved into the Domain field. Re-run if it looks wrong.")
                st.rerun()
            else:
                st.warning("Couldn't resolve a domain. Type it manually — Google the company name, copy the address bar.")

    c3, c4 = st.columns(2)
    first = c3.text_input("First name (optional)", placeholder="e.g. Meghana")
    last = c4.text_input("Last name (optional)", placeholder="e.g. Narayan")

    do_verify = st.checkbox("Verify email (uses 1 verification credit)", value=False)

    if st.button("Find email", type="primary"):
        if not domain:
            st.warning("Domain is required. Hunter searches by domain, not company name.")
        else:
            try:
                from core.enrich.finder import find_email

                with st.spinner("Searching..."):
                    result = find_email(domain, first or None, last or None, verify=do_verify)

                fe = result.get("fatal_error")
                if fe:
                    kind = fe.get("kind", "")
                    prov = fe.get("provider", "provider")
                    if "Auth" in kind:
                        st.error(
                            f"**{prov.title()} API key was rejected.** Open Settings and rotate the key. "
                            f"Detail: {fe.get('message')}",
                            icon="⚠️",
                        )
                    elif "Quota" in kind:
                        st.error(
                            f"**{prov.title()} credits are exhausted.** Wait for next month or swap "
                            f"in a different account's key. Detail: {fe.get('message')}",
                            icon="⚠️",
                        )
                    else:
                        st.error(f"**{prov.title()} failed:** {fe.get('message')}", icon="⚠️")

                if result.get("email"):
                    st.success(f"**{result['email']}** · score {result.get('score')} · via `{result['source']}`")
                    st.json(result)
                elif not fe:
                    st.warning("No email found (provider returned no match for this name+domain).")
                    if result.get("alternates"):
                        st.write("Alternates returned by domain search:")
                        st.json(result["alternates"])
            except Exception as e:
                st.error(f"Lookup failed: {e}")

else:
    if not sheet_id():
        st.warning("Configure the Sheet (Settings) to use this mode.")
        st.stop()

    from core.sheets import read_df, update_cells

    try:
        df = read_df(TAB_SIGNAL)
    except Exception as e:
        st.error(f"Read failed: {e}")
        st.stop()

    if df.empty:
        st.info("No rows in Signal Based Outreach yet.")
        st.stop()

    # Show only rows missing an email
    needs_email = df["POC Email"].fillna("").eq("") if "POC Email" in df.columns else df.index == df.index
    candidates = df[needs_email]
    if candidates.empty:
        st.success("Every row already has an email. Nothing to enrich.")
        st.stop()

    st.caption(f"{len(candidates)} row(s) need an email.")

    # Pick one row at a time (simpler, predictable credit usage)
    options = []
    for idx, row in candidates.iterrows():
        label = f"Row {idx + 2}: {row.get('Name of Organisation', '?')} — {row.get('POC Name', '?')}"
        options.append((idx, label))

    pick = st.selectbox("Lead", options, format_func=lambda o: o[1])
    row_idx_df, _ = pick
    row = candidates.loc[row_idx_df]
    sheet_row = int(row_idx_df) + 2  # 1-based + header

    pre_domain = row.get("Organisation Website", "").replace("https://", "").replace("http://", "").rstrip("/")
    domain_key = f"sheet_domain_{row_idx_df}"
    domain = st.text_input("Domain", value=st.session_state.get(domain_key, pre_domain), key=domain_key + "_input")
    if not domain and st.button("Guess domain from company name"):
        company_name = row.get("Name of Organisation", "")
        label = "Looking up via Brave..." if _brave_ready else "Trying common patterns + DNS check..."
        with st.spinner(label):
            resolved, source = _lookup_domain(company_name)
        if resolved:
            st.session_state[domain_key] = resolved
            st.toast(f"Found {resolved} via {source}")
            st.rerun()
        else:
            st.warning("Couldn't resolve. Google the company name and paste the domain manually.")
    poc_name = row.get("POC Name", "") or ""
    parts = poc_name.strip().split(" ", 1)
    first = st.text_input("First name", value=parts[0] if parts else "")
    last = st.text_input("Last name", value=parts[1] if len(parts) > 1 else "")
    do_verify = st.checkbox("Verify email (uses 1 verification credit)", value=False)

    if st.button("Find + save", type="primary"):
        if not domain:
            st.warning("Domain is required.")
        else:
            try:
                from core.enrich.finder import find_email

                with st.spinner("Searching..."):
                    result = find_email(domain, first or None, last or None, verify=do_verify)

                fe = result.get("fatal_error")
                if fe:
                    kind = fe.get("kind", "")
                    prov = fe.get("provider", "provider")
                    if "Auth" in kind:
                        st.error(
                            f"**{prov.title()} API key was rejected.** Rotate it in Settings. "
                            f"Detail: {fe.get('message')}",
                            icon="⚠️",
                        )
                    elif "Quota" in kind:
                        st.error(
                            f"**{prov.title()} credits are exhausted.** Detail: {fe.get('message')}",
                            icon="⚠️",
                        )
                    else:
                        st.error(f"**{prov.title()} failed:** {fe.get('message')}", icon="⚠️")

                if not result.get("email"):
                    if not fe:
                        st.warning("No email found (provider returned no match for this name+domain).")
                else:
                    updates = {"POC Email": result["email"]}
                    if result.get("position") and not row.get("POC Job Title"):
                        updates["POC Job Title"] = result["position"]
                    update_cells(TAB_SIGNAL, sheet_row, updates)
                    st.success(f"Saved **{result['email']}** to row {sheet_row}.")
                    st.json(result)
            except Exception as e:
                st.error(f"Lookup failed: {e}")

# ============================================================
# Bulk backfill: take every LinkedIn-channel row missing an email,
# run the full provider chain, fall back to pattern guessing, then
# move successful rows over to Automation channel.
# ============================================================
st.divider()
st.header("Bulk backfill — LinkedIn channel rows")
st.caption(
    "Grinds through every row currently routed to LinkedIn outreach (because "
    "the importer couldn't find an email at the time), throws the full provider "
    "chain at each one, and falls back to pattern-based guessing when "
    "providers come up dry. Successful rows move to Automation channel."
)

if not sheet_id():
    st.warning("Configure the Sheet (Settings) to use this mode.")
    st.stop()

from core.sheets import read_df as _read_df

try:
    df_all = _read_df(TAB_SIGNAL)
except Exception as e:
    st.error(f"Read failed: {e}")
    st.stop()

if df_all.empty:
    st.info("No rows in Signal Based Outreach.")
    st.stop()

# Find rows that need an email, split by channel for visibility
email_col = df_all["POC Email"] if "POC Email" in df_all.columns else pd.Series([""] * len(df_all), index=df_all.index)
needs = df_all[email_col.astype(str).str.strip().eq("")].copy()

if "Outreach Channel" in needs.columns:
    needs_channel = needs["Outreach Channel"].astype(str).str.strip()
else:
    needs_channel = pd.Series([""] * len(needs), index=needs.index)

in_linkedin = needs[needs_channel.str.lower().str.contains("linkedin", na=False)]
in_blank = needs[needs_channel.eq("")]

bk_cols = st.columns(3)
bk_cols[0].metric("LinkedIn-channel, no email", len(in_linkedin))
bk_cols[1].metric("Blank channel, no email", len(in_blank))
bk_cols[2].metric("Total rows missing email", len(needs))

bk_opts = st.columns(2)
include_blank = bk_opts[0].checkbox("Also include rows with blank Outreach Channel", value=True)
allow_guess = bk_opts[1].checkbox(
    "Allow pattern-guess fallback",
    value=True,
    help=(
        "When providers can't find an email, generate the most likely pattern "
        "(e.g. firstname@domain). Marked as 'guessed' in Signal Details. "
        "Some will bounce — that's the trade-off."
    ),
)

if include_blank:
    target_rows = pd.concat([in_linkedin, in_blank]).drop_duplicates()
else:
    target_rows = in_linkedin

if target_rows.empty:
    st.success("No backfill candidates. Every row is either already enriched or in a channel you opted out of.")
else:
    st.caption(f"Will run backfill on **{len(target_rows)}** rows.")

    aggressive_guess = st.checkbox(
        "Aggressive mode — derive a domain from the company name when DNS can't resolve one",
        value=True,
        help=(
            "For 'Slurrp Farm Pvt Ltd' with no website, derives 'slurrpfarm.com' "
            "and uses it. Bounces more, but guarantees every row gets *something*. "
            "Turn off if you only want emails that have a verified domain."
        ),
    )

    if st.button(f"Backfill emails for {len(target_rows)} rows", type="primary"):
        from core.enrich.finder import find_email
        from core.enrich.guesser import derive_domain_from_name, guess_email
        from core.sheets import batch_update_column
        from core.config import CHANNEL_AUTOMATION

        def _extract_domain_from_website(website: str) -> str:
            if not website:
                return ""
            d = website.strip().replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]
            return d.replace("www.", "")

        poc_email_updates: dict[int, str] = {}
        channel_updates: dict[int, str] = {}
        signal_detail_updates: dict[int, str] = {}

        dead_providers: set[str] = set()
        provider_deaths: dict[str, dict] = {}
        outcomes: list[dict] = []  # per-row decisions for the post-run audit table
        n_via_provider = 0
        n_via_guess = 0
        n_via_aggressive_guess = 0
        n_no_domain = 0
        n_no_email = 0

        progress = st.progress(0.0)
        log = st.empty()
        total = len(target_rows)

        for i, (df_idx, row) in enumerate(target_rows.iterrows(), 1):
            sheet_row = int(df_idx) + 2  # 1-based + header
            poc_name = str(row.get("POC Name", "")).strip()
            company = str(row.get("Name of Organisation", "")).strip()

            parts = poc_name.split(" ", 1)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""

            # Step 1: resolve domain via website → Brave → DNS
            domain = _extract_domain_from_website(str(row.get("Organisation Website", "")))
            domain_source = "website" if domain else ""
            if not domain:
                resolved, lookup_source = _lookup_domain(company)
                domain = resolved or ""
                if domain:
                    domain_source = lookup_source  # 'Brave' or 'DNS guess'

            # Step 2: aggressive fallback — derive a domain from the company name
            if not domain and aggressive_guess and company:
                derived = derive_domain_from_name(company)
                if derived:
                    domain = derived
                    domain_source = "derived from name (unverified)"

            if not domain:
                n_no_domain += 1
                outcomes.append({
                    "sheet_row": sheet_row, "poc": poc_name, "company": company,
                    "outcome": "skipped: no domain", "domain": "", "email": "",
                })
                log.caption(f"({i}/{total}) {poc_name} @ {company}: no domain — skipped")
                progress.progress(i / total)
                continue

            # Step 3: provider chain (skip dead ones)
            found_email = None
            found_source = ""
            try:
                result = find_email(
                    domain, first or None, last or None, skip_providers=dead_providers,
                )
                fe = result.get("fatal_error") if isinstance(result, dict) else None
                if fe:
                    prov = fe.get("provider")
                    if prov and prov not in dead_providers:
                        dead_providers.add(prov)
                        provider_deaths[prov] = fe
                if result.get("email"):
                    found_email = result["email"]
                    found_source = result.get("source", "provider")
                    n_via_provider += 1
            except Exception as e:
                log.caption(f"({i}/{total}) {poc_name}: chain crashed ({e})")

            # Step 4: pattern-guess fallback
            if not found_email and allow_guess and first:
                g = guess_email(first, last, domain, prefer_founder_format=True)
                if g.get("email"):
                    found_email = g["email"]
                    found_source = (
                        "guess (derived domain)" if domain_source.startswith("derived")
                        else "guess"
                    )
                    if domain_source.startswith("derived"):
                        n_via_aggressive_guess += 1
                    else:
                        n_via_guess += 1

            if found_email:
                # Compose signal note carrying provenance — gives the analyst
                # full transparency about how this email was found
                signal_note = f" | Backfilled: {found_email} via {found_source} (domain: {domain_source})"
                alts_note = ""
                if found_source.startswith("guess"):
                    g_alts = guess_email(first, last, domain, prefer_founder_format=True).get("alternates", [])
                    if g_alts:
                        alts_note = f" | Alternates if bounces: {' / '.join(g_alts[:3])}"
                poc_email_updates[sheet_row] = found_email
                channel_updates[sheet_row] = CHANNEL_AUTOMATION
                existing_signal = str(row.get("Signal Details", "")).strip()
                signal_detail_updates[sheet_row] = (existing_signal + signal_note + alts_note).strip()
                outcomes.append({
                    "sheet_row": sheet_row, "poc": poc_name, "company": company,
                    "outcome": found_source, "domain": domain, "email": found_email,
                })
                log.caption(f"({i}/{total}) {poc_name} @ {company} → {found_email} ({found_source})")
            else:
                n_no_email += 1
                outcomes.append({
                    "sheet_row": sheet_row, "poc": poc_name, "company": company,
                    "outcome": "no email found", "domain": domain, "email": "",
                })
                log.caption(f"({i}/{total}) {poc_name} @ {company}: domain={domain}, no email found")

            progress.progress(i / total)

        # Batch writes — 3 separate column updates, one API call each
        write_error = None
        if poc_email_updates:
            with st.spinner(f"Writing {len(poc_email_updates)} rows to Sheet..."):
                try:
                    batch_update_column(TAB_SIGNAL, "POC Email", poc_email_updates)
                    batch_update_column(TAB_SIGNAL, "Outreach Channel", channel_updates)
                    batch_update_column(TAB_SIGNAL, "Signal Details", signal_detail_updates)
                except Exception as e:
                    write_error = str(e)
                    st.error(f"Sheet write FAILED: {e}")

        # Provider death warnings
        if provider_deaths:
            for prov, info in provider_deaths.items():
                kind = info.get("kind", "")
                msg = info.get("message", "")
                if "Auth" in kind:
                    st.warning(f"**{prov.title()} key rejected during backfill.** {msg}")
                elif "Quota" in kind:
                    st.warning(f"**{prov.title()} credits exhausted during backfill.** {msg}")

        # Summary
        n_written = len(poc_email_updates) if not write_error else 0
        if n_written == 0:
            st.error(
                f"**0 rows written to the Sheet.** Here's why:\n\n"
                f"- {n_no_domain} rows had no resolvable domain "
                f"(turn on **Aggressive mode** above to force-guess one from the company name)\n"
                f"- {n_no_email} rows had a domain but no email could be found or guessed "
                f"(usually means the POC Name was empty)\n"
                f"- Providers found: {n_via_provider} · Pattern-guessed: {n_via_guess} · "
                f"Aggressive-guessed: {n_via_aggressive_guess}"
            )
        else:
            st.success(
                f"Backfill complete · **{n_written} rows** updated in the Sheet.\n\n"
                f"- **{n_via_provider}** found via API providers\n"
                f"- **{n_via_guess}** pattern-guessed with verified domain\n"
                f"- **{n_via_aggressive_guess}** pattern-guessed with name-derived domain (higher bounce risk)\n"
                f"- **{n_no_domain}** skipped (no domain possible)\n"
                f"- **{n_no_email}** skipped (had domain but no name to guess from)"
            )

        # Per-row audit table — always show so the user can see exactly what happened
        if outcomes:
            with st.expander(f"Per-row outcomes ({len(outcomes)})", expanded=(n_written == 0)):
                st.dataframe(pd.DataFrame(outcomes), width="stretch", hide_index=True)

        if n_via_aggressive_guess > 0:
            st.warning(
                f"{n_via_aggressive_guess} rows got an email built on a **name-derived domain** "
                f"(no website or DNS check confirmed the domain). Bounce risk is high. "
                f"Spot-check 5 random rows in the Sheet, send a small test batch, and watch "
                f"the bounce rate before scaling up."
            )
