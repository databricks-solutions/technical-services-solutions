# Documentation screenshots

The PNGs in `docs/screenshots/` are captured from the built frontend, running against a mock backend with fictional
data. Regenerate them after a UI change; nothing here touches a real workspace.

| File | Shows |
|------|-------|
| `overview-first-run.png` | Overview before any snapshot (the three first steps) |
| `overview.png` | Overview with data: KPIs, trend charts, waves |
| `scans-new.png` | Start-scan form and scan history |
| `scan-readiness.png` | A scan's Readiness tab: status, blockers, warnings |
| `scan-code-fixes.png` | The Code fixes tab |
| `apply-planner.png` | Apply planner after a successful dry run |
| `apply-confirm.png` | The typed EXECUTE confirmation dialog |
| `cutover-traffic.png` | Verify & cut over: legacy traffic and usage tracking |
| `cutover-pause-test.png` | Pausing a legacy endpoint and a test call |
| `cutover-usage-enforce.png` | Unity Gateway traffic table and the Enforce checklist |

## Files

- `mock_server.py`: standard-library server. Serves `app/frontend/static` and answers every `/api/*` route the
  frontend calls, with the response shapes of `app/backend/main.py`. Runs live in memory. `POST /__mock/reset`
  restores the seeded state (`{"state": "full"}` or `{"state": "empty"}`). Auth, Databricks calls and CSV/Markdown
  exports are not modelled (exports answer 501).
- `capture.mjs`: drives headless Chrome (puppeteer-core) through each image. Every image starts from a fresh seeded
  state, so one image's clicks don't change the next.
- `optimize.py`: shrinks the PNGs in place (pngquant when installed, otherwise a 256-colour Pillow palette).

## Regenerate

1. Build the frontend (writes `app/frontend/static`, which is tracked in git):

   ```sh
   cd app/frontend && npm install --silent && npm run build
   ```

   If you don't want the rebuilt bundle in your change, run `git checkout app/frontend/static` afterwards.

2. One-time setup of the browser driver, outside the repo:

   ```sh
   mkdir -p /tmp/shots && cd /tmp/shots && npm init -y && npm i puppeteer-core
   ```

3. Capture (from the repo root). It starts the mock on port 8765 and stops it at the end:

   ```sh
   node tools/screenshots/capture.mjs
   ```

   Options (environment variables): `ONLY=scan-readiness,apply-confirm` captures a subset; `MOCK_URL=http://127.0.0.1:8765`
   uses a mock you already started; `MOCK_PORT`, `OUT_DIR`, `SHOTS_DIR` and `CHROME_PATH` override the defaults. Chrome
   defaults to `/Applications/Google Chrome.app` (macOS).

4. Shrink the PNGs (Pillow is fetched by uv, nothing to install):

   ```sh
   uv run --with pillow python tools/screenshots/optimize.py docs/screenshots/*.png
   ```

Every image is 1280 px wide at 1x, light theme, and cropped to its content (the header is included where the image
shows the tab bar). The size target is under 250 KB per file; the current set is 30 to 83 KB.

To look at the mock by hand instead, run `python3 tools/screenshots/mock_server.py --port 8765` and open
`http://127.0.0.1:8765`. Add `--empty` to start with no snapshot, scans or runs.

## Fictional data

Nothing is taken from a real customer, employee or workspace.

- Workspace: `https://adb-1234567890123456.7.azuredatabricks.net` (ID `1234567890123456`), named `lakeside-core-prod`.
  Five more snapshot-only workspaces (`retail-analytics-prod`, `claims-ml-dev`, `support-bot-prod`,
  `finance-reporting`, `sandbox-team-a`) and one stopped workspace (`marketing-lab`).
- Signed-in operator: `maria.lopez@example.com`. Other people: `analyst@example.com`. Service principal:
  `0f6d1c2a-1111-2222-3333-444455556666`.
- Results schema `main.ug_migration`; secret schema `main.ug_secrets`; target `ai_gateway.migrated`.
- Endpoints: `chat-gpt4o-proxy` and `support-bot-openai` (external model, OpenAI), `claims-summary-pt` (Provisioned
  Throughput), `legacy-summarizer-openai` (external model, quiet, its service already exists), `ticket-router-v2` (v2
  workspace-bound), `faq-bot-openai`, `docs-embed-v1`, `claims-classify-v2`, `fraud-scorer-custom` (custom model),
  and the Databricks pay-per-token endpoints `databricks-meta-llama-3-3-70b-instruct`, `databricks-gpt-5-mini` and
  `databricks-bge-large-en`.
- Snapshot: four weekly points ending two hours before the server started. Scan: one BLOCKED scan (three blockers,
  three warnings, one close candidate) and one READY_WITH_WARNINGS scan, both on the workspace above. Deadline
  2027-03-30, as of 2026-11-01.
- Timestamps are relative to the server's start time, so ages such as "2 days ago" stay true when you regenerate.
