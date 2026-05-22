import streamlit as st

from core.config import (
    OWNERS,
    SECTORS,
    TAB_MASTER,
    TAB_SIGNAL,
    TAB_ORG,
    TAB_PERSONAL,
    SIGNAL_SCHEMA,
    PERSONAL_SCHEMA,
    MASTER_SCHEMA,
    gemini_key,
    sheet_id,
    secret,
)
from core.ui import apply_branding

apply_branding()

st.title("Settings")
st.caption("API keys, sector default, connection tests")

st.subheader("Current configuration")
st.write(
    {
        "Gemini configured": bool(gemini_key()),
        "Sheet ID configured": bool(sheet_id()),
        "Service account configured": bool(secret("google_service_account", "client_email")),
        "Hunter configured": bool(secret("apis", "hunter_api_key")),
        "Brave configured": bool(secret("apis", "brave_api_key")),
        "Snov configured": bool(secret("apis", "snov_user_id")) and bool(secret("apis", "snov_secret")),
        "Skrapp configured": bool(secret("apis", "skrapp_api_key")),
        "Apollo configured": bool(secret("apis", "apollo_api_key")),
    }
)

st.divider()

st.subheader("Sheets connection test")
if st.button("Test connection + ensure tab headers"):
    try:
        from core.sheets import sheet_status, ensure_headers

        status = sheet_status()
        if not status["ok"]:
            st.error(f"Connection failed: {status['error']}")
        else:
            st.success(f"Connected to **{status['sheet_title']}**. Tabs: {', '.join(status['tabs'])}")
            with st.spinner("Ensuring headers for the 4 tabs..."):
                for tab, schema in [
                    (TAB_MASTER, MASTER_SCHEMA),
                    (TAB_SIGNAL, SIGNAL_SCHEMA),
                    (TAB_ORG, []),  # we don't manage this tab's schema in v1
                    (TAB_PERSONAL, PERSONAL_SCHEMA),
                ]:
                    if schema:
                        try:
                            headers = ensure_headers(tab, schema)
                            st.write(f"`{tab}` → {len(headers)} columns")
                        except Exception as e:
                            st.warning(f"`{tab}` skipped: {e}")
    except Exception as e:
        st.error(f"Setup error: {e}")

st.divider()

st.subheader("Your sector default")
st.caption("Pick once per session. Other pages use this as the pre-selected sector and the 180DC POC routing.")

# Default to whatever's already in session, else SaaS at index 0.
current = st.session_state.get("default_sector", SECTORS[0])
sector = st.selectbox(
    "Sector",
    SECTORS,
    index=SECTORS.index(current) if current in SECTORS else 0,
)
st.session_state["default_sector"] = sector

analyst = OWNERS.get(sector, "unassigned")
st.markdown(f"**180DC POC for this sector:** :green[{analyst}]")
st.caption(
    "If this name doesn't match you, change the sector above. "
    "Each analyst's allocated sectors are mapped in `core/config.py` (ANALYST_SECTORS)."
)

st.divider()

st.markdown(
    "**Persistent keys:** edit `.streamlit/secrets.toml` locally, or paste them into the "
    "Streamlit Cloud secrets manager on deploy. The field below is a session-only override."
)
with st.expander("Session override (BYOK)"):
    g = st.text_input("Gemini API key", type="password")
    if g:
        st.session_state["gemini_override"] = g
        st.success("Gemini override active for this session.")
