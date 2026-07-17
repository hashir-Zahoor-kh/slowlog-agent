"""CopilotBackend: argv construction, fence stripping, timeout handling.

Copilot CLI has no native --json-schema flag, so schema enforcement happens
entirely via the rendered prompt (tested in test_analyzer.py); this module
covers argv construction and the defensive markdown-fence stripping.
"""

import json
import subprocess
from unittest.mock import patch

import pytest

from slowlog_agent.backends.copilot import ALLOWED_TOOL, CopilotBackend
from slowlog_agent.errors import AgentError

_SCHEMA = {"title": "AnalysisReport", "type": "object"}


def _completed(
    stdout: str, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["copilot"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- argv construction, security-relevant flags asserted exactly -------------------


def test_analyze_builds_expected_argv() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(json.dumps({"ok": True}))

        CopilotBackend().analyze("the prompt", _SCHEMA, timeout=60)

        argv = run.call_args.args[0]

    assert argv[0] == "copilot"
    assert argv[1] == "-p"
    assert argv[2] == "the prompt"
    assert "-s" in argv
    assert "--no-ask-user" in argv
    assert "--allow-tool" in argv
    assert argv[argv.index("--allow-tool") + 1] == ALLOWED_TOOL
    assert ALLOWED_TOOL == "shell(mysql --defaults-group-suffix=readonly*)"
    # no native schema flag: schema is inlined into the prompt itself, not argv
    assert "--json-schema" not in argv


# --- defensive markdown-fence stripping ---------------------------------------------


def test_analyze_strips_json_fenced_output() -> None:
    payload = {"summary": "hi"}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(fenced)

        raw = CopilotBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert json.loads(raw) == payload


def test_analyze_strips_bare_fenced_output() -> None:
    payload = {"summary": "hi"}
    fenced = f"```\n{json.dumps(payload)}\n```"
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(fenced)

        raw = CopilotBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert json.loads(raw) == payload


def test_analyze_leaves_unfenced_output_unchanged() -> None:
    payload_text = json.dumps({"summary": "hi"})
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed(payload_text)

        raw = CopilotBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert raw == payload_text


def test_analyze_leaves_non_json_garbage_unchanged() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.return_value = _completed("not json at all")

        raw = CopilotBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert raw == "not json at all"


# --- subprocess failure modes ---------------------------------------------------------


def test_analyze_timeout_raises_agent_error() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="copilot", timeout=60)

        with pytest.raises(AgentError) as exc_info:
            CopilotBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert "timed out" in exc_info.value.message.lower()


def test_analyze_missing_binary_raises_agent_error() -> None:
    with patch("slowlog_agent.backends._process.subprocess.run") as run:
        run.side_effect = FileNotFoundError()

        with pytest.raises(AgentError) as exc_info:
            CopilotBackend().analyze("prompt", _SCHEMA, timeout=60)

    assert "copilot" in exc_info.value.message
    assert "not found on PATH" in exc_info.value.message


# --- check_available -------------------------------------------------------------------


def test_check_available_ok() -> None:
    with patch("slowlog_agent.backends.copilot.shutil.which", return_value="/usr/bin/copilot"):
        result = CopilotBackend().check_available()

    assert result.ok is True


def test_check_available_missing() -> None:
    with patch("slowlog_agent.backends.copilot.shutil.which", return_value=None):
        result = CopilotBackend().check_available()

    assert result.ok is False
    assert result.remediation is not None
