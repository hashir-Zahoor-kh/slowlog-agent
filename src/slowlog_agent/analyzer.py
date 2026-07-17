"""Render the analysis prompt, invoke the configured agent backend, and validate its output.

Deterministic concerns (prompt rendering, schema validation, the single
retry-with-validation-error policy, dumping failed output for debugging) live
here and are identical regardless of which `AgentBackend` is plugged in.
Backends (see `backends/`) own only subprocess construction and raw-output
extraction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from slowlog_agent.backends.base import AgentBackend
from slowlog_agent.errors import AgentError
from slowlog_agent.schemas import AnalysisReport, QueryDigest, export_json_schema

_DIGEST_TOKEN = "{{DIGEST_JSON}}"  # noqa: S105 - not a secret, a template placeholder
_DB_AVAILABLE_TOKEN = "{{DB_AVAILABLE}}"
_SCHEMA_TOKEN = "{{JSON_SCHEMA}}"

_DB_AVAILABLE_TEXT = (
    "A read-only DB DSN is configured: run `EXPLAIN` for each pattern's "
    "example SQL and cite the output as evidence."
)
_DB_UNAVAILABLE_TEXT = (
    "No DB DSN is configured for this run: do not attempt to connect to a "
    "database. Reason from the digest statistics alone and set `db_verified` to `false`."
)


def load_prompt_template() -> str:
    return resources.files("slowlog_agent").joinpath("prompts", "analyze.md").read_text()


def render_prompt(digest: QueryDigest, *, db_dsn: str | None) -> str:
    template = load_prompt_template()
    text = template.replace(_DIGEST_TOKEN, digest.to_prompt_json())
    text = text.replace(_DB_AVAILABLE_TOKEN, _DB_AVAILABLE_TEXT if db_dsn else _DB_UNAVAILABLE_TEXT)
    return text.replace(_SCHEMA_TOKEN, export_json_schema())


def analyze(
    digest: QueryDigest,
    *,
    db_dsn: str | None,
    timeout: int,
    output_dir: Path,
    backend: AgentBackend,
) -> AnalysisReport:
    """Run the full analyze-validate-retry-once pipeline and return a validated report."""
    prompt = render_prompt(digest, db_dsn=db_dsn)
    schema = json.loads(export_json_schema())

    raw = backend.analyze(prompt, schema, timeout)
    try:
        return _parse_and_validate(raw)
    except PydanticValidationError as first_error:
        retry_prompt = _append_validation_error(prompt, raw, first_error)
        raw_retry = backend.analyze(retry_prompt, schema, timeout)
        try:
            return _parse_and_validate(raw_retry)
        except PydanticValidationError as second_error:
            dump_path = _dump_failed_output(output_dir, raw_retry)
            raise AgentError(
                "Agent output failed schema validation after one retry.",
                f"Raw output was written to {dump_path} for debugging. "
                f"Validation errors: {second_error}",
            ) from second_error


def _parse_and_validate(raw: str) -> AnalysisReport:
    return AnalysisReport.model_validate_json(raw)


def _append_validation_error(prompt: str, raw: str, error: PydanticValidationError) -> str:
    return (
        f"{prompt}\n\n"
        "---\n\n"
        "Your previous response failed schema validation.\n\n"
        f"Raw output:\n{raw}\n\n"
        f"Validation errors:\n{error}\n\n"
        "Fix these errors and respond with ONLY a JSON object conforming exactly "
        "to the schema above — no prose, no markdown code fences."
    )


def _dump_failed_output(output_dir: Path, raw: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"failed_{timestamp}.raw.json"
    path.write_text(raw)
    return path
