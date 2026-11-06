# Developing the toolkit (source repo only)

This file, the tests and `test_fixtures.py` stay in the source repo. They aren't shipped to customers.

## Build the deliverables

```bash
cd app/frontend && npm install && cd ../..   # once, or after package.json changes
./package.sh                                  # frontend build, installer, zip
cp dist/INSTALL_unity_gateway_migration_toolkit_*.py .   # commit the regenerated installer at the root
python3 check_release.py                      # must pass before a release
```

- `package.sh` runs `npm run build` (so `app/frontend/static` is never stale), then `make_installer.py`, which writes `dist/INSTALL_unity_gateway_migration_toolkit_<version>.py` by embedding the runtime files into `installer/install_template.py`, and then writes `dist/unity-gateway-migration-toolkit-<version>.zip`.
- The zip has one top folder, `unity-gateway-migration-toolkit-<version>/`. It holds the installer, the README, HOW_TO_READ and USER_GUIDE, the three CLI modules and the store, the four notebooks in `notebook/`, `app/` (backend `main.py` and `__init__.py` plus copies of `ug_migration_store.py`, `ug_migration_apply.py` and `ug_migration_planner.py`, the frontend sources and build, `requirements.txt`) and `databricks.yml` without the repo-only sync excludes. This file isn't shipped.
- The installer build is deterministic (fixed zip timestamps and permissions). Build with the same Python in CI and locally (3.12).

`check_release.py` (standard library only) rebuilds the installer in a temp folder and byte-compares it with the committed root `INSTALL_unity_gateway_migration_toolkit_<version>.py`. It also checks that the versions agree. Exit 1 on any problem. Until the root installer is rebuilt and committed, it fails.

### Version bump

Change the version in every place below, then run `check_release.py`:

- `__version__` in `ug_migration_planner.py`. The installer's `__VERSION__` placeholder, the app's reported version and every report's header come from it.
- `version` in `app/frontend/package.json`.
- `version` in `app/frontend/package-lock.json`, in two places: the top level and `packages[""]`. `check_release.py` doesn't check the lock file, so check it by hand (or let `npm version --no-git-tag-version` update both).
- `toolkit_version` in `databricks.yml` (its `default`).

Then commit the regenerated root installer. Customer file names carry the version, for example `unity-gateway-migration-toolkit-0.10.2.zip` and `INSTALL_unity_gateway_migration_toolkit_0_10_2.py`. `check_release.py` fails if any guide still names an installer file of another version.

Check the bundle from the zip:

```bash
cd /tmp && unzip -o ~/path/to/dist/unity-gateway-migration-toolkit-<version>.zip && cd unity-gateway-migration-toolkit-<version>
databricks bundle validate -t dev --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s>
databricks bundle validate -t prod --var warehouse_id=<id> --var snapshot_catalog=<c> --var snapshot_schema=<s> --var operators=<emails>
```

## The legacy deadline

The retirement date is one value, and the customer-facing text must agree with it. The date is confirmed as of 2026-11-01. When it moves, change it in each place that writes it:

- `LEGACY_DEADLINE` default in `ug_migration_planner.py` and `ug_migration_account.py` (both read `UGMIG_DEADLINE` first), and `DEADLINE_AS_OF` in both.
- `LEGACY_DEADLINE` default in `app/backend/main.py` (reads `UGMIG_DEADLINE`).
- `DEFAULT_DEADLINE` and the `deadline` widget default in `installer/install_template.py`.
- The `deadline` variable default in `databricks.yml`.
- The `deadline` widget help text in `notebook/run_planner.py`, `notebook/run_account.py` and `notebook/run_scan.py`.
- The date in the Start here section of USER_GUIDE.md, the deadline line in README.md and the deadline in HOW_TO_READ.md (the customer docs state it in these places).

`test_app.py` (`test_app_and_account_agree_on_the_deadline_and_old_wave_names`), `test_installer.py` (the default and `valid_deadline`) and `test_planner.py` / `test_account.py` assert the values. Update them with the date.

The override paths stay the same: the installer widget, the bundle variable, `--deadline` on the planner and account CLIs, the `deadline` notebook widget, and `UGMIG_DEADLINE`. A bad date must fail before any call is made.

## How the app gets the job-side rules

The app imports `ug_migration_store.py`, `ug_migration_apply.py` and `ug_migration_planner.py`, so the fingerprints, the rollback rule, run status, the v2 failing rule, cut-over options and the dry-run and pause gates exist once. `main.py` looks for the modules next to itself (`app/backend`), then in the repository root:

- **Installer:** `make_installer.py` (`APP_MODULES`) embeds the three modules again under `app/backend/`, byte for byte, because the installer deploys `<install folder>/app`.
- **Release zip:** `package.sh` copies them into `app/backend/`.
- **Bundle:** the app's `source_code_path` is the bundle root and its command is `uvicorn app.backend.main:app`, so it finds them in the root. The root `requirements.txt` only includes `app/requirements.txt`.

Don't commit copies of the modules under `app/backend`. `test_installer.py` (`test_the_deployed_app_gets_the_modules_it_imports`) checks all three paths.

Two sets of rules are still written twice:

- The deadline and the wave names: `ug_migration_account.py` and `main.py` (`LEGACY_DEADLINE`, `DEADLINE_AS_OF`, `_validate_deadline`, `LEGACY_WAVE_NAMES`). The account module isn't shipped with the app. `test_app_and_account_agree_on_the_deadline_and_old_wave_names` checks them.
- The caller rules (`caller_class` and its token lists) in `ug_migration_planner.py` and `ug_migration_account.py`. Each copy has its own test (`test_planner.py`, `test_account.py`), but no test compares the two, so change both together. Keep the labels in `app/frontend/src/api.ts` (`CALLER_LABEL`) and the caller types in USER_GUIDE and HOW_TO_READ in step too.

## Run the app locally

```bash
cd app
UGMIG_LOCAL_DEV=1 uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

`UGMIG_LOCAL_DEV=1` runs requests as the CLI profile's user with no operator check. It is ignored when `DATABRICKS_APP_NAME` is set (inside a Databricks App), and without it every request fails closed (401). Bind to `127.0.0.1` only. For frontend work, `cd app/frontend && npm run dev` proxies `/api` to that server.


## Tests

```bash
python -m pytest -q          # offline, all Python tests
cd app/frontend && npx tsc --noEmit && npm run build
```

The API and installer tests need the app's dependencies. The command the team uses:

```bash
uv run --with pytest --with "databricks-sdk==0.158.0" --with requests --with fastapi --with httpx python -m pytest -q
```

- `test_planner.py`: classification, rate-limit translation, provider dedup, routing and fallback, inference tables, grants, the scanner, readiness (labels and actions on every blocker and warning), dependency linking, CODE_FIXES, the v2 workspace endpoint inventory, caller classes, and the API-type check.
- `test_account.py`: classification, waves (including the `v2 traffic` rename and the old-name mapping), collisions, profile matching, the deadline and the custom-ML-only wave, and the account copy of `caller_class`.
- `test_apply.py`: payload builders, fallback mapping, secrets, masking, guardrails (including the real planner output), the Terraform export, the job's run outcome, and the cut-over operations (test call, pause, resume, tracking) against fakes: URLs, bodies, refusals, and that no secret is recorded.
- `test_store.py`: the app's Delta store helpers, rollback protection, credential scrubbing, rate-limit caps, the verify builders' bound parameters and the cut-over lock.
- `test_app.py`: the FastAPI app with the Databricks clients mocked: identity and operator rules, CSRF, fail-closed run checks, 202/404 polling, 409 conflicts, the target-schema endpoint, the secret allowlist, dry-run fingerprint matching, stale scans, guardrail acknowledgement, exports, the cut-over endpoints (typed words, dry-run match, resume, rollback refusals, traffic and usage reads), and the parity tests above.
- `test_installer.py`: two kinds of test. The pure helpers in the block between `# HELPERS-BEGIN` and `# HELPERS-END` in `installer/install_template.py` (folders, names, markers, job specs and the parameter contract, the uninstall plan matrix, the rollback pass rule, messages, the deadline check). And notebook-level scenarios: the generated notebook runs cell by cell against `FakeWS`, an in-memory workspace. The scenarios cover fresh installs, reruns, warehouse start and failure, each system-table grant, folder and catalog refusals, bundle jobs and apps, active runs, uninstall preview, rollback order, `NEEDS_ATTENTION` retries, the pass limit, timeouts, drop refusals, shared schemas, reinstall waiting, service principals and the widget labels. Keep the helper block free of `dbutils`, `spark` and `w`: the test runs it without a workspace.
- `test_edge_cases.py`: reviewer-found edge cases across all modules.
- `test_fixtures.py`: live check, not a pytest file. `UGMIG_TEST_CATALOG=<catalog> UGMIG_TEST_GROUP=<group> python test_fixtures.py --profile <p> setup|teardown` creates and removes throwaway `ugmig_test_` objects: two external-model endpoints (fake keys, never queried), a notebook with legacy calls and fake credentials, a saved query, and, unless `UGMIG_SKIP_EXTRA=1`, an AI Search endpoint and index, an app and a job that name legacy endpoints. **The AI Search endpoint is billed while it exists, so run teardown right after.**

The notebooks in `notebook/` run only on Databricks. The installer's logic runs in the `FakeWS` scenarios above, and the notebooks themselves are checked by reading and by byte-compiling them. The live test call (one billable request per service) and the live pause, resume and tracking writes have not been run from the test suite. Run them by hand on a test workspace, with one explicit go-ahead each.

## Making a change to a generated output

Readiness, SUMMARY and CODE_FIXES text is generated in `ug_migration_planner.py`, and ACCOUNT_SUMMARY text in `ug_migration_account.py`. The app shows the same `label` and `action` fields from `readiness.json`. When you change a label or action, check `app/frontend/src` and HOW_TO_READ.md, which name the status legend, glossary lines, caller types and wave names. The cut-over copy lives in `app/frontend/src/Cutover.tsx` (the typed words, the refusals and the Enforce checklist), and USER_GUIDE sections 4 and 5 and the typed confirmation words table in section 8 name the same words. Change them together.

## Screenshots

The images in `docs/screenshots/` are embedded in USER_GUIDE.md, and `overview.png` is also in README.md. They are captured from the built frontend running against the mock backend in `tools/screenshots/`, with fictional data. Regenerate them after a UI change:

```bash
cd app/frontend && npm install && npm run build && cd ../..   # writes app/frontend/static
node tools/screenshots/capture.mjs                           # needs the browser setup in tools/screenshots/README.md
uv run --with pillow python tools/screenshots/optimize.py docs/screenshots/*.png
```

After a regeneration, check that each caption in USER_GUIDE.md still matches its image. `package.sh` copies only the three Markdown guides into the zip, so add `docs/screenshots/` to it before shipping, or the images won't render in the unzipped folder.
