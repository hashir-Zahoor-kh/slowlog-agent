"""GitHub Copilot CLI backend.

Copilot CLI has no native JSON-schema flag, so the rendered prompt already
inlines the schema (via `{{JSON_SCHEMA}}` in prompts/analyze.md) and instructs
the model to respond with ONLY conforming JSON. Markdown code fences are
stripped defensively since that instruction isn't always honored; expect a
higher retry rate here than with the Claude backend.
"""

from __future__ import annotations

import shutil
from typing import Any

from slowlog_agent.backends._process import run_agent_subprocess
from slowlog_agent.backends.base import DoctorResult

ALLOWED_TOOL = "shell(mysql --defaults-group-suffix=readonly*)"


class CopilotBackend:
    name = "copilot"

    def check_available(self) -> DoctorResult:
        if shutil.which("copilot"):
            return DoctorResult(ok=True, detail="copilot binary found on PATH")
        return DoctorResult(
            ok=False,
            detail="copilot binary not found on PATH",
            remediation=(
                "Install GitHub Copilot CLI: "
                "https://docs.github.com/copilot/github-copilot-in-the-cli"
            ),
        )

    def analyze(self, prompt: str, schema: dict[str, Any], timeout: int) -> str:
        argv = [
            "copilot",
            "-p",
            prompt,
            "-s",
            "--no-ask-user",
            "--allow-tool",
            ALLOWED_TOOL,
        ]
        raw = run_agent_subprocess(argv, timeout=timeout, binary_name="copilot")
        return _strip_code_fences(raw)


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    text = text.split("\n", 1)[1] if "\n" in text else text.removeprefix("```")
    if text.rstrip().endswith("```"):
        text = text.rstrip()[: -len("```")]
    return text.strip()
