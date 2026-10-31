"""Offline tests for the account-wide view."""

import ug_migration_account as acct

INV = [
    {"workspace_id": "1", "endpoint_name": "databricks-gpt-5-5", "entity_type": "FOUNDATION_MODEL", "is_pt": "false"},
    {"workspace_id": "1", "endpoint_name": "proj-gpt", "entity_type": "EXTERNAL_MODEL", "provider": "openai", "is_pt": "false"},
    {"workspace_id": "2", "endpoint_name": "proj-gpt", "entity_type": "EXTERNAL_MODEL", "provider": "openai", "is_pt": "false"},
    {"workspace_id": "2", "endpoint_name": "llama-pt", "entity_type": "FOUNDATION_MODEL", "is_pt": "true"},
    {"workspace_id": "3", "endpoint_name": "churn", "entity_type": "CUSTOM_MODEL", "is_pt": "false"},
]
V1 = [{"workspace_id": "1", "endpoint_name": "databricks-gpt-5-5", "requests": "20000", "requesters": "3",
       "throttled": "50", "tokens": "1000", "last_request": "2026-10-30"},
      {"workspace_id": "2", "endpoint_name": "old-ep", "requests": "5", "requesters": "1", "throttled": "0",
       "tokens": "1", "last_request": "2026-10-01"}]
UG = [{"workspace_id": "1", "v3_requests": "80000", "v3_requesters": "9", "v2_requests": "0"},
      {"workspace_id": "4", "v3_requests": "10", "v3_requesters": "1", "v2_requests": "3"}]
WS = [{"workspace_id": w, "workspace_name": f"ws{w}", "workspace_url": f"adb-{w}.azuredatabricks.net", "status": "RUNNING"}
      for w in "1234"]


def test_classify():
    assert [acct.classify(r) for r in INV] == ["system_ppt", "external_model", "external_model",
                                              "provisioned_throughput", "out_of_scope"]


def test_build_waves_and_collisions():
    res = acct.build(INV, V1, UG, WS, 30)
    by = {w["workspace_id"]: w for w in res["workspaces"]}
    assert by["1"]["wave"] == "2: high volume" and by["1"]["v3_share"] == 0.8
    assert by["2"]["wave"] == "1: small" and by["2"]["custom_legacy_endpoints"] == 2
    assert by["3"]["wave"] == "0: enforce candidate"  # only a custom ML model
    assert by["4"]["wave"] == "v2 first"
    assert res["workspaces"][0]["workspace_id"] == "1"  # busiest first
    assert res["collisions"] == [{"endpoint_name": "proj-gpt", "workspaces": ["1", "2"], "count": 2}]
    assert any(e["endpoint_name"] == "old-ep" and e["kind"] == "deleted_or_unknown" for e in res["endpoints"])
    md = acct.summary_md(res)
    assert "Name collisions" in md and "(80% of model traffic on Unity Gateway)" in md


def test_profiles_for(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.write_text("[DEFAULT]\nhost = https://adb-1.azuredatabricks.net\n\n[other]\nhost = https://adb-2.azuredatabricks.net/\n")
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
    assert acct._profiles_for("https://adb-2.azuredatabricks.net") == ["other"]
    assert acct._profiles_for("adb-1.azuredatabricks.net") == ["DEFAULT"]
