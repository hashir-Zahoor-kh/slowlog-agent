import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from slowlog_agent.analyzer import analyze, render_prompt
from slowlog_agent.errors import AgentError
from slowlog_agent.schemas import QueryDigest, QueryPattern

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "claude_output_valid.json"


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
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _valid_envelope() -> str:
    return FIXTURE_PATH.read_text()


def _invalid_envelope() -> str:
    return json.dumps({"type": "result", "structured_output": {"not": "a valid report"}})


# --- prompt rendering ------------------------------------------------------------


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


# --- happy path + argv construction ----------------------------------------------


def test_analyze_returns_valid_report_on_first_success(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.return_value = _completed(_valid_envelope())

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert run.call_count == 1
    assert report.db_verified is True
    assert report.findings[0].severity == "critical"


def test_analyze_builds_expected_argv_and_security_relevant_flags(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.return_value = _completed(_valid_envelope())

        analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

        argv = run.call_args.args[0]

    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--allowedTools" in argv
    allowed_tools = argv[argv.index("--allowedTools") + 1]
    assert allowed_tools == "Bash(mysql --defaults-group-suffix=readonly*)"
    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--json-schema" in argv


def test_analyze_writes_schema_to_a_readable_temp_file(tmp_path: Path) -> None:
    captured_schema_path: list[str] = []

    def _fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        schema_path = argv[argv.index("--json-schema") + 1]
        captured_schema_path.append(schema_path)
        schema = json.loads(Path(schema_path).read_text())
        assert schema["title"] == "AnalysisReport"
        return _completed(_valid_envelope())

    with patch("slowlog_agent.analyzer.subprocess.run", side_effect=_fake_run):
        analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    # temp file is cleaned up after the call
    assert not Path(captured_schema_path[0]).exists()


# --- retry policy ------------------------------------------------------------


def test_analyze_retries_once_on_validation_failure_then_succeeds(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.side_effect = [_completed(_invalid_envelope()), _completed(_valid_envelope())]

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert run.call_count == 2
    assert report.db_verified is True
    retry_prompt = run.call_args_list[1].args[0][run.call_args_list[1].args[0].index("-p") + 1]
    assert "failed schema validation" in retry_prompt


def test_analyze_raises_agent_error_after_second_validation_failure(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.side_effect = [_completed(_invalid_envelope()), _completed(_invalid_envelope())]

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert run.call_count == 2
    dumped = list(tmp_path.glob("failed_*.raw.json"))
    assert len(dumped) == 1
    assert "a valid report" in dumped[0].read_text()
    assert str(dumped[0]) in exc_info.value.remediation


def test_analyze_accepts_raw_report_json_without_envelope_wrapper(tmp_path: Path) -> None:
    envelope = json.loads(_valid_envelope())
    direct_json = json.dumps(envelope["structured_output"])

    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.return_value = _completed(direct_json)

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert run.call_count == 1
    assert report.db_verified is True


def test_analyze_retries_on_completely_non_json_output(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.side_effect = [_completed("not json at all"), _completed(_valid_envelope())]

        report = analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert run.call_count == 2
    assert report.db_verified is True


# --- subprocess failure modes ----------------------------------------------------


def test_analyze_timeout_raises_agent_error_without_retry(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert run.call_count == 1
    assert "timed out" in exc_info.value.message.lower()


def test_analyze_missing_binary_raises_agent_error(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.side_effect = FileNotFoundError()

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert "not found on PATH" in exc_info.value.message


def test_analyze_nonzero_exit_raises_agent_error_with_stderr(tmp_path: Path) -> None:
    with patch("slowlog_agent.analyzer.subprocess.run") as run:
        run.return_value = _completed("", returncode=1, stderr="permission denied")

        with pytest.raises(AgentError) as exc_info:
            analyze(_digest(), db_dsn=None, timeout=60, output_dir=tmp_path)

    assert "permission denied" in exc_info.value.remediation
