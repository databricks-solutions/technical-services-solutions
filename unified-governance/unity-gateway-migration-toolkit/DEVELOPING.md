# Developing the toolkit (source repo only)

This file, the tests and `test_fixtures.py` stay in the source repo; they aren't shipped to customers.

## Build the deliverables

```bash
cd app/frontend && npm install && cd ../..   # once (or after package.json changes)
./package.sh
cp dist/INSTALL_unity_gateway_migration_toolkit_*.py .    # commit the regenerated installer in this folder
```

`package.sh` rebuilds the frontend (`app/frontend/static`), runs `make_installer.py` (writes `dist/INSTALL_unity_gateway_migration_toolkit_<version>.py`, the installer notebook that embeds the runtime files) and writes `dist/unity-gateway-migration-toolkit-<version>.zip`, the one file customers download: the installer at the top, plus the toolkit files for command-line and bundle users. Commit the regenerated installer in this folder whenever the code changes, so the repo release zip carries it too. Bump `__version__` in `ug_migration_planner.py` and `version` in `app/frontend/package.json` together.

Then check the bundle from the zip:

```bash
cd /tmp && unzip -o ~/path/to/dist/unity-gateway-migration-toolkit-<version>.zip && cd unity-gateway-migration-toolkit-<version>
databricks bundle validate -t dev --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
databricks bundle validate -t prod --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
```

## Tests

```bash
python -m pytest -q          # offline: test_planner, test_apply, test_account, test_edge_cases, test_store
cd app/frontend && npx tsc --noEmit
```

- `test_planner.py`: classification, rate-limit translation, provider dedup, routing and fallback, inference tables, grants, the scanner, readiness and dependency linking.
- `test_apply.py`: payload builders, fallback mapping, secrets, masking and the Terraform export.
- `test_account.py`: classification, waves, collisions and profile matching for the account view.
- `test_edge_cases.py`: reviewer-found edge cases across all modules.
- `test_store.py`: the app's Delta store helpers, rollback protection, credential scrubbing and rate-limit caps.

`UGMIG_TEST_CATALOG=<catalog> UGMIG_TEST_GROUP=<group> python test_fixtures.py --profile <p> setup|teardown` (the catalog and group must exist) creates and removes throwaway `ugmig_test_` objects for a live check: two external-model endpoints (fake keys, never queried) with rate limits, guardrails, inference table, fallback, tags and a `CAN_QUERY` grant; a notebook with legacy calls and fake literal credentials (to check that scans hide them); a saved SQL query with legacy calls; and, unless `UGMIG_SKIP_EXTRA=1`, an AI Search (formerly Vector Search) endpoint and index on `databricks-gte-large-en`, an app with a serving-endpoint resource and a job whose parameters name legacy endpoints. **The AI Search endpoint is billed while it exists, so run teardown right after.**
