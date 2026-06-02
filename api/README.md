# Dividend Analyzer API

FastAPI wrapper around repo-root `analyzer_core.py`.

## Run locally

```powershell
cd api
pip install -r requirements.txt
pip install -r ../requirements.txt
pip install -e .                    # recommended on Windows (fixes reload import)
copy .env.example .env

# Option A — hot reload (Windows-safe)
python run.py

# Option B — no reload
python -m uvicorn app.main:app --port 8000
```

**Windows `--reload` error?** If you see `Could not import module "app.main"`, use `python run.py` or `pip install -e .` first.
Streamlit warnings on startup are normal (analyzer_core uses `@st.cache_data`).

## Endpoints

- `GET /health`
- `GET /api/v1/analyze/{ticker}?mode=value|growth`
- `GET /api/v1/narrative/{ticker}?mode=`
- `POST /api/v1/hunter/scan` → `{ taskId }`
- `GET /api/v1/hunter/status/{task_id}`
- `DELETE /api/v1/hunter/status/{task_id}`

See root [README.md](../README.md) for deployment (Railway + Vercel).

## Tests

```powershell
pytest api/tests -q
```
