"""Offline tests for ug_migration_planner using synthetic endpoint payloads."""

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
    assert any("Sensitive Data Detection" in n for n in a.needs_human)
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
    assert fix[5][0] == "r = requests.post(f'{host}/ai-gateway/mlflow/v1/chat/completions')"
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
    eps = [_ep(EXTERNAL), _ep(EXTERNAL_SAME_KEY)]
    full = m.readiness(rows, refs, True, 30, eps)
    assert [c["endpoint"] for c in full["rate_limit_zero_candidates"]] == ["proj-b-gpt"]
    cand = full["rate_limit_zero_candidates"][0]
    assert cand["ai_gateway_body"]["rate_limits"] == [{"key": "endpoint", "calls": 0, "renewal_period": "minute"}]
    assert "usage_tracking_config" not in cand["undo_body"]
    refs2 = refs + [m.ClientReference("notebook", "/n", 1, "legacy_endpoint_name", "'proj-b-gpt'", "proj-b-gpt", "x")]
    assert m.readiness(rows, refs2, True, 30, eps)["rate_limit_zero_candidates"] == []
    gap = m.readiness(rows, refs, True, 30, eps, {"apps": "failed: 403"})
    assert gap["rate_limit_zero_candidates"] == [] and gap["coverage_gaps"] == {"apps": "failed: 403"}
    a_ep = _ep(EXTERNAL)  # proj-a-gpt keeps its other rate limits when closed
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
    assert r["status"] == "READY_WITH_WARNINGS" and not r["blockers"]
    assert r["warnings"][0]["type"] == "legacy_traffic_kept_after_enforce"
    assert r["rate_limit_zero_candidates"] == []  # it has traffic
