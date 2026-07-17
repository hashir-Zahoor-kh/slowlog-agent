"""Analyzer tests: shared retry/validation/dump logic, parametrized over both real backends.

Backend-specific concerns (exact argv construction, schema tempfile handling,
envelope/fence extraction) live in tests/test_backends_claude.py and
tests/test_backends_copilot.py. Both backends route their subprocess call
through `slowlog_agent.backends._process.run_agent_subprocess`, so mocking
that one call site is enough to drive either backend end-to-end here.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from slowlog_agent.analyzer import analyze, render_prompt
from slowlog_agent.backends import get_backend
from slowlog_agent.errors import AgentError
from slowlog_agent.schemas import QueryDigest, QueryPattern

BACKEND_NAMES = ["claude", "copilot"]

_VALID_REPORT = {
    "findings": [
        {
            "fingerprint": "select * from orders where customer_email = ?",
            "severity": "critical",
            "problem": "Full table scan on orders.customer_email for a high-frequency pattern.",
            "evidence": "EXPLAIN shows type=ALL, key=NULL, rows=4400312.",
            "recommendation": "Add a secondary index on orders(customer_email).",
            "suggested_ddl": "CREATE INDEX idx_orders_customer_email ON orders (customer_email);",
            "estimated_impact": "Rows examined should drop from ~4.4M to a handful per query.",
        }
    ],
    "summary": "One critical full-table-scan pattern accounts for most of the slow-log time.",
    "analyzed_patterns": 1,
    "db_verified": True,
}
_INVALID_REPORT = {"not": "a valid report"}


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
            )
        ],
        total_entries=42,
        parse_skipped=0,
        window_start=datetime(2026, 7, 14),
        window_end=datetime(2026, 7, 15),
    )


def _completed(
    stdout: str, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["agent"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _stdout_for(backend_name: str, structured: dict[str, object]) -> str:
    """Build the raw subprocess stdout each backend would need to produce `structured`."""
    if backend_name == "claude":
        return json.dumps({"type": "result", "structured_output": structured})
    return "```json\n" + json.dumps(structured) + "\n```"


# --- prompt rendering (backend-independent) ---------------------------------------


def test_render_prompt_includes_digest_json() -> None:
    prompt = render_prompt(_digest(), db_dsn=None)

    assert "customer_email" in prompt
    assert "520.5" in prompt


def test_render_prompt_notes_db_available_when_dsn_set() -> None:
    prompt = render_prompt(_digest(), db_dsn="mysql://readonly@host/db")

    assert "EXPLAIN" in prompt
    assert "db_verified" in prompt


def test_render_prompt_notes_db_unavailable_without_dsn() -> None:
    prompt = render_prompt(_digest(), db_dsn=None)

    assert "No DB DSN is configured" in prompt


def test_render_prompt_includes_json_schema() -> None:
    prompt = render_prompt(_digest(), db_dsn=None)

    assert '"title": "AnalysisReport"' in prompt


# --- shared analyzer behavior, parametrized over both real backends ----------------


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_returns_valid_report_on_first_success(backend_name: str, tmp_path: Path) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(_stdout_for(backend_name, _VALID_REPORT))

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert run.call_count == 1
    assert report.db_verified is True
    assert report.findings[0].severity == "critical"


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_retries_once_on_validation_failure_then_succeeds(
    backend_name: str, tmp_path: Path
) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = [
            _completed(_stdout_for(backend_name, _INVALID_REPORT)),
            _completed(_stdout_for(backend_name, _VALID_REPORT)),
        ]

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert run.call_count == 2
    assert report.db_verified is True
    argv = run.call_args_list[1].args[0]
    retry_prompt = argv[argv.index("-p") + 1]
    assert "failed schema validation" in retry_prompt


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_raises_agent_error_after_second_validation_failure(
    backend_name: str, tmp_path: Path
) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = [
            _completed(_stdout_for(backend_name, _INVALID_REPORT)),
            _completed(_stdout_for(backend_name, _INVALID_REPORT)),
        ]

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert run.call_count == 2
    dumped = list(tmp_path.glob("failed_*.raw.json"))
    assert len(dumped) == 1
    assert "a valid report" in dumped[0].read_text()
    assert str(dumped[0]) in exc_info.value.remediation


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_retries_on_completely_non_json_output(backend_name: str, tmp_path: Path) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = [
            _completed("not json at all"),
            _completed(_stdout_for(backend_name, _VALID_REPORT)),
        ]

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert run.call_count == 2
    assert report.db_verified is True


# --- subprocess failure modes, parametrized over both real backends ----------------


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_timeout_raises_agent_error_without_retry(
    backend_name: str, tmp_path: Path
) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd=backend_name, timeout=60)

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert run.call_count == 1
    assert "timed out" in exc_info.value.message.lower()


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_missing_binary_raises_agent_error(backend_name: str, tmp_path: Path) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = FileNotFoundError()

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert "not found on PATH" in exc_info.value.message


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_analyze_nonzero_exit_raises_agent_error_with_stderr(
    backend_name: str, tmp_path: Path
) -> None:
    backend = get_backend(backend_name)
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed("", returncode=1, stderr="permission denied")

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert "permission denied" in exc_info.value.remediation


# --- claude-specific extraction fallback --------------------------------------------


def test_analyze_accepts_raw_report_json_without_envelope_wrapper(tmp_path: Path) -> None:
    backend = get_backend("claude")
    direct_json = json.dumps(_VALID_REPORT)

    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(direct_json)

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path, backend=backend)

    assert run.call_count == 1
    assert report.db_verified is True
