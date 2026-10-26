"""Unity Catalog enrichment: metric-view classification, effective table
descriptions from UC comments, config-vs-UC column sourcing for check 3, and
the graceful live-fetch helper."""

from __future__ import annotations

from typing import Any

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from genie_space_iq import GenieSpaceApi, fetch_uc_metadata, normalize_uc_table, scan_space
from genie_space_iq.checks import (
    check_01_data_sources_exist,
    check_02_table_descriptions,
    check_03_column_descriptions,
)
from genie_space_iq.model import Space


def space(ss: dict[str, Any], uc: dict[str, Any] | None = None) -> Space:
    return Space.from_document(ss, uc_metadata=uc)


# -- metric-view classification (check 1) ----------------------------------
def test_uc_metric_view_reclassified_out_of_tables():
    # Two entries declared under data_sources.tables; UC flags one as a METRIC_VIEW.
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.orders"}, {"identifier": "c.s.mv_calls"}]
        }
    }
    uc = {
        "c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []},
        "c.s.mv_calls": {"table_type": "METRIC_VIEW", "comment": "Calls MV.", "columns": []},
    }
    sp = space(ss, uc)
    assert [r.identifier for r in sp.tables] == ["c.s.orders"]
    assert [r.identifier for r in sp.metric_views] == ["c.s.mv_calls"]

    rec = check_01_data_sources_exist(sp)
    assert rec["passed"] is True
    assert "1 table(s), 1 metric view(s)" in rec["evidence"]


def test_without_uc_no_reclassification():
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.orders"}, {"identifier": "c.s.mv_calls"}]
        }
    }
    sp = space(ss, None)
    # No UC: both stay tables, and check 1 flags the config-only classification.
    assert len(sp.tables) == 2
    assert len(sp.metric_views) == 0
    rec = check_01_data_sources_exist(sp)
    assert "2 table(s), 0 metric view(s)" in rec["evidence"]
    assert "UC not available" in rec["evidence"]


def test_declared_metric_view_reclassified_to_table_when_uc_says_managed():
    # FIX 1 reverse direction: an entry declared under data_sources.metric_views
    # whose UC table_type is NOT METRIC_VIEW must be classified as a regular table.
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.orders"}],
            "metric_views": [{"identifier": "c.s.not_really_mv"}],
        }
    }
    uc = {
        "c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []},
        "c.s.not_really_mv": {"table_type": "MANAGED", "comment": "Also a table.", "columns": []},
    }
    sp = space(ss, uc)
    assert sorted(r.identifier for r in sp.tables) == ["c.s.not_really_mv", "c.s.orders"]
    assert sp.metric_views == []
    assert "2 table(s), 0 metric view(s)" in check_01_data_sources_exist(sp)["evidence"]


def test_declared_metric_view_without_uc_stays_metric_view():
    # Fallback: no UC entry for the declared metric view -> trust the bucket.
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.orders"}],
            "metric_views": [{"identifier": "c.s.mv_calls"}],
        }
    }
    uc = {"c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []}}
    sp = space(ss, uc)  # mv_calls has no UC entry -> config bucket wins
    assert [r.identifier for r in sp.tables] == ["c.s.orders"]
    assert [r.identifier for r in sp.metric_views] == ["c.s.mv_calls"]


@pytest.mark.parametrize("table_type", ["VIEW", "MATERIALIZED_VIEW", "STREAMING_TABLE"])
def test_non_metric_view_uc_types_are_tables(table_type):
    # Any UC type other than METRIC_VIEW is a regular table.
    ss = {"data_sources": {"tables": [{"identifier": "c.s.thing"}]}}
    uc = {"c.s.thing": {"table_type": table_type, "comment": "c.", "columns": []}}
    sp = space(ss, uc)
    assert [r.identifier for r in sp.tables] == ["c.s.thing"]
    assert sp.metric_views == []


# -- effective table description from UC comment (check 2) -----------------
def test_uc_comment_counts_as_table_description():
    # No space-level description, but UC carries a comment -> described.
    ss = {"data_sources": {"tables": [{"identifier": "c.s.orders"}]}}
    uc = {"c.s.orders": {"table_type": "MANAGED", "comment": "From UC.", "columns": []}}
    rec = check_02_table_descriptions(space(ss, uc))
    assert rec["passed"] is True
    assert "1/1 tables have descriptions (100%)" in rec["evidence"]


def test_no_uc_comment_and_no_override_is_undescribed():
    ss = {"data_sources": {"tables": [{"identifier": "c.s.orders"}]}}
    uc = {"c.s.orders": {"table_type": "MANAGED", "comment": None, "columns": []}}
    rec = check_02_table_descriptions(space(ss, uc))
    assert rec["passed"] is False
    assert "0/1 tables have descriptions (0%)" in rec["evidence"]


def test_metric_views_excluded_from_table_description_denominator():
    # 1 real table (described) + 1 metric view -> denominator is 1, not 2.
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.orders"}, {"identifier": "c.s.mv_calls"}]
        }
    }
    uc = {
        "c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []},
        "c.s.mv_calls": {"table_type": "METRIC_VIEW", "comment": "Calls.", "columns": []},
    }
    rec = check_02_table_descriptions(space(ss, uc))
    assert rec["passed"] is True
    assert "1/1 tables have descriptions (100%)" in rec["evidence"]


# -- check 2 zero-table rule (FIX 3) ---------------------------------------
def test_check_02_empty_space_fails_not_vacuous_pass():
    # 0 tables AND 0 metric views -> FAIL (mirrors check 3; check 1 also fails).
    rec = check_02_table_descriptions(space({}, None))
    assert rec["passed"] is False
    assert rec["severity"] == "fail"
    assert "empty space" in rec["evidence"]


def test_check_02_metric_view_only_space_passes():
    # A metric-view-only space has no tables to grade -> PASS (metric views are
    # graded separately); the space is still valid (check 1 passes).
    ss = {"data_sources": {"metric_views": [{"identifier": "c.s.mv"}]}}
    uc = {"c.s.mv": {"table_type": "METRIC_VIEW", "comment": "MV.", "columns": []}}
    rec = check_02_table_descriptions(space(ss, uc))
    assert rec["passed"] is True
    assert rec["severity"] == "pass"
    assert "metric-view-only" in rec["evidence"]


def test_check_02_zero_table_note_when_uc_unavailable():
    # FIX 3a: the zero-table early-return still carries the UC-not-available note.
    rec_empty = check_02_table_descriptions(space({}, None))
    assert "UC not available" in rec_empty["evidence"]
    ss = {"data_sources": {"metric_views": [{"identifier": "c.s.mv"}]}}
    rec_mv = check_02_table_descriptions(space(ss, None))
    assert rec_mv["passed"] is True
    assert "UC not available" in rec_mv["evidence"]


# -- config-vs-UC column sourcing (check 3) --------------------------------
def test_check_03_counts_configured_columns_not_uc_columns():
    # UC reports many well-commented columns, but NONE are configured in the
    # space -> the check must fail 0/0, never inflate to a UC column count.
    ss = {"data_sources": {"tables": [{"identifier": "c.s.orders"}]}}
    uc = {
        "c.s.orders": {
            "table_type": "MANAGED",
            "comment": "Orders.",
            "columns": [{"name": f"col{i}", "comment": "documented"} for i in range(30)],
        }
    }
    rec = check_03_column_descriptions(space(ss, uc))
    assert rec["passed"] is False
    assert "0/0 configured columns" in rec["evidence"]
    assert "30" not in rec["evidence"]  # UC column count must not leak in


def test_check_03_empty_columns_fails_not_vacuous_pass():
    ss = {"data_sources": {"tables": [{"identifier": "c.s.orders"}]}}
    rec = check_03_column_descriptions(space(ss, None))
    assert rec["passed"] is False
    assert rec["severity"] == "fail"
    assert "0/0 configured columns" in rec["evidence"]


def test_check_03_uses_configured_column_descriptions_when_present():
    ss = {
        "data_sources": {
            "tables": [
                {
                    "identifier": "c.s.orders",
                    "column_configs": [
                        {"column_name": "x", "description": ["described"]},
                        {"column_name": "y"},
                    ],
                }
            ]
        }
    }
    # 1/2 configured columns described -> 50% -> passes; UC absence is irrelevant.
    rec = check_03_column_descriptions(space(ss, None))
    assert rec["passed"] is True
    assert "1/2 configured columns" in rec["evidence"]


# -- normalize + graceful live fetch ---------------------------------------
def test_normalize_uc_table_reduces_to_schema():
    raw = {
        "name": "orders",
        "table_type": "MANAGED",
        "comment": "Orders fact.",
        "storage_location": "s3://ignored",
        "columns": [
            {"name": "id", "comment": "key", "type_name": "LONG"},
            {"name": "amt", "comment": None},
            "not-a-dict",
        ],
    }
    out = normalize_uc_table(raw)
    assert out == {
        "comment": "Orders fact.",
        "table_type": "MANAGED",
        "columns": [{"name": "id", "comment": "key"}, {"name": "amt", "comment": None}],
    }


class _FakeTableInfo:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def as_dict(self) -> dict[str, Any]:
        return self._payload


class _FakeTablesApi:
    def __init__(
        self,
        table_map: dict[str, dict[str, Any]],
        errors: dict[str, BaseException] | None = None,
    ):
        self._table_map = table_map
        self._errors = errors or {}

    def get(self, full_name: str) -> _FakeTableInfo:
        if full_name in self._errors:
            raise self._errors[full_name]
        return _FakeTableInfo(self._table_map[full_name])


class _FakeClient:
    def __init__(
        self,
        table_map: dict[str, dict[str, Any]],
        errors: dict[str, BaseException] | None = None,
    ):
        self.tables = _FakeTablesApi(table_map, errors)


def test_fetch_uc_metadata_degrades_on_expected_api_error():
    # NotFound / PermissionDenied are DatabricksError subclasses -> degrade.
    table_map = {
        "c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []},
        "c.s.mv_calls": {"table_type": "METRIC_VIEW", "comment": "MV.", "columns": []},
    }
    errors = {
        "c.s.secret": PermissionDenied("denied: c.s.secret"),
        "c.s.missing": NotFound("no such table: c.s.missing"),
    }
    api = GenieSpaceApi(client=_FakeClient(table_map, errors))

    uc, warnings = fetch_uc_metadata(
        api, ["c.s.orders", "c.s.secret", "c.s.missing", "c.s.mv_calls"]
    )

    assert set(uc) == {"c.s.orders", "c.s.mv_calls"}
    assert uc["c.s.mv_calls"]["table_type"] == "METRIC_VIEW"
    assert [w[0] for w in warnings] == ["c.s.secret", "c.s.missing"]
    assert "denied" in warnings[0][1]


def test_fetch_uc_metadata_does_not_mask_unexpected_error():
    # A non-DatabricksError (e.g. a payload/shape change surfacing as TypeError)
    # must propagate, not be swallowed as a "UC missing" warning.
    table_map = {"c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []}}
    errors = {"c.s.orders": TypeError("unexpected UC payload shape")}
    api = GenieSpaceApi(client=_FakeClient(table_map, errors))

    with pytest.raises(TypeError, match="unexpected UC payload shape"):
        fetch_uc_metadata(api, ["c.s.orders"])


def test_fetch_uc_metadata_feeds_scorer_end_to_end():
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.orders"}, {"identifier": "c.s.mv_calls"}]
        }
    }
    table_map = {
        "c.s.orders": {"table_type": "MANAGED", "comment": "Orders.", "columns": []},
        "c.s.mv_calls": {"table_type": "METRIC_VIEW", "comment": "MV.", "columns": []},
    }
    api = GenieSpaceApi(client=_FakeClient(table_map))
    identifiers = Space.from_document(ss).data_source_identifiers
    uc, warnings = fetch_uc_metadata(api, identifiers)
    assert warnings == []

    report = scan_space(ss, uc_metadata=uc)
    check1 = next(c for c in report["checks"] if c["id"] == 1)
    assert "1 table(s), 1 metric view(s)" in check1["evidence"]
    assert report["uc_available"] is True
    assert report["uc_status"] == "full"


# -- partial-enrichment visibility (FIX 4) ---------------------------------
def test_uc_status_tri_state_full_partial_unavailable():
    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.a"}, {"identifier": "c.s.b"}]
        }
    }
    full_uc = {
        "c.s.a": {"table_type": "MANAGED", "comment": "A.", "columns": []},
        "c.s.b": {"table_type": "MANAGED", "comment": "B.", "columns": []},
    }
    partial_uc = {"c.s.a": full_uc["c.s.a"]}  # c.s.b missing

    full = scan_space(ss, uc_metadata=full_uc)
    assert full["uc_status"] == "full"
    assert full["uc_available"] is True
    assert full["uc_missing"] == []

    partial = scan_space(ss, uc_metadata=partial_uc)
    assert partial["uc_status"] == "partial"
    assert partial["uc_available"] is True
    assert partial["uc_missing"] == ["c.s.b"]

    none = scan_space(ss, uc_metadata=None)
    assert none["uc_status"] == "unavailable"
    assert none["uc_available"] is False
    assert none["uc_missing"] == []


def test_partial_enrichment_surfaced_in_markdown():
    from genie_space_iq import render_markdown

    ss = {
        "data_sources": {
            "tables": [{"identifier": "c.s.a"}, {"identifier": "c.s.b"}]
        }
    }
    partial_uc = {"c.s.a": {"table_type": "MANAGED", "comment": "A.", "columns": []}}
    md = render_markdown(scan_space(ss, uc_metadata=partial_uc))
    assert "partial" in md
    assert "c.s.b" in md
