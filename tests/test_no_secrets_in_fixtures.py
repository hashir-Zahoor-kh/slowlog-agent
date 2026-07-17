"""Guard against accidentally committing secret-like strings in test fixtures.

This repo touches AWS credentials and DB DSNs by design, so fixtures are a
plausible place for a real secret to leak in by copy-paste. This is a
narrower, dependency-light complement to the repo-wide detect-secrets
pre-commit hook (.pre-commit-config.yaml / .secrets.baseline).
"""

from __future__ import annotations

import re
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_SECRET_PATTERNS = {
    "AWS access key ID": re.compile(r"AKIA[0-9A-Z]{16}"),
    "AWS secret access key assignment": re.compile(
        r"aws_secret_access_key\s*=\s*\S+", re.IGNORECASE
    ),
    "PEM private key header": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "generic secret/password/token assignment": re.compile(
        r"(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][A-Za-z0-9+/=_-]{12,}['\"]",
        re.IGNORECASE,
    ),
}


def _all_fixture_files() -> list[Path]:
    return [p for p in FIXTURES_DIR.rglob("*") if p.is_file()]


def test_fixtures_directory_is_not_empty() -> None:
    assert _all_fixture_files(), "expected at least one fixture file to scan"


def test_no_fixture_file_contains_secret_like_patterns() -> None:
    violations: list[str] = []
    for path in _all_fixture_files():
        text = path.read_text(errors="ignore")
        for name, pattern in _SECRET_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{path.relative_to(FIXTURES_DIR.parent)}: matched {name!r}")

    assert not violations, "possible secrets found in fixtures:\n" + "\n".join(violations)
