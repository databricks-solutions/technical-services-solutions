"""Offline tests for the apply payload builders, the apply/rollback safety rules, and the fakes they run on."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from databricks.sdk.errors import AlreadyExists, NotFound

import ug_migration_apply as a
import ug_migration_planner as m
from test_planner import EXTERNAL, EXTERNAL_SAME_KEY, PT, _ep

APPLY = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
RB = "33333333-3333-3333-3333-333333333333"


class FakeSecrets(a.Secrets):
    def __init__(self, uc_map=None, allow_read=False):
        super().__init__(None, uc_map, allow_read)


def _plan(eps):
    return m.plan(eps, {}, {}, "c", "s", traffic_known=False)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Obj:
    def __init__(self, d):
        self.d = dict(d)

    @property
    def comment(self):
        return self.d.get("comment")

    @property
    def etag(self):
        return self.d.get("etag")

    def as_dict(self):
        return dict(self.d)


class FakeAI:
    def __init__(self):
        self.services, self.providers, self.calls = {}, {}, []
        self.race = False  # create loses a race: someone else stored the same object, then AlreadyExists
        self.drop_fallback = False  # the service reads back without its fallback
        self._n = 0

    def _stamp(self, d):
        self._n += 1
        d["etag"], d["update_time"] = f"etag{self._n}", f"t{self._n}"
        return d

    def get_model_service(self, name):
        key = name.split("/", 1)[1]
        if key not in self.services:
            raise NotFound(key)
        return Obj(self.services[key])

    def get_model_provider_service(self, name):
        key = name.split("/", 1)[1]
        if key not in self.providers:
            raise NotFound(key)
        return Obj(self.providers[key])

    def create_model_service(self, model_service, parent, model_service_id):
        fqn = f"{parent[len('schemas/'):]}.{model_service_id}"
        self.calls.append(("create_model_service", fqn))
        obj = model_service.as_dict()
        cfg = obj["config"]
        if self.drop_fallback:
            cfg["routing"].pop("fallback", None)
        stored = self._stamp({"comment": obj.get("comment"), "config": cfg})
        self.services[fqn] = stored
        if self.race:
            raise AlreadyExists(fqn)
        return Obj(stored)

    def create_model_provider_service(self, model_provider_service, parent, model_provider_service_id):
        fqn = f"{parent[len('schemas/'):]}.{model_provider_service_id}"
        self.calls.append(("create_model_provider_service", fqn))
        obj = model_provider_service.as_dict()
        stored = self._stamp({"comment": obj.get("comment"), "config": obj["config"]})
        self.providers[fqn] = stored
        return Obj(stored)

    def update_model_provider_service(self, name, model_provider_service, update_mask, etag=None):
        key = name.split("/", 1)[1]
        self.calls.append(("update_model_provider_service", key, tuple(update_mask.paths), etag))
        targets = model_provider_service.as_dict()["config"]["targets"]
        self.providers[key]["config"]["targets"] = targets
        return Obj(self._stamp(self.providers[key]))

    def delete_model_service(self, name, etag=None):
        key = name.split("/", 1)[1]
        self.calls.append(("delete_model_service", key, etag))
        self.services.pop(key)

    def delete_model_provider_service(self, name, etag=None):
        key = name.split("/", 1)[1]
        self.calls.append(("delete_model_provider_service", key, etag))
        self.providers.pop(key)

    def list_model_services(self, page_size=None, page_token=None):
        return [Obj({"name": f"model-services/{k}", **v}) for k, v in self.services.items()]


class FakeGrants:
    def __init__(self):
        self.privs, self.updates = {}, []
        self.fail = False

    def get(self, securable_type, full_name):
        cur = self.privs.get(full_name, {})
        return Obj({"privilege_assignments": [{"principal": p, "privileges": sorted(s)} for p, s in cur.items()]})

    def update(self, securable_type, full_name, changes):
        if self.fail:
            raise RuntimeError("permission denied on grants")
        self.updates.append((full_name, changes))
        cur = self.privs.setdefault(full_name, {})
        for c in changes:
            for p in c.add or []:
                cur.setdefault(c.principal, set()).add(p.value)
            for p in c.remove or []:
                cur.get(c.principal, set()).discard(p.value)


class FakeSecretsUc:
    def __init__(self, known=()):
        self.known = set(known)

    def get_secret(self, full_name, include_value=None):
        if full_name not in self.known:
            raise NotFound(full_name)
        return Obj({"name": full_name})


class FakeW:
    def __init__(self, uc_known=("c.s.openai_key",)):
        self.ai_gateway = FakeAI()
        self.grants = FakeGrants()
        self.secrets_uc = FakeSecretsUc(uc_known)
        self.schemas = SimpleNamespace(get=lambda full: None)


def _run(monkeypatch, tmp_path, w, eps, uc_map=None, allowed=("c.s",), execute=True, **kw):
    kw.setdefault("ack_guardrails", True)  # the EXTERNAL fixture has legacy guardrails
    monkeypatch.setattr(m, "inventory", lambda _w: eps)
    log = tmp_path / "apply.jsonl"
    sec = a.Secrets(w, uc_map, False, dry_run=not execute, allowed_schemas=list(allowed), read_enabled=False)
    res = a.apply(w, [e.name for e in eps], "c", "s", execute, sec, str(log), apply_id=APPLY, **kw)
    return res, log


def _target(eps):
    rows, _ = _plan(eps)
    return rows[0].target_service


UC_MAP = {"llm/openai": "secrets/c.s.openai_key"}


# ---------------------------------------------------------------------------
# Payload builders (existing behaviour)
# ---------------------------------------------------------------------------


def test_provider_from_uc_secret():
    eps = [_ep(EXTERNAL), _ep(EXTERNAL_SAME_KEY)]
    _, providers = _plan(eps)
    dests = [d for e in eps for d in e.destinations]
    body = a.build_provider(dests, FakeSecrets({"llm/openai": "secrets/c.s.openai_key"}))
    cfg = body["config"]
    assert cfg["provider_type"] == "EXTERNAL_MODEL_PROVIDER_TYPE_OPENAI" and cfg["allow_all_targets"] is False
    assert cfg["openai"]["direct"]["api_key"] == {"secret_reference": {"name": "secrets/c.s.openai_key"}}
    assert [t["model"] for t in cfg["targets"]] == ["gpt-5", "gpt-5-mini"]
    assert cfg["targets"][0]["native_api_types"] == ["openai/v1/chat/completions"]


def test_provider_needs_secret_decision():
    with pytest.raises(a.Manual, match="uc-secret-map"):
        a.build_provider(_ep(EXTERNAL).destinations, FakeSecrets())


def test_model_service_fallback_and_limits():
    ep = _ep(EXTERNAL)
    rows, providers = _plan([ep])
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    body = a.build_model_service(ep, rows[0], fqn, ack_guardrails=True)
    routing = body["config"]["routing"]
    assert [d["name"] for d in routing["destinations"]] == ["primary"]
    assert "traffic_percentage" not in routing["destinations"][0]
    assert [d["name"] for d in routing["fallback"]["destinations"]] == ["backup"]
    ext = routing["destinations"][0]["external_model_config"]
    assert ext["model_provider_service"] == "model-provider-services/c.s.openai_llm_openai"
    assert ext["target"]["model"] == "gpt-5"
    assert len(body["config"]["rate_limits"]) == 3
    assert body["config"]["inference_table"] == {"parent": "schemas/main.logs", "table_name_prefix": "proj_a_ug"}


def test_fallback_only_when_legacy_fallback_enabled():
    ep = _ep(EXTERNAL)
    ep.fallback_enabled = False
    rows, providers = _plan([ep])
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    assert "fallback" not in a.build_model_service(ep, rows[0], fqn, ack_guardrails=True)["config"]["routing"]


def test_model_service_pt():
    ep = _ep(PT)
    rows, _ = _plan([ep])
    body = a.build_model_service(ep, rows[0], {})
    d = body["config"]["routing"]["destinations"][0]
    assert d["provisioned_throughput_config"] == {"model_serving_endpoint": "serving-endpoints/llama-pt"}


def test_mask_hides_plaintext():
    masked = a._mask({"config": {"openai": {"direct": {"api_key": {"plaintext": "sk-real"}}}}})
    assert masked["config"]["openai"]["direct"]["api_key"]["plaintext"] == "***"


def test_mask_hides_secret_like_keys_but_not_rate_limit_tokens():
    masked = a._mask({"client_secret_value": "abc", "access_token": "t0k", "db_password": "pw", "openai_api_key": "k",
                      "rate_limits": [{"tokens": 1000, "requests": 5}],
                      "api_key": {"secret_reference": {"name": "secrets/c.s.k"}},
                      "allow_secret_read_enabled": True, "secret_schemas": "c.s"})
    assert masked["client_secret_value"] == "***" and masked["access_token"] == "***"
    assert masked["db_password"] == "***" and masked["openai_api_key"] == "***"
    assert masked["rate_limits"] == [{"tokens": 1000, "requests": 5}]
    assert masked["api_key"] == {"secret_reference": {"name": "secrets/c.s.k"}}
    assert masked["allow_secret_read_enabled"] is True and masked["secret_schemas"] == "c.s"


def test_to_hcl():
    out = a.to_hcl({"a": "x${y}", "b": [1, True], "c": a.RawHCL("var.k"), "d": {}})
    assert 'a = "x$${y}"' in out and "c = var.k" in out and "true" in out


def test_terraform_export(tmp_path, monkeypatch):
    from test_planner import SYSTEM_PPT
    eps = [_ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}]),
           _ep(EXTERNAL_SAME_KEY), _ep(PT), _ep(SYSTEM_PPT)]
    monkeypatch.setattr(m, "inventory", lambda w: eps)

    class W:
        class config:
            host = "https://example"
    out = tmp_path / "main.tf"
    res = a.terraform(W(), None, "c", "s", None, str(out), ack_guardrails=True)
    tf = out.read_text()
    assert res["provider_services"] == 1 and res["model_services"] == 3
    assert res["variables"] == ["secret_llm_openai"]
    assert 'variable "secret_llm_openai"' in tf and "sensitive   = true" in tf
    assert "plaintext = var.secret_llm_openai" in tf and "sk-" not in tf
    assert 'resource "databricks_grants" "service_proj_a_gpt"' in tf
    assert "depends_on = [databricks_ai_gateway_model_provider_service.provider_openai_llm_openai]" in tf
    res2 = a.terraform(W(), None, "c", "s", {"llm/openai": "secrets/c.s.openai"}, str(out))
    assert res2["variables"] == [] and '"secrets/c.s.openai"' in out.read_text()


def test_terraform_header_marks_draft_and_authoritative_grants(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "inventory", lambda w: [_ep(EXTERNAL)])

    class W:
        class config:
            host = "https://example"
    out = tmp_path / "main.tf"
    a.terraform(W(), None, "c", "s", None, str(out), ack_guardrails=True)
    head = "\n".join(out.read_text().splitlines()[:8])
    assert "DRAFT" in head and "terraform validate" in head and "AUTHORITATIVE" in head


def test_rate_limit_caps_are_described_as_toolkit_caps():
    ep = m.LegacyEndpoint("e", "id", "provisioned_throughput",
                          destinations=[{"type": "provisioned_throughput", "served_entity": "x", "traffic_percentage": 100}])
    row = m.PlanRow("e", "provisioned_throughput", "create_model_service", "c.s.e", None, None,
                    [{"key": "RATE_LIMIT_KEY_USER_GROUP", "principal": f"g{i}", "calls": 1,
                      "renewal_period": "RATE_LIMIT_RENEWAL_PERIOD_MINUTE"} for i in range(6)],
                    None, None, [], [], [])
    with pytest.raises(a.Manual, match="toolkit safety caps"):
        a.build_model_service(ep, row, {})


def test_guardrails_block_without_ack_and_are_listed_with_ack():
    ep = _ep(PT)
    row = m.PlanRow("e", "provisioned_throughput", "create_model_service", "c.s.e", None, None, [], None, None, [], [],
                    [m.BLOCKING_PREFIX + "guardrails: re-create as service policies (not 1:1)"])
    with pytest.raises(a.Manual, match="guardrails"):
        a.build_model_service(ep, row, {})
    body = a.build_model_service(ep, row, {}, ack_guardrails=True)
    assert a.guardrail_items(row) == ["guardrails: re-create as service policies (not 1:1)"]
    assert body["config"]["routing"]["destinations"]


# ---------------------------------------------------------------------------
# Secret policy
# ---------------------------------------------------------------------------


def test_secret_policy_rules():
    with pytest.raises(a.PolicyError, match="disabled"):
        a.check_secret_policy(UC_MAP, [], False, False)
    with pytest.raises(a.PolicyError, match="outside the allowed"):
        a.check_secret_policy(UC_MAP, ["c.other"], False, False)
    with pytest.raises(a.PolicyError, match="not enabled"):
        a.check_secret_policy(None, ["c.s"], True, False)
    with pytest.raises(a.PolicyError, match="catalog.schema"):
        a.check_secret_policy(None, ["c.s.extra"], False, False)
    a.check_secret_policy(UC_MAP, ["c.s"], True, True)  # allowed: no error


def test_unknown_uc_secret_fails_before_any_change(tmp_path, monkeypatch):
    w = FakeW(uc_known=())
    eps = [_ep(EXTERNAL)]
    with pytest.raises(a.PolicyError, match="doesn't exist"):
        _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    assert w.ai_gateway.calls == [] and w.grants.updates == []


def test_secret_outside_allowlist_fails_before_any_change(tmp_path, monkeypatch):
    w = FakeW()
    with pytest.raises(a.PolicyError, match="outside the allowed"):
        _run(monkeypatch, tmp_path, w, [_ep(EXTERNAL)], uc_map=UC_MAP, allowed=("c.other",))
    assert w.ai_gateway.calls == []


# ---------------------------------------------------------------------------
# Apply: ownership, reuse, grants, verify, races
# ---------------------------------------------------------------------------


def test_apply_creates_marks_verifies_then_grants(tmp_path, monkeypatch):
    w = FakeW()
    eps = [_ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}])]
    res, log = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    svc = _target(eps)
    assert ("model_service", svc, "created") in [(r["type"], r["name"], r["action"]) for r in res]
    assert f"ug-migration-toolkit apply={APPLY}" in w.ai_gateway.services[svc]["comment"]
    order = [(r["action"], r.get("scope")) for r in res if r.get("name") == svc]
    assert order.index(("ok", "config")) < order.index(("granted", None))
    grant = next(r for r in res if r.get("action") == "granted")
    assert grant["added"] == [{"principal": "data-sci", "privileges": ["EXECUTE"]}]
    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert lines and all(l["apply_id"] == APPLY for l in lines if "apply_id" in l)


def test_unmarked_existing_service_is_manual_and_gets_no_grants(tmp_path, monkeypatch):
    w = FakeW()
    eps = [_ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}])]
    svc = _target(eps)
    w.ai_gateway.services[svc] = {"comment": "made by hand", "config": {}}
    res, _ = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    item = next(r for r in res if r["type"] == "model_service")
    assert item["action"] == "manual" and "wasn't created by this toolkit" in item["reason"]
    assert w.grants.updates == [] and not any(c[0] == "create_model_service" for c in w.ai_gateway.calls)


def test_marked_service_with_other_config_is_manual(tmp_path, monkeypatch):
    w = FakeW()
    eps = [_ep(EXTERNAL)]
    svc = _target(eps)
    w.ai_gateway.services[svc] = {"comment": f"x ug-migration-toolkit apply={OTHER}", "config": {"routing": {"destinations": []}}}
    res, _ = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    item = next(r for r in res if r["type"] == "model_service")
    assert item["action"] == "manual" and "different configuration" in item["reason"]
    assert w.grants.updates == []


def test_create_race_is_treated_as_existing(tmp_path, monkeypatch):
    w = FakeW()
    w.ai_gateway.race = True
    eps = [_ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}])]
    res, _ = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    svc = _target(eps)
    item = [r for r in res if r["type"] == "model_service"][-1]
    assert item["action"] == "exists", res
    assert w.grants.updates, "grants still follow a successful verify"


def test_config_mismatch_after_create_blocks_grants(tmp_path, monkeypatch):
    w = FakeW()
    w.ai_gateway.drop_fallback = True
    eps = [_ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}])]
    res, _ = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    verify = next(r for r in res if r["type"] == "verify" and r.get("scope") == "config")
    assert verify["action"] == "mismatch" and any("fallback" in i for i in verify["issues"])
    assert not any(r["action"] == "granted" for r in res) and w.grants.updates == []


def test_grant_failure_after_create_needs_attention(tmp_path, monkeypatch):
    w = FakeW()
    w.grants.fail = True
    eps = [_ep(EXTERNAL, [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}])]
    res, _ = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP)
    item = next(r for r in res if r.get("action") == "needs_attention")
    assert item["type"] == "model_service" and "grants failed" in item["reason"]


def test_smoke_check_is_recorded_and_sends_no_inference(tmp_path, monkeypatch):
    w = FakeW()
    eps = [_ep(EXTERNAL)]
    res, _ = _run(monkeypatch, tmp_path, w, eps, uc_map=UC_MAP, smoke=True)
    smoke = next(r for r in res if r.get("action") == "smoke_ok")
    assert smoke["state"] is None and "no state field" in smoke["note"]


def test_existing_provider_missing_models_is_updated_with_mask(tmp_path):
    w = FakeW()
    cfg = {"provider_type": "EXTERNAL_MODEL_PROVIDER_TYPE_OPENAI", "allow_all_targets": False,
           "targets": [{"model": "gpt-5", "native_api_types": ["openai/v1/chat/completions"]}],
           "openai": {"direct": {"api_key": {"secret_reference": {"name": "secrets/c.s.openai_key"}}}}}
    w.ai_gateway.providers["c.s.p"] = {"comment": f"x ug-migration-toolkit apply={OTHER}", "config": cfg, "etag": "e0"}
    want = {"provider_type": "EXTERNAL_MODEL_PROVIDER_TYPE_OPENAI", "allow_all_targets": False,
            "targets": [{"model": "gpt-5", "native_api_types": ["openai/v1/chat/completions"]},
                        {"model": "gpt-5-mini", "native_api_types": ["openai/v1/chat/completions"]}],
            "openai": cfg["openai"]}
    applier = a.Applier(w, True, str(tmp_path / "l.jsonl"), APPLY)
    assert applier.ensure_provider("c.s.p", {"comment": "", "config": want}) == "updated"
    call = next(c for c in w.ai_gateway.calls if c[0] == "update_model_provider_service")
    assert call[1] == "c.s.p" and call[2] == ("config.targets",) and call[3] == "e0"
    assert [t["model"] for t in w.ai_gateway.providers["c.s.p"]["config"]["targets"]] == ["gpt-5", "gpt-5-mini"]


def test_unmarked_provider_is_manual(tmp_path):
    w = FakeW()
    w.ai_gateway.providers["c.s.p"] = {"comment": "by hand", "config": {}}
    applier = a.Applier(w, True, str(tmp_path / "l.jsonl"), APPLY)
    with pytest.raises(a.Manual, match="wasn't created by this toolkit"):
        applier.ensure_provider("c.s.p", {"comment": "", "config": {"provider_type": "x"}})


def test_fallback_presence_mismatch_is_an_issue():
    w = FakeW()
    applier = a.Applier(w, False, "unused", APPLY)
    body = {"config": {"routing": {"destinations": [{"name": "p"}], "fallback": {"destinations": [{"name": "b"}]}}}}
    w.ai_gateway.services["c.s.x"] = {"comment": "", "config": {"routing": {"destinations": [{"name": "p"}]}}}
    issues = applier.verify_config("c.s.x", body, fallback_enabled=True)
    assert any("fallback is empty" in i for i in issues)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def _log(tmp_path, rows, name="run.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _created(name, apply_id=APPLY, etag=None, typ="model_service", action="created"):
    e = {"type": typ, "name": name, "action": action, "execute": True, "apply_id": apply_id}
    if etag:
        e["etag"] = etag
    return e


def test_rollback_deletes_only_this_runs_objects(tmp_path):
    w = FakeW()
    w.ai_gateway.services = {
        "c.s.mine": {"comment": f"Created by ug-migration-toolkit apply={APPLY}, x", "etag": "e1"},
        "c.s.other": {"comment": f"Created by ug-migration-toolkit apply={OTHER}, x", "etag": "e2"},
        "c.s.legacy": {"comment": "Created by ug-migration-toolkit, old", "etag": "e3"},
        "c.s.hand": {"comment": "by hand", "etag": "e4"},
    }
    log = _log(tmp_path, [_created("c.s.mine", etag="e1"), _created("c.s.other", etag="e2"),
                          _created("c.s.legacy", etag="e3", apply_id=None), _created("c.s.hand", etag="e4")])
    out = a.rollback(w, str(log), True, apply_id=APPLY)
    actions = {r["name"]: r["action"] for r in out if r.get("type") == "model_service"}
    assert actions == {"c.s.hand": "kept", "c.s.legacy": "deleted", "c.s.other": "kept", "c.s.mine": "deleted"}
    assert "c.s.other" in w.ai_gateway.services and "c.s.mine" not in w.ai_gateway.services
    assert ("delete_model_service", "c.s.mine", "e1") in w.ai_gateway.calls


def test_rollback_keeps_changed_objects_unless_forced(tmp_path):
    def world():
        w = FakeW()
        w.ai_gateway.services["c.s.mine"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "changed"}
        return w
    log = _log(tmp_path, [_created("c.s.mine", etag="e1")])
    out = a.rollback(world(), str(log), True, apply_id=APPLY)
    assert out[0]["action"] == "kept" and "changed since apply" in out[0]["reason"]
    w = world()
    out = a.rollback(w, str(log), True, apply_id=APPLY, force=True)
    assert out[0]["action"] == "deleted" and "c.s.mine" not in w.ai_gateway.services


def test_provider_still_referenced_by_a_service_is_kept(tmp_path):
    w = FakeW()
    w.ai_gateway.providers["c.s.p"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "p1", "config": {}}
    w.ai_gateway.services["c.s.hand"] = {"comment": "by hand", "config": {"routing": {"destinations": [
        {"external_model_config": {"model_provider_service": "model-provider-services/c.s.p"}}]}}}
    log = _log(tmp_path, [_created("c.s.p", etag="p1", typ="model_provider_service")])
    out = a.rollback(w, str(log), True, apply_id=APPLY)
    assert out[0]["action"] == "kept" and "c.s.hand" in out[0]["reason"]
    assert "c.s.p" in w.ai_gateway.providers


def test_reused_provider_is_deleted_only_after_its_owner_is_rolled_back(tmp_path):
    def world():
        w = FakeW()
        w.ai_gateway.providers["c.s.p"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "p1", "config": {}}
        return w
    reuse = _log(tmp_path, [{"type": "model_provider_service", "name": "c.s.p", "action": "exists",
                             "execute": True, "apply_id": OTHER, "owner": APPLY}], "reuse.jsonl")
    kept = a.rollback(world(), str(reuse), True, apply_id=OTHER, released=set())
    assert kept[0]["action"] == "kept"
    w = world()
    out = a.rollback(w, str(reuse), True, apply_id=OTHER, released={APPLY})
    assert any(r["action"] == "deleted" for r in out) and "c.s.p" not in w.ai_gateway.providers


def test_rollback_revokes_only_added_grants_on_surviving_service(tmp_path):
    w = FakeW()
    w.ai_gateway.services["c.s.svc"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "now"}
    w.grants.privs["c.s.svc"] = {"data-sci": {"EXECUTE"}, "ml": {"EXECUTE", "MANAGE"}}
    rows = [{"type": "model_service", "name": "c.s.svc", "action": "exists", "execute": True, "apply_id": OTHER,
             "etag": "old"},
            {"type": "grant", "name": "c.s.svc", "action": "granted", "execute": True, "apply_id": OTHER,
             "added": [{"principal": "data-sci", "privileges": ["EXECUTE"]}]}]
    log = _log(tmp_path, rows, "reuse.jsonl")
    out = a.rollback(w, str(log), True, apply_id=OTHER, released={APPLY})
    assert any(r["action"] == "kept" for r in out)  # changed since apply, so the service survives
    assert any(r["action"] == "revoked" for r in out)
    assert w.grants.privs["c.s.svc"]["data-sci"] == set() and w.grants.privs["c.s.svc"]["ml"] == {"EXECUTE", "MANAGE"}


def test_rollback_audit_is_written_as_it_happens_and_marked_complete(tmp_path):
    w = FakeW()
    w.ai_gateway.services["c.s.mine"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "e1"}
    log = _log(tmp_path, [_created("c.s.mine", etag="e1")])
    a.rollback(w, str(log), True, apply_id=APPLY, audit_path=str(log))
    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert any(l.get("action") == "deleted" and l.get("rollback_of") == APPLY for l in lines)
    assert lines[-1] == {"type": "run", "action": "rollback_complete", "rollback_of": APPLY, "time": lines[-1]["time"]}


def test_protection_from_runs():
    runs = [
        {"apply_id": "A", "rolled_back": False, "entries": [
            {"type": "model_service", "name": "c.s.x", "action": "created", "execute": True}]},
        {"apply_id": "B", "rolled_back": True, "entries": [
            {"type": "model_service", "name": "c.s.y", "action": "created", "execute": True}]},
        {"apply_id": "C", "rolled_back": False, "entries": [
            {"type": "model_service", "name": "c.s.z", "action": "exists", "execute": True}]},
    ]
    protect, released = a.protection_from_runs(runs, "D")
    assert set(protect) == {("model_service", "c.s.x"), ("model_service", "c.s.z")}
    assert released == {"B"}


def test_cli_log_scan_finds_sibling_runs(tmp_path):
    own = _log(tmp_path, [_created("c.s.mine", apply_id=OTHER)], "own.jsonl")
    _log(tmp_path, [_created("c.s.x", apply_id=APPLY)], "a.jsonl")
    _log(tmp_path, [{"type": "run", "action": "rollback_complete", "apply_id": APPLY}], "done.jsonl")
    runs = {r["apply_id"]: r["rolled_back"] for r in a.cli_runs(str(own))}
    assert runs == {OTHER: False, APPLY: True}  # the marker in done.jsonl marks APPLY as rolled back


def test_run_lock_from_sibling_logs(tmp_path):
    now = datetime.now(timezone.utc)
    start = {"type": "run", "action": "run_start", "target": "c.s", "apply_id": APPLY, "time": now.isoformat()}
    _log(tmp_path, [start], "live.jsonl")
    own = tmp_path / "mine.jsonl"
    assert a.running_in_logs(str(own), "c.s", OTHER) == [APPLY]
    assert a.running_in_logs(str(own), "c.other", OTHER) == []
    assert a.running_in_logs(str(own), "c.s", APPLY) == []  # own run never blocks itself
    _log(tmp_path, [start, {"type": "run", "action": "run_end", "apply_id": APPLY, "time": now.isoformat()}], "live.jsonl")
    assert a.running_in_logs(str(own), "c.s", OTHER) == []
    old = {**start, "time": (now - timedelta(hours=13)).isoformat()}
    _log(tmp_path, [old], "live.jsonl")
    assert a.running_in_logs(str(own), "c.s", OTHER) == []


def test_execute_refuses_when_another_run_holds_the_target(tmp_path, monkeypatch):
    w = FakeW()
    _log(tmp_path, [{"type": "run", "action": "run_start", "target": "c.s", "apply_id": OTHER,
                     "time": datetime.now(timezone.utc).isoformat()}], "other.jsonl")
    with pytest.raises(a.PolicyError, match="RUNNING"):
        _run(monkeypatch, tmp_path, w, [_ep(EXTERNAL)], uc_map=UC_MAP)
    assert w.ai_gateway.calls == []
