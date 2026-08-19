# OrderFlow app (React + FastAPI)

The customer-facing web app: a CRUD UI over the OrderFlow Lakebase database.

- `app.py` — FastAPI entry point; serves `/api/*` and the built React SPA.
- `server/db.py` — Lakebase connection pool with per-connection OAuth token minting.
- `server/routes/` — CRUD routes for products, orders (+ line items), customers, and stats.
- `frontend/` — Vite + React + TypeScript + Tailwind UI (Databricks-branded).
- `requirements.txt` — the file the Databricks Apps builder installs from (kept in
  sync with `pyproject.toml`, which is used for local `uv` development).

## Local dev

```bash
# Backend
export DATABRICKS_PROFILE=<profile>
export ENDPOINT_NAME="projects/orderflow/branches/production/endpoints/primary"
export LAKEBASE_HOST="<endpoint-host>"
export LAKEBASE_DATABASE="orderflow"
uv run uvicorn app:app --reload --port 8000

# Frontend (separate terminal) — proxies /api to :8000
cd frontend && npm run dev
```

## Build + deploy

The frontend must be built (`npm run build` → `frontend/dist`) before deploying; the
`databricks.yml` bundle uploads `dist` and the Apps runtime serves it. Deploy the whole
stack from the repo root with `databricks bundle deploy`.
