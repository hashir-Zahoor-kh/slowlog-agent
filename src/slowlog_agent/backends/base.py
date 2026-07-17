"""The AgentBackend protocol every LLM engine backend implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class DoctorResult:
    """Result of a backend's `slowlog doctor` availability check."""

    ok: bool
    detail: str
    remediation: str | None = None


class AgentBackend(Protocol):
    name: str

    def check_available(self) -> DoctorResult:
        """Check that the backend's binary is on PATH (and authenticated, where checkable)."""
        ...

    def analyze(self, prompt: str, schema: dict[str, Any], timeout: int) -> str:
        """Invoke the backend and return its raw candidate JSON for AnalysisReport.

        Callers (analyzer.py) validate and retry; this returns the backend's
        best-effort extracted JSON text, not a parsed/validated report.
        """
        ...
