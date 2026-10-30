"""Offline tests for the apply payload builders."""

import pytest

import ug_migration_apply as a
import ug_migration_planner as m
from test_planner import EXTERNAL, EXTERNAL_SAME_KEY, PT, _ep


class FakeSecrets(a.Secrets):
    def __init__(self, uc_map=None, allow_read=False):
        super().__init__(None, uc_map, allow_read)


def _plan(eps):
    return m.plan(eps, {}, {}, "c", "s", traffic_known=False)


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
    body = a.build_model_service(ep, rows[0], fqn)
    routing = body["config"]["routing"]
    assert [d["name"] for d in routing["destinations"]] == ["primary"]
    assert "traffic_percentage" not in routing["destinations"][0]
    assert [d["name"] for d in routing["fallback"]["destinations"]] == ["backup"]
    ext = routing["destinations"][0]["external_model_config"]
    assert ext["model_provider_service"] == "model-provider-services/c.s.openai_llm_openai"
    assert ext["target"]["model"] == "gpt-5"
    assert len(body["config"]["rate_limits"]) == 3
    assert body["config"]["inference_table"] == {"parent": "schemas/main.logs", "table_name_prefix": "proj_a_ug"}


def test_model_service_pt():
    ep = _ep(PT)
    rows, _ = _plan([ep])
    body = a.build_model_service(ep, rows[0], {})
    d = body["config"]["routing"]["destinations"][0]
    assert d["provisioned_throughput_config"] == {"model_serving_endpoint": "serving-endpoints/llama-pt"}


def test_mask_hides_plaintext():
    masked = a._mask({"config": {"openai": {"direct": {"api_key": {"plaintext": "sk-real"}}}}})
    assert masked["config"]["openai"]["direct"]["api_key"]["plaintext"] == "***"


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
    res = a.terraform(W(), None, "c", "s", None, str(out))
    tf = out.read_text()
    assert res["provider_services"] == 1 and res["model_services"] == 3
    assert res["variables"] == ["secret_llm_openai"]
    assert 'variable "secret_llm_openai"' in tf and "sensitive   = true" in tf
    assert "plaintext = var.secret_llm_openai" in tf and "sk-" not in tf
    assert 'resource "databricks_grants" "service_proj_a_gpt"' in tf
    assert "depends_on = [databricks_ai_gateway_model_provider_service.provider_openai_llm_openai]" in tf
    res2 = a.terraform(W(), None, "c", "s", {"llm/openai": "secrets/c.s.openai"}, str(out))
    assert res2["variables"] == [] and '"secrets/c.s.openai"' in out.read_text()
