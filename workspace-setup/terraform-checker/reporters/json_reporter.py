"""
JSON Reporter for Databricks Permission Pre-Check.

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
        """Lossless — includes remediation, doc_link and the assumed flag."""
        return result.to_dict()

    def _category_to_dict(self, category: CheckCategory) -> Dict[str, Any]:
        """Convert a CheckCategory to a dictionary (+ tri-state area_state)."""
        d = category.to_dict()
        d["area_state"] = category.area_state
        return d
    
    def generate(self, report: CheckReport) -> str:
        """
        Generate JSON report.
        
        Args:
            report: The CheckReport to convert
        
        Returns:
            JSON string
        """
        # Collect failed / warning / skipped checks (lossless: include
        # remediation + assumed so CI/audit consumers can act on them).
        failed_checks = []
        warning_checks = []
        skipped_checks = []

        def _entry(category, result):
            return {
                "category": category.name,
                "check": result.name,
                "message": result.message,
                "remediation": result.remediation,
                "doc_link": result.doc_link,
                "assumed": result.assumed,
            }

        for category in report.categories:
            for result in category.results:
                if result.status == CheckStatus.NOT_OK:
                    failed_checks.append(_entry(category, result))
                elif result.status == CheckStatus.WARNING:
                    warning_checks.append(_entry(category, result))
                elif result.status == CheckStatus.SKIPPED:
                    skipped_checks.append(_entry(category, result))

        # Dedicated sections for the matrix + the explicit "not validated" note.
        def _section(name_fragment):
            cat = next((c for c in report.categories if name_fragment in c.name), None)
            return self._category_to_dict(cat) if cat else None
        compatibility = _section("DEPLOYMENT COMPATIBILITY")
        not_validated = _section("NOT VALIDATED")
        
        # Determine overall status
        if report.total_not_ok > 0:
            overall_status = "FAILED"
        elif report.total_warning > 0:
            overall_status = "WARNING"
        else:
            overall_status = "PASSED"
        
        output = {
            "version": "1.1",
            "timestamp": datetime.now().isoformat(),
            "cloud": report.cloud,
            "region": report.region,
            "account_info": report.account_info,
            "subscription_id": report.subscription_id,
            "project_id": report.project_id,
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
            "skipped_checks": skipped_checks,
            "deployment_compatibility": compatibility,
            "not_validated": not_validated,
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

