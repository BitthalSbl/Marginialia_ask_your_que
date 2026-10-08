# Marginalia: PDF Q&A that runs free, with no Docker and no API key

Upload PDFs, pick which ones to search, and ask questions. Every answer cites the page it came from.

| Mode | When | Search | Answers |
|---|---|---|---|
| **Offline** (default) | no key set | BM25 keyword search | lines quoted from your PDFs, with `[n]` page citations |
| **AI** | `GEMINI_API_KEY` (free) or `OPENAI_API_KEY` set | keyword + semantic (hybrid) | written by the model, streamed |

If the AI provider fails (bad key, quota, outage), the app silently falls back to offline mode instead of erroring.

## Structure

```
backend/            FastAPI app (pure-Python deps, installs in seconds)
  app/              main.py, providers.py, vectorstore.py (BM25 + cosine), local_llm.py, ...
  static/           pre-built React app, served by FastAPI (committed on purpose)
  tests/            no network or keys needed
frontend/           React + Vite source
render.yaml         one free Render web service
```

## Deploy on Render (free)

1. Push this folder to GitHub (the `static/` folder must be included):
   ```bash
   git init && git add . && git commit -m "Marginalia"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
2. Render dashboard → **New → Blueprint** → pick the repo → **Apply**. No values to fill in.
3. Wait for the build (about 2 minutes). Open the `https://marginalia-xxxx.onrender.com` URL. Done.

Without Blueprints: **New → Web Service**, Runtime *Python*, Root Directory `backend`,
Build `pip install -r requirements.txt`,
Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`,
Health Check Path `/api/health`, plan Free. Add env var `PYTHON_VERSION=3.11.9`.

Every later `git push` redeploys automatically.

### Optional: AI answers
Render → your service → **Environment** → add `GEMINI_API_KEY` (free at https://aistudio.google.com/apikey). It restarts and switches to AI mode by itself. Documents uploaded earlier keep working with keyword search.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000        # open http://localhost:8000
pytest -q                               # after: pip install -r requirements-dev.txt
```

Changing the UI: `cd frontend && npm ci && npm run dev` (hot reload on :5173), then `npm run build` and commit the updated `backend/static/`.

## Free-tier limits

- **Sleeps after ~15 min idle**; the first request then takes up to a minute (the UI says so). A free pinger such as UptimeRobot hitting `/api/health` every 10 minutes keeps it awake.
- **Documents reset on restart/redeploy.** Free Render has no persistent disk, so uploads live only until the instance restarts.
- **512 MB RAM**, plenty for this app. `MAX_UPLOAD_MB` (15) and `MAX_CHUNKS_PER_DOC` (800) cap upload size.
- **Scanned PDFs** have no text layer and are rejected with a clear message.
- Offline mode quotes your documents; it does not paraphrase or reason across passages. Use AI mode for that.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness + active mode |
| GET | `/api/documents` | list documents |
| POST | `/api/documents` | multipart `file`; dedupes by content hash |
| DELETE | `/api/documents/{id}` | remove |
| POST | `/api/chat` | `{question, doc_ids[], history[]}` → SSE: `sources`, `token`…, `done` / `error` |
