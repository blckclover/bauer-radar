# Dividend Analyzer · 投資分析系統

Next.js 15 + FastAPI 架構，Python 核心邏輯保留於 `analyzer_core.py`。

| 介面 | 路徑 | 說明 |
|------|------|------|
| **Next.js（主要）** | `web/` | Dashboard、個股分析、逆向轉機雷達 |
| **FastAPI** | `api/` | REST API 包裝 `analyzer_core.py` |
| **Streamlit（即將退役）** | `app.py` | 舊版儀表板，保留作後備 |

---

## 本地啟動

### 1. Python 依賴（根目錄 + API）

```powershell
cd C:\Users\bauer\Projects\dividend-analyzer
pip install -r requirements.txt
pip install -r api/requirements.txt
```

### 2. 環境變數

```powershell
# API
copy api\.env.example api\.env
# 編輯 GEMINI_API_KEY、CORS_ORIGINS

# Web
copy web\.env.example web\.env.local
# 預設 NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. 啟動 FastAPI（Terminal 1）

```powershell
cd api
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 健康檢查：http://localhost:8000/health  
- OpenAPI：http://localhost:8000/docs  

### 4. 啟動 Next.js（Terminal 2）

```powershell
cd web
npm install
npm run dev
```

- Dashboard：http://localhost:3000  
- 轉機雷達：http://localhost:3000/reversal-scan  
- 個股分析：http://localhost:3000/stock/AAPL?mode=value  

---

## 環境變數說明

### Web (`web/.env.local`)

| 變數 | 說明 | 預設 |
|------|------|------|
| `NEXT_PUBLIC_API_URL` | FastAPI 公開 URL | `http://localhost:8000` |
| `NEXT_PUBLIC_APP_ENV` | `development` / `production` | `development` |
| `NEXT_PUBLIC_USE_API_PROXY` | 使用 Next.js rewrite 代理 | `false` |
| `NEXT_PUBLIC_ENABLE_MOCK_FALLBACK` | API 離線時使用 Mock | `false`（本地可設 `true`） |
| `API_INTERNAL_URL` | SSR 專用內網 URL（Vercel→Railway） | — |
| `API_PROXY_TARGET` | Rewrite 目標（server-only） | — |

### API (`api/.env`)

| 變數 | 說明 |
|------|------|
| `GEMINI_API_KEY` | Gemini LLM（敘事、Red Team） |
| `CORS_ORIGINS` | 允許來源，含 Vercel 網域 |
| `ENABLE_ANALYZE_CACHE` | 分析結果 in-memory 快取 |
| `CACHE_TTL_SECONDS` | 快取 TTL（秒） |
| `APP_ENV` | 執行環境 |

---

## 部署指南

### Railway（FastAPI）

1. 建立 Railway 專案，連接 GitHub repo。
2. **Root Directory**：留空（使用根目錄 `Dockerfile`）。
3. 設定環境變數：
   - `GEMINI_API_KEY`
   - `CORS_ORIGINS=https://your-app.vercel.app,https://*.vercel.app`
   - `APP_ENV=production`
4. Deploy 後取得公開 URL，例如 `https://dividend-api.up.railway.app`。
5. 健康檢查路徑：`/health`

**Docker 本地測試：**

```powershell
docker build -t dividend-analyzer-api .
docker run -p 8000:8000 -e GEMINI_API_KEY=xxx dividend-analyzer-api
```

### Vercel（Next.js）

1. Import repo，**Root Directory** 設為 `web`。
2. Framework Preset：Next.js。
3. 環境變數：
   - `NEXT_PUBLIC_API_URL=https://dividend-api.up.railway.app`
   - `NEXT_PUBLIC_APP_ENV=production`
   - `NEXT_PUBLIC_ENABLE_MOCK_FALLBACK=false`
4. （可選）若需同源代理：
   - `NEXT_PUBLIC_USE_API_PROXY=true`
   - `API_PROXY_TARGET=https://dividend-api.up.railway.app`
5. Deploy。

### CORS 設定

Railway API 的 `CORS_ORIGINS` 必須包含 Vercel 網域。已支援 `https://*.vercel.app` 萬用字元（透過 `allow_origin_regex`）。

---

## API Endpoints

| Method | Path | 說明 |
|--------|------|------|
| `GET` | `/health` | 健康檢查 |
| `GET` | `/api/v1/analyze/{ticker}?mode=value\|growth` | 個股分析 |
| `GET` | `/api/v1/narrative/{ticker}?mode=` | 公司敘事 |
| `POST` | `/api/v1/hunter/scan` | 啟動轉機掃描（回傳 `taskId`） |
| `GET` | `/api/v1/hunter/status/{task_id}` | 查詢掃描進度 |
| `DELETE` | `/api/v1/hunter/status/{task_id}` | 取消掃描 |

---

## 專案結構（Phase 5）

```
dividend-analyzer/
├── analyzer_core.py      # Python 評分核心
├── app.py                # Streamlit（即將退役）
├── Dockerfile            # FastAPI 容器
├── .github/workflows/ci.yml
├── api/
│   ├── app/
│   │   ├── main.py       # CORS、路由
│   │   ├── config.py     # 環境設定
│   │   ├── routers/      # analyze, narrative, hunter
│   │   └── services/     # analyzer, hunter, hunter_tasks, cache
│   └── tests/
└── web/
    ├── app/              # Next.js App Router
    ├── components/       # UI 元件
    └── lib/
        ├── api.ts        # safeFetch 統一錯誤處理
        └── config.ts     # 環境與 proxy
```

---

## CI

Push / PR 至 `main` 時自動執行：

- **web**：`tsc --noEmit`、`eslint`
- **api**：`pytest api/tests`

本地執行：

```powershell
cd web && npx tsc --noEmit && npm run lint
pytest api/tests -q
```

---

## Streamlit 後備

```powershell
streamlit run app.py
```

啟動時會顯示退役警告，建議使用 http://localhost:3000 新介面。

---

## 正式上線前檢查清單

- [ ] `GEMINI_API_KEY` 已在 Railway 設定且有效
- [ ] Railway `/health` 回傳 `{"status":"ok"}`
- [ ] Vercel `NEXT_PUBLIC_API_URL` 指向 Railway 公開 URL
- [ ] CORS 包含 production Vercel 網域
- [ ] `NEXT_PUBLIC_ENABLE_MOCK_FALLBACK=false`（production）
- [ ] Dashboard 可載入 Live API（非 Mock）
- [ ] `/stock/AAPL` Narrative + FCF 圖表正常
- [ ] `/reversal-scan` Dow 30 掃描可完成並顯示結果
- [ ] Hunter polling 進度條與取消按鈕正常
- [ ] 429 錯誤不污染快取（narrative 空白 fallback）
- [ ] CI workflow 綠燈
