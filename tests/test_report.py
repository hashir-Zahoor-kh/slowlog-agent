from datetime import datetime
from pathlib import Path

from slowlog_agent.report import render_markdown
from slowlog_agent.schemas import AnalysisReport, Finding, QueryDigest, QueryPattern

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "expected_report.md"


def _digest() -> QueryDigest:
    return QueryDigest(
        patterns=[
            QueryPattern(
                fingerprint="select * from orders where customer_email = ?",
                example_sql="SELECT * FROM orders WHERE customer_email = 'a@x.com'",
                count=42,
                total_time=520.5,
                max_time=30.2,
                p95_time=25.0,
                avg_rows_examined=4400312.0,
                avg_rows_sent=3.0,
            ),
            QueryPattern(
                fingerprint="select * from orders where status = ?",
                example_sql="SELECT * FROM orders WHERE status = 'pending'",
                count=10,
                total_time=80.0,
                max_time=12.0,
                p95_time=11.0,
                avg_rows_examined=120000.0,
                avg_rows_sent=5.0,
            ),
        ],
        total_entries=54,
        parse_skipped=2,
        window_start=datetime(2026, 7, 15, 0, 0, 0),
        window_end=datetime(2026, 7, 16, 0, 0, 0),
    )


def _report() -> AnalysisReport:
    return AnalysisReport(
        findings=[
            Finding(
                fingerprint="select * from orders where customer_email = ?",
                severity="critical",
                problem="Full table scan on orders.customer_email for a high-frequency pattern.",
                evidence=(
                    "EXPLAIN shows type=ALL, key=NULL, rows=4400312 for this "
                    "pattern's example query."
                ),
                recommendation="Add a secondary index on orders(customer_email).",
                suggested_ddl="CREATE INDEX idx_orders_customer_email ON orders (customer_email);",
                estimated_impact="Rows examined should drop from ~4.4M to a handful per query.",
            ),
            Finding(
                fingerprint="select * from orders where status = ?",
                severity="medium",
                problem="Moderate scan volume on orders.status without an index.",
                evidence="digest stats: avg_rows_examined=120000.0, avg_rows_sent=5.0, count=10",
                recommendation=(
                    "Consider a composite index on orders(status, created_at) "
                    "if this pattern grows."
                ),
                suggested_ddl=None,
                estimated_impact="Minor latency improvement; not urgent at current volume.",
            ),
        ],
        summary=(
            "One critical full-table-scan pattern dominates this window; "
            "a single index resolves it."
        ),
        analyzed_patterns=2,
        db_verified=True,
    )


def test_render_markdown_matches_golden_file() -> None:
    text = render_markdown(_report(), _digest(), generated_at=datetime(2026, 7, 16, 12, 0, 0))

    assert text == FIXTURE_PATH.read_text()


def test_render_markdown_omits_ddl_block_when_none() -> None:
    text = render_markdown(_report(), _digest(), generated_at=datetime(2026, 7, 16, 12, 0, 0))

    medium_section = text.split("### 2.")[1]
    assert "Suggested DDL" not in medium_section


def test_render_markdown_handles_no_findings() -> None:
    report = AnalysisReport(
        findings=[], summary="No significant issues found.", analyzed_patterns=0, db_verified=False
    )

    text = render_markdown(report, _digest(), generated_at=datetime(2026, 7, 16, 12, 0, 0))

    assert "No findings were reported" in text
    assert "## Findings" not in text
    assert "## Details" not in text


def test_render_markdown_includes_db_verified_status() -> None:
    unverified = AnalysisReport(findings=[], summary="s", analyzed_patterns=0, db_verified=False)
    text = render_markdown(unverified, _digest(), generated_at=datetime(2026, 7, 16, 12, 0, 0))

    assert "DB-verified (EXPLAIN executed):** No" in text
