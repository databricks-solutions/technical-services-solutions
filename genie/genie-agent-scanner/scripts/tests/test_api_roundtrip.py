"""PATCH round-trip preserves unknown top-level AND nested fields.

Uses a fully mocked API client -- NO live calls, NO databricks-sdk import.
"""

from __future__ import annotations

import json
from typing import Any

from genie_space_iq import GenieSpaceApi, apply_fixes


class _FakeApiClient:
    """Stand-in for WorkspaceClient.api_client; records every call."""

    def __init__(self, get_response: dict[str, Any]):
        self._get_response = get_response
        self.calls: list[dict[str, Any]] = []

    def do(self, method: str, path: str, query=None, body=None):
        self.calls.append({"method": method, "path": path, "query": query, "body": body})
        if method == "GET":
            return self._get_response
        return {"status": "ok"}


class _FakeClient:
    def __init__(self, get_response: dict[str, Any]):
        self.api_client = _FakeApiClient(get_response)


def _get_response_for(serialized_space: dict[str, Any]) -> dict[str, Any]:
    # A realistic GET response: serialized_space is a JSON *string*.
    return {
        "space_id": "space123",
        "title": "Retail",
        "warehouse_id": "wh1",
        "serialized_space": json.dumps(serialized_space),
    }


def test_get_space_parses_serialized_space_string(load_fixture):
    extra = load_fixture("extra_fields.json")
    client = _FakeClient(_get_response_for(extra))
    api = GenieSpaceApi(client=client)

    resp = api.get_space("space123")

    assert isinstance(resp["serialized_space"], dict)
    assert resp["serialized_space"]["mystery_top_level"]["preserve"] is True
    # GET carried the include_serialized_space flag.
    assert client.api_client.calls[0]["method"] == "GET"
    assert client.api_client.calls[0]["query"] == {"include_serialized_space": "true"}


def test_patch_roundtrip_preserves_unknown_fields(load_fixture):
    extra = load_fixture("extra_fields.json")
    client = _FakeClient(_get_response_for(extra))
    api = GenieSpaceApi(client=client)

    before = api.get_space("space123")["serialized_space"]
    patched = apply_fixes(
        before,
        [
            {
                "check_id": 2,
                "operation": "set_table_description",
                "target": {"identifier": "main.retail.customers"},
                "new_value": ["Updated customer description."],
            }
        ],
    )
    api.patch_space("space123", patched)

    patch_call = client.api_client.calls[-1]
    assert patch_call["method"] == "PATCH"
    assert patch_call["path"] == "/api/2.0/genie/spaces/space123"

    body_space = json.loads(patch_call["body"]["serialized_space"])

    # Unknown TOP-LEVEL field preserved verbatim.
    assert body_space["mystery_top_level"] == {
        "preserve": True,
        "count": 3,
        "note": "keep this whole object",
    }
    # Unknown NESTED fields preserved (under data_sources, on a table, on a column).
    assert (
        body_space["data_sources"]["custom_data_sources_meta"]["provenance"]
        == "unknown-but-preserved"
    )
    table0 = body_space["data_sources"]["tables"][0]
    assert table0["mystery_nested_field"] == "keep me too"
    assert table0["column_configs"][0]["custom_col_flag"] == 42
    assert body_space["instructions"]["mystery_instructions_field"] == [
        "preserve this array element"
    ]

    # The targeted change was actually applied.
    assert table0["description"] == ["Updated customer description."]


def test_input_space_is_not_mutated(load_fixture):
    extra = load_fixture("extra_fields.json")
    client = _FakeClient(_get_response_for(extra))
    api = GenieSpaceApi(client=client)

    before = api.get_space("space123")["serialized_space"]
    before_snapshot = json.dumps(before, sort_keys=True)
    apply_fixes(
        before,
        [
            {
                "operation": "set_table_description",
                "target": {"identifier": "main.retail.customers"},
                "new_value": ["changed"],
            }
        ],
    )
    assert json.dumps(before, sort_keys=True) == before_snapshot
