"""The 12 deterministic IQ-scan checks.

A faithful, LLM-free port of the IQ-scan scoring core from the public Databricks
Genie Workbench accelerator (databricks-solutions/databricks-genie-workbench),
``packages/genie-space-optimizer/.../iq_scan/scoring.py`` (``calculate_score``).
This is a modified derivative work; see NOTICE.md for attribution.
Each check consumes a :class:`~genie_space_iq.model.Space` and returns a record::

    {id, name, passed, severity, threshold, evidence, fixable, levers}

* ``severity`` is one of ``pass`` | ``warning`` | ``fail``.
* A ``warning`` still counts as ``passed`` (matching the source: ``passed`` is set
  from the coverage threshold; severity is a finer-grained annotation).
* Checks 1-10 are configuration checks; checks 11-12 are optimization outcomes
  (``CONFIG_CHECK_COUNT = 10``).

The scan is fully deterministic: same input => same output. No network, no LLM.
"""

from __future__ import annotations

import re
from typing import Any

from .levers import levers_for_check
from .model import Space, as_str_list

CONFIG_CHECK_COUNT = 10
TOTAL_CHECKS = 12

# -- Check 4 helper: smart "SQL-in-prose" detector -------------------------
# Reimplemented from the upstream ``iq_scan/scoring.py`` ``looks_like_sql_in_prose``
# helper (see NOTICE.md).

_SQL_ANCHOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bSELECT\b[\s\S]*\bFROM\b", re.IGNORECASE),
    re.compile(r"\bJOIN\b\s+[\w.`]+\s+[\s\S]*\bON\b", re.IGNORECASE),
    re.compile(r"\bWHERE\b\s+[\w.`]+\s*[=<>!]", re.IGNORECASE),
    re.compile(r"\bGROUP\s+BY\b[\s\S]*\bHAVING\b", re.IGNORECASE),
)
_PROSE_IMPERATIVE_RE = re.compile(
    r"^\s*(?:Do not|Don't|Never|Always|When|If|Prefer|Avoid|Combine|Link|Pair|"
    r"Associate|Consider|Note)\b",
    re.IGNORECASE,
)
_SQL_IN_TEXT_RE = re.compile(
    r"\b(SELECT|FROM|WHERE|JOIN|ON|GROUP\s+BY|ORDER\s+BY|HAVING|SUM|COUNT|AVG|MIN|MAX|DISTINCT)\b",
    re.IGNORECASE,
)
_SQL_STRUCTURAL_SIGNALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\w+\.\w+\b"),  # dotted identifier
    re.compile(r"!=|[=<>]"),  # comparator
    re.compile(r"\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\(", re.IGNORECASE),  # aggregate call
    re.compile(r"\bIS\s+(?:NOT\s+)?NULL\b", re.IGNORECASE),  # IS [NOT] NULL
)


def looks_like_sql_in_prose(line: str) -> bool:
    """Heuristically detect a line of prose that is really raw SQL."""
    if not line or not line.strip():
        return False
    for pat in _SQL_ANCHOR_PATTERNS:
        if pat.search(line):
            return True
    if _PROSE_IMPERATIVE_RE.match(line):
        return False
    distinct_kws = {
        re.sub(r"\s+", " ", m.group(1).upper()) for m in _SQL_IN_TEXT_RE.finditer(line)
    }
    if len(distinct_kws) >= 2 and any(sig.search(line) for sig in _SQL_STRUCTURAL_SIGNALS):
        return True
    return False


# -- record builder --------------------------------------------------------

def _record(
    check_id: int,
    name: str,
    passed: bool,
    threshold: str,
    evidence: str,
    severity: str | None = None,
) -> dict[str, Any]:
    if severity is None:
        severity = "pass" if passed else "fail"
    lever_info = levers_for_check(check_id)
    return {
        "id": check_id,
        "name": name,
        "passed": passed,
        "severity": severity,
        "threshold": threshold,
        "evidence": evidence,
        "fixable": lever_info["fixable"],
        "levers": list(lever_info["levers"]),
    }


def _pct(n: int, d: int) -> float:
    return (n / d) if d else 0.0


# -- the 12 checks ---------------------------------------------------------

def check_01_data_sources_exist(space: Space) -> dict[str, Any]:
    n_tables = len(space.tables)
    n_metric_views = len(space.metric_views)
    total = n_tables + n_metric_views
    passed = total >= 1
    evidence = f"{n_tables} table(s), {n_metric_views} metric view(s) configured"
    if not space.uc_available:
        evidence += " (UC not available; metric views classified from config only)"
    return _record(1, "Data sources exist", passed, ">=1 table or metric view", evidence)


def check_02_table_descriptions(space: Space) -> dict[str, Any]:
    # Denominator is TABLES ONLY -- metric views are excluded (they are graded
    # separately by Genie Workbench). A table is "described" if it has a
    # space-level override OR an effective UC comment.
    tables = space.tables
    # UC-dependent check: annotate every branch when UC classification/comments
    # were unavailable, so a config-only reading is never mistaken for parity.
    uc_note = "" if space.uc_available else " (UC not available; space-level descriptions only)"
    if not tables:
        # Zero-table rule (mirrors check 3's no-vacuous-pass philosophy):
        #  * metric-view-only space -> PASS: there are legitimately no tables to
        #    grade (metric views are graded separately), and check 1 still passes.
        #  * truly empty space -> FAIL: 0 data sources is not a vacuous pass
        #    (check 1 also fails, so the space stays Not Ready either way).
        if space.metric_views:
            return _record(
                2,
                "Table descriptions",
                True,
                ">=80% of tables described",
                "No tables to describe (metric-view-only space)" + uc_note,
                severity="pass",
            )
        return _record(
            2,
            "Table descriptions",
            False,
            ">=80% of tables described",
            "No tables configured to describe (empty space)" + uc_note,
            severity="fail",
        )
    described = sum(1 for t in tables if t.effective_has_description)
    pct = _pct(described, len(tables))
    passed = pct >= 0.80
    evidence = f"{described}/{len(tables)} tables have descriptions ({pct:.0%})"
    if not passed:
        severity = "fail"
        evidence += " - 80%+ required"
    elif pct < 1.0:
        severity = "warning"
        evidence += " - aim for 100%"
    else:
        severity = "pass"
    return _record(
        2, "Table descriptions", passed, ">=80% of tables described", evidence + uc_note, severity
    )


def check_03_column_descriptions(space: Space) -> dict[str, Any]:
    # Denominator is columns CONFIGURED IN THE SPACE (``column_configs``), never
    # UC columns. When no columns are configured the check FAILS 0/0 (0% < 50%);
    # it must not vacuously pass.
    columns = space.all_columns()
    total = len(columns)
    if total == 0:
        return _record(
            3,
            "Column descriptions",
            False,
            ">=50% of columns described",
            "0/0 configured columns have descriptions (0%) - no columns configured "
            "in the space (UC columns are not counted); 50%+ required",
            severity="fail",
        )
    described = sum(1 for c in columns if c.has_description)
    pct = _pct(described, total)
    passed = pct >= 0.50
    with_synonyms = sum(1 for c in columns if c.synonyms)
    evidence = f"{described}/{total} configured columns have descriptions ({pct:.0%})"
    if not passed:
        severity = "fail"
        evidence += " - 50%+ required"
    elif pct < 0.80:
        severity = "warning"
        evidence += " - aim for 80%+"
    else:
        severity = "pass"
    if with_synonyms == 0:
        evidence += " - advisory: no column synonyms defined"
    return _record(
        3, "Column descriptions", passed, ">=50% of columns described", evidence, severity
    )


def check_04_text_instructions(space: Space) -> dict[str, Any]:
    blocks = space.text_instructions
    text = space.instruction_text()
    total_chars = len(text)
    passed = len(blocks) >= 1 and total_chars > 50
    sql_in_prose = any(
        looks_like_sql_in_prose(line) for line in text.splitlines() if line.strip()
    )
    if not passed:
        severity = "fail"
        if not blocks:
            evidence = "No text instructions configured"
        else:
            evidence = f"Text instructions too brief ({total_chars} chars; need >50)"
    elif total_chars > 2000:
        severity = "warning"
        evidence = f"{total_chars} chars of instructions - consider trimming below 2000"
    elif sql_in_prose:
        severity = "warning"
        evidence = (
            f"{total_chars} chars of instructions - raw SQL detected in prose; "
            "move it to example SQL"
        )
    else:
        severity = "pass"
        evidence = f"{total_chars} chars of instructions across {len(blocks)} block(s)"
    return _record(4, "Text instructions", passed, ">=1 block, >50 chars", evidence, severity)


def check_05_join_specifications(space: Space) -> dict[str, Any]:
    total_sources = space.data_source_count
    joins = len(space.join_specs)
    if total_sources <= 1:
        return _record(
            5,
            "Join specifications",
            True,
            ">=1 join when multiple data sources",
            f"{total_sources} data source(s); joins not required",
            severity="pass",
        )
    passed = joins >= 1
    evidence = f"{joins} join spec(s) for {total_sources} data sources"
    if not passed:
        evidence += " - define at least one join"
    return _record(
        5, "Join specifications", passed, ">=1 join when multiple data sources", evidence
    )


def check_06_data_source_count(space: Space) -> dict[str, Any]:
    total = space.data_source_count
    passed = 1 <= total <= 12
    evidence = f"{total} data source(s)"
    if total > 12:
        evidence += " - >12; consider a multi-room architecture"
    elif total == 0:
        evidence += " - none configured"
    return _record(6, "Data source count 1-12", passed, "1 <= data sources <= 12", evidence)


def check_07_example_sqls(space: Space) -> dict[str, Any]:
    examples = space.example_sqls
    n = len(examples)
    passed = n >= 8
    missing_guidance = sum(1 for e in examples if not as_str_list(e.get("usage_guidance")))
    evidence = f"{n} example SQL(s)"
    if not passed:
        severity = "fail"
        evidence += " - need >=8"
    elif n < 10:
        severity = "warning"
        evidence += " - 10-15 is the sweet spot"
    else:
        severity = "pass"
    if n > 0 and missing_guidance > n / 2:
        evidence += f" - advisory: {missing_guidance}/{n} lack usage_guidance"
    return _record(
        7, "8+ example SQLs", passed, ">=8 example question/SQL pairs", evidence, severity
    )


def check_08_sql_snippets(space: Space) -> dict[str, Any]:
    filters = len(space.snippet_filters)
    expressions = len(space.snippet_expressions)
    measures = len(space.snippet_measures)
    functions = len(space.sql_functions)
    total = filters + expressions + measures + functions
    passed = total >= 1
    evidence = (
        f"{filters} filter(s), {measures} measure(s), {expressions} expression(s), "
        f"{functions} function(s)"
    )
    if not passed:
        severity = "fail"
        evidence += " - add at least one reusable SQL snippet"
    elif filters == 0 or measures == 0:
        severity = "warning"
        missing = []
        if filters == 0:
            missing.append("filters")
        if measures == 0:
            missing.append("measures")
        evidence += f" - consider adding {' and '.join(missing)}"
    else:
        severity = "pass"
    return _record(
        8,
        "SQL snippets",
        passed,
        ">=1 filter/expression/measure/function",
        evidence,
        severity,
    )


def check_09_entity_format_matching(space: Space) -> dict[str, Any]:
    matched = [
        c
        for c in space.all_columns()
        if c.enable_entity_matching or c.enable_format_assistance
    ]
    count = len(matched)
    passed = count >= 1
    evidence = f"{count} column(s) with entity/format matching enabled"
    if not passed:
        severity = "fail"
        evidence += " - enable it on at least one categorical column"
    elif count > 120:
        severity = "warning"
        evidence += " - >120 exceeds the value-dictionary cap; excess is ignored"
    elif count > 100:
        severity = "warning"
        evidence += " - approaching the 120-column value-dictionary cap"
    else:
        severity = "pass"
    evidence += " (RLS-tainted tables not evaluated offline)"
    return _record(
        9,
        "Entity/format matching",
        passed,
        ">=1 column with entity/format matching",
        evidence,
        severity,
    )


def check_10_benchmarks(space: Space) -> dict[str, Any]:
    n = len(space.benchmark_questions)
    passed = n >= 10
    evidence = f"{n} benchmark question(s)"
    if not passed:
        evidence += " - need >=10"
    return _record(10, "10+ benchmark questions", passed, ">=10 benchmark questions", evidence)


def check_11_optimization_run(space: Space) -> dict[str, Any]:
    run = space.optimization_run
    passed = isinstance(run, dict) and bool(run)
    if passed:
        status = run.get("status", "present")
        evidence = f"optimization_run present (status={status})"
    else:
        evidence = "No optimization_run found - run an optimization workflow"
    return _record(
        11, "Optimization workflow completed", passed, "an optimization_run exists", evidence
    )


def _accuracy_fraction(run: dict[str, Any]) -> float | None:
    acc = run.get("accuracy")
    if acc is None:
        acc = run.get("optimization_accuracy")
    if not isinstance(acc, (int, float)) or isinstance(acc, bool):
        return None
    # Accept both 0-1 fractions and 0-100 percentages.
    return acc / 100.0 if acc > 1 else float(acc)


def check_12_optimization_accuracy(space: Space) -> dict[str, Any]:
    run = space.optimization_run if isinstance(space.optimization_run, dict) else {}
    frac = _accuracy_fraction(run) if run else None
    passed = frac is not None and frac >= 0.85
    if frac is None:
        evidence = "No optimization accuracy available"
    else:
        evidence = f"optimization accuracy {frac:.0%}"
        if not passed:
            evidence += " - need >=85%"
    return _record(
        12, "Optimization accuracy >= 85%", passed, "accuracy >= 85%", evidence
    )


ALL_CHECKS = (
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
)


def run_all_checks(space: Space) -> list[dict[str, Any]]:
    """Run every check in id order and return the list of records."""
    return [check(space) for check in ALL_CHECKS]
