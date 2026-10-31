"""Offline tests for ug_migration_planner using synthetic endpoint payloads."""

import base64
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
    assert fix[1] == ("SELECT ai_query('system.ai.gpt-5-5', p) FROM t", "auto")
    assert fix[2] == ("judge = 'databricks:/system.ai.gpt-5-5'", "auto")
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
    assert m.readiness(clean, [], True, 30)["status"] == "READY"
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


def test_pt_wrapper_is_a_readiness_warning():
    rows, _ = m.plan([_ep(PT)], {}, {}, "c", "s", traffic_known=False)
    r = m.readiness(rows, [], True, 30, [])
    assert any(w["type"] == "pt_wrapper_on_legacy_endpoint" for w in r["warnings"])


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
    assert r["status"] == "READY" and r["notes"] == cov
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
