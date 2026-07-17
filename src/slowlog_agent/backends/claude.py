"""Claude Code headless backend: native JSON-schema enforcement via `--json-schema`."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from slowlog_agent.backends._process import run_agent_subprocess
from slowlog_agent.backends.base import DoctorResult

ALLOWED_TOOLS = "Bash(mysql --defaults-group-suffix=readonly*)"


class ClaudeBackend:
    name = "claude"

    def check_available(self) -> DoctorResult:
        if shutil.which("claude"):
            return DoctorResult(ok=True, detail="claude binary found on PATH")
        return DoctorResult(
            ok=False,
            detail="claude binary not found on PATH",
            remediation="Install Claude Code: https://docs.claude.com/claude-code",
        )

    def analyze(self, prompt: str, schema: dict[str, Any], timeout: int) -> str:
        schema_path = _write_schema_tempfile(schema)
        try:
            argv = [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "json",
                "--json-schema",
                str(schema_path),
                "--allowedTools",
                ALLOWED_TOOLS,
                "--permission-mode",
                "acceptEdits",
            ]
            raw = run_agent_subprocess(argv, timeout=timeout, binary_name="claude")
        finally:
            schema_path.unlink(missing_ok=True)
        return _extract_structured_output(raw)


def _extract_structured_output(raw: str) -> str:
    """Pull the `structured_output` payload out of Claude's `--output-format json` envelope.

    Falls back to returning `raw` unchanged for non-JSON output or JSON that
    isn't wrapped in an envelope — analyzer.py's schema validation is what
    ultimately decides whether either of those is usable.
    """
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(envelope, dict) and "structured_output" in envelope:
        return json.dumps(envelope["structured_output"])
    return raw


def _write_schema_tempfile(schema: dict[str, Any]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".schema.json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(schema, f)
        return Path(f.name)
