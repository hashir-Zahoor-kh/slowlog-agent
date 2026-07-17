"""Pluggable LLM engine backends, selected via `agent_backend` in config.

Shared analysis logic (prompt rendering, schema validation, the single
retry-with-validation-error policy, dumping failed output) lives in
`analyzer.py` and is backend-agnostic. Backends only own subprocess
construction and raw-output extraction — see `base.AgentBackend`.
"""

from __future__ import annotations

from collections.abc import Callable

from slowlog_agent.backends.base import AgentBackend
from slowlog_agent.backends.claude import ClaudeBackend
from slowlog_agent.backends.copilot import CopilotBackend
from slowlog_agent.errors import ConfigError

_REGISTRY: dict[str, Callable[[], AgentBackend]] = {
    ClaudeBackend.name: ClaudeBackend,
    CopilotBackend.name: CopilotBackend,
}


def get_backend(name: str) -> AgentBackend:
    """Instantiate the backend registered under `name`.

    Raises ConfigError (naming the valid choices) for anything else, so a
    typo in `agent_backend` fails with the same remediation-bearing shape as
    every other config problem rather than a bare KeyError.
    """
    try:
        factory = _REGISTRY[name]
    except KeyError as exc:
        valid = ", ".join(sorted(_REGISTRY))
        raise ConfigError(
            f"Unknown agent_backend '{name}'.",
            f"Set agent_backend to one of: {valid}.",
        ) from exc
    return factory()


__all__ = ["AgentBackend", "ClaudeBackend", "CopilotBackend", "get_backend"]
