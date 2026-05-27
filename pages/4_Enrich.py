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

if not secret("apis", "hunter_api_key"):
    st.error("Hunter API key missing. Add `apis.hunter_api_key` to secrets.toml.")
    st.stop()

# Quota panel (free, doesn't consume credits)
with st.expander("Provider quota", expanded=False):
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

    if secret("apis", "snov_user_id") and secret("apis", "snov_secret"):
        try:
            from core.enrich import snov

            bal = snov.balance()
            st.write({"Snov balance": bal.get("balance"), "Snov daily limit": bal.get("limit")})
        except Exception as e:
            st.warning(f"Snov quota fetch failed: {e}")
    else:
        st.caption("Snov not configured — add `apis.snov_user_id` and `apis.snov_secret` to double the monthly capacity.")

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
