"""
Markdown report generator for Databricks Permission Pre-Check.

Designed to be read by the CUSTOMER's cloud admin (not a Databricks engineer):
plain language, a clear verdict up front, an explicit "what to fix" list with
remediation, and the raw detail tucked into a collapsible section at the end.

Render it anywhere Markdown is supported (GitHub, Slack, email, docs) or share
the .md file directly.
"""

from datetime import datetime
from typing import List, Optional

from checkers.base import CheckReport, CheckResult, CheckStatus, CheckCategory


# Plain-language guidance per cloud when a specific remediation isn't attached
# to the check. Keeps the report actionable even before checks populate
# CheckResult.remediation.
_GENERIC_FIX = {
    "aws": (
        "Ask your AWS administrator to grant the missing IAM permission, or "
        "attach the **Suggested IAM policy** generated at the end of the text "
        "report. Then re-run this pre-check."
    ),
    "azure": (
        "Ask your Azure administrator to assign the **Contributor** role (or "
        "**Owner**, if Unity Catalog role assignments are in scope) on the "
        "target subscription/resource group, then re-run this pre-check."
    ),
    "gcp": (
        "Ask your GCP administrator to grant the missing IAM permission or "
        "enable the required API on the project, then re-run this pre-check."
    ),
}

# Icons used for each status in the human-facing summary.
_STATUS_ICON = {
    CheckStatus.OK: "✅",
    CheckStatus.WARNING: "⚠️",
    CheckStatus.NOT_OK: "❌",
    CheckStatus.SKIPPED: "⏭️",
}


class MarkdownReporter:
    """Generate a customer-friendly Markdown report from check results."""

    def __init__(self, lang: str = "en"):
        # lang reserved for future i18n (pt-BR); English is the only locale today.
        self.lang = lang

    # ----- helpers -------------------------------------------------------
    @staticmethod
    def _clean(text: Optional[str]) -> str:
        """Strip decorative icons / status prefixes from a message for prose."""
        if not text:
            return ""
        out = text
        for junk in ("📦", "👤", "📜", "🔒", "🌐", "📁", "🔗", "🗑️", "✓", "✗"):
            out = out.replace(junk, "")
        for prefix in ("DENIED:", "DENIED -", "AUTH ERROR:", "QUOTA:", "CONFIG:", "Error:"):
            if out.strip().startswith(prefix):
                out = out.strip()[len(prefix):]
        return out.strip(" -–—")

    @staticmethod
    def _clean_name(name: Optional[str]) -> str:
        out = name or ""
        for junk in ("📦", "👤", "📜", "🔒", "🌐", "📁", "🔗", "🗑️", "✓", "✗"):
            out = out.replace(junk, "")
        return out.replace("──", "").strip(" -–—│").strip()

    def _verdict(self, report: CheckReport) -> tuple:
        """Return (icon, headline, plain_summary)."""
        if report.total_not_ok > 0:
            return (
                "❌",
                "Action required before deploying",
                (
                    f"We found **{report.total_not_ok} blocker(s)** that will very "
                    "likely make `terraform apply` fail. Fix the items below, then "
                    "run this pre-check again until it passes."
                ),
            )
        if report.total_warning > 0:
            return (
                "⚠️",
                "Ready to deploy — with a few things to review",
                (
                    "No blockers found. Check the **Worth reviewing** items below "
                    "(if any) before deploying; the **Notes** are just context on "
                    "what the pre-check couldn't auto-verify — not action items."
                ),
            )
        return (
            "✅",
            "Ready to deploy",
            "All checks passed. Your environment has the credentials, permissions, "
            "and quotas needed for this deployment.",
        )

    # Categories rendered as their own prominent sections (not folded into the
    # generic fix/notes buckets or the collapsed detail).
    _SPECIAL_CATEGORIES = ("DEPLOYMENT COMPATIBILITY", "NOT VALIDATED")

    def _is_special(self, category_name: str) -> bool:
        return any(s in (category_name or "") for s in self._SPECIAL_CATEGORIES)

    def _collect(self, report: CheckReport, status: CheckStatus) -> List[tuple]:
        """Collect (category, result) pairs with the given status.

        Skips the special categories (compatibility / not-validated) — they get
        dedicated prominent sections instead of being scattered into buckets.
        """
        out = []
        for category in report.categories:
            if self._is_special(category.name):
                continue
            for result in category.results:
                if result.status == status:
                    out.append((category.name, result))
        return out

    def _compatibility_section(self, report: CheckReport) -> List[str]:
        cat = next((c for c in report.categories if "DEPLOYMENT COMPATIBILITY" in c.name), None)
        if not cat:
            return []
        icon = {CheckStatus.OK: "✅", CheckStatus.WARNING: "⚠️", CheckStatus.NOT_OK: "❌"}
        lines = ["## Deployment compatibility", "",
                 "Which deployment types your account is ready for:", "",
                 "| Mode | Status | Detail |", "|---|:---:|---|"]
        for r in cat.results:
            mode = self._clean_name(r.name) or "—"
            msg = (self._clean(r.message) or "").replace("|", "\\|")
            lines.append(f"| {mode} | {icon.get(r.status, '•')} | {msg} |")
        lines.append("")
        return lines

    def _not_validated_section(self, report: CheckReport) -> List[str]:
        cat = next((c for c in report.categories if "NOT VALIDATED" in c.name), None)
        if not cat:
            return []
        lines = ["## ⛔ Not validated by this pre-check", "",
                 "A green result above does **not** guarantee `terraform apply` succeeds — "
                 "these still need checking separately:", ""]
        for r in cat.results:
            name = self._clean_name(r.name) or "—"
            msg = self._clean(r.message) or ""
            lines.append(f"- **{name}** — {msg}")
        lines.append("")
        return lines

    def _fix_block(self, report: CheckReport, results: List[tuple], heading: str,
                   intro: str, generic_fallback: bool = True) -> List[str]:
        """Render action items. generic_fallback=True adds the "ask your admin"
        line when an item has no specific remediation (only right for blockers —
        never slap it on an informational warning)."""
        cloud = (report.cloud or "").lower()
        generic = _GENERIC_FIX.get(cloud, "Ask your cloud administrator to grant the missing access, then re-run.")
        lines = [f"## {heading}", "", intro, ""]
        for _cat, r in results:
            name = self._clean_name(r.name) or "Check"
            lines.append(f"### {name}")
            msg = self._clean(r.message)
            if msg:
                lines.append(f"- **What we saw:** {msg}")
            fix = self._clean(r.remediation) or (generic if generic_fallback else "")
            if fix:
                lines.append(f"- **How to fix:** {fix}")
            if r.doc_link:
                lines.append(f"- **Docs:** {r.doc_link}")
            lines.append("")
        return lines

    def _notes_block(self, results: List[tuple]) -> List[str]:
        """Informational items — tool limitations / context, NOT action items.
        Rendered as plain bullets so they don't read as scary 'fix this' tasks."""
        lines = ["## ℹ️ Notes (no action needed)", "",
                 "Context about what the pre-check could and couldn't auto-verify:", ""]
        for _cat, r in results:
            name = self._clean_name(r.name) or "Note"
            msg = self._clean(r.message)
            lines.append(f"- **{name}** — {msg}" if msg else f"- {name}")
        lines.append("")
        return lines

    def _next_steps(self, report: CheckReport) -> List[str]:
        cloud = (report.cloud or "aws").lower()
        rerun = f"python main.py --cloud {cloud} [your options]"
        if report.total_not_ok > 0:
            return [
                "## Next steps",
                "",
                "1. Apply the fixes listed above with your cloud administrator.",
                f"2. Re-run the pre-check: `{rerun}`",
                "3. Once it reports **Ready to deploy**, proceed with "
                "`terraform init && terraform plan && terraform apply`.",
                "",
            ]
        if report.total_warning > 0:
            return [
                "## Next steps",
                "",
                "1. Review the warnings above (commonly quota increases — these can "
                "take up to 24h to approve).",
                "2. Proceed with `terraform init && terraform plan && terraform apply` "
                "when ready.",
                "",
            ]
        return [
            "## Next steps",
            "",
            "You're clear to deploy:",
            "",
            "```bash",
            "terraform init",
            "terraform plan",
            "terraform apply",
            "```",
            "",
        ]

    def _detail(self, report: CheckReport) -> List[str]:
        lines = ["<details>", "<summary>Full check detail (all categories)</summary>", ""]
        for category in report.categories:
            if self._is_special(category.name):
                continue  # already shown as a prominent section
            lines.append(f"### {category.name}")
            lines.append("")
            lines.append("| Status | Check | Detail |")
            lines.append("|:---:|---|---|")
            for r in category.results:
                icon = _STATUS_ICON.get(r.status, "•")
                name = self._clean_name(r.name) or "—"
                msg = (self._clean(r.message) or "").replace("|", "\\|")
                lines.append(f"| {icon} | {name} | {msg} |")
            lines.append("")
        lines.append("</details>")
        lines.append("")
        return lines

    # ----- public API ----------------------------------------------------
    def generate(self, report: CheckReport) -> str:
        icon, headline, summary = self._verdict(report)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        meta = f"**Cloud:** {report.cloud} · **Region:** {report.region}"
        if report.account_info:
            meta += f" · {report.account_info}"
        if report.subscription_id:
            meta += f" · **Subscription:** {report.subscription_id}"
        if report.project_id:
            meta += f" · **Project:** {report.project_id}"

        lines = [
            "# Databricks Deployment Pre-Check — Report",
            "",
            meta,
            f"**Generated:** {now}",
            "",
            f"## {icon} Result: {headline}",
            "",
            f"> {summary}",
            "",
            "| Passed | Warnings | Blockers | Skipped |",
            "|:---:|:---:|:---:|:---:|",
            f"| ✅ {report.total_ok} | ⚠️ {report.total_warning} | "
            f"❌ {report.total_not_ok} | ⏭️ {report.total_skipped} |",
            "",
        ]

        # Prominent: which modes are viable + what we couldn't validate.
        lines += self._compatibility_section(report)

        blockers = self._collect(report, CheckStatus.NOT_OK)
        if blockers:
            lines += self._fix_block(
                report, blockers,
                "🔧 What you need to fix",
                "These will block the deployment. Each item shows what we observed "
                "and how to resolve it.",
            )

        # Split warnings: items with a concrete remediation are real "review"
        # action items; the rest are informational notes (tool couldn't verify,
        # scope hints, expected verify-only messages) — never scary fixes.
        warnings = self._collect(report, CheckStatus.WARNING)
        review = [(c, r) for c, r in warnings if (r.remediation or "").strip()]
        notes = [(c, r) for c, r in warnings if not (r.remediation or "").strip()]
        if review:
            lines += self._fix_block(
                report, review,
                "👀 Worth reviewing",
                "Not blockers, but recommended to check before deploying.",
                generic_fallback=False,
            )
        if notes:
            lines += self._notes_block(notes)

        lines += self._not_validated_section(report)
        lines += self._next_steps(report)
        lines += self._detail(report)

        lines += [
            "---",
            "",
            "_This pre-check runs in your own cloud account. On AWS/Azure it creates "
            "and immediately deletes small, clearly-tagged temporary resources "
            "(prefixed `dbx-precheck-temp-*` / `dbxprecheck-*`) to prove permissions "
            "empirically; on GCP it is read-only. Run `--cleanup-orphans` to confirm "
            "nothing was left behind._",
        ]
        return "\n".join(lines)

    def generate_all_clouds(self, reports: List[CheckReport]) -> str:
        if not reports:
            return "# Databricks Deployment Pre-Check\n\nNo reports to generate."
        parts = ["# Databricks Deployment Pre-Check — Multi-Cloud Report", ""]
        total_blockers = sum(r.total_not_ok for r in reports)
        total_warn = sum(r.total_warning for r in reports)
        if total_blockers:
            parts.append(f"## ❌ {total_blockers} blocker(s) across {len(reports)} cloud(s)")
        elif total_warn:
            parts.append(f"## ⚠️ Ready with {total_warn} warning(s) across {len(reports)} cloud(s)")
        else:
            parts.append(f"## ✅ All {len(reports)} cloud(s) ready to deploy")
        parts.append("")
        for report in reports:
            parts.append(self.generate(report))
            parts.append("\n---\n")
        return "\n".join(parts)

    def save(self, filepath: str, report: CheckReport) -> None:
        with open(filepath, "w") as f:
            f.write(self.generate(report))
