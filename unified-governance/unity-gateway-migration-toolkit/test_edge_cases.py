"""Adversarial offline tests for the UG migrator prototype (review5).

Assertions state the EXPECTED (safe / graceful) behaviour. A failing test is a finding.
"""

import csv
import json
from dataclasses import asdict
from unittest import mock

import pytest

import ug_migration_account as acct
import ug_migration_apply as a
import ug_migration_planner as m
from test_planner import _ep


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def ext_entity(name, model="gpt-5", task="llm/v1/chat", key="{{secrets/llm/openai}}"):
    return {"name": name, "external_model": {"provider": "openai", "name": model, "task": task,
                                             "openai_config": {"openai_api_key": key}}}


def ext_ep(name, entities, routes=None, fallback=False, gw=None):
    payload = {"name": name, "id": "id-" + name,
               "config": {"served_entities": entities,
                          "traffic_config": {"routes": routes or []}},
               "ai_gateway": {**(gw or {}), "fallback_config": {"enabled": fallback}}}
    return _ep(payload)


def build_for(ep):
    rows, providers = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    return rows, a.build_model_service(ep, rows[0], fqn)


def scan(names, text, sys_map=None, asset_type="notebook", asset="nb"):
    s = m.Scanner(names, sys_map or {}, [])
    s.scan_text(asset_type, asset, text)
    return s.refs


# ---------------------------------------------------------------------------
# Scanner: names, regex metacharacters, substrings
# ---------------------------------------------------------------------------

def test_scanner_prefix_names_resolve_to_longest_quoted_name():
    names = ["gpt", "gpt-5", "databricks-gpt-5-5"]
    text = "model: gpt-5\nspark.sql(\"SELECT ai_query('gpt', 'x')\")\nc = 'databricks-gpt-5-5'\n"
    got = sorted(r.legacy_endpoint for r in scan(names, text))
    assert got == ["databricks-gpt-5-5", "gpt", "gpt-5"]


def test_scanner_regex_metacharacters_in_name_are_literal():
    names = ["a.b+c(", "a.b"]
    refs = scan(names, "x = 'a.b+c('\ny = 'aXb'\n")
    assert [r.legacy_endpoint for r in refs] == ["a.b+c("]


def test_scanner_empty_endpoint_name_is_ignored():
    # An empty name must not turn every '' or key: value line into a hit.
    refs = scan([""], "x = ''\nkey: \n")
    assert refs == [], [r.match for r in refs]


def test_scanner_ai_query_fix_does_not_touch_ai_query_keyword():
    # Endpoint named "ai": re.sub rewrites the "ai" inside the ai_query( keyword too.
    refs = scan(["ai"], "df = spark.sql(\"select ai_query('ai', 'hi')\")\n",
                sys_map={"ai": "system.ai.gpt_5"})
    assert refs and refs[0].fixed_line is not None
    assert "ai_query('system.ai.gpt_5', 'hi')" in refs[0].fixed_line, refs[0].fixed_line


def test_scanner_config_value_fix_replaces_value_not_key():
    # Only endpoint-like keys count as config values; the fix replaces the value, never the key.
    assert scan(["gpt"], "gpt: gpt\n", sys_map={"gpt": "system.ai.gpt_5"}, asset_type="config") == []
    refs = scan(["gpt"], "model: gpt\n", sys_map={"gpt": "system.ai.gpt_5"}, asset_type="config")
    assert refs and refs[0].fixed_line == "model: system.ai.gpt_5", refs[0].fixed_line


def test_scanner_multiple_refs_on_one_line():
    refs = scan(["gpt-5", "gpt-5-mini"], "x = [ai_query('gpt-5', 'a'), ai_query('gpt-5-mini', 'b')]\n")
    assert sorted(r.legacy_endpoint for r in refs) == ["gpt-5", "gpt-5-mini"]


# ---------------------------------------------------------------------------
# Scanner: notebooks, multi-line calls, line handling
# ---------------------------------------------------------------------------

def test_ipynb_escaped_double_quotes_ai_query_missed():
    # Code using double quotes inside a notebook cell is stored with \" escapes.
    nb2 = {"cells": [{"cell_type": "code", "source": ["import json\n", "x = ai_query(\"gpt-5\", \"hi\")\n"]}]}
    refs = scan(["gpt-5"], json.dumps(nb2, indent=1), asset="nb.ipynb")
    assert any(r.legacy_endpoint == "gpt-5" for r in refs), "ai_query with \\\" escapes in .ipynb JSON missed"


def test_ipynb_escaped_endpoint_name_missed():
    nb = {"cells": [{"cell_type": "code", "source": ["client.predict(endpoint=\"gpt-5\", inputs=x)\n"]}]}
    refs = scan(["gpt-5"], json.dumps(nb, indent=1), asset="nb.ipynb")
    assert any(r.legacy_endpoint == "gpt-5" for r in refs)


def test_ai_query_split_across_lines_plain_passes():
    refs = scan(["gpt-5"], "SELECT ai_query(\n  'gpt-5',\n  'hi')\n")
    assert [r.line for r in refs if r.pattern == "ai_query"] == [2]


def test_ai_query_split_with_sql_comment_detected_as_ai_query():
    # Without the comment, the call is detected as ai_query (see the plain split test). With it,
    # only the generic legacy_endpoint_name pattern fires and the ai_query guidance is lost.
    refs = scan(["gpt-5"], "SELECT ai_query( -- pick the model\n  'gpt-5', 'hi')\n")
    assert any(r.legacy_endpoint == "gpt-5" and r.pattern == "ai_query" for r in refs), \
        [(r.pattern, r.line) for r in refs]


def test_ai_query_line_numbers_with_form_feed():
    # str.splitlines() treats \f as a line break; text.count("\n") does not. Line numbers diverge.
    # The endpoint name is on physical line 4; every reference should say line 4.
    text = "x = 1\f\ny = 2\nq = ai_query(\n  'gpt-5', 'hi')\n"
    refs = scan(["gpt-5"], text)
    assert {r.line for r in refs} == {4}, [(r.pattern, r.line, r.line_text) for r in refs]


def test_long_line_truncated_at_5000_drops_reference():
    text = "x = '" + "a" * 5990 + "'; y = ai_query('gpt-5', 'hi')\n"
    refs = scan(["gpt-5"], text)
    assert any(r.legacy_endpoint == "gpt-5" for r in refs), "reference past column 5000 silently dropped"


def test_crlf_and_tabs_scan_correctly():
    refs = scan(["gpt-5"], "a =\t1\r\nb = ai_query('gpt-5', 'x')\r\n")
    assert [r.line for r in refs] == [2]


def test_references_in_comments_and_strings_are_reported():
    # Informational: a reference inside a comment or string is still reported (conservative).
    refs = scan(["gpt-5-mini"], "# old: ai_query('gpt-5-mini', 'x')\nmsg = \"use 'gpt-5-mini' later\"\n")
    assert len(refs) == 2


# ---------------------------------------------------------------------------
# Planner: inventory helpers and classification
# ---------------------------------------------------------------------------

def test_classify_none_name_does_not_raise():
    assert m._classify({"name": None, "config": {}})[0] == "unknown"


def test_classify_served_entities_none_and_empty():
    assert m._classify({"name": "x", "config": {"served_entities": None}})[0] == "unknown"
    assert m._classify({"name": "databricks-x", "config": {"served_entities": []}})[0] == "system_ppt"


def test_classify_mixed_entities_become_manual_row():
    payload = {"name": "mix", "id": "m1", "config": {"served_entities": [
        ext_entity("a"), {"name": "b", "entity_name": "main.ml.churn", "entity_version": "1"}]}}
    ep = _ep(payload)
    rows, _ = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].action == "manual"


def test_agent_task_becomes_manual_row():
    payload = {"name": "agent-x", "id": "g1", "task": "agent/v1/chat",
               "config": {"served_entities": [{"name": "x", "entity_name": "main.ml.agent", "entity_version": "1"}]}}
    rows, _ = m.plan([_ep(payload)], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].action == "manual"


def test_guardrail_pii_non_dict_does_not_crash():
    ep = ext_ep("g", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}],
                gw={"guardrails": {"input": {"pii": True}}})
    rows, _ = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].action in ("create_model_service", "manual")


def test_inference_table_missing_catalog_gives_none_parent():
    ep = ext_ep("inf", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}],
                gw={"inference_table_config": {"enabled": True, "table_name_prefix": "p"}})
    rows, _ = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].inference_table is None or "None" not in rows[0].inference_table["parent"], \
        rows[0].inference_table


def test_principal_none_in_can_query_does_not_create_grant():
    payload = _ep({"name": "g", "id": "g2", "config": {"served_entities": [ext_entity("x")]}})
    payload.can_query = [{"principal": None, "principal_type": "service_principal", "levels": ["CAN_QUERY"]}]
    rows, _ = m.plan([payload], {}, {}, "c", "s", traffic_known=False)
    assert all(g["principal"] for g in rows[0].grants), rows[0].grants


def test_hour_renewal_rate_limit_must_not_become_minute():
    # Legacy "100 per hour" is written as "per minute" (60x looser) and apply uses it without checking needs.
    ep = ext_ep("h", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}],
                gw={"rate_limits": [{"key": "endpoint", "calls": 100, "renewal_period": "hour"}]})
    rows, body = build_for(ep)
    # Unity Gateway supports hourly limits: the period must be kept, never widened to per minute.
    assert [l["renewal_period"] for l in body["config"]["rate_limits"]] == ["RATE_LIMIT_RENEWAL_PERIOD_HOUR"]


def test_unknown_rate_limit_key_must_block_not_drop():
    ep = ext_ep("u", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}],
                gw={"rate_limits": [{"key": "bogus", "calls": 5, "renewal_period": "minute"}]})
    with pytest.raises(a.Manual):
        build_for(ep)


def test_planner_name_collision_after_sanitising_is_flagged():
    eps = [ext_ep("Proj-A", [ext_entity("p")]), ext_ep("proj_a", [ext_entity("p")])]
    rows, _ = m.plan(eps, {}, {}, "c", "s", traffic_known=False)
    targets = [r.target_service for r in rows]
    assert len(set(targets)) == len(targets) or all(r.action == "manual" for r in rows), targets


def test_identical_duplicate_endpoint_is_flagged():
    ep1 = ext_ep("dup", [ext_entity("p")])
    ep2 = ext_ep("dup", [ext_entity("p")])
    rows, _ = m.plan([ep1, ep2], {}, {}, "c", "s", traffic_known=False)
    # Can't happen within one workspace, but must never produce two plans for one target.
    assert len({r.target_service for r in rows}) == 2 and any("already taken" in n for n in rows[1].needs_human)


def test_target_name_longer_than_uc_limit_flagged():
    long = "x" * 300
    rows, _ = m.plan([ext_ep(long, [ext_entity("p")])], {}, {}, "c", "s", traffic_known=False)
    assert len(rows[0].target_service.split(".")[-1]) <= 255 or rows[0].action == "manual"


def test_traffic_routes_name_mismatch_consistent_with_non_fallback():
    # Routes don't match entity names. Without fallback this raises Manual; with fallback it silently
    # picks the first destination.
    ents = [ext_entity("p1", model="gpt-5"), ext_entity("p2", model="gpt-5-mini")]
    routes = [{"served_entity_name": "zzz", "traffic_percentage": 100}]
    ep = ext_ep("mm", ents, routes=routes, fallback=True)
    with pytest.raises(a.Manual):
        build_for(ep)


def test_zero_traffic_all_destinations_must_not_create_empty_routing():
    ents = [ext_entity("p1"), ext_entity("p2", model="gpt-5-mini")]
    routes = [{"served_entity_name": "p1", "traffic_percentage": 0},
              {"served_entity_name": "p2", "traffic_percentage": 0}]
    ep = ext_ep("zero", ents, routes=routes)
    with pytest.raises(a.Manual):
        build_for(ep)


def test_traffic_percentages_not_summing_to_100_flagged():
    ents = [ext_entity("p1"), ext_entity("p2", model="gpt-5-mini")]
    routes = [{"served_entity_name": "p1", "traffic_percentage": 50},
              {"served_entity_name": "p2", "traffic_percentage": 30}]
    ep = ext_ep("pct", ents, routes=routes)
    with pytest.raises(a.Manual):
        build_for(ep)


def test_fallback_more_than_five_not_silently_truncated():
    ents = [ext_entity(f"e{i}", model=f"gpt-{i}") for i in range(7)]
    routes = [{"served_entity_name": "e0", "traffic_percentage": 100}] + \
             [{"served_entity_name": f"e{i}", "traffic_percentage": 0} for i in range(1, 7)]
    ep = ext_ep("fb7", ents, routes=routes, fallback=True)
    try:
        _, body = build_for(ep)
    except a.Manual:
        return
    total = len(body["config"]["routing"]["destinations"]) + len(body["config"]["routing"]["fallback"]["destinations"])
    assert total == 7, f"{total} of 7 destinations kept"


def test_more_than_ten_destinations_flagged():
    ents = [ext_entity(f"e{i}", model=f"gpt-{i}") for i in range(11)]
    routes = [{"served_entity_name": f"e{i}", "traffic_percentage": 9 if i < 10 else 10} for i in range(11)]
    ep = ext_ep("many", ents, routes=routes)
    try:
        _, body = build_for(ep)
    except a.Manual:
        return
    assert len(body["config"]["routing"]["destinations"]) <= 10


def test_served_entity_names_colliding_after_safe_flagged():
    ents = [ext_entity("gpt-5"), ext_entity("gpt_5", model="gpt-5-mini")]
    routes = [{"served_entity_name": "gpt-5", "traffic_percentage": 50},
              {"served_entity_name": "gpt_5", "traffic_percentage": 50}]
    ep = ext_ep("dupnames", ents, routes=routes)
    try:
        _, body = build_for(ep)
    except a.Manual:
        return
    names = [d["name"] for d in body["config"]["routing"]["destinations"]]
    assert len(names) == len(set(names)), names


# ---------------------------------------------------------------------------
# Planner: inventory with mocked REST, legacy CSV leakage
# ---------------------------------------------------------------------------

def test_raw_api_key_not_written_to_legacy_csv(tmp_path):
    payload = {"name": "raw", "id": "r1", "config": {"served_entities": [
        {"name": "p", "external_model": {"provider": "openai", "name": "gpt-5", "task": "llm/v1/chat",
                                         "openai_config": {"openai_api_key": "sk-live-PLAINTEXT-123"}}}]}}
    ep = _ep(payload)
    out = tmp_path / "legacy_endpoints.csv"
    m._write_csv(str(out), [asdict(ep)])
    assert "sk-live-PLAINTEXT-123" not in out.read_text()


def test_inventory_permission_entry_without_permissions_degrades(monkeypatch):
    summary = {"name": "proj", "id": "e9", "config": {"served_entities": [ext_entity("p")]}}

    def fake_get(w, path, query=None):
        if path.startswith("/api/2.0/serving-endpoints/proj"):
            return summary
        if path.startswith("/api/2.0/permissions"):
            return {"access_control_list": [{"user_name": "a@x.com", "all_permissions": None},
                                            {"group_name": "g", "all_permissions": [{}]}]}
        return {"endpoints": [{"name": "proj"}]}

    monkeypatch.setattr(m, "_get", fake_get)
    eps = m.inventory(mock.MagicMock())
    assert eps and eps[0].name == "proj"


def test_inventory_detail_failure_falls_back_to_summary(monkeypatch):
    def fake_get(w, path, query=None):
        if path == "/api/2.0/serving-endpoints":
            return {"endpoints": [{"name": "databricks-x"}, {"name": "other"}]}
        raise RuntimeError("403")

    monkeypatch.setattr(m, "_get", fake_get)
    eps = {e.name: e for e in m.inventory(mock.MagicMock())}
    assert eps["databricks-x"].kind == "system_ppt" and eps["other"].kind == "unknown"


def test_link_callers_does_not_match_requester_as_substring():
    refs = [m.ClientReference("notebook", "/Users/joanna@corp.com/etl", 3, "ai_query", "x", None,
                              "s", None, None, None)]
    out = m.link_callers([{"requester": "anna@corp.com", "endpoint_name": "e", "requests": 1}], refs, {})
    assert out[0]["linked_count"] == 0, out[0]["linked_code"]


def test_scan_local_utf16_file_not_silently_skipped(tmp_path):
    p = tmp_path / "job.py"
    p.write_bytes("x = ai_query('gpt-5', 'hi')\n".encode("utf-16"))
    s = m.Scanner(["gpt-5"], {}, [])
    m.scan_local(s, [str(tmp_path)])
    assert any(r.legacy_endpoint == "gpt-5" for r in s.refs)


def test_scan_local_binary_file_skipped(tmp_path):
    (tmp_path / "x.py").write_bytes(b"\x00\x01ai_query('gpt-5', 'a')")
    s = m.Scanner(["gpt-5"], {}, [])
    m.scan_local(s, [str(tmp_path)])
    assert s.refs == []


def test_scan_local_identical_copies_counted_once(tmp_path):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "n.py").write_text("x = ai_query('gpt-5', 'hi')\n")
    s = m.Scanner(["gpt-5"], {}, [])
    m.scan_local(s, [str(tmp_path)])
    assert len(s.refs) == 1 and "identical copies" in s.refs[0].asset


def test_readiness_and_summaries_empty_inputs_do_not_raise():
    r = m.readiness([], [], True, 30, [])
    assert r["status"] == "READY"
    assert "Enforce" in m.readiness_md("https://x", r, 30)
    assert m.code_fixes_md([]).startswith("# Proposed code fixes")
    assert m.summary_md("https://x", [], [], [], [], 30, False).startswith("# Unity Gateway")


# ---------------------------------------------------------------------------
# Apply: payload builders and secrets
# ---------------------------------------------------------------------------

def test_build_model_service_unmapped_task_raises_manual():
    ep = ext_ep("rr", [ext_entity("p", task="llm/v1/rerank")],
                routes=[{"served_entity_name": "p", "traffic_percentage": 100}])
    rows, providers = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    with pytest.raises(a.Manual):
        a.build_model_service(ep, rows[0], fqn)


def test_rate_limits_and_secret_reference_from_uc_map_pass_through():
    ep = ext_ep("ok", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}],
                gw={"rate_limits": [{"key": "endpoint", "calls": 0, "renewal_period": "minute"}]})
    _, body = build_for(ep)
    assert body["config"]["rate_limits"][0]["requests"] == 0  # zero is a real limit, keep it


def test_mask_nested_plaintext_everywhere():
    obj = {"a": [{"x": {"plaintext": "s1"}}, [{"plaintext": "s2"}]], "plaintext": "s3", "keep": "ok"}
    masked = a._mask(obj)
    assert json.dumps(masked).count("***") == 3 and "s1" not in json.dumps(masked)
    assert obj["plaintext"] == "s3"  # original untouched


def test_secret_key_with_slash_and_read_error_surfaces():
    s = a.Secrets(None, {}, False)
    with pytest.raises(a.Manual):
        s.resolve("{{secrets/scope/a/b}}")


def test_terraform_secret_variable_collision_gives_wrong_secret():
    ts = a.TerraformSecrets(None)
    r1 = ts.resolve("{{secrets/s/abc-def}}")["plaintext"]
    r2 = ts.resolve("{{secrets/s/abc_def}}")["plaintext"]
    assert str(r1) != str(r2), f"both providers reference {r1}"


def test_terraform_provider_key_variable_shared_by_two_keys():
    ts = a.TerraformSecrets(None)
    r1 = ts.resolve(None, plaintext="x")
    r2 = ts.resolve("not-a-ref")
    assert str(r1["plaintext"]) != str(r2["plaintext"])


def test_to_hcl_emoji_surrogates_are_invalid_hcl():
    out = a.to_hcl("launch \U0001F680")
    assert "\\ud83d" not in out, out  # JSON emits surrogate pairs, which HCL rejects


def test_to_hcl_dollar_and_percent_escaped():
    out = a.to_hcl('a"b\\c${x}%{y}')
    assert "$${x}" in out and "%%{y}" in out


def test_to_hcl_key_with_space_is_quoted_or_rejected():
    try:
        out = a.to_hcl({"a b": 1})
    except TypeError:
        return
    assert '"a b"' in out, out


def test_to_hcl_none_raises_type_error_only():
    # Informational: None has no HCL form, so this raises TypeError rather than emitting null.
    with pytest.raises(TypeError):
        a.to_hcl({"x": None})


def test_terraform_catalog_with_dot_raises_valueerror(tmp_path, monkeypatch):
    ep = ext_ep("tfdot", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}])
    monkeypatch.setattr(a.planner, "inventory", lambda w: [ep])
    w = mock.MagicMock()
    try:
        res = a.terraform(w, None, "my.cat", "s", None, str(tmp_path / "out.tf"))
    except SystemExit:
        return
    assert res["skipped"], res


def test_rollback_survives_truncated_log_line(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"type": "model_service", "name": "c.s.good", "action": "created"}) + "\n"
                   + '{"type": "model_serv')  # partial write from a crash
    out = a.rollback(mock.MagicMock(), str(log), execute=False)
    assert any(o["name"] == "c.s.good" for o in out)


def test_dry_run_apply_writes_no_log(tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    ep = ext_ep("dry", [ext_entity("p")], routes=[{"served_entity_name": "p", "traffic_percentage": 100}])
    monkeypatch.setattr(a.planner, "inventory", lambda w: [ep])
    w = mock.MagicMock()
    w.schemas.get.return_value = None
    from databricks.sdk.errors import NotFound
    w.ai_gateway.get_model_provider_service.side_effect = NotFound("nope")
    w.ai_gateway.get_model_service.side_effect = NotFound("nope")
    res = a.apply(w, None, "c", "s", False, a.Secrets(None, {"llm/openai": "secrets/c.s.k"}, False, allowed_schemas=["c.s"]), str(log))
    assert not log.exists()
    assert any(r["action"] == "would_create" for r in res)


# ---------------------------------------------------------------------------
# Account view
# ---------------------------------------------------------------------------

def _inv(ep="gpt"):
    return [{"workspace_id": "1", "endpoint_name": ep, "entity_type": "FOUNDATION_MODEL", "is_pt": "false"}]


def _v1(req):
    return [{"workspace_id": "1", "endpoint_name": "gpt", "requests": req, "requesters": "2",
             "throttled": "0", "tokens": "10", "last_request": "2026-10-30"}]


def test_account_float_string_request_counts_not_zeroed():
    res = acct.build(_inv(), _v1("20000.0"), [], [{"workspace_id": "1", "workspace_name": "ws1"}], 30)
    ws = res["workspaces"][0]
    assert ws["legacy_requests"] == 20000 and ws["wave"] == "2: high volume", ws


def test_account_missing_workspace_metadata_is_ok():
    res = acct.build(_inv(), _v1("5"), [], [], 30)
    assert res["workspaces"][0]["workspace_name"] is None
    assert "Workspaces with" in acct.summary_md(res)


def test_account_int_and_str_workspace_ids_join():
    inv = [{"workspace_id": 1, "endpoint_name": "gpt", "entity_type": "FOUNDATION_MODEL", "is_pt": "false"}]
    ws = [{"workspace_id": "1", "workspace_name": "ws1", "workspace_url": "u", "status": "RUNNING"}]
    res = acct.build(inv, [], [], ws, 30)
    assert res["workspaces"][0]["workspace_name"] == "ws1"


def test_account_summary_empty_inputs_do_not_raise():
    res = acct.build([], [], [], [], 30)
    assert "Legacy model endpoints in scope (live): **0**" in acct.summary_md(res)


def test_account_summary_pipe_in_workspace_name_escaped():
    inv = _inv()
    ws = [{"workspace_id": "1", "workspace_name": "Team | Prod", "workspace_url": "u", "status": "RUNNING"}]
    md = acct.summary_md(acct.build(inv, _v1("5"), [], ws, 30))
    row = [l for l in md.splitlines() if "Team" in l and "Prod" in l and l.startswith("| Team")]
    assert row and row[0].replace("\\|", "").count("|") == 10, row  # 9 columns; the name's pipe is escaped


def test_account_duplicate_traffic_rows_are_summed_not_overwritten():
    res = acct.build(_inv(), _v1("5") + _v1("7"), [], [], 30)
    assert res["endpoints"][0]["requests"] == 12


def test_account_collision_across_workspaces_listed():
    inv = [{"workspace_id": w, "endpoint_name": "churn", "entity_type": "CUSTOM_MODEL"} for w in "12"] + \
          [{"workspace_id": w, "endpoint_name": "proj", "entity_type": "EXTERNAL_MODEL", "provider": "openai"}
           for w in "12"]
    res = acct.build(inv, [], [], [], 30)
    assert [c["endpoint_name"] for c in res["collisions"]] == ["proj"]
