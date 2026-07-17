"""Pydantic models shared across the pipeline.

`AnalysisReport` is the single source of truth for the agent's output shape;
its JSON schema is exported (via `python -m slowlog_agent.schemas`) for the
`--json-schema` flag passed to the headless Claude invocation, so the schema
used to validate agent output is generated from the same model this module
defines rather than hand-maintained separately.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]


class SlowQueryEntry(BaseModel):
    """A single parsed entry from the MySQL slow query log."""

    timestamp: datetime
    user: str
    host: str
    query_time: float = Field(ge=0)
    lock_time: float = Field(default=0.0, ge=0)
    rows_sent: int = Field(default=0, ge=0)
    rows_examined: int = Field(ge=0)
    sql: str


class QueryPattern(BaseModel):
    """One fingerprinted query pattern aggregated from one or more entries."""

    fingerprint: str
    example_sql: str
    count: int = Field(ge=1)
    total_time: float = Field(ge=0)
    max_time: float = Field(ge=0)
    p95_time: float = Field(ge=0)
    avg_rows_examined: float = Field(ge=0)
    avg_rows_sent: float = Field(ge=0)


class QueryDigest(BaseModel):
    """Aggregated summary of a slow-log window: the top N patterns by total time."""

    patterns: list[QueryPattern]
    total_entries: int = Field(ge=0)
    parse_skipped: int = Field(ge=0)
    window_start: datetime
    window_end: datetime

    def to_prompt_json(self) -> str:
        return self.model_dump_json(indent=2)


class Finding(BaseModel):
    """One issue identified by the analysis agent for a specific query pattern."""

    fingerprint: str
    severity: Severity
    problem: str
    evidence: str
    recommendation: str
    suggested_ddl: str | None = None
    estimated_impact: str


class AnalysisReport(BaseModel):
    """The full, schema-validated output of an analysis run."""

    findings: list[Finding]
    summary: str
    analyzed_patterns: int = Field(ge=0)
    db_verified: bool


def export_json_schema() -> str:
    return json.dumps(AnalysisReport.model_json_schema(), indent=2)


if __name__ == "__main__":
    print(export_json_schema())
