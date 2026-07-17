"""Render an AnalysisReport (plus the digest it was computed from) as Markdown."""

from __future__ import annotations

from datetime import datetime

from slowlog_agent.schemas import AnalysisReport, QueryDigest

_SEVERITY_LABEL = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}


def render_markdown(report: AnalysisReport, digest: QueryDigest, *, generated_at: datetime) -> str:
    lines: list[str] = []
    lines.append("# Slow Query Analysis Report")
    lines.append("")
    lines.append(f"- **Generated:** {generated_at.isoformat()}")
    lines.append(
        f"- **Window:** {digest.window_start.isoformat()} to {digest.window_end.isoformat()}"
    )
    lines.append(
        f"- **Log entries parsed:** {digest.total_entries} "
        f"({digest.parse_skipped} skipped during parsing)"
    )
    lines.append(f"- **Patterns analyzed:** {report.analyzed_patterns}")
    lines.append(f"- **DB-verified (EXPLAIN executed):** {'Yes' if report.db_verified else 'No'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(report.summary)
    lines.append("")

    if not report.findings:
        lines.append("No findings were reported for this window.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Findings")
    lines.append("")
    lines.append("| # | Severity | Fingerprint | Problem |")
    lines.append("|---|---|---|---|")
    for i, finding in enumerate(report.findings, start=1):
        lines.append(
            f"| {i} | {_SEVERITY_LABEL[finding.severity]} | `{finding.fingerprint}` "
            f"| {finding.problem} |"
        )
    lines.append("")

    lines.append("## Details")
    lines.append("")
    for i, finding in enumerate(report.findings, start=1):
        lines.append(f"### {i}. [{_SEVERITY_LABEL[finding.severity]}] {finding.fingerprint}")
        lines.append("")
        lines.append(f"**Problem:** {finding.problem}")
        lines.append("")
        lines.append(f"**Evidence:** {finding.evidence}")
        lines.append("")
        lines.append(f"**Recommendation:** {finding.recommendation}")
        lines.append("")
        if finding.suggested_ddl:
            lines.append("**Suggested DDL:**")
            lines.append("")
            lines.append("```sql")
            lines.append(finding.suggested_ddl)
            lines.append("```")
            lines.append("")
        lines.append(f"**Estimated impact:** {finding.estimated_impact}")
        lines.append("")

    return "\n".join(lines)
