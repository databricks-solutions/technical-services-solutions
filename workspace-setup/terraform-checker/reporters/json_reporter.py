"""
JSON Reporter for Databricks Terraform Pre-Check.

Produces machine-readable JSON output for CI/CD pipelines.
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from checkers.base import CheckReport, CheckStatus, CheckCategory, CheckResult


class JsonReporter:
    """Reporter that produces JSON output for CI/CD integration."""
    
    def __init__(self, pretty: bool = False):
        """
        Initialize JSON reporter.
        
        Args:
            pretty: If True, output formatted JSON with indentation
        """
        self.pretty = pretty
    
    def _result_to_dict(self, result: CheckResult) -> Dict[str, Any]:
        """Convert a CheckResult to a dictionary."""
        return {
            "name": result.name,
            "status": result.status.value,
            "message": result.message,
            "details": result.details,
        }
    
    def _category_to_dict(self, category: CheckCategory) -> Dict[str, Any]:
        """Convert a CheckCategory to a dictionary."""
        return {
            "name": category.name,
            "results": [self._result_to_dict(r) for r in category.results],
            "summary": {
                "ok": category.ok_count,
                "warning": category.warning_count,
                "not_ok": category.not_ok_count,
                "skipped": category.skipped_count,
            }
        }
    
    def generate(self, report: CheckReport) -> str:
        """
        Generate JSON report.
        
        Args:
            report: The CheckReport to convert
        
        Returns:
            JSON string
        """
        # Collect all failed checks
        failed_checks = []
        warning_checks = []
        
        for category in report.categories:
            for result in category.results:
                if result.status == CheckStatus.NOT_OK:
                    failed_checks.append({
                        "category": category.name,
                        "check": result.name,
                        "message": result.message,
                    })
                elif result.status == CheckStatus.WARNING:
                    warning_checks.append({
                        "category": category.name,
                        "check": result.name,
                        "message": result.message,
                    })
        
        # Determine overall status
        if report.total_not_ok > 0:
            overall_status = "FAILED"
        elif report.total_warning > 0:
            overall_status = "WARNING"
        else:
            overall_status = "PASSED"
        
        output = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "cloud": report.cloud,
            "region": report.region,
            "account_info": report.account_info,
            "status": overall_status,
            "summary": {
                "total_checks": (
                    report.total_ok + 
                    report.total_warning + 
                    report.total_not_ok + 
                    report.total_skipped
                ),
                "passed": report.total_ok,
                "warnings": report.total_warning,
                "failed": report.total_not_ok,
                "skipped": report.total_skipped,
            },
            "failed_checks": failed_checks,
            "warning_checks": warning_checks,
            "categories": [
                self._category_to_dict(c) for c in report.categories
            ],
        }
        
        if self.pretty:
            return json.dumps(output, indent=2)
        else:
            return json.dumps(output)
    
    def generate_minimal(self, report: CheckReport) -> str:
        """
        Generate minimal JSON with just pass/fail status.
        
        Useful for quick CI checks.
        """
        output = {
            "cloud": report.cloud,
            "passed": report.total_not_ok == 0,
            "failed_count": report.total_not_ok,
            "warning_count": report.total_warning,
        }
        return json.dumps(output)

