# Dividend Analyzer — Next.js Frontend

## Phase 2: FastAPI Integration

### Prerequisites

1. **Python API** (from repo root dependencies + api extras):

```bash
pip install -r requirements.txt
pip install -r api/requirements.txt
```

2. **Node.js** for the frontend:

```bash
cd web
npm install
cp .env.local.example .env.local
```

### Run (two terminals)

**Terminal 1 — FastAPI**

```bash
cd api
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — Next.js**

```bash
cd web
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Dashboard calls `GET /api/v1/analyze/{ticker}` and falls back to mock data when API is offline.

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | FastAPI base URL |

### Data Layer

- `lib/api.ts` — fetch wrapper, 429/timeout handling, mock fallback
- `hooks/useDashboardQueries.ts` — TanStack Query hooks
- `types/index.ts` — synced with `api/app/schemas/scorecard.py`

## Project Structure

```
web/
├── app/(dashboard)/page.tsx
├── components/shared/     # ScoreCard, MetricCard, DashboardShell, …
├── hooks/useDashboardQueries.ts
├── lib/api.ts
├── lib/mockData.ts        # Fallback only
└── types/index.ts
```

## Phase 3 (Suggested)

- `/stock/[ticker]` full detail page wired to analyze + narrative APIs
- `/reversal-scan` page + `POST /api/v1/hunter/scan`
- OpenAPI → Zod codegen for schema sync
- Server-side proxy route (`app/api/...`) to hide API URL in production
