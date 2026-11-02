"""Offline tests for the account-wide view, its snapshot writes and the app's overview handler."""

import csv
import sys
import time
from pathlib import Path

import pytest

import ug_migration_account as acct
import ug_migration_planner as planner

INV = [
    {"workspace_id": "1", "endpoint_name": "databricks-gpt-5-5", "entity_type": "FOUNDATION_MODEL", "is_pt": "false"},
    {"workspace_id": "1", "endpoint_name": "proj-gpt", "entity_type": "EXTERNAL_MODEL", "provider": "openai", "is_pt": "false"},
    {"workspace_id": "2", "endpoint_name": "proj-gpt", "entity_type": "EXTERNAL_MODEL", "provider": "openai", "is_pt": "false"},
    {"workspace_id": "2", "endpoint_name": "llama-pt", "entity_type": "FOUNDATION_MODEL", "is_pt": "true"},
    {"workspace_id": "3", "endpoint_name": "churn", "entity_type": "CUSTOM_MODEL", "is_pt": "false"},
]
V1 = [{"workspace_id": "1", "endpoint_name": "databricks-gpt-5-5", "requests": "20000", "requesters": "3",
       "throttled": "50", "tokens": "1000", "last_request": "2026-10-30", "last_seen": "2026-10-30 10:00:00"},
      {"workspace_id": "2", "endpoint_name": "old-ep", "requests": "5", "requesters": "1", "throttled": "0",
       "tokens": "1", "last_request": "2026-10-01", "last_seen": "2026-10-01 10:00:00"}]
UG = [{"workspace_id": "1", "v3_requests": "80000", "v3_requesters": "9", "v2_requests": "0"},
      {"workspace_id": "4", "v3_requests": "10", "v3_requesters": "1", "v2_requests": "3"}]
WS = [{"workspace_id": w, "workspace_name": f"ws{w}", "workspace_url": f"adb-{w}.azuredatabricks.net", "status": "RUNNING"}
      for w in "1234"]


def _by(res):
    return {w["workspace_id"]: w for w in res["workspaces"]}


def test_classify():
    assert [acct.classify(r) for r in INV] == ["system_ppt", "external_model", "external_model",
                                              "provisioned_throughput", "out_of_scope"]


def test_build_waves_and_collisions():
    res = acct.build(INV, V1, UG, WS, 30)
    by = _by(res)
    assert by["1"]["wave"] == "2: high volume" and by["1"]["v3_share"] == 0.8
    assert by["2"]["wave"] == "1: cleanup" and by["2"]["custom_legacy_endpoints"] == 2
    # Traffic to an endpoint deleted since is kept apart: it doesn't make the workspace "active".
    assert by["2"]["v1_requests"] == 0 and by["2"]["deleted_endpoint_requests"] == 5
    assert by["3"]["wave"] == "no legacy endpoints (custom ML only)"  # only a custom ML model: not a no-traffic candidate
    assert by["4"]["wave"] == "v2 traffic"
    assert res["workspaces"][0]["workspace_id"] == "1"  # busiest first
    assert res["collisions"] == [{"endpoint_name": "proj-gpt", "workspaces": ["1", "2"], "count": 2}]
    assert any(e["endpoint_name"] == "old-ep" and e["kind"] == "deleted_or_unknown" for e in res["endpoints"])
    md = acct.summary_md(res)
    assert "Name collisions" in md and "(about 80% of model traffic on Unity Gateway" in md


def test_wave_0_is_no_traffic_with_last_seen_not_ready():
    inv = [{"workspace_id": "1", "endpoint_name": "databricks-gpt", "entity_type": "FOUNDATION_MODEL", "is_pt": "false"}]
    v1 = [{"workspace_id": "1", "endpoint_name": "databricks-gpt", "requests": "0", "requesters": "0", "throttled": "0",
           "tokens": "", "last_seen": "2026-07-22 17:53:27"}]
    by = _by(acct.build(inv, v1, [], WS[:1], 30))
    assert by["1"]["wave"] == "0: no legacy traffic"
    assert "last seen 2026-07-22" in by["1"]["hint"] and "passing workspace scan" in by["1"]["hint"]


def test_no_usage_rows_is_traffic_unknown_not_zero():
    inv = [{"workspace_id": "1", "endpoint_name": "databricks-gpt", "entity_type": "FOUNDATION_MODEL", "is_pt": "false"}]
    by = _by(acct.build(inv, [], [], WS[:1], 30))
    assert by["1"]["wave"] == "0: traffic unknown" and by["1"]["unknown_traffic_endpoints"] == 1
    assert "usage tracking may be off" in by["1"]["hint"]


def test_running_workspace_without_rows_is_no_endpoint_data():
    res = acct.build(INV, V1, UG, WS + [{"workspace_id": "9", "workspace_name": "idle", "status": "RUNNING"}], 30)
    assert _by(res)["9"]["wave"] == "no endpoint data"
    stopped = acct.build([], [], [], [{"workspace_id": "8", "workspace_name": "off", "status": "STOPPED"}], 30)
    assert _by(stopped)["8"]["wave"] == "not running"


def test_foundation_model_other_blocks_wave_0_and_is_labeled():
    inv = [{"workspace_id": "1", "endpoint_name": "ft", "entity_type": "FOUNDATION_MODEL", "is_pt": "false"}]
    by = _by(acct.build(inv, [], [], WS[:1], 30))
    assert by["1"]["wave"] == "1: cleanup" and "foundation_model_other" in by["1"]["hint"]


def test_config_signals_are_billing_product_names():
    cfg = [{"workspace_id": "1", "billing_origin_product": "VECTOR_SEARCH"},
           {"workspace_id": "1", "billing_origin_product": "APPS"}]
    by = _by(acct.build([], [], [], WS[:1], 30, config=cfg))
    assert by["1"]["config_signals"] == "APPS,VECTOR_SEARCH"
    assert "AI Search" in acct.summary_md(acct.build([], [], [], WS[:1], 30, config=cfg))
    assert _by(acct.build([], [], [], WS[:1], 30, config=None))["1"]["config_signals"] is None


def test_profiles_for(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.write_text("[DEFAULT]\nhost = https://adb-1.azuredatabricks.net\n\n[other]\nhost = https://adb-2.azuredatabricks.net/\n")
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
    assert acct._profiles_for("https://adb-2.azuredatabricks.net") == ["other"]
    assert acct._profiles_for("adb-1.azuredatabricks.net") == ["DEFAULT"]


def test_run_with_failed_usage_query_marks_waves_unknown_and_refuses_snapshot(tmp_path, monkeypatch):
    def fake_sql(w, wh, sql, params=None):
        if "ai_gateway.usage" in sql:
            raise RuntimeError("permission denied on system.ai_gateway.usage")
        if "served_entities" in sql and "latest" in sql:
            return INV
        if "endpoint_usage" in sql:
            return []
        if "workspaces_latest" in sql:
            return WS
        return []

    monkeypatch.setattr(planner, "_sql", fake_sql)
    res = acct.run(object(), "wh", str(tmp_path), days=30)
    assert res["errors"]
    with open(tmp_path / "account_workspaces.csv") as f:
        waves = [r["wave"] for r in csv.DictReader(f)]
    assert waves and set(waves) == {"unknown"}
    with pytest.raises(SystemExit):
        acct.run(object(), "wh", str(tmp_path / "again"), days=30, snapshot_prefix="c.s.p")


def test_snapshot_writes_endpoints_first_then_marks_complete(monkeypatch):
    calls = []

    def fake_sql(w, wh, sql, params=None):
        calls.append(sql)
        if sql.startswith("DESCRIBE"):
            # An old table: no run markers yet, so they must be added
            return [{"col_name": "snapshot_time"}, {"col_name": "workspace_id"}]
        return []

    monkeypatch.setattr(planner, "_sql", fake_sql)
    result = {"days": 30, "workspaces": [{"workspace_id": "1", "wave": "0: no legacy traffic"}],
              "endpoints": [{"workspace_id": "1", "endpoint_name": "gpt", "requests": 0}]}
    acct.write_snapshot(object(), "wh", "c.s.ug_migration", result, "run-abc", 1761904800)
    ins = [i for i, s in enumerate(calls) if s.startswith("INSERT")]
    upd = [i for i, s in enumerate(calls) if s.startswith("UPDATE")]
    assert "_endpoints" in calls[ins[0]] and "_workspaces" in calls[ins[1]]
    # Endpoints go in and are marked first; the workspace rows (what the overview reads) are the last to complete.
    assert ins[0] < upd[0] < ins[1] < upd[1]
    assert all("TRUE WHERE run_id = 'run-abc'" in calls[u] for u in upd)
    assert any("ALTER TABLE c.s.ug_migration_workspaces ADD COLUMNS (run_id STRING" in s for s in calls)
    assert any("timestamp_seconds(1761904800)" in s for s in calls)
    assert all("FALSE)" in calls[i] for i in ins)


def test_deep_scan_selects_by_wave_and_logs_skips(monkeypatch, tmp_path):
    res = acct.build(INV, V1, UG, WS + [{"workspace_id": "8", "workspace_name": "off", "workspace_url": "u8",
                                         "status": "STOPPED"}], 30)
    res["workspaces"].append({"workspace_id": "7", "workspace_name": "idle", "workspace_url": "u7", "status": "RUNNING",
                              "wave": "0: no legacy traffic", "legacy_requests": 0, "custom_legacy_endpoints": 0})
    seen = []

    class FakeUser:
        user_name = "sp-scanner"

    class FakeClient:
        current_user = type("U", (), {"me": staticmethod(lambda: FakeUser())})()

    def fake_connect(url, parent=None, expect_id=None):
        seen.append(expect_id)
        return FakeClient()

    def fake_run(client, out, **kw):
        return {"readiness": "READY", "workspace": kw["workspace_id"]}

    monkeypatch.setattr(acct, "connect", fake_connect)
    monkeypatch.setattr(planner, "run", fake_run)
    monkeypatch.setattr(planner, "_log", lambda msg: None)
    out = acct.deep_scan(res, str(tmp_path), None, None, "ai_gateway", "migrated", 30, "wh", wave="0")
    # Wave 0 candidates only (workspace 7; workspace 3 is custom ML only and is no longer wave 0); the stopped
    # workspace 8 is never a candidate.
    assert [o["workspace_id"] for o in out if o["status"] == "ok"] == ["7"]
    assert out[0]["principal"] == "sp-scanner" and seen == ["7"]  # each connection checked against its ID
    skipped = acct.deep_scan(res, str(tmp_path), None, ["8", "99"], "ai_gateway", "migrated", 30, "wh")
    assert [s["error"] for s in skipped] == ["workspace status STOPPED", "not in the account tables"]


def test_connect_rejects_a_client_on_another_workspace(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.config = type("Cfg", (), {"host": "https://adb-1.azuredatabricks.net"})()
            self.current_user = type("U", (), {"me": staticmethod(lambda: None)})()

    monkeypatch.setattr(acct, "WorkspaceClient", FakeClient)
    monkeypatch.setattr(acct, "_profiles_for", lambda url: [])
    monkeypatch.setattr(planner, "workspace_id_of", lambda c: "1")
    with pytest.raises(RuntimeError, match="connected to workspace 1, not 2"):
        acct.connect("https://adb-2.azuredatabricks.net", expect_id="2")


# ---------------------------------------------------------------------------
# App overview: which run is read, readiness from scans, export truncation
# ---------------------------------------------------------------------------

APP = Path(__file__).resolve().parent / "app"


@pytest.fixture
def main_mod(monkeypatch):
    sys.path.insert(0, str(APP))
    from backend import main

    monkeypatch.setattr(main, "RESULTS_SCHEMA", "c.s")
    monkeypatch.setattr(main, "SNAPSHOT_PREFIX", "ug_migration")
    monkeypatch.setattr(main, "_running_snapshot", lambda: None)
    return main


def _ws_row(epoch, wid="1", wave="0: no legacy traffic", complete="true", **kw):
    row = {"snapshot_epoch": str(epoch), "workspace_id": wid, "workspace_name": f"ws{wid}", "status": "RUNNING",
           "wave": wave, "complete": complete, "window_days": "30", "run_id": "r1", "legacy_endpoints": "1",
           "custom_legacy_endpoints": "0", "active_legacy_endpoints": "0", "unknown_traffic_endpoints": "0",
           "v1_requests": "0", "v2_requests": "0", "legacy_requests": "0", "legacy_throttled": "0",
           "deleted_endpoint_requests": "0", "v3_requests": "0", "v3_share": None, "last_seen": "2026-07-22 17:53:27",
           "config_signals": None, "legacy_tokens": "0"}
    row.update(kw)
    return row


def _fake_query(ws_rows, ep_rows=(), scan_rows=()):
    def q(request, sql, params=None):
        if "unix_timestamp(snapshot_time)" in sql:
            return list(ws_rows)
        if "ug_migration_scans" in sql:
            return list(scan_rows)
        if "_endpoints" in sql:
            return list(ep_rows)
        return []
    return q


def test_overview_reads_only_complete_runs_and_handles_old_snapshots(monkeypatch, main_mod):
    now = int(time.time())
    rows = [_ws_row(now - 3600, complete="false"),  # a write that didn't finish: never shown
            _ws_row(now - 7200, wave="v2 first", v2_requests="3", legacy_requests="3", run_id="old",
                    complete=None, window_days=None)]  # 0.8.0 snapshot: no marker and no window column
    monkeypatch.setattr(main_mod, "query", _fake_query(rows))
    out = main_mod.overview(None)
    assert out["run_id"] == "old" and out["window_assumed"] is True
    ws = out["workspaces"][0]
    # One deadline now: old wave names show under the new ones, no per-workspace due date, caller columns are unknown.
    assert ws["wave"] == "v2 traffic" and "due_date" not in ws and "due_for" not in ws
    assert ws["customer_requests"] is None and out["kpis"]["customer_requests"] is None
    assert out["kpis"]["running_workspaces"] == 1 and out["kpis"]["legacy_requests"] == 3
    assert out["deadline"]["date"] == "2027-03-30" and "deadlines" not in out and "2026-11-30" not in str(out)
    assert main_mod._wave({"wave": "0: enforce candidate"}) == "0: no legacy traffic"


def test_overview_sums_the_caller_split_when_the_snapshot_has_it(monkeypatch, main_mod):
    now = int(time.time())
    rows = [_ws_row(now, wid="1", legacy_requests="10", customer_requests="4", platform_requests="6",
                    coding_agent_requests="2"),
            _ws_row(now, wid="2", legacy_requests="5", customer_requests="5", platform_requests="0",
                    coding_agent_requests="0")]
    monkeypatch.setattr(main_mod, "query", _fake_query(rows))
    out = main_mod.overview(None)
    assert (out["kpis"]["customer_requests"], out["kpis"]["platform_requests"],
            out["kpis"]["coding_agent_requests"]) == (9, 6, 2)
    assert {w["workspace_id"]: w["platform_requests"] for w in out["workspaces"]} == {"1": 6, "2": 0}


def test_overview_ready_needs_a_passing_scan_inside_the_window(monkeypatch, main_mod):
    now = int(time.time())
    rows = [_ws_row(now, wid="1"), _ws_row(now, wid="2"), _ws_row(now, wid="3", wave="0: traffic unknown")]
    scans = [{"workspace_id": "1", "readiness": "READY", "run_id": "s1", "finished_epoch": str(now - 86400)},
             {"workspace_id": "2", "readiness": "READY", "run_id": "s2", "finished_epoch": str(now - 90 * 86400)},
             {"workspace_id": "3", "readiness": "BLOCKED", "run_id": "s3", "finished_epoch": str(now - 86400)}]
    monkeypatch.setattr(main_mod, "query", _fake_query(rows, scan_rows=scans))
    by = {w["workspace_id"]: w for w in main_mod.overview(None)["workspaces"]}
    assert by["1"]["ready"] is True and by["1"]["readiness"].startswith("Ready to enforce")
    assert by["2"]["ready"] is False and "older than the window" in by["2"]["readiness"]
    assert by["3"]["readiness"] == "Traffic unknown; scan required"


def test_export_sets_x_truncated_only_when_the_limit_is_hit(monkeypatch, main_mod):
    now = int(time.time())
    eps = [{"snapshot_epoch": str(now), "workspace_id": "1", "endpoint_name": f"e{i}", "kind": "external_model",
            "requests": "1", "complete": "true", "last_seen": None, "traffic_status": "x"} for i in range(3)]
    monkeypatch.setattr(main_mod, "query", _fake_query([_ws_row(now)], eps))
    monkeypatch.setattr(main_mod, "EXPORT_ROW_LIMIT", 2)
    resp = main_mod.export_overview("endpoints", None)
    assert resp.headers.get("X-Truncated") == "true"
    monkeypatch.setattr(main_mod, "EXPORT_ROW_LIMIT", 3)
    resp = main_mod.export_overview("endpoints", None)
    assert resp.headers.get("X-Truncated") is None


def test_account_summary_units_deadlines_and_wave_legend():
    res = acct.build(INV, V1, UG, WS, 30)
    md = acct.summary_md(res)
    assert md.index("## Deadline") < md.index("## Headline")  # deadline comes first
    assert "stop serving: **2027-03-30**" in md and "Nov 30" not in md and "2026-11-30" not in md
    assert "confirmed as of 2026-11-01" in md
    # Traffic-unknown count is endpoints in workspaces, not workspaces.
    assert "endpoints in" in md.split("Traffic unknown")[1].split("\n")[0]
    for label in acct.WAVE_MEANING:  # every wave label has a definition
        assert f"| {label} |" in md
    assert "not migrated by this toolkit" in md and "Nov 30" not in md
    assert "Custom model and feature serving endpoints are not affected" in md


def test_custom_only_workspace_is_its_own_wave_and_not_no_traffic():
    inv = [{"workspace_id": "1", "endpoint_name": "churn", "entity_type": "CUSTOM_MODEL", "is_pt": "false"}]
    res = acct.build(inv, [], [], WS[:1], 30)
    by = _by(res)
    assert by["1"]["wave"] == acct.W_CUSTOM_ONLY
    md = acct.summary_md(res)
    assert "No legacy traffic in 30 days: **0 of 0** running workspaces" in md  # custom-only is excluded
    assert "custom ML only: 1)" in md


def test_share_is_marked_approximate_and_collisions_are_readable():
    res = acct.build(INV, V1, UG, WS, 30)
    md = acct.summary_md(res)
    assert "approximate" in md and "about 80%" in md
    assert "| Endpoint | Workspace IDs | Workspaces |" in md and "| proj-gpt | 1, 2 | 2 |" in md


def test_wave_legend_thresholds_are_stated():
    assert "10,000 or more" in acct.WAVE_MEANING[acct.W_HIGH]
    assert "1 to 9,999" in acct.WAVE_MEANING[acct.W_SMALL]
    assert "v2" in acct.WAVE_MEANING[acct.W_V2] and "2026" not in acct.WAVE_MEANING[acct.W_V2]
    assert list(acct.WAVE_MEANING)[:3] == [acct.W_HIGH, acct.W_V2, acct.W_SMALL]  # volume and risk order


# ---------------------------------------------------------------------------
# Deadline, caller classes, v2 endpoints, customer-owned split, snapshot columns
# ---------------------------------------------------------------------------


def test_one_deadline_for_all_legacy_endpoints(monkeypatch):
    assert acct._deadline(None) == acct.LEGACY_DEADLINE  # default unless UGMIG_DEADLINE is set
    res = acct.build(INV, V1, UG, WS, 30)
    res["deadline"] = "2027-06-01"
    md = acct.summary_md(res)
    assert "stop serving: **2027-06-01**" in md and "2027-03-30" not in md
    assert acct._deadline("2027-06-01") == "2027-06-01"
    with pytest.raises(ValueError):
        acct._deadline("30/03/2027")
    assert acct.LEGACY_WAVE_NAMES["v2 first"] == "v2 traffic"  # old snapshot name, shown under the new one


def test_caller_class_rules_v2_and_v1():
    # v2: no user agent and no URL is no_client_info (customer-owned, likely ai_query or batch); only a known
    # Databricks system identity is platform; the user agent decides otherwise
    assert acct.caller_class(None, None, "a@b.com") == "no_client_info"
    assert acct.caller_class("", None, "sp") == "no_client_info"
    assert acct.caller_class(None, None, "system") == "platform"
    assert acct.caller_class(None, None, "Databricks", source="v1") == "platform"
    # coding agents win over the SDK they run inside
    ua = "unknown/0.0.0 databricks-sdk-py/0.137.0 python/3.13.12 os/darwin auth/databricks-cli agent/claude-code"
    assert acct.caller_class(ua, "set", "a@b.com") == "coding_agent"
    assert acct.caller_class("opencode/1.18.35 ai-sdk/provider-utils", "set", "x") == "coding_agent"
    assert acct.caller_class("databricks-sdk-py/0.137.0 python/3.11", None, "x") == "sdk"
    assert acct.caller_class("mlflow/2.19.0", None, "x") == "sdk"
    assert acct.caller_class("OpenAI/Python 1.2", "set", "x") == "llm_sdk"
    assert acct.caller_class("python-requests/2.31", "set", "x") == "http"
    assert acct.caller_class("Mystery/1.0", "set", "x") == "unknown"
    assert acct.caller_class(None, "set", "x") == "unknown"  # a URL but no user agent is not platform
    # v1 rows carry no user agent or URL: requester decides
    assert acct.caller_class(None, None, "0a1b2c3d-1111-2222-3333-444455556666", source="v1") == "service_principal"
    assert acct.caller_class(None, None, "someone@example.com", source="v1") == "user"
    assert acct.caller_class(None, None, None, source="v1") == "unknown"
    assert acct.caller_class(None, None, "0a1b2c3d-1111-2222-3333-444455556666") == "no_client_info"  # v2 default


V2_EPS = [{"workspace_id": "1", "endpoint_name": "v2-chat", "requests": "120", "requesters": "4",
           "last_request": "2026-10-29 10:00:00", "last_seen": "2026-10-29 10:00:00"},
          {"workspace_id": "1", "endpoint_name": "v2-idle", "requests": "0", "requesters": "0",
           "last_request": None, "last_seen": "2026-08-01 09:00:00"}]
CLASSES = [
    {"source": "v1", "workspace_id": "1", "endpoint_name": "databricks-gpt-5-5",
     "requester": "0a1b2c3d-1111-2222-3333-444455556666", "requests": "20000"},
    {"source": "v2", "workspace_id": "1", "endpoint_name": "v2-chat", "user_agent": None, "url": None,
     "requester": "system", "requests": "100"},
    {"source": "v2", "workspace_id": "1", "endpoint_name": "v2-chat", "user_agent": "agent/claude-code databricks-sdk-py",
     "url": "set", "requester": "dev@example.com", "requests": "20"},
]


def test_v2_endpoints_are_legacy_endpoints_with_their_own_kind():
    res = acct.build([], [], [{"workspace_id": "1", "v3_requests": "0", "v2_requests": "120", "v3_requesters": "0"}],
                     WS[:1], 30, v2_endpoints=V2_EPS)
    by = _by(res)
    assert by["1"]["legacy_endpoints"] == 2 and by["1"]["v2_endpoints"] == 2
    assert by["1"]["v1_requests"] == 0 and by["1"]["v2_requests"] == 120  # v2 traffic is not counted as v1
    assert by["1"]["active_legacy_endpoints"] == 1 and by["1"]["wave"] == "v2 traffic"
    kinds = {e["endpoint_name"]: e["kind"] for e in res["endpoints"]}
    assert kinds == {"v2-chat": acct.V2_KIND, "v2-idle": acct.V2_KIND}
    idle = next(e for e in res["endpoints"] if e["endpoint_name"] == "v2-idle")
    assert idle["traffic_status"].startswith("no requests in 30 days; last seen 2026-08-01")
    assert "v2 workspace endpoint" in acct.summary_md(res)


def test_customer_owned_split_and_enforce_readiness_lines():
    ug_v2 = [{"workspace_id": "1", "v3_requests": "80000", "v3_requesters": "9", "v2_requests": "120"}]
    res = acct.build(INV, V1, ug_v2, WS, 30, v2_endpoints=V2_EPS, classes=CLASSES)
    by = _by(res)
    assert by["1"]["platform_requests"] == 100 and by["1"]["coding_agent_requests"] == 20
    # legacy = v1 + v2; customer-owned = everything except platform
    assert by["1"]["legacy_requests"] == 20120
    assert by["1"]["legacy_requests"] - by["1"]["platform_requests"] == by["1"]["customer_requests"]
    md = acct.summary_md(res)
    assert "## Customer-owned vs Databricks-managed traffic" in md
    assert "Databricks-managed: **100**" in md and "floor" in md
    assert "**Blocking**: **1** running workspaces" in md
    # Platform-only traffic on a v2 endpoint is a warning, not a blocker
    managed = acct.build([], [], [{"workspace_id": "1", "v3_requests": "0", "v2_requests": "5", "v3_requesters": "0"}],
                         WS[:1], 30, v2_endpoints=[{"workspace_id": "1", "endpoint_name": "x", "requests": "5",
                                                     "requesters": "1", "last_request": None, "last_seen": None}],
                         classes=[{"source": "v2", "workspace_id": "1", "endpoint_name": "x", "user_agent": None,
                                   "url": None, "requester": "system", "requests": "5"}])
    assert _by(managed)["1"]["platform_requests"] == 5 and _by(managed)["1"]["customer_requests"] == 0
    md = acct.summary_md(managed)
    assert "**Warning**: **1** running workspaces" in md and "**Blocking**: **0**" in md


def test_snapshot_adds_caller_columns_to_old_tables(monkeypatch):
    calls = []

    def fake_sql(w, wh, sql, params=None):
        calls.append(sql)
        if sql.startswith("DESCRIBE"):
            return [{"col_name": "snapshot_time"}, {"col_name": "workspace_id"}]
        return []

    monkeypatch.setattr(planner, "_sql", fake_sql)
    result = {"days": 30, "workspaces": [{"workspace_id": "1", "wave": "v2 traffic", "customer_requests": 5,
                                          "platform_requests": 2, "coding_agent_requests": 0}],
              "endpoints": [{"workspace_id": "1", "endpoint_name": "v2-chat", "kind": acct.V2_KIND, "requests": 3,
                             "customer_requests": 1, "platform_requests": 2, "coding_agent_requests": 0}]}
    acct.write_snapshot(object(), "wh", "c.s.ug_migration", result, "run-x", 1761904800)
    for table in ("c.s.ug_migration_workspaces", "c.s.ug_migration_endpoints"):
        for col in ("customer_requests BIGINT", "platform_requests BIGINT", "coding_agent_requests BIGINT"):
            assert any(s.startswith(f"ALTER TABLE {table} ADD COLUMNS ({col})") for s in calls), (table, col)
    assert any(acct.V2_KIND in s for s in calls if s.startswith("INSERT"))


def test_v2_wave_name_and_old_names_map_for_snapshots():
    assert acct.W_V2 == "v2 traffic" and "v2 first" not in acct.WAVE_MEANING
    assert acct.LEGACY_WAVE_NAMES == {"v2 first": "v2 traffic", "0: enforce candidate": "0: no legacy traffic"}


def test_run_passes_deadline_and_classes_to_the_build(monkeypatch, tmp_path):
    def fake_sql(w, wh, sql, params=None):
        if "served_entities" in sql and "latest" in sql:
            return INV
        if "endpoint_usage" in sql and "requester" in sql and "GROUP BY eu.workspace_id, se.endpoint_id, eu.requester" in sql:
            return [{k: v for k, v in r.items() if k != "source"} for r in CLASSES if r["source"] == "v1"]
        if "ai_gateway.usage" in sql and "GROUP BY 1, 2, 3, 4, 5" in sql:
            return [{k: v for k, v in r.items() if k != "source"} for r in CLASSES if r["source"] == "v2"]
        if "ai_gateway.usage" in sql and "GROUP BY workspace_id, endpoint_name" in sql:
            return V2_EPS
        if "ai_gateway.usage" in sql:
            return UG
        if "endpoint_usage" in sql:
            return V1
        if "workspaces_latest" in sql:
            return WS
        return []

    monkeypatch.setattr(planner, "_sql", fake_sql)
    res = acct.run(object(), "wh", str(tmp_path), days=30, deadline="2027-05-15")
    assert res["errors"] == [] and res["deadline"] == "2027-05-15"
    md = (tmp_path / "ACCOUNT_SUMMARY.md").read_text()
    assert "stop serving: **2027-05-15**" in md
    with open(tmp_path / "account_endpoints.csv") as f:
        assert any(acct.V2_KIND in line for line in f)
    with pytest.raises(ValueError):
        acct.run(object(), "wh", str(tmp_path / "bad"), days=30, deadline="next spring")



def test_calls_with_no_client_info_count_as_customer_owned_and_block():
    res = acct.build([], [], [{"workspace_id": "1", "v3_requests": "0", "v2_requests": "5", "v3_requesters": "0"}],
                     WS[:1], 30, v2_endpoints=[{"workspace_id": "1", "endpoint_name": "x", "requests": "5",
                                                 "requesters": "1", "last_request": None, "last_seen": None}],
                     classes=[{"source": "v2", "workspace_id": "1", "endpoint_name": "x", "user_agent": None,
                               "url": None, "requester": "analyst@example.com", "requests": "5"}])
    assert _by(res)["1"]["platform_requests"] == 0 and _by(res)["1"]["customer_requests"] == 5
    assert "**Blocking**: **1** running workspaces" in acct.summary_md(res)


def test_tokens_and_v2_failures_per_workspace_and_endpoint():
    ug = [{"workspace_id": "4", "v3_requests": "0", "v3_requesters": "0", "v2_requests": "100", "v2_failed": "96",
           "v2_tokens": "5000"},
          {"workspace_id": "2", "v3_requests": "0", "v3_requesters": "0", "v2_requests": "100", "v2_failed": "5",
           "v2_tokens": "10"}]
    v2_eps = [{"workspace_id": "4", "endpoint_name": "proj-v2", "requests": "100", "requesters": "2",
               "tokens": "4000", "last_request": "2026-10-30", "last_seen": "2026-10-30 10:00:00"}]
    res = acct.build(INV, V1, ug, WS, 30, v2_endpoints=v2_eps)
    by = _by(res)
    assert by["4"]["v2_failed"] == 96 and by["4"]["v2_tokens"] == 5000 and by["4"]["legacy_tokens"] == 5000
    assert by["1"]["legacy_tokens"] == 1000 and by["1"]["v2_failed"] == 0  # v1 tokens are the endpoint's tokens
    assert by["2"]["legacy_tokens"] == 10  # v2 tokens only: old-ep is deleted, so its traffic is kept apart
    ep = next(e for e in res["endpoints"] if e["endpoint_name"] == "proj-v2")
    assert ep["legacy_tokens"] == 4000 and ep["kind"] == "v2_workspace_endpoint"
    assert "tokens" not in ep  # the endpoint column is legacy_tokens everywhere
    md = acct.summary_md(res)
    assert "v2 failing: 96 of 100 requests" in md and "**1 workspace**" in md
    assert "Tokens in the last 30 days (input and output, v1 and v2): **" in md
    assert acct._v2_failing(by["2"]) is False and acct._v2_failing(by["4"]) is True
    assert "legacy_tokens" in acct.SNAPSHOT_COLUMNS["endpoints"] and "tokens" not in acct.SNAPSHOT_COLUMNS["endpoints"]
    assert "v2_failed" in acct.SNAPSHOT_COLUMNS["workspaces"] and "v2_tokens" in acct.SNAPSHOT_COLUMNS["workspaces"]
    assert "v2_failed" in acct.NUMERIC and "v2_tokens" in acct.NUMERIC and "legacy_tokens" in acct.NUMERIC
