# Developing the toolkit (source repo only)

This file, the tests and `test_fixtures.py` stay in the source repo; they aren't shipped to customers.

## Build the deliverables

```bash
cd app/frontend && npm install && cd ../..   # once (or after package.json changes)
./package.sh
cp dist/INSTALL_unity_gateway_migration_toolkit_*.py .    # commit the regenerated installer in this folder
python3 check_release.py                                   # must pass before a release
```

`package.sh` rebuilds the frontend (`app/frontend/static`), runs `make_installer.py` (writes `dist/INSTALL_unity_gateway_migration_toolkit_<version>.py`, the installer notebook that embeds the runtime files) and writes `dist/unity-gateway-migration-toolkit-<version>.zip`, the one file customers download: the installer at the top, plus the toolkit files for command-line and bundle users (README, HOW_TO_READ, USER_GUIDE, the three CLI modules, the store, the notebooks, the app and `databricks.yml`).

The installer build is deterministic (fixed zip timestamps and permissions), so build with the same Python in CI and locally (3.12).

`check_release.py` (standard library only) rebuilds the installer in a temp folder, byte-compares it with the root `INSTALL_unity_gateway_migration_toolkit_<version>.py`, and checks that the versions agree. Exit 1 on any mismatch.

### Version bump

Change the version in all three places together, then run `check_release.py`:

- `__version__` in `ug_migration_planner.py`
- `version` in `app/frontend/package.json`
- `toolkit_version` in `databricks.yml` (default `"0.9.0"`)

Then commit the regenerated root installer. Customer file names carry the version, for example `unity-gateway-migration-toolkit-0.9.0.zip` and `INSTALL_unity_gateway_migration_toolkit_0_9_0.py`.

Check the bundle from the zip:

```bash
cd /tmp && unzip -o ~/path/to/dist/unity-gateway-migration-toolkit-<version>.zip && cd unity-gateway-migration-toolkit-<version>
databricks bundle validate -t dev --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
databricks bundle validate -t prod --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
```

## Run the app locally

```bash
cd app
UGMIG_LOCAL_DEV=1 uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

`UGMIG_LOCAL_DEV=1` runs requests as the CLI profile's user with no operator check. It is ignored when `DATABRICKS_APP_NAME` is set (inside a Databricks App), and every request fails closed (401) without it. Bind to `127.0.0.1` only. For frontend work, `cd app/frontend && npm run dev` proxies `/api` to that server.

## Tests

```bash
python -m pytest -q          # offline
cd app/frontend && npx tsc --noEmit
```

- `test_planner.py`: classification, rate-limit translation, provider dedup, routing and fallback, inference tables, grants, the scanner, readiness and dependency linking.
- `test_apply.py`: payload builders, fallback mapping, secrets, masking and the Terraform export.
- `test_account.py`: classification, waves, collisions and profile matching for the account view.
- `test_edge_cases.py`: reviewer-found edge cases across all modules.
- `test_store.py`: the app's Delta store helpers, rollback protection, credential scrubbing and rate-limit caps.
- `test_installer.py`: runs the helper block between `# HELPERS-BEGIN` and `# HELPERS-END` in `installer/install_template.py`. Keep that block free of `dbutils`, `spark` and `w`.
- `test_app.py`: the FastAPI app with the Databricks clients mocked (identity and operator rules, CSRF, the fail-closed run check, job message visibility, the secret allowlist, dry-run matching, stale scans, guardrail acknowledgement, export truncation).

The notebooks (`notebook/*.py`) and the installer run only on Databricks; they are checked by reading and by the offline harness, not by pytest.

`UGMIG_TEST_CATALOG=<catalog> UGMIG_TEST_GROUP=<group> python test_fixtures.py --profile <p> setup|teardown` (the catalog and group must exist) creates and removes throwaway `ugmig_test_` objects for a live check: two external-model endpoints (fake keys, never queried) with rate limits, guardrails, inference table, fallback, tags and a `CAN_QUERY` grant; a notebook with legacy calls and fake literal credentials (to check that scans hide them); a saved SQL query with legacy calls; and, unless `UGMIG_SKIP_EXTRA=1`, an AI Search (formerly Vector Search) endpoint and index on `databricks-gte-large-en`, an app with a serving-endpoint resource and a job whose parameters name legacy endpoints. **The AI Search endpoint is billed while it exists, so run teardown right after.**
