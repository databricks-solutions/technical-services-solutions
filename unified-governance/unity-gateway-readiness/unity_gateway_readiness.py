# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Gateway Readiness Check
# MAGIC
# MAGIC Reusable end-to-end check that a workspace is ready to run production traffic through Unity Gateway.
# MAGIC Unity Gateway exposes models as Unity Catalog securables called **model services** (for example `system.ai.claude-opus-5-5`).
# MAGIC Callers reach them at `https://<workspace>/ai-gateway/...`, governed by UC grants, rate limits, budgets, and usage tables.
# MAGIC
# MAGIC ### How to use
# MAGIC 1. Set the widgets at the top. `target_models` is the list of models the customer plans to use.
# MAGIC 2. Run all cells as the identity that will call the gateway in production. Run it interactively for a user, or as a job owned by the service principal to test the SP's real access.
# MAGIC 3. Each section ends with a card of its checks. The dashboard in section 10 shows the verdict, a model-by-check matrix (hover a cell for evidence), blockers with fixes, and the manual checklist.
# MAGIC
# MAGIC ### Requirements
# MAGIC **Role.** Run the notebook as a **workspace admin** who is also a **metastore admin**. Account admin adds the most coverage.
# MAGIC The usage and spend tables in sections 8 and 9 are readable only by account and metastore admins by default, and reading another principal's grants (section 3) needs `MANAGE` or ownership.
# MAGIC Section 1 reports the roles the running identity holds.
# MAGIC
# MAGIC Run it twice for a full picture:
# MAGIC 1. As an admin, for the complete inventory, grants, usage, and cost data.
# MAGIC 2. As the production identity (for example a service principal, through a job it owns), to prove that identity's real access in sections 4 and 7.
# MAGIC
# MAGIC | Requirement | Needed for | Without it |
# MAGIC |---|---|---|
# MAGIC | Workspace admin | Reading workspace settings and other principals' access | Section 3 and 7 grant checks return WARN |
# MAGIC | Metastore admin, or `MANAGE` on `system.ai` | Effective grants on `system.ai` model and MCP services | Grant checks return WARN |
# MAGIC | Account admin, or `SELECT` on `system.ai_gateway` | `system.ai_gateway.usage` and `external_model_spend` | Sections 8 and 9 return FAIL for those reads |
# MAGIC | `SELECT` on `system.billing.usage` and `system.billing.list_prices` | Spend by model service | Section 9 spend check returns FAIL |
# MAGIC | `EXECUTE` on each target model and MCP service | Live probes in sections 4 and 7 | Probes return FAIL, which is the point of running as the production identity |
# MAGIC | `USE CATALOG`, `USE SCHEMA`, `CREATE SERVICE` on `test_schema` | Optional custom service round trip (section 6) | Section 6 returns WARN or SKIP |
# MAGIC | `CREATE TABLE` on the target schema | Optional `results_table` write | The final cell fails |
# MAGIC
# MAGIC **Platform.** Unity Catalog enabled, a workspace in a Unity Gateway supported region (not AWS GovCloud), and compute that can reach the workspace host over HTTPS.
# MAGIC **Compute.** Tested on serverless notebook compute, environment version 3. Classic clusters need a runtime that ships `databricks-sdk` with `WorkspaceClient.api_client`.
# MAGIC
# MAGIC ### Status values
# MAGIC | Status | Meaning |
# MAGIC |---|---|
# MAGIC | `PASS` | Verified working in this workspace for this identity |
# MAGIC | `FAIL` | Blocks readiness. The `remediation` column says what to change |
# MAGIC | `WARN` | Works, but needs review before production scale, or could not be verified |
# MAGIC | `INFO` | Context for the reader. No action needed |
# MAGIC | `MANUAL` | No API exposes this. Confirm it in the account console or with the account team |
# MAGIC | `SKIP` | Turned off by a widget, or skipped because a prerequisite failed |
# MAGIC
# MAGIC ### Sections
# MAGIC | Section | What it verifies |
# MAGIC |---|---|
# MAGIC | 1. Platform | Unity Catalog metastore, cloud, region, GovCloud exclusion, caller identity, gateway API reachability |
# MAGIC | 2. Model catalog | Each target model has a model service, live destinations, supported APIs, rate limits, inference table |
# MAGIC | 3. Access | `system` / `system.ai` / per-service grants for `account users` and an optional principal |
# MAGIC | 4. Invocation | Live call on every supported API, streaming, `ai_query`, optional parallel burst |
# MAGIC | 5. Azure ADI Services | On Azure Databricks: which targets are delivered through ADI, and whether ADI is activated (live proof) |
# MAGIC | 6. Custom services | `CREATE SERVICE` on a schema, optional create, query, delete round trip, provider and MCP services |
# MAGIC | 7. MCP services | Each target MCP service exists, its tool selection, rate limits, grants, a live `tools/list` call, and recent MCP traffic |
# MAGIC | 8. Observability | `system.ai_gateway.usage`, `external_model_spend`, `system.billing.usage`, probe traffic landing in usage |
# MAGIC | 9. Cost controls | Rate limit coverage, service and request tags, spend by model service, cache, reasoning, and priority tier use, budgets |
# MAGIC | 10. Manual checks and scorecard | Account-level items, verdict, per-model matrix, optional write to a Delta table |
# MAGIC
# MAGIC ### Cost and side effects
# MAGIC Probes send a few prompts per model of about 20 tokens each. The burst probe sends `burst_requests` more per model.
# MAGIC MCP probes call `initialize` and `tools/list` only. They never call a tool.
# MAGIC The only write is the opt-in temporary model service in section 6, which the notebook deletes in a `finally` block.
# MAGIC Every probe carries the request tag `tool=ug_readiness` and a unique `readiness_run_id`, so its traffic is easy to filter in usage tables.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Widgets
# MAGIC | Widget | Purpose |
# MAGIC |---|---|
# MAGIC | `target_models` | Comma-separated model services. A bare name such as `gpt-6-astra` is read as `system.ai.gpt-6-astra`. Custom services use `catalog.schema.name` |
# MAGIC | `principal_to_check` | A group, user, or service principal application id. Section 3 reports its effective grants |
# MAGIC | `run_invocation_probes` | `no` skips all live calls. Sections 4, 5, and 7 then cannot prove access, and the verdict is `NOT VERIFIED` instead of `READY` |
# MAGIC | `burst_requests` | Sends N parallel requests per model to surface 429 rate limiting. 0 skips it |
# MAGIC | `test_schema` | `catalog.schema` where the customer will create custom model services. Blank skips section 6 |
# MAGIC | `create_test_service` | `yes` creates a temporary model service in `test_schema`, queries it, then deletes it |
# MAGIC | `adi_mode` | `auto` runs section 5 only on Azure. `force` runs it on any cloud (for dry runs). `off` skips it |
# MAGIC | `target_mcp_services` | Comma-separated MCP services to check and probe with `tools/list`. A bare name such as `web_search` is read as `system.ai.web_search`. Blank skips the per-service checks in section 7 |
# MAGIC | `usage_lookback_days` | Window for usage and billing queries in sections 7, 8, and 9 |
# MAGIC | `usage_wait_seconds` | How long section 8 waits for this run's probe rows to appear in `system.ai_gateway.usage` |
# MAGIC | `results_table` | Optional Delta table to append results to, for tracking readiness across runs |

# COMMAND ----------

dbutils.widgets.text(
    "target_models",
    "system.ai.claude-opus-5-5,system.ai.claude-fable-5,system.ai.gpt-5-6-sol,system.ai.gpt-6-astra",
    "01. Target models (comma separated)",
)
dbutils.widgets.text("principal_to_check", "", "02. Extra principal to check grants")
dbutils.widgets.dropdown("run_invocation_probes", "yes", ["yes", "no"], "03. Run live invocation probes")
dbutils.widgets.text("burst_requests", "0", "04. Parallel burst size per model (0 = skip)")
dbutils.widgets.text("test_schema", "", "05. catalog.schema for custom services (blank = skip)")
dbutils.widgets.dropdown("create_test_service", "no", ["no", "yes"], "06. Create, query, delete a temp model service")
dbutils.widgets.dropdown("adi_mode", "auto", ["auto", "force", "off"], "07. Azure ADI checks")
dbutils.widgets.text("target_mcp_services", "system.ai.web_search", "08. Target MCP services (comma separated)")
dbutils.widgets.text("usage_lookback_days", "7", "09. Usage lookback days")
dbutils.widgets.text("usage_wait_seconds", "180", "10. Seconds to wait for probe rows in usage")
dbutils.widgets.text("results_table", "", "11. Delta table to append results (blank = skip)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Setup and helpers
# MAGIC `record()` collects every check into one results list. `api()` calls workspace REST APIs with the notebook's own credentials.
# MAGIC `gateway_post()` calls the Unity Gateway data plane with the same credentials and the readiness request tags.
# MAGIC `classify_error()` turns an HTTP failure into a cause and a fix. A 404 that says "not available in your region" means region or data residency, not a typo.
# MAGIC `CHECK_ABOUT` holds the plain-language description shown in the `about` column of the results.

# COMMAND ----------

import html as html_lib
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import requests
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
HOST = w.config.host.rstrip("/")
RUN_ID = uuid.uuid4().hex[:12]
RUN_TS = datetime.now(timezone.utc)


NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def normalize_model(name):
    name = name.strip()
    if not NAME_RE.match(name):
        raise ValueError(f"Invalid service name {name!r}. Use catalog.schema.name with letters, digits, '_', '-', and '.' only.")
    return name if "." in name else f"system.ai.{name}"


TARGET_MODELS = [normalize_model(m) for m in dbutils.widgets.get("target_models").split(",") if m.strip()]
if not TARGET_MODELS:
    raise ValueError("target_models is empty. Enter at least one model service, for example system.ai.claude-opus-5-5.")
PRINCIPAL_TO_CHECK = dbutils.widgets.get("principal_to_check").strip()
RUN_PROBES = dbutils.widgets.get("run_invocation_probes") == "yes"
BURST = int(dbutils.widgets.get("burst_requests") or 0)
TEST_SCHEMA = dbutils.widgets.get("test_schema").strip()
CREATE_TEST_SERVICE = dbutils.widgets.get("create_test_service") == "yes"
ADI_MODE = dbutils.widgets.get("adi_mode")
TARGET_MCP = [normalize_model(m) for m in dbutils.widgets.get("target_mcp_services").split(",") if m.strip()]
LOOKBACK_DAYS = int(dbutils.widgets.get("usage_lookback_days") or 7)
USAGE_WAIT_S = int(dbutils.widgets.get("usage_wait_seconds") or 0)
RESULTS_TABLE = dbutils.widgets.get("results_table").strip()
REQUEST_TAGS = json.dumps({"tool": "ug_readiness", "readiness_run_id": RUN_ID})

# Ordered (prefix, description) pairs. The first prefix that matches a check name supplies its `about` text.
CHECK_ABOUT = [
    ("Caller identity", "The user or service principal running this notebook. Every probe runs as this identity, so the results reflect its access only."),
    ("Unity Catalog metastore", "Unity Gateway model services are Unity Catalog securables, so the workspace must have a metastore assigned."),
    ("Workspace admin", "Whether the running identity is in the workspace `admins` group. Admins can read other principals' grants and workspace settings."),
    ("Metastore admin", "Whether the running identity owns the metastore, directly or through a group. Metastore admins can read and manage grants on system.ai model and MCP services."),
    ("Account admin", "Account admin cannot be read from inside a workspace. Section 8 proves it indirectly: system.ai_gateway tables are readable only by account and metastore admins by default."),
    ("Region supports", "Unity Gateway is not available on AWS GovCloud."),
    ("Region", "The metastore's cloud and region. Model availability varies by region. Sections 2 and 4 test each model live instead of relying on a static table."),
    ("Unity Gateway API reachable", "Lists model services in system.ai. A failure means the gateway control plane is not available to this workspace."),
    ("List model services", "Lists every model service in the target model's schema, with full config."),
    ("Model services visible", "How many model services this identity can see in the target schemas."),
    ("Model service exists", "The target model has a model service this identity can see, and lists the API formats it accepts. On Azure, ADI models can appear here before ADI is activated, so section 5 relies on the live call."),
    ("Live destination", "The model service routes to at least one destination that is not deleted. A service with only deleted destinations cannot serve traffic."),
    ("Rate limits", "Service-level QPM or TPM limits apply to all callers together. Very low limits throttle production traffic."),
    ("Inference table", "Requests and responses are logged to a Delta table for audit and debugging."),
    ("account users:", "Effective grants for the built-in `account users` group. By default every account user has EXECUTE on system.ai. Locked-down accounts remove this and grant per team."),
    ("Extra principal", "Effective grants for the principal named in the widget."),
    ("mlflow/v1/chat/completions", "Live call to the unified OpenAI-compatible Chat Completions API at /ai-gateway/mlflow/v1/chat/completions."),
    ("mlflow/v1/responses", "Live call to the unified Responses API at /ai-gateway/mlflow/v1/responses, which Databricks recommends for new clients."),
    ("openai/v1/responses", "Live call to the native OpenAI Responses API at /ai-gateway/openai/v1/responses, used by OpenAI SDK code."),
    ("anthropic/v1/messages", "Live call to the native Anthropic Messages API at /ai-gateway/anthropic/v1/messages, used by Anthropic SDK code and Claude Code."),
    ("Client-specific APIs", "API formats used by specific coding agents (Cursor, Codex). They share the same service and grants, so they are listed but not probed."),
    ("streaming, ai_query, burst", "Follow-on probes run only when the basic call succeeds."),
    ("streaming", "Streams a chat completion over server-sent events and measures time to first chunk. Interactive apps and coding agents depend on streaming."),
    ("ai_query", "Runs ai_query() from SQL against the model service. This is the batch inference path. Only usage tracking applies to it, not rate limits or guardrails."),
    ("burst of", "Sends parallel requests to surface HTTP 429 rate limiting before production load does."),
    ("Live probes", "All live invocation probes."),
    ("ADI applies", "On Azure Databricks, OpenAI, Google Gemini, Kimi, GLM, DeepSeek, and TypeSafe AI models are delivered through ADI Services, which must be enabled before they can be used."),
    ("ADI delivery", "Whether this model reaches Azure Databricks through ADI Services or is served natively."),
    ("ADI activation", "Proves ADI is activated for this model with a live call. Without activation, ADI models show in system.ai but fail when called."),
    ("ADI toggle", "The Integration with ADI Services toggle in the workspace's account settings. No public API exposes it."),
    ("ADI cross-geo", "Global-only ADI models, such as some Gemini models, also need cross-geography processing to be allowed. If it is off, the models are missing or unusable."),
    ("ADI TypeSafe", "TypeSafe AI models also need the TypeSafe AI Models preview turned on in the account console."),
    ("ADI HIPAA", "Using ADI Services with PHI means accepting the Databricks Business Associate Agreement unless a separate BAA is in place."),
    ("ADI OpenAI retention", "OpenAI may retain flagged content from coding and routing customers for GPT-5.5 and later models."),
    ("Custom service checks", "Checks for the schema where the customer will create its own model services."),
    ("CREATE SERVICE", "The caller can create model services in the schema. Needs USE CATALOG, USE SCHEMA, and CREATE SERVICE."),
    ("Existing model provider services", "Bring-your-own-key connections to external providers (OpenAI, Azure OpenAI, Bedrock) already in the schema."),
    ("Existing MCP services", "Governed MCP servers already registered in the schema."),
    ("Existing model services", "Custom model services already in the schema."),
    ("Inventory of ", "Listing a service type in the schema failed. This usually means a missing USE SCHEMA grant."),
    ("Temp model service round trip", "Optional end-to-end test of custom service creation."),
    ("Create temp model service", "Creates a temporary custom model service that routes to a working target model."),
    ("Query temp model service", "Calls the new custom service by its catalog.schema.name, retrying while the new grants propagate."),
    ("Delete temp model service", "Removes the temporary service. A failure here leaves it behind and must be cleaned up by hand."),
    ("Read system.ai_gateway.usage", "Reads the gateway usage system table: requests, tokens, latency, and status per model service. Readable only by account and metastore admins by default."),
    ("Non-200 traffic", "Error responses on the target models in the lookback window. Repeated 429s or 403s point to limits or access gaps."),
    ("Read system.ai_gateway.external_model_spend", "Reads estimated spend for external providers reached through model provider services."),
    ("Read system.billing.usage", "Reads billed DBUs for model serving and gateway SKUs, which is the source of truth for commit burn-down."),
    ("Probe traffic recorded", "Confirms this run's probes reached the usage table with their request tags. Ingestion can lag by 20 minutes or more, so a timeout here is a WARN, not a FAIL."),
    ("Cross-geography routing", "Account setting that lets requests be processed outside the workspace's geography. Some models in some regions need it."),
    ("Data retention opt-out", "Claude Fable models need 30-day trust and safety retention."),
    ("Service policies", "Guardrails on request and response content (PII, prompt injection, unsafe content). Beta."),
    ("Usage dashboard", "The built-in dashboard over system.ai_gateway.usage."),
    ("Client auth model", "How production clients authenticate."),
    ("MCP services visible", "Every MCP service this identity can see in system.ai and in the schemas of the target MCP services."),
    ("List MCP services", "Listing MCP services in a schema failed. This usually means a missing USE SCHEMA grant."),
    ("MCP service exists", "The target MCP service is registered and visible to this identity."),
    ("MCP source connection", "The Unity Catalog HTTP connection an external MCP service routes to. Databricks-provided MCPs in system.ai have none."),
    ("MCP tool selection", "Which tools the service exposes. An empty selection exposes every tool the server offers, which is a review item for external servers that can write."),
    ("MCP rate limits", "Requests-per-minute limits on the MCP service. Token limits do not apply to MCP services."),
    ("MCP initialize", "Opens an MCP session at /ai-gateway/mcp-services/<name> as the running identity. A 401 or 403 means no EXECUTE, or the caller has not signed in to the provider."),
    ("MCP tools/list", "Lists the tools the running identity can see through the gateway. It never calls a tool."),
    ("MCP traffic", "MCP_SERVICE rows in system.ai_gateway.usage for the lookback window, by service, JSON-RPC method, and status."),
    ("Rate limit coverage", "Whether each target has service-level and per-user limits. Without a per-user limit, one caller can use the model's whole quota and budget."),
    ("Service tags on target traffic", "Share of recent requests to each target that carried customer service tags. System tags such as ai.model_family are ignored. Budget tag filters and cost attribution by team match on service tags."),
    ("Request tags on target traffic", "Share of recent requests that carried the Databricks-Ai-Gateway-Request-Tags header, excluding this notebook's probes. Request tags attribute spend to workloads."),
    ("Spend by model service", "DBUs and list-price cost per model service from system.billing.usage, before discounts. system.billing.usage is the source of truth for billed usage."),
    ("Prompt cache reuse", "Share of input tokens read from the prompt cache. Low reuse with high volume usually means the stable part of the prompt is not at the front."),
    ("Reasoning token share", "Share of output tokens spent on reasoning. A high share is the main cost driver on reasoning models. Lower the effort setting where quality allows."),
    ("Priority tier use", "Share of requests served on the priority tier, which costs more per token. Confirm only latency-sensitive traffic uses it."),
    ("External model spend", "Estimated USD spend on external providers through model provider services, from system.ai_gateway.external_model_spend."),
    ("Token and tag usage", "Reads token, tag, and service tier columns for the target models from system.ai_gateway.usage."),
    ("Budget", "Unity Gateway budgets alert or block in near real time on pay-per-token, AI Functions, and Genie spend. No workspace API exposes them."),
]


def describe(check):
    about = next((about for prefix, about in CHECK_ABOUT if check.startswith(prefix)), "")
    if not about and check.startswith(f"{PRINCIPAL_TO_CHECK}:"):
        about = "Effective grants for the principal named in principal_to_check, direct or inherited from the catalog and schema."
    return about


RESULTS = []


def record(section, check, status, detail="", remediation="", model=None):
    RESULTS.append(
        {
            "run_id": RUN_ID,
            "run_ts": RUN_TS,
            "section": section,
            "model": model,
            "check": check,
            "status": status,
            "detail": str(detail)[:2000],
            "remediation": remediation,
            "about": describe(check),
        }
    )


def api(method, path, query=None, body=None):
    """Workspace REST call. Returns (ok, json_or_error_message)."""
    try:
        return True, w.api_client.do(method, path, query=query, body=body)
    except Exception as e:
        return False, str(e)


def gateway_post(path, body, extra_headers=None, stream=False, timeout=180):
    headers = {**w.config.authenticate(), "Content-Type": "application/json", "Databricks-Ai-Gateway-Request-Tags": REQUEST_TAGS}
    headers.update(extra_headers or {})
    return requests.post(f"{HOST}{path}", headers=headers, json=body, stream=stream, timeout=timeout)


def classify_error(status_code, text):
    t = (text or "").lower()
    if status_code == 404 and "not available in your region" in t:
        return (
            "Model not served in this workspace's region",
            "Check model region availability. If the model is marked cross-geo for this region, an account admin enables "
            "cross-geography routing. Claude Fable models also require the account not to opt out of 30-day data retention.",
        )
    if status_code == 404:
        return "Model service not found", "Confirm the fully qualified name, and that the model service exists in system.ai for this metastore."
    if status_code in (401, 403):
        return "Caller not authorized", "Grant USE CATALOG on system, USE SCHEMA on system.ai, and EXECUTE on the model service. Confirm the workspace entitlement (Workspace or Consumer access). On Azure, ADI models also fail this way until ADI Services is activated (section 5)."
    if status_code == 429:
        return "Rate limited", "Review service, user, and group rate limits on the model service, and any budget hard caps."
    if status_code == 400:
        return "Request rejected", "Check the payload against the API type, and any service policy (guardrail) attached to the service."
    return f"HTTP {status_code}", "Inspect the error text. Retry to rule out a transient provider error."


# ---------- HTML rendering ----------
# Status colors are reserved for state and always ship with an icon and a label, so color never carries meaning alone.
STATUS_STYLE = {
    "PASS": ("#0ca30c", "#ffffff", "✓", "Pass"),
    "FAIL": ("#d03b3b", "#ffffff", "✕", "Fail"),
    "WARN": ("#fab219", "#0b0b0b", "!", "Warn"),
    "MANUAL": (None, None, "☐", "Manual"),
    "INFO": (None, None, "i", "Info"),
    "SKIP": (None, None, "–", "Skip"),
}
STATUS_ORDER = ["FAIL", "WARN", "MANUAL", "PASS", "INFO", "SKIP"]

CSS = """
<style>
.ug{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px;color:var(--ink);background:var(--surface);
    border:1px solid var(--ring);border-radius:8px;padding:14px 16px;margin:4px 0}
@media (prefers-color-scheme:dark){.ug{--surface:#1a1a19;--plane:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10)}}
.ug h2{font-size:18px;margin:0 0 4px;font-weight:600}.ug h3{font-size:15px;margin:0;font-weight:600}
.ug h4{font-size:13px;margin:16px 0 6px;font-weight:600;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.ug .hdr{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.ug .sub{color:var(--ink2);font-size:12px}
.ug .b{display:inline-flex;gap:4px;align-items:center;padding:1px 8px;border-radius:999px;font-weight:600;font-size:11px;white-space:nowrap;line-height:18px}
.ug .b.o{border:1px solid var(--axis);color:var(--ink2)}
.ug table{border-collapse:collapse;width:100%;font-size:13px;color:var(--ink);font-family:inherit}
.ug code{color:var(--ink)}
.ug th{font-size:11px;color:var(--muted);font-weight:600;text-align:left;padding:4px 8px;border-bottom:1px solid var(--axis)}
.ug td{padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top;text-align:left}
.ug td.num{font-variant-numeric:tabular-nums;text-align:right}
.ug .chk{font-weight:600;color:var(--ink)}.ug .about{color:var(--muted);font-size:12px;margin-top:2px}
.ug .det{color:var(--ink2);font-size:12px;word-break:break-word}.ug .fix{font-size:12px;color:var(--ink);border-left:2px solid var(--axis);padding-left:8px}
.ug code{font-size:12px;color:var(--ink)}
.ug .tiles{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
.ug .tile{background:var(--plane);border:1px solid var(--ring);border-radius:8px;padding:8px 14px;min-width:96px}
.ug .tile .v{font-size:22px;font-weight:600}.ug .tile .l{font-size:12px;color:var(--ink2);display:flex;gap:6px;align-items:center}
.ug .banner{display:flex;gap:12px;align-items:center;padding:10px 14px;border-radius:8px;color:#ffffff;margin-bottom:6px}
.ug .banner .big{font-size:20px;font-weight:700}
.ug .mx td,.ug .mx th{text-align:center;white-space:nowrap}.ug .mx td:first-child,.ug .mx th:first-child{text-align:left}
.ug .mx td{cursor:default}
.ug details summary{cursor:pointer;color:var(--ink2);font-weight:600;margin-top:12px}
</style>"""


def esc(x):
    return html_lib.escape("" if x is None else str(x))


def badge(status, text=None):
    bg, fg, icon, label = STATUS_STYLE[status]
    text = label if text is None else text
    if bg:
        return f'<span class="b" style="background:{bg};color:{fg}">{icon} {esc(text)}</span>'
    return f'<span class="b o">{icon} {esc(text)}</span>'


def show(body):
    displayHTML(CSS + f'<div class="ug">{body}</div>')


def counts_chips(rows):
    c = {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_ORDER}
    return " ".join(badge(s, f"{c[s]} {STATUS_STYLE[s][3]}") for s in STATUS_ORDER if c[s])


def rows_table(rows, show_model=True):
    head = "<tr><th>Status</th>" + ("<th>Target</th>" if show_model else "") + "<th>Check</th><th>Evidence</th><th>Fix</th></tr>"
    body = ""
    for r in sorted(rows, key=lambda r: STATUS_ORDER.index(r["status"])):
        model = esc((r["model"] or "").removeprefix("system.ai.")) or '<span class="sub">-</span>'
        fix = f'<div class="fix">{esc(r["remediation"])}</div>' if r["remediation"] and r["status"] in ("FAIL", "WARN", "MANUAL") else ""
        detail = r["detail"]
        short = detail if len(detail) <= 260 else detail[:260] + "…"
        body += (
            f"<tr><td>{badge(r['status'])}</td>"
            + (f'<td style="white-space:nowrap">{model}</td>' if show_model else "")
            + f'<td><div class="chk">{esc(r["check"])}</div><div class="about">{esc(r["about"])}</div></td>'
            + f'<td class="det" title="{esc(detail)}">{esc(short)}</td><td>{fix}</td></tr>'
        )
    return f"<table>{head}{body}</table>"


def render_section(section, title, intro=""):
    rows = [r for r in RESULTS if r["section"] == section]
    has_model = any(r["model"] for r in rows)
    attention = [r for r in rows if r["status"] in ("FAIL", "WARN", "MANUAL")]
    rest = [r for r in rows if r["status"] not in ("FAIL", "WARN", "MANUAL")]
    body = rows_table(attention, show_model=has_model) if attention else '<div class="sub">Nothing needs attention in this section.</div>'
    if rest:
        body += f"<details><summary>{len(rest)} passing or informational checks</summary>{rows_table(rest, show_model=has_model)}</details>"
    show(
        f'<div class="hdr"><h3>{esc(title)}</h3>{counts_chips(rows)}</div>'
        + (f'<div class="sub" style="margin-bottom:8px">{esc(intro)}</div>' if intro else "")
        + body
    )


def render_df(df, title, note=""):
    cols = list(df.columns)
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = ""
    for _, row in df.iterrows():
        cells = ""
        for c in cols:
            v = row[c]
            num = isinstance(v, (int, float)) and not isinstance(v, bool)
            cells += f'<td class="num">{v:,.0f}</td>' if num and v == v else f"<td>{esc(v)}</td>"
        body += f"<tr>{cells}</tr>"
    show(f'<div class="hdr"><h3>{esc(title)}</h3></div>' + (f'<div class="sub">{esc(note)}</div>' if note else "") + f"<table><tr>{head}</tr>{body}</table>")


show(
    f'<div class="hdr"><h3>Run started</h3><span class="b o">run {RUN_ID}</span></div>'
    f'<div class="sub">{esc(HOST)}</div>'
    f'<div style="margin-top:6px">Targets: {" ".join(f"<code>{esc(m)}</code>" for m in TARGET_MODELS)}</div>'
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Platform prerequisites
# MAGIC Confirms the workspace can host Unity Gateway at all, before checking any model.
# MAGIC
# MAGIC | Check | What it does | If it fails |
# MAGIC |---|---|---|
# MAGIC | Caller identity | Records who is running the probes | n/a |
# MAGIC | Unity Catalog metastore assigned | Reads the metastore summary (name, cloud, region) | Assign a UC metastore to the workspace |
# MAGIC | Region supports Unity Gateway | Flags AWS GovCloud, where Unity Gateway is unavailable | Use a workspace in a supported region |
# MAGIC | Unity Gateway API reachable | Lists one model service in `system.ai` | Region unsupported, or gateway not enabled for the account |
# MAGIC | Workspace admin | Checks membership in the workspace `admins` group | WARN: grant checks and settings reads may be incomplete |
# MAGIC | Metastore admin | Compares the metastore owner with the caller and the caller's groups | WARN: grant checks on `system.ai` may be incomplete |
# MAGIC | Account admin | Not readable from a workspace, so it is reported as INFO | Section 8 shows whether the admin-only usage tables are readable |
# MAGIC
# MAGIC The detected cloud also decides whether section 5 (Azure ADI) runs.

# COMMAND ----------

me = w.current_user.me()
CALLER = me.user_name
CALLER_GROUPS = {g.display for g in (me.groups or []) if g.display}
record("1 Platform", "Caller identity", "INFO", f"{CALLER} (id {me.id})")
if "admins" in CALLER_GROUPS:
    record("1 Platform", "Workspace admin", "PASS", "Member of the workspace admins group")
else:
    record("1 Platform", "Workspace admin", "WARN", "Not in the workspace admins group",
           "Run as a workspace admin for full coverage, then re-run as the production identity to prove its access.")

CLOUD, REGION = "", ""
ok, summary = api("GET", "/api/2.1/unity-catalog/metastore_summary")
if ok:
    CLOUD, REGION = summary.get("cloud", "").lower(), summary.get("region", "")
    record("1 Platform", "Unity Catalog metastore assigned", "PASS", f"{summary.get('name')} ({summary.get('metastore_id')}), {CLOUD} {REGION}")
    owner = summary.get("owner", "")
    if owner and (owner == CALLER or owner in CALLER_GROUPS or owner == "account users"):
        record("1 Platform", "Metastore admin", "PASS", f"Metastore owner is {owner}")
    else:
        record("1 Platform", "Metastore admin", "WARN", f"Metastore owner is {owner or 'unknown'}, which is not the caller or one of its groups",
               "Run as a metastore admin, or grant MANAGE on system.ai, so grant checks on system.ai services are complete.")
    record("1 Platform", "Account admin", "INFO", "Not readable from a workspace. See the system.ai_gateway reads in section 8.")
    if "gov" in REGION.lower():
        record("1 Platform", "Region supports Unity Gateway", "FAIL", f"{REGION} is GovCloud", "Unity Gateway is not supported on AWS GovCloud.")
    else:
        record("1 Platform", "Region", "INFO", f"{CLOUD} {REGION}")
else:
    record("1 Platform", "Unity Catalog metastore assigned", "FAIL", summary, "Assign a Unity Catalog metastore to the workspace.")
if not CLOUD and "azuredatabricks.net" in HOST:
    CLOUD = "azure"

ok, svc_probe = api("GET", "/api/2.1/unity-catalog/model-services", query={"parent": "schemas/system.ai", "page_size": 1})
if ok:
    record("1 Platform", "Unity Gateway API reachable", "PASS", "model-services API responded for system.ai")
else:
    record("1 Platform", "Unity Gateway API reachable", "FAIL", svc_probe, "Workspace may be in an unsupported region, or Unity Gateway is not enabled for the account.")

render_section("1 Platform", "1. Platform prerequisites")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Model catalog
# MAGIC Lists every model service in each target's schema (with `view=FULL`, so config is included) and inspects each target.
# MAGIC Being visible here does not prove the model can be called. Region gates, ADI activation, and policies only show up in section 4.
# MAGIC
# MAGIC | Check | What it does | If it fails or warns |
# MAGIC |---|---|---|
# MAGIC | Model service exists | Looks up the target by its full name and lists `supported_api_types` | Not exposed for this region, or no access. Section 4 shows the gateway's own error |
# MAGIC | Live destination | Confirms at least one routing destination is not deleted | Repoint or recreate the service |
# MAGIC | Rate limits | Shows service-level QPM and TPM limits | WARN: confirm they fit production traffic |
# MAGIC | Inference table | Shows whether payload logging is on | INFO only |

# COMMAND ----------


def list_model_services(parent):
    services, token = [], None
    while True:
        q = {"parent": parent, "view": "FULL"}
        if token:
            q["page_token"] = token
        ok, resp = api("GET", "/api/2.1/unity-catalog/model-services", query=q)
        if not ok:
            raise RuntimeError(resp)
        services += resp.get("model_services", [])
        token = resp.get("next_page_token")
        if not token:
            return services


SERVICES = {}
for parent in sorted({"schemas/" + m.rsplit(".", 1)[0] for m in TARGET_MODELS}):
    try:
        for s in list_model_services(parent):
            SERVICES[s["name"].removeprefix("model-services/")] = s
    except Exception as e:
        record("2 Catalog", f"List model services in {parent}", "FAIL", e, "Caller needs USE CATALOG and USE SCHEMA on the parent.")

record("2 Catalog", "Model services visible", "INFO", f"{len(SERVICES)} services across target schemas")

AVAILABLE = []
for m in TARGET_MODELS:
    s = SERVICES.get(m)
    if not s:
        record(
            "2 Catalog", "Model service exists", "FAIL", "No model service with this name is visible",
            "The model is not exposed for this metastore's region, or the caller lacks access. Section 4 shows the gateway's own error.", model=m,
        )
        continue
    AVAILABLE.append(m)
    cfg = s.get("config", {})
    dests = cfg.get("routing", {}).get("destinations", [])
    live = [d for d in dests if not d.get("is_deleted")]
    record("2 Catalog", "Model service exists", "PASS", f"api types: {', '.join(s.get('supported_api_types', []))}", model=m)
    if not live:
        record("2 Catalog", "Live destination", "FAIL", "All destinations are deleted" if dests else "No destinations configured",
               "Recreate or repoint the model service destination.", model=m)
    else:
        record("2 Catalog", "Live destination", "PASS", "; ".join(f"{d.get('destination_type')} -> {d.get('name')} ({d.get('traffic_percentage', '-')}%)" for d in live), model=m)
    limits = cfg.get("rate_limits", [])
    if limits:
        record(
            "2 Catalog", "Rate limits", "WARN", json.dumps(limits),
            "Service-level limits throttle every caller. Confirm they match the expected production QPM and TPM.", model=m,
        )
    else:
        record("2 Catalog", "Rate limits", "INFO", "None configured on the service", model=m)
    if cfg.get("inference_table"):
        record("2 Catalog", "Inference table", "INFO", json.dumps(cfg["inference_table"]), model=m)

render_section("2 Catalog", "2. Model catalog")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Access
# MAGIC Reads **effective** Unity Catalog permissions (direct plus inherited from catalog and schema) for the privileges a caller needs:
# MAGIC `USE CATALOG` on `system`, `USE SCHEMA` on `system.ai`, and `EXECUTE` on each model service.
# MAGIC
# MAGIC Model services use definer's rights. The gateway checks the **owner's** access to the underlying model, so a caller only needs `EXECUTE` on the service itself.
# MAGIC
# MAGIC | Check | What it does | If it warns |
# MAGIC |---|---|---|
# MAGIC | `account users`: ... | Shows whether every account user can call the models (the default) | Expected in locked-down accounts. Confirm the intended teams have grants instead |
# MAGIC | `<principal>`: ... | Same check for the principal in `principal_to_check` | Run the printed `GRANT`, or confirm a group grant covers it |
# MAGIC
# MAGIC Grants inherited through group membership may not show here. The live call in section 4 is the authoritative test for the running identity.

# COMMAND ----------


def effective(securable_type, full_name, principal):
    ok, resp = api("GET", f"/api/2.1/unity-catalog/effective-permissions/{securable_type}/{full_name}", query={"principal": principal})
    if not ok:
        return None, resp
    privs = {p["privilege"] for pa in resp.get("privilege_assignments", []) for p in pa.get("privileges", [])}
    return privs, None


def check_principal(principal, label):
    checks = [("catalog", "system", {"USE_CATALOG"}), ("schema", "system.ai", {"USE_SCHEMA"})]
    checks += [("model_service", m, {"EXECUTE"}) for m in AVAILABLE]
    for stype, name, needed in checks:
        privs, err = effective(stype, name, principal)
        model = name if stype == "model_service" else None
        if privs is None:
            record("3 Access", f"{label}: {stype} {name}", "WARN", err, "Could not read effective permissions. Requires MANAGE or ownership, or run as the principal.", model=model)
        elif needed & privs or "ALL_PRIVILEGES" in privs or "MANAGE" in privs:
            record("3 Access", f"{label}: {', '.join(sorted(needed))} on {stype} {name}", "PASS", ", ".join(sorted(privs)), model=model)
        else:
            record(
                "3 Access", f"{label}: {', '.join(sorted(needed))} on {stype} {name}", "WARN",
                f"Direct or inherited grants: {', '.join(sorted(privs)) or 'none'}. Group-based grants may still apply; section 4 is the authoritative test.",
                f"GRANT {', '.join(sorted(needed)).replace('_', ' ')} ON {stype.replace('_', ' ').upper()} {name} TO `{principal}`", model=model,
            )


check_principal("account users", "account users")
if PRINCIPAL_TO_CHECK:
    check_principal(PRINCIPAL_TO_CHECK, PRINCIPAL_TO_CHECK)
else:
    record("3 Access", "Extra principal", "SKIP", "principal_to_check is blank")

render_section("3 Access", "3. Access")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Live invocation probes
# MAGIC Sends a real request to every API format the model service declares in `supported_api_types`, as the running identity.
# MAGIC Each request asks the model to reply "OK", with an output cap of 64 tokens.
# MAGIC
# MAGIC | Check | Endpoint | Who uses it |
# MAGIC |---|---|---|
# MAGIC | `mlflow/v1/chat/completions` | `/ai-gateway/mlflow/v1/chat/completions` | OpenAI-compatible clients and most frameworks. Works across providers |
# MAGIC | `mlflow/v1/responses` | `/ai-gateway/mlflow/v1/responses` | Unified Responses API, recommended for new clients |
# MAGIC | `openai/v1/responses` | `/ai-gateway/openai/v1/responses` | Native OpenAI SDK code (GPT models) |
# MAGIC | `anthropic/v1/messages` | `/ai-gateway/anthropic/v1/messages` | Native Anthropic SDK code and Claude Code |
# MAGIC | streaming | Chat Completions with `stream: true` | Chat UIs and coding agents. Reports time to first chunk |
# MAGIC | `ai_query` | `SELECT ai_query(...)` from SQL | Batch inference. Only `system.ai` services are supported, and only usage tracking applies |
# MAGIC | burst | N parallel Chat Completions | Surfaces 429 rate limiting early |
# MAGIC
# MAGIC Failures are classified by HTTP status: 404 region (data residency or cross-geo), 401/403 access or ADI not activated, 429 limits, 400 payload or guardrail.

# COMMAND ----------

PROMPT = "Reply with the single word OK."
API_PROBES = {
    "mlflow/v1/chat/completions": ("/ai-gateway/mlflow/v1/chat/completions", lambda m: {"model": m, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 64}, {}),
    "mlflow/v1/responses": ("/ai-gateway/mlflow/v1/responses", lambda m: {"model": m, "input": PROMPT, "max_output_tokens": 64}, {}),
    "openai/v1/responses": ("/ai-gateway/openai/v1/responses", lambda m: {"model": m, "input": PROMPT, "max_output_tokens": 64}, {}),
    "anthropic/v1/messages": ("/ai-gateway/anthropic/v1/messages", lambda m: {"model": m, "max_tokens": 64, "messages": [{"role": "user", "content": PROMPT}]}, {"anthropic-version": "2023-06-01"}),
}
CLIENT_SPECIFIC = {"cursor/v1/chat/completions", "codex/v1/responses"}
PROBE_ROWS = []


def probe(model, api_type):
    path, body_fn, headers = API_PROBES[api_type]
    t0 = time.time()
    try:
        r = gateway_post(path, body_fn(model), headers)
        ms = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            usage = r.json().get("usage", {})
            PROBE_ROWS.append({"model": model, "api_type": api_type, "status_code": 200, "latency_ms": ms, "error": ""})
            tin = usage.get("prompt_tokens", usage.get("input_tokens", "?"))
            tout = usage.get("completion_tokens", usage.get("output_tokens", "?"))
            record("4 Invocation", f"{api_type}", "PASS", f"{ms} ms, {tin} tokens in, {tout} out", model=model)
        else:
            PROBE_ROWS.append({"model": model, "api_type": api_type, "status_code": r.status_code, "latency_ms": ms, "error": r.text[:400]})
            what, fix = classify_error(r.status_code, r.text)
            record("4 Invocation", f"{api_type}", "FAIL", f"{what}: {r.text[:400]}", fix, model=model)
        return r.status_code
    except Exception as e:
        PROBE_ROWS.append({"model": model, "api_type": api_type, "status_code": None, "latency_ms": None, "error": str(e)[:400]})
        record("4 Invocation", f"{api_type}", "FAIL", e, "Network or client error. Check egress from the compute to the workspace host.", model=model)
        return None


def probe_stream(model):
    path, body_fn, _ = API_PROBES["mlflow/v1/chat/completions"]
    body = {**body_fn(model), "stream": True}
    t0 = time.time()
    try:
        with gateway_post(path, body, stream=True) as r:
            if r.status_code != 200:
                what, fix = classify_error(r.status_code, r.text)
                record("4 Invocation", "streaming (chat completions)", "FAIL", f"{what}: {r.text[:300]}", fix, model=model)
                return
            ttfb, chunks = None, 0
            for line in r.iter_lines():
                if line and line.startswith(b"data:"):
                    chunks += 1
                    ttfb = ttfb or int((time.time() - t0) * 1000)
            record("4 Invocation", "streaming (chat completions)", "PASS" if chunks else "WARN", f"first chunk {ttfb} ms, {chunks} SSE events", model=model)
    except Exception as e:
        record("4 Invocation", "streaming (chat completions)", "FAIL", e, model=model)


def probe_ai_query(model):
    try:
        out = spark.sql(f"SELECT ai_query('{model}', '{PROMPT}') AS r").collect()[0]["r"]
        record("4 Invocation", "ai_query (SQL batch)", "PASS", f"response: {str(out)[:80]}", model=model)
    except Exception as e:
        msg = str(e).splitlines()[0][:400]
        record("4 Invocation", "ai_query (SQL batch)", "FAIL", msg, "ai_query supports system.ai model services only. Check the region error and the caller's EXECUTE grant.", model=model)


def probe_burst(model, n):
    path, body_fn, headers = API_PROBES["mlflow/v1/chat/completions"]
    with ThreadPoolExecutor(max_workers=n) as ex:
        def one(_):
            try:
                return gateway_post(path, body_fn(model), headers).status_code
            except Exception:
                return "error"

        codes = list(ex.map(one, range(n)))
    summary = {c: codes.count(c) for c in set(codes)}
    status = "PASS" if summary.get(200) == n else ("WARN" if 429 in summary else "FAIL")
    record("4 Invocation", f"burst of {n} parallel requests", status, f"status counts {summary}", "429s indicate service, user, or group rate limits, or a budget cap." if status != "PASS" else "", model=model)


if not RUN_PROBES:
    record("4 Invocation", "Live probes", "SKIP", "run_invocation_probes = no")
else:
    for m in TARGET_MODELS:
        s = SERVICES.get(m)
        api_types = [a for a in s.get("supported_api_types", []) if a in API_PROBES] if s else []
        api_types = api_types or ["mlflow/v1/chat/completions"]
        skipped = [a for a in (s or {}).get("supported_api_types", []) if a in CLIENT_SPECIFIC]
        codes = [probe(m, a) for a in api_types]
        if skipped:
            record("4 Invocation", "Client-specific APIs", "INFO", f"{', '.join(skipped)} are exercised by Cursor and Codex clients, not probed here", model=m)
        if 200 in codes:
            probe_stream(m)
            probe_ai_query(m)
            if BURST > 0:
                probe_burst(m, BURST)
        else:
            record("4 Invocation", "streaming, ai_query, burst", "SKIP", "Skipped because the basic call failed", model=m)

render_section("4 Invocation", "4. Live invocation probes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Azure Databricks: ADI Services
# MAGIC On Azure Databricks, some models cannot be offered natively. They are delivered through **ADI Services**, an integration Databricks provides inside Azure Databricks.
# MAGIC Today that covers OpenAI GPT, Google Gemini, Moonshot Kimi, Zhipu GLM, DeepSeek, and TypeSafe AI models. Claude and the other natively served models do not go through ADI.
# MAGIC See [docs.databricks.com/adi](https://docs.databricks.com/adi) for the current model list and terms.
# MAGIC
# MAGIC **Why a live call is required:** ADI models appear in `system.ai`, and pass section 2, even when ADI is not activated. They only fail when called.
# MAGIC So this section uses the section 4 results as proof of activation.
# MAGIC
# MAGIC **Activation:** access requires ADI Services eligibility and enablement. The Azure Databricks account team confirms eligibility.
# MAGIC An admin then turns on **Integration with ADI Services** in the account settings of the workspace. Standard data residency settings apply to ADI Services.
# MAGIC
# MAGIC | Check | What it does | If it fails |
# MAGIC |---|---|---|
# MAGIC | ADI applies | Detects Azure from the metastore (or `adi_mode = force`) | n/a |
# MAGIC | ADI delivery | Classifies each target as ADI-delivered or native, by model family | n/a |
# MAGIC | ADI activation | PASS if the model answered a live call in section 4 | Activate ADI: confirm eligibility, then turn on the toggle. Global-only models also need cross-geo processing |
# MAGIC | ADI toggle, cross-geo, TypeSafe, HIPAA, OpenAI retention | MANUAL items with no public API | Confirm in workspace settings, the account console, or with the account team |

# COMMAND ----------

ADI_FAMILIES = ("gpt-", "gemini-", "databricks-gemini-", "kimi-", "glm-", "deepseek-", "typesafeai-")
NOT_ADI = ("gpt-oss-",)  # open-weight models served natively


def adi_family(model):
    """Return the ADI family prefix for a model service, using its destination model when it is a custom service."""
    names = [model.rsplit(".", 1)[-1]]
    for d in (SERVICES.get(model) or {}).get("config", {}).get("routing", {}).get("destinations", []):
        names.append(d.get("name", "").rsplit(".", 1)[-1].removeprefix("databricks-"))
    for n in names:
        if n.startswith(NOT_ADI):
            return None
        for f in ADI_FAMILIES:
            if n.startswith(f):
                return f.removeprefix("databricks-").rstrip("-")
    return None


ADI_ACTIVE = ADI_MODE == "force" or (ADI_MODE == "auto" and CLOUD == "azure")
if not ADI_ACTIVE:
    record("5 Azure ADI", "ADI applies", "SKIP", f"cloud = {CLOUD or 'unknown'}, adi_mode = {ADI_MODE}. ADI Services only exist on Azure Databricks.")
else:
    record("5 Azure ADI", "ADI applies", "INFO", f"cloud = {CLOUD}, adi_mode = {ADI_MODE}")
    adi_targets = []
    for m in TARGET_MODELS:
        fam = adi_family(m)
        record("5 Azure ADI", "ADI delivery", "INFO", f"Delivered through ADI ({fam} family)" if fam else "Served natively, ADI not required", model=m)
        if fam:
            adi_targets.append((m, fam))

    for m, fam in adi_targets:
        rows = [p for p in PROBE_ROWS if p["model"] == m]
        if not RUN_PROBES:
            record("5 Azure ADI", "ADI activation", "WARN", "Live probes are off, so activation cannot be proven", "Re-run with run_invocation_probes = yes.", model=m)
        elif any(p["status_code"] == 200 for p in rows):
            record("5 Azure ADI", "ADI activation", "PASS", "Model answered a live call, so ADI is active for it", model=m)
        else:
            err = rows[0]["error"] if rows else "no probe row"
            fix = (
                "Enable ADI Services: confirm eligibility with the Azure Databricks account team, then turn on "
                "Integration with ADI Services in the account settings of the workspace."
            )
            if fam == "gemini":
                fix += " Global-only Gemini models also need cross-geography processing allowed."
            if m not in SERVICES:
                fix += " The model service is missing entirely, which points to cross-geo or regional availability rather than the toggle."
            record("5 Azure ADI", "ADI activation", "FAIL", err, fix, model=m)

    families = {fam for _, fam in adi_targets}
    record("5 Azure ADI", "ADI toggle", "MANUAL", "Integration with ADI Services is on in the account settings of the workspace. Repeat for every workspace that will call ADI models.")
    if "gemini" in families:
        record("5 Azure ADI", "ADI cross-geo", "MANUAL", "Global-only Gemini models need cross-geography processing allowed. If it is off, they are missing or unusable.")
    if "typesafeai" in families:
        record("5 Azure ADI", "ADI TypeSafe", "MANUAL", "An account admin turns on the TypeSafe AI Models preview in the account console. TypeSafe AI's own terms apply.")
    record("5 Azure ADI", "ADI HIPAA", "MANUAL", "If PHI will flow through ADI models, using ADI Services means accepting the Databricks BAA unless a separate BAA is in place.")
    if "gpt" in families:
        record("5 Azure ADI", "ADI OpenAI retention", "MANUAL", "For GPT-5.5 and later, OpenAI may retain content its classifiers flag from coding and routing customers. Confirm whether the customer's use case falls in that category.")

render_section("5 Azure ADI", "5. Azure Databricks: ADI Services")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Custom model services, provider services, MCP services
# MAGIC Most production rollouts wrap `system.ai` models in custom model services, to get per-team grants, rate limits, budgets tied to tags, fallbacks, and inference tables.
# MAGIC This section checks the schema where those will live (`test_schema`).
# MAGIC
# MAGIC | Check | What it does | If it fails or warns |
# MAGIC |---|---|---|
# MAGIC | CREATE SERVICE on schema | Reads the caller's effective privileges on the catalog and schema | Grant USE CATALOG, USE SCHEMA, CREATE SERVICE |
# MAGIC | Existing provider / MCP / model services | Inventories what already exists in the schema | WARN means the list call failed (usually USE SCHEMA) |
# MAGIC | Create temp model service | Creates `ug_readiness_<run_id>` routing to the first target that passed section 4 | Missing CREATE SERVICE, or no EXECUTE on the destination |
# MAGIC | Query temp model service | Calls it by `catalog.schema.name`, retrying up to 2 minutes while grants propagate | Propagation delay, or the owner lost access to the destination |
# MAGIC | Delete temp model service | Removes it | Delete it by hand using the name in the detail |

# COMMAND ----------

if not TEST_SCHEMA:
    record("6 Custom services", "Custom service checks", "SKIP", "test_schema is blank")
else:
    cat = TEST_SCHEMA.split(".")[0]
    privs_c, err_c = effective("catalog", cat, CALLER)
    privs_s, err_s = effective("schema", TEST_SCHEMA, CALLER)
    have = (privs_c or set()) | (privs_s or set())
    need = {"USE_CATALOG", "USE_SCHEMA", "CREATE_SERVICE"}
    if "ALL_PRIVILEGES" in have or "MANAGE" in have or need <= have:
        record("6 Custom services", f"CREATE SERVICE on {TEST_SCHEMA}", "PASS", ", ".join(sorted(have)))
    else:
        record(
            "6 Custom services", f"CREATE SERVICE on {TEST_SCHEMA}", "WARN", f"Visible privileges: {', '.join(sorted(have)) or 'none'} {err_c or ''} {err_s or ''}",
            f"GRANT USE CATALOG ON CATALOG {cat}, and USE SCHEMA, CREATE SERVICE ON SCHEMA {TEST_SCHEMA} to the team that owns custom services.",
        )

    for kind, path in [("model provider services", "model-provider-services"), ("MCP services", "mcp-services"), ("model services", "model-services")]:
        ok, resp = api("GET", f"/api/2.1/unity-catalog/{path}", query={"parent": f"schemas/{TEST_SCHEMA}"})
        if ok:
            key = path.replace("-", "_")
            names = [x["name"] for x in resp.get(key, [])]
            record("6 Custom services", f"Existing {kind} in {TEST_SCHEMA}", "INFO", f"{len(names)}: {', '.join(names)[:500]}")
        else:
            record("6 Custom services", f"Inventory of {kind} in {TEST_SCHEMA}", "WARN", resp)

    if CREATE_TEST_SERVICE:
        working = [p["model"] for p in PROBE_ROWS if p["status_code"] == 200 and p["model"] in SERVICES]
        if not working:
            record("6 Custom services", "Temp model service round trip", "SKIP", "No target model passed section 4 to use as a destination")
        else:
            dest = working[0]
            dest_cfg = next(d for d in SERVICES[dest]["config"]["routing"]["destinations"] if not d.get("is_deleted"))
            svc_id = f"ug_readiness_{RUN_ID}"
            fqn = f"{TEST_SCHEMA}.{svc_id}"
            body = {
                "comment": f"Temporary Unity Gateway readiness check {RUN_ID}. Safe to delete.",
                "config": {"routing": {"destinations": [{
                    "name": "primary",
                    "destination_type": dest_cfg["destination_type"],
                    "pay_per_token_config": dest_cfg["pay_per_token_config"],
                    "traffic_percentage": 100,
                }]}},
            }
            ok, resp = api("POST", "/api/2.1/unity-catalog/model-services", query={"parent": f"schemas/{TEST_SCHEMA}", "model_service_id": svc_id}, body=body)
            if not ok:
                record("6 Custom services", "Create temp model service", "FAIL", resp, "Requires CREATE SERVICE on the schema and EXECUTE on the destination model.")
            else:
                record("6 Custom services", "Create temp model service", "PASS", f"{fqn} -> {dest}")
                try:
                    code, text = None, ""
                    for attempt in range(12):
                        path, body_fn, _ = API_PROBES["mlflow/v1/chat/completions"]
                        r = gateway_post(path, body_fn(fqn))
                        code, text = r.status_code, r.text
                        if code == 200:
                            break
                        time.sleep(10)
                    if code == 200:
                        record("6 Custom services", "Query temp model service", "PASS", f"after {attempt + 1} attempt(s)")
                    else:
                        what, fix = classify_error(code, text)
                        record("6 Custom services", "Query temp model service", "FAIL", f"{what}: {text[:300]}", fix)
                finally:
                    ok_d, resp_d = api("DELETE", f"/api/2.1/unity-catalog/model-services/{fqn}")
                    record("6 Custom services", "Delete temp model service", "PASS" if ok_d else "FAIL", fqn if ok_d else resp_d, "" if ok_d else f"Delete {fqn} manually.")
    else:
        record("6 Custom services", "Temp model service round trip", "SKIP", "create_test_service = no")

render_section("6 Custom services", "6. Custom model services")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. MCP services
# MAGIC Unity Gateway governs MCP servers the same way it governs models: each one is a Unity Catalog securable (an **MCP service**) with grants, tool selection, rate limits, and usage tracking.
# MAGIC Agents and coding tools reach them at `https://<workspace>/ai-gateway/mcp-services/<catalog>.<schema>.<service>`.
# MAGIC
# MAGIC | Check | What it does | If it fails or warns |
# MAGIC |---|---|---|
# MAGIC | MCP services visible | Lists MCP services in `system.ai` and in each target's schema | WARN means the list call failed (usually USE SCHEMA) |
# MAGIC | MCP service exists | Looks up each `target_mcp_services` entry | Register it, or grant USE CATALOG and USE SCHEMA on its parents |
# MAGIC | MCP source connection | Shows the HTTP connection an external MCP routes to | INFO only |
# MAGIC | MCP tool selection | Shows which tools are exposed | WARN for external MCPs that expose every tool |
# MAGIC | MCP rate limits | Shows requests-per-minute limits | INFO when none are set |
# MAGIC | `account users` / principal grants | Effective `EXECUTE` on the MCP service | Grant EXECUTE plus USE CATALOG and USE SCHEMA. End users do not need USE CONNECTION |
# MAGIC | MCP initialize, MCP tools/list | Opens a session and lists tools as the running identity. Never calls a tool | FAIL on a gateway 401/403 (no EXECUTE). WARN when the upstream provider rejects the user's credential, which each user fixes by signing in to the provider |
# MAGIC | MCP traffic | Recent MCP_SERVICE rows in `system.ai_gateway.usage` | FAIL means the usage table is not readable by this identity |

# COMMAND ----------

MCP_PROTOCOL_VERSION = "2025-06-18"


def list_mcp_services(parent):
    out, token = [], None
    while True:
        q = {"parent": parent, "view": "FULL"}
        if token:
            q["page_token"] = token
        ok, resp = api("GET", "/api/2.1/unity-catalog/mcp-services", query=q)
        if not ok:
            raise RuntimeError(resp)
        out += resp.get("mcp_services", [])
        token = resp.get("next_page_token")
        if not token:
            return out


def mcp_post(fqn, body, session_id=None):
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return gateway_post(f"/ai-gateway/mcp-services/{fqn}", body, headers, timeout=60)


def mcp_message(r):
    """Return the JSON-RPC message from a JSON or server-sent-events response."""
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if "result" in msg or "error" in msg:
                    return msg
        return {}
    try:
        return r.json()
    except ValueError:
        return {}


def mcp_fix(status_code, text):
    t = (text or "").lower()
    if status_code == 200 and any(k in t for k in ("http 401", "http 403")):
        return "The upstream provider rejected this user's credential. The user signs in to the provider for this MCP service in Catalog Explorer, then re-runs."
    if status_code in (401, 403) and any(k in t for k in ("sign in", "login", "oauth", "credential", "authorize")):
        return "The provider needs this user to sign in. Open the MCP service in Catalog Explorer and sign in, then re-run."
    if status_code in (401, 403):
        return "Grant EXECUTE on the MCP service, plus USE CATALOG and USE SCHEMA on its parents."
    if status_code == 404:
        return "Confirm the fully qualified name and that the MCP service is registered."
    if status_code == 429:
        return "An MCP rate limit was hit. Review the service's requests-per-minute limits."
    return "Inspect the error text. External servers can also fail behind the gateway."


def probe_mcp(fqn):
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "ug-readiness", "version": "1"}},
    }
    t0 = time.time()
    try:
        r = mcp_post(fqn, init)
    except Exception as e:
        record("7 MCP", "MCP initialize", "FAIL", e, "Network or client error. Check egress from the compute to the workspace host.", model=fqn)
        return
    msg = mcp_message(r)
    if r.status_code != 200 or "result" not in msg:
        text = json.dumps(msg.get("error")) if "error" in msg else r.text[:400]
        needs_sign_in = r.status_code == 200 and any(k in text.lower() for k in ("http 401", "http 403"))
        record("7 MCP", "MCP initialize", "WARN" if needs_sign_in else "FAIL", f"HTTP {r.status_code}: {text}", mcp_fix(r.status_code, text), model=fqn)
        return
    server = msg.get("result", {}).get("serverInfo", {})
    record("7 MCP", "MCP initialize", "PASS", f"{int((time.time() - t0) * 1000)} ms, server {server.get('name', '?')} {server.get('version', '')}".strip(), model=fqn)
    session_id = r.headers.get("mcp-session-id")
    try:
        mcp_post(fqn, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
        r = mcp_post(fqn, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session_id)
    except Exception as e:
        record("7 MCP", "MCP tools/list", "FAIL", e, model=fqn)
        return
    msg = mcp_message(r)
    if r.status_code != 200 or "result" not in msg:
        text = json.dumps(msg.get("error")) if "error" in msg else r.text[:400]
        needs_sign_in = r.status_code == 200 and any(k in text.lower() for k in ("http 401", "http 403"))
        record("7 MCP", "MCP tools/list", "WARN" if needs_sign_in else "FAIL", f"HTTP {r.status_code}: {text}", mcp_fix(r.status_code, text), model=fqn)
        return
    tools = [t.get("name", "?") for t in msg.get("result", {}).get("tools", [])]
    status = "PASS" if tools else "WARN"
    fix = "" if tools else "The server returned no tools. Check the service's tool selection and the caller's access to the underlying resources."
    record("7 MCP", "MCP tools/list", status, f"{len(tools)} tool(s): {', '.join(tools[:12])}{' …' if len(tools) > 12 else ''}", fix, model=fqn)


MCP_SERVICES = {}
mcp_parents = {"schemas/system.ai"} | {"schemas/" + m.rsplit(".", 1)[0] for m in TARGET_MCP}
for parent in sorted(mcp_parents):
    try:
        for x in list_mcp_services(parent):
            MCP_SERVICES[x["name"].removeprefix("mcp-services/")] = x
    except Exception as e:
        record("7 MCP", f"List MCP services in {parent}", "WARN", e, "Grant USE CATALOG and USE SCHEMA on the parent to see its MCP services.")
record("7 MCP", "MCP services visible", "INFO", f"{len(MCP_SERVICES)}: {', '.join(sorted(MCP_SERVICES))[:600]}")

if not TARGET_MCP:
    record("7 MCP", "MCP service exists", "SKIP", "target_mcp_services is blank")

for fqn in TARGET_MCP:
    x = MCP_SERVICES.get(fqn)
    if not x:
        record("7 MCP", "MCP service exists", "FAIL", "No MCP service with this name is visible",
               "Register the MCP service, or grant USE CATALOG and USE SCHEMA on its catalog and schema.", model=fqn)
        continue
    record("7 MCP", "MCP service exists", "PASS", x.get("comment", "")[:200] or "registered", model=fqn)
    cfg = x.get("config", {}) or {}
    conn = (cfg.get("source_connection") or {}).get("name")
    is_system = fqn.startswith("system.ai.")
    if conn:
        record("7 MCP", "MCP source connection", "INFO", conn, model=fqn)
    selectors = cfg.get("include_tool_selectors") or []
    if selectors:
        record("7 MCP", "MCP tool selection", "PASS", json.dumps(selectors)[:300], model=fqn)
    elif is_system:
        record("7 MCP", "MCP tool selection", "INFO", "All tools exposed (Databricks-provided MCP)", model=fqn)
    else:
        record("7 MCP", "MCP tool selection", "WARN", "All tools exposed",
               "Set config.include_tool_selectors to the tools agents need, especially for servers with write tools.", model=fqn)
    limits = cfg.get("rate_limits") or []
    record("7 MCP", "MCP rate limits", "INFO", json.dumps(limits)[:300] if limits else "None configured", model=fqn)
    for principal in ["account users"] + ([PRINCIPAL_TO_CHECK] if PRINCIPAL_TO_CHECK else []):
        privs, err = effective("mcp_service", fqn, principal)
        check = f"{principal}: EXECUTE on mcp_service {fqn}"
        if privs is None:
            record("7 MCP", check, "WARN", err, "Could not read effective permissions. Requires MANAGE or ownership.", model=fqn)
        elif {"EXECUTE", "ALL_PRIVILEGES", "MANAGE"} & privs:
            record("7 MCP", check, "PASS", ", ".join(sorted(privs)), model=fqn)
        else:
            record("7 MCP", check, "WARN", f"Direct or inherited grants: {', '.join(sorted(privs)) or 'none'}",
                   f"GRANT EXECUTE ON MCP SERVICE {fqn} TO `{principal}`, plus USE CATALOG and USE SCHEMA on its parents.", model=fqn)
    if RUN_PROBES:
        probe_mcp(fqn)
    else:
        record("7 MCP", "MCP initialize", "SKIP", "run_invocation_probes = no", model=fqn)

try:
    mcp_usage = spark.sql(f"""
        SELECT service_name, mcp_metadata.json_rpc_method AS method, status_code, count(*) AS requests
        FROM system.ai_gateway.usage
        WHERE service_type = 'MCP_SERVICE' AND event_time >= current_timestamp() - INTERVAL {LOOKBACK_DAYS} DAYS
        GROUP BY ALL ORDER BY requests DESC LIMIT 25""").toPandas()
    record("7 MCP", f"MCP traffic, last {LOOKBACK_DAYS}d", "INFO", f"{int(mcp_usage.requests.sum()) if len(mcp_usage) else 0} request(s) across {mcp_usage.service_name.nunique() if len(mcp_usage) else 0} service(s)")
    if len(mcp_usage):
        render_df(mcp_usage, f"MCP traffic, last {LOOKBACK_DAYS} days", "From system.ai_gateway.usage where service_type = MCP_SERVICE.")
except Exception as e:
    record("7 MCP", f"MCP traffic, last {LOOKBACK_DAYS}d", "FAIL", str(e).splitlines()[0][:400],
           "By default only account and metastore admins can read system.ai_gateway tables.")

render_section("7 MCP", "7. MCP services")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Observability: usage, spend, and billing tables
# MAGIC A large commit needs burn-down tracking from day one. This section confirms the tables that track it are readable, and that gateway traffic lands in them.
# MAGIC
# MAGIC | Check | What it does | If it fails or warns |
# MAGIC |---|---|---|
# MAGIC | Read `system.ai_gateway.usage` | Requests, tokens, p50 and p95 latency, and status per target in the lookback window | Only account and metastore admins can read it by default. Grant SELECT to the platform team |
# MAGIC | Non-200 traffic | Error status codes on the targets in the window | Look into repeated 403, 429, or 400 before scaling |
# MAGIC | Read `system.ai_gateway.external_model_spend` | Estimated external provider spend, updated hourly | Same grant as above |
# MAGIC | Read `system.billing.usage` | Billed DBUs for serving and gateway SKUs, the source of truth for commit burn-down | Grant SELECT on the billing schema |
# MAGIC | Probe traffic recorded | Polls for rows tagged with this run's `readiness_run_id` | WARN on timeout. Ingestion can lag 20 minutes or more. Re-run the printed query later |

# COMMAND ----------


def sql_check(label, query, remediation):
    try:
        rows = spark.sql(query).limit(50).toPandas()
        record("8 Observability", label, "PASS", f"{len(rows)} row(s)")
        return rows
    except Exception as e:
        record("8 Observability", label, "FAIL", str(e).splitlines()[0][:400], remediation)
        return None


GRANT_FIX = "By default only account and metastore admins can read system.ai_gateway tables. Grant USE SCHEMA and SELECT on the schema to the platform team."
usage_recent = sql_check(
    "Read system.ai_gateway.usage",
    f"""SELECT endpoint_name, status_code, count(*) AS requests, sum(total_tokens) AS total_tokens,
               percentile(latency_ms, 0.5) AS p50_ms, percentile(latency_ms, 0.95) AS p95_ms
        FROM system.ai_gateway.usage
        WHERE event_time >= current_timestamp() - INTERVAL {LOOKBACK_DAYS} DAYS
          AND endpoint_name IN ({', '.join(repr(m) for m in TARGET_MODELS)})
        GROUP BY ALL ORDER BY endpoint_name, status_code""",
    GRANT_FIX,
)
if usage_recent is not None and len(usage_recent):
    render_df(usage_recent, f"Gateway traffic on target models, last {LOOKBACK_DAYS} days", "From system.ai_gateway.usage. Latency in milliseconds.")
    errs = usage_recent[usage_recent.status_code != 200]
    if len(errs):
        record("8 Observability", f"Non-200 traffic on targets, last {LOOKBACK_DAYS}d", "WARN", "; ".join(f"{e.endpoint_name.removeprefix('system.ai.')}: HTTP {e.status_code} x{e.requests}" for e in errs.itertuples()), "Review 4xx and 429 patterns before scaling traffic.")

sql_check("Read system.ai_gateway.external_model_spend", "SELECT * FROM system.ai_gateway.external_model_spend LIMIT 1", GRANT_FIX)
sql_check(
    "Read system.billing.usage (serving and gateway SKUs)",
    f"""SELECT sku_name, sum(usage_quantity) AS dbus FROM system.billing.usage
        WHERE usage_date >= current_date() - INTERVAL {LOOKBACK_DAYS} DAYS
          AND (sku_name ILIKE '%GATEWAY%' OR sku_name ILIKE '%SERVING%')
        GROUP BY ALL ORDER BY dbus DESC""",
    "Grant SELECT on system.billing.usage to the team that tracks commit burn-down.",
)

if RUN_PROBES and USAGE_WAIT_S > 0 and any(p["status_code"] == 200 for p in PROBE_ROWS):
    deadline, seen = time.time() + USAGE_WAIT_S, 0
    while time.time() < deadline:
        try:
            seen = spark.sql(
                f"SELECT count(*) AS n FROM system.ai_gateway.usage WHERE event_time >= current_timestamp() - INTERVAL 1 DAY AND request_tags['readiness_run_id'] = '{RUN_ID}'"
            ).collect()[0]["n"]
        except Exception as e:
            seen = None
            record("8 Observability", "Probe traffic recorded in usage table", "FAIL", str(e).splitlines()[0][:400],
                   "By default only account and metastore admins can read system.ai_gateway tables.")
            break
        if seen:
            break
        time.sleep(20)
    if seen is None:
        pass
    elif seen:
        record("8 Observability", "Probe traffic recorded in usage table", "PASS", f"{seen} row(s) tagged readiness_run_id={RUN_ID}, request tags propagate")
    else:
        record("8 Observability", "Probe traffic recorded in usage table", "WARN", f"No rows after {USAGE_WAIT_S}s. Ingestion can lag. Re-run the query in remediation later.",
               f"SELECT * FROM system.ai_gateway.usage WHERE request_tags['readiness_run_id'] = '{RUN_ID}'")

render_section("8 Observability", "8. Observability")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Cost controls
# MAGIC Checks whether spend on the target models can be capped, attributed, and reduced. It reads service configs and the usage and billing tables from section 8.
# MAGIC Recent traffic from this notebook (`tool=ug_readiness`) is excluded from the traffic-based checks.
# MAGIC
# MAGIC | Check | What it does | If it warns |
# MAGIC |---|---|---|
# MAGIC | Rate limit coverage | Reads service-level and per-user limits on each target | Front production traffic with a custom model service that sets a user default limit and group limits |
# MAGIC | Service tags on target traffic | Share of recent requests carrying customer service tags. System `ai.*` tags are ignored | Tag services by team or project. Budget tag filters match service tags, not request tags |
# MAGIC | Request tags on target traffic | Share of recent requests carrying `Databricks-Ai-Gateway-Request-Tags` | Have clients send request tags to attribute spend to workloads |
# MAGIC | Spend by model service | DBUs and list-price cost per model service from `system.billing.usage` | FAIL means the billing tables are not readable |
# MAGIC | Prompt cache reuse | Cache-read input tokens against total input tokens | WARN when high volume shows no cache reads. Put stable content (system prompt, tools, reference docs) first |
# MAGIC | Reasoning token share | Reasoning tokens as a share of output tokens | WARN above 80% on high volume. Lower the effort setting where quality allows |
# MAGIC | Priority tier use | Share of requests served on the priority tier | INFO. Confirm only latency-sensitive traffic pays for it |
# MAGIC | External model spend | Estimated USD spend through model provider services | INFO |
# MAGIC | Budget items | Unity Gateway budgets, per-user thresholds, tag scope | MANUAL. Budgets live in the account console |
# MAGIC
# MAGIC The cache and reasoning thresholds are heuristics for spotting the largest cost levers. They are not limits.

# COMMAND ----------

for m in AVAILABLE:
    keys = [str(l.get("key", "")) for l in (SERVICES[m].get("config", {}).get("rate_limits") or [])]
    has_service = any(k.endswith("_SERVICE") for k in keys)
    has_user = any("USER" in k for k in keys)
    custom = [k for k in keys if not k.endswith("_SERVICE") and "USER" not in k]
    detail = f"service: {'yes' if has_service else 'no'}, per-user: {'yes' if has_user else 'no'}, custom: {len(custom)}"
    if has_user:
        record("9 Cost controls", "Rate limit coverage", "PASS", detail, model=m)
    else:
        record("9 Cost controls", "Rate limit coverage", "WARN", detail,
               "Front production traffic with a custom model service that sets a user default limit, and group limits for heavy users (max 20 limits, 5 group limits per service).", model=m)

target_list = ", ".join(repr(m) for m in TARGET_MODELS)
try:
    eff = spark.sql(f"""
        SELECT endpoint_name,
               count(*) AS requests,
               avg(CASE WHEN coalesce(size(map_filter(service_tags, (k, v) -> NOT startswith(k, 'ai.'))), 0) > 0 THEN 1 ELSE 0 END) AS service_tagged,
               avg(CASE WHEN coalesce(size(request_tags), 0) > 0 THEN 1 ELSE 0 END) AS request_tagged,
               coalesce(sum(input_tokens), 0) AS input_tokens,
               coalesce(sum(token_details.cache_read_input_tokens), 0) AS cache_read_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(token_details.output_reasoning_tokens), 0) AS reasoning_tokens,
               avg(CASE WHEN lower(invocation_metadata.service_tier) = 'priority' THEN 1 ELSE 0 END) AS priority_share
        FROM system.ai_gateway.usage
        WHERE event_time >= current_timestamp() - INTERVAL {LOOKBACK_DAYS} DAYS
          AND endpoint_name IN ({target_list})
          AND coalesce(request_tags['tool'], '') <> 'ug_readiness'
        GROUP BY endpoint_name""").toPandas()
except Exception as e:
    eff = None
    record("9 Cost controls", "Token and tag usage on targets", "FAIL", str(e).splitlines()[0][:400],
           "By default only account and metastore admins can read system.ai_gateway tables.")

if eff is not None:
    seen = set(eff.endpoint_name)
    for m in TARGET_MODELS:
        if m not in seen:
            record("9 Cost controls", "Service tags on target traffic", "SKIP", f"No traffic in the last {LOOKBACK_DAYS} days besides this notebook's probes", model=m)
    for _, r in eff.iterrows():
        m, n = r.endpoint_name, int(r.requests)
        st, rt = float(r.service_tagged), float(r.request_tagged)
        record("9 Cost controls", "Service tags on target traffic", "PASS" if st >= 0.9 else "WARN", f"{st:.0%} of {n:,} requests",
               "" if st >= 0.9 else "Tag the services this traffic uses (team, project, cost center), so budgets and cost reports can scope it.", model=m)
        record("9 Cost controls", "Request tags on target traffic", "PASS" if rt >= 0.5 else "WARN", f"{rt:.0%} of {n:,} requests",
               "" if rt >= 0.5 else "Have clients send the Databricks-Ai-Gateway-Request-Tags header to attribute spend to workloads.", model=m)
        it, cr = int(r.input_tokens), int(r.cache_read_tokens)
        if it >= 1_000_000 and cr == 0:
            record("9 Cost controls", "Prompt cache reuse", "WARN", f"0 cache-read tokens over {it:,} input tokens",
                   "Put stable content (system prompt, tool definitions, reference docs) first and variable content last. With traffic splitting, keep a session on one destination.", model=m)
        else:
            record("9 Cost controls", "Prompt cache reuse", "INFO", f"{cr:,} cache-read tokens, {it:,} input tokens", model=m)
        ot, rs = int(r.output_tokens), int(r.reasoning_tokens)
        share = rs / ot if ot else 0
        if ot >= 100_000 and share > 0.8:
            record("9 Cost controls", "Reasoning token share", "WARN", f"{share:.0%} of {ot:,} output tokens",
                   "Set reasoning effort explicitly per task type and test quality at a lower setting.", model=m)
        else:
            record("9 Cost controls", "Reasoning token share", "INFO", f"{share:.0%} of {ot:,} output tokens", model=m)
        record("9 Cost controls", "Priority tier use", "INFO", f"{float(r.priority_share):.0%} of requests", model=m)
    if len(eff):
        view = eff.assign(
            service_tagged=(eff.service_tagged * 100).round(0),
            request_tagged=(eff.request_tagged * 100).round(0),
            priority_share=(eff.priority_share * 100).round(0),
        ).rename(columns={"service_tagged": "service_tagged_pct", "request_tagged": "request_tagged_pct", "priority_share": "priority_pct"})
        render_df(view, f"Cost signals on target models, last {LOOKBACK_DAYS} days", "From system.ai_gateway.usage, excluding this notebook's probes.")

try:
    spend = spark.sql(f"""
        SELECT u.usage_metadata.ai_gateway.endpoint_name AS model_service,
               u.usage_metadata.ai_gateway.destination_model AS destination_model,
               sum(u.usage_quantity) AS dbus,
               sum(u.usage_quantity * lp.pricing.default) AS list_cost,
               coalesce(sum(CASE WHEN lp.pricing.default IS NULL THEN u.usage_quantity END), 0) AS unpriced_dbus
        FROM system.billing.usage u
        LEFT JOIN system.billing.list_prices lp
          ON u.sku_name = lp.sku_name AND u.cloud = lp.cloud AND u.usage_unit = lp.usage_unit
         AND u.usage_start_time >= lp.price_start_time
         AND (lp.price_end_time IS NULL OR u.usage_start_time < lp.price_end_time)
        WHERE u.billing_origin_product = 'MODEL_SERVING'
          AND u.usage_metadata.ai_gateway.endpoint_name IS NOT NULL
          AND u.usage_date >= current_date() - INTERVAL {LOOKBACK_DAYS} DAYS
        GROUP BY ALL ORDER BY dbus DESC LIMIT 25""").toPandas()
    spend[["dbus", "list_cost", "unpriced_dbus"]] = spend[["dbus", "list_cost", "unpriced_dbus"]].astype(float)
    total = float(spend.list_cost.fillna(0).sum()) if len(spend) else 0.0
    record("9 Cost controls", f"Spend by model service, last {LOOKBACK_DAYS}d", "INFO",
           f"{len(spend)} service(s), {float(spend.dbus.sum()) if len(spend) else 0:,.1f} DBUs, {total:,.2f} at list price before discounts"
           + (f", {float(spend.unpriced_dbus.sum()):,.1f} DBUs had no list price match" if len(spend) and spend.unpriced_dbus.sum() else ""))
    if len(spend):
        render_df(spend, f"Unity Gateway spend by model service, last {LOOKBACK_DAYS} days", "From system.billing.usage joined to system.billing.list_prices. List price, before discounts.")
except Exception as e:
    record("9 Cost controls", f"Spend by model service, last {LOOKBACK_DAYS}d", "FAIL", str(e).splitlines()[0][:400],
           "Grant SELECT on system.billing.usage and system.billing.list_prices to the team that tracks spend.")

try:
    ext = spark.sql(f"""
        SELECT usage_metadata.endpoint_name AS model_provider_service, sum(usage_quantity) AS usd
        FROM system.ai_gateway.external_model_spend
        WHERE usage_date >= current_date() - INTERVAL {LOOKBACK_DAYS} DAYS
        GROUP BY ALL ORDER BY usd DESC LIMIT 10""").toPandas()
    ext["usd"] = ext["usd"].astype(float)
    record("9 Cost controls", f"External model spend, last {LOOKBACK_DAYS}d", "INFO",
           f"{float(ext.usd.sum()) if len(ext) else 0:,.2f} USD estimated across {len(ext)} provider service(s)")
except Exception as e:
    record("9 Cost controls", f"External model spend, last {LOOKBACK_DAYS}d", "FAIL", str(e).splitlines()[0][:400],
           "By default only account and metastore admins can read system.ai_gateway tables.")

for name, how in [
    ("Budget for Unity Gateway", "Account console > Usage > Budgets: create a budget with Unity Gateway as the resource type, a shared threshold that matches the spend plan, and alert or block actions."),
    ("Budget per-user thresholds", "Add a per-user threshold with Block usage, and per-user overrides for power users or service principals (max 4 shared thresholds, 100 overrides per budget)."),
    ("Budget scope", "Budget tag filters match service tags, not request tags. Budgets do not cover provisioned throughput or traffic sent straight to serving endpoints. Enforcement is approximate, not an absolute cap."),
]:
    record("9 Cost controls", name, "MANUAL", how)

render_section("9 Cost controls", "9. Cost controls")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. Manual checks and scorecard
# MAGIC These account-level controls have no workspace API, so they are listed as MANUAL for the admin to confirm.
# MAGIC The verdict is **READY** only when no check FAILs. WARN and MANUAL rows still need review before the commit decision.

# COMMAND ----------

MANUAL = [
    ("Cross-geography routing", "Account console > Settings. Required where a target model is marked cross-geo for this region. Confirm it meets the customer's data residency policy."),
    ("Data retention opt-out", "Claude Fable models need 30-day trust and safety retention. Accounts that opted out of retention cannot use them."),
    ("Service policies (Beta)", "Workspace admin opts into Unity Gateway Service Policies on the Previews page if PII, prompt-injection, or content guardrails are required."),
    ("Usage dashboard", "AI Gateway > Usage. Import the built-in usage dashboard for spend and adoption tracking."),
    ("Client auth model", "Production callers should use service principals with OAuth M2M, not PATs. auth_mode in system.ai_gateway.usage shows what clients use today."),
]
for name, how in MANUAL:
    record("10 Manual", name, "MANUAL", how)

results = pd.DataFrame(RESULTS)
results["_o"] = results.status.map(STATUS_ORDER.index)
results["_s"] = results.section.str.split(" ").str[0].astype(int)
results = results.sort_values(["_o", "_s"]).drop(columns=["_o", "_s"])
blocking = [r for r in RESULTS if r["status"] == "FAIL"]
verdict = "NOT READY" if blocking else ("READY" if RUN_PROBES else "NOT VERIFIED")

# Model-level checks collapse into short matrix columns, in reading order.
MATRIX_COLUMNS = [
    ("Exists", lambda r: r["check"] == "Model service exists"),
    ("Destination", lambda r: r["check"] == "Live destination"),
    ("Rate limits", lambda r: r["check"] == "Rate limits"),
    ("EXECUTE", lambda r: r["section"] == "3 Access"),
    ("Chat", lambda r: r["check"] == "mlflow/v1/chat/completions"),
    ("Responses", lambda r: r["check"] == "mlflow/v1/responses"),
    ("OpenAI native", lambda r: r["check"] == "openai/v1/responses"),
    ("Anthropic native", lambda r: r["check"] == "anthropic/v1/messages"),
    ("Streaming", lambda r: r["check"].startswith("streaming")),
    ("ai_query", lambda r: r["check"].startswith("ai_query")),
    ("Burst", lambda r: r["check"].startswith("burst of")),
    ("ADI", lambda r: r["check"] == "ADI activation"),
]


def matrix_html():
    cols = [c for c, pred in MATRIX_COLUMNS if any(r["model"] and pred(r) for r in RESULTS)]
    head = "<tr><th>Model</th><th>Overall</th>" + "".join(f"<th>{esc(c)}</th>" for c in cols) + "</tr>"
    body = ""
    for m in TARGET_MODELS:
        mrows = [r for r in RESULTS if r["model"] == m]
        worst = min((r["status"] for r in mrows if r["status"] in ("FAIL", "WARN", "PASS")), key=STATUS_ORDER.index, default="SKIP")
        cells = ""
        for c, pred in MATRIX_COLUMNS:
            if c not in cols:
                continue
            hits = [r for r in mrows if pred(r)]
            if not hits:
                cells += '<td><span class="sub">·</span></td>'
                continue
            st = min((r["status"] for r in hits), key=STATUS_ORDER.index)
            tip = " | ".join(f"{r['check']}: {r['detail']}" for r in hits)
            cells += f'<td title="{esc(tip)}">{badge(st, "")}</td>'
        body += f'<tr><td><code>{esc(m.removeprefix("system.ai."))}</code></td><td>{badge(worst)}</td>{cells}</tr>'
    return f'<table class="mx">{head}{body}</table>'


def list_block(rows, empty):
    if not rows:
        return f'<div class="sub">{esc(empty)}</div>'
    return rows_table(rows)


c = {s: sum(1 for r in RESULTS if r["status"] == s) for s in STATUS_ORDER}
banner_bg = {"READY": "#0ca30c", "NOT VERIFIED": "#fab219"}.get(verdict, "#d03b3b")
banner_icon = {"READY": "✓", "NOT VERIFIED": "!"}.get(verdict, "✕")
summary_line = {
    "READY": "No blocking failures. Review the warnings and manual items before the commit decision.",
    "NOT VERIFIED": "No blocking failures, but live probes were off, so access is not proven. Re-run with run_invocation_probes = yes.",
}.get(verdict, f"{len(blocking)} blocking failure(s). Fix them, then re-run.")
tiles = "".join(
    f'<div class="tile"><div class="v">{c[s]}</div><div class="l">{badge(s, "")} {STATUS_STYLE[s][3]}</div></div>'
    for s in ["FAIL", "WARN", "MANUAL", "PASS"]
)
show(
    f'<div class="banner" style="background:{banner_bg};color:{'#0b0b0b' if verdict == 'NOT VERIFIED' else '#ffffff'}"><span class="big">{banner_icon} {verdict}</span><span>{esc(summary_line)}</span></div>'
    f'<div class="sub">{esc(HOST)} · {esc(CLOUD)} {esc(REGION)} · run as {esc(CALLER)} · run {RUN_ID} · {RUN_TS:%Y-%m-%d %H:%M} UTC</div>'
    f'<div class="tiles">{tiles}</div>'
    f"<h4>Model readiness</h4>{matrix_html()}"
    '<div class="sub" style="margin-top:4px">Hover a cell for the evidence. · means the check does not apply to that model.</div>'
    f"<h4>Blockers</h4>{list_block(blocking, 'None.')}"
    f"<h4>Needs review</h4>{list_block([r for r in RESULTS if r['status'] == 'WARN'], 'None.')}"
    f"<h4>Manual checklist</h4>{list_block([r for r in RESULTS if r['status'] == 'MANUAL'], 'None.')}"
    f"<details><summary>All {len(RESULTS)} checks</summary>{rows_table(RESULTS)}</details>"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Raw results
# MAGIC The same rows as a sortable, filterable, downloadable table. `detail` is the evidence, `remediation` is the fix, `about` explains the check.

# COMMAND ----------

display(results[["status", "section", "model", "check", "detail", "remediation", "about", "run_id", "run_ts"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Optional: persist results
# MAGIC Appends this run to `results_table` so readiness can be compared across runs, for example before and after ADI activation or a grant change.

# COMMAND ----------

if RESULTS_TABLE:
    spark.createDataFrame(results.astype({"model": "string", "detail": "string"})).write.mode("append").option("mergeSchema", "true").saveAsTable(RESULTS_TABLE)
    show(f'{badge("PASS", "Saved")} Appended {len(results)} rows to <code>{esc(RESULTS_TABLE)}</code> (run {RUN_ID})')
