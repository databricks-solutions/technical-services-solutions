# How to read the migration results

This guide describes the files the toolkit writes. It is for the team that runs the Unity Gateway Migration Toolkit in its own account. The toolkit is a prototype, provided as is.

Scans only read your workspace. Results, including matched code lines, go to the results schema. Apply and rollback create or delete Unity Gateway services. Verify and cut-over runs send test requests, change endpoint rate limits or change usage tracking, and only when you execute them. Snapshots append rows to tables. Nothing else changes.

For the deadline, install, uninstall and limitations, see [USER_GUIDE.md](USER_GUIDE.md). The app's Export menus carry the same data (see [Export names](#export-names)).

---

## Start with these

| File | Question it answers |
|---|---|
| `READINESS.md` | Can we turn on Enforce Unity Gateway in this workspace? If not, what's in the way? |
| `SUMMARY.md` | Which legacy endpoints do we have, who calls them, and where is that code? |
| `CODE_FIXES.md` | Which lines change, and what do they look like before and after? |
| `ACCOUNT_SUMMARY.md` | Across the account, which workspaces are where, and in which wave? (account view) |

---

## READINESS.md

The first line is `Status: <STATUS>`, followed by the status legend:

| Status | Legend in the file |
|---|---|
| `READY` | no blockers, full scan. |
| `READY_WITH_WARNINGS` | no blockers; review warnings first. |
| `BLOCKED` | enforcing now breaks the calls listed below. |
| `INCOMPLETE` | nothing blocking found, but part of the scan didn't run; fix the listed gap and re-run. |

Sections, in order:

- **Next steps:** a numbered list for the current status. When the status is `BLOCKED` with an incomplete scan, the first step is to close the scan gaps.
- **Glossary:** Enforce, legacy endpoint (v1 and v2), workspace-bound v2 endpoint, Unity Gateway model service, provider service, caller type, apply, dry run, blocker, warning.
- **Blockers (N):** a count per label, then one line per finding: `label (item): detail. Action: ...`. The first 60 are listed, then "+N more in readiness.json".
- **Warnings (N):** the same format, for code and traffic that will break if it still runs.
- **Incomplete scan:** surfaces that failed, were cut off or were skipped. Readiness can't be confirmed until these are fixed.
- **Not covered (notes, not gaps):** surfaces that were left out on purpose.
- **Can be stopped now (no new service needed):** external model endpoints with no traffic in the window, no code references and no dependents. Each has a stop command and an undo command (`databricks api put` on the endpoint's `ai-gateway` path). The stop sets the rate limit to 0 calls per minute and keeps the other settings. The second column says whether the replacement service already exists. Stopping doesn't need it; migrating does.
- **What Enforce does:** the setting, what it breaks (`PERMISSION_DENIED`), and that zero requests in the window is not proof that nothing calls an endpoint.

### Finding types in readiness.json

Every blocker and warning has `type` (a stable machine name), `label`, `item`, `detail` and `action`. The file shows the `label` and `action`. Traffic findings also carry `caller_classes` (requests per caller class) and, when coding agents are seen, `user_agents`.

Blocker types:

| `type` | Label in the file | Meaning |
|---|---|---|
| `unity_gateway_unavailable` | Unity Gateway isn't available in this workspace | Listing the `system.ai` model services failed with a not-enabled, disabled or 403 error, so Unity Gateway is off for this workspace or account. Nothing can be migrated until it is enabled. The detail gives the error. |
| `v2_off_failing_calls` | v2 calls are already failing in this workspace | At least 95% of at least 10 v2 requests failed (no status code, status 0 or status 501; 403 and 404 aren't counted, because they usually come from the caller). v2 is already off, so the callers get errors now. The detail gives failed out of total, and the HTTP 501 count. Move the callers to the `system.ai` target first, keeping the `/ai-gateway/` route. |
| `legacy_traffic` | Callers still use a legacy endpoint | Callers other than Databricks-managed ones still send requests. The detail gives requests by caller type, for example `callers by type (requests): coding_agent 1,200, no_client_info 300`. |
| `pay_per_token_call` | Code calls a Databricks pay-per-token endpoint | Code references a `databricks-*` endpoint. The call fails once Enforce is on. If the endpoint also embeds for an AI Search index, switch only the direct calls and keep the endpoint. |
| `v2_workspace_call` | Code calls a v2 workspace endpoint | Code calls a workspace-bound v2 endpoint by its flat name. Fix: keep the `/ai-gateway/` route and change the model (see CODE_FIXES.md). |
| `ai_query_custom` | ai_query calls a model with no Unity Gateway service yet | Keep the call, or switch it to a `system.ai` model. |
| `vector_search` | AI Search index embeds with a legacy endpoint | Keep the endpoint, and don't enforce Unity Gateway until AI Search supports `system.ai` embeddings. |
| `unresolved_endpoint_call` | Code calls a serving endpoint the scan can't name | The endpoint name is built at run time. Find which endpoint the call reaches: move a legacy one to `/ai-gateway/`, and name a custom model or feature serving one in the code so the scan can see it. |
| `agent_bricks_vector_search` | Agent Bricks agent uses AI Search | Check its index and embedding model. |
| `app_resource` | App declares a legacy serving endpoint resource | Replace the resource with the Unity Gateway service. |
| `agent` | Agent endpoint runs on legacy serving | The agent has requests in the window. Redeploy it on Databricks Apps. |

Warning types:

| `type` | Label in the file | Meaning |
|---|---|---|
| `platform_managed_traffic` | Databricks-managed callers use this endpoint | Only Databricks-managed callers (class `platform`) send traffic. A warning, not a blocker. You can't change these callers. |
| `local_folders_not_scanned` | Local folders were not scanned | No `--local-path` was given, so cloned repos and bundle folders were not searched. This caps the status at READY_WITH_WARNINGS. |
| `skipped_paths_not_scanned` | Some folders or file types were not scanned | The scan skipped dependency or build folders, or file types it doesn't read. The detail lists them. Check them, or confirm they hold no calls. This caps the status at READY_WITH_WARNINGS. |
| `confirm_infrequent_callers` | Pay-per-token or v2 endpoint has no traffic and no known callers | A monthly or quarterly job wouldn't show in the window. v2 endpoints seen in the last year are included. Confirm with the owners. |
| `no_traffic_in_window` | No requests in the window and usage tracking is off | Confirm with the owners that no infrequent job calls it. |
| `dormant_agent_endpoint` | Agent endpoint has no traffic in the window | Confirm with the owner that it is unused. |
| `legacy_traffic_kept_after_enforce` | Callers use an external or PT endpoint that outlives Enforce | It keeps working after Enforce and retires on the deadline in [USER_GUIDE.md](USER_GUIDE.md#the-deadline). |
| `pt_wrapper_on_legacy_endpoint` | Unity Gateway wrapper routes to a legacy PT endpoint | Plan the PT move before the deadline. |

Code-reference warnings use the reference pattern as their type, for example `sdk_serving_query` or `ai_gateway_regional_host`. Each has its fix in CODE_FIXES.md.

---

## SUMMARY.md

- **Title line:** `Status: <STATUS>. Start with READINESS.md.`
- **Glossary:** the same lines as READINESS.md.
- **Endpoints:** a count per kind, a count per plan action, and how many endpoints had traffic in the window. A line says how many of those requests were v2 traffic, how many tokens the window had (input and output, v1 and v2; shown for sizing, readiness uses requests), and which v2 calls are already failing. All legacy endpoints stop on the deadline in [USER_GUIDE.md](USER_GUIDE.md#the-deadline). The kinds are named as follows:

| Kind in the file | Meaning |
|---|---|
| Databricks pay-per-token (system) | `databricks-*` models. Their `system.ai` replacement already exists, so only callers change |
| External model | OpenAI, Anthropic and other providers. Apply can create a service |
| Provisioned throughput | Dedicated capacity. Apply can wrap it |
| Custom ML model | Your own models. Not affected |
| Agent | Agent served on legacy serving. Redeploy it on Databricks Apps |
| v2 workspace endpoint | An AI Gateway v2 endpoint with no serving-endpoint object. Its only trace is its traffic, so it is inventoried from `system.ai_gateway.usage`. Its source in `legacy_endpoints.csv` and `migration_plan.csv` is `AI Gateway v2 (workspace-bound)` |

The plan actions are "Use a system.ai model" (`use_system_ai`), "Create a Unity Gateway service" (`create_model_service`), "Out of scope (custom ML)" (`out_of_scope`) and "Manual (see needs)" (`manual`). `manual` covers a system endpoint with no `system.ai` model, and a v2 endpoint whose target doesn't support an API type its callers use.

- **Active endpoints:** the top 25 with traffic: endpoint, kind, requests, tokens, requesters, last request, target service.
- **Who calls legacy endpoints:** the top 30 caller and endpoint pairs, with columns endpoint, caller, caller type, API, requests, last request and code found. "no code found: check jobs, external apps or local code" means the code isn't in a scanned folder. The caller type is explained in [Caller types](USER_GUIDE.md#caller-types).
- **Provider services:** each service with its status: `automated` (apply creates it), `manual_supported` (Unity Gateway supports it, apply doesn't) or `no_ug_provider`.
- **Needs a human (N endpoints):** the decisions the toolkit won't make. A line counts the plaintext API keys (values are never shown). The list is capped at 50, then "+N more in migration_plan.csv".
- **Client references:** a count per finding, then the first 40 references. The rest are in `client_references.csv`.

---

## CODE_FIXES.md

The header states the number of proposed line changes, the number of files, and the number of references that need a manual edit. Nothing is changed. Apply the fixes in the source (and its Git repo), then re-run the planner.

- **Proposed line changes** are grouped by file, as a diff. Each change has the line number, the old line (`-`), the new line (`+`) and a `# note:` with its caveat.
- **Confidence** is `review` for every change. Check each one and test it. A proposed change is never applied automatically.
- **References that need a manual edit** have no safe one-line rewrite. Each line shows the matched text, its location, the finding and what to do.

Patterns that matter for the cut-over:

| Pattern | What the fix does |
|---|---|
| `v2_gateway_model` | A v2 workspace endpoint's flat model name on an `/ai-gateway/` route. The model becomes the `system.ai` target and the route stays. If the target doesn't support the route's API type, there is no fix: the reference is manual. Never move a Responses route to Chat Completions. |
| `sdk_serving_query` | `serving_endpoints.query(name=...)` in the Databricks SDK. Never rewritten, because the SDK has no Unity Gateway query method at databricks-sdk 0.158.0. Manual: use the OpenAI client on `<workspace>/ai-gateway/mlflow/v1` with an `ai-gateway` scoped token. |
| `ai_gateway_regional_host` | A legacy regional AI Gateway host. Manual. Move to the workspace `/ai-gateway/` route with an `ai-gateway` scoped token. |
| `ChatDatabricks` (multi-line) | The fix changes only the model line. Add `use_ai_gateway=True` by hand. |

Caveats that appear in the notes: `ai_query` on Unity Gateway gets usage tracking only; when you change a URL, move the token from `all-apis` to `ai-gateway`.

---

## ACCOUNT_SUMMARY.md

- **Deadline (confirmed as of 2026-11-01):** the one legacy deadline and the days left, counted when the summary was written. The date and its overrides are in [USER_GUIDE.md](USER_GUIDE.md#the-deadline).
- **Headline:** running workspaces (and how many have no endpoint data or are custom-ML only), workspaces with legacy endpoints, traffic-unknown endpoints and workspaces, legacy endpoints in scope, and requests for v1, v2 and Unity Gateway. The Unity Gateway share is marked "about" because v1 rows can include Unity Gateway backend legs. The headline also gives customer-owned and Databricks-managed request counts.
- **Endpoints by kind:** the same kinds as SUMMARY.md, account-wide.
- **Waves:** each workspace gets one wave. The rules are applied in this order, and the first match wins: not running, no endpoint data, high volume, v2 traffic, small, custom-ML only, cleanup, traffic unknown, no legacy traffic.

| Wave | Workspaces with this wave mean |
|---|---|
| `not running` | Status isn't RUNNING. Not in the running total |
| `no endpoint data` | Running, but no endpoint, usage or AI Gateway rows. A workspace scan says whether anything needs migrating |
| `2: high volume` | 10,000 or more legacy requests (v1 and v2) in the window |
| `v2 traffic` | Any v2 requests in the window, below the high-volume line. Renamed from `v2 first`. It carries no urgency of its own: the one deadline applies to every legacy endpoint |
| `1: small` | 1 to 9,999 v1 requests in the window, and no v2 requests |
| `no legacy endpoints (custom ML only)` | Only custom ML or feature serving endpoints. Nothing to migrate here, but notebooks may still call legacy endpoints, so scan it. Not counted as no traffic |
| `1: cleanup` | No v1 traffic, but external, PT or other legacy endpoints exist |
| `0: traffic unknown` | Live legacy endpoints with no usage rows in the history window (usage tracking may be off) |
| `0: no legacy traffic` | No v1 or v2 requests and no unknown endpoints. A candidate only. A passing workspace scan is still needed. Renamed from `0: enforce candidate` |

- **Workspaces (busiest first):** legacy endpoints, the external, PT or other share, active endpoints, v1 and v2 requests, throttled requests, Unity Gateway requests, the customer-owned, Databricks-managed and coding-agent request counts, the approximate share, and the wave. Old snapshots written before these columns show "-".
- **Tokens:** the headline gives the window's tokens (input and output, v1 and v2). Each workspace has `legacy_tokens` (v1 and v2) in the account CSV, and each endpoint has `legacy_tokens`. Snapshots written before these columns show "-" for them. Tokens are shown for sizing; waves and readiness use requests.
- **Workspace signals:** endpoints with unknown traffic, last seen, deleted-endpoint requests, a **v2 calls** column marked "v2 failing" where most v2 requests failed (at least 10 requests and 95% failed), and config signals from billing activity over the last year (AI Search, Agent Bricks, Apps, AI Functions). Signals suggest where to look. The workspace scan is the check.
- **Busiest legacy v1 endpoints:** the top 20.
- **Name collisions:** custom endpoint names that exist in more than one workspace. If the workspaces share a metastore, give each its own target schema.

---

## callers.csv

One row per (endpoint, requester, API, user agent, caller class). A requester can appear on several rows, one per user agent.

| Column | Meaning |
|---|---|
| `endpoint_name` | The legacy endpoint |
| `requester` | Who sent the requests: an email, a service principal ID, or a Databricks system identity |
| `requester_name` | A display name, when one is known |
| `api` | `v1` (serving endpoint usage) or `v2` (AI Gateway usage) |
| `caller_class` | One of the values in [Caller types](USER_GUIDE.md#caller-types). `platform` is Databricks system identities only |
| `user_agent` | v2 rows only. The client's user agent, which tells coding agents and SDKs apart |
| `requests`, `last_request` | Requests in the window, and the last one |
| `tokens` | Input plus output tokens in the window (v1 usage) or `total_tokens` (v2). Shown, not used for decisions. 0 when the source has none |
| `linked_code`, `linked_count` | The code found in the caller's folders, and how many references |

---

## migration_plan.csv

One row per legacy endpoint. The columns that changed in 0.10.0:

- `kind`: includes `v2_workspace_endpoint`.
- `source`: `Model Serving (v1)` or `AI Gateway v2 (workspace-bound)`.
- `action`: `use_system_ai`, `create_model_service`, `manual` or `out_of_scope`.
- `api_types`: the API types callers use in the window (for example `mlflow/v1/chat/completions` or `openai/v1/responses`).
- `target_api_types`: what the target service supports. Empty when unknown.
- `tokens_window`: input plus output tokens in the traffic window (v1 and v2). Shown for sizing; readiness uses requests.
- `v2_tokens`, `v2_failed`, `v2_status_501`: the v2 part of the window. `v2_failed` counts v2 requests with no status code, status 0 or status 501. `v2_status_501` counts HTTP 501 (v2 is off for the workspace).

A `manual` row with a note in `needs_human` means a person has to decide. Typical cases: the target doesn't support an API type callers use, or no `system.ai` model fits.

---

## readiness.json and the code-reference patterns

`readiness.json` has every finding (see [Finding types in readiness.json](#finding-types-in-readinessjson)) and the status, coverage and counts. The planner's printed JSON summary has a `v2_workspace_endpoints` count.

---

## Verify and cut-over runs

The **Verify & cut over** tab writes its runs to the same results tables as apply, with an `operation` column: `apply` (or blank on older rows), `test_call`, `pause_legacy`, `enable_tracking` or `resume_legacy`. Use `operation` to tell them apart. The run's items have these columns:

- Every item: `type`, `name`, `action`, `reason`, `execute` and `time`.
- Test rows (`type = model_service`): `api_type`, `path` (`/ai-gateway/<api_type>`, no host), `http_status`, `request_id` (from the response headers), `latency_ms`, `reply_excerpt` (at most 200 characters; for embeddings, the vector size) and `note` (when no request ID came back).
- Endpoint rows (`type = serving_endpoint`): `kind`, plus the settings before and after the change (`previous_ai_gateway`, `paused_ai_gateway`, `requested_ai_gateway`, `current_ai_gateway`) and `pause_apply_id` for a resume.

The action values are in [Result actions](USER_GUIDE.md#result-actions). A test result never contains the token.

---

## Export names

The app's **Export** menus download these. Scan exports are named after the report or data they carry.

| Page | Export name | Format |
|---|---|---|
| Overview | Workspaces | CSV |
| Overview | All legacy endpoints | CSV (not only the top 100 on screen) |
| Overview | Trend across snapshots | CSV (rolling windows, so consecutive points overlap) |
| Scans | Readiness report | Markdown (READINESS.md) |
| Scans | Code fixes | Markdown (CODE_FIXES.md) |
| Scans | Summary | Markdown (SUMMARY.md) |
| Scans | Endpoint plan | CSV (the same data as migration_plan.csv) |
| Scans | Callers | CSV (the same data as callers.csv) |
| Scans | All references | CSV (the same data as client_references.csv) |
| Scans | Provider services | CSV (the same data as provider_services.csv) |
| Apply (one run) | Export results | CSV: every object the run created, checked, skipped or kept |
| Verify & cut over | Export CSV (Unity Gateway traffic) | CSV: the per-service, requester and API type summary for the chosen window and service |
| Verify & cut over (one run) | Export results | CSV: the run's items, as described above |

An export that reaches 200,000 rows is cut off, and the response carries `X-Truncated: true`.

---

## Things to know

- Usage data can lag by a few hours. Unity Gateway usage can take 20 to 30 minutes to appear. The traffic window can miss rare callers. See [Limitations](USER_GUIDE.md#10-limitations) for the full list.
- The scan only sees what's in the workspace. Code in external repos, on laptops and in other apps needs `--local-path` or the callers table. Coding agents on laptops show up as callers, not as code.
- Questions go to your Databricks account team.
