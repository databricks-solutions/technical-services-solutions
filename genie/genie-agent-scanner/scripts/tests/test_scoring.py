"""Score totals and 3-tier maturity boundaries (incl. the two headline fixtures)."""

from __future__ import annotations

from genie_space_iq import scan_space
from genie_space_iq.checks import run_all_checks
from genie_space_iq.model import Space
from genie_space_iq.scoring import (
    TIER_NOT_READY,
    TIER_READY,
    TIER_TRUSTED,
    calculate_score,
    get_maturity_label,
)


def _checks(passed_ids: set[int]):
    return [
        {"id": i, "passed": i in passed_ids, "severity": "pass" if i in passed_ids else "fail"}
        for i in range(1, 13)
    ]


def test_score_is_count_of_passed():
    assert calculate_score(_checks({1, 2, 3})) == 3
    assert calculate_score(_checks(set(range(1, 13)))) == 12


def test_tier_trusted_requires_all_12():
    assert get_maturity_label(_checks(set(range(1, 13)))) == TIER_TRUSTED


def test_tier_ready_when_config_passes_but_optimization_missing():
    # Checks 1-10 pass, 11-12 fail -> Ready to Optimize.
    assert get_maturity_label(_checks(set(range(1, 11)))) == TIER_READY


def test_tier_not_ready_when_a_config_check_fails():
    # 11 & 12 pass but a config check (5) fails -> Not Ready.
    passed = set(range(1, 13)) - {5}
    assert get_maturity_label(_checks(passed)) == TIER_NOT_READY


def test_high_quality_fixture_is_trusted_12(load_fixture):
    report = scan_space(load_fixture("high_quality.json"))
    assert report["score"] == 12
    assert report["total"] == 12
    assert report["maturity"] == TIER_TRUSTED
    assert report["findings"] == []


def test_low_quality_fixture_is_sub_12_not_ready(load_fixture):
    report = scan_space(load_fixture("low_quality.json"))
    assert report["score"] < 12
    assert report["score"] == 2
    assert report["maturity"] == TIER_NOT_READY


def test_scan_is_deterministic(load_fixture):
    doc = load_fixture("high_quality.json")
    assert scan_space(doc) == scan_space(doc)


def test_config_only_scan_tops_out_at_ready(load_fixture):
    # High-quality space WITHOUT the optimization_run -> config perfect, 10/12.
    doc = load_fixture("high_quality.json")
    checks = run_all_checks(Space.from_document(doc["serialized_space"]))
    assert calculate_score(checks) == 10
    assert get_maturity_label(checks) == TIER_READY
