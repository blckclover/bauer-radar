# Dividend Analyzer — Next.js Frontend (Phase 1)

Modern frontend scaffold for migrating the Streamlit dividend-analyzer dashboard.

## Stack

- **Next.js 15** (App Router)
- **TypeScript**
- **Tailwind CSS**
- **shadcn/ui** (default style, slate base)
- **lucide-react**

## Getting Started

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Project Structure

```
web/
├── app/
│   ├── (dashboard)/          # Main dashboard (route: /)
│   ├── stock/[ticker]/       # Stock detail placeholder
│   ├── globals.css           # Dark fintech theme + Inter
│   └── layout.tsx
├── components/
│   ├── ui/                   # shadcn/ui primitives
│   ├── shared/               # ScoreCard, MetricCard, RedTeamAlert, …
│   ├── scorecard/            # Phase 2
│   └── reversal-scan/        # Phase 2
├── lib/
│   ├── mockData.ts           # Mock dashboard data
│   └── utils.ts
└── types/
    └── index.ts              # Core TypeScript types
```

## Phase 1 Scope

- Dashboard layout with collapsible methodology sidebar
- Value / Growth mode toggle with weight explanations
- Mock scorecards, metrics, Red Team alerts, watchlist table
- No backend integration yet

## Phase 2 (Suggested)

1. **FastAPI wrapper** around `analyzer_core.py` exposing REST endpoints
2. **Server Components** or **TanStack Query** for `/api/analyze/[ticker]`
3. **Zod schemas** mirroring `types/index.ts` for runtime validation
4. Stock detail page at `/stock/[ticker]` with charts (Recharts / Lightweight Charts)

The existing Streamlit app remains in the repo root (`app.py`).
