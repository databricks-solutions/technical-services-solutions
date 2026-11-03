"""Offline tests for ug_migration_planner using synthetic endpoint payloads."""

import base64
import inspect
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest import mock

import pytest

import ug_migration_planner as m

SYSTEM_PPT = {"name": "databricks-gpt-5-5", "id": "e1",
              "config": {"served_entities": [{"name": "databricks-gpt-5-5",
                                              "foundation_model": {"name": "databricks-gpt-5-5"}}]},
              "ai_gateway": {"rate_limits": [{"key": "user", "calls": 10, "renewal_period": "minute"}]}}

EXTERNAL = {"name": "proj-a-gpt", "id": "e2", "creator": "a@x.com",
            "config": {"served_entities": [
                {"name": "primary", "external_model": {"provider": "openai", "name": "gpt-5", "task": "llm/v1/chat",
                                                       "openai_config": {"openai_api_key": "{{secrets/llm/openai}}"}}},
                {"name": "backup", "external_model": {"provider": "openai", "name": "gpt-5-mini", "task": "llm/v1/chat",
                                                      "openai_config": {"openai_api_key": "{{secrets/llm/openai}}"}}}],
                "traffic_config": {"routes": [{"served_model_name": "primary", "traffic_percentage": 100},
                                              {"served_model_name": "backup", "traffic_percentage": 0}]}},
            "ai_gateway": {"rate_limits": [{"key": "endpoint", "calls": 100, "renewal_period": "minute"},
                                           {"key": "user_group", "principal": "data-sci", "tokens": 5000,
                                            "renewal_period": "minute"},
                                           {"key": "service_principal", "principal": "abc-123", "calls": 5,
                                            "renewal_period": "minute"}],
                           "guardrails": {"input": {"pii": {"behavior": "BLOCK"}}},
                           "inference_table_config": {"catalog_name": "main", "schema_name": "logs",
                                                      "table_name_prefix": "proj_a", "enabled": True},
                           "fallback_config": {"enabled": True}}}

EXTERNAL_SAME_KEY = {"name": "proj-b-gpt", "id": "e3",
                     "config": {"served_entities": [
                         {"name": "x", "external_model": {"provider": "openai", "name": "gpt-5", "task": "llm/v1/chat",
                                                          "openai_config": {"openai_api_key": "{{secrets/llm/openai}}"}}}]}}

PT = {"name": "llama-pt", "id": "e4",
      "config": {"served_entities": [{"name": "llama", "entity_name": "system.ai.llama_v3_3_70b_instruct",
                                      "entity_version": "1", "min_provisioned_throughput": 0,
                                      "max_provisioned_throughput": 9500}]}}

CUSTOM = {"name": "churn-model", "id": "e5",
          "config": {"served_entities": [{"name": "churn", "entity_name": "main.ml.churn", "entity_version": "3"}]}}


def _ep(payload, can_query=None):
    kind, dest = m._classify(payload)
    gw = payload.get("ai_gateway") or {}
    return m.LegacyEndpoint(
        name=payload["name"], endpoint_id=payload["id"], kind=kind, destinations=dest,
        traffic_routes=((payload.get("config") or {}).get("traffic_config") or {}).get("routes") or [],
        rate_limits=gw.get("rate_limits") or [], guardrails=gw.get("guardrails"),
        inference_table=gw.get("inference_table_config"),
        fallback_enabled=bool((gw.get("fallback_config") or {}).get("enabled")),
        usage_tracking=(gw.get("usage_tracking_config") or {}).get("enabled"),
        gateway_settings=sorted(k for k, v in gw.items() if v),
        can_query=can_query or [])


def test_classify():
    assert m._classify(SYSTEM_PPT)[0] == "system_ppt"
    assert m._classify(EXTERNAL)[0] == "external_model"
    assert m._classify(PT)[0] == "provisioned_throughput"
    assert m._classify(CUSTOM)[0] == "custom_model"
    assert m._classify({"name": "databricks-claude-x"})[0] == "system_ppt"


def test_rate_limits():
    out, issues = m._translate_rate_limits(EXTERNAL["ai_gateway"]["rate_limits"])
    assert [o["key"] for o in out] == ["RATE_LIMIT_KEY_SERVICE", "RATE_LIMIT_KEY_USER_GROUP",
                                       "RATE_LIMIT_KEY_SERVICE_PRINCIPAL"]
    assert out[0]["requests"] == 100 and out[1]["tokens"] == 5000 and out[1]["principal"] == "data-sci"
    assert not issues
    out, _ = m._translate_rate_limits(SYSTEM_PPT["ai_gateway"]["rate_limits"])
    assert out[0]["key"] == "RATE_LIMIT_KEY_USER_DEFAULT"


TRACKED_A = {**EXTERNAL, "ai_gateway": {**EXTERNAL["ai_gateway"], "usage_tracking_config": {"enabled": True}}}
TRACKED_B = {**EXTERNAL_SAME_KEY, "ai_gateway": {"usage_tracking_config": {"enabled": True}}}


def test_plan():
    eps = [_ep(SYSTEM_PPT), _ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}]),
           _ep(EXTERNAL_SAME_KEY), _ep(PT), _ep(CUSTOM)]
    sys_map = {"databricks-gpt-5-5": "system.ai.gpt-5-5"}
    rows, providers = m.plan(eps, sys_map, {"proj-a-gpt": {"requests": 7, "requesters": 2, "last_request": "x"}},
                             "ai_gateway", "migrated")
    by = {r.legacy_endpoint: r for r in rows}
    assert by["databricks-gpt-5-5"].action == "use_system_ai"
    assert by["databricks-gpt-5-5"].target_service == "system.ai.gpt-5-5"
    assert any("shared across" in n for n in by["databricks-gpt-5-5"].needs_human)
    a = by["proj-a-gpt"]
    assert a.action == "create_model_service" and a.target_service == "ai_gateway.migrated.proj_a_gpt"
    assert len(a.routing["destinations"]) == 2 and a.routing["fallback"]
    assert a.routing["destinations"][0]["traffic_percentage"] == 100
    assert a.inference_table["parent"] == "schemas/main.logs"
    assert a.grants == [{"principal": "data-sci", "principal_type": "group", "privileges": ["EXECUTE"]}]
    # Guardrails block apply until they are acknowledged (ack_guardrails), and name the replacement policy.
    assert any(n.startswith(m.BLOCKING_PREFIX) and "system.ai.detect_sensitive_data" in n for n in a.needs_human)
    assert a.requests_window == 7
    # Both OpenAI endpoints share one secret, so one provider service.
    assert len(providers) == 1 and providers[0]["secrets"] == ["llm/openai"]
    assert providers[0]["legacy_endpoints"] == ["proj-a-gpt", "proj-b-gpt"]
    assert by["llama-pt"].routing["destinations"][0]["model_serving_endpoint"] == "serving-endpoints/llama-pt"
    assert by["churn-model"].action == "out_of_scope"


def test_scanner():
    eps = [_ep(SYSTEM_PPT), _ep(EXTERNAL)]
    rows, _ = m.plan(eps, {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "ai_gateway", "migrated")
    s = m.Scanner([e.name for e in eps], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, rows)
    s.scan_text("notebook", "/n", "\n".join([
        "SELECT ai_query('databricks-gpt-5-5', prompt) FROM t",
        "SELECT ai_query('system.ai.gpt-5-5', prompt) FROM t",
        "client = OpenAI(base_url=f'{host}/serving-endpoints', api_key=t)",
        "client.chat.completions.create(model='proj-a-gpt', messages=m)",
        "requests.post(f'{host}/serving-endpoints/proj-a-gpt/invocations')",
        "llm = ChatDatabricks(endpoint='databricks-gpt-5-5')",
        "judge = 'endpoints:/databricks-gpt-5-5'",
        "x = 'nothing here'",
    ]))
    pats = [(r.line, r.pattern, r.legacy_endpoint) for r in s.refs]
    assert (1, "ai_query", "databricks-gpt-5-5") in pats
    assert not any(line == 2 for line, *_ in pats)
    assert (3, "serving_endpoints_url", None) in pats
    assert (4, "legacy_endpoint_name", "proj-a-gpt") in pats
    assert (5, "serving_endpoints_url", "proj-a-gpt") in pats
    assert not any(line == 5 and p == "legacy_endpoint_name" for line, p, _ in pats)
    assert (6, "ChatDatabricks", "databricks-gpt-5-5") in pats
    assert (7, "mlflow_endpoint_uri", "databricks-gpt-5-5") in pats
    assert not any(line == 8 for line, *_ in pats)
    ai = next(r for r in s.refs if r.pattern == "ai_query")
    assert ai.suggestion.startswith("ai_query('system.ai.gpt-5-5', ...)") and "usage tracking only" in ai.suggestion


def test_grants_skip_workspace_groups():
    acl = [{"principal": "admins", "principal_type": "group", "levels": ["CAN_MANAGE"]},
           {"principal": "users", "principal_type": "group", "levels": ["CAN_QUERY"]},
           {"principal": "owner@x.com", "principal_type": "user", "levels": ["CAN_MANAGE"]}]
    rows, _ = m.plan([_ep(EXTERNAL_SAME_KEY, acl)], {}, {}, "c", "s")
    assert rows[0].grants == [{"principal": "owner@x.com", "principal_type": "user", "privileges": ["EXECUTE", "MANAGE"]}]
    assert any("all workspace users" in n for n in rows[0].needs_human)


def test_dependencies_block_enforce():
    rows, _ = m.plan([_ep(SYSTEM_PPT), _ep(EXTERNAL)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s")
    refs = [m.ClientReference("vector_search_index", "index main.rag.docs", None, "embedding_endpoint",
                              "databricks-gpt-5-5", "databricks-gpt-5-5", "x"),
            m.ClientReference("app", "app chat-app", None, "app_serving_endpoint_resource", "proj-a-gpt",
                              "proj-a-gpt", "x")]
    m.annotate_dependencies(rows, refs)
    by = {r.legacy_endpoint: r for r in rows}
    assert any("main.rag.docs" in n and "blocks Enforce" in n for n in by["databricks-gpt-5-5"].needs_human)
    assert any("chat-app" in n for n in by["proj-a-gpt"].needs_human)


def test_code_fixes():
    eps = [_ep(SYSTEM_PPT), _ep(EXTERNAL)]
    sysmap = {"databricks-gpt-5-5": "system.ai.gpt-5-5"}
    rows, _ = m.plan(eps, sysmap, {}, "c", "s")
    s = m.Scanner([e.name for e in eps], sysmap, rows)
    s.scan_text("notebook", "/n", "\n".join([
        "SELECT ai_query('databricks-gpt-5-5', p) FROM t",
        "judge = 'endpoints:/databricks-gpt-5-5'",
        "llm = ChatDatabricks(endpoint='databricks-gpt-5-5')",
        "client = OpenAI(base_url=f'{host}/serving-endpoints', api_key=t)",
        "r = requests.post(f'{host}/serving-endpoints/proj-a-gpt/invocations')",
    ]))
    fix = {r.line: (r.fixed_line, r.fix_confidence) for r in s.refs}
    assert fix[1] == ("SELECT ai_query('system.ai.gpt-5-5', p) FROM t", "review")
    assert fix[2] == ("judge = 'databricks:/system.ai.gpt-5-5'", "review")
    assert fix[3][0] == "llm = ChatDatabricks(model='system.ai.gpt-5-5', use_ai_gateway=True)"
    assert fix[4][0] == "client = OpenAI(base_url=f'{host}/ai-gateway/mlflow/v1', api_key=t)"
    # Chat-style /invocations bodies change shape, so the line is left for a person to edit.
    assert fix[5] == (None, None)
    inv = next(r for r in s.refs if r.line == 5)
    assert "body changes to OpenAI chat format" in inv.suggestion
    md = m.code_fixes_md(s.refs)
    assert "- SELECT ai_query('databricks-gpt-5-5', p) FROM t" in md and "+ SELECT ai_query('system.ai.gpt-5-5', p) FROM t" in md


def test_readiness():
    rows, _ = m.plan([_ep(SYSTEM_PPT), _ep(EXTERNAL), _ep(EXTERNAL_SAME_KEY)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"},
                     {"databricks-gpt-5-5": {"requests": 3, "requesters": 1, "last_request": "x"}}, "c", "s")
    refs = [m.ClientReference("vector_search_index", "index a.b.c", None, "embedding_endpoint", "proj-a-gpt", "proj-a-gpt", "x")]
    r = m.readiness(rows, refs, True, 30)
    assert r["status"] == "BLOCKED"
    assert {b["type"] for b in r["blockers"]} == {"legacy_traffic", "vector_search"}
    assert r["rate_limit_zero_candidates"] == []  # needs the endpoint config (for the undo command)
    eps = [_ep(TRACKED_A), _ep(TRACKED_B)]  # usage tracking on, so zero traffic here is known
    full = m.readiness(rows, refs, True, 30, eps)
    assert [c["endpoint"] for c in full["rate_limit_zero_candidates"]] == ["proj-b-gpt"]
    cand = full["rate_limit_zero_candidates"][0]
    assert cand["ai_gateway_body"]["rate_limits"] == [{"key": "endpoint", "calls": 0, "renewal_period": "minute"}]
    assert cand["undo_body"]["usage_tracking_config"] == {"enabled": True}  # undo restores the current config
    refs2 = refs + [m.ClientReference("notebook", "/n", 1, "legacy_endpoint_name", "'proj-b-gpt'", "proj-b-gpt", "x")]
    assert m.readiness(rows, refs2, True, 30, eps)["rate_limit_zero_candidates"] == []
    gap = m.readiness(rows, refs, True, 30, eps, {"apps": "failed: 403"})
    assert gap["rate_limit_zero_candidates"] == [] and gap["coverage_gaps"] == {"apps": "failed: 403"}
    a_ep = _ep(TRACKED_A)  # proj-a-gpt keeps its other rate limits when closed
    rows_a, _ = m.plan([a_ep], {}, {}, "c", "s")
    close = m.readiness(rows_a, [], True, 30, [a_ep])["rate_limit_zero_candidates"][0]["ai_gateway_body"]
    assert [l["key"] for l in close["rate_limits"]] == ["user_group", "service_principal", "endpoint"]
    clean, _ = m.plan([_ep(SYSTEM_PPT)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s")
    # READY is cautious: a zero-traffic pay-per-token endpoint with no known caller caps the result.
    capped = m.readiness(clean, [], True, 30)
    assert capped["status"] == "READY_WITH_WARNINGS"
    assert [w["type"] for w in capped["warnings"]] == ["confirm_infrequent_callers"]
    assert m.readiness([], [], True, 30, [], {"local_files": "ok"})["status"] == "READY"
    r = m.readiness(clean, [], False, 30)
    assert r["status"] == "INCOMPLETE" and "traffic" in r["coverage_gaps"] and not r["blockers"]
    assert m.readiness(clean, [], True, 30, scanned=False)["status"] == "INCOMPLETE"


def test_local_scan_and_config_values(tmp_path):
    repo = tmp_path / "repo"
    (repo / "resources").mkdir(parents=True)
    (repo / "node_modules").mkdir()
    (repo / "resources" / "app.yml").write_text(
        "resources:\n  apps:\n    chat:\n      resources:\n        - name: llm\n          serving_endpoint:\n"
        "            name: proj-a-gpt\n            permission: CAN_QUERY\n")
    (repo / "main.tf").write_text('resource "x" "y" {\n  endpoint_name = "databricks-gpt-5-5"\n}\n')
    (repo / "job.sql").write_text("SELECT ai_query('databricks-gpt-5-5', p) FROM t\n")
    (repo / "copy.sql").write_text("SELECT ai_query('databricks-gpt-5-5', p) FROM t\n")
    (repo / "node_modules" / "x.js").write_text("const m = 'databricks-gpt-5-5'\n")
    (repo / "blob.bin.json").write_bytes(b"\x00\x01databricks-gpt-5-5")
    eps = [_ep(SYSTEM_PPT), _ep(EXTERNAL)]
    sysmap = {"databricks-gpt-5-5": "system.ai.gpt-5-5"}
    rows, _ = m.plan(eps, sysmap, {}, "c", "s")
    s = m.Scanner([e.name for e in eps], sysmap, rows)
    m.scan_local(s, [str(repo)])
    found = {(r.asset.split(" ")[0], r.pattern, r.legacy_endpoint) for r in s.refs}
    assert ("repo/resources/app.yml", "bundle_serving_endpoint_resource", "proj-a-gpt") in found
    assert ("repo/main.tf", "legacy_endpoint_name", "databricks-gpt-5-5") in found
    assert any(r.pattern == "ai_query" and "identical copies" in r.asset for r in s.refs)
    assert not any("node_modules" in r.asset or "blob" in r.asset for r in s.refs)
    res = next(r for r in s.refs if r.pattern == "bundle_serving_endpoint_resource")
    assert res.fixed_line is None
    assert m.readiness(rows, [res], True, 30)["blockers"][0]["type"] == "app_resource"
    s2 = m.Scanner([e.name for e in eps], sysmap, rows)
    s2.scan_text("local_file", "databricks.yml", "variables:\n  llm:\n    default: databricks-gpt-5-5\n")
    assert s2.refs[0].pattern == "config_value" and s2.refs[0].fixed_line == "default: system.ai.gpt-5-5"


def test_multiline_ai_query_and_routes():
    eps = [_ep(SYSTEM_PPT)]
    sysmap = {"databricks-gpt-5-5": "system.ai.gpt-5-5"}
    rows, _ = m.plan(eps, sysmap, {}, "c", "s")
    s = m.Scanner([e.name for e in eps], sysmap, rows)
    s.scan_text("uc_function", "function a.b.c", "RETURN ai_query(\n  'databricks-gpt-5-5',\n  prompt)\n"
                "url = host + '/serving-endpoints/responses'\n")
    aq = [r for r in s.refs if r.pattern == "ai_query"]
    assert len(aq) == 1 and aq[0].line == 2 and aq[0].fixed_line == "'system.ai.gpt-5-5',"
    assert not any(r.pattern == "legacy_endpoint_name" for r in s.refs)
    route = next(r for r in s.refs if r.pattern == "serving_endpoints_url")
    assert route.fixed_line == "url = host + '/ai-gateway/mlflow/v1/responses'"


def test_external_traffic_does_not_block_enforce():
    ep = _ep(EXTERNAL)
    rows, _ = m.plan([ep], {}, {"proj-a-gpt": {"requests": 9, "requesters": 1, "last_request": "x"}}, "c", "s")
    r = m.readiness(rows, [], True, 30, [ep])
    assert not r["blockers"] and r["warnings"][0]["type"] == "legacy_traffic_kept_after_enforce"
    assert r["status"] == "READY_WITH_WARNINGS" and not r["coverage_gaps"]
    assert r["rate_limit_zero_candidates"] == []  # it has traffic


# ---------------------------------------------------------------------------
# Review fixes: inventory, plan, scanner, coverage and readiness
# ---------------------------------------------------------------------------


def _ext_payload(name, key="sk-AAAAAAAAAAAAAAAAAA", provider="openai", cfg_name="openai_config", model="gpt-5"):
    cfg = {"openai_api_key": key} if provider == "openai" else {"api_key": key}
    return {"name": name, "id": "id-" + name,
            "config": {"served_entities": [{"name": "p", "external_model": {
                "provider": provider, "name": model, "task": "llm/v1/chat", cfg_name: cfg}}]}}


def test_pt_entity_with_foundation_model_is_still_pt():
    ent = {"name": "llama", "foundation_model": {"name": "llama"}, "min_provisioned_throughput": 0,
           "max_provisioned_throughput": 9500, "workload_type": "GPU_MEDIUM", "scale_to_zero_enabled": True}
    kind, dest = m._classify({"name": "pt", "config": {"served_entities": [ent]}})
    assert kind == "provisioned_throughput"
    assert dest[0]["workload_type"] == "GPU_MEDIUM" and dest[0]["scale_to_zero"] is True


def test_inventory_reads_auto_capture_route_and_policy_fields(monkeypatch):
    detail = {"name": "legacy-pt", "id": "x1", "route_optimized": True,
              "endpoint_url": "https://1234.serving.databricks.com/invocations", "budget_policy_id": "bp-1",
              "config": {"served_entities": [{"name": "llama", "entity_name": "system.ai.llama",
                                              "min_provisioned_throughput": 0, "max_provisioned_throughput": 10}],
                         "auto_capture_config": {"catalog_name": "main", "schema_name": "logs", "enabled": True}},
              "ai_gateway": {"usage_tracking_config": {"enabled": True}}}

    def fake_get(w, path, query=None):
        if path == "/api/2.0/serving-endpoints":
            return {"endpoints": [{"name": "legacy-pt"}]}
        if path == "/api/2.0/serving-endpoints/legacy-pt":
            return detail
        return {"access_control_list": []}

    monkeypatch.setattr(m, "_get", fake_get)
    ep = m.inventory(mock.MagicMock())[0]
    assert ep.auto_capture == {"catalog_name": "main", "schema_name": "logs", "enabled": True}
    assert ep.route_optimized and ep.endpoint_url == "https://1234.serving.databricks.com/invocations"
    assert ep.budget_policy_id == "bp-1" and ep.usage_policy_id is None
    assert ep.usage_tracking is True and ep.gateway_settings == ["usage_tracking_config"]


def test_auto_capture_table_maps_like_an_inference_table():
    ep = _ep(EXTERNAL_SAME_KEY)
    ep.auto_capture = {"catalog_name": "main", "schema_name": "logs", "enabled": True}
    rows, _ = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].inference_table["parent"] == "schemas/main.logs"
    assert rows[0].inference_table["table_name_prefix"] == "proj_b_gpt_ug"
    assert any("auto-capture" in n for n in rows[0].needs_human)


def test_route_optimized_budget_and_usage_policy_are_called_out():
    ep = _ep(EXTERNAL_SAME_KEY)
    ep.route_optimized, ep.endpoint_url = True, "https://1234.serving.databricks.com/invocations"
    ep.budget_policy_id, ep.usage_policy_id, ep.usage_tracking = "bp-1", "up-1", True
    rows, _ = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    needs = " | ".join(rows[0].needs_human)
    assert "https://1234.serving.databricks.com/invocations" in needs
    assert "budget policy bp-1 doesn't carry over" in needs and "usage policy up-1 doesn't carry over" in needs
    assert "system.ai_gateway.usage" in needs
    assert not any(n.startswith(m.BLOCKING_PREFIX) for n in rows[0].needs_human)


def test_pt_scale_to_zero_and_workload_stay_on_legacy_endpoint():
    pt = {**PT, "config": {"served_entities": [{**PT["config"]["served_entities"][0], "workload_type": "GPU_MEDIUM",
                                                "scale_to_zero_enabled": True}]}}
    rows, _ = m.plan([_ep(pt)], {}, {}, "c", "s", traffic_known=False)
    assert any("workload GPU_MEDIUM, scale to zero on" in n and "stay on the legacy PT endpoint" in n
               for n in rows[0].needs_human)


def test_fallback_text_names_zero_traffic_destinations_like_apply():
    rows, _ = m.plan([_ep(EXTERNAL)], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].routing["fallback"] == "0%-traffic destinations, in listing order: backup"
    even = {**EXTERNAL, "config": {**EXTERNAL["config"], "traffic_config": {"routes": [
        {"served_model_name": "primary", "traffic_percentage": 50},
        {"served_model_name": "backup", "traffic_percentage": 50}]}}}
    rows, _ = m.plan([_ep(even)], {}, {}, "c", "s", traffic_known=False)
    assert "fallback" not in rows[0].routing
    assert any("apply creates no fallback" in n for n in rows[0].needs_human)


def test_provider_status_and_manual_action_for_unautomated_providers():
    assert m.provider_status({"provider": "openai", "provider_config": {"openai_config": {}}}) == "automated"
    assert m.provider_status({"provider": "anthropic", "provider_config": {}}) == "automated"
    assert m.provider_status({"provider": "openai",
                              "provider_config": {"openai_config": {"openai_api_type": "azuread"}}}) == "manual_supported"
    assert m.provider_status({"provider": "amazon-bedrock", "provider_config": {}}) == "manual_supported"
    assert m.provider_status({"provider": "cohere", "provider_config": {}}) == "no_ug_provider"
    assert m.provider_status({"provider": "databricks-model-serving", "provider_config": {}}) == "no_ug_provider"
    assert m.provider_status({"provider": "something-new", "provider_config": {}}) == "unknown_provider"
    bedrock = _ep(_ext_payload("bed", provider="amazon-bedrock", cfg_name="amazon_bedrock_config"))
    rows, providers = m.plan([bedrock], {}, {}, "c", "s", traffic_known=False)
    assert rows[0].action == "manual" and rows[0].provider_status == "manual_supported"
    assert providers[0]["provider_status"] == "manual_supported"
    assert any("create the provider and model services by hand" in n for n in rows[0].needs_human)


def test_plaintext_keys_get_separate_provider_groups_and_no_value_is_printed():
    eps = [_ep(_ext_payload("a", "sk-AAAAAAAAAAAAAAAAAA")), _ep(_ext_payload("b", "sk-BBBBBBBBBBBBBBBBBB")),
           _ep(_ext_payload("c", "sk-AAAAAAAAAAAAAAAAAA"))]
    rows, providers = m.plan(eps, {}, {}, "c", "s", traffic_known=False)
    assert len(providers) == 2
    dump = json.dumps([asdict(e) for e in eps] + providers, default=str)
    assert "sk-AAAA" not in dump and "sk-BBBB" not in dump
    assert "<redacted plaintext " in dump


def test_guardrail_advice_names_current_policies():
    text = m._guardrail_advice({"input": {"pii": {"behavior": "MASK"}}, "output": {"safety": True}})
    assert "system.ai.detect_sensitive_data, redact" in text and "system.ai.block_unsafe_content" in text
    assert "Beta" in text and "preview" in text


def test_system_ppt_names_the_settings_it_drops():
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s", traffic_known=False)
    assert any("(rate limits)" in n for n in rows[0].needs_human)


def test_pt_wrapper_is_not_a_readiness_warning():
    # The PT endpoint keeps serving behind its Unity Gateway model service after the deadline.
    rows, _ = m.plan([_ep(PT)], {}, {}, "c", "s", traffic_known=False)
    r = m.readiness(rows, [], True, 30, [])
    assert not any(w["type"] == "pt_wrapper_on_legacy_endpoint" for w in r["warnings"])


def test_pay_per_token_calls_block_even_without_traffic():
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s", traffic_known=False)
    refs = [m.ClientReference("notebook", "/n", 3, "ai_query", "'databricks-gpt-5-5'", "databricks-gpt-5-5",
                              "ai_query('system.ai.gpt-5-5', ...)"),
            m.ClientReference("notebook", "/n", 4, "serving_endpoints_management_api", "/api/2.0/serving-endpoints",
                              "databricks-gpt-5-5", "x")]
    r = m.readiness(rows, refs, True, 30, [])
    assert r["status"] == "BLOCKED"
    assert [b["type"] for b in r["blockers"]] == ["pay_per_token_call"]


def test_zero_traffic_is_not_proof_and_untracked_endpoints_are_warned():
    ep = _ep(EXTERNAL_SAME_KEY)  # usage tracking off: warn about callers outside the window
    rows, _ = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    r = m.readiness(rows, [], True, 30, [ep])
    w = [x for x in r["warnings"] if x["type"] == "no_traffic_in_window"]
    assert r["status"] == "READY_WITH_WARNINGS" and not r["coverage_gaps"] and "proj-b-gpt" in w[0]["detail"]
    assert "not proof that nothing calls an endpoint" in m.readiness_md("https://x", r, 30)
    tracked = _ep(TRACKED_B)
    rows, _ = m.plan([tracked], {}, {}, "c", "s", traffic_known=False)
    assert m.readiness(rows, [], True, 30, [tracked])["status"] == "READY"


def test_guardrails_block_apply_until_acknowledged():
    import ug_migration_apply as a

    ep = _ep(EXTERNAL)
    rows, providers = m.plan([ep], {}, {}, "c", "s", traffic_known=False)
    assert any(n.startswith(m.BLOCKING_PREFIX + "guardrails not carried over") for n in rows[0].needs_human)
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    with pytest.raises(a.Manual, match="guardrails not carried over"):
        a.build_model_service(ep, rows[0], fqn)
    rows, providers = m.plan([ep], {}, {}, "c", "s", traffic_known=False, ack_guardrails=True)
    assert not any(n.startswith(m.BLOCKING_PREFIX) for n in rows[0].needs_human)
    assert any(n.startswith("guardrails acknowledged") for n in rows[0].needs_human)
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    assert a.build_model_service(ep, rows[0], fqn, ack_guardrails=True)["config"]["routing"]["destinations"]


def test_app_yaml_value_and_env_export_are_detected():
    s = m.Scanner(["proj-a-gpt"], {"proj-a-gpt": "system.ai.x"}, [])
    s.scan_text("file", "app.yaml", "env:\n  - name: MODEL_ENDPOINT\n    value: proj-a-gpt\n"
                                    "  - name: OTHER\n    value: proj-a-gpt\n")
    s.scan_text("file", ".env", "export MODEL_ENDPOINT=proj-a-gpt\n")
    cfg = [(r.asset, r.line, r.fixed_line) for r in s.refs if r.pattern == "config_value"]
    assert ("app.yaml", 3, "value: system.ai.x") in cfg and (".env", 1, "export MODEL_ENDPOINT=system.ai.x") in cfg
    assert not any(line == 5 for _, line, _ in cfg)  # OTHER isn't an endpoint setting


def test_generic_names_need_key_or_call_context():
    s = m.Scanner(["test", "proj-a-gpt"], {}, [])
    s.scan_text("notebook", "nb", "print('test')\nx = {'endpoint': 'test'}\n")
    assert {(r.line, r.legacy_endpoint) for r in s.refs} == {(2, "test")}


def test_dynamic_serving_url_is_manual_not_rewritten():
    s = m.Scanner(["proj-a-gpt"], {"proj-a-gpt": "system.ai.x"}, [])
    s.scan_text("notebook", "nb", "url = f'{host}/serving-endpoints/{ep}/invocations'\n")
    r = s.refs[0]
    assert r.fixed_line is None and r.legacy_endpoint is None and "manual" in r.suggestion


def test_embedding_invocations_map_to_embeddings_and_chat_is_manual():
    s = m.Scanner(["bge-large-x", "proj-a-gpt"], {"bge-large-x": "system.ai.bge", "proj-a-gpt": "system.ai.x"}, [])
    s.scan_text("notebook", "nb", "e = f'{host}/serving-endpoints/bge-large-x/invocations'\n"
                                  "c = f'{host}/serving-endpoints/proj-a-gpt/invocations'\n")
    by_line = {r.line: r for r in s.refs if r.pattern == "serving_endpoints_url"}
    assert by_line[1].fixed_line == "e = f'{host}/ai-gateway/mlflow/v1/embeddings'"
    assert by_line[2].fixed_line is None and "body changes to OpenAI chat format" in by_line[2].suggestion


def test_route_optimized_urls_are_matched_by_endpoint_url():
    text = "url = 'https://1234.serving.databricks.com/invocations'\n"
    s = m.Scanner(["proj-a-gpt"], {}, [], {"https://1234.serving.databricks.com/invocations": "proj-a-gpt"})
    s.scan_text("notebook", "nb", text)
    assert [(r.pattern, r.legacy_endpoint) for r in s.refs] == [("serving_endpoint_route_url", "proj-a-gpt")]
    s2 = m.Scanner(["proj-a-gpt"], {}, [])
    s2.scan_text("notebook", "nb", text)
    assert s2.refs[0].pattern == "serving_endpoint_route_url" and s2.refs[0].legacy_endpoint is None


def test_scrub_hides_unquoted_values_and_common_names():
    assert m.scrub("api_key=abc123def456ghi") == "api_key=<hidden>"
    assert m.scrub("DB_PASS: hunter2hunter") == "DB_PASS: <hidden>"
    assert m.scrub("pwd = abcdef12") == "pwd = <hidden>"
    assert m.scrub("secret = xyz123456") == "secret = <hidden>"
    assert m.scrub("token=abc123abc123") == "token=<hidden>"
    assert m.scrub("key = 'abcdefgh'") == "key = '<hidden>'"
    for safe in ("keyboard = 'layout_x'", "monkey_patch = 'banana_split'", "endpoint = 'databricks-gpt-5-5'"):
        assert m.scrub(safe) == safe


def test_identical_copies_keep_every_path_for_caller_linking(monkeypatch):
    objects = {"/Users": [{"path": "/Users/a", "object_type": "DIRECTORY"},
                          {"path": "/Users/b", "object_type": "DIRECTORY"}],
               "/Users/a": [{"path": "/Users/a/app.py", "object_type": "FILE"}],
               "/Users/b": [{"path": "/Users/b/app.py", "object_type": "FILE"}]}
    text = "SELECT ai_query('proj-a-gpt', p)"

    def fake_get(w, path, query=None):
        if path == "/api/2.0/workspace/list":
            return {"objects": objects.get(query["path"], [])}
        return {"content": base64.b64encode(text.encode()).decode()}

    monkeypatch.setattr(m, "_get", fake_get)
    s = m.Scanner(["proj-a-gpt"], {}, [])
    m.scan_workspace(mock.MagicMock(), s, ["/Users"], 100, threads=2)
    refs = [r for r in s.refs if r.pattern == "ai_query"]
    assert len(refs) == 1 and "(+1 identical copies)" in refs[0].asset and refs[0].also_in == ["/Users/b/app.py"]
    linked = m.link_callers([{"requester": "b", "endpoint_name": "proj-a-gpt", "requests": 1, "last_request": "x"}],
                            s.refs, {})
    assert linked[0]["linked_count"] == 1


def test_walk_skips_dependency_folders_and_budgets_per_root(monkeypatch):
    def f(p):
        return {"path": p, "object_type": "FILE"}

    def d(p):
        return {"path": p, "object_type": "DIRECTORY"}

    objects = {"/Users": [d("/Users/node_modules"), d("/Users/proj")],
               "/Users/node_modules": [f("/Users/node_modules/bad.py")],
               "/Users/proj": [f("/Users/proj/a.py"), f("/Users/proj/b.py"), f("/Users/proj/c.py"),
                               f("/Users/proj/d.png")],
               "/Shared": [f("/Shared/s.py")]}
    listed = []

    def fake_get(w, path, query=None):
        listed.append(query["path"])
        return {"objects": objects.get(query["path"], [])}

    monkeypatch.setattr(m, "_get", fake_get)
    found = m._walk_workspace(mock.MagicMock(), ["/Users", "/Shared"], 2, accept=lambda o: o["path"].endswith(".py"))
    assert sorted(o["path"] for o in found) == ["/Shared/s.py", "/Users/proj/a.py", "/Users/proj/b.py"]
    assert "/Users/node_modules" not in listed


def test_toolkit_folder_skip_is_partial_coverage(monkeypatch):
    objects = {"/Users": [{"path": "/Users/kit", "object_type": "DIRECTORY"}],
               "/Users/kit": [{"path": "/Users/kit/ug_migration_planner.py", "object_type": "FILE"}]}
    monkeypatch.setattr(m, "_get", lambda w, path, query=None: {"objects": objects.get(query["path"], [])})
    s = m.Scanner(["proj-a-gpt"], {}, [])
    m.scan_workspace(mock.MagicMock(), s, ["/Users"], 100, threads=2)
    assert s.coverage["workspace_files"] == "partial: 1 folders skipped (the toolkit's own install)"


def test_genie_space_without_definition_is_unreadable():
    w = mock.MagicMock()
    w.genie.list_spaces.return_value = SimpleNamespace(
        spaces=[SimpleNamespace(space_id="s1", title="t1"), SimpleNamespace(space_id="s2", title="t2")],
        next_page_token=None)
    w.genie.get_space.side_effect = lambda space_id, include_serialized_space=None: SimpleNamespace(
        serialized_space=None if space_id == "s1" else "x = 'proj-a-gpt'")
    s = m.Scanner(["proj-a-gpt"], {}, [])
    m.scan_genie(w, s)
    assert s.coverage["genie_spaces"] == "partial: 1 unreadable"
    assert any(r.asset_type == "genie_space" for r in s.refs)


def test_system_ai_map_failure_keeps_ready_out_of_reach():
    cov = {}
    w = mock.MagicMock()
    w.ai_gateway.list_model_services.side_effect = RuntimeError("boom")
    assert m.system_ai_map(w, cov) == {} and cov["system_ai_map"].startswith("failed: boom")
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {}, {}, "c", "s", traffic_known=False)
    assert m.readiness(rows, [], True, 30, [], cov)["status"] == "INCOMPLETE"


def test_no_local_path_is_a_note_not_a_gap():
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s", traffic_known=False)
    cov = {"local_files": "not scanned: no --local-path given"}
    r = m.readiness(rows, [], True, 30, [], cov)
    # Still a note (not an incomplete scan), but without local folders READY is capped at READY_WITH_WARNINGS.
    assert r["status"] == "READY_WITH_WARNINGS" and r["notes"] == cov and not r["coverage_gaps"]
    assert "local_folders_not_scanned" in [w["type"] for w in r["warnings"]]
    assert "Not covered (notes, not gaps)" in m.readiness_md("https://x", r, 30)


def test_app_source_folders_become_scan_roots():
    w = mock.MagicMock()
    w.apps.list.return_value = [
        SimpleNamespace(source_code_path="/Workspace/Users/a@x.com/app",
                        default_source_code_path="/Workspace/Users/a@x.com/app/src"),
        SimpleNamespace(source_code_path=None, default_source_code_path=None)]
    cov = {}
    assert m.app_source_roots(w, cov) == ["/Users/a@x.com/app", "/Users/a@x.com/app/src"]
    assert cov == {"app_sources": "ok"}


def test_local_scan_marks_oversize_files_partial(tmp_path):
    (tmp_path / "big.py").write_text("x = 'proj-a-gpt'\n" + "# pad\n" * 50)
    s = m.Scanner(["proj-a-gpt"], {}, [])
    m.scan_local(s, [str(tmp_path)], max_bytes=20)
    assert s.coverage["local_files"] == "partial: 1 files over 0 MB not scanned"
    assert not s.refs


def test_workspace_extensions_include_infrastructure_and_frontend_files():
    for ext in (".tf", ".tfvars", ".hcl", ".ini", ".conf", ".properties", ".tsx", ".jsx", ".java", ".go"):
        assert ext in m.WORKSPACE_EXTS


def test_sql_polling_gives_up_after_the_deadline(monkeypatch):
    from databricks.sdk.service.sql import StatementState

    running = SimpleNamespace(statement_id="s1", status=SimpleNamespace(state=StatementState.RUNNING))
    w = mock.MagicMock()
    w.statement_execution.execute_statement.return_value = running
    w.statement_execution.get_statement.return_value = running
    monkeypatch.setattr(m, "SQL_POLL_SECONDS", -1)
    with pytest.raises(RuntimeError, match="stopped waiting"):
        m._sql(w, "wh-1", "SELECT 1")


def test_scan_roots_narrowed_or_defaults_are_recorded(tmp_path, monkeypatch):
    w = mock.MagicMock()
    w.config.host = "https://example.test"
    w.genie.list_spaces.return_value = SimpleNamespace(spaces=[], next_page_token=None)

    def fake_get(w_, path, query=None):
        if path == "/api/2.0/serving-endpoints":
            return {"endpoints": [{"name": "proj-a-gpt"}]}
        if path == "/api/2.0/serving-endpoints/proj-a-gpt":
            return EXTERNAL
        return {"objects": [], "access_control_list": []}

    monkeypatch.setattr(m, "_get", fake_get)
    # Only the served-entity count returns a row: the traffic and UC queries get no rows.
    monkeypatch.setattr(m, "_sql", lambda w, wh, stmt, params=None: [{"n": 1}] if "count(*) AS n" in stmt else [])
    narrowed = m.run(w, str(tmp_path / "n"), workspace_id="1", scan_roots=["/Users/a@x.com"], allow_spark=False)
    ready = json.loads((tmp_path / "n" / "readiness.json").read_text())
    assert ready["scan_roots"] == ["/Users/a@x.com"]
    assert ready["coverage"]["scan_roots"].startswith("partial: only /Users/a@x.com")
    assert "scan_roots" in ready["coverage_gaps"] and ready["coverage"]["local_files"].startswith("not scanned")
    assert narrowed["readiness"] == "INCOMPLETE"
    m.run(w, str(tmp_path / "d"), workspace_id="1", allow_spark=False)
    assert json.loads((tmp_path / "d" / "readiness.json").read_text())["coverage"]["scan_roots"] == "ok"


def test_v2_gateway_traffic_is_added_to_legacy_traffic():
    v1 = [{"endpoint_name": "a", "requests": "5", "requesters": "2", "last_request": "2026-10-01", "throttled": "0"}]
    v2 = [{"endpoint_name": "a", "requests": "7", "requesters": "3", "last_request": "2026-10-20"},
          {"endpoint_name": "databricks-gpt-x", "requests": "100", "requesters": "1", "last_request": "2026-10-30"}]
    t = m._merge_traffic(v1, v2)
    assert t["a"]["requests"] == 12 and t["a"]["v2_requests"] == 7 and t["a"]["requesters"] == 3
    assert t["a"]["last_request"] == "2026-10-20"
    assert t["databricks-gpt-x"]["requests"] == 100  # v2-only traffic counts: Enforce would break it


def test_every_blocker_and_warning_has_label_and_action():
    rows, _ = m.plan([_ep(SYSTEM_PPT), _ep(EXTERNAL), _ep(PT)],
                     {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {"proj-a-gpt": {"requests": 3, "requesters": 1}},
                     "c", "s")
    refs = [m.ClientReference("notebook", "/n", 3, "ai_query", "'databricks-gpt-5-5'", "databricks-gpt-5-5",
                              "ai_query('system.ai.gpt-5-5', ...)"),
            m.ClientReference("app", "app chat-app", 2, "config_value", "proj-a-gpt", "proj-a-gpt", "x"),
            m.ClientReference("app", "app chat-app", 4, "bundle_serving_endpoint_resource", "proj-a-gpt",
                              "proj-a-gpt", "replace it")]
    r = m.readiness(rows, refs, True, 30, [_ep(SYSTEM_PPT), _ep(EXTERNAL)])
    for f in r["blockers"] + r["warnings"]:
        assert f["label"] and f["action"] and f["type"], f


def test_app_env_values_are_warnings_and_only_resources_block():
    app_value = m.ClientReference("app", "app chat-app", 3, "config_value", "proj-a-gpt", "proj-a-gpt", "x")
    app_resource = m.ClientReference("app", "app chat-app", 7, "bundle_serving_endpoint_resource", "guarded-gpt",
                                     "guarded-gpt", "replace it")
    r = m.readiness([], [app_value], True, 30, [])
    assert not r["blockers"] and r["warnings"][0]["label"] == "App config value uses a legacy endpoint"
    assert r["warnings"][0]["action"] == "change the env value and the code that reads it"
    r = m.readiness([], [app_resource], True, 30, [])
    assert [b["type"] for b in r["blockers"]] == ["app_resource"]


def test_pay_per_token_call_sites_are_one_blocker_per_endpoint():
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"},
                     {"databricks-gpt-5-5": {"requests": 40, "requesters": 2, "last_request": "x"}}, "c", "s")
    refs = [m.ClientReference("notebook", "/n", i, "legacy_endpoint_name", "'databricks-gpt-5-5'",
                              "databricks-gpt-5-5", "x") for i in (1, 2, 3, 4)]
    r = m.readiness(rows, refs, True, 30, [])
    assert [b["type"] for b in r["blockers"]] == ["pay_per_token_call"]
    assert r["blockers"][0]["item"] == "databricks-gpt-5-5"
    assert "4 call sites: see CODE_FIXES.md" in r["blockers"][0]["detail"] and "40 requests" in r["blockers"][0]["detail"]


def test_no_traffic_advice_retires_only_without_code_references():
    rows, _ = m.plan([_ep(EXTERNAL)], {}, {}, "c", "s")
    m.annotate_dependencies(rows, [], 30)
    assert any("no code references it" in n and "retire" in n for n in rows[0].needs_human)
    rows, _ = m.plan([_ep(EXTERNAL)], {}, {}, "c", "s")
    ref = m.ClientReference("notebook", "/n", 1, "legacy_endpoint_name", "'proj-a-gpt'", "proj-a-gpt", "x")
    m.annotate_dependencies(rows, [ref], 30)
    text = " ".join(rows[0].needs_human)
    assert "No requests in 30 days, but code still references it (see client_references.csv): keep it or move the callers" in text
    assert "retire" not in text


def test_plaintext_key_need_and_summary_count():
    plain = {"name": "plain-key", "id": "e9", "config": {"served_entities": [
        {"name": "p", "external_model": {"provider": "openai", "name": "gpt-4.1", "task": "llm/v1/chat",
                                         "openai_config": {"openai_api_key": "sk-proj-AbCdEf1234567890XYZ"}}}]}}
    rows, _ = m.plan([_ep(plain)], {}, {}, "c", "s")
    assert m.PLAINTEXT_KEY_NEED in rows[0].needs_human
    assert "sk-proj" not in json.dumps(asdict(rows[0]))
    md = m.summary_md("https://x", [_ep(plain)], rows, [], [], 30, True, None, "BLOCKED")
    assert "Plaintext API keys: 1 endpoint" in md and md.startswith("# Unity Gateway") and "Status: BLOCKED" in md


def test_system_ppt_without_system_ai_target_is_manual():
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {}, {}, "c", "s")
    assert rows[0].action == "manual" and m.NO_SYSTEM_AI_NEED in rows[0].needs_human
    assert all(r.action != "create_model_service" for r in rows)


def test_blockers_and_needs_say_how_many_more_are_hidden():
    many = [m.PlanRow(f"ep{i}", "external_model", "create_model_service", None, None, None, [], None, None, [], [],
                      [f"need {i}"]) for i in range(55)]
    refs = [m.ClientReference("notebook", f"/n{i}", 1, "legacy_endpoint_name", "'x'", f"proj-{i}", "x")
            for i in range(65)]
    r = {"status": "READY_WITH_WARNINGS", "blockers": [], "warnings": [
        m._flag("config_value", f"i{i}", "d", "Config value names a legacy endpoint", "act") for i in range(65)],
         "coverage_gaps": {}, "notes": {}, "rate_limit_zero_candidates": [], "scan_roots": []}
    md = m.readiness_md("https://x", r, 30)
    assert "+5 more in readiness.json" in md
    s = m.summary_md("https://x", [], many, [], refs, 30, True)
    assert "+5 more in migration_plan.csv" in s
    assert "... 25 more in client_references.csv" in s  # references list keeps its own cap at 40 entries


def test_readiness_next_steps_follow_status_and_legend_is_shown():
    base = {"blockers": [], "warnings": [], "coverage_gaps": {}, "notes": {}, "rate_limit_zero_candidates": [],
            "scan_roots": []}
    for status, first in (("READY", "Confirm with the owners"), ("INCOMPLETE", "Fix the gap"),
                          ("READY_WITH_WARNINGS", "Review the warnings"), ("BLOCKED", "Fix each blocker")):
        md = m.readiness_md("https://x", {**base, "status": status}, 30)
        assert f"**Status: {status}**" in md and "## Next steps" in md
        assert md.split("## Next steps")[1].split("\n1. ")[1].startswith(first), status
    assert "INCOMPLETE**: nothing blocking found, but part of the scan didn't run" in m.readiness_md(
        "https://x", {**base, "status": "INCOMPLETE"}, 30)


def test_code_fixes_lists_manual_edits_with_counts():
    eps = [_ep(SYSTEM_PPT)]
    rows, _ = m.plan(eps, {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s")
    s = m.Scanner([e.name for e in eps], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, rows)
    s.scan_text("notebook", "/n", "\n".join([
        "SELECT ai_query('databricks-gpt-5-5', p) FROM t",
        "r = requests.post(f'{host}/serving-endpoints/{name}/invocations')"]))
    md = m.code_fixes_md(s.refs)
    assert "1 proposed line change across 1 file" in md
    assert "## References that need a manual edit (1)" in md
    assert "# note: ai_query('system.ai.gpt-5-5', ...); caveat:" in md


# ---------------------------------------------------------------------------
# v2 workspace-bound endpoints, caller classes, the single deadline, and the caution rules
# ---------------------------------------------------------------------------

V2_CHAT = "https://adb-1.azuredatabricks.net/ai-gateway/mlflow/v1/chat/completions"
V2_RESPONSES = "https://adb-1.azuredatabricks.net/ai-gateway/openai/v1/responses"
SYS_GPT = {"databricks-gpt-5-5": "system.ai.gpt-5-5"}


def scan(names, text, sys_map=None, asset_type="notebook", asset="nb"):
    s = m.Scanner(names, sys_map or {}, [])
    s.scan_text(asset_type, asset, text)
    return s.refs


def _v2_usage(name, requests=10, api_types=("mlflow/v1/chat/completions",), requesters=1):
    """One endpoint's merged traffic entry, shaped like traffic() returns for a v2-only name."""
    return {"endpoint_name": name, "requests": requests, "requesters": requesters, "last_request": "2026-10-30",
            "throttled": 0, "v2_requests": requests, "api_types": list(api_types)}


def test_caller_class_rules_for_v1_and_v2():
    assert m.caller_class(None, None, "dev@databricks.com", "v2") == "no_client_info"
    assert m.caller_class(None, None, "dev@databricks.com", "v1") == "user"
    assert m.caller_class(None, None, "0f6d1c2a-1111-2222-3333-444455556666") == "service_principal"
    assert m.caller_class(None, None, "system") == "platform"
    assert m.caller_class(None, None, None) == "unknown"
    assert m.caller_class("", None, None, "v2") == "no_client_info"  # a blank user agent counts as none
    assert m.caller_class("claude-code/1.0 databricks-sdk-py/0.137.0", V2_CHAT, "a@x.com", "v2") == "coding_agent"
    assert m.caller_class("unknown/0.0.0 databricks-sdk-py/0.137.0 python/3.13 auth/databricks-cli agent", V2_CHAT,
                          "a@x.com", "v2") == "sdk"
    assert m.caller_class("opencode/latest/2.2.5/cli", V2_CHAT, "a@x.com", "v2") == "coding_agent"
    assert m.caller_class("OpenAI/Python 1.50.0", V2_CHAT, "a@x.com", "v2") == "llm_sdk"
    assert m.caller_class("python-requests/2.31.0", V2_CHAT, None, "v2") == "http"
    assert m.caller_class("Mozilla/5.0", V2_CHAT, None, "v2") == "unknown"


def test_traffic_by_requester_and_totals_split_v1_and_v2_callers(monkeypatch):
    v1 = [{"endpoint_name": "databricks-gpt-5-5", "requester": "0f6d1c2a-1111-2222-3333-444455556666",
           "requests": 4, "last_request": "2026-10-01"}]
    v2 = [{"endpoint_name": "databricks-gpt-5-5", "requester": "dev@databricks.com", "user_agent": None, "url": None,
           "api_type": None, "requests": 900, "last_request": "2026-10-30"},
          {"endpoint_name": "databricks-gpt-5-5", "requester": "ana@x.com", "user_agent": "opencode/1.18",
           "url": V2_CHAT, "api_type": "mlflow/v1/chat/completions", "requests": 3, "last_request": "2026-10-29"}]
    monkeypatch.setattr(m, "_sql", lambda w, wh, statement, params=None: v1 if "serving.endpoint_usage" in statement else v2)
    rows = m.traffic_by_requester(mock.MagicMock(), None, "1", 30)
    assert {(r["api"], r["caller_class"]): r["requests"] for r in rows} == {
        ("v1", "service_principal"): 4, ("v2", "no_client_info"): 900, ("v2", "coding_agent"): 3}
    t = m.traffic(mock.MagicMock(), None, "1", 30)["databricks-gpt-5-5"]
    assert t["requests"] == 907 and t["v2_requests"] == 903
    assert t["api_types"] == ["mlflow/v1/chat/completions"]


def test_v2_workspace_endpoints_come_from_traffic_not_the_serving_list():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5"),
             "databricks-claude-x": _v2_usage("databricks-claude-x", api_types=("openai/v1/responses",)),
             "proj-a-gpt": _v2_usage("proj-a-gpt"),
             "old-v1": {"requests": 5, "requesters": 1, "last_request": "x", "v2_requests": 0}}
    eps = m.v2_workspace_endpoints(usage, ["proj-a-gpt"])
    assert [e.name for e in eps] == ["databricks-claude-x", "databricks-gpt-5-5"]
    assert all(e.kind == "v2_workspace_endpoint" and e.source == "AI Gateway v2 (workspace-bound)" for e in eps)
    assert _ep(EXTERNAL).source == "Model Serving (v1)"


def test_v2_plan_rows_use_system_ai_and_check_the_api_types():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5"),
             "databricks-claude-x": _v2_usage("databricks-claude-x", api_types=("openai/v1/responses",)),
             "databricks-mystery": _v2_usage("databricks-mystery")}
    eps = m.v2_workspace_endpoints(usage, [])
    sys_map = {"databricks-gpt-5-5": "system.ai.gpt-5-5", "databricks-claude-x": "system.ai.claude-x"}
    supported = {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions", "openai/v1/chat/completions"],
                 "system.ai.claude-x": ["mlflow/v1/chat/completions"]}
    rows, _ = m.plan(eps, sys_map, usage, "c", "s", True, False, supported)
    by = {r.legacy_endpoint: r for r in rows}
    assert by["databricks-gpt-5-5"].action == "use_system_ai" and by["databricks-gpt-5-5"].target_service == "system.ai.gpt-5-5"
    assert any(n == m.V2_NEED for n in by["databricks-gpt-5-5"].needs_human)
    assert by["databricks-gpt-5-5"].api_types == ["mlflow/v1/chat/completions"]
    assert by["databricks-gpt-5-5"].target_api_types == supported["system.ai.gpt-5-5"]
    # Responses traffic that the target can't serve is a manual decision, with the reason in the note.
    assert by["databricks-claude-x"].action == "manual"
    assert any("openai/v1/responses" in n and "doesn't support" in n for n in by["databricks-claude-x"].needs_human)
    assert by["databricks-mystery"].action == "manual" and m.NO_SYSTEM_AI_NEED in by["databricks-mystery"].needs_human
    # Without the target's types, the row says so instead of guessing.
    rows2, _ = m.plan(eps, sys_map, usage, "c", "s", True, False, None)
    gpt = next(r for r in rows2 if r.legacy_endpoint == "databricks-gpt-5-5")
    assert gpt.action == "use_system_ai" and any("could not read the supported API types" in n for n in gpt.needs_human)


def test_platform_only_traffic_warns_and_other_callers_block():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5", requests=900)}
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    platform = [{"endpoint_name": "databricks-gpt-5-5", "caller_class": "platform", "requests": 900}]
    r = m.readiness(rows, [], True, 30, eps, {}, True, platform)
    assert r["status"] == "READY_WITH_WARNINGS" and not r["blockers"]
    warn = next(x for x in r["warnings"] if x["type"] == "platform_managed_traffic")
    assert warn["action"] == m.PLATFORM_ACTION and warn["caller_classes"] == {"platform": 900}
    assert "Genie" in warn["action"] and "account team" in warn["action"]
    mixed = platform + [{"endpoint_name": "databricks-gpt-5-5", "caller_class": "sdk", "requests": 50}]
    r2 = m.readiness(rows, [], True, 30, eps, {}, True, mixed)
    blocker = next(x for x in r2["blockers"] if x["type"] == "legacy_traffic")
    assert r2["status"] == "BLOCKED" and "sdk 50" in blocker["detail"] and "platform 900" in blocker["detail"]
    # No caller data: traffic blocks as it always did.
    assert m.readiness(rows, [], True, 30, eps, {}, True, None)["status"] == "BLOCKED"


def test_coding_agent_traffic_gets_the_ucode_action():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5", requests=3)}
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    callers = [{"endpoint_name": "databricks-gpt-5-5", "caller_class": "coding_agent", "requests": 3}]
    r = m.readiness(rows, [], True, 30, eps, {}, True, callers)
    blocker = next(x for x in r["blockers"] if x["type"] == "legacy_traffic")
    assert "move the coding agent to Unity Gateway with ucode (docs: coding agent integration)" in blocker["action"]


def test_v2_model_name_on_a_gateway_route_is_renamed_and_the_route_kept():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5")}
    eps = m.v2_workspace_endpoints(usage, [])
    targets = {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions", "openai/v1/responses"]}
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, targets)
    names = [e.name for e in eps]
    text = (f'client = OpenAI(base_url="{V2_CHAT.rsplit("/chat", 1)[0]}", api_key=t)\n'
            'client.chat.completions.create(model="databricks-gpt-5-5", messages=msgs)')
    s = m.Scanner(names, SYS_GPT, rows, v2_names=names, target_api_types=targets)
    s.scan_text("notebook", "/n", text)
    ref = s.refs[0]
    assert ref.pattern == "v2_gateway_model" and ref.line == 2 and ref.fix_confidence == "review"
    assert ref.fixed_line == 'client.chat.completions.create(model="system.ai.gpt-5-5", messages=msgs)'
    assert "keep the route" in ref.suggestion and "never switch a Responses route" in ref.suggestion
    # A Responses route the target can't serve: no rewrite, manual decision.
    bad = (f'client = OpenAI(base_url="{V2_RESPONSES.rsplit("/responses", 1)[0]}/responses")\n'
           'client.responses.create(model="databricks-gpt-5-5", input=x)')
    s2 = m.Scanner(names, SYS_GPT, rows, v2_names=names, target_api_types={"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    s2.scan_text("notebook", "/n", bad)
    assert s2.refs[0].pattern == "v2_gateway_model" and s2.refs[0].fixed_line is None
    assert s2.refs[0].suggestion.startswith("manual: system.ai.gpt-5-5 doesn't support openai/v1/responses")
    # Outside a gateway route the same name is an ordinary legacy reference.
    s3 = m.Scanner(names, SYS_GPT, rows, v2_names=names)
    s3.scan_text("notebook", "/n", 'cfg = {"model": "databricks-gpt-5-5"}')
    assert s3.refs[0].pattern == "legacy_endpoint_name"


def test_v2_call_site_blocks_enforce_with_its_own_type():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5")}
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    s = m.Scanner([e.name for e in eps], SYS_GPT, rows, v2_names=[e.name for e in eps])
    s.scan_text("notebook", "/n", f'OpenAI(base_url="{V2_CHAT}")\nc.create(model="databricks-gpt-5-5")')
    r = m.readiness(rows, s.refs, True, 30, eps, {}, True, None)
    types = [b["type"] for b in r["blockers"]]
    assert "v2_workspace_call" in types and "pay_per_token_call" not in types


def test_sdk_serving_query_is_never_rewritten():
    sys_map = dict(SYS_GPT)
    for text in ('resp = w.serving_endpoints.query(name="databricks-gpt-5-5", messages=msgs)',
                 'resp = w.serving_endpoints.query(\n    name="databricks-gpt-5-5",\n    messages=msgs)'):
        s = m.Scanner(["databricks-gpt-5-5"], sys_map, [])
        s.scan_text("notebook", "/n", text)
        ref = next(r for r in s.refs if r.legacy_endpoint == "databricks-gpt-5-5")
        assert ref.pattern == "sdk_serving_query" and ref.fixed_line is None and ref.fix_confidence is None
        assert "Unity Gateway query method" in ref.suggestion and "/ai-gateway/mlflow/v1" in ref.suggestion
    assert m.PATTERN_TEXT["sdk_serving_query"][0].startswith("Databricks SDK query call")


def test_regional_gateway_host_is_flagged_narrowly():
    text = ('BASE = "https://1234.ai-gateway.azuredatabricks.net/openai/v1"\n'
            'NOTE = "see https://docs.example.com/ai-gateway.html"\n'
            'X = "https://ai-gateway.example.com/x"')
    hits = [r for r in scan([], text) if r.pattern == "ai_gateway_regional_host"]
    assert [h.line for h in hits] == [1] and hits[0].fixed_line is None
    assert "/ai-gateway/ route" in hits[0].suggestion and "ai-gateway scoped PAT" in hits[0].suggestion
    assert "all-apis" in hits[0].suggestion


def test_multiline_chatdatabricks_gets_use_ai_gateway_guidance():
    text = 'llm = ChatDatabricks(\n    endpoint="databricks-gpt-5-5",\n    temperature=0,\n)'
    ref = scan(["databricks-gpt-5-5"], text, SYS_GPT)[0]
    assert ref.pattern == "ChatDatabricks" and ref.line == 2
    assert "spans lines" in ref.suggestion and "use_ai_gateway=True" in ref.suggestion
    assert ref.fixed_line == 'model="system.ai.gpt-5-5",'
    one = scan(["databricks-gpt-5-5"], 'llm = ChatDatabricks(endpoint="databricks-gpt-5-5")', SYS_GPT)[0]
    assert one.fixed_line == 'llm = ChatDatabricks(model="system.ai.gpt-5-5", use_ai_gateway=True)'
    assert "spans lines" not in one.suggestion


def test_dormant_agent_warns_and_an_active_agent_blocks():
    agent = _ep({"name": "agent-x", "id": "a1", "task": "agent/v1/responses",
                 "config": {"served_entities": [{"name": "a", "entity_name": "main.ml.agent", "entity_version": "1"}]}})
    rows, _ = m.plan([agent], {}, {}, "c", "s")
    dormant = m.readiness(rows, [], True, 30, [agent], {})
    assert dormant["status"] == "READY_WITH_WARNINGS" and not dormant["blockers"]
    assert "dormant_agent_endpoint" in [w["type"] for w in dormant["warnings"]]
    rows2, _ = m.plan([agent], {}, {"agent-x": {"requests": 5, "requesters": 1, "last_request": "x"}}, "c", "s")
    active = m.readiness(rows2, [], True, 30, [agent], {})
    assert "agent" in [b["type"] for b in active["blockers"]] and active["status"] == "BLOCKED"


def test_zero_traffic_pay_per_token_with_no_known_caller_caps_ready():
    rows, _ = m.plan([_ep(SYSTEM_PPT)], SYS_GPT, {}, "c", "s")
    r = m.readiness(rows, [], True, 30, [_ep(SYSTEM_PPT)], {"local_files": "ok"})
    assert r["status"] == "READY_WITH_WARNINGS"
    warn = next(w for w in r["warnings"] if w["type"] == "confirm_infrequent_callers")
    assert "monthly or quarterly" in warn["detail"] and "confirm infrequent callers" in warn["action"]


def test_callers_carry_caller_class_api_and_user_agent():
    by_req = [{"endpoint_name": "e", "requester": "ana@x.com", "api": "v2", "caller_class": "coding_agent",
               "user_agent": "opencode/1", "requests": 3, "last_request": "x"}]
    out = m.link_callers(by_req, [], {})
    assert out[0]["caller_class"] == "coding_agent" and out[0]["api"] == "v2" and out[0]["user_agent"] == "opencode/1"
    assert m.link_callers([{"endpoint_name": "e", "requester": "a@x.com", "requests": 1}], [], {})[0]["api"] == "v1"


def test_the_single_deadline_is_used_everywhere_and_can_be_overridden(monkeypatch):
    monkeypatch.setattr(m, "LEGACY_DEADLINE", "2027-03-30")
    assert m.deadline_text() == "March 30, 2027"
    rows, _ = m.plan([_ep(PT)], {}, {}, "c", "s")
    refs = [m.ClientReference("notebook", "/n", 1, "ai_query", "x", None, "x")]
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5", requests=5)}
    eps = m.v2_workspace_endpoints(usage, [])
    v2_rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    r = m.readiness(v2_rows + rows, refs, True, 30, eps + [_ep(PT)], {}, True,
                    [{"endpoint_name": "databricks-gpt-5-5", "caller_class": "sdk", "requests": 5}])
    text = m.readiness_md("https://x", r, 30) + m.summary_md("https://x", eps, v2_rows, [], [], 30, True, [], "BLOCKED")
    assert "March 30, 2027" in text and "confirmed as of 2026-11-01" in text
    for old in ("Nov 30", "November 30", "Mar 30", "Mar 30 2027", "v1 retires"):
        assert old not in text, old
    monkeypatch.setattr(m, "LEGACY_DEADLINE", "2028-01-05")
    assert m.deadline_text() == "January 5, 2028"
    assert "January 5, 2028" in m.readiness_md("https://x", r, 30)


def test_deadline_must_be_an_iso_date(monkeypatch):
    with pytest.raises(ValueError):
        m.validate_deadline("2027-02-30")
    with pytest.raises(ValueError):
        m.validate_deadline("March 30 2027")
    assert m.validate_deadline("2027-03-30") == "2027-03-30"
    with pytest.raises(SystemExit):
        m.main(["--deadline", "2027-13-01"])


def test_planner_source_has_no_stale_v2_date():
    from pathlib import Path
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "Nov 30" not in src and "November 30" not in src and "Mar 30" not in src


def test_system_pay_per_token_names_on_the_v2_route_get_the_api_type_check():
    usage = {"databricks-gpt-5-5": {**_v2_usage("databricks-gpt-5-5", requests=5, api_types=("openai/v1/responses",))}}
    rows, _ = m.plan([_ep(SYSTEM_PPT)], SYS_GPT, usage, "c", "s", True, False,
                     {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    row = rows[0]
    assert row.action == "manual" and row.api_types == ["openai/v1/responses"]
    assert any("openai/v1/responses" in n and "doesn't support" in n for n in row.needs_human)
    # The same name on a route the target serves keeps its system.ai move.
    ok, _ = m.plan([_ep(SYSTEM_PPT)], SYS_GPT, {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5")}, "c", "s",
                   True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    assert ok[0].action == "use_system_ai"
    s = m.Scanner(["databricks-gpt-5-5"], SYS_GPT, rows, v2_names=["databricks-gpt-5-5"],
                  target_api_types={"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    s.scan_text("notebook", "/n", f'OpenAI(base_url="{V2_RESPONSES.rsplit("/responses", 1)[0]}/responses")\n'
                                  'c.responses.create(model="databricks-gpt-5-5")')
    assert s.refs[0].pattern == "v2_gateway_model" and s.refs[0].fixed_line is None


def test_coding_agent_user_agents_reach_the_readiness_blocker():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5", requests=3)}
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    callers = [{"endpoint_name": "databricks-gpt-5-5", "caller_class": "coding_agent", "requests": 3,
                "user_agent": "opencode/1.18 ai-sdk"},
               {"endpoint_name": "databricks-gpt-5-5", "caller_class": "sdk", "requests": 1, "user_agent": None}]
    r = m.readiness(rows, [], True, 30, eps, {}, True, callers)
    blocker = next(x for x in r["blockers"] if x["type"] == "legacy_traffic")
    assert blocker["user_agents"] == ["opencode/1.18 ai-sdk"] and "opencode/1.18 ai-sdk" in blocker["detail"]
    assert "coding agent user agents" in blocker["detail"]


def test_mlflow_deployments_predict_is_never_rewritten():
    t = {"claims-summary-pt": "ai_gateway.migrated.claims-summary-pt"}
    s = m.Scanner(list(t), t, [])
    s.scan_text("file", "a.py", 'client.predict(endpoint="claims-summary-pt", inputs=batch)\n'
                                'client.predict(inputs=x, endpoint="claims-summary-pt")\nendpoint = "claims-summary-pt"\n')
    by = {r.line: r for r in s.refs}
    assert by[1].pattern == by[2].pattern == "mlflow_deployments_predict"
    assert not by[1].fixed_line and not by[2].fixed_line and "OpenAI client" in by[1].suggestion
    assert by[3].pattern == "legacy_endpoint_name" and by[3].fixed_line


# ---------------------------------------------------------------------------
# v2 calls that already fail, Unity Gateway unavailable, and tokens next to requests
# ---------------------------------------------------------------------------


def _v2_failing(name, requests=100, failed=96, status_501=90, tokens=5000):
    """A v2-only traffic entry where most calls failed (v2 is off for the workspace)."""
    return {"endpoint_name": name, "requests": requests, "requesters": 2, "last_request": "2026-10-30", "throttled": 0,
            "v2_requests": requests, "v2_failed": failed, "v2_status_501": status_501, "v2_tokens": tokens,
            "tokens": tokens, "api_types": ["mlflow/v1/chat/completions"]}


def test_v2_failures_and_tokens_are_summed_next_to_requests(monkeypatch):
    v1 = [{"endpoint_name": "a", "requests": "5", "requesters": "1", "last_request": "2026-10-01", "throttled": "0",
           "tokens": "300"}]
    v2 = [{"endpoint_name": "a", "requests": "7", "failed": "2", "status_501": "0", "tokens": "700",
           "requesters": "1", "last_request": "2026-10-20"},
          {"endpoint_name": "b", "requests": "4", "failed": "4", "status_501": "4", "tokens": "0",
           "requesters": "1", "last_request": "2026-10-20"}]
    t = m._merge_traffic(v1, v2)
    assert t["a"]["tokens"] == 1000 and t["a"]["v2_tokens"] == 700
    assert t["a"]["v2_failed"] == 2 and t["a"]["v2_status_501"] == 0
    assert t["b"]["v2_failed"] == 4 and t["b"]["v2_status_501"] == 4 and t["b"]["tokens"] == 0
    # The SQL counts failures per row: no status, status 0 or HTTP 501; 501 is also counted apart.
    assert "status_code IS NULL OR status_code IN (0, 501)" in m.V2_CALLER_SQL
    assert "sum(CASE WHEN status_code = 501" in m.V2_CALLER_SQL and "coalesce(sum(total_tokens), 0)" in m.V2_CALLER_SQL
    seen = []
    monkeypatch.setattr(m, "_sql", lambda w, wh, statement, params=None: seen.append(statement) or [])
    m.traffic(mock.MagicMock(), None, "1", 30)
    assert any("eu.input_token_count" in s and "eu.output_token_count" in s for s in seen)


def test_plan_rows_carry_tokens_and_v2_failures():
    usage = {"databricks-gpt-5-5": _v2_usage("databricks-gpt-5-5", requests=900)}
    usage["databricks-gpt-5-5"]["tokens"] = 4200
    usage["databricks-gpt-5-5"]["v2_tokens"] = 4200
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    assert rows[0].tokens_window == 4200 and rows[0].v2_tokens == 4200
    assert rows[0].v2_failed == 0 and rows[0].v2_status_501 == 0
    assert asdict(rows[0])["tokens_window"] == 4200


def test_v2_mostly_failing_needs_ten_requests_and_95_percent():
    def failing(**kw):
        return m.v2_mostly_failing(m.PlanRow("x", "v2_workspace_endpoint", "manual", None, None, None, [], None, None,
                                             [], [], [], **kw))
    assert failing(v2_requests=100, v2_failed=95) is True
    assert failing(v2_requests=100, v2_failed=94) is False
    assert failing(v2_requests=9, v2_failed=9) is False  # too few requests to say
    assert failing(v2_requests=10, v2_failed=10) is True


def test_v2_calls_already_failing_replace_the_plain_v2_blocker():
    usage = {"databricks-gpt-5-5": _v2_failing("databricks-gpt-5-5")}
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    s = m.Scanner([e.name for e in eps], SYS_GPT, rows, v2_names=[e.name for e in eps])
    s.scan_text("notebook", "/n", 'client.chat.completions.create(model="databricks-gpt-5-5", messages=m)')
    r = m.readiness(rows, s.refs, True, 30, eps, {}, True, [])
    assert r["status"] == "BLOCKED"
    assert [b["type"] for b in r["blockers"]] == ["v2_off_failing_calls"]  # one blocker, not two
    blocker = r["blockers"][0]
    assert blocker["label"] == "v2 calls are already failing in this workspace"
    assert blocker["action"] == ("v2 is off here: these callers get errors now. Move them to system.ai.gpt-5-5 first "
                                 "(keep the /ai-gateway/ route, change the model)")
    assert "96 of 100 AI Gateway v2 requests failed" in blocker["detail"] and "90 with HTTP 501" in blocker["detail"]
    assert "1 call site" in blocker["detail"] and "requests from" in blocker["detail"]


def test_healthy_v2_endpoint_keeps_the_plain_v2_blocker_and_few_failures_do_not_count():
    usage = {"databricks-gpt-5-5": _v2_failing("databricks-gpt-5-5", requests=100, failed=3, status_501=0)}
    eps = m.v2_workspace_endpoints(usage, [])
    rows, _ = m.plan(eps, SYS_GPT, usage, "c", "s", True, False, {"system.ai.gpt-5-5": ["mlflow/v1/chat/completions"]})
    s = m.Scanner([e.name for e in eps], SYS_GPT, rows, v2_names=[e.name for e in eps])
    s.scan_text("notebook", "/n", 'client.chat.completions.create(model="databricks-gpt-5-5", messages=m)')
    r = m.readiness(rows, s.refs, True, 30, eps, {}, True, [])
    assert [b["type"] for b in r["blockers"]] == ["v2_workspace_call"]
    # An endpoint with traffic and no code: the failing blocker replaces its traffic blocker (no double count).
    usage2 = {"proj-v2-chat": _v2_failing("proj-v2-chat", requests=50, failed=50, status_501=50)}
    eps2 = m.v2_workspace_endpoints(usage2, [])
    rows2, _ = m.plan(eps2, {}, usage2, "c", "s", True, False, {})
    r2 = m.readiness(rows2, [], True, 30, eps2, {}, True, [])
    assert [b["type"] for b in r2["blockers"]] == ["v2_off_failing_calls"]
    assert "50 of 50" in r2["blockers"][0]["detail"] and "requests from" in r2["blockers"][0]["detail"]
    # The failing blocker comes first, ahead of a plain v2 blocker for another endpoint.
    usage3 = dict(usage2, **{"proj-b": _v2_usage("proj-b")})
    eps3 = m.v2_workspace_endpoints(usage3, [])
    rows3, _ = m.plan(eps3, {}, usage3, "c", "s", True, False, {})
    r3 = m.readiness(rows3, [], True, 30, eps3, {}, True, [])
    assert [b["type"] for b in r3["blockers"]] == ["v2_off_failing_calls", "legacy_traffic"]


def test_unity_gateway_unavailable_is_recognised_and_blocks_with_the_plain_message():
    from databricks.sdk import errors as sdk_errors

    assert m.unity_gateway_unavailable(sdk_errors.NotImplemented("nope"))
    assert m.unity_gateway_unavailable(sdk_errors.PermissionDenied("denied"))
    assert m.unity_gateway_unavailable(sdk_errors.DatabricksError("off", error_code="FEATURE_DISABLED"))
    assert m.unity_gateway_unavailable(sdk_errors.DatabricksError("off", error_code="NOT_IMPLEMENTED"))
    assert m.unity_gateway_unavailable(RuntimeError("Unity Gateway is not enabled for this account"))
    assert m.unity_gateway_unavailable(RuntimeError("the AI Gateway feature is disabled"))
    assert not m.unity_gateway_unavailable(RuntimeError("connection reset by peer"))
    assert not m.unity_gateway_unavailable(sdk_errors.InternalError("try again"))

    cov = {}
    w = mock.MagicMock()
    w.ai_gateway.list_model_services.side_effect = sdk_errors.NotImplemented("not implemented here")
    assert m.system_ai_map(w, cov) == {} and cov["system_ai_map"].startswith("unavailable: ")
    rows, _ = m.plan([_ep(SYSTEM_PPT)], {}, {}, "c", "s", traffic_known=False)
    r = m.readiness(rows, [], True, 30, [], cov)
    assert r["status"] == "BLOCKED" and r["coverage_gaps"] == {}
    blocker = r["blockers"][0]
    assert blocker["type"] == "unity_gateway_unavailable"
    assert blocker["label"] == "Unity Gateway isn't available in this workspace"
    assert blocker["action"] == ("Ask your account team to enable Unity Gateway for this workspace and account. "
                                 "Nothing can be migrated until it is.")
    assert "not implemented here" in blocker["detail"]
    # Other errors stay a coverage gap, not a blocker.
    cov2 = {}
    w2 = mock.MagicMock()
    w2.ai_gateway.list_model_services.side_effect = RuntimeError("timeout talking to the API")
    m.system_ai_map(w2, cov2)
    r2 = m.readiness(rows, [], True, 30, [], cov2)
    assert r2["status"] == "INCOMPLETE" and "system_ai_map" in r2["coverage_gaps"] and not r2["blockers"]


def test_serving_endpoint_with_failing_v2_calls_keeps_its_own_blockers():
    # A v1 serving endpoint that also gets v2 calls which fail: the v2 blocker is added, and its own call site and
    # v1 traffic blocker stay (the traffic is folded into the pay-per-token blocker, as before).
    usage = {"databricks-gpt-5-5": _v2_failing("databricks-gpt-5-5")}
    rows, _ = m.plan([_ep(SYSTEM_PPT)], SYS_GPT, usage, "c", "s", True, False, {})
    s = m.Scanner(["databricks-gpt-5-5"], SYS_GPT, rows, v2_names=[])
    s.scan_text("notebook", "/n", 'client.responses.create(model="databricks-gpt-5-5")')
    r = m.readiness(rows, s.refs, True, 30, [_ep(SYSTEM_PPT)], {}, True, [])
    assert [b["type"] for b in r["blockers"]] == ["v2_off_failing_calls", "pay_per_token_call"]
    assert "requests from" in r["blockers"][1]["detail"]



def test_scrub_hides_header_env_and_connection_string_secrets():
    cases = {
        "headers['api-key'] = 'abcd1234efgh'": "headers['api-key'] = '<hidden>'",
        'headers["Authorization"] = "Bearer abcd1234efgh5678"': 'headers["Authorization"] = "Bearer <hidden>"',
        "os.environ['OPENAI_API_KEY'] = 'abcd1234efgh'": "os.environ['OPENAI_API_KEY'] = '<hidden>'",
        'os.environ["DATABRICKS_TOKEN"] = "abcd1234efgh"': 'os.environ["DATABRICKS_TOKEN"] = "<hidden>"',
        "h = {'x-api-key': 'abcd1234efgh'}": "h = {'x-api-key': '<hidden>'}",
        "d = {'token': 'abcd1234efgh'}": "d = {'token': '<hidden>'}",
        'c = "AccountName=foo;AccountKey=abcd1234efgh==;EndpointSuffix=core"':
            'c = "AccountName=foo;AccountKey=<hidden>;EndpointSuffix=core"',
        'c = "SharedAccessKeyName=root;SharedAccessKey=abcd1234efgh="':
            'c = "SharedAccessKeyName=root;SharedAccessKey=<hidden>"',
    }
    for line, want in cases.items():
        assert m.scrub(line) == want, line
    for safe in ('headers["Authorization"] = f"Bearer {tok}"', "headers['Content-Type'] = 'application/json'"):
        assert m.scrub(safe) == safe


def test_client_permission_and_provider_errors_are_not_counted_as_v2_off():
    # Only no status, status 0 and HTTP 501 (v2 retired) count as failed. 400, 403, 404, 429 and other 5xx can
    # come from the caller, its permissions, rate limits or the provider, so they never mark v2 as off.
    import ug_migration_account as acct
    import ug_migration_store as store
    for sql in (m.V2_CALLER_SQL, acct.UG_TRAFFIC_SQL,
                inspect.getsource(store.legacy_traffic_since)):
        assert "IN (0, 501)" in sql
        for broad in ("403", "404", "410", ">= 500", ">= 400"):
            assert broad not in sql, broad


def test_unmatched_v1_traffic_is_a_warning_not_a_gap():
    rows, _ = m.plan([_ep(EXTERNAL)], {}, {}, "c", "s")
    note = {"v1_unattributed": f"{m.UNATTRIBUTED_NOTE}: 12 v1 requests in 30 days have no served_entities match"}
    r = m.readiness(rows, [], True, 30, coverage=note)
    w = [x for x in r["warnings"] if x["type"] == "unattributed_legacy_traffic"]
    assert w and "12 v1 requests" in w[0]["detail"]
    assert r["status"] in ("READY_WITH_WARNINGS", "BLOCKED")  # a warning, never a coverage gap (INCOMPLETE)


def test_retarget_plan_moves_services_but_not_system_ai():
    rows, _ = m.plan([_ep(SYSTEM_PPT), _ep(EXTERNAL)], {"databricks-gpt-5-5": "system.ai.gpt-5-5"}, {}, "c", "s")
    moved = m.retarget_plan(rows, "cat2", "sch2")
    by = {r.legacy_endpoint: r for r in moved}
    ext = next(r for r in moved if r.kind == "external_model")
    assert ext.target_service.startswith("cat2.sch2.") and (ext.provider_service or "cat2.sch2.").startswith("cat2.sch2.")
    sys_row = next(r for r in moved if r.target_service and r.target_service.startswith("system.ai."))
    assert sys_row.target_service == "system.ai.gpt-5-5"
    assert all(r.target_service is None or not r.target_service.startswith("cat2.") for r in rows)  # input unchanged
    as_dicts = m.retarget_plan([{"target_service": "c.s.x", "provider_service": "c.s.p", "other": 1}], "a", "b")
    assert as_dicts == [{"target_service": "a.b.x", "provider_service": "a.b.p", "other": 1}]
    assert m.retarget_name("system.ai.x", "a", "b") == "system.ai.x" and m.retarget_name(None, "a", "b") is None
