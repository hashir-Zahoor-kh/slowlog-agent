"""Typed exceptions. Every exception carries a remediation hint for the user."""

from __future__ import annotations


class SlowlogError(Exception):
    """Base class for all slowlog-agent errors.

    Every instance carries a `remediation` string describing the concrete
    action a user should take to resolve the error. CLI error handlers print
    both `message` and `remediation`.
    """

    exit_code: int = 1

    def __init__(self, message: str, remediation: str) -> None:
        self.message = message
        self.remediation = remediation
        super().__init__(f"{message} (remediation: {remediation})")


class ConfigError(SlowlogError):
    """Raised for missing or invalid configuration."""

    exit_code = 5


class FetchError(SlowlogError):
    """Raised when fetching logs from CloudWatch fails."""

    exit_code = 3


class ParseError(SlowlogError):
    """Raised only for fatal, non-recoverable parse failures.

    Per-entry parse issues are skipped and counted by the parser rather than
    raising; this is reserved for cases where parsing cannot proceed at all.
    """

    exit_code = 3


class AgentError(SlowlogError):
    """Raised when the LLM backend fails to produce a valid analysis."""

    exit_code = 4


class ValidationError(SlowlogError):
    """Raised when agent output fails schema validation after retry."""

    exit_code = 4
