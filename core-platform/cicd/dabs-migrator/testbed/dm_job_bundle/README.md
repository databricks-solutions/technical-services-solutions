# dm_job_bundle

Databricks Asset Bundle for `dm_job` — migrated from the DEV workspace
(`https://adb-7405613676539969.9.azuredatabricks.net`).

> ⚠️ **Paused for staging and prod.** This bundle is safe to run in `dev` only.
> Staging and prod targets will be added after open issues are resolved:
> [#107](https://github.com/databricks-solutions/technical-services-solutions/issues/107),
> [#108](https://github.com/databricks-solutions/technical-services-solutions/issues/108).

## Layout

```
dm_job_bundle/
├── databricks.yml          # bundle root (dev target only)
├── resources/
│   └── jobs/
│       └── dm_job.yml      # job resource definition
├── src/
│   └── dm_job/
│       └── notebook.py     # verbatim source from workspace
├── tests/
│   └── test_unity_catalog.py
├── bindings/
│   └── dev.yml             # bind map for source workspace (run once before first deploy)
├── requirements.txt
└── .gitignore
```

## Binding (one-time per source workspace)

Before the **first** `databricks bundle deploy -t dev`, you must bind each migrated
resource to its existing workspace counterpart so the deploy updates it rather than
creating a duplicate.

The bind map is in `bindings/dev.yml`. Run:

```bash
cd dm_job_bundle
grep -v '^#' bindings/dev.yml | while IFS=': ' read -r key bind_id; do
  [ -z "$key" ] && continue
  bind_id=$(printf '%s' "$bind_id" | tr -d '"')
  echo "Binding $key -> $bind_id"
  databricks bundle deployment bind "$key" "$bind_id" -t dev --auto-approve
done
```

> ⛔ **Never run `databricks bundle destroy`** — it will delete live workspace assets.

## Deploy

```bash
# First-time (after binding):
databricks bundle deploy -t dev

# Subsequent deploys:
databricks bundle deploy -t dev
```

## Local validation

```bash
databricks bundle validate -t dev
```
