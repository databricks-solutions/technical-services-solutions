"""TXT report generator for Databricks Terraform Pre-Check."""

from datetime import datetime
from typing import List, Optional, Dict

from checkers.base import CheckReport, CheckResult, CheckStatus


class TxtReporter:
    """Generate TXT reports from check results."""
    
    # Column widths for formatting
    NAME_WIDTH = 45
    STATUS_WIDTH = 10
    LINE_WIDTH = 70
    
    def __init__(self):
        self.reports: List[CheckReport] = []
        self._current_cloud = "AWS"  # Default, updated per report
    
    def add_report(self, report: CheckReport) -> None:
        """Add a report to be included in the output."""
        self.reports.append(report)
    
    def _format_status(self, status: CheckStatus) -> str:
        """Format status with consistent width."""
        return status.value.center(self.STATUS_WIDTH)
    
    def _format_result_line(self, result: CheckResult) -> str:
        """Format a single result line."""
        name = result.name[:self.NAME_WIDTH - 1].ljust(self.NAME_WIDTH - 1)
        status = result.status.value
        
        if result.message:
            return f"  {name} {status} - {result.message}"
        else:
            return f"  {name} {status}"
    
    def _generate_header(self, report: CheckReport) -> str:
        """Generate report header."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * self.LINE_WIDTH
        
        lines = [
            separator,
            "  DATABRICKS TERRAFORM PRE-CHECK REPORT".center(self.LINE_WIDTH),
            f"  Cloud: {report.cloud} | Region: {report.region}".center(self.LINE_WIDTH),
            f"  Date: {now}".center(self.LINE_WIDTH),
            separator,
        ]
        
        if report.account_info:
            lines.insert(-1, f"  {report.account_info}".center(self.LINE_WIDTH))
        
        return "\n".join(lines)
    
    def _collect_problems(self, report: CheckReport) -> Dict[str, List[tuple]]:
        """Collect all problems grouped by type."""
        problems = {
            "permissions": [],  # IAM/permission issues
            "quotas": [],       # Resource quota issues
            "config": [],       # Configuration issues
        }
        
        for category in report.categories:
            for result in category.results:
                if result.status == CheckStatus.NOT_OK:
                    action_name = result.name.strip()
                    
                    # Categorize the problem
                    if "LIMIT" in result.message or "QUOTA" in result.message.upper():
                        problems["quotas"].append((action_name, result.message, category.name))
                    elif "iam:" in action_name.lower() or "DENIED" in result.message:
                        problems["permissions"].append((action_name, result.message, category.name))
                    else:
                        problems["config"].append((action_name, result.message, category.name))
        
        return problems
    
    def _generate_problems_summary(self, report: CheckReport) -> str:
        """Generate a clear summary of all problems found."""
        problems = self._collect_problems(report)
        
        total_problems = sum(len(v) for v in problems.values())
        if total_problems == 0:
            return ""
        
        lines = [
            "",
            "╔" + "═" * (self.LINE_WIDTH - 2) + "╗",
            "║" + " 🚨 PROBLEMS FOUND - ACTION REQUIRED ".center(self.LINE_WIDTH - 2) + "║",
            "╚" + "═" * (self.LINE_WIDTH - 2) + "╝",
            "",
        ]
        
        # Permission problems
        if problems["permissions"]:
            lines.append("┌─────────────────────────────────────────────────────────────────────┐")
            lines.append("│ ❌ PERMISSÕES FALTANDO (Terraform VAI FALHAR nestas etapas)        │")
            lines.append("├─────────────────────────────────────────────────────────────────────┤")
            
            for action, message, category in problems["permissions"]:
                # Extract just the action name
                clean_action = action.replace("📦", "").replace("👤", "").replace("📜", "").replace("🔒", "").strip()
                lines.append(f"│  • {clean_action:<30} │")
            
            lines.append("│                                                                     │")
            lines.append("│  📋 O QUE FAZER:                                                    │")
            if self._current_cloud.upper() == "AZURE":
                lines.append("│     1. Ask your Azure administrator to add the permissions        │")
                lines.append("│     2. Or use a role with Contributor/Owner on the subscription   │")
                lines.append("│     3. Verify you are using the correct subscription              │")
            else:
                lines.append("│     1. Ask your AWS administrator to add the permissions          │")
                lines.append("│     2. Or use a role/user with more privileges                    │")
                lines.append("│     3. See SUGGESTED POLICY at the end of this report             │")
            lines.append("└─────────────────────────────────────────────────────────────────────┘")
            lines.append("")
        
        # Quota problems
        if problems["quotas"]:
            lines.append("┌─────────────────────────────────────────────────────────────────────┐")
            lines.append("│ ⚠️  LIMITES DE QUOTA ATINGIDOS                                      │")
            lines.append("├─────────────────────────────────────────────────────────────────────┤")
            
            for action, message, category in problems["quotas"]:
                clean_action = action.strip()
                lines.append(f"│  • {clean_action}: {message:<40}│")
            
            lines.append("│                                                                     │")
            lines.append("│  📋 O QUE FAZER:                                                    │")
            if self._current_cloud.upper() == "AZURE":
                lines.append("│     1. Go to Azure Portal → Quotas                                 │")
                lines.append("│     2. Request quota increase for the listed resources             │")
                lines.append("│     3. Wait for approval (may take up to 24h)                      │")
            else:
                lines.append("│     1. Go to AWS Console → Service Quotas                          │")
                lines.append("│     2. Request quota increase for the listed resources             │")
                lines.append("│     3. Wait for approval (may take up to 24h)                      │")
            lines.append("└─────────────────────────────────────────────────────────────────────┘")
            lines.append("")
        
        # Config problems
        if problems["config"]:
            lines.append("┌─────────────────────────────────────────────────────────────────────┐")
            lines.append("│ ⚙️  CONFIGURATION PROBLEMS                                           │")
            lines.append("├─────────────────────────────────────────────────────────────────────┤")
            
            for action, message, category in problems["config"]:
                clean_action = action.strip()
                lines.append(f"│  • {clean_action}: {message[:45]:<45}│")
            
            lines.append("└─────────────────────────────────────────────────────────────────────┘")
            lines.append("")
        
        return "\n".join(lines)
    
    def _generate_category(self, name: str, results: List[CheckResult]) -> str:
        """Generate output for a single category."""
        lines = [f"\n[{name}]"]
        
        for result in results:
            lines.append(self._format_result_line(result))
            
            # Add details if present
            if result.details:
                lines.append(f"    {result.details}")
        
        return "\n".join(lines)
    
    def _generate_summary(self, report: CheckReport) -> str:
        """Generate summary section."""
        separator = "=" * self.LINE_WIDTH
        
        summary_parts = []
        
        if report.total_ok > 0:
            summary_parts.append(f"{report.total_ok} OK")
        if report.total_warning > 0:
            summary_parts.append(f"{report.total_warning} WARNING")
        if report.total_not_ok > 0:
            summary_parts.append(f"{report.total_not_ok} NOT OK")
        if report.total_skipped > 0:
            summary_parts.append(f"{report.total_skipped} SKIPPED")
        
        summary = " | ".join(summary_parts)
        
        lines = [
            "",
            separator,
            f"  SUMMARY: {summary}".center(self.LINE_WIDTH),
            separator,
        ]
        
        # Add overall status indicator
        if report.total_not_ok > 0:
            lines.insert(-1, "  STATUS: FAILED - Some checks did not pass".center(self.LINE_WIDTH))
        elif report.total_warning > 0:
            lines.insert(-1, "  STATUS: PASSED WITH WARNINGS".center(self.LINE_WIDTH))
        else:
            lines.insert(-1, "  STATUS: PASSED - All checks successful".center(self.LINE_WIDTH))
        
        return "\n".join(lines)
    
    def _generate_next_steps(self, report: CheckReport) -> str:
        """Generate next steps based on report results."""
        problems = self._collect_problems(report)
        total_problems = sum(len(v) for v in problems.values())
        
        if total_problems == 0:
            return """
╔══════════════════════════════════════════════════════════════════════╗
║  ✅ NEXT STEPS                                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  All checks passed! You can proceed with:                            ║
║                                                                      ║
║    $ terraform init                                                  ║
║    $ terraform plan                                                  ║
║    $ terraform apply                                                 ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""
        else:
            lines = [
                "",
                "╔══════════════════════════════════════════════════════════════════════╗",
                "║  ⛔ NEXT STEPS - FIXES REQUIRED                                       ║",
                "╠══════════════════════════════════════════════════════════════════════╣",
                "║                                                                      ║",
            ]
            
            step = 1
            
            if problems["permissions"]:
                lines.append(f"║  {step}. FIX PERMISSIONS:                                                ║")
                if self._current_cloud.upper() == "AZURE":
                    lines.append("║     • Assign Contributor or Owner role on the subscription           ║")
                    lines.append("║     • Or ask your Azure administrator to add them                    ║")
                else:
                    lines.append("║     • Add the suggested policy (see below) to your user/role         ║")
                    lines.append("║     • Or ask your AWS administrator to add the permissions           ║")
                lines.append("║                                                                      ║")
                step += 1
            
            if problems["quotas"]:
                lines.append(f"║  {step}. INCREASE QUOTAS:                                                ║")
                if self._current_cloud.upper() == "AZURE":
                    lines.append("║     • Azure Portal → Quotas → Request increase                       ║")
                else:
                    lines.append("║     • AWS Console → Service Quotas → Request increase                ║")
                lines.append("║     • Wait for approval before running Terraform                     ║")
                lines.append("║                                                                      ║")
                step += 1
            
            cloud_cmd = "azure" if self._current_cloud.upper() == "AZURE" else "aws"
            lines.append(f"║  {step}. RUN THIS PRE-CHECK AGAIN:                                        ║")
            lines.append(f"║     $ python main.py --cloud {cloud_cmd} [your options]                      ║")
            lines.append("║                                                                      ║")
            step += 1
            
            lines.append(f"║  {step}. ONLY AFTER ALL CHECKS PASS:                                     ║")
            lines.append("║     $ terraform init && terraform plan && terraform apply            ║")
            lines.append("║                                                                      ║")
            lines.append("╚══════════════════════════════════════════════════════════════════════╝")
            
            return "\n".join(lines)
    
    def generate(self, report: Optional[CheckReport] = None) -> str:
        """Generate the complete TXT report."""
        if report:
            reports = [report]
        else:
            reports = self.reports
        
        if not reports:
            return "No reports to generate."
        
        output_parts = []
        
        for report in reports:
            # Set current cloud for context-aware messages
            self._current_cloud = report.cloud
            
            # Header
            output_parts.append(self._generate_header(report))
            
            # Problems summary (before details)
            problems_summary = self._generate_problems_summary(report)
            if problems_summary:
                output_parts.append(problems_summary)
            
            # Categories
            for category in report.categories:
                output_parts.append(
                    self._generate_category(category.name, category.results)
                )
            
            # Summary
            output_parts.append(self._generate_summary(report))
            
            # Next steps
            output_parts.append(self._generate_next_steps(report))
            
            # Add separator between multiple reports
            if len(reports) > 1:
                output_parts.append("\n")
        
        return "\n".join(output_parts)
    
    def save(self, filepath: str, report: Optional[CheckReport] = None) -> None:
        """Save the report to a file."""
        content = self.generate(report)
        with open(filepath, 'w') as f:
            f.write(content)
    
    def generate_all_clouds(self, reports: List[CheckReport]) -> str:
        """Generate a combined report for multiple clouds."""
        if not reports:
            return "No reports to generate."
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * self.LINE_WIDTH
        
        # Combined header
        header_lines = [
            separator,
            "  DATABRICKS TERRAFORM PRE-CHECK REPORT".center(self.LINE_WIDTH),
            "  Multi-Cloud Assessment".center(self.LINE_WIDTH),
            f"  Date: {now}".center(self.LINE_WIDTH),
            separator,
        ]
        
        output_parts = ["\n".join(header_lines)]
        
        # Individual cloud reports
        for report in reports:
            cloud_header = f"\n{'─' * self.LINE_WIDTH}"
            cloud_header += f"\n  {report.cloud.upper()} ({report.region})"
            if report.account_info:
                cloud_header += f"\n  {report.account_info}"
            cloud_header += f"\n{'─' * self.LINE_WIDTH}"
            output_parts.append(cloud_header)
            
            # Categories
            for category in report.categories:
                output_parts.append(
                    self._generate_category(category.name, category.results)
                )
            
            # Mini summary for this cloud
            summary_parts = []
            if report.total_ok > 0:
                summary_parts.append(f"{report.total_ok} OK")
            if report.total_warning > 0:
                summary_parts.append(f"{report.total_warning} WARNING")
            if report.total_not_ok > 0:
                summary_parts.append(f"{report.total_not_ok} NOT OK")
            if report.total_skipped > 0:
                summary_parts.append(f"{report.total_skipped} SKIPPED")
            
            output_parts.append(f"\n  {report.cloud} Summary: {' | '.join(summary_parts)}")
        
        # Combined summary
        total_ok = sum(r.total_ok for r in reports)
        total_warning = sum(r.total_warning for r in reports)
        total_not_ok = sum(r.total_not_ok for r in reports)
        total_skipped = sum(r.total_skipped for r in reports)
        
        summary_parts = []
        if total_ok > 0:
            summary_parts.append(f"{total_ok} OK")
        if total_warning > 0:
            summary_parts.append(f"{total_warning} WARNING")
        if total_not_ok > 0:
            summary_parts.append(f"{total_not_ok} NOT OK")
        if total_skipped > 0:
            summary_parts.append(f"{total_skipped} SKIPPED")
        
        final_summary = [
            "",
            separator,
            f"  OVERALL SUMMARY: {' | '.join(summary_parts)}".center(self.LINE_WIDTH),
        ]
        
        if total_not_ok > 0:
            final_summary.append("  STATUS: FAILED - Some checks did not pass".center(self.LINE_WIDTH))
        elif total_warning > 0:
            final_summary.append("  STATUS: PASSED WITH WARNINGS".center(self.LINE_WIDTH))
        else:
            final_summary.append("  STATUS: PASSED - All checks successful".center(self.LINE_WIDTH))
        
        final_summary.append(separator)
        
        output_parts.append("\n".join(final_summary))
        
        return "\n".join(output_parts)
