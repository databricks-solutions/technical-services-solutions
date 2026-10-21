"""Each of the 12 checks: one passing and one failing scenario, plus the
SQL-in-prose detector and the low-quality fixture's exact failing set."""

from __future__ import annotations

from typing import Any

from genie_space_iq.checks import (
    check_01_data_sources_exist,
    check_02_table_descriptions,
    check_03_column_descriptions,
    check_04_text_instructions,
    check_05_join_specifications,
    check_06_data_source_count,
    check_07_example_sqls,
    check_08_sql_snippets,
    check_09_entity_format_matching,
    check_10_benchmarks,
    check_11_optimization_run,
    check_12_optimization_accuracy,
    looks_like_sql_in_prose,
    run_all_checks,
)
from genie_space_iq.model import Space


def space(ss: dict[str, Any], opt: dict[str, Any] | None = None) -> Space:
    return Space.from_document(ss, optimization_run=opt)


def _table(identifier: str, description: str | None = None, columns=None) -> dict[str, Any]:
    t: dict[str, Any] = {"identifier": identifier}
    if description is not None:
        t["description"] = [description]
    if columns is not None:
        t["column_configs"] = columns
    return t


# -- Check 1 ---------------------------------------------------------------
def test_check_01_pass():
    ss = {"data_sources": {"tables": [_table("a.b.c")]}}
    assert check_01_data_sources_exist(space(ss))["passed"] is True


def test_check_01_fail():
    assert check_01_data_sources_exist(space({}))["passed"] is False


# -- Check 2 ---------------------------------------------------------------
def test_check_02_pass():
    ss = {"data_sources": {"tables": [_table("a.b.c", "described")]}}
    rec = check_02_table_descriptions(space(ss))
    assert rec["passed"] is True and rec["severity"] == "pass"


def test_check_02_fail():
    ss = {"data_sources": {"tables": [_table("a.b.c"), _table("a.b.d")]}}
    assert check_02_table_descriptions(space(ss))["passed"] is False


def test_check_02_warning_still_passes():
    # 9/10 described -> 90% -> passed but severity warning.
    tables = [_table(f"a.b.t{i}", "d") for i in range(9)] + [_table("a.b.t9")]
    rec = check_02_table_descriptions(space({"data_sources": {"tables": tables}}))
    assert rec["passed"] is True and rec["severity"] == "warning"


# -- Check 3 ---------------------------------------------------------------
def test_check_03_pass():
    cols = [{"column_name": "x", "description": ["d"]}, {"column_name": "y"}]
    ss = {"data_sources": {"tables": [_table("a.b.c", columns=cols)]}}
    assert check_03_column_descriptions(space(ss))["passed"] is True  # 50%


def test_check_03_fail():
    cols = [{"column_name": "x"}, {"column_name": "y"}]
    ss = {"data_sources": {"tables": [_table("a.b.c", columns=cols)]}}
    assert check_03_column_descriptions(space(ss))["passed"] is False  # 0%


# -- Check 4 ---------------------------------------------------------------
def test_check_04_pass():
    ss = {"instructions": {"text_instructions": [{"id": "1", "content": ["x" * 60]}]}}
    assert check_04_text_instructions(space(ss))["passed"] is True


def test_check_04_fail_too_brief():
    ss = {"instructions": {"text_instructions": [{"id": "1", "content": ["short"]}]}}
    assert check_04_text_instructions(space(ss))["passed"] is False


def test_check_04_warning_on_sql_in_prose():
    prose = "Compute revenue as SELECT SUM(o.revenue) FROM orders o WHERE o.year = 2024. "
    content = [prose + "x" * 40 + "\n"]
    ss = {"instructions": {"text_instructions": [{"id": "1", "content": content}]}}
    rec = check_04_text_instructions(space(ss))
    assert rec["passed"] is True and rec["severity"] == "warning"


# -- Check 5 ---------------------------------------------------------------
def test_check_05_pass_multisource_with_join():
    ss = {
        "data_sources": {"tables": [_table("a.b.c"), _table("a.b.d")]},
        "instructions": {"join_specs": [{"id": "1", "left": {}, "right": {}, "sql": []}]},
    }
    assert check_05_join_specifications(space(ss))["passed"] is True


def test_check_05_fail_multisource_no_join():
    ss = {"data_sources": {"tables": [_table("a.b.c"), _table("a.b.d")]}}
    assert check_05_join_specifications(space(ss))["passed"] is False


def test_check_05_single_source_autopass():
    ss = {"data_sources": {"tables": [_table("a.b.c")]}}
    assert check_05_join_specifications(space(ss))["passed"] is True


# -- Check 6 ---------------------------------------------------------------
def test_check_06_pass():
    ss = {"data_sources": {"tables": [_table(f"a.b.t{i}") for i in range(3)]}}
    assert check_06_data_source_count(space(ss))["passed"] is True


def test_check_06_fail_too_many():
    ss = {"data_sources": {"tables": [_table(f"a.b.t{i}") for i in range(13)]}}
    assert check_06_data_source_count(space(ss))["passed"] is False


# -- Check 7 ---------------------------------------------------------------
def test_check_07_pass():
    examples = [{"id": str(i), "question": ["q"], "sql": ["s"]} for i in range(8)]
    ss = {"instructions": {"example_question_sqls": examples}}
    assert check_07_example_sqls(space(ss))["passed"] is True


def test_check_07_fail():
    examples = [{"id": str(i), "question": ["q"], "sql": ["s"]} for i in range(2)]
    ss = {"instructions": {"example_question_sqls": examples}}
    assert check_07_example_sqls(space(ss))["passed"] is False


# -- Check 8 ---------------------------------------------------------------
def test_check_08_pass():
    ss = {"instructions": {"sql_snippets": {"filters": [{"id": "1"}]}}}
    assert check_08_sql_snippets(space(ss))["passed"] is True


def test_check_08_fail():
    assert check_08_sql_snippets(space({}))["passed"] is False


# -- Check 9 ---------------------------------------------------------------
def test_check_09_pass():
    cols = [{"column_name": "x", "enable_entity_matching": True}]
    ss = {"data_sources": {"tables": [_table("a.b.c", columns=cols)]}}
    assert check_09_entity_format_matching(space(ss))["passed"] is True


def test_check_09_fail():
    cols = [{"column_name": "x"}]
    ss = {"data_sources": {"tables": [_table("a.b.c", columns=cols)]}}
    assert check_09_entity_format_matching(space(ss))["passed"] is False


# -- Check 10 --------------------------------------------------------------
def test_check_10_pass():
    qs = [{"id": str(i), "question": ["q"]} for i in range(10)]
    ss = {"benchmarks": {"questions": qs}}
    assert check_10_benchmarks(space(ss))["passed"] is True


def test_check_10_fail():
    qs = [{"id": str(i), "question": ["q"]} for i in range(3)]
    ss = {"benchmarks": {"questions": qs}}
    assert check_10_benchmarks(space(ss))["passed"] is False


# -- Check 11 --------------------------------------------------------------
def test_check_11_pass():
    assert check_11_optimization_run(space({}, opt={"status": "COMPLETED"}))["passed"] is True


def test_check_11_fail():
    assert check_11_optimization_run(space({}))["passed"] is False


# -- Check 12 --------------------------------------------------------------
def test_check_12_pass_fraction():
    assert check_12_optimization_accuracy(space({}, opt={"accuracy": 0.9}))["passed"] is True


def test_check_12_pass_percentage():
    # Accept a 0-100 percentage too.
    assert check_12_optimization_accuracy(space({}, opt={"accuracy": 90}))["passed"] is True


def test_check_12_fail():
    assert check_12_optimization_accuracy(space({}, opt={"accuracy": 0.5}))["passed"] is False


def test_check_12_fail_no_run():
    assert check_12_optimization_accuracy(space({}))["passed"] is False


# -- SQL-in-prose detector -------------------------------------------------
def test_looks_like_sql_in_prose_detects_sql():
    assert looks_like_sql_in_prose("SELECT id FROM orders WHERE id = 1") is True


def test_looks_like_sql_in_prose_ignores_imperative_prose():
    # Two SQL keywords + a dotted identifier would trip the keyword path, but the
    # leading imperative ("When") marks it as guidance prose, so it is NOT flagged.
    line = "When computing SUM and COUNT for orders.revenue, use the curated measure."
    assert looks_like_sql_in_prose(line) is False


def test_looks_like_sql_in_prose_ignores_plain_guidance():
    assert looks_like_sql_in_prose("Always prefer the curated revenue measure.") is False


def test_looks_like_sql_in_prose_blank():
    assert looks_like_sql_in_prose("   ") is False


# -- fixture-level failing set --------------------------------------------
def test_low_quality_failing_set(load_fixture):
    checks = run_all_checks(Space.from_document(load_fixture("low_quality.json")))
    failing = sorted(c["id"] for c in checks if not c["passed"])
    assert failing == [2, 3, 4, 5, 7, 8, 9, 10, 11, 12]


def test_all_checks_have_contract_shape(load_fixture):
    checks = run_all_checks(Space.from_document(load_fixture("high_quality.json")))
    assert len(checks) == 12
    for c in checks:
        assert set(c) >= {"id", "name", "passed", "severity", "threshold", "evidence", "fixable"}
        assert c["severity"] in {"pass", "warning", "fail"}
