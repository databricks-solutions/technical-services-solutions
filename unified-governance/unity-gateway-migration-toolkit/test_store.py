"""Offline tests for the app's Delta store helpers."""

import json
from types import SimpleNamespace

import pytest

import ug_migration_store as store


def test_lit_escapes_and_types():
    assert store._lit("it's \\ ok", "STRING") == "'it\\'s \\\\ ok'"
    assert store._lit("12.0", "BIGINT") == "12"
    assert store._lit(None, "STRING") == "NULL" and store._lit("", "BIGINT") == "NULL"
    # Timestamps carry an explicit UTC offset, so a job or warehouse in another time zone reads the same instant.
    assert store._lit("2026-10-30 10:00:00", "TIMESTAMP") == "TIMESTAMP '2026-10-30 10:00:00+00:00'"
    assert store._lit("2026-10-30T10:00:00Z", "TIMESTAMP") == "TIMESTAMP '2026-10-30 10:00:00Z'"
    assert store._lit("2026-10-30 10:00:00+02:00", "TIMESTAMP") == "TIMESTAMP '2026-10-30 10:00:00+02:00'"
    assert store._utc("2026-10-30") == "2026-10-30 00:00:00+00:00" and store._utc("2026-10-30 06:00") == "2026-10-30 06:00:00+00:00"


class FakeSpark:
    def __init__(self, rows):
        self.rows, self.statements = rows, []

    def sql(self, q):
        self.statements.append(q)
        rows = self.rows

        class R:
            def collect(self_inner):
                return rows
        return R()


class SparkByQuery:
    """Answers each SQL statement with the rows whose key appears in the statement (first match wins)."""

    def __init__(self, answers):
        self.answers, self.statements = answers, []

    def sql(self, q):
        self.statements.append(q)
        rows = next((rows for key, rows in self.answers if key in q), [])

        class R:
            def collect(self_inner):
                return rows
        return R()


class DescribeSpark:
    """Reports the columns an existing table has, and records the DDL that ensure_tables sends."""

    def __init__(self, have):
        self.have, self.statements = have, []

    def sql(self, q):
        self.statements.append(q)
        rows = [{"col_name": c} for c in self.have] if q.startswith("DESCRIBE") else []

        class R:
            def collect(self_inner):
                return rows
        return R()


class Workspace:
    """Stands in for WorkspaceClient: jobs.get_run answers with one life cycle state for every run."""

    def __init__(self, life_cycle):
        self.jobs = SimpleNamespace(get_run=lambda job_run_id: SimpleNamespace(
            state=SimpleNamespace(life_cycle_state=SimpleNamespace(value=life_cycle), result_state=None)))


def test_rollback_log_only_keeps_executed_creates(tmp_path):
    items = [{"payload": json.dumps(p)} for p in (
        {"type": "model_service", "name": "c.s.a", "action": "creating", "execute": True},
        {"type": "model_service", "name": "c.s.a", "action": "created", "execute": True},
        {"type": "model_service", "name": "c.s.b", "action": "would_create", "execute": False},
        {"type": "grant", "name": "c.s.a", "action": "granted", "execute": True})]
    path = tmp_path / "log.jsonl"
    n = store.apply_log_from_items(FakeSpark(items), "c.s", "abc", str(path))
    assert n == 2 and [json.loads(l)["action"] for l in path.read_text().splitlines()] == ["creating", "created"]


def test_upsert_builds_merge():
    sp = FakeSpark([])
    store.upsert(sp, "c.s", "ug_migration_scans", store.SCAN_COLUMNS, "run_id",
                 {"run_id": "r1", "status": "RUNNING", "endpoints": "3", "unknown": "x"})
    q = sp.statements[-1]
    assert q.startswith("MERGE INTO `c`.`s`.ug_migration_scans") and "'r1' AS run_id" in q and "3 AS endpoints" in q
    assert "unknown" not in q


def test_ids_are_escaped(tmp_path):
    sp = FakeSpark([])
    store.apply_log_from_items(sp, "c.s", "x' OR '1'='1", str(tmp_path / "l.jsonl"))
    assert "'x\\' OR \\'1\\'=\\'1'" in sp.statements[-1]


def test_durable_log_fallback(tmp_path):
    log = tmp_path / "durable.jsonl"
    log.write_text(json.dumps({"type": "model_service", "name": "c.s.a", "action": "creating", "execute": True}) + "\n")
    assert store.apply_log_from_items(FakeSpark([]), "c.s", "a", str(tmp_path / "out.jsonl"), str(log)) == 1


def test_ensure_tables_adds_the_fingerprint_column_to_old_tables():
    sp = DescribeSpark(have=[c for c in store.APPLY_COLUMNS if c != "fingerprint"])
    store.ensure_tables(sp, "c.s")
    assert "ALTER TABLE `c`.`s`.ug_migration_applies ADD COLUMNS (fingerprint STRING)" in sp.statements
    assert not any("ADD COLUMNS (apply_id" in s for s in sp.statements)


def test_apply_columns_include_the_fingerprint():
    assert store.APPLY_COLUMNS["fingerprint"] == "STRING"


def test_protection_runs_marks_finished_rollbacks():
    items = [{"apply_id": "A", "payload": json.dumps({"type": "model_service", "name": "c.s.x", "action": "created",
                                                       "execute": True})},
             {"apply_id": "B", "payload": json.dumps({"type": "model_service", "name": "c.s.y", "action": "exists",
                                                       "execute": True})}]
    executes = [{"apply_id": "A"}, {"apply_id": "B"}]
    rollbacks = [{"apply_id": "R", "rollback_of": "A", "status": "SUCCEEDED", "job_run_id": "1", "summary": "{}"}]
    sp = SparkByQuery([("apply_items", items), ("mode = 'rollback'", rollbacks), ("mode = 'execute'", executes)])
    runs = {r["apply_id"]: r for r in store.protection_runs(sp, "c.s")}
    assert runs["A"]["rolled_back"] is True and runs["B"]["rolled_back"] is False
    assert runs["B"]["entries"][0]["action"] == "exists"


def test_protection_runs_keeps_runs_without_stored_items(tmp_path):
    # A run killed before it stored its results has no item rows; its durable log still says what it created.
    (tmp_path / "KILLED.jsonl").write_text(
        json.dumps({"type": "model_service", "name": "c.s.x", "action": "created", "execute": True}) + "\n"
        + '{"torn line')
    sp = SparkByQuery([("apply_items", []), ("mode = 'rollback'", []), ("mode = 'execute'", [{"apply_id": "KILLED"}])])
    runs = store.protection_runs(sp, "c.s", str(tmp_path))
    assert [r["apply_id"] for r in runs] == ["KILLED"]
    assert runs[0]["entries"][0]["name"] == "c.s.x" and runs[0]["rolled_back"] is False


def test_rollback_done_is_the_one_definition():
    kept_by_other = json.dumps({"kept": 2, "kept_other_run": 2, "deleted": 1})
    assert store.rollback_done("SUCCEEDED", "{}") is True
    assert store.rollback_done("NEEDS_ATTENTION", kept_by_other) is True
    assert store.rollback_done("NEEDS_ATTENTION", {"kept": 2, "kept_other_run": 1}) is False  # one kept for a changed object
    assert store.rollback_done("NEEDS_ATTENTION", {"kept": 1, "kept_other_run": 1, "error": 1}) is False
    assert store.rollback_done("NEEDS_ATTENTION", {"manual": 1, "kept_other_run": 0}) is False
    assert store.rollback_done("FAILED", {"deleted": 3}) is False
    assert store.rollback_done("RUNNING", None) is False
    assert store.rollback_done("NEEDS_ATTENTION", None) is True  # written before kept_other_run existed
    assert store.rollback_done("NEEDS_ATTENTION", {"kept": 3}) is True  # same: no kept_other_run, so the old rule


def test_rollback_blocks_running_done_and_self():
    done = {"apply_id": "R1", "status": "SUCCEEDED", "job_run_id": "1", "summary": "{}"}
    running = {"apply_id": "R2", "status": "RUNNING", "job_run_id": "2", "summary": None}
    assert store.rollback_blocks([done]) is True
    assert store.rollback_blocks([running]) is True                       # no workspace to check: stay safe
    assert store.rollback_blocks([running], Workspace("RUNNING")) is True
    assert store.rollback_blocks([running], Workspace("TERMINATED")) is False  # killed rollback doesn't block
    assert store.rollback_blocks([done], exclude="R1") is False          # its own row never blocks it
    assert store.rollback_blocks([]) is False


def test_rolled_back_ids_follow_the_rule():
    rows = [{"apply_id": "R1", "rollback_of": "A", "status": "NEEDS_ATTENTION", "summary": {"kept": 1, "kept_other_run": 1}},
            {"apply_id": "R2", "rollback_of": "B", "status": "NEEDS_ATTENTION",
             "summary": {"error": 1, "kept_other_run": 0}},
            {"apply_id": "R3", "rollback_of": "C", "status": "SUCCEEDED", "summary": "{}"}]
    assert store.rolled_back_ids(rows) == {"A", "C"}


def test_running_applies_for_the_same_target():
    rows = [{"apply_id": "A", "job_run_id": "", "status": "RUNNING"}]
    sp = SparkByQuery([("mode = 'execute'", rows)])
    assert store.running_applies(sp, None, "c.s", "c", "s", "B") == ["A"]
    assert "target_catalog = 'c'" in sp.statements[-1] and "apply_id <> 'B'" in sp.statements[-1]


def test_is_run_active_follows_the_job_run():
    row = [{"mode": "execute", "operation": "apply", "status": "RUNNING", "job_run_id": "12"}]
    sp = SparkByQuery([("ug_migration_applies", row)])
    assert store.is_run_active(sp, Workspace("RUNNING"), "c.s", "A") is True
    assert store.is_run_active(sp, Workspace("TERMINATED"), "c.s", "A") is False  # killed: not active
    assert store.is_run_active(SparkByQuery([]), Workspace("RUNNING"), "c.s", "A") is False  # no row, not active


def test_log_from_items_keeps_reuse_and_added_grants(tmp_path):
    items = [{"payload": json.dumps(p)} for p in (
        {"type": "model_provider_service", "name": "c.s.p", "action": "exists", "execute": True},
        {"type": "model_service", "name": "c.s.a", "action": "updated", "execute": True},
        {"type": "grant", "name": "c.s.a", "action": "granted", "execute": True, "added": [{"principal": "g"}]},
        {"type": "grant", "name": "c.s.a", "action": "granted", "execute": True},
        {"type": "model_service", "name": "c.s.b", "action": "exists", "execute": False})]
    path = tmp_path / "log.jsonl"
    assert store.apply_log_from_items(FakeSpark(items), "c.s", "abc", str(path)) == 3


def test_selection_fingerprint_is_order_independent_and_canonical():
    base = {"scan_run_id": "S", "endpoints": "ep-b,ep-a", "target_catalog": "c", "target_schema": "s",
            "uc_secret_map": json.dumps({"b/k": "secrets/c.s.b", "a/k": "secrets/c.s.a"}, sort_keys=True),
            "allow_secret_read": "false", "grants": "false", "ack_guardrails": "false"}
    same = {**base, "endpoints": "ep-a,ep-b", "uc_secret_map": json.dumps({"a/k": "secrets/c.s.a", "b/k": "secrets/c.s.b"}),
            "grants": "False", "requested_by": "someone", "smoke_test": "true", "force": "true"}
    assert store.selection_fingerprint(base) == store.selection_fingerprint(same)
    assert store.selection_fingerprint(base) != store.selection_fingerprint({**base, "endpoints": "ep-a"})
    assert store.selection_fingerprint(base) != store.selection_fingerprint({**base, "grants": "true"})
    # A missing value counts as empty, the same as an empty string.
    assert store.selection_fingerprint({"scan_run_id": "S"}) == store.selection_fingerprint({"scan_run_id": "S", "endpoints": ""})


def test_scrub_hides_credentials():
    import ug_migration_planner as p
    assert p.scrub('OpenAI(api_key="sk-abcdefghijklmnop")') == 'OpenAI(api_key="<hidden>")'
    assert "{{secrets/s/k}}" in p.scrub('token = "{{secrets/s/k}}"')
    assert p.scrub("ai_query('risk-sk-scoring-v2', 'x')") == "ai_query('risk-sk-scoring-v2', 'x')"
    for line in ('aws_secret_access_key = "abcdefgh123"', 'openai_key = "abcdefgh123"', 'db_pwd = "hunter2222"',
                 'client_secret_value = "abcdefgh123"'):
        assert "abcdefgh123" not in p.scrub(line) and "hunter2222" not in p.scrub(line), line
    assert p.scrub('endpoint = "databricks-gpt-5-5"') == 'endpoint = "databricks-gpt-5-5"'


def test_plaintext_key_is_manual():
    import pytest
    import ug_migration_apply as a
    with pytest.raises(a.Manual):
        a.Secrets(None, {}, False).resolve(None, plaintext="<redacted plaintext>")


def test_rollback_keeps_protected(tmp_path):
    import ug_migration_apply as a

    class Obj:
        comment = a.TOOL_MARK

        def as_dict(self):
            return {"comment": self.comment}

    class GW:
        deleted = []
        def get_model_service(self, name): return Obj()
        def delete_model_service(self, name): self.deleted.append(name)

    class W:
        ai_gateway = GW()

    log = tmp_path / "l.jsonl"
    log.write_text(json.dumps({"type": "model_service", "name": "c.s.a", "action": "created", "execute": True}) + "\n")
    out = a.rollback(W(), str(log), execute=True, protect={("model_service", "c.s.a")})
    assert out[-1]["action"] == "kept" and not GW.deleted


def test_rate_limit_caps():
    import pytest
    import ug_migration_apply as a
    import ug_migration_planner as p
    ep = p.LegacyEndpoint("e", "id", "provisioned_throughput",
                          destinations=[{"type": "provisioned_throughput", "served_entity": "x", "traffic_percentage": 100}])
    row = p.PlanRow("e", "provisioned_throughput", "create_model_service", "c.s.e", None, None,
                    [{"key": "RATE_LIMIT_KEY_USER_GROUP", "principal": f"g{i}", "calls": 1,
                      "renewal_period": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE"} for i in range(6)],
                    None, None, [], [], [])
    with pytest.raises(a.Manual):
        a.build_model_service(ep, row, {})


def test_every_store_function_the_notebooks_call_exists():
    import pathlib
    import re
    import ug_migration_store as store
    root = pathlib.Path(__file__).parent / "notebook"
    called = {m for f in root.glob("*.py") for m in re.findall(r"\bstore\.([a-z_]+)\(", f.read_text())}
    assert called and not [n for n in called if not hasattr(store, n)]


# ---------------------------------------------------------------------------
# Verify and cut over: operation column, fingerprints, write-side lock, verify query builders (offline)
# ---------------------------------------------------------------------------


def test_apply_columns_carry_the_operation_services_and_api_type():
    assert store.APPLY_COLUMNS["operation"] == "STRING"
    assert store.APPLY_COLUMNS["services"] == "STRING" and store.APPLY_COLUMNS["api_type"] == "STRING"
    assert "refused" in store.PROBLEM_ACTIONS and "test_failed" in store.PROBLEM_ACTIONS


def test_apply_run_reads_the_operation_and_defaults_to_apply():
    sp = SparkByQuery([("ug_migration_applies", [{"mode": "execute", "operation": None, "status": "SUCCEEDED",
                                                  "job_run_id": "1"}])])
    assert store.apply_run(sp, "c.s", "A")["operation"] == "apply"
    sp2 = SparkByQuery([("ug_migration_applies", [{"mode": "execute", "operation": "pause_legacy",
                                                   "status": "SUCCEEDED", "job_run_id": "1"}])])
    assert store.apply_run(sp2, "c.s", "A")["operation"] == "pause_legacy"
    assert store.apply_run(SparkByQuery([]), "c.s", "A") is None


def test_apply_only_queries_exclude_cutover_runs():
    sp = SparkByQuery([("apply_items", []), ("mode = 'rollback'", []), ("mode = 'execute'", [])])
    store.protection_runs(sp, "c.s")
    assert sum("operation IS NULL OR" in s for s in sp.statements) == 2
    sp2 = SparkByQuery([("ug_migration_applies", [])])
    store.running_applies(sp2, None, "c.s", "t", "s", "A")
    assert "operation IS NULL OR operation = 'apply'" in sp2.statements[-1]


def test_running_legacy_lists_other_write_runs_still_running():
    rows = [{"apply_id": "A", "job_run_id": "1", "status": "RUNNING"},
            {"apply_id": "B", "job_run_id": "2", "status": "RUNNING"}]
    sp = SparkByQuery([("operation IN", rows)])
    assert store.running_legacy(sp, None, "c.s", "Z") == ["A", "B"]
    assert "'pause_legacy'" in sp.statements[-1] and "'resume_legacy'" in sp.statements[-1]
    assert "apply_id <> 'Z'" in sp.statements[-1]
    assert store.running_legacy(sp, Workspace("TERMINATED"), "c.s", "Z") == []  # killed runs don't block


def test_legacy_fingerprint_is_order_and_default_tolerant():
    base = {"operation": "pause_legacy", "endpoints": "b,a", "api_type": "", "prompt": "", "force": "false"}
    same = {"operation": "pause_legacy", "endpoints": "a, b", "api_type": "mlflow/v1/chat/completions",
            "prompt": "Reply with: ok", "force": "False"}
    assert store.legacy_fingerprint(base) == store.legacy_fingerprint(same)
    assert store.legacy_fingerprint(base) != store.legacy_fingerprint({**base, "endpoints": "a"})
    assert store.legacy_fingerprint({"operation": "resume_legacy", "rollback_of": "x", "force": "true"}) != \
        store.legacy_fingerprint({"operation": "resume_legacy", "rollback_of": "x", "force": "false"})


def test_run_fingerprint_keeps_apply_runs_on_the_selection_hash():
    assert store.run_fingerprint({"operation": "apply", "endpoints": "a"}) == \
        store.selection_fingerprint({"endpoints": "a"})
    assert store.run_fingerprint({"operation": "test_call", "services": "c.s.b, c.s.a"}) == \
        store.legacy_fingerprint({"operation": "test_call", "services": "c.s.a,c.s.b"})


def test_legacy_run_entries_prefers_stored_rows_then_the_durable_log(tmp_path):
    stored = [{"payload": json.dumps({"type": "serving_endpoint", "name": "e", "action": "paused"})}]
    sp = SparkByQuery([("apply_items", stored)])
    assert store.legacy_run_entries(sp, "c.s", "P", str(tmp_path / "none.jsonl"))[0]["action"] == "paused"
    log = tmp_path / "P.jsonl"
    log.write_text(json.dumps({"type": "serving_endpoint", "name": "x", "action": "paused"}) + "\n" + '{"torn')
    entries = store.legacy_run_entries(SparkByQuery([("apply_items", [])]), "c.s", "P", str(log))
    assert [e["name"] for e in entries] == ["x"]


def test_resume_rows_count_as_rolled_back_only_when_complete():
    assert store.rollback_done("NEEDS_ATTENTION", {"kept": 1, "kept_other_run": 0, "resumed": 1}) is False
    assert store.rollback_done("SUCCEEDED", {"resumed": 2, "kept_other_run": 0}) is True


def test_traffic_sql_binds_every_value_and_covers_v1_and_v2():
    sql, params = store.legacy_traffic_since(["legacy-ext-1", "legacy-chat-2"], "2026-10-01", "123")
    assert "system.serving.endpoint_usage" in sql and "system.ai_gateway.usage" in sql
    assert "service_type IS NULL" in sql and "UNION ALL" in sql
    assert ":workspace_id" in sql and "CAST(:since AS TIMESTAMP)" in sql
    assert params["workspace_id"] == "123" and params["since"] == "2026-10-01 00:00:00+00:00"
    assert sorted(v for k, v in params.items() if k.startswith("v1_")) == ["legacy-chat-2", "legacy-ext-1"]
    assert sorted(v for k, v in params.items() if k.startswith("v2_")) == ["legacy-chat-2", "legacy-ext-1"]
    assert "legacy-ext-1" not in sql and "legacy-chat-2" not in sql  # names are bound, never interpolated
    assert "AS failed" in sql and "AS tokens" in sql and "input_token_count" in sql and "total_tokens" in sql


def test_traffic_sql_rejects_bad_input():
    with pytest.raises(ValueError):
        store.legacy_traffic_since(["x'; DROP TABLE t; --"], "2026-10-01", "1")
    with pytest.raises(ValueError):
        store.legacy_traffic_since([], "2026-10-01", "1")
    with pytest.raises(ValueError):
        store.legacy_traffic_since(["a"], "2026-10-01'; --", "1")


def test_usage_summary_counts_model_services_only():
    sql, params = store.ug_usage_summary("c.s.llama", "2026-10-01")
    assert "service_type = 'MODEL_SERVICE'" in sql and "AND service_name = :service" in sql
    assert params == {"since": "2026-10-01 00:00:00+00:00", "service": "c.s.llama"}
    for part in ("count(DISTINCT request_id)", "percentile_approx(latency_ms, 0.95)", "error_invocations",
                 "GROUP BY service_name, workspace_id, requester, api_type, destination_model"):
        assert part in sql
    sql_all, params_all = store.ug_usage_summary("", "2026-10-01T06:00")
    assert ":service" not in sql_all and params_all == {"since": "2026-10-01 06:00:00+00:00"}
    with pytest.raises(ValueError):
        store.ug_usage_summary("c.s.llama'; --", "2026-10-01")


def test_request_lookup_binds_the_id():
    sql, params = store.ug_request_lookup("abc-123")
    assert ":request_id" in sql and "abc-123" not in sql and params == {"request_id": "abc-123"}
    with pytest.raises(ValueError):
        store.ug_request_lookup("")
    with pytest.raises(ValueError):
        store.ug_request_lookup("a b")


def test_run_built_passes_the_bound_values_to_spark():
    seen = {}

    class Spark:
        def sql(self, q, args=None):
            seen["args"] = args

            class R:
                def collect(self_inner):
                    return [{"invocation_id": "i1"}]
            return R()

    assert store.run_built(Spark(), store.ug_request_lookup("req-1")) == [{"invocation_id": "i1"}]
    assert seen["args"] == {"request_id": "req-1"}


def test_traffic_sql_counts_unmatched_v1_requests_so_pause_fails_closed():
    sql, _ = store.legacy_traffic_since(["legacy-ext-1"], "2026-10-01", "123")
    assert "LEFT JOIN system.serving.served_entities" in sql and "se.served_entity_id IS NULL" in sql
    assert f"'{store.UNATTRIBUTED}' AS endpoint_name" in sql


def test_dry_run_used_lookup_is_bound():
    sql, params = store.dry_run_used("c.s", "11111111-1111-1111-1111-111111111111")
    assert "`c`.`s`.ug_migration_applies" in sql and "dry_run_id = :dry_run_id" in sql and "mode = 'execute'" in sql
    assert params == {"dry_run_id": "11111111-1111-1111-1111-111111111111"}
    assert store.APPLY_COLUMNS["dry_run_id"] == "STRING"  # ensure_tables adds it to older tables


def test_rollback_done_ignores_preexisting_kept_objects():
    assert store.rollback_done("NEEDS_ATTENTION", {"kept": 2, "kept_other_run": 1, "kept_preexisting": 1}) is True
    assert store.rollback_done("NEEDS_ATTENTION", {"kept": 2, "kept_other_run": 0, "kept_preexisting": 1}) is False


def test_job_sessions_run_in_utc():
    seen = {}
    store.use_utc(SimpleNamespace(conf=SimpleNamespace(set=lambda k, v: seen.__setitem__(k, v))))
    assert seen == {"spark.sql.session.timeZone": "UTC"}
    store.use_utc(object())  # a session without conf is left alone
