"""optimize.py: dry-run diff, --apply PATCH body, determinism, per-operation
apply behaviour, unknown-field preservation, and fix validation."""

from __future__ import annotations

import json
from typing import Any

import optimize as optimize_cli
import pytest
from genie_space_iq import apply_fixes, render_diff, validate_fixes
from genie_space_iq.fixes import FixApplicationError, FixValidationError


def _base_space() -> dict[str, Any]:
    return {
        "version": 2,
        "data_sources": {
            "tables": [
                {
                    "identifier": "main.retail.orders",
                    "column_configs": [{"column_name": "region"}],
                }
            ]
        },
        "instructions": {},
        "benchmarks": {"questions": []},
    }


# -- diff ------------------------------------------------------------------
def test_render_diff_shows_change():
    before = _base_space()
    after = apply_fixes(
        before,
        [
            {
                "operation": "set_table_description",
                "target": {"identifier": "main.retail.orders"},
                "new_value": ["Orders fact table."],
            }
        ],
    )
    diff = render_diff(before, after, space_id="s1")
    assert "Orders fact table." in diff
    assert diff.startswith("---")


def test_render_diff_empty_when_no_change():
    before = _base_space()
    assert render_diff(before, before) == ""


# -- determinism -----------------------------------------------------------
def test_apply_is_deterministic():
    before = _base_space()
    fixes = [
        {
            "operation": "add_example_sql",
            "target": {"kind": "example_sql"},
            "new_value": {"question": "How many orders?", "sql": "SELECT COUNT(*) FROM orders;"},
        }
    ]
    first = apply_fixes(before, fixes)
    second = apply_fixes(before, fixes)
    assert first == second
    # deterministic (content-hash) id, not a random uuid
    new_id = first["instructions"]["example_question_sqls"][0]["id"]
    assert len(new_id) == 32 and all(ch in "0123456789abcdef" for ch in new_id)


# -- per-operation coverage ------------------------------------------------
def test_op_set_column_description_creates_missing_column():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "set_column_description",
                "target": {"identifier": "main.retail.orders", "column_name": "amount"},
                "new_value": "Order amount.",
            }
        ],
    )
    cols = after["data_sources"]["tables"][0]["column_configs"]
    assert {"column_name": "amount", "description": ["Order amount."]} in cols


def test_op_add_column_synonyms_preserves_existing():
    space = _base_space()
    space["data_sources"]["tables"][0]["column_configs"][0]["synonyms"] = ["geo"]
    after = apply_fixes(
        space,
        [
            {
                "operation": "add_column_synonyms",
                "target": {"identifier": "main.retail.orders", "column_name": "region"},
                "new_value": ["territory", "geo"],
            }
        ],
    )
    synonyms = after["data_sources"]["tables"][0]["column_configs"][0]["synonyms"]
    assert synonyms == ["geo", "territory"]  # existing kept, dup dropped, new appended


def test_op_enable_entity_matching_sets_format_assistance():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "enable_entity_matching",
                "target": {"identifier": "main.retail.orders", "column_name": "region"},
            }
        ],
    )
    col = after["data_sources"]["tables"][0]["column_configs"][0]
    assert col["enable_entity_matching"] is True
    assert col["enable_format_assistance"] is True


def test_op_set_text_instruction_enforces_trailing_newline_and_single_block():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "set_text_instruction",
                "target": {"kind": "text_instruction"},
                "new_value": ["Line without newline"],
            }
        ],
    )
    blocks = after["instructions"]["text_instructions"]
    assert len(blocks) == 1
    assert blocks[0]["content"] == ["Line without newline\n"]


def test_op_set_text_instruction_preserves_existing_id():
    space = _base_space()
    space["instructions"]["text_instructions"] = [{"id": "keepme", "content": ["old\n"]}]
    after = apply_fixes(
        space,
        [{"operation": "set_text_instruction", "new_value": "new content"}],
    )
    assert after["instructions"]["text_instructions"][0]["id"] == "keepme"


def test_op_add_join_spec():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "add_join_spec",
                "target": {"kind": "join_spec"},
                "new_value": {
                    "left": {"identifier": "main.retail.orders", "alias": "o"},
                    "right": {"identifier": "main.retail.customers", "alias": "c"},
                    "sql": [
                        "`o`.`customer_id` = `c`.`customer_id`",
                        "--rt=FROM_RELATIONSHIP_TYPE_MANY_TO_ONE--",
                    ],
                },
            }
        ],
    )
    assert len(after["instructions"]["join_specs"]) == 1


def test_op_add_sql_snippet_measure():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "add_sql_snippet",
                "target": {"kind": "measure"},
                "new_value": {"display_name": "Total", "sql": "SUM(revenue) AS total"},
            }
        ],
    )
    assert len(after["instructions"]["sql_snippets"]["measures"]) == 1


def test_op_add_benchmark_question():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "add_benchmark_question",
                "target": {"kind": "benchmark"},
                "new_value": {"question": "How many?", "sql": "SELECT COUNT(*) FROM orders;"},
            }
        ],
    )
    q = after["benchmarks"]["questions"][0]
    assert q["answer"][0]["format"] == "SQL"


def test_op_set_field_raw_path():
    after = apply_fixes(
        _base_space(),
        [
            {
                "operation": "set_field",
                "target": {"path": "data_sources.tables[0].description"},
                "new_value": ["via raw path"],
            }
        ],
    )
    assert after["data_sources"]["tables"][0]["description"] == ["via raw path"]


def test_apply_makes_low_quality_scan_improve(load_fixture):
    """A batch of fixes measurably raises the deterministic score."""
    from genie_space_iq import scan_space

    space = load_fixture("low_quality.json")
    before = scan_space(space)["score"]
    fixes = [
        {
            "operation": "set_table_description",
            "target": {"identifier": "main.sales.leads"},
            "new_value": ["Leads table."],
        },
        {
            "operation": "set_table_description",
            "target": {"identifier": "main.sales.opportunities"},
            "new_value": ["Opportunities table."],
        },
    ]
    after = apply_fixes(space, fixes)
    assert scan_space(after)["score"] > before


# -- validation ------------------------------------------------------------
def test_validate_rejects_unknown_operation():
    with pytest.raises(FixValidationError):
        validate_fixes([{"operation": "delete_everything"}])


def test_validate_rejects_non_list():
    with pytest.raises(FixValidationError):
        validate_fixes("not a list")


def test_validate_accepts_wrapped_object():
    fixes = validate_fixes(
        {
            "fixes": [
                {
                    "operation": "enable_format_assistance",
                    "target": {"identifier": "a", "column_name": "b"},
                }
            ]
        }
    )
    assert len(fixes) == 1


def test_apply_errors_on_missing_data_source():
    with pytest.raises(FixApplicationError):
        apply_fixes(
            _base_space(),
            [
                {
                    "operation": "set_table_description",
                    "target": {"identifier": "does.not.exist"},
                    "new_value": ["x"],
                }
            ],
        )


# -- CLI: dry-run and --apply ---------------------------------------------
def _write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_cli_dry_run_prints_diff(tmp_path, capsys):
    space_file = tmp_path / "space.json"
    fixes_file = tmp_path / "fixes.json"
    _write_json(space_file, _base_space())
    _write_json(
        fixes_file,
        [
            {
                "operation": "set_table_description",
                "target": {"identifier": "main.retail.orders"},
                "new_value": ["Orders fact table."],
            }
        ],
    )
    rc = optimize_cli.main(
        ["--serialized-space-file", str(space_file), "--fixes-file", str(fixes_file)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "Orders fact table." in out


def test_cli_apply_builds_correct_patch_body(tmp_path, capsys, monkeypatch):
    space_file = tmp_path / "space.json"
    fixes_file = tmp_path / "fixes.json"
    _write_json(space_file, _base_space())
    _write_json(
        fixes_file,
        [
            {
                "operation": "set_table_description",
                "target": {"identifier": "main.retail.orders"},
                "new_value": ["Orders fact table."],
            }
        ],
    )

    captured: dict[str, Any] = {}

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        def patch_space(self, space_id, serialized_space):
            captured["space_id"] = space_id
            captured["serialized_space"] = serialized_space
            return {"status": "ok"}

    # optimize.main does `from genie_space_iq import GenieSpaceApi` at call time.
    import genie_space_iq

    monkeypatch.setattr(genie_space_iq, "GenieSpaceApi", _FakeApi)

    rc = optimize_cli.main(
        [
            "--space-id",
            "space123",
            "--serialized-space-file",
            str(space_file),
            "--fixes-file",
            str(fixes_file),
            "--apply",
        ]
    )
    assert rc == 0
    assert captured["space_id"] == "space123"
    assert (
        captured["serialized_space"]["data_sources"]["tables"][0]["description"]
        == ["Orders fact table."]
    )
    assert "Applied" in capsys.readouterr().out
