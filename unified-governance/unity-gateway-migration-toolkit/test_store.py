"""Offline tests for the app's Delta store helpers."""

import json

import ug_migration_store as store


def test_lit_escapes_and_types():
    assert store._lit("it's \\ ok", "STRING") == "'it\\'s \\\\ ok'"
    assert store._lit("12.0", "BIGINT") == "12"
    assert store._lit(None, "STRING") == "NULL" and store._lit("", "BIGINT") == "NULL"
    assert store._lit("2026-10-30 10:00:00", "TIMESTAMP") == "TIMESTAMP '2026-10-30 10:00:00'"


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


class SparkByQuery:
    """Answers each SQL statement with the rows whose key appears in the statement."""

    def __init__(self, answers):
        self.answers, self.statements = answers, []

    def sql(self, q):
        self.statements.append(q)
        rows = next((rows for key, rows in self.answers if key in q), [])

        class R:
            def collect(self_inner):
                return rows
        return R()


def test_protection_runs_marks_finished_rollbacks():
    items = [{"apply_id": "A", "payload": json.dumps({"type": "model_service", "name": "c.s.x", "action": "created",
                                                       "execute": True})},
             {"apply_id": "B", "payload": json.dumps({"type": "model_service", "name": "c.s.y", "action": "exists",
                                                       "execute": True})}]
    sp = SparkByQuery([("ug_migration_apply_items", items), ("mode = 'rollback'", [{"rollback_of": "A"}])])
    runs = {r["apply_id"]: r for r in store.protection_runs(sp, "c.s")}
    assert runs["A"]["rolled_back"] is True and runs["B"]["rolled_back"] is False
    assert runs["B"]["entries"][0]["action"] == "exists"


def test_running_applies_for_the_same_target():
    rows = [{"apply_id": "A", "job_run_id": "", "status": "RUNNING"}]
    sp = SparkByQuery([("mode = 'execute'", rows)])
    assert store.running_applies(sp, None, "c.s", "c", "s", "B") == ["A"]
    assert "target_catalog = 'c'" in sp.statements[-1] and "apply_id <> 'B'" in sp.statements[-1]


def test_log_from_items_keeps_reuse_and_added_grants(tmp_path):
    items = [{"payload": json.dumps(p)} for p in (
        {"type": "model_provider_service", "name": "c.s.p", "action": "exists", "execute": True},
        {"type": "model_service", "name": "c.s.a", "action": "updated", "execute": True},
        {"type": "grant", "name": "c.s.a", "action": "granted", "execute": True, "added": [{"principal": "g"}]},
        {"type": "grant", "name": "c.s.a", "action": "granted", "execute": True},
        {"type": "model_service", "name": "c.s.b", "action": "exists", "execute": False})]
    path = tmp_path / "log.jsonl"
    assert store.apply_log_from_items(FakeSpark(items), "c.s", "abc", str(path)) == 3


def test_durable_log_fallback(tmp_path):
    log = tmp_path / "durable.jsonl"
    log.write_text(json.dumps({"type": "model_service", "name": "c.s.a", "action": "creating", "execute": True}) + "\n")
    assert store.apply_log_from_items(FakeSpark([]), "c.s", "a", str(tmp_path / "out.jsonl"), str(log)) == 1


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
