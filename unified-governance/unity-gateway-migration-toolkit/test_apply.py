"""Offline tests for the apply payload builders, the apply/rollback safety rules, and the fakes they run on."""

import copy
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import databricks.sdk as sdk
import pytest
from databricks.sdk.errors import AlreadyExists, BadRequest, InternalError, NotFound, PermissionDenied

import ug_migration_apply as a
import ug_migration_planner as m
import ug_migration_store as store
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

    def list_model_services(self, parent=None, view=None, page_size=None, page_token=None):
        # Like the API: parent (schemas/catalog.schema) is required, and only that schema is listed.
        assert parent and parent.startswith("schemas/"), "list_model_services needs parent=schemas/<catalog>.<schema>"
        prefix = parent[len("schemas/"):] + "."
        return [Obj({"name": f"model-services/{k}", **v}) for k, v in self.services.items()
                if k.startswith(prefix) and k.count(".") == 2]


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
        self.extra_schemas = set()  # catalog.schema names visible without a service in them
        self.unlistable = set()  # catalogs whose schemas can't be listed
        self.schemas = SimpleNamespace(get=lambda full: None, list=self._list_schemas)
        self.catalogs = SimpleNamespace(list=lambda: [SimpleNamespace(name=c) for c in sorted(
            {n.split(".")[0] for n in self._visible()} | {"system"})])

    def _visible(self) -> set:
        return ({k.rsplit(".", 1)[0] for k in list(self.ai_gateway.services) + list(self.ai_gateway.providers)}
                | self.extra_schemas)

    def _list_schemas(self, catalog_name):
        if catalog_name in self.unlistable:
            raise PermissionDenied(f"no USE CATALOG on {catalog_name}")
        return [SimpleNamespace(name=n.split(".", 1)[1]) for n in sorted(self._visible())
                if n.split(".")[0] == catalog_name] + [SimpleNamespace(name="information_schema")]


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


def _split(ep):
    names = [d["served_entity"] for d in ep.destinations]
    ep.traffic_routes = [{"served_entity_name": n, "traffic_percentage": 100 // len(names)} for n in names]
    return ep


def test_split_traffic_with_fallback_on_is_left_for_a_person():
    ep = _split(_ep(EXTERNAL))
    rows, providers = _plan([ep])
    fqn = {p["provider_key"]: p["provider_service"] for p in providers}
    with pytest.raises(a.Manual, match="can't carry the fallback over"):
        a.build_model_service(ep, rows[0], fqn, ack_guardrails=True)
    ep.fallback_enabled = False  # no fallback to lose: the split is carried over as is
    body = a.build_model_service(ep, rows[0], fqn, ack_guardrails=True)
    assert [d["traffic_percentage"] for d in body["config"]["routing"]["destinations"]] == [50, 50]


def test_not_carried_over_lists_the_governance_the_service_does_not_get(tmp_path, monkeypatch):
    ep = _ep(EXTERNAL)
    ep.tags, ep.usage_tracking, ep.route_optimized, ep.budget_policy_id = [{"key": "team", "value": "a"}], True, True, "bp"
    ep.can_query = [{"principal": "data-sci", "principal_type": "group", "levels": ["CAN_QUERY"]}]
    rows, _ = _plan([ep])
    dropped = a.not_carried_over(ep, rows[0], grants=False)
    joined = "; ".join(dropped)
    for word in ("guardrails", "inference table history", "usage tracking", "endpoint tags (1)", "route optimization",
                 "budget policy", "grants were not copied"):
        assert word in joined, word
    w = FakeW()
    res, _ = _run(monkeypatch, tmp_path, w, [ep], uc_map=UC_MAP, execute=False, grants=False)
    svc = [r for r in res if r["type"] == "model_service"]
    assert svc and svc[0]["not_carried_over"] == dropped
    assert a.run_outcome(res)[1]["not_carried_over"] == 1


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


def test_rollback_never_revokes_grants_on_a_service_it_keeps(tmp_path):
    w = FakeW()
    w.ai_gateway.services["c.s.svc"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "now"}
    w.grants.privs["c.s.svc"] = {"data-sci": {"EXECUTE"}, "ml": {"EXECUTE", "MANAGE"}}
    rows = [{"type": "model_service", "name": "c.s.svc", "action": "exists", "execute": True, "apply_id": OTHER,
             "etag": "old"},
            {"type": "grant", "name": "c.s.svc", "action": "granted", "execute": True, "apply_id": OTHER,
             "added": [{"principal": "data-sci", "privileges": ["EXECUTE"]}]}]
    log = _log(tmp_path, rows, "reuse.jsonl")
    out = a.rollback(w, str(log), True, apply_id=OTHER, released={APPLY})
    assert any(r["action"] == "kept" and r["type"] == "model_service" for r in out)  # changed since apply: survives
    kept = [r for r in out if r["type"] == "grant"]
    assert kept and kept[0]["action"] == "kept" and kept[0]["grants"] == [{"principal": "data-sci", "privileges": ["EXECUTE"]}]
    assert w.grants.updates == []  # callers may depend on the grant now: listed, never revoked
    assert w.grants.privs["c.s.svc"]["data-sci"] == {"EXECUTE"} and w.grants.privs["c.s.svc"]["ml"] == {"EXECUTE", "MANAGE"}


def test_rollback_reports_no_grant_for_a_deleted_service(tmp_path):
    w = FakeW()
    w.ai_gateway.services["c.s.svc"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "e1"}
    rows = [_created("c.s.svc", etag="e1"),
            {"type": "grant", "name": "c.s.svc", "action": "granted", "execute": True, "apply_id": APPLY,
             "added": [{"principal": "data-sci", "privileges": ["EXECUTE"]}]}]
    for execute in (False, True):
        out = a.rollback(w, str(_log(tmp_path, rows, f"g{execute}.jsonl")), execute, apply_id=APPLY)
        assert not [r for r in out if r["type"] == "grant"] and w.grants.updates == []


def test_provider_used_by_a_service_in_another_schema_is_kept(tmp_path):
    w = FakeW()
    w.ai_gateway.providers["c.s.p"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "p1", "config": {}}
    w.ai_gateway.services["other.team.svc"] = {"comment": "by hand", "config": {"routing": {"destinations": [], "fallback": {
        "destinations": [{"external_model_config": {"model_provider_service": "model-provider-services/c.s.p"}}]}}}}
    log = _log(tmp_path, [_created("c.s.p", etag="p1", typ="model_provider_service")])
    out = a.rollback(w, str(log), True, apply_id=APPLY)
    assert out[0]["action"] == "kept" and "other.team.svc" in out[0]["reason"]
    assert "c.s.p" in w.ai_gateway.providers


def test_provider_is_kept_when_a_catalog_cannot_be_checked(tmp_path):
    w = FakeW()
    w.ai_gateway.providers["c.s.p"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "p1", "config": {}}
    w.extra_schemas.add("locked.x")
    w.unlistable.add("locked")
    log = _log(tmp_path, [_created("c.s.p", etag="p1", typ="model_provider_service")])
    out = a.rollback(w, str(log), True, apply_id=APPLY)
    assert out[0]["action"] == "kept" and "couldn't check" in out[0]["reason"]
    assert "c.s.p" in w.ai_gateway.providers


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


# ---------------------------------------------------------------------------
# Job side, from the app's point of view: secrets, killed runs, outcome, guardrails, rollback markers
# ---------------------------------------------------------------------------


def test_secret_schema_check_ignores_case():
    a.check_secret_policy({"s/k": "secrets/CAT.Sec.name"}, ["cat.sec"], False, False)
    a.check_secret_policy({"s/k": "secrets/cat.sec.name"}, ["CAT.SEC"], False, False)
    with pytest.raises(a.PolicyError, match="outside"):
        a.check_secret_policy({"s/k": "secrets/cat.other.name"}, ["CAT.SEC"], False, False)


def test_killed_execute_does_not_block_its_target(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    _log(tmp_path, [{"type": "run", "action": "run_start", "target": "c.s", "apply_id": OTHER, "time": now}],
         "killed.jsonl")
    own = tmp_path / "mine.jsonl"
    assert a.running_in_logs(str(own), "c.s", APPLY) == [OTHER]  # no checker: a young log blocks
    assert a.running_in_logs(str(own), "c.s", APPLY, is_active=lambda _: False) == []
    assert a.running_in_logs(str(own), "c.s", APPLY, is_active=lambda aid: aid == OTHER) == [OTHER]
    w = FakeW()
    res, _ = _run(monkeypatch, tmp_path, w, [_ep(EXTERNAL)], uc_map=UC_MAP, is_active=lambda _: False)
    assert a.run_outcome(res)[0] == "SUCCEEDED" and w.ai_gateway.calls  # the new run goes ahead


def test_run_outcome_status_and_summary():
    assert a.run_outcome([{"action": "created"}, {"action": "would_create"}]) == \
        ("SUCCEEDED", {"created": 1, "would_create": 1, "kept_other_run": 0, "not_carried_over": 0})
    status, summary = a.run_outcome([{"action": "created"}, {"action": "manual"}])
    assert status == "NEEDS_ATTENTION" and summary["manual"] == 1
    assert a.run_outcome([{"action": "kept", "other_run": True}])[1]["kept_other_run"] == 1


def test_guardrails_flow_with_real_planner_output(monkeypatch, tmp_path):
    # Not acknowledged: the endpoint is blocked, so the dry run needs attention.
    res, _ = _run(monkeypatch, tmp_path, FakeW(), [_ep(EXTERNAL)], uc_map=UC_MAP, execute=False, ack_guardrails=False)
    assert [r["action"] for r in res if r["type"] == "model_service"] == ["manual"]
    assert a.run_outcome(res)[0] == "NEEDS_ATTENTION"
    # Acknowledged: the dry run plans the service and records what isn't migrated; the run still SUCCEEDED.
    res, _ = _run(monkeypatch, tmp_path, FakeW(), [_ep(EXTERNAL)], uc_map=UC_MAP, execute=False, ack_guardrails=True)
    svc = [r for r in res if r["type"] == "model_service"]
    assert [r["action"] for r in svc] == ["would_create"]
    assert svc[0]["guardrails_not_migrated"] and "guardrails not carried over" in svc[0]["guardrails_not_migrated"][0]
    assert a.run_outcome(res)[0] == "SUCCEEDED"
    # The execute with the same acknowledgement creates the service, and it reads back as planned.
    w = FakeW()
    res, _ = _run(monkeypatch, tmp_path, w, [_ep(EXTERNAL)], uc_map=UC_MAP, ack_guardrails=True)
    assert any(r["action"] == "created" and r.get("guardrails_not_migrated") for r in res)
    assert a.run_outcome(res)[0] == "SUCCEEDED"


def test_kept_objects_say_whether_another_run_uses_them(tmp_path):
    w = FakeW()
    w.ai_gateway.services["c.s.shared"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "s1"}
    w.ai_gateway.services["c.s.changed"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "now"}
    log = _log(tmp_path, [_created("c.s.shared", etag="s1"), _created("c.s.changed", etag="s1")])
    protect = {("model_service", "c.s.shared"): f"used by apply {OTHER}, which hasn't been rolled back"}
    out = a.rollback(w, str(log), True, apply_id=APPLY, protect=protect)
    by = {r["name"]: r for r in out}
    assert by["c.s.shared"]["action"] == "kept" and by["c.s.shared"]["other_run"] is True
    assert by["c.s.changed"]["action"] == "kept" and not by["c.s.changed"].get("other_run")
    assert "roll back from the command line with --force" in by["c.s.changed"]["reason"]
    assert "rerun" not in by["c.s.changed"]["reason"]
    status, summary = a.run_outcome(out)
    assert status == "NEEDS_ATTENTION" and summary["kept_other_run"] == 1
    assert store.rollback_done(status, summary) is False  # the changed object is still there

    w2 = FakeW()
    w2.ai_gateway.services["c.s.shared"] = {"comment": f"ug-migration-toolkit apply={APPLY}", "etag": "s1"}
    log2 = _log(tmp_path, [_created("c.s.shared", etag="s1")], "only_shared.jsonl")
    out2 = a.rollback(w2, str(log2), True, apply_id=APPLY, protect=protect)
    status2, summary2 = a.run_outcome(out2)
    assert status2 == "NEEDS_ATTENTION" and store.rollback_done(status2, summary2) is True  # only shared objects kept


# ---------------------------------------------------------------------------
# Verify and cut over: test calls, legacy rate-limit pause and resume, usage tracking (fakes only)
# ---------------------------------------------------------------------------

GW_RATE = [{"key": "user", "renewal_period": "minute", "calls": 50},
           {"key": "endpoint", "renewal_period": "minute", "calls": 100}]
GW_FULL = {"rate_limits": GW_RATE, "guardrails": {"input": {"pii": {"behavior": "BLOCK"}}},
           "inference_table_config": {"catalog_name": "c", "schema_name": "s", "table_name_prefix": "p"},
           "fallback_config": {"enabled": True}}
CUSTOM = [{"name": "m", "entity_name": "c.s.model", "entity_version": "1"}]
API_CHAT = "mlflow/v1/chat/completions"
SVC = "c.s.llama"


def _endpoint(name, gateway=None, served=None, task="llm/v1/chat", tags=None):
    if served is None:
        served = [{"name": "primary", "external_model": {"name": "gpt-5", "provider": "openai", "task": task}}]
    return {"name": name, "id": "id-" + name, "task": task, "tags": tags or [],
            "config": {"served_entities": served}, "ai_gateway": copy.deepcopy(gateway or {})}


class CutoverApi:
    """Stands in for w.api_client for the serving-endpoints GET, list and ai-gateway PUT.

    Like the real API, PUT /ai-gateway replaces the whole AI Gateway config with the body."""

    def __init__(self, endpoints, refuse=()):
        self.endpoints = {e["name"]: e for e in endpoints}
        self.refuse = set(refuse)
        self.puts = []

    def do(self, method, path, body=None, query=None):
        if method == "GET" and path == "/api/2.0/serving-endpoints":
            return {"endpoints": [{"name": n} for n in self.endpoints]}
        name = path.split("/")[4]
        if name not in self.endpoints:
            raise NotFound(name)
        if method == "GET":
            return copy.deepcopy(self.endpoints[name])
        if method == "PUT":
            if name in self.refuse:
                raise PermissionDenied(f"{name} is a Databricks system endpoint")
            if not body:
                raise BadRequest("AI Gateway configuration must be provided.")
            self.puts.append((name, copy.deepcopy(body)))
            self.endpoints[name]["ai_gateway"] = copy.deepcopy(body)
            return {}
        raise AssertionError(method)


class CutoverW:
    def __init__(self, endpoints, refuse=(), services=None):
        self.api_client = CutoverApi(endpoints, refuse)
        self.config = SimpleNamespace(host="https://ws.example.com/",
                                      authenticate=lambda: {"Authorization": "Bearer tok-SECRET"})
        self.services = services or {}
        self.ai_gateway = SimpleNamespace(get_model_service=self._get_service)

    def _get_service(self, name):
        key = name.split("/", 1)[1]
        if key not in self.services:
            raise NotFound(key)
        return SimpleNamespace(supported_api_types=self.services[key])


def _roundtrip(results):
    """The result rows as the store returns them (JSON)."""
    return [json.loads(json.dumps(r, default=str)) for r in results]


def _pause(w, names, tmp_path, execute=True, apply_id=APPLY, recent=None, force=False):
    log = tmp_path / "pause.jsonl"
    recent = {} if recent is None else recent  # traffic checked: no recent requests
    return a.pause_legacy(w, names, execute, str(log), apply_id, recent_requests=recent, force=force), log


@pytest.mark.parametrize("ep, reason", [
    (_endpoint("custom", GW_FULL, served=CUSTOM), "custom_model"),
    (_endpoint("emb", GW_FULL, task="llm/v1/embeddings"), "embedding"),
    (_endpoint("search", GW_FULL, tags=[{"key": "vector_search", "value": "true"}]), "AI Search"),
])
def test_pause_refuses_custom_embedding_and_search_endpoints(tmp_path, ep, reason):
    w = CutoverW([ep])
    res, _ = _pause(w, [ep["name"]], tmp_path)
    assert res[0]["action"] == "refused" and reason in res[0]["reason"]
    assert w.api_client.puts == []


def test_pause_dry_run_writes_nothing(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    res, log = _pause(w, ["ext"], tmp_path, execute=False)
    assert res[0]["action"] == "would_pause" and w.api_client.puts == [] and not log.exists()
    rates = res[0]["paused_ai_gateway"]["rate_limits"]
    assert {"key": "user", "renewal_period": "minute", "calls": 50} in rates
    assert rates[-1] == {"key": "endpoint", "calls": 0, "renewal_period": "minute"}
    assert res[0]["previous_ai_gateway"] == GW_FULL


def test_pause_execute_resends_every_setting_and_reads_back(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    res, log = _pause(w, ["ext"], tmp_path)
    ((name, body),) = w.api_client.puts
    assert name == "ext" and body["guardrails"] == GW_FULL["guardrails"]
    assert body["inference_table_config"] == GW_FULL["inference_table_config"]
    assert body["fallback_config"] == {"enabled": True}
    assert res[0]["action"] == "paused"
    assert a._zero_endpoint_limit(w.api_client.endpoints["ext"]["ai_gateway"])
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert [x["action"] for x in lines] == ["pausing", "paused"]  # pausing is durable before the write
    assert lines[0]["previous_ai_gateway"] == GW_FULL and len(res) == 1


def test_pause_refuses_an_endpoint_with_recent_traffic_unless_forced(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    res, _ = _pause(w, ["ext"], tmp_path, recent={"ext": 12})
    assert res[0]["action"] == "refused" and "12 legacy request" in res[0]["reason"] and res[0]["recent_requests"] == 12
    assert w.api_client.puts == []
    forced, _ = _pause(w, ["ext"], tmp_path, recent={"ext": 12}, force=True)
    assert forced[0]["action"] == "paused"


def test_pause_fails_closed_when_traffic_could_not_be_checked(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    res = a.pause_legacy(w, ["ext"], True, str(tmp_path / "p.jsonl"), APPLY, recent_requests=None)
    assert res[0]["action"] == "refused" and "couldn't check" in res[0]["reason"] and w.api_client.puts == []


def test_a_pause_whose_read_back_failed_can_still_be_resumed(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    real_get = w.api_client.do
    state = {"reads": 0}

    def flaky(method, path, body=None, **kw):
        if method == "GET" and path.endswith("/serving-endpoints/ext"):
            state["reads"] += 1
            if state["reads"] == 2:  # the read-back after the PUT
                raise InternalError("timeout")
        return real_get(method, path, body=body, **kw)

    w.api_client.do = flaky
    res, log = _pause(w, ["ext"], tmp_path)
    assert res[0]["action"] == "mismatch" and res[0]["write_attempted"] and "resume" in res[0]["reason"]
    resumed = a.resume_legacy(w, _roundtrip(res), None, True, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    assert resumed[0]["action"] == "resumed" and w.api_client.endpoints["ext"]["ai_gateway"] == GW_FULL


def test_a_pause_killed_mid_write_is_resumed_from_its_durable_log(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    _pause(w, ["ext"], tmp_path)
    durable = [json.loads(x) for x in (tmp_path / "pause.jsonl").read_text().splitlines()][:1]  # killed after the PUT
    assert durable[0]["action"] == "pausing"
    resumed = a.resume_legacy(w, durable, None, True, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    assert resumed[0]["action"] == "resumed" and w.api_client.endpoints["ext"]["ai_gateway"] == GW_FULL


def test_pause_skips_an_endpoint_already_at_zero(tmp_path):
    gw = {"rate_limits": [{"key": "endpoint", "calls": 0, "renewal_period": "minute"}]}
    w = CutoverW([_endpoint("ext", gw)])
    res, _ = _pause(w, ["ext"], tmp_path)
    assert res[0]["action"] == "already_paused" and w.api_client.puts == []


def test_pause_reports_an_api_refusal_on_a_system_endpoint(tmp_path):
    w = CutoverW([_endpoint("databricks-meta-llama", GW_FULL, served=[])], refuse=["databricks-meta-llama"])
    res, _ = _pause(w, ["databricks-meta-llama"], tmp_path)
    assert res[0]["action"] == "refused" and "refused" in res[0]["reason"]
    assert res[0]["kind"] == "system_ppt"


def test_pause_refuses_settings_the_tool_does_not_resend_and_missing_endpoints(tmp_path):
    w = CutoverW([_endpoint("ext", {**GW_FULL, "new_setting": {"x": 1}})])
    res, _ = _pause(w, ["ext", "ghost"], tmp_path)
    assert res[0]["action"] == "refused" and "new_setting" in res[0]["reason"]
    assert res[1]["action"] == "refused" and res[1]["reason"] == "endpoint not found"
    assert w.api_client.puts == []


def test_pause_then_resume_restores_the_exact_previous_config(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    paused = _roundtrip(_pause(w, ["ext"], tmp_path, apply_id=APPLY)[0])
    resumed = a.resume_legacy(w, paused, None, True, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    assert resumed[0]["action"] == "resumed"
    assert w.api_client.endpoints["ext"]["ai_gateway"] == GW_FULL
    assert resumed[0]["pause_apply_id"] == APPLY


def test_resume_of_an_endpoint_that_had_no_gateway_settings(tmp_path):
    # The API refuses an empty body, so resume sends usage tracking off, which reads the same as no settings.
    w = CutoverW([_endpoint("bare", None)])
    paused = _roundtrip(_pause(w, ["bare"], tmp_path, apply_id=APPLY)[0])
    assert paused[0]["action"] == "paused"
    resumed = a.resume_legacy(w, paused, None, True, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    assert resumed[0]["action"] == "resumed"
    assert w.api_client.endpoints["bare"]["ai_gateway"] == a.NO_GATEWAY_SETTINGS
    assert not a._zero_endpoint_limit(w.api_client.endpoints["bare"]["ai_gateway"])


def test_resume_keeps_an_endpoint_changed_after_the_pause_unless_forced(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    paused = _roundtrip(_pause(w, ["ext"], tmp_path)[0])
    w.api_client.endpoints["ext"]["ai_gateway"]["guardrails"] = {"input": {"pii": {"behavior": "MASK"}}}
    kept = a.resume_legacy(w, paused, None, True, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    assert kept[0]["action"] == "kept" and "force" in kept[0]["reason"]
    assert len(w.api_client.puts) == 1  # only the pause wrote
    forced = a.resume_legacy(w, paused, None, True, str(tmp_path / "r2.jsonl"), OTHER, APPLY, force=True)
    assert forced[0]["action"] == "resumed"
    assert w.api_client.endpoints["ext"]["ai_gateway"] == GW_FULL


def test_resume_twice_and_resume_of_a_deleted_endpoint(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    paused = _roundtrip(_pause(w, ["ext"], tmp_path)[0])
    a.resume_legacy(w, paused, None, True, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    again = a.resume_legacy(w, paused, None, True, str(tmp_path / "r2.jsonl"), OTHER, APPLY)
    assert again[0]["action"] == "already_resumed"
    del w.api_client.endpoints["ext"]
    gone = a.resume_legacy(w, paused, None, True, str(tmp_path / "r3.jsonl"), OTHER, APPLY)
    assert gone[0]["action"] == "already_gone"


def test_resume_only_touches_endpoints_this_run_paused(tmp_path):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    paused = _roundtrip(_pause(w, ["ext"], tmp_path)[0])
    res = a.resume_legacy(w, paused, ["other"], False, str(tmp_path / "r.jsonl"), OTHER, APPLY)
    assert res[0]["action"] == "skipped" and not (tmp_path / "r.jsonl").exists()


def test_resume_source_must_be_an_executed_pause_run():
    assert a.resume_source_error({"operation": "pause_legacy", "mode": "execute"}) is None
    assert "pause" in a.resume_source_error({"operation": "apply", "mode": "execute"})
    assert "pause" in a.resume_source_error({"operation": "pause_legacy", "mode": "dry_run"})
    assert "exist" in a.resume_source_error(None)


def test_enable_tracking_default_set_skips_custom_system_and_enabled(tmp_path):
    w = CutoverW([
        _endpoint("ext", GW_FULL),
        _endpoint("custom", GW_FULL, served=CUSTOM),
        _endpoint("databricks-llama", GW_FULL, served=[]),
        _endpoint("tracked", {**GW_FULL, "usage_tracking_config": {"enabled": True}}),
    ])
    res = a.enable_tracking(w, [], True, str(tmp_path / "t.jsonl"), APPLY)
    assert {r["name"]: r["action"] for r in res} == {
        "ext": "tracking_enabled", "custom": "skipped", "databricks-llama": "skipped", "tracked": "already_enabled"}
    assert [n for n, _ in w.api_client.puts] == ["ext"]
    body = w.api_client.puts[0][1]
    assert body["usage_tracking_config"] == {"enabled": True}
    assert body["rate_limits"] == GW_RATE and body["guardrails"] == GW_FULL["guardrails"]


def test_enable_tracking_refuses_an_explicit_custom_endpoint_and_dry_run_writes_nothing(tmp_path):
    w = CutoverW([_endpoint("custom", GW_FULL, served=CUSTOM), _endpoint("ext", GW_FULL)])
    res = a.enable_tracking(w, ["custom"], True, str(tmp_path / "t.jsonl"), APPLY)
    assert res[0]["action"] == "refused" and w.api_client.puts == []
    dry = a.enable_tracking(w, ["ext"], False, str(tmp_path / "t2.jsonl"), APPLY)
    assert dry[0]["action"] == "would_enable_tracking" and w.api_client.puts == []
    assert not (tmp_path / "t2.jsonl").exists()


def test_enable_tracking_reports_api_refusal(tmp_path):
    w = CutoverW([_endpoint("databricks-llama", GW_FULL, served=[])], refuse=["databricks-llama"])
    res = a.enable_tracking(w, ["databricks-llama"], True, str(tmp_path / "t.jsonl"), APPLY)
    assert res[0]["action"] == "refused"


class FakeResp:
    def __init__(self, status_code=200, body=None, headers=None, text=None):
        self.status_code = status_code
        self._body = body
        self.headers = {"x-request-id": "req-123"} if headers is None else headers
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _post(responses):
    calls = []
    queue = list(responses) if isinstance(responses, list) else None

    def post(url, **kw):
        calls.append({"url": url, **kw})
        r = queue.pop(0) if queue is not None else responses
        if isinstance(r, Exception):
            raise r
        return r
    post.calls = calls
    return post


CHAT_OK = {"choices": [{"message": {"content": "ok"}}]}


def test_test_call_dry_run_validates_and_sends_nothing(tmp_path):
    w = CutoverW([], services={SVC: [API_CHAT]})
    post = _post(FakeResp(body=CHAT_OK))
    res = a.run_test_calls(w, [SVC], API_CHAT, "Reply with: ok", False, str(tmp_path / "x.jsonl"), APPLY, post=post)
    assert res[0]["action"] == "would_test" and post.calls == [] and not (tmp_path / "x.jsonl").exists()


def test_test_call_execute_records_status_request_id_latency_and_excerpt(tmp_path):
    w = CutoverW([], services={SVC: [API_CHAT]})
    post = _post(FakeResp(body={"choices": [{"message": {"content": "x" * 500}}]},
                          headers={"x-databricks-request-id": "req-9"}))
    res = a.run_test_calls(w, [SVC], API_CHAT, "Reply with: ok", True, str(tmp_path / "x.jsonl"), APPLY, post=post)
    r = res[0]
    assert r["action"] == "test_ok" and r["http_status"] == 200 and r["request_id"] == "req-9"
    assert len(r["reply_excerpt"]) == 200 and isinstance(r["latency_ms"], int)
    call = post.calls[0]
    assert call["url"] == "https://ws.example.com/ai-gateway/mlflow/v1/chat/completions"
    assert call["json"] == {"model": SVC, "messages": [{"role": "user", "content": "Reply with: ok"}]}
    assert call["headers"]["Authorization"] == "Bearer tok-SECRET"
    assert "tok-SECRET" not in json.dumps(res) and "tok-SECRET" not in (tmp_path / "x.jsonl").read_text()


def test_test_call_reply_shapes_for_responses_and_embeddings(tmp_path):
    w = CutoverW([], services={SVC: ["openai/v1/responses", "mlflow/v1/embeddings"]})
    post = _post([FakeResp(body={"output": [{"content": [{"type": "output_text", "text": "hi there"}]}]}),
                  FakeResp(body={"data": [{"embedding": [0.1, 0.2, 0.3]}]})])
    log = str(tmp_path / "x.jsonl")
    r1 = a.run_test_calls(w, [SVC], "openai/v1/responses", "Reply with: ok", True, log, APPLY, post=post)
    r2 = a.run_test_calls(w, [SVC], "mlflow/v1/embeddings", "Reply with: ok", True, log, APPLY, post=post)
    assert r1[0]["reply_excerpt"] == "hi there" and post.calls[0]["json"] == {"model": SVC, "input": "Reply with: ok"}
    assert r2[0]["reply_excerpt"] == "embedding with 3 dimensions"


def test_test_call_failures_and_refusals_are_reported_and_need_attention(tmp_path):
    w = CutoverW([], services={SVC: [API_CHAT]})
    log = str(tmp_path / "x.jsonl")
    missing = a.run_test_calls(w, ["c.s.missing"], API_CHAT, "p", True, log, APPLY, post=_post(FakeResp(body=CHAT_OK)))
    assert missing[0]["action"] == "test_failed" and "not found" in missing[0]["reason"]
    unsupported = a.run_test_calls(w, [SVC], "openai/v1/responses", "p", True, log, APPLY,
                                   post=_post(FakeResp(body=CHAT_OK)))
    assert unsupported[0]["action"] == "refused" and "does not support" in unsupported[0]["reason"]
    http = _post(FakeResp(status_code=500, body={"message": "boom"}, text="boom"))
    failed = a.run_test_calls(w, [SVC], API_CHAT, "p", True, log, APPLY, post=http)
    assert failed[0]["action"] == "test_failed" and failed[0]["http_status"] == 500
    down = a.run_test_calls(w, [SVC], API_CHAT, "p", True, log, APPLY, post=_post(ConnectionError("down")))
    assert down[0]["action"] == "test_failed" and "no response" in down[0]["reason"]
    assert a.run_outcome(missing)[0] == "NEEDS_ATTENTION" and a.run_outcome(failed)[0] == "NEEDS_ATTENTION"


def test_test_call_without_a_request_id_says_how_to_find_it(tmp_path):
    w = CutoverW([], services={SVC: [API_CHAT]})
    res = a.run_test_calls(w, [SVC], API_CHAT, "p", True, str(tmp_path / "x.jsonl"), APPLY,
                           post=_post(FakeResp(body=CHAT_OK, headers={})))
    assert res[0]["action"] == "test_ok" and res[0]["request_id"] is None and "note" in res[0]


def test_cutover_option_validation():
    assert a.resolve_api_type("") == "mlflow/v1/chat/completions"
    assert a.resolve_api_type("openai/v1/responses") == "openai/v1/responses"
    with pytest.raises(ValueError):
        a.resolve_api_type("openai/v1/chat")
    assert a.resolve_prompt("") == "Reply with: ok" and a.resolve_prompt("  hi ") == "hi"
    assert len(a.resolve_prompt("x" * 200)) == 200
    with pytest.raises(ValueError, match="200"):
        a.resolve_prompt("x" * 201)
    with pytest.raises(ValueError):
        a.resolve_prompt("line\nbreak")
    assert a.parse_services("c.s.a, c.s.a ,c.s.b") == ["c.s.a", "c.s.b"]
    for bad in ("", "c.s", "c.s.a.b", "c.s.a'; --"):
        with pytest.raises(ValueError):
            a.parse_services(bad)
    with pytest.raises(ValueError):
        a.parse_services(",".join(f"c.s.m{i}" for i in range(a.MAX_TEST_SERVICES + 1)))
    assert a.parse_endpoints("") == [] and a.parse_endpoints("a, b,a") == ["a", "b"]
    with pytest.raises(ValueError):
        a.parse_endpoints("bad name")


def test_api_refusals_are_told_apart_from_server_errors():
    assert a._api_refusal(PermissionDenied("no")) is True
    assert a._api_refusal(InternalError("oops")) is False
    assert a._api_refusal(RuntimeError("x")) is False


def test_outcome_counts_refusals_and_test_failures_but_not_no_op_actions():
    assert a.run_outcome([{"action": "test_ok"}])[0] == "SUCCEEDED"
    assert a.run_outcome([{"action": "refused"}])[0] == "NEEDS_ATTENTION"
    assert a.run_outcome([{"action": "already_enabled"}, {"action": "already_paused"}, {"action": "skipped"}])[0] \
        == "SUCCEEDED"


# ---------------------------------------------------------------------------
# The job notebook's dispatch for the cut-over operations. The notebook is exec'd with a fake dbutils, a fake
# WorkspaceClient (CutoverW) and the store's Delta calls patched out. Nothing is written anywhere.
# ---------------------------------------------------------------------------

NB_PATH = Path(__file__).parent / "notebook" / "run_apply.py"


class DryRunSpark:
    """spark for the job notebook: answers only the dry-run lookup, from rows keyed by apply_id."""

    def __init__(self, rows):
        self.rows, self.queries = rows or {}, []

    def sql(self, text, args=None):
        self.queries.append(text)
        m = re.search(r"WHERE apply_id = '([0-9a-f-]+)'", text)
        row = self.rows.get(m.group(1)) if m else None
        return SimpleNamespace(collect=lambda: [SimpleNamespace(asDict=lambda: dict(row))] if row else [])


def _dry_row(calls, apply_id, **override):
    """The dry run's row as the job wrote it (its first upsert), the way the execute reads it back."""
    first = next(r for r in calls["upserts"] if r.get("apply_id") == apply_id and r.get("status") == "RUNNING")
    row = {k: first.get(k) for k in ("mode", "operation", "fingerprint", "scan_run_id", "requested_by", "started_at")}
    row["status"] = _final(calls, apply_id)["status"]
    row.update(override)
    return row


def _notebook(monkeypatch, params, fake_w, apply_rows=None, legacy_entries=None, dry_rows=None, traffic=None):
    import ug_migration_store as st

    calls = {"upserts": [], "items": {}, "exits": []}
    widgets = dict(params)
    dbutils = SimpleNamespace(
        widgets=SimpleNamespace(text=lambda name, default: widgets.setdefault(name, default),
                                get=lambda name: widgets[name]),
        notebook=SimpleNamespace(
            entry_point=SimpleNamespace(getDbutils=lambda: SimpleNamespace(notebook=lambda: SimpleNamespace(
                getContext=lambda: SimpleNamespace(notebookPath=lambda: SimpleNamespace(
                    get=lambda: "/Workspace/Users/tester/ug/notebook/run_apply"))))),
            exit=lambda text: calls["exits"].append(text)))
    monkeypatch.setattr(st, "ensure_tables", lambda spark, schema: None)
    monkeypatch.setattr(st, "run_exists", lambda *a, **k: False)
    monkeypatch.setattr(st, "upsert", lambda spark, schema, table, cols, key, values: calls["upserts"].append(dict(values)))
    monkeypatch.setattr(st, "write_apply_items", lambda spark, schema, apply_id, results: calls["items"].__setitem__(apply_id, list(results)))
    monkeypatch.setattr(st, "apply_run", lambda spark, schema, apply_id: (apply_rows or {}).get(apply_id))
    monkeypatch.setattr(st, "effective_status", lambda w, status, job_run_id: status)
    monkeypatch.setattr(st, "already_rolled_back", lambda *a, **k: False)
    monkeypatch.setattr(st, "running_legacy", lambda *a, **k: [])
    monkeypatch.setattr(st, "legacy_run_entries",
                        lambda spark, schema, apply_id, durable=None: list((legacy_entries or {}).get(apply_id, [])))
    monkeypatch.setattr(st, "run_built", lambda spark, built: [
        {"endpoint_name": n, "requests": c} for n, c in (traffic or {}).items()])
    if not hasattr(fake_w, "get_workspace_id"):
        fake_w.get_workspace_id = lambda: 1234
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)  # the job's log folder doesn't exist here
    monkeypatch.setattr(sdk, "WorkspaceClient", lambda *a, **k: fake_w)
    code = compile(NB_PATH.read_text(), str(NB_PATH), "exec")
    exec(code, {"dbutils": dbutils, "spark": DryRunSpark(dry_rows), "__name__": "run_apply_test"})
    return calls


def _final(calls, apply_id):
    rows = [r for r in calls["upserts"] if r.get("apply_id") == apply_id and "status" in r]
    return rows[-1]


def test_notebook_test_call_dry_run_validates_and_writes_no_request(monkeypatch):
    w = CutoverW([], services={SVC: [API_CHAT]})
    calls = _notebook(monkeypatch, {"apply_id": APPLY, "results_schema": "c.s", "operation": "test_call",
                                    "mode": "dry_run", "services": SVC, "job_run_id": "5"}, w)
    assert calls["items"][APPLY][0]["action"] == "would_test"
    assert _final(calls, APPLY)["status"] == "SUCCEEDED"
    assert calls["upserts"][0]["operation"] == "test_call" and calls["upserts"][0]["services"] == SVC
    assert calls["upserts"][0]["fingerprint"] == store.legacy_fingerprint(
        {"operation": "test_call", "services": SVC, "api_type": "", "prompt": "Reply with: ok", "rollback_of": "",
         "force": "false"})


def test_notebook_refuses_a_test_call_without_services_before_writing_anything(monkeypatch):
    with pytest.raises(ValueError, match="services"):
        _notebook(monkeypatch, {"apply_id": APPLY, "results_schema": "c.s", "operation": "test_call",
                                "mode": "dry_run", "services": ""}, CutoverW([]))


DRY = "dddddddd-0000-0000-0000-000000000001"


def test_notebook_pause_then_rollback_of_the_pause_resumes_it(monkeypatch):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    base = {"results_schema": "c.s", "operation": "pause_legacy", "endpoints": "ext", "requested_by": "me@x.com"}
    dry = _notebook(monkeypatch, {**base, "apply_id": DRY, "mode": "dry_run", "job_run_id": "6"}, w)
    assert dry["items"][DRY][0]["action"] == "would_pause"
    paused = _notebook(monkeypatch, {**base, "apply_id": APPLY, "mode": "execute", "job_run_id": "7",
                                     "dry_run_id": DRY}, w, dry_rows={DRY: _dry_row(dry, DRY)})
    assert paused["items"][APPLY][0]["action"] == "paused"
    assert _final(paused, APPLY)["status"] == "SUCCEEDED"
    assert w.api_client.endpoints["ext"]["ai_gateway"] != GW_FULL  # paused
    pause_row = {"mode": "execute", "operation": "pause_legacy", "status": "SUCCEEDED", "job_run_id": "7"}

    resumed = _notebook(monkeypatch, {"apply_id": OTHER, "results_schema": "c.s", "mode": "rollback",
                                      "rollback_of": APPLY, "job_run_id": "8"}, w,
                        apply_rows={APPLY: pause_row},
                        legacy_entries={APPLY: _roundtrip(paused["items"][APPLY])})
    assert resumed["items"][OTHER][0]["action"] == "resumed"
    assert w.api_client.endpoints["ext"]["ai_gateway"] == GW_FULL
    first = resumed["upserts"][0]
    assert first["mode"] == "rollback" and first["operation"] == "resume_legacy" and first["rollback_of"] == APPLY
    assert _final(resumed, OTHER)["status"] == "SUCCEEDED"


def test_notebook_resume_needs_a_pause_run(monkeypatch):
    apply_run = {"mode": "execute", "operation": "apply", "status": "SUCCEEDED", "job_run_id": "1"}
    with pytest.raises(ValueError, match="pause run"):
        _notebook(monkeypatch, {"apply_id": OTHER, "results_schema": "c.s", "operation": "resume_legacy",
                                "mode": "execute", "rollback_of": APPLY}, CutoverW([]), apply_rows={APPLY: apply_run})


def test_notebook_rollback_of_a_tracking_run_is_refused(monkeypatch):
    tracking_run = {"mode": "execute", "operation": "enable_tracking", "status": "SUCCEEDED", "job_run_id": "1"}
    with pytest.raises(ValueError, match="enable_tracking"):
        _notebook(monkeypatch, {"apply_id": OTHER, "results_schema": "c.s", "mode": "rollback",
                                "rollback_of": APPLY}, CutoverW([]), apply_rows={APPLY: tracking_run})


def test_notebook_pause_needs_endpoints(monkeypatch):
    with pytest.raises(ValueError, match="at least one endpoint"):
        _notebook(monkeypatch, {"apply_id": APPLY, "results_schema": "c.s", "operation": "pause_legacy",
                                "mode": "dry_run", "endpoints": ""}, CutoverW([]))


def test_unity_gateway_off_stops_the_apply_before_any_write(tmp_path, monkeypatch):
    from databricks.sdk import errors as sdk_errors

    w = FakeW()

    def off(parent=None, page_size=None, page_token=None):
        raise sdk_errors.PermissionDenied("Unity Gateway is not enabled for this workspace")

    w.ai_gateway.list_model_services = off
    with pytest.raises(a.PolicyError) as refused:
        _run(monkeypatch, tmp_path, w, [_ep(EXTERNAL)])
    assert str(refused.value) == ("Unity Gateway isn't available in this workspace. Ask your account team to enable "
                                  "Unity Gateway for this workspace and account. Nothing can be migrated until it is.")
    assert w.ai_gateway.calls == [] and w.grants.updates == []
    assert not (tmp_path / "apply.jsonl").exists()  # nothing was logged either


def test_other_listing_errors_do_not_stop_the_apply(tmp_path, monkeypatch):
    w = FakeW()

    def flaky(parent=None, page_size=None, page_token=None):
        raise RuntimeError("connection reset")

    w.ai_gateway.list_model_services = flaky
    res, _ = _run(monkeypatch, tmp_path, w, [_ep(EXTERNAL)])
    assert res and not any("isn't available" in str(r) for r in res)  # the run went on past the listing


def _gate_case(monkeypatch, w, dry_override=None, execute_params=None, traffic=None):
    base = {"results_schema": "c.s", "operation": "enable_tracking", "endpoints": "ext", "requested_by": "me@x.com"}
    dry = _notebook(monkeypatch, {**base, "apply_id": DRY, "mode": "dry_run", "job_run_id": "6"}, w, traffic=traffic)
    params = {**base, "apply_id": APPLY, "mode": "execute", "job_run_id": "7", "dry_run_id": DRY, **(execute_params or {})}
    return _notebook(monkeypatch, params, w, dry_rows={DRY: _dry_row(dry, DRY, **(dry_override or {}))}, traffic=traffic)


def test_notebook_execute_without_a_dry_run_is_refused_before_any_write(monkeypatch):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    for op, extra in (("enable_tracking", {"endpoints": "ext"}), ("pause_legacy", {"endpoints": "ext"}),
                      ("test_call", {"services": SVC})):
        with pytest.raises(ValueError, match="needs dry_run_id"):
            _notebook(monkeypatch, {"apply_id": APPLY, "results_schema": "c.s", "operation": op,
                                            "mode": "execute", **extra}, w)
    assert w.api_client.puts == []


def test_notebook_apply_execute_without_a_dry_run_is_refused(monkeypatch):
    with pytest.raises(ValueError, match="needs dry_run_id"):
        _notebook(monkeypatch, {"apply_id": APPLY, "results_schema": "c.s", "mode": "execute", "endpoints": "ext",
                                "target_catalog": "c", "target_schema": "s", "scan_run_id": "33333333-3333-3333-3333-333333333333"}, FakeW())


@pytest.mark.parametrize("override, params, match", [
    ({}, {"endpoints": "ext,other"}, "changed since"),
    ({"status": "FAILED"}, {}, "didn't succeed"),
    ({"operation": "pause_legacy"}, {}, "dry run of enable_tracking"),
    ({"requested_by": "someone@x.com"}, {}, "someone else"),
    ({"started_at": "2020-01-01 00:00:00"}, {}, "24 hours"),
])
def test_notebook_execute_needs_a_matching_recent_dry_run(monkeypatch, override, params, match):
    w = CutoverW([_endpoint("ext", GW_FULL), _endpoint("other", GW_FULL)])
    with pytest.raises(ValueError, match=match):
        _gate_case(monkeypatch, w, override, params)
    assert w.api_client.puts == []


def test_notebook_execute_after_its_dry_run_runs(monkeypatch):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    calls = _gate_case(monkeypatch, w)
    assert calls["items"][APPLY][0]["action"] == "tracking_enabled" and len(w.api_client.puts) == 1


def test_notebook_pause_refuses_recent_traffic_unless_forced(monkeypatch):
    w = CutoverW([_endpoint("ext", GW_FULL)])
    base = {"results_schema": "c.s", "operation": "pause_legacy", "endpoints": "ext", "job_run_id": "6"}
    busy = _notebook(monkeypatch, {**base, "apply_id": DRY, "mode": "dry_run"}, w, traffic={"ext": 3})
    assert busy["items"][DRY][0]["action"] == "refused" and _final(busy, DRY)["status"] == "NEEDS_ATTENTION"
    forced = _notebook(monkeypatch, {**base, "apply_id": OTHER, "mode": "dry_run", "force": "true"}, w,
                       traffic={"ext": 3})
    assert forced["items"][OTHER][0]["action"] == "would_pause"


def test_dry_run_gate_rules():
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    ok = {"mode": "dry_run", "operation": "apply", "status": "SUCCEEDED", "fingerprint": "f", "scan_run_id": "s1",
          "requested_by": "me", "started_at": "2026-11-02 01:00:00"}
    assert a.dry_run_gate_error(ok, "apply", "f", "s1", "me", now) is None
    assert "different scan" in a.dry_run_gate_error(ok, "apply", "f", "s2", "me", now)
    assert "24 hours" in a.dry_run_gate_error({**ok, "started_at": "2026-11-01 11:59:00"}, "apply", "f", "s1", "me", now)
    assert "24 hours" in a.dry_run_gate_error({**ok, "started_at": None}, "apply", "f", "s1", "me", now)
    assert "changed" in a.dry_run_gate_error({**ok, "fingerprint": None}, "apply", None, "s1", "me", now)
    assert a.dry_run_gate_error({**ok, "requested_by": ""}, "apply", "f", "s1", "anyone", now) is None
    assert a.DRY_RUN_TTL_HOURS == 24 and "resume_legacy" not in a.DRY_RUN_GATED
