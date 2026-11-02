#!/usr/bin/env python3
"""Mock backend for the Unity Gateway Migration Toolkit, for documentation screenshots and UI work.

Serves app/frontend/static and answers the /api/* routes the React app calls, with the response shapes of
app/backend/main.py. All data is fictional (example.com people, a made-up workspace host). Standard library only.

Runs and results live in memory and complete immediately. POST /__mock/reset restores the seeded state:
{"state": "full"} (default) or {"state": "empty"} for the first-run page. Auth, Databricks calls and exports are not
modelled (export routes answer 501).

Usage:
    python3 mock_server.py [--host 127.0.0.1] [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
STATIC = (HERE / ".." / ".." / "app" / "frontend" / "static").resolve()

# ---------------------------------------------------------------------------
# Fictional identity, workspace and config (nothing here is a real customer, employee or host)
# ---------------------------------------------------------------------------

HOST = "https://adb-1234567890123456.7.azuredatabricks.net"
WS_ID = "1234567890123456"
ME = "maria.lopez@example.com"  # signed-in operator
ANALYST = "analyst@example.com"
SP_ID = "0f6d1c2a-1111-2222-3333-444455556666"
RESULTS_SCHEMA = "main.ug_migration"
TARGET_CATALOG = "ai_gateway"
TARGET_SCHEMA = "migrated"
TARGET = f"{TARGET_CATALOG}.{TARGET_SCHEMA}"
SECRET_SCHEMA = "main.ug_secrets"
WAREHOUSE_ID = "5f2c9a1b7d3e4f60"
DEADLINE = "2027-03-30"
DEADLINE_AS_OF = "2026-11-01"
TOOLKIT = "0.10.0"

# Anchor for every relative timestamp: the server start time, to the minute.
T0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)
LATEST_SNAPSHOT = T0 - timedelta(hours=2)


def sql_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def ago(**kw) -> str:
    return sql_ts(T0 - timedelta(**kw))


def svc(name: str) -> str:
    return f"{TARGET}.{name}"


# ---------------------------------------------------------------------------
# Snapshot fixtures (account overview). Endpoint requests are the 30-day window of the latest snapshot.
# ---------------------------------------------------------------------------

WORKSPACES = [
    dict(id=WS_ID, name="lakeside-core-prod", status="RUNNING", v3=18400, signals="VECTOR_SEARCH,APPS"),
    dict(id="2222222222222222", name="retail-analytics-prod", status="RUNNING", v3=21300, signals="AI_FUNCTIONS"),
    dict(id="3333333333333333", name="claims-ml-dev", status="RUNNING", v3=1050, signals="AGENT_BRICKS"),
    dict(id="4444444444444444", name="support-bot-prod", status="RUNNING", v3=14900, signals=""),
    dict(id="5555555555555555", name="finance-reporting", status="RUNNING", v3=2210, signals=""),
    dict(id="6666666666666666", name="sandbox-team-a", status="RUNNING", v3=0, signals=""),
    dict(id="7777777777777777", name="marketing-lab", status="STOPPED", v3=0, signals=""),
]
WS_NAME = {w["id"]: w["name"] for w in WORKSPACES}


class Ep:
    """One endpoint in one workspace, latest snapshot. cust/plat/coding split the requests by caller class."""

    def __init__(self, ws, name, kind, req, requesters, throttled, last_h, traffic="ok", cust=0, plat=0, coding=0):
        self.ws, self.name, self.kind, self.req = ws, name, kind, req
        self.requesters, self.throttled, self.last_h, self.traffic = requesters, throttled, last_h, traffic
        self.cust, self.plat, self.coding = cust, plat, coding


ENDPOINTS = [
    Ep(WS_ID, "chat-gpt4o-proxy", "external_model", 1930, 2, 42, 3, cust=1930),
    Ep(WS_ID, "claims-summary-pt", "pt", 1740, 2, 0, 5, cust=1740, coding=560),
    Ep(WS_ID, "support-bot-openai", "external_model", 310, 1, 0, 26, cust=310),
    Ep(WS_ID, "legacy-summarizer-openai", "external_model", 0, 0, 0, 620),
    Ep(WS_ID, "databricks-meta-llama-3-3-70b-instruct", "system_ppt", 2240, 1, 0, 1, plat=2240),
    Ep(WS_ID, "databricks-gpt-5-mini", "system_ppt", 1020, 1, 0, 14, cust=1020),
    Ep(WS_ID, "databricks-bge-large-en", "system_ppt", 0, 0, 0, None),
    Ep(WS_ID, "databricks-claude-sonnet-4-5", "v2_workspace_endpoint", 380, 1, 0, 6, cust=380),
    Ep(WS_ID, "fraud-scorer-custom", "custom_model", 0, 0, 0, 96),
    Ep("2222222222222222", "faq-bot-openai", "external_model", 2310, 3, 18, 2, cust=2310),
    Ep("2222222222222222", "docs-embed-v1", "v1_foundation", 640, 1, 0, 4, plat=640),
    Ep("3333333333333333", "claims-classify-v2", "v2_workspace_endpoint", 2760, 2, 0, 1, cust=2760),
    Ep("4444444444444444", "legacy-helper-openai", "external_model", 0, 0, 0, 1500),
    Ep("5555555555555555", "fin-report-pt", "pt", 0, 0, 0, None, traffic="unknown"),
    Ep("5555555555555555", "fin-summary-openai", "external_model", 0, 0, 0, None, traffic="unknown"),
]

# Fictional token sizing: about 900 input and output tokens per request. The v2 endpoint below is shown as failing
# (HTTP 501 and errors on most calls, so v2 is off for this workspace): 372 of its 380 requests failed.
TOKENS_PER_REQUEST = 900
V2_FAILED_SHARE = {"databricks-claude-sonnet-4-5": 0.98}

WAVE_ORDER = ["v2 traffic", "2: high volume", "1: small", "1: cleanup", "0: traffic unknown",
              "0: no legacy traffic", "no legacy endpoints (custom ML only)", "no endpoint data", "not running", "unknown"]


def _last_seen(h):
    return None if h is None else ago(hours=h)


def _wave(ws, eps, v2, legacy):
    if ws["status"] != "RUNNING":
        return "not running"
    if v2 > 0:
        return "v2 traffic"
    if legacy >= 10000:
        return "2: high volume"
    if legacy > 0:
        return "1: small"
    if any(e.traffic == "unknown" for e in eps):
        return "0: traffic unknown"
    if any(e.kind != "custom_model" for e in eps):
        return "0: no legacy traffic"
    if not eps:
        return "no endpoint data"
    return "no legacy endpoints (custom ML only)"


def build_snapshot(f_legacy: float, f_v3: float):
    """Workspace views for one snapshot. The factors scale older snapshots down (legacy) and up (Unity Gateway)."""
    views = []
    for ws in WORKSPACES:
        eps = [e for e in ENDPOINTS if e.ws == ws["id"]]
        legacy_eps = [e for e in eps if e.kind != "custom_model"]
        v1 = sum(round(e.req * f_legacy) for e in legacy_eps if e.kind != "v2_workspace_endpoint")
        v2 = sum(round(e.req * f_legacy) for e in legacy_eps if e.kind == "v2_workspace_endpoint")
        legacy = v1 + v2
        v2_tokens = sum(round(e.req * f_legacy) * TOKENS_PER_REQUEST for e in legacy_eps if e.kind == "v2_workspace_endpoint")
        legacy_tokens = sum(round(e.req * f_legacy) * TOKENS_PER_REQUEST for e in legacy_eps)
        v2_failed = sum(round(round(e.req * f_legacy) * V2_FAILED_SHARE.get(e.name, 0)) for e in legacy_eps
                        if e.kind == "v2_workspace_endpoint")
        v3 = round(ws["v3"] * f_v3)
        wave = _wave(ws, eps, v2, legacy)
        seen = [e.last_h for e in eps if e.last_h is not None]
        last_seen = _last_seen(min(seen)) if seen else None
        running = ws["status"] == "RUNNING"
        views.append({
            "workspace_id": ws["id"], "workspace_name": ws["name"], "status": ws["status"], "wave": wave,
            "readiness": None, "ready": False, "scan_readiness": None, "scan_run_id": None,
            "legacy_endpoints": len(legacy_eps), "custom_legacy_endpoints": sum(1 for e in eps if e.kind in ("external_model", "pt")),
            "active_legacy_endpoints": sum(1 for e in legacy_eps if round(e.req * f_legacy) > 0),
            "unknown_traffic_endpoints": sum(1 for e in eps if e.traffic == "unknown"),
            "v1_requests": v1, "v2_requests": v2, "legacy_requests": legacy, "legacy_throttled": sum(e.throttled for e in eps),
            "legacy_tokens": legacy_tokens, "v2_tokens": v2_tokens, "v2_failed": v2_failed,
            "v2_failing": v2 >= 10 and 100 * v2_failed >= 95 * v2,
            "deleted_endpoint_requests": 0, "v3_requests": v3,
            "v3_share": round(v3 / (v3 + legacy), 3) if (v3 + legacy) else None,
            "last_seen": last_seen, "config_signals": [s for s in ws["signals"].split(",") if s],
            "customer_requests": sum(round(e.cust * f_legacy) for e in eps),
            "platform_requests": sum(round(e.plat * f_legacy) for e in eps),
            "coding_agent_requests": sum(round(e.coding * f_legacy) for e in eps),
            "_running": running,
        })
    # Current workspace: its latest passing scan decides nothing here (the scan is BLOCKED), so no readiness text.
    return views


def _readiness_text(v):
    """Mirrors _workspace_view: wave-0 workspaces say what they still need."""
    if not v["wave"].startswith("0"):
        return None, False
    if v["wave"] == "0: traffic unknown":
        return "Traffic unknown; scan required", False
    return "No recent traffic; scan required", False


def snapshot_overview():
    """Latest snapshot plus trend (four weekly points, oldest first). Same shape as /api/overview."""
    snaps = [LATEST_SNAPSHOT - timedelta(days=7 * k) for k in (3, 2, 1, 0)]
    factors = [(2.8, 0.5), (2.0, 0.66), (1.4, 0.82), (1.0, 1.0)]
    trend = []
    latest_views = None
    for snap, (fl, fv) in zip(snaps, factors):
        views = build_snapshot(fl, fv)
        running = [v for v in views if v["_running"]]
        trend.append({
            "snapshot_time": snap.strftime("%Y-%m-%dT%H:%M:%SZ"), "snapshot_epoch": int(snap.timestamp()),
            "window_days": 30, "workspaces": len(running),
            "no_traffic": sum(1 for v in running if v["wave"] == "0: no legacy traffic"),
            "legacy_requests": sum(v["legacy_requests"] for v in views),
            "v3_requests": sum(v["v3_requests"] for v in views),
            "active_legacy_endpoints": sum(v["active_legacy_endpoints"] for v in views),
        })
        latest_views = views
    views = latest_views
    running = [v for v in views if v["_running"]]
    legacy = sum(v["legacy_requests"] for v in running)
    v3 = sum(v["v3_requests"] for v in running)
    counts: dict[str, int] = {}
    for v in running:
        counts[v["wave"]] = counts.get(v["wave"], 0) + 1
    waves = [{"wave": k, "workspaces": counts[k]} for k in WAVE_ORDER if counts.get(k)]
    for v in views:
        v.pop("_running", None)
    views.sort(key=lambda v: (-(v["legacy_requests"] or 0), -(v["custom_legacy_endpoints"] or 0), str(v["workspace_id"])))
    # Scan readiness: only the scanned workspace has one (its latest scan is BLOCKED, so it is not ready).
    for v in views:
        if v["workspace_id"] == WS_ID:
            v["scan_readiness"] = "BLOCKED"
            v["scan_run_id"] = SCAN_IDS["latest"]
        else:
            v["readiness"], v["ready"] = _readiness_text(v)
    kpis = {
        "running_workspaces": len(running),
        "no_traffic": counts.get("0: no legacy traffic", 0),
        "traffic_unknown": counts.get("0: traffic unknown", 0),
        "no_endpoint_data": counts.get("no endpoint data", 0),
        "ready": 0,
        "legacy_requests": legacy, "v3_requests": v3,
        "v3_share": round(v3 / (v3 + legacy), 3) if (v3 + legacy) else None,
        "active_legacy_endpoints": sum(v["active_legacy_endpoints"] for v in running),
        "live_legacy_endpoints": sum(v["legacy_endpoints"] for v in running),
        "deleted_endpoint_requests": 0,
        "customer_requests": sum(v["customer_requests"] for v in running),
        "platform_requests": sum(v["platform_requests"] for v in running),
        "coding_agent_requests": sum(v["coding_agent_requests"] for v in running),
        "legacy_tokens": sum(v["legacy_tokens"] for v in running),
        "v2_failing_workspaces": sum(1 for v in running if v["v2_failing"]),
    }
    eps = []
    for e in ENDPOINTS:
        last = _last_seen(e.last_h)
        eps.append({
            "workspace_id": e.ws, "workspace_name": WS_NAME[e.ws], "endpoint_name": e.name, "kind": e.kind,
            "live": e.kind != "deleted_or_unknown", "requests": e.req, "requesters": e.requesters,
            "throttled": e.throttled, "last_request": last, "last_seen": last, "traffic_status": e.traffic,
            "customer_requests": e.cust, "platform_requests": e.plat, "coding_agent_requests": e.coding,
            "legacy_tokens": e.req * TOKENS_PER_REQUEST,
        })
    top = [e for e in eps if e["requests"] or e["last_seen"]]
    top.sort(key=lambda e: str(e["last_seen"] or ""), reverse=True)
    top.sort(key=lambda e: -e["requests"])
    return {
        "snapshot_time": snaps[-1].strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": 30, "window_assumed": False,
        "run_id": "c3a9e0d4-5b7f-4e21-9a6d-8f2b1e7c4d10", "running_snapshot": None, "trend": trend,
        "kpis": kpis, "deadline": deadline_block(), "waves": waves, "workspaces": views,
        "endpoints": top[:100], "endpoints_limit": 100, "endpoints_total": len(eps),
    }


def deadline_block():
    today = datetime.now(timezone.utc).date()
    return {
        "date": DEADLINE, "days_left": (date.fromisoformat(DEADLINE) - today).days, "as_of": DEADLINE_AS_OF,
        "what": "Legacy serving endpoints (v1 and v2) stop serving. Custom model and feature serving aren't affected; "
                "Government cloud workspaces can have different dates: ask your account team.",
    }


def empty_overview():
    return {
        "snapshot_time": None, "window_days": None, "window_assumed": False, "run_id": None,
        "running_snapshot": None, "trend": [], "kpis": {}, "deadline": deadline_block(), "waves": [],
        "workspaces": [], "endpoints": [], "endpoints_limit": 100, "endpoints_total": 0,
    }


# ---------------------------------------------------------------------------
# Scan fixtures: one plan, callers, providers and code references shared by the scans of this workspace.
# ---------------------------------------------------------------------------

PLAN = [
    dict(legacy_endpoint="chat-gpt4o-proxy", kind="external_model", action="create_model_service",
         target_service=svc("chat-gpt4o-proxy"), target_status="missing", requests_window=1930,
         needs_human=["BLOCKS APPLY: guardrails: PII filter and topic block are not migrated; re-create them as service policies"]),
    dict(legacy_endpoint="claims-summary-pt", kind="pt", action="create_model_service",
         target_service=svc("claims-summary-pt"), target_status="missing", requests_window=1740,
         needs_human=["Provisioned Throughput: confirm the throughput units before creating the service"]),
    dict(legacy_endpoint="support-bot-openai", kind="external_model", action="create_model_service",
         target_service=svc("support-bot-openai"), target_status="missing", requests_window=310, needs_human=[]),
    dict(legacy_endpoint="legacy-summarizer-openai", kind="external_model", action="create_model_service",
         target_service=svc("legacy-summarizer-openai"), target_status="exists", requests_window=0, needs_human=[]),
    dict(legacy_endpoint="databricks-claude-sonnet-4-5", kind="v2_workspace_endpoint", action="use_system_ai",
         target_service="system.ai.claude_sonnet_4_5", target_status="exists", requests_window=380,
         needs_human=["AI Gateway v2 workspace-bound endpoint: keep the /ai-gateway/ route and change the model to system.ai.claude_sonnet_4_5"]),
    dict(legacy_endpoint="databricks-meta-llama-3-3-70b-instruct", kind="system_ppt", action="use_system_ai",
         target_service="system.ai.llama_3_3_70b_instruct", target_status="exists", requests_window=2240, needs_human=[]),
    dict(legacy_endpoint="databricks-gpt-5-mini", kind="system_ppt", action="use_system_ai",
         target_service="system.ai.gpt_5_mini", target_status="exists", requests_window=1020, needs_human=[]),
    dict(legacy_endpoint="databricks-bge-large-en", kind="system_ppt", action="use_system_ai",
         target_service="system.ai.bge_large_en", target_status="exists", requests_window=0, needs_human=[]),
]
for _p in PLAN:  # tokens next to requests (fictional sizing, see TOKENS_PER_REQUEST)
    _p["tokens_window"] = _p["requests_window"] * TOKENS_PER_REQUEST
PLAN_BY_NAME = {p["legacy_endpoint"]: p for p in PLAN}
PROVIDER_OF = {"chat-gpt4o-proxy": "openai-chat", "support-bot-openai": "openai-support",
               "legacy-summarizer-openai": "openai-support"}
PROVIDERS = [
    dict(provider_service=svc("openai-chat"), provider="OpenAI", models=["gpt-4o-mini"], secrets=["openai/api-key"]),
    dict(provider_service=svc("openai-support"), provider="OpenAI", models=["gpt-4o-mini"], secrets=["openai/api-key"]),
]

CALLER_ROWS = [
    # endpoint, requester, requester_name, caller_class, user agent, requests (30 days), hours since last request, code
    ("chat-gpt4o-proxy", ANALYST, "llm_sdk", "openai-python/1.52.0", 1930, 3, ["/Repos/team-ml/support-bot/app/chat.py"]),
    ("claims-summary-pt", SP_ID, "service_principal", "", 1180, 9, []),
    ("claims-summary-pt", ME, "coding_agent", "claude-code/1.0.85", 560, 5, [f"/Users/{ME}/claims/summarize.py"]),
    ("databricks-meta-llama-3-3-70b-instruct", "genie-runtime", "platform", "", 2240, 1, []),
    ("databricks-gpt-5-mini", "nightly-batch-runner", "no_client_info", "", 1020, 14, []),
    ("databricks-claude-sonnet-4-5", "ticket-triage-app", "http", "python-requests/2.32.3", 380, 6,
     ["/Repos/team-ml/ticket-triage/router.py"]),
    ("support-bot-openai", ANALYST, "sdk", "databricks-sdk-py/0.38.0", 310, 26, ["/Repos/team-ml/support-bot/app/main.py"]),
]
CALLERS = [
    dict(endpoint_name=ep, requester=who, requester_name=who, caller_class=cls, user_agent=ua, requests=req,
         last_request=ago(hours=h), last_h=h, linked_code=code)
    for ep, who, cls, ua, req, h, code in CALLER_ROWS
]

BLOCKERS = [
    dict(type="legacy_traffic", label="Callers still use a legacy endpoint", item="claims-summary-pt",
         detail="1,740 requests in 30 days from 2 callers (a service principal and a coding agent)",
         action=f"move these callers to {svc('claims-summary-pt')}, then scan again",
         caller_classes={"service_principal": 1, "coding_agent": 1}, user_agents=["claude-code/1.0.85"]),
    dict(type="pay_per_token_call", label="Code calls a Databricks pay-per-token endpoint",
         item="databricks-gpt-5-mini", detail="3 call sites: see CODE_FIXES.md",
         action="switch the calls to system.ai.gpt_5_mini (see CODE_FIXES.md), then re-scan"),
    dict(type="v2_workspace_call", label="Code calls a v2 workspace endpoint", item="databricks-claude-sonnet-4-5",
         detail="1 call site: see CODE_FIXES.md",
         action="set the model to system.ai.claude_sonnet_4_5 and keep the /ai-gateway/ route (see CODE_FIXES.md), then re-scan"),
]
WARNINGS = [
    dict(type="no_traffic_in_window", label="No requests in the window and usage tracking is off", item="1 endpoint",
         detail="no requests in the window and usage tracking off: legacy-summarizer-openai",
         action="confirm with the owners that no infrequent job (monthly, quarterly) calls them"),
    dict(type="confirm_infrequent_callers", label="Pay-per-token endpoint has no traffic and no known callers",
         item="databricks-bge-large-en",
         detail="no requests in 30 days and no code found that calls it: a job that runs monthly or quarterly would not show up in the window",
         action="confirm infrequent callers (monthly or quarterly jobs) with the owners before enforcing"),
    dict(type="pt_wrapper_on_legacy_endpoint", label="Unity Gateway wrapper routes to a legacy PT endpoint",
         item="claims-summary-pt",
         detail="the Unity Gateway service routes to serving-endpoints/claims-summary-pt, a legacy endpoint that retires (March 30, 2027)",
         action="point callers at the Unity Gateway service; the legacy endpoint retires on March 30, 2027"),
]
CLOSE_CANDIDATES = [
    dict(endpoint="legacy-summarizer-openai", target_ready=True,
         undo_body={"rate_limits": [{"calls": 60, "key": "endpoint", "renewal_period": "minute"}],
                    "usage_tracking_config": {"enabled": False}},
         ai_gateway_body={"rate_limits": [{"calls": 0, "key": "endpoint", "renewal_period": "minute"}],
                          "usage_tracking_config": {"enabled": False}}),
]

# Code references: (asset_type, asset, line, pattern, legacy endpoint, suggestion, line_text, fixed_line)
_FIX = [
    ("file", "/Repos/team-ml/support-bot/app/chat.py", 42, "chat_completions", "chat-gpt4o-proxy",
     "call the model service through the /ai-gateway/ route",
     'response = client.chat.completions.create(model="chat-gpt4o-proxy", messages=msgs)',
     f'response = client.chat.completions.create(model="{svc("chat-gpt4o-proxy")}", messages=msgs)'),
    ("file", "/Repos/team-ml/support-bot/app/chat.py", 58, "serving_endpoint_name", "chat-gpt4o-proxy",
     "use the model service name", 'ENDPOINT = "chat-gpt4o-proxy"', f'ENDPOINT = "{svc("chat-gpt4o-proxy")}"'),
    ("file", "/Repos/team-ml/support-bot/app/main.py", 17, "serving_endpoint_name", "support-bot-openai",
     "use the model service name", 'SUPPORT_MODEL = "support-bot-openai"', f'SUPPORT_MODEL = "{svc("support-bot-openai")}"'),
    ("file", "/Repos/team-ml/ticket-triage/router.py", 18, "v2_gateway_model", "databricks-claude-sonnet-4-5",
     "keep the /ai-gateway/ route", 'MODEL = "databricks-claude-sonnet-4-5"', 'MODEL = "system.ai.claude_sonnet_4_5"'),
    ("notebook", f"/Users/{ME}/claims/summarize", 27, "serving_endpoint_name", "claims-summary-pt",
     "use the model service name", 'endpoint = "claims-summary-pt"', f'endpoint = "{svc("claims-summary-pt")}"'),
    ("notebook", f"/Users/{ME}/claims/summarize", 61, "mlflow_deployments_predict", "claims-summary-pt",
     "manual: the MLflow deployments client calls /serving-endpoints/claims-summary-pt/invocations, which has no "
     "Unity Gateway form, so use the OpenAI client on <workspace>/ai-gateway/mlflow/v1 with "
     f"model='{svc('claims-summary-pt')}' and an ai-gateway scoped token",
     'client.predict(endpoint="claims-summary-pt", inputs=batch)', None),
    ("notebook", f"/Users/{ANALYST}/eval/score-answers", 12, "ai_query", "databricks-gpt-5-mini",
     "ai_query calls a pay-per-token endpoint: call system.ai.gpt_5_mini through a model service", None, None),
    ("job_sql", "/Repos/team-ml/nightly/score_answers.sql", 8, "ai_query", "databricks-gpt-5-mini",
     "ai_query calls a pay-per-token endpoint: call system.ai.gpt_5_mini through a model service", None, None),
]
_OTHER = [
    ("file", "/Repos/team-ml/support-bot/app/config.yaml", 4, "serving_endpoints_url", "support-bot-openai",
     "move the URL to the model service route"),
    ("notebook", f"/Users/{ANALYST}/eval/rerank", 33, "ChatDatabricks", "databricks-meta-llama-3-3-70b-instruct",
     "use system.ai.llama_3_3_70b_instruct through a model service"),
    ("app", "/Workspace/Apps/faq-widget/app.yaml", 9, "app config value", "faq-bot-openai",
     "App config value uses a legacy endpoint: change the value to the model service"),
    ("dashboard", "dashboard: Weekly claims review", None, "ai_query", "databricks-gpt-5-mini",
     "ai_query calls a pay-per-token endpoint"),
]


def _refs():
    rows = []
    for at, asset, line, pattern, ep, sug, lt, ft in _FIX:
        rows.append(dict(asset_type=at, asset=asset, line=line, pattern=pattern, match=pattern, legacy_endpoint=ep,
                         suggestion=sug, line_text=lt, fixed_line=ft, fix_confidence="review" if ft else None,
                         also_in=[]))
    for at, asset, line, pattern, ep, sug in _OTHER:
        rows.append(dict(asset_type=at, asset=asset, line=line, pattern=pattern, match=pattern, legacy_endpoint=ep,
                         suggestion=sug, line_text=None, fixed_line=None, fix_confidence=None, also_in=[]))
    for i in range(12):
        rows.append(dict(asset_type="notebook", asset=f"/Users/{ANALYST}/eval/notebook-{i + 1:02d}", line=5 + i * 3,
                         pattern="serving_endpoint_route_url", match="/serving-endpoints/", legacy_endpoint="databricks-gpt-5-mini",
                         suggestion="route through the model service", line_text=None, fixed_line=None,
                         fix_confidence=None, also_in=[]))
    return rows


REFS = _refs()
FIX_COUNT = sum(1 for r in REFS if r["fixed_line"] and r["fixed_line"] != r["line_text"])


def build_readiness(status: str) -> dict:
    blockers = [dict(b) for b in BLOCKERS] if status == "BLOCKED" else []
    return {"status": status, "blockers": blockers, "warnings": [dict(w) for w in WARNINGS],
            "coverage_gaps": {}, "coverage": {"plan": "ok", "callers": "ok", "code": "ok", "traffic": "ok"},
            "notes": {}, "rate_limit_zero_candidates": [dict(c) for c in CLOSE_CANDIDATES], "traffic_status": "ok"}


# ---------------------------------------------------------------------------
# Run state (in memory). Records: scans, applies (apply, dry run, execute, rollback and cut-over operations).
# ---------------------------------------------------------------------------

STATE_LOCK = threading.Lock()
STATE: dict = {}
SCAN_IDS = {"latest": "9b1e4c7a-2d3f-4a5b-8c6d-7e8f9a0b1c2d", "previous": "3e7a1f2b-6c5d-4e8f-9a0b-1c2d3e4f5a6b"}
DRY_RUN_TRACK_ID = "0c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f"


def _job_id():
    STATE["seq"] += 1
    return str(700000000 + STATE["seq"])


def _new_id():
    return str(uuid.uuid4())


def _summary(items):
    counts: dict[str, int] = {}
    for it in items:
        if it.get("action") in ("would_create", "created", "exists", "smoke_ok", "would_delete", "deleted",
                                "would_pause", "paused", "would_enable_tracking", "tracking_enabled",
                                "already_enabled", "would_test", "test_ok", "test_failed", "resumed", "would_resume"):
            counts[it["action"]] = counts.get(it["action"], 0) + 1
    return json.dumps(counts, sort_keys=True)


def seed(empty: bool):
    STATE.clear()
    STATE.update({"seq": 100, "scans": [], "applies": [], "jobs": {}, "empty": empty})
    if empty:
        return
    s_prev_fin = T0 - timedelta(days=9)
    s_prev_start = s_prev_fin - timedelta(minutes=9)
    s_latest_fin = T0 - timedelta(hours=52)
    s_latest_start = s_latest_fin - timedelta(minutes=8)
    prev = {
        "run_id": SCAN_IDS["previous"], "job_run_id": _job_id(), "requested_by": ANALYST, "workspace_url": HOST,
        "workspace_id": WS_ID, "status": "SUCCEEDED", "readiness": "READY_WITH_WARNINGS", "endpoints": len(PLAN),
        "client_references": len(REFS), "traffic_status": "ok", "days": 30, "target_catalog": TARGET_CATALOG,
        "target_schema": TARGET_SCHEMA, "scan_roots": "", "toolkit_version": TOOLKIT, "error": None,
        "started_at": sql_ts(s_prev_start), "finished_at": sql_ts(s_prev_fin),
        "_detail": build_readiness("READY_WITH_WARNINGS"),
    }
    latest = {
        "run_id": SCAN_IDS["latest"], "job_run_id": _job_id(), "requested_by": ME, "workspace_url": HOST,
        "workspace_id": WS_ID, "status": "SUCCEEDED", "readiness": "BLOCKED", "endpoints": len(PLAN),
        "client_references": len(REFS), "traffic_status": "ok", "days": 30, "target_catalog": TARGET_CATALOG,
        "target_schema": TARGET_SCHEMA, "scan_roots": "", "toolkit_version": TOOLKIT, "error": None,
        "started_at": sql_ts(s_latest_start), "finished_at": sql_ts(s_latest_fin),
        "_detail": build_readiness("BLOCKED"),
    }
    STATE["scans"] = [latest, prev]
    # Earlier apply history: a dry run and an execute on the older scan created the legacy-summarizer service.
    STATE["applies"] = []
    dry_prev = _apply_record("dry_run", SCAN_IDS["previous"], ["legacy-summarizer-openai"], ANALYST,
                             s_prev_fin + timedelta(hours=3), None, items=[
                                 dict(type="model_provider_service", name=svc("openai-support"), action="would_create"),
                                 dict(type="model_service", name=svc("legacy-summarizer-openai"), action="would_create")])
    exe_prev = _apply_record("execute", SCAN_IDS["previous"], ["legacy-summarizer-openai"], ANALYST,
                             s_prev_fin + timedelta(hours=3, minutes=14), None, dry_run_id=dry_prev["apply_id"], items=[
                                 dict(type="model_provider_service", name=svc("openai-support"), action="created"),
                                 dict(type="model_service", name=svc("legacy-summarizer-openai"), action="created"),
                                 dict(type="model_service", name=svc("legacy-summarizer-openai"), action="smoke_ok", state="ready")])
    track = _cutover_record("enable_tracking", "dry_run", ["chat-gpt4o-proxy", "claims-summary-pt", "legacy-summarizer-openai"],
                            ME, T0 - timedelta(hours=50), SCAN_IDS["latest"], apply_id=DRY_RUN_TRACK_ID,
                            items=[
                                dict(type="serving_endpoint", name="chat-gpt4o-proxy", action="would_enable_tracking", kind="external_model"),
                                dict(type="serving_endpoint", name="claims-summary-pt", action="already_enabled", kind="pt"),
                                dict(type="serving_endpoint", name="legacy-summarizer-openai", action="would_enable_tracking", kind="external_model"),
                            ])
    test_run = _cutover_record("test_call", "execute", [], ME, T0 - timedelta(hours=28), SCAN_IDS["latest"],
                               services=[svc("legacy-summarizer-openai")], api_type="mlflow/v1/chat/completions",
                               items=[dict(type="model_service", name=svc("legacy-summarizer-openai"), action="test_ok",
                                           http_status=200, latency_ms=412, reply_excerpt="ok",
                                           request_id="7a1d0c59-3b8e-4f62-a4c1-9e5d2b7f0a13")])
    STATE["applies"] = [track, test_run, exe_prev, dry_prev]  # newest first; the list is sorted below
    STATE["applies"].sort(key=lambda a: a["started_at"], reverse=True)


def _apply_items(scan_id, endpoints, execute, smoke=True):
    items = []
    seen_providers = set()
    for name in endpoints:
        p = PLAN_BY_NAME.get(name)
        if not p or p["action"] != "create_model_service":
            continue
        prov = PROVIDER_OF.get(name)
        if prov and prov not in seen_providers:
            seen_providers.add(prov)
            ps = svc(prov)
            if prov == "openai-support":
                items.append(dict(type="model_provider_service", name=ps, action="exists"))
            else:
                items.append(dict(type="model_provider_service", name=ps, action="created" if execute else "would_create"))
        if p["target_status"] == "exists":
            items.append(dict(type="model_service", name=p["target_service"], action="exists"))
        else:
            items.append(dict(type="model_service", name=p["target_service"],
                              action="created" if execute else "would_create"))
            if execute and smoke:
                items.append(dict(type="model_service", name=p["target_service"], action="smoke_ok", state="ready"))
    return items


def _apply_record(mode, scan_id, endpoints, who, started_dt, operation, dry_run_id=None, apply_id=None, items=None):
    ep = sorted(endpoints)
    if items is None:
        items = _apply_items(scan_id, ep, execute=(mode == "execute"))
    return {
        "apply_id": apply_id or _new_id(), "job_run_id": _job_id(), "requested_by": who, "scan_run_id": scan_id,
        "mode": mode, "endpoints": ",".join(ep), "target_catalog": TARGET_CATALOG, "target_schema": TARGET_SCHEMA,
        "rollback_of": None, "status": "SUCCEEDED", "summary": _summary(items), "error": None,
        "started_at": sql_ts(started_dt), "finished_at": sql_ts(started_dt + timedelta(seconds=41)),
        "operation": operation, "services": None, "api_type": None, "_items": items, "_dry_run_id": dry_run_id,
        "_resumed": False,
    }


def _cutover_record(operation, mode, endpoints, who, started_dt, scan_id, services=None, api_type=None, items=None,
                    apply_id=None, rollback_of=None):
    rec = _apply_record(mode, scan_id, endpoints, who, started_dt, operation, apply_id=apply_id, items=items or [])
    rec["services"] = ",".join(services) if services else None
    rec["api_type"] = api_type
    rec["rollback_of"] = rollback_of
    return rec


def _latest_succeeded_scan():
    done = [s for s in STATE["scans"] if s["status"] == "SUCCEEDED"]
    return done[0] if done else None


def _scan_by_id(run_id):
    return next((s for s in STATE["scans"] if s["run_id"] == run_id), None)


def _tracking_status():
    runs = [a for a in STATE["applies"] if a["operation"] == "enable_tracking" and a["mode"] == "dry_run"
            and a["status"] == "SUCCEEDED"]
    if not runs:
        return {"states": {}, "checked_at": None}
    latest = max(runs, key=lambda a: a["started_at"])
    states = {}
    for it in latest["_items"]:
        if it.get("type") != "serving_endpoint":
            continue
        if it.get("action") == "would_enable_tracking":
            states[it["name"]] = "off"
        elif it.get("action") == "already_enabled":
            states[it["name"]] = "on"
    return {"states": states, "checked_at": latest["started_at"][:16]}


def _public(rec, with_items=False):
    out = {k: v for k, v in rec.items() if not k.startswith("_") and k not in ("operation",)}
    out["rolled_back"] = any(a["rollback_of"] == rec["apply_id"] and a["status"] == "SUCCEEDED"
                             for a in STATE["applies"]) if rec["mode"] == "execute" else False
    if rec.get("operation") is not None:
        out["operation"] = rec["operation"]
    if rec["operation"] == "pause_legacy" and rec["mode"] == "execute":
        out["resumed"] = rec.get("_resumed", False)
    return out


def _list_applies(cutover: bool):
    rows = []
    for a in STATE["applies"]:
        is_cut = a["operation"] not in (None, "apply")
        if is_cut != cutover:
            continue
        rows.append(_public(a))
    return rows


# ---------------------------------------------------------------------------
# Usage fixtures (system.ai_gateway.usage, MODEL_SERVICE rows, 7-day base)
# ---------------------------------------------------------------------------

USAGE = [
    dict(service=svc("chat-gpt4o-proxy"), ws=WS_ID, requester=ANALYST, api="mlflow/v1/chat/completions",
         dest="gpt-4o-mini", requests=1844, invocations=1851, tokens=2910220, avg=612.4, p95=1480.0, errors=12, last_h=3),
    dict(service=svc("claims-summary-pt"), ws=WS_ID, requester=SP_ID, api="mlflow/v1/chat/completions",
         dest="claims-summary-pt", requests=2310, invocations=2318, tokens=5184330, avg=880.6, p95=1920.1, errors=3, last_h=9),
    dict(service=svc("claims-summary-pt"), ws=WS_ID, requester=ME, api="openai/v1/responses",
         dest="claims-summary-pt", requests=412, invocations=418, tokens=690115, avg=1104.2, p95=2930.5, errors=0, last_h=5),
    dict(service="system.ai.gpt_5_mini", ws=WS_ID, requester="nightly-batch-runner", api="mlflow/v1/chat/completions",
         dest="gpt-5-mini", requests=1020, invocations=1020, tokens=3344020, avg=940.0, p95=2010.0, errors=8, last_h=7),
    dict(service=svc("support-bot-openai"), ws=WS_ID, requester=ANALYST, api="mlflow/v1/chat/completions",
         dest="gpt-4o-mini", requests=388, invocations=388, tokens=402211, avg=701.3, p95=1650.4, errors=1, last_h=20),
    dict(service="system.ai.llama_3_3_70b_instruct", ws=WS_ID, requester=ME, api="openai/v1/responses",
         dest="llama-3-3-70b-instruct", requests=210, invocations=214, tokens=480300, avg=1210.8, p95=3020.2, errors=0, last_h=40),
]
WINDOW_FACTOR = {"24h": 0.15, "7d": 1.0, "30d": 3.4}
WINDOW_SPAN = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
USAGE_COLUMNS = ["service_name", "workspace_id", "requester", "api_type", "destination_model", "requests",
                 "invocations", "total_tokens", "average_latency_ms", "p95_latency_ms", "error_invocations", "last_request"]


def usage_rows(window: str, service: str):
    f = WINDOW_FACTOR[window]
    rows = []
    for u in USAGE:
        if service and u["service"] != service:
            continue
        rows.append({
            "service_name": u["service"], "workspace_id": u["ws"], "requester": u["requester"], "api_type": u["api"],
            "destination_model": u["dest"], "requests": round(u["requests"] * f),
            "invocations": round(u["invocations"] * f), "total_tokens": round(u["tokens"] * f),
            "average_latency_ms": u["avg"], "p95_latency_ms": u["p95"], "error_invocations": round(u["errors"] * f),
            "last_request": ago(hours=u["last_h"]),
        })
    rows.sort(key=lambda r: (-r["total_tokens"], -r["requests"]))
    return rows


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra or {}


def _plan_for(scan):
    return [dict(p) for p in PLAN]


def _callers_for(scan):
    return [dict(c) for c in CALLERS]


def _scan_detail(scan):
    det = scan["_detail"]
    meta = {k: v for k, v in scan.items() if not k.startswith("_")}
    return {
        "meta": meta, "readiness": json.loads(json.dumps(det)),
        "plan": _plan_for(scan), "callers": _callers_for(scan), "providers": [dict(p) for p in PROVIDERS],
        "ref_counts": {"all": len(REFS), "fixes": FIX_COUNT},
    }


def _job_status(job_run_id: str):
    if not re.fullmatch(r"[0-9]{1,18}", job_run_id):
        raise ApiError(400, "That job run id isn't valid")
    job = STATE["jobs"].get(job_run_id)
    if job is None:
        return {"job_run_id": job_run_id, "life_cycle": "TERMINATED", "result": "SUCCESS", "start_time": None,
                "end_time": None, "message": None, "url": None}
    return {"job_run_id": job_run_id, "life_cycle": "TERMINATED", "result": "SUCCESS",
            "start_time": int(T0.timestamp() * 1000), "end_time": int(T0.timestamp() * 1000) + 41000,
            "message": None, "url": f"{HOST}/?o={WS_ID}#job/{job_run_id}"}


def _new_job(kind: str, item_id: str) -> str:
    jid = _job_id()
    STATE["jobs"][jid] = {"kind": kind, "id": item_id}
    return jid


def _body_required(body: dict, key: str, msg: str):
    if not body.get(key):
        raise ApiError(400, msg)


def handle_api(method: str, path: str, qs: dict, body: dict):
    with STATE_LOCK:
        return _handle_api(method, path, qs, body)


def _handle_api(method, path, qs, body):
    if method == "GET":
        if path == "/api/whoami":
            return 200, {"email": ME, "user_authorization": True, "operator": True, "workspace": HOST}
        if path == "/api/config":
            return 200, {
                "results_schema": RESULTS_SCHEMA, "warehouse_id": WAREHOUSE_ID,
                "jobs": {"snapshot": True, "scan": True, "apply": True}, "secret_schemas": [SECRET_SCHEMA],
                "allow_secret_read": False, "max_scan_age_days": 14, "export_row_limit": 200000,
                "deadline": DEADLINE, "deadline_as_of": DEADLINE_AS_OF, "workspace_url": HOST,
                "scan_scope": f"This app scans only {HOST}.",
            }
        if path == "/api/target-schema":
            return 200, {"exists": True, "can_create_service": None, "error": None}
        if path.startswith("/api/jobs/"):
            return 200, _job_status(unquote(path.rsplit("/", 1)[1]))
        if path == "/api/overview":
            return 200, empty_overview() if STATE["empty"] else snapshot_overview()
        if path == "/api/scans":
            return 200, [_list_scan(s) for s in STATE["scans"]]
        m = re.fullmatch(r"/api/scans/([^/]+)/refs", path)
        if m:
            return 200, _refs_page(m.group(1), qs)
        m = re.fullmatch(r"/api/scans/([^/]+)", path)
        if m:
            scan = _scan_by_id(m.group(1))
            if not scan:
                raise ApiError(404, "not found")
            return 200, _scan_detail(scan)
        if path == "/api/applies":
            return 200, _list_applies(cutover=False)
        m = re.fullmatch(r"/api/applies/([^/]+)", path)
        if m:
            return 200, _apply_detail(m.group(1), cutover=False)
        if path == "/api/cutover/runs":
            return 200, _list_applies(cutover=True)
        if path == "/api/cutover/traffic":
            return 200, _traffic(qs)
        if path == "/api/cutover/endpoints":
            return 200, _cutover_endpoints(qs)
        if path == "/api/cutover/services":
            return 200, _cutover_services(qs)
        if path == "/api/usage/summary":
            window = qs.get("window", "7d")
            if window not in WINDOW_SPAN:
                raise ApiError(400, "window must be 24h, 7d or 30d")
            service = qs.get("service", "")
            return 200, {"window": window, "since": sql_ts(T0 - WINDOW_SPAN[window]),
                         "service": service or None, "rows": usage_rows(window, service)}
        if path == "/api/usage/request":
            return 200, {"request_id": qs.get("request_id", ""), "rows": []}
        m = re.fullmatch(r"/api/cutover/([^/]+)", path)
        if m:
            return 200, _apply_detail(m.group(1), cutover=True)
        if "/export" in path:
            raise ApiError(501, "exports aren't modelled in the mock server")
    if method == "POST":
        if path == "/api/account/snapshot":
            return 200, {"job_run_id": _new_job("snapshot", "")}
        if path == "/api/scans":
            return 200, _start_scan(body)
        if path == "/api/applies":
            return 200, _start_apply(body)
        if path == "/api/cutover":
            return 200, _start_cutover(body)
    raise ApiError(404, "not found")


def _list_scan(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def _refs_page(run_id, qs):
    scan = _scan_by_id(run_id)
    if not scan:
        raise ApiError(404, "not found")
    kind = qs.get("kind", "all")
    if kind not in ("all", "fixes"):
        raise ApiError(400, "kind must be all or fixes")
    q = (qs.get("q") or "").lower()
    offset, limit = int(qs.get("offset", 0)), min(int(qs.get("limit", 100)), 1000)
    rows = [r for r in REFS if (kind == "all" or (r["fixed_line"] and r["fixed_line"] != r["line_text"]))]
    if q:
        rows = [r for r in rows if q in (r["asset"] or "").lower()] if kind == "fixes" \
            else [r for r in rows if q in json.dumps(r).lower()]
    if kind == "fixes":
        rows.sort(key=lambda r: (r["asset"], r["line"] or 0))
    page = [dict(r) for r in rows[offset:offset + limit]]
    return {"total": len(rows), "offset": offset, "limit": limit, "rows": page}


def _apply_detail(run_id, cutover: bool):
    rec = next((a for a in STATE["applies"] if a["apply_id"] == run_id and
                (a["operation"] not in (None, "apply")) == cutover), None)
    if not rec:
        raise ApiError(404, "not found")
    rollbacks = [{"apply_id": a["apply_id"], "status": a["status"]} for a in STATE["applies"]
                 if a["rollback_of"] == run_id and a["mode"] == "rollback"]
    meta = _public(rec)
    if cutover:
        meta["resumed"] = rec["operation"] == "pause_legacy" and rec.get("_resumed", False)
    return {"meta": meta, "items": [dict(i) for i in rec["_items"]], "rollbacks": rollbacks}


def _start_scan(body):
    days = int(body.get("days", 30))
    if not 1 <= days <= 365:
        raise ApiError(400, "days must be 1 to 365")
    for v in (body.get("target_catalog", "ai_gateway"), body.get("target_schema", "migrated")):
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", v or ""):
            raise ApiError(400, "catalog and schema names may only contain letters, digits, _ and -")
    run_id = _new_id()
    job = _new_job("scan", run_id)
    now = T0 + timedelta(minutes=0)
    scan = {
        "run_id": run_id, "job_run_id": job, "requested_by": ME, "workspace_url": HOST, "workspace_id": WS_ID,
        "status": "SUCCEEDED", "readiness": "BLOCKED", "endpoints": len(PLAN), "client_references": len(REFS),
        "traffic_status": "ok", "days": days, "target_catalog": body.get("target_catalog", "ai_gateway"),
        "target_schema": body.get("target_schema", "migrated"), "scan_roots": body.get("scan_roots", ""),
        "toolkit_version": TOOLKIT, "error": None, "started_at": sql_ts(now - timedelta(minutes=2)),
        "finished_at": sql_ts(now), "_detail": build_readiness("BLOCKED"),
    }
    STATE["scans"].insert(0, scan)
    return {"run_id": run_id, "job_run_id": job}


def _start_apply(body):
    mode = body.get("mode", "dry_run")
    if mode not in ("dry_run", "execute", "rollback"):
        raise ApiError(400, "mode must be dry_run, execute or rollback")
    if mode == "rollback":
        if body.get("confirm") != "ROLLBACK" or not body.get("rollback_of"):
            raise ApiError(400, "type ROLLBACK and choose the execute run to roll back")
        src = next((a for a in STATE["applies"] if a["apply_id"] == body["rollback_of"]), None)
        if not src or src["mode"] != "execute" or src["operation"] not in (None, "apply"):
            raise ApiError(400, "rollback_of must be an execute run")
        if any(a["rollback_of"] == src["apply_id"] and a["status"] == "SUCCEEDED" for a in STATE["applies"]):
            raise ApiError(409, "That execute run has already been rolled back, or a rollback of it is running")
        created = [i for i in src["_items"] if i.get("action") == "created"]
        items = [dict(type=i["type"], name=i["name"], action="deleted") for i in created]
        rec = _apply_record("rollback", src["scan_run_id"], [], ME, T0, None, items=items)
        rec["rollback_of"] = src["apply_id"]
        rec["endpoints"] = src["endpoints"]
        STATE["applies"].insert(0, rec)
        return {"apply_id": rec["apply_id"], "job_run_id": rec["job_run_id"]}
    scan_id = body.get("scan_run_id", "")
    scan = _scan_by_id(scan_id)
    if not scan:
        raise ApiError(404, "scan not found")
    if scan["status"] != "SUCCEEDED":
        raise ApiError(409, "That scan didn't finish successfully; apply uses a finished scan")
    endpoints = sorted(set(body.get("endpoints") or []))
    if not endpoints:
        raise ApiError(400, "choose at least one endpoint")
    for e in endpoints:
        p = PLAN_BY_NAME.get(e)
        if not p or p["action"] != "create_model_service":
            raise ApiError(400, f"{e} isn't an endpoint apply can migrate in this scan")
    if mode == "execute":
        if body.get("confirm") != "EXECUTE":
            raise ApiError(400, "type EXECUTE to confirm creating objects")
        dry = next((a for a in STATE["applies"] if a["apply_id"] == body.get("dry_run_id")), None)
        if not dry or dry["mode"] != "dry_run" or dry["scan_run_id"] != scan_id:
            raise ApiError(400, "Run a dry run with this selection first")
        if dry["endpoints"] != ",".join(endpoints):
            raise ApiError(409, "The endpoints or options changed since that dry run; run a dry run with these settings")
        guardrails = any(n.startswith("BLOCKS APPLY: guardrails") for e in endpoints for n in PLAN_BY_NAME[e]["needs_human"])
        if guardrails and not body.get("ack_guardrails"):
            raise ApiError(400, "Some endpoints have guardrails that aren't migrated. Read the notes in the plan and "
                                "tick the guardrails acknowledgement to execute.")
    apply_id = _new_id()
    job = _new_job("apply", apply_id)
    smoke = bool(body.get("smoke_test", mode == "execute"))
    items = _apply_items(scan_id, endpoints, execute=(mode == "execute"), smoke=smoke)
    rec = _apply_record(mode, scan_id, endpoints, ME, T0, None, items=items, apply_id=apply_id)
    rec["job_run_id"] = job
    rec["target_catalog"], rec["target_schema"] = body.get("target_catalog", TARGET_CATALOG), body.get("target_schema", TARGET_SCHEMA)
    STATE["applies"].insert(0, rec)
    return {"apply_id": apply_id, "job_run_id": job}


CUTOVER_WORD = {"test_call": "TEST", "enable_tracking": "ENABLE"}


def _start_cutover(body):
    op = body.get("operation", "")
    if op not in ("test_call", "pause_legacy", "enable_tracking", "resume_legacy"):
        raise ApiError(400, "operation must be test_call, pause_legacy, enable_tracking or resume_legacy")
    if op == "resume_legacy":
        if body.get("mode") != "execute":
            raise ApiError(400, "Resume runs as execute. There is no dry run for a resume.")
        if body.get("confirm") != "RESUME":
            raise ApiError(400, "type RESUME to confirm")
        src = next((a for a in STATE["applies"] if a["apply_id"] == body.get("rollback_of")), None)
        if not src or src["operation"] != "pause_legacy" or src["mode"] != "execute":
            raise ApiError(400, "Resume needs a pause run that was executed")
        if src["_resumed"]:
            raise ApiError(409, "That pause run has already been resumed, or a resume of it is running")
        src["_resumed"] = True
        items = [dict(type="serving_endpoint", name=n, action="resumed") for n in src["endpoints"].split(",") if n]
        rec = _cutover_record("resume_legacy", "execute", src["endpoints"].split(","), ME, T0, "",
                              items=items, rollback_of=src["apply_id"])
        STATE["applies"].insert(0, rec)
        return {"apply_id": rec["apply_id"], "job_run_id": rec["job_run_id"], "operation": op, "mode": "execute"}
    mode = body.get("mode", "dry_run")
    if mode not in ("dry_run", "execute"):
        raise ApiError(400, "mode must be dry_run or execute")
    scan_id = body.get("scan_run_id", "") or (_latest_succeeded_scan() or {}).get("run_id", "")
    items, services, endpoints, api_type = [], None, [], None
    if op == "test_call":
        services = sorted({s for s in body.get("services", []) if s})
        if not services:
            raise ApiError(400, "Choose at least one Unity Gateway service to test")
        if len(services) > 10:
            raise ApiError(400, "Test at most 10 services at a time (each gets one billable request)")
        api_type = body.get("api_type") or "mlflow/v1/chat/completions"
        prompt = (body.get("prompt") or "").strip() or "Reply with: ok"
        if len(prompt) > 200 or any(ord(c) < 32 for c in prompt):
            raise ApiError(400, "The prompt must be one line of up to 200 characters")
    else:
        endpoints = sorted({e for e in body.get("endpoints", []) if e})
        if op == "pause_legacy" and len(endpoints) != 1:
            raise ApiError(400, "Pause one endpoint per run")
        if op == "enable_tracking" and not endpoints:
            raise ApiError(400, "Choose at least one endpoint to turn usage tracking on for")
    if mode == "execute":
        word = f"PAUSE {endpoints[0]}" if op == "pause_legacy" else CUTOVER_WORD.get(op, "")
        if body.get("confirm") != word:
            raise ApiError(400, f"type {word} to confirm")
        dry = next((a for a in STATE["applies"] if a["apply_id"] == body.get("dry_run_id")), None)
        if not dry or dry["mode"] != "dry_run" or dry["operation"] != op or dry["status"] != "SUCCEEDED":
            raise ApiError(400 if not dry else 409, "Run a dry run with these settings first")
    if op == "test_call":
        if mode == "dry_run":
            items = [dict(type="model_service", name=s, action="would_test") for s in services]
        else:
            items = [dict(type="model_service", name=s, action="test_ok", http_status=200,
                          latency_ms=380 + (sum(map(ord, s)) % 300), reply_excerpt="ok",
                          request_id=_new_id()) for s in services]
    elif op == "pause_legacy":
        kind = PLAN_BY_NAME.get(endpoints[0], {}).get("kind", "external_model")
        items = [dict(type="serving_endpoint", name=endpoints[0], kind=kind,
                      action="would_pause" if mode == "dry_run" else "paused")]
    elif op == "enable_tracking":
        tracked = _tracking_status()["states"]
        for e in endpoints:
            if tracked.get(e) == "on":
                items.append(dict(type="serving_endpoint", name=e, action="already_enabled"))
            else:
                items.append(dict(type="serving_endpoint", name=e,
                                  action="would_enable_tracking" if mode == "dry_run" else "tracking_enabled"))
    rec = _cutover_record(op, mode, endpoints, ME, T0, scan_id, services=services, api_type=api_type, items=items)
    if op == "test_call":
        rec["endpoints"] = ""
    STATE["applies"].insert(0, rec)
    return {"apply_id": rec["apply_id"], "job_run_id": rec["job_run_id"], "operation": op, "mode": mode}


def _traffic(qs):
    window = qs.get("window", "24h")
    if window != "scan" and window not in WINDOW_SPAN:
        raise ApiError(400, "window must be 24h, 7d, 30d or scan")
    scan = _scan_by_id(qs.get("scan_run_id", "")) if qs.get("scan_run_id") else _latest_succeeded_scan()
    if not scan:
        return {"scan_run_id": None, "window": window, "since": None, "total_requests": 0, "endpoints": []}
    span = WINDOW_SPAN[window] if window != "scan" else timedelta(days=30)
    factor = WINDOW_FACTOR_TRAFFIC.get(window, 1.0)
    out = []
    for p in PLAN:
        if p["kind"] in ("custom_model", "agent"):
            continue
        name = p["legacy_endpoint"]
        callers = []
        for c in CALLERS:
            if c["endpoint_name"] != name:
                continue
            req = round(c["requests"] * factor)
            if req <= 0:
                continue
            # The last request can't be older than the window it is counted in.
            hours = c["last_h"] if window == "scan" else min(c["last_h"], span.total_seconds() / 3600 - 1)
            callers.append({"source": "v2" if p["kind"] == "v2_workspace_endpoint" else "v1",
                            "requester": c["requester"], "requests": req, "last_request": ago(hours=hours),
                            "caller_class": c["caller_class"]})
        total = sum(c["requests"] for c in callers)
        last = max((c["last_request"] for c in callers), default=None)
        callers.sort(key=lambda c: -c["requests"])
        failed = round(total * V2_FAILED_SHARE.get(name, 0))
        for c in callers:  # tokens and failures split across the callers in proportion to their requests
            c["tokens"] = c["requests"] * TOKENS_PER_REQUEST
            c["failed"] = round(c["requests"] * failed / total) if total else 0
        out.append({"endpoint_name": name, "kind": p["kind"], "requests": total, "failed": failed,
                    "tokens": total * TOKENS_PER_REQUEST, "v2_requests": total if p["kind"] == "v2_workspace_endpoint" else 0,
                    "v2_failed": failed if p["kind"] == "v2_workspace_endpoint" else 0,
                    "v2_tokens": total * TOKENS_PER_REQUEST if p["kind"] == "v2_workspace_endpoint" else 0,
                    "v2_failing": p["kind"] == "v2_workspace_endpoint" and total >= 10 and 100 * failed >= 95 * total,
                    "last_request": last, "callers": callers, "status": "requests" if total else "no_requests"})
    out.sort(key=lambda e: (-e["requests"], e["endpoint_name"]))
    return {"scan_run_id": scan["run_id"], "workspace_id": WS_ID, "window": window,
            "since": sql_ts(T0 - span), "checked_at": T0.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_requests": sum(e["requests"] for e in out), "endpoints": out}


WINDOW_FACTOR_TRAFFIC = {"24h": 0.05, "7d": 0.3, "30d": 1.0, "scan": 1.0}


def _cutover_endpoints(qs):
    scan = _scan_by_id(qs.get("scan_run_id", "")) if qs.get("scan_run_id") else _latest_succeeded_scan()
    if not scan:
        return {"scan_run_id": None, "endpoints": [], "tracking_checked": None}
    tracking = _tracking_status()
    not_operable = ("custom_model", "agent", "v2_workspace_endpoint", "unknown", "out_of_scope", "deleted_or_unknown")
    seen = {}
    for p in PLAN:
        name = p["legacy_endpoint"]
        if p["kind"] in not_operable or name in seen:
            continue
        seen[name] = {"endpoint": name, "kind": p["kind"], "plan": p["action"],
                      "trackable": p["kind"] != "system_ppt",
                      "tracking": tracking["states"].get(name, "not checked")}
    return {"scan_run_id": scan["run_id"], "endpoints": sorted(seen.values(), key=lambda e: e["endpoint"]),
            "tracking_checked": tracking["checked_at"]}


def _cutover_services(qs):
    scan = _scan_by_id(qs.get("scan_run_id", "")) if qs.get("scan_run_id") else _latest_succeeded_scan()
    if not scan:
        return {"scan_run_id": None, "source": "scan plan", "services": []}
    services = [{"name": p["target_service"], "from": p["legacy_endpoint"], "plan": p["action"],
                 "exists": p["target_status"] == "exists"} for p in PLAN]
    services.sort(key=lambda s: s["name"])
    return {"scan_run_id": scan["run_id"], "source": "scan plan", "services": services}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".json": "application/json", ".map": "application/json", ".woff2": "font/woff2"}


class Handler(BaseHTTPRequestHandler):
    server_version = "UGMockServer/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload):
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise ApiError(400, "body must be JSON")

    def _dispatch(self, method: str):
        url = urlparse(self.path)
        path = url.path
        qs = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        if path == "/__mock/reset" and method == "POST":
            body = self._read_body()
            seed(empty=body.get("state") == "empty")
            return self._json(200, {"state": "empty" if body.get("state") == "empty" else "full"})
        if path.startswith("/api/") or path == "/api":
            try:
                body = self._read_body() if method == "POST" else {}
                status, payload = handle_api(method, path, qs, body)
                return self._json(status, payload)
            except ApiError as e:
                payload = {"detail": e.detail, **e.extra}
                return self._json(e.status, payload)
            except (KeyError, IndexError, TypeError, ValueError) as e:
                return self._json(400, {"detail": f"mock: bad request ({e})"})
            except Exception as e:  # a mock bug should show up in the page, not hang it
                return self._json(500, {"detail": f"mock error: {e}"})
        return self._static(path)

    def _static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC)) or not target.is_file():
            target = STATIC / "index.html"
        if not target.is_file():
            return self._send(404, b"frontend not built: run npm run build in app/frontend", "text/plain; charset=utf-8")
        return self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_HEAD(self):
        self._dispatch("GET")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--empty", action="store_true", help="start with no snapshot, scans or runs (first-run page)")
    args = ap.parse_args()
    seed(empty=args.empty)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock Unity Gateway backend on http://{args.host}:{args.port} (state: {'empty' if args.empty else 'full'})",
          flush=True)
    print(f"serving {STATIC}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
