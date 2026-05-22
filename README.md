# Job App Tool

A Flask web app for tailoring resumes and generating cover letters with AI, plus an Android WebView client that wraps the same UI.

## One-click deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Jaywifh72/job-app-tool)

Click the button, sign in with GitHub, paste your `OPENAI_API_KEY` when prompted, and Render hands you a public URL (`https://job-app-tool-xxxx.onrender.com`). Free tier; cold starts after 15 min idle.

## Components

- **Flask backend** (`app.py`, `ai_handler.py`, `resume_handler.py`, `scraper.py`) — scrapes job postings, tailors resumes, generates cover letters, exports DOCX/PDF.
- **Android client** (`android/`) — WebView wrapper that connects to the Flask backend. APK is built by GitHub Actions (`.github/workflows/build-apk.yml`).

## Quick start (local)

```bash
pip install -r requirements.txt
playwright install chromium
export OPENAI_API_KEY=sk-...
python app.py
```

Then open http://127.0.0.1:5000.

> Note: `pywin32` in `requirements.txt` is Windows-only (used for DOCX→PDF via Word COM). Skip it on Linux/macOS; PDF export will fall back accordingly.

## Using it remotely

Easiest: use the **Deploy to Render** button above. Render reads `render.yaml`, builds with `pip install -r requirements.txt`, and serves via `gunicorn`.

Other options:

- **Tunnel (no deploy):** run `python app.py` locally, then `cloudflared tunnel --url http://localhost:5000` and use the URL it prints. Only works while your machine is on.
- **Railway / Fly.io:** same idea as Render — point at this repo, set `OPENAI_API_KEY`, use `gunicorn -b 0.0.0.0:$PORT app:app` as the start command.
- **VPS:** `gunicorn -w 2 -b 0.0.0.0:5000 app:app` behind nginx + TLS.

After the backend is up, update the WebView URL in `android/` to point at it and install the APK produced by the `build-apk` workflow.

## Building the Android APK

Push to the branch and GitHub Actions runs `.github/workflows/build-apk.yml`, producing a signed APK as a workflow artifact.

## Environment

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required. Used by `ai_handler.py`. |
| `FLASK_ENV` | Optional. Set to `production` when deployed. |

## Project layout

```
app.py              # Flask entrypoint
ai_handler.py       # OpenAI calls
resume_handler.py   # DOCX read/write
scraper.py          # Job posting scraper (requests + playwright fallback)
pdf_utils.py        # DOCX→PDF (Windows / Word COM)
diff_utils.py       # Resume diff rendering
templates/, static/ # Flask views
android/            # WebView Android client
generated/          # Output artifacts (gitignored content)
```
