"""Workbench parity: the captured Meridian space must score 7/12 with the
exact per-check breakdown the Genie Workbench app produces.

Fixtures were captured live (read-only) from space
``01f19b352ad81adc9c7fa1bfea5e5835`` (profile ``genie_demo``):

* ``meridian_serialized_space.json`` -- the raw serialized_space.
* ``meridian_uc_metadata.json``      -- full-table-name -> UC metadata
  ``{comment, table_type, columns:[{name, comment}]}``.

The oracle (per-check): id -> (passed, severity_matcher, evidence_substring).
``severity_matcher`` is a set of acceptable severities (check 4 is WARN *or*
PASS in the Workbench, and either still counts as passing).
"""

from __future__ import annotations

from genie_space_iq import scan_space

MERIDIAN_SPACE_ID = "01f19b352ad81adc9c7fa1bfea5e5835"

# id: (passed, {allowed severities}, evidence substring)
ORACLE: dict[int, tuple[bool, set[str], str]] = {
    1: (True, {"pass"}, "6 table(s), 1 metric view(s)"),
    2: (True, {"pass"}, "6/6 tables have descriptions (100%)"),
    3: (False, {"fail"}, "0/0 configured columns have descriptions (0%)"),
    4: (True, {"warning", "pass"}, "2505 chars"),
    5: (True, {"pass"}, "4 join spec(s) for 7 data sources"),
    6: (True, {"pass"}, "7 data source(s)"),
    7: (True, {"pass", "warning"}, "53 example SQL(s)"),
    8: (False, {"fail"}, "add at least one reusable SQL snippet"),
    9: (False, {"fail"}, "0 column(s) with entity/format matching enabled"),
    10: (True, {"pass"}, "16 benchmark question(s)"),
    11: (False, {"fail"}, "No optimization_run found"),
    12: (False, {"fail"}, "No optimization accuracy available"),
}

EXPECTED_TOTAL = 7


def _meridian_report(load_fixture):
    return scan_space(
        load_fixture("meridian_serialized_space.json"),
        uc_metadata=load_fixture("meridian_uc_metadata.json"),
        space_id=MERIDIAN_SPACE_ID,
    )


def test_meridian_scores_seven_of_twelve(load_fixture):
    report = _meridian_report(load_fixture)
    assert report["score"] == EXPECTED_TOTAL
    assert report["total"] == 12
    assert report["uc_available"] is True


def test_meridian_per_check_breakdown(load_fixture, capsys):
    report = _meridian_report(load_fixture)
    by_id = {c["id"]: c for c in report["checks"]}

    # Print the full breakdown so `pytest -s` shows the parity table verbatim.
    with capsys.disabled():
        print(f"\nMeridian parity: {report['score']}/{report['total']} "
              f"(maturity: {report['maturity']}, uc_available: {report['uc_available']})")
        for cid in sorted(by_id):
            c = by_id[cid]
            tag = "PASS" if c["passed"] else "FAIL"
            print(f"  {cid:>2}  {tag}  [{c['severity']:<7}]  {c['evidence']}")

    assert sorted(by_id) == list(range(1, 13))
    for cid, (passed, severities, substring) in ORACLE.items():
        check = by_id[cid]
        assert check["passed"] is passed, f"check {cid} passed mismatch: {check}"
        assert check["severity"] in severities, f"check {cid} severity mismatch: {check}"
        assert substring in check["evidence"], f"check {cid} evidence mismatch: {check}"

    # The passing set is exactly {1, 2, 4, 5, 6, 7, 10}.
    passing = sorted(cid for cid, c in by_id.items() if c["passed"])
    assert passing == [1, 2, 4, 5, 6, 7, 10]


def test_meridian_scan_is_deterministic(load_fixture):
    a = _meridian_report(load_fixture)
    b = _meridian_report(load_fixture)
    assert a == b
