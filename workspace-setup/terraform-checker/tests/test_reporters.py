"""Tests for report generators."""

import json
import pytest

from checkers.base import CheckReport, CheckCategory, CheckResult, CheckStatus
from reporters.json_reporter import JsonReporter


class TestJsonReporter:
    """Tests for JSON reporter."""
    
    @pytest.fixture
    def sample_report(self) -> CheckReport:
        """Create a sample report for testing."""
        report = CheckReport(cloud="AWS", region="us-east-1")
        report.account_info = "123456789012"
        
        # Add a passing category
        cat1 = CheckCategory(name="Credentials")
        cat1.add_result(CheckResult(
            name="AWS Access Key",
            status=CheckStatus.OK,
            message="Valid"
        ))
        cat1.add_result(CheckResult(
            name="AWS Region",
            status=CheckStatus.OK,
            message="us-east-1"
        ))
        report.add_category(cat1)
        
        # Add a category with failures
        cat2 = CheckCategory(name="Permissions")
        cat2.add_result(CheckResult(
            name="iam:CreateRole",
            status=CheckStatus.OK,
            message="Allowed"
        ))
        cat2.add_result(CheckResult(
            name="ec2:CreateVpc",
            status=CheckStatus.NOT_OK,
            message="DENIED"
        ))
        cat2.add_result(CheckResult(
            name="s3:CreateBucket",
            status=CheckStatus.WARNING,
            message="Quota near limit"
        ))
        report.add_category(cat2)
        
        return report
    
    def test_generate_json(self, sample_report):
        """Test generating JSON output."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        
        # Should be valid JSON
        data = json.loads(output)
        
        assert data["cloud"] == "AWS"
        assert data["region"] == "us-east-1"
        assert data["account_info"] == "123456789012"
    
    def test_generate_pretty_json(self, sample_report):
        """Test generating pretty JSON output."""
        reporter = JsonReporter(pretty=True)
        output = reporter.generate(sample_report)
        
        # Should have indentation
        assert "\n" in output
        assert "  " in output
        
        # Should still be valid JSON
        data = json.loads(output)
        assert data["cloud"] == "AWS"
    
    def test_summary_counts(self, sample_report):
        """Test that summary counts are correct."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        data = json.loads(output)
        
        summary = data["summary"]
        assert summary["passed"] == 3  # 2 OK in cat1 + 1 OK in cat2
        assert summary["failed"] == 1  # 1 NOT_OK in cat2
        assert summary["warnings"] == 1  # 1 WARNING in cat2
    
    def test_status_failed(self, sample_report):
        """Test that overall status is FAILED when there are failures."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        data = json.loads(output)
        
        assert data["status"] == "FAILED"
    
    def test_status_passed(self):
        """Test that overall status is PASSED when no failures."""
        report = CheckReport(cloud="AWS", region="us-east-1")
        cat = CheckCategory(name="Credentials")
        cat.add_result(CheckResult(
            name="Test",
            status=CheckStatus.OK,
            message="OK"
        ))
        report.add_category(cat)
        
        reporter = JsonReporter()
        output = reporter.generate(report)
        data = json.loads(output)
        
        assert data["status"] == "PASSED"
    
    def test_failed_checks_list(self, sample_report):
        """Test that failed checks are listed."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        data = json.loads(output)
        
        failed = data["failed_checks"]
        assert len(failed) == 1
        assert failed[0]["check"] == "ec2:CreateVpc"
        assert failed[0]["category"] == "Permissions"
    
    def test_warning_checks_list(self, sample_report):
        """Test that warning checks are listed."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        data = json.loads(output)
        
        warnings = data["warning_checks"]
        assert len(warnings) == 1
        assert warnings[0]["check"] == "s3:CreateBucket"
    
    def test_generate_minimal(self, sample_report):
        """Test generating minimal JSON output."""
        reporter = JsonReporter()
        output = reporter.generate_minimal(sample_report)
        data = json.loads(output)
        
        assert data["cloud"] == "AWS"
        assert data["passed"] is False
        assert data["failed_count"] == 1
        assert data["warning_count"] == 1
    
    def test_categories_in_output(self, sample_report):
        """Test that categories are properly structured."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        data = json.loads(output)
        
        categories = data["categories"]
        assert len(categories) == 2
        
        creds = categories[0]
        assert creds["name"] == "Credentials"
        assert len(creds["results"]) == 2
        assert creds["summary"]["ok"] == 2
    
    def test_version_and_timestamp(self, sample_report):
        """Test that version and timestamp are included."""
        reporter = JsonReporter()
        output = reporter.generate(sample_report)
        data = json.loads(output)
        
        assert "version" in data
        assert "timestamp" in data
        assert data["version"] == "1.0"

