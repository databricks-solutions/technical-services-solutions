# Unity Gateway Playbook: Manage Model-Service Access and Budgets with Terraform

This playbook shows how to manage two parts of Unity Gateway with Terraform:

- **Who can use which model service** in `system.ai` (for example `system.ai.claude-sonnet-4-6`), with Unity Catalog grants or ABAC GRANT policies.
- **AI Gateway budgets**: monthly limits that send an email or block usage.

It covers a new setup and an existing setup that you move to Terraform without a change in access.

> **Business scenario:** Your platform team removed the default access to the `system.ai` models and gave `EXECUTE` to selected groups by hand. You also created budgets in the account console. Now you want Terraform to own both, so that every change goes through a pull request and changes made by hand are reverted.

> Unity Gateway changes fast. For current features, release status and limits, use the Databricks docs linked in [Further Reading](#further-reading). The summaries here can get old.

---

## Contents

| Folder | What it holds |
| --- | --- |
| [`grants/`](grants) | Workspace-level Terraform project: model-service grants (`main.tf`, `access.tf`), optional ABAC policy |
| [`budgets/`](budgets) | Account-level Terraform project: AI Gateway budgets |
| [`scripts/`](scripts) | Read-only helpers: snapshot today's grants, generate `access.tf`, check the plan, import budgets |
| [`ci/plan_and_check.sh`](ci/plan_and_check.sh) | CI gate: plan to a file, refuse deletes, compare with the snapshot, apply the saved plan |
| [`test-harness/`](test-harness) | Prove revoke, re-grant and ABAC behaviour on a test metastore |

---

## What we tested

All results are from a test metastore with 21 `system.ai` model services, provider `databricks/databricks` 1.136.0 and 1.137.0, October 2026.

| Behaviour | Result |
| --- | --- |
| `databricks_grants` on `model_service` | Works. No import needed. Removes principals that are not listed, including the default `account users`. |
| Grant added by hand | Reverted on the next apply (`databricks_grants`). `databricks_grant` does not see grants of other principals. |
| `databricks_grants` with no grant block | Rejected: `Insufficient grant blocks`. |
| Destroy of `databricks_grants` | Revokes every grant in the resource. |
| Terraform identity without `MANAGE` on `system.ai` | Fails: `User does not have MANAGE on MODEL_SERVICE`. Metastore owner alone is not enough. |
| Revoke on one model | Takes effect in about 1–2 minutes. Other models are not affected. |
| Re-grant | Takes effect in about 50 seconds. |
| Call without access | HTTP 404: `'system.ai.<model>' does not exist` (not a permission error). |
| `databricks_ai_gateway_model_services` data source | Returned an empty list on 5 of 6 calls. An empty `for_each` made Terraform revoke the grants. **Do not use it to drive grants.** |
| ABAC GRANT policy (`ai.model_creator = anthropic`) | Anthropic model opened (200) after about 1.5 minutes. Non-Anthropic model stayed closed (404). |
| ABAC access in `databricks grants get` | Not shown. `databricks_grants` does not see it as drift. |
| Terraform exporter and `system.ai` grants | Not exported: the exporter skips the `system` catalog. |
| Budget import (`import` block + `-generate-config-out`) | Round trip with 0 changes, also after removing read-only fields. |

Not tested: budget enforcement (`BLOCK_USAGE`), the exporter output for budgets on a large account, and ABAC with a group (we used a service principal).

---

## Prerequisites

| Requirement | Details |
| --- | --- |
| Terraform | 1.5+ (import blocks), provider `databricks/databricks` 1.136.0+ (`model_service` grants) |
| Grants identity | Service principal with `MANAGE` on schema `system.ai`. A metastore admin grants it once (step 0). |
| Budgets identity | Account admin service principal. Budgets are account-level objects. |
| Databricks CLI | For the snapshot and import scripts (`databricks grants get`, `databricks account budgets list`) |
| State | Remote backend with locking, one for `grants/` and one for `budgets/` |

---

## Key concepts

**`databricks_grants` vs `databricks_grant`**

| | `databricks_grants` (recommended) | `databricks_grant` |
| --- | --- | --- |
| Scope | The full access list of one model service | One principal on one model service |
| Principals you do not list | Removed | Ignored |
| Default `account users` grant | Removed on apply | Stays, unless you add a resource for it |
| Grant added by hand | Reverted on the next apply | Not seen (other principal) |
| Use it for | Model services | The `system.ai` schema grant of `account users` (keeps other schema grants intact) |

**Defaults differ per metastore.** Check before you plan:

```bash
databricks grants get schema system.ai
databricks grants get model_service system.ai.claude-sonnet-4-6
```

- `account users` has `EXECUTE` on each model service: `databricks_grants` removes it per model.
- `account users` has `EXECUTE` on the **schema** `system.ai`: every model inherits it, and a revoke on one model has no effect. Move the access down to each model first ([Schema-level EXECUTE](#schema-level-execute)).

**Direct grants or ABAC?**

| | Direct grants per model | ABAC GRANT policy |
| --- | --- | --- |
| Rule | `access.tf`: model → groups | One tag condition, for example `ai.model_creator = anthropic` |
| New model from Databricks | Closed until you add it in a pull request | Opens at once if it has the tag |
| Visible in `databricks grants get` | Yes | No |
| Removes the default grant | Yes | No (policies only add) |

Start with direct grants. Add a policy only if new models must open without a code change. Even then, keep `databricks_grants`, because only `databricks_grants` removes the default grant.

---

## Step 0: Identities and state (one time)

| Project | Provider | Identity |
| --- | --- | --- |
| `grants/` | `host = <any workspace on the metastore>` | Terraform SP with `MANAGE` on `system.ai` |
| `budgets/` | `host = https://accounts.cloud.databricks.com` (AWS), `https://accounts.azuredatabricks.net` (Azure) or `https://accounts.gcp.databricks.com` (GCP), plus `account_id` | Account admin SP |

A metastore admin runs this once:

```bash
databricks grants update schema system.ai \
  --json '{"changes":[{"principal":"<terraform-sp-application-id>","add":["MANAGE"]}]}'
```

Grants are stored in the metastore, so one `grants/` project covers every workspace on that metastore.

## Step 1: Snapshot today's grants (read-only)

```bash
python3 scripts/snapshot_grants.py --profile <workspace-profile> --out snapshot/grants.json
```

- Reads the grants on catalog `system`, schema `system.ai` and every model service.
- Calls the model-service list API several times and stops if the results do not agree.
- Keep the file: it is also your rollback copy. It holds real principal names, so store it privately.
- `WARNING: account users has EXECUTE on schema system.ai` means every model is open through inheritance. See [Schema-level EXECUTE](#schema-level-execute).

New setup: skip steps 1–3 and write [`grants/access.tf`](grants/access.tf) by hand.

## Step 2: Generate `access.tf` from the snapshot

```bash
python3 scripts/gen_grants_config.py --snapshot snapshot/grants.json --out grants/access.tf
```

```hcl
locals {
  account_users_schema_privileges = ["READ_VOLUME", "SELECT", "USE_SCHEMA"]

  model_grants = {
    "claude-sonnet-4-6" = {
      "data-scientists" = ["EXECUTE"]
      "ml-engineers"    = ["EXECUTE"]
    }
    "gemma-3-12b" = {} # no direct grants today -> break-glass group only
  }
}
```

[`grants/main.tf`](grants/main.tf) does not change. It holds:

- one `databricks_grants` per model (`for_each` over `local.model_grants`), with `prevent_destroy`;
- the break-glass group on models with no other grant;
- one `databricks_grant` for `account users` on the schema, with a precondition that blocks `EXECUTE`.

## Step 3: Prove the first plan changes no access

On the first apply, the plan shows only "create". It does not show which grants it will remove. So compare the plan with the snapshot:

```bash
export DATABRICKS_HOST=https://<workspace-host>   # plus the SP credentials
ci/plan_and_check.sh grants --snapshot snapshot/grants.json
```

```text
Plan: 22 to add, 0 to change, 0 to destroy.
OK: no grant or budget resource is deleted or replaced.
NOTE  system.ai.gemma-3-12b: no grants today; break-glass group gets EXECUTE
OK: planned grants equal the snapshot for 21 models.
```

Any difference fails:

```text
DIFF  system.ai.claude-haiku-4-5: ml-engineers: today ['EXECUTE'] -> planned None
FAILED: 1 difference(s) between the plan and today's grants.
```

## Step 4: Apply the grants

```bash
ci/plan_and_check.sh grants --snapshot snapshot/grants.json --apply
```

The script applies the exact saved plan. Because the plan equals today's grants, no user loses or gets access. The only addition is the break-glass group. You do not need a maintenance window.

## Step 5: Budgets

**New budgets:** copy [`budgets/budgets.tf.example`](budgets/budgets.tf.example) to `budgets.tf`. It has a shared email budget and a per-user `BLOCK_USAGE` cap with a higher limit for one group (`principal_overrides`).

**Existing budgets:** import them. An import changes nothing in the account. You have two options.

*Option A: import blocks (recommended, you select the budgets)*

```bash
# 5a. Import blocks for the AI Gateway budgets (or --resource-type ALL, --name-regex '<pattern>')
python3 scripts/gen_budget_imports.py --profile <account-profile> --out budgets/imports.tf

# 5b. Terraform writes the config from the live budgets
terraform -chdir=budgets plan -var account_id=<account-id> -generate-config-out=budgets_generated.tf

# 5c. Remove read-only fields; replace numeric principal_id with data source lookups
python3 scripts/clean_budget_config.py --profile <account-profile> \
  --in budgets/budgets_generated.tf --out budgets/budgets.tf
rm budgets/budgets_generated.tf

# 5d. Must show: N to import, 0 to add, 0 to change, 0 to destroy
ci/plan_and_check.sh budgets
ci/plan_and_check.sh budgets --apply
rm budgets/imports.tf
```

The import ID of a budget is `<account_id>|<budget_configuration_id>`. If `clean_budget_config.py` prints `WARNING: principal <id> not found`, the principal was deleted: remove or replace that override.

*Option B: the Terraform exporter*

The [exporter](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter) is a command in the provider binary (after `terraform init`, under `.terraform/providers/registry.terraform.io/databricks/databricks/<version>/<os_arch>/`).

```bash
export DATABRICKS_HOST=https://accounts.azuredatabricks.net
export DATABRICKS_ACCOUNT_ID=<account-id>
export DATABRICKS_CLIENT_ID=<sp-application-id>
export DATABRICKS_CLIENT_SECRET=<sp-secret>

./terraform-provider-databricks exporter -skip-interactive \
  -listing billing -services billing -native-import -directory budgets_export
```

- It writes `databricks_budget` and `databricks_budget_policy` resources, import blocks, a provider block and a `databricks_account_id` variable.
- It has no name filter for budgets: it exports **every** budget and serverless budget policy in the account. On a large account this can take a long time. Delete what you do not want Terraform to manage.
- The output has the same read-only fields and numeric principal IDs, so run step 5c on it.
- It does not export `system.ai` grants.

If you recreate a budget in Terraform instead of importing it, delete the old budget afterwards. Two `BLOCK_USAGE` budgets both block.

## Step 6: Stop changes by hand and watch for drift

```bash
# Keep MANAGE on system.ai for the Terraform SP only
databricks grants update schema system.ai \
  --json '{"changes":[{"principal":"<user-or-group>","remove":["MANAGE"]}]}'

# Daily drift check in CI (exit code 2 = drift)
terraform -chdir=grants plan -detailed-exitcode -input=false
terraform -chdir=budgets plan -detailed-exitcode -input=false
```

## Step 7: Change control

| Change | How |
| --- | --- |
| Give a group access to a model | Add the group under the model in `access.tf`, open a PR. In-place update. |
| New model from Databricks | Add `"<model>" = { ... }` in `access.tf`, open a PR. The first apply removes any default grant on it. |
| Retire a model | Remove the entry and run `terraform state rm 'databricks_grants.system_ai_models["<model>"]'` on purpose. `prevent_destroy` blocks an accidental revoke. |
| Change a budget limit | Edit `budgets.tf`, open a PR. In-place update. |

Keep one `databricks_grants` resource keyed by model. If you move a model from one resource to another, the destroy fails (`permissions ... have to be []`). Use a `moved` block or `terraform state rm`.

---

## Optional: ABAC GRANT policy

Rename [`grants/abac_policy.tf.example`](grants/abac_policy.tf.example) to `abac_policy.tf`:

```hcl
resource "databricks_policy_info" "claude_models" {
  name                  = "grant-claude-models"
  on_securable_type     = "SCHEMA"
  on_securable_fullname = "system.ai"
  policy_type           = "POLICY_TYPE_GRANT"
  for_securable_type    = "MODEL_SERVICE"
  to_principals         = ["data-scientists", "ml-engineers"]
  when_condition        = "has_tag_value('ai.model_creator', 'anthropic')"
  grant = {
    privileges = ["EXECUTE"]
  }
}
```

- Databricks tags each `system.ai` model with `ai.model_creator` (for example `anthropic`) and `ai.model_family` (for example `claude-sonnet`).
- The policy adds access. In `access.tf`, give the models only the break-glass group (`{}`), so the policy is the only way in.
- Policies cannot grant `USE CATALOG` or `USE SCHEMA`. The groups still need them on `system` and `system.ai` (`account users` has them by default).
- To check access, read the policies (`databricks policies list-policies SCHEMA system.ai`), not `databricks grants get`.
- Import an existing policy with `id = "SCHEMA,system.ai,<policy-name>"`.

---

## Schema-level EXECUTE

If `account users` has `EXECUTE` on the schema `system.ai`, move it down to each model first. This avoids a gap:

1. In `access.tf`, give each model that must stay open `"account users" = ["EXECUTE"]`.
2. Remove `EXECUTE` from `account_users_schema_privileges`.
3. Plan and apply. Terraform creates the per-model grants first (`depends_on`), then changes the schema grant.
4. In a second PR, remove `"account users"` from the models that must be closed.

## Rollback

| Situation | Action |
| --- | --- |
| Before an apply | Nothing to do: a plan changes nothing. |
| Stop managing a resource | `terraform state rm <address>`. Access does not change. Never run `terraform destroy`. |
| Access broken after an apply | Re-apply the grants from `snapshot/grants.json`. Fastest broad recovery: `GRANT EXECUTE ON SCHEMA system.ai TO \`account users\``. |

## Gotchas

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Insufficient grant blocks` | A model with no grants | Keep the break-glass group on locked models |
| `User does not have MANAGE on MODEL_SERVICE` | Terraform identity has no `MANAGE` | Grant `MANAGE` on `system.ai` (step 0) |
| Plan wants to destroy many grants | The model list came from a data source that returned empty | Use a fixed list in `access.tf`. Never apply a plan with unexpected destroys. |
| Revoke on one model has no effect | `account users` has `EXECUTE` on the schema | [Schema-level EXECUTE](#schema-level-execute) |
| `'system.ai.<model>' does not exist` | The caller has no `EXECUTE` (or the change is still propagating) | Wait 1–2 minutes, then check the grants and policies |
| User has access, but `grants get` shows nothing | Access comes from an ABAC policy | `databricks policies list-policies SCHEMA system.ai` |
| `permissions ... have to be []` on destroy | A model moved between two `databricks_grants` resources | `moved` block or `terraform state rm` |

---

## Test in your own environment

[`test-harness/`](test-harness) proves the behaviour above on a **test metastore you own**. It closes two models (one Anthropic, one not) and keeps every other model open.

```bash
cd test-harness
# 1. Check that models.tf lists every model service in your metastore.
# 2. Create a test SP, get its OAuth token into a file, and give yourself MANAGE on system.ai.
export HOST=https://<workspace-host> TOKEN_FILE=<token-file>
export TF_VAR_profile=<test-profile> TF_VAR_break_glass=<you@example.com> TF_VAR_test_sp_app_id=<sp-app-id>

./call.sh claude-opus-4-5; ./call.sh gemma-3-12b       # baseline: expect 200, 200
./safe_apply.sh '^databricks_grants?\.'                 # close the two test models
./call.sh claude-opus-4-5; ./call.sh gemma-3-12b       # expect 404, 404 after about 1-2 min
./safe_apply.sh '^databricks_policy_info' -var enable_policy=true
./call.sh claude-opus-4-5; ./call.sh gemma-3-12b       # expect 200, 404 after about 1-2 min
```

`safe_apply.sh` plans to a file, refuses any delete or any change outside the address pattern, then applies that plan.

Restore in this order, so no model closes. These steps delete resources, so use `terraform plan -out` and read the plan before each `terraform apply`:

1. Delete the policy: `-var enable_policy=false` (plan: only `databricks_policy_info` delete).
2. Put `EXECUTE` back on the schema: `./safe_apply.sh '^databricks_grant\.schema' -var 'schema_privileges=["EXECUTE","READ_VOLUME","SELECT","USE_SCHEMA"]'`.
3. `terraform state rm databricks_grant.schema_account_users`. If you skip this, the destroy revokes all `account users` privileges on the schema.
4. `terraform plan -destroy -out=tf.plan`: check that it has only `databricks_grants` deletes, then `terraform apply tf.plan`.
5. Delete the test SP and remove your `MANAGE`.

---

## Further Reading

- [databricks_grants resource](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grants) and [databricks_grant resource](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/grant)
- [databricks_policy_info resource](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/policy_info)
- [databricks_budget resource](https://registry.terraform.io/providers/databricks/databricks/latest/docs/resources/budget)
- [Terraform exporter guide](https://registry.terraform.io/providers/databricks/databricks/latest/docs/guides/experimental-exporter)
- [Terraform import blocks with generated configuration](https://developer.hashicorp.com/terraform/language/import/generating-configuration)
- [Unity Gateway documentation](https://docs.databricks.com/aws/en/ai-gateway/)
- [Govern access to models with grant policies](https://docs.databricks.com/aws/en/ai-gateway/govern-access-to-models-with-grant-policies)
- [Unity Gateway budgets](https://docs.databricks.com/aws/en/ai-gateway/budgets)
