"""Orchestration-level tests for main.py (review H6 + H10 + M11).

Covers behaviour that previously had no coverage:
  - H6: a cloud whose SDK import fails must surface as a NOT_OK report, never be
    silently dropped (which let ``--all`` exit 0 with a cloud unevaluated).
  - M11: the exit-code mapping (extracted to ``_compute_exit_code``).
  - H10: ``skip_cleanup`` is parsed from the config file.
"""

import main
from main import _compute_exit_code
from checkers.base import CheckReport
from utils import ExitCode
from utils.config_loader import PreCheckConfig


# --- H6: a missing SDK must be surfaced as NOT_OK, not dropped ---------------

def test_import_error_surfaces_as_not_ok_report(monkeypatch):
    class _BoomChecker:
        def __init__(self, *args, **kwargs):
            raise ImportError("azure-mgmt-network is not installed")

    monkeypatch.setattr(main, "AzureChecker", _BoomChecker)
    report = main.run_azure_checks("eastus", "sub-1", None)

    assert isinstance(report, CheckReport)   # NOT None
    assert report.total_not_ok > 0           # counted as a blocker -> non-zero exit


# --- M11: exit-code mapping is now a pure, unit-tested helper ----------------

def test_exit_code_blocker():
    assert _compute_exit_code(1, 0, 0, strict=False) == ExitCode.PERMISSION_DENIED


def test_exit_code_blocker_outranks_strict():
    assert _compute_exit_code(2, 5, 5, strict=True) == ExitCode.PERMISSION_DENIED


def test_exit_code_strict_warning():
    assert _compute_exit_code(0, 3, 0, strict=True) == ExitCode.GENERAL_ERROR


def test_exit_code_strict_not_verified():
    assert _compute_exit_code(0, 0, 2, strict=True) == ExitCode.GENERAL_ERROR


def test_exit_code_non_strict_warning_is_success():
    assert _compute_exit_code(0, 9, 9, strict=False) == ExitCode.SUCCESS


def test_exit_code_clean():
    assert _compute_exit_code(0, 0, 0, strict=False) == ExitCode.SUCCESS


# --- H10: skip_cleanup is parsed from the config file (then applied in main) --

def test_config_skip_cleanup_is_parsed():
    assert PreCheckConfig.from_dict({"skip_cleanup": True}).skip_cleanup is True
    assert PreCheckConfig.from_dict({}).skip_cleanup is False
