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
    assert by["3"]["wave"] == "0: no legacy traffic"  # only a custom ML model
    assert by["4"]["wave"] == "v2 first"
    assert res["workspaces"][0]["workspace_id"] == "1"  # busiest first
    assert res["collisions"] == [{"endpoint_name": "proj-gpt", "workspaces": ["1", "2"], "count": 2}]
    assert any(e["endpoint_name"] == "old-ep" and e["kind"] == "deleted_or_unknown" for e in res["endpoints"])
    md = acct.summary_md(res)
    assert "Name collisions" in md and "(80% of model traffic on Unity Gateway)" in md


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
    # Wave 0 candidates only (workspaces 3 and 7); the stopped workspace 8 is never a candidate.
    assert [o["workspace_id"] for o in out if o["status"] == "ok"] == ["3", "7"]
    assert out[0]["principal"] == "sp-scanner" and seen == ["3", "7"]  # each connection checked against its ID
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
    assert ws["wave"] == "v2 first" and ws["due_for"] == "v2" and ws["due_date"] == "2026-11-30"
    assert out["kpis"]["running_workspaces"] == 1 and out["kpis"]["legacy_requests"] == 3
    assert main_mod._wave({"wave": "0: enforce candidate"}) == "0: no legacy traffic"


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
