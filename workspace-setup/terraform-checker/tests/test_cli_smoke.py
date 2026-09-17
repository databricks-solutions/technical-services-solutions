"""Smoke tests for the CLI entry point and output-format wiring.

These guard two regressions found in review:
  1. The packaged entry point pointed at a symbol that didn't exist
     (`main:cli`), so `dbx-precheck` failed to start.
  2. `--dry-run` was AWS-only and `--format markdown` did not exist.
"""

import json

from click.testing import CliRunner

import main as main_module
from checkers.base import CheckCategory, CheckReport, CheckResult, CheckStatus
from cli import cli
from main import main


def _successful_report() -> CheckReport:
    report = CheckReport(cloud="AWS", region="us-east-1")
    category = CheckCategory(name="CREDENTIALS")
    category.add_result(CheckResult(
        name="Credential check",
        status=CheckStatus.OK,
        message="Valid credentials",
    ))
    report.add_category(category)
    return report


def test_entry_point_symbol_exists():
    # main:main is the packaged entry point — must be importable and a Click command.
    import click

    assert callable(main)
    assert isinstance(main, click.Command)
    # cli is the auxiliary command group (completion/init-config/doctor).
    assert hasattr(cli, "commands")  # it's a click.Group


def test_help_runs():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Pre-Check" in result.output
    # honesty: help must not claim it creates nothing
    assert "without creating any resources" not in result.output


def test_dry_run_is_cloud_aware_gcp():
    result = CliRunner().invoke(main, ["--cloud", "gcp", "--dry-run"])
    assert result.exit_code == 0
    assert "READ-ONLY" in result.output


def test_dry_run_is_cloud_aware_azure():
    result = CliRunner().invoke(main, ["--cloud", "azure", "--dry-run"])
    assert result.exit_code == 0
    assert "Resource Group" in result.output


def test_format_flag_accepts_markdown():
    # Should not error on parsing the flag (dry-run exits before any cloud calls).
    result = CliRunner().invoke(main, ["--cloud", "aws", "--format", "markdown", "--dry-run"])
    assert result.exit_code == 0


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "1.2.0" in result.output


def test_progress_goes_to_stderr_not_stdout(capsys):
    # Progress/status must never pollute stdout — keeps --json parseable and the
    # Markdown report clean when stdout is piped to a file or a CI step.
    from main import _progress

    _progress("hello-progress")
    captured = capsys.readouterr()
    assert "hello-progress" in captured.err
    assert "hello-progress" not in captured.out


def test_format_json_is_parseable_without_quiet(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "run_aws_checks",
        lambda *args, **kwargs: (_successful_report(), None),
    )

    result = CliRunner().invoke(main, ["--cloud", "aws", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["cloud"] == "AWS"
    assert "DATABRICKS TERRAFORM PRE-CHECK" not in result.stdout


def test_quiet_suppresses_progress(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "run_aws_checks",
        lambda *args, **kwargs: (_successful_report(), None),
    )

    result = CliRunner().invoke(main, ["--cloud", "aws", "--json", "--quiet"])

    assert result.exit_code == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["cloud"] == "AWS"


def test_cleanup_orphans_gcp_is_read_only_message():
    # GCP creates nothing, so cleanup must say so (not falsely "Cleanup complete").
    result = CliRunner().invoke(main, ["--cleanup-orphans", "--cloud", "gcp"])
    assert result.exit_code == 0
    assert "read-only" in result.output
    assert "nothing to clean up" in result.output
