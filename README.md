# 180DC NITW — Client Outreach Pipeline

Streamlit app for the summer cycle. Sector-segmented prospecting, enrichment, LinkedIn/email draft generation, and live tracker sync into a shared Google Sheet.

## Run locally

```powershell
cd C:\Users\NilayTamdu\Downloads\co-pipeline
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501.

## First-time setup (one-time, ~10 min)

1. **Gemini API key** — already in `.streamlit/secrets.toml`. Regenerate at https://aistudio.google.com/app/apikey before deploy, and paste the new key into Streamlit Cloud secrets only.
2. **Google Sheet** — create a Sheet with 4 tabs named exactly:
   - `Client Outreach Tracker`
   - `Signal Based Outreach`
   - `Organization Based Outreach`
   - `Personal Outreach`
   The app will auto-write header rows on first run.
3. **Google Cloud service account** for Sheets API:
   - https://console.cloud.google.com → new project → enable Google Sheets API + Google Drive API
   - IAM → Service Accounts → create → keys → JSON → download
   - Open the downloaded JSON, copy each field into `[google_service_account]` in `secrets.toml`
   - Share the Sheet with the service account's `client_email` (Editor access)
   - Paste the Sheet ID (from its URL) into `[sheets].spreadsheet_id`
4. **Prospecting APIs** (free tiers, do as you build out):
   - Hunter.io — https://hunter.io/users/sign_up (25 searches/mo free)
   - Snov.io — https://app.snov.io/register
   - Apollo — https://www.apollo.io/sign-up

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (private is fine).
2. https://streamlit.io/cloud → New app → point at the repo, branch `main`, main file `app.py`.
3. Settings → Secrets → paste the contents of your `secrets.toml`.
4. Share the public URL with the team.

## Mac / cross-device

Once deployed, the Mac (or anyone) just opens the Streamlit URL. No install. For editing code from Mac: clone the GitHub repo, edit in VS Code, push — Streamlit Cloud auto-redeploys.

## Project layout

```
app.py                 # home page
pages/                 # one file per sidebar page
core/
  config.py            # sectors, schemas, secrets helpers
  sheets.py            # gspread wrapper (Task #9)
  sources/             # per-source company finders (Task #8)
  enrich/              # per-source email finders (Task #2)
  llm/gemini.py        # Gemini wrapper for drafts
prompts/               # markdown prompt templates
.streamlit/
  secrets.toml         # local keys (gitignored)
  secrets.toml.example # template for new clones
```

## Schema reference

All 4 tabs of the tracker, with the team's existing column names preserved. See `core/config.py` for the exact schemas.
