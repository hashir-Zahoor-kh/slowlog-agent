import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from slowlog_agent.schemas import (
    AnalysisReport,
    Finding,
    QueryDigest,
    QueryPattern,
    SlowQueryEntry,
    export_json_schema,
)


def test_slow_query_entry_valid() -> None:
    entry = SlowQueryEntry(
        timestamp=datetime(2026, 7, 15, 4, 12, 33),
        user="app",
        host="10.0.1.5",
        query_time=12.4,
        lock_time=0.001,
        rows_sent=3,
        rows_examined=4400312,
        sql="SELECT * FROM orders WHERE customer_email LIKE '%gmail%'",
    )
    assert entry.query_time == 12.4


def test_slow_query_entry_defaults_lock_time_and_rows_sent() -> None:
    entry = SlowQueryEntry(
        timestamp=datetime(2026, 7, 15, 4, 12, 33),
        user="app",
        host="10.0.1.5",
        query_time=1.0,
        rows_examined=10,
        sql="SELECT 1",
    )
    assert entry.lock_time == 0.0
    assert entry.rows_sent == 0


def test_slow_query_entry_rejects_negative_query_time() -> None:
    with pytest.raises(ValidationError):
        SlowQueryEntry(
            timestamp=datetime(2026, 7, 15, 4, 12, 33),
            user="app",
            host="10.0.1.5",
            query_time=-1.0,
            rows_examined=10,
            sql="SELECT 1",
        )


def test_query_digest_round_trips_to_prompt_json() -> None:
    digest = QueryDigest(
        patterns=[
            QueryPattern(
                fingerprint="select * from orders where customer_email = ?",
                example_sql="SELECT * FROM orders WHERE customer_email LIKE '%gmail%'",
                count=42,
                total_time=520.5,
                max_time=30.2,
                p95_time=25.0,
                avg_rows_examined=4400312.0,
                avg_rows_sent=3.0,
            )
        ],
        total_entries=50,
        parse_skipped=2,
        window_start=datetime(2026, 7, 14, 0, 0, 0),
        window_end=datetime(2026, 7, 15, 0, 0, 0),
    )
    payload = json.loads(digest.to_prompt_json())
    assert payload["total_entries"] == 50
    assert payload["patterns"][0]["count"] == 42


def test_finding_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        Finding(
            fingerprint="x",
            severity="urgent",  # type: ignore[arg-type]
            problem="p",
            evidence="e",
            recommendation="r",
            estimated_impact="i",
        )


def test_finding_suggested_ddl_defaults_to_none() -> None:
    finding = Finding(
        fingerprint="x",
        severity="high",
        problem="p",
        evidence="e",
        recommendation="r",
        estimated_impact="i",
    )
    assert finding.suggested_ddl is None


def test_analysis_report_valid() -> None:
    report = AnalysisReport(
        findings=[],
        summary="No significant issues found.",
        analyzed_patterns=0,
        db_verified=False,
    )
    assert report.db_verified is False


def test_export_json_schema_is_valid_json_with_expected_keys() -> None:
    schema = json.loads(export_json_schema())
    assert schema["title"] == "AnalysisReport"
    assert "findings" in schema["properties"]
    assert "db_verified" in schema["properties"]
