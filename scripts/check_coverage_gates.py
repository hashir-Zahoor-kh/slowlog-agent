#!/usr/bin/env python3
"""Enforce per-file coverage gates from coverage.json.

The overall >=80% gate is enforced by pytest-cov's --cov-fail-under; this
script enforces the stricter >=90% gate on the deterministic core modules
called out in the project spec. Run after `pytest --cov-report=json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GATED_FILES = {
    "src/slowlog_agent/parser.py": 90.0,
    "src/slowlog_agent/digest.py": 90.0,
    "src/slowlog_agent/report.py": 90.0,
    "src/slowlog_agent/schemas.py": 90.0,
}


def main() -> int:
    data = json.loads(Path("coverage.json").read_text())

    failures = []
    for path, threshold in GATED_FILES.items():
        file_data = data["files"].get(path)
        if file_data is None:
            failures.append(f"{path}: not found in coverage report")
            continue
        percent = file_data["summary"]["percent_covered"]
        if percent < threshold:
            failures.append(f"{path}: {percent:.1f}% covered, required >= {threshold:.0f}%")

    if failures:
        print("Coverage gate failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("All per-file coverage gates passed (>= 90% on parser/digest/report/schemas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
