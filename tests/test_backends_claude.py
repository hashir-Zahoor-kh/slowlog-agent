"""ClaudeBackend: argv construction, schema tempfile handling, envelope extraction."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from slowlog_agent.backends.claude import ALLOWED_TOOLS, ClaudeBackend
from slowlog_agent.errors import AgentError

_SCHEMA = {"title": "AnalysisReport", "type": "object"}


def _completed(
    stdout: str, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _envelope(structured: dict[str, object]) -> str:
    return json.dumps({"type": "result", "structured_output": structured})


# --- argv construction, security-relevant flags asserted exactly -------------------


def test_analyze_builds_expected_argv() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(_envelope({"ok": True}))

        ClaudeBackend().analyze("the prompt", _SCHEMA, timeout=60)

        argv = run.call_args.args[0]

    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert argv[2] == "the prompt"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--allowedTools" in argv
    assert argv[argv.index("--allowedTools") + 1] == ALLOWED_TOOLS
    assert ALLOWED_TOOLS == "Bash(mysql --defaults-group-suffix=readonly*)"
    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--json-schema" in argv


def test_analyze_writes_schema_to_a_readable_tempfile_then_cleans_up() -> None:
    captured: list[str] = []

    def _fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        schema_path = argv[argv.index("--json-schema") + 1]
        captured.append(schema_path)
        assert json.loads(Path(schema_path).read_text()) == _SCHEMA
        return _completed(_envelope({"ok": True}))

    with patch("slowlog_agent.backends._process.subprocess.run", side_effect=_fake_run):
        ClaudeBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert not Path(captured[0]).exists()


# --- raw-output extraction -----------------------------------------------------------


def test_analyze_extracts_structured_output_from_envelope() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(_envelope({"summary": "hi"}))

        raw = ClaudeBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert json.loads(raw) == {"summary": "hi"}


def test_analyze_returns_raw_unchanged_when_not_an_envelope() -> None:
    direct = json.dumps({"summary": "hi"})
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(direct)

        raw = ClaudeBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert raw == direct


def test_analyze_returns_raw_unchanged_when_not_json() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed("not json at all")

        raw = ClaudeBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert raw == "not json at all"


# --- subprocess failure modes ---------------------------------------------------------


def test_analyze_timeout_raises_agent_error_and_cleans_up_tempfile() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)

        with pytest.raises(AgentError) as exc_info:
            ClaudeBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert "timed out" in exc_info.value.message.lower()


def test_analyze_missing_binary_raises_agent_error() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = FileNotFoundError()

        with pytest.raises(AgentError) as exc_info:
            ClaudeBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert "claude" in exc_info.value.message
    assert "not found on PATH" in exc_info.value.message


# --- check_available -------------------------------------------------------------------


def test_check_available_ok() -> None:
    with patch("slowlog_agent.backends.claude.shutil.which", return_value="/usr/bin/claude"):
        result = ClaudeBackend().check_available()

    assert result.ok is True


def test_check_available_missing() -> None:
    with patch("slowlog_agent.backends.claude.shutil.which", return_value=None):
        result = ClaudeBackend().check_available()

    assert result.ok is False
    assert result.remediation is not None
