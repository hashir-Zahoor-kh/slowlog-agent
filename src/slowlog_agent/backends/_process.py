"""Subprocess execution shared by every backend, with a uniform AgentError shape.

Kept separate from any one backend so both `claude.py` and `copilot.py`
patch/behave identically for timeouts, missing binaries, and non-zero exits —
the only thing that differs between backends is argv construction and
raw-output extraction.
"""

from __future__ import annotations

import subprocess

from slowlog_agent.errors import AgentError


def run_agent_subprocess(argv: list[str], *, timeout: int, binary_name: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - argv is built from fixed flags + a rendered prompt
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(
            f"{binary_name} analysis timed out after {timeout}s.",
            "Retry with a smaller --top-n or shorter --hours window, or raise "
            "agent_timeout_seconds in slowlog.toml.",
        ) from exc
    except FileNotFoundError as exc:
        raise AgentError(
            f"The `{binary_name}` binary was not found on PATH.",
            f"Install {binary_name} and ensure it's on PATH, then run `slowlog doctor`.",
        ) from exc
    if result.returncode != 0:
        raise AgentError(
            f"{binary_name} exited with code {result.returncode}.",
            f"stderr: {(result.stderr or '').strip()[:500] or '(empty)'}",
        )
    return result.stdout
