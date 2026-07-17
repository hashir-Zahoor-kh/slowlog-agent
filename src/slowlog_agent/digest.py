"""Normalize queries into fingerprints and aggregate parsed entries into a QueryDigest."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime

from slowlog_agent.schemas import QueryDigest, QueryPattern, SlowQueryEntry

_STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_NUMBER_RE = re.compile(r"(?<!\w)-?\d+(?:\.\d+)?")
_IN_LIST_RE = re.compile(r"in\s*\(\s*\?(?:\s*,\s*\?)+\s*\)")
_WHITESPACE_RE = re.compile(r"\s+")
_OPERATOR_RE = re.compile(r"\s*(<=|>=|!=|<>|=|<|>)\s*")


def fingerprint(sql: str) -> str:
    """Normalize a SQL statement into a shape-only pattern.

    Lowercases the statement, replaces string and numeric literals with `?`,
    and collapses multi-element `IN (?, ?, ?)` lists to `IN (?)` so that
    queries differing only in literal values or IN-list length collapse to
    the same fingerprint.
    """
    text = sql.strip().rstrip(";").strip().lower()
    text = _WHITESPACE_RE.sub(" ", text)
    text = _STRING_RE.sub("?", text)
    text = _NUMBER_RE.sub("?", text)
    text = _OPERATOR_RE.sub(r" \1 ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _IN_LIST_RE.sub("in (?)", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    lower_weight = sorted_values[lower] * (upper - rank)
    upper_weight = sorted_values[upper] * (rank - lower)
    return lower_weight + upper_weight


def build_digest(
    entries: list[SlowQueryEntry],
    *,
    parse_skipped: int,
    window_start: datetime,
    window_end: datetime,
    top_n: int = 10,
) -> QueryDigest:
    """Aggregate parsed entries by fingerprint into the top-N patterns by total time."""
    groups: dict[str, list[SlowQueryEntry]] = defaultdict(list)
    for entry in entries:
        groups[fingerprint(entry.sql)].append(entry)

    patterns = [_build_pattern(fp, group) for fp, group in groups.items()]
    patterns.sort(key=lambda p: p.total_time, reverse=True)

    return QueryDigest(
        patterns=patterns[:top_n],
        total_entries=len(entries),
        parse_skipped=parse_skipped,
        window_start=window_start,
        window_end=window_end,
    )


def _build_pattern(fp: str, group: list[SlowQueryEntry]) -> QueryPattern:
    times = sorted(e.query_time for e in group)
    return QueryPattern(
        fingerprint=fp,
        example_sql=group[0].sql,
        count=len(group),
        total_time=sum(e.query_time for e in group),
        max_time=max(e.query_time for e in group),
        p95_time=_percentile(times, 0.95),
        avg_rows_examined=sum(e.rows_examined for e in group) / len(group),
        avg_rows_sent=sum(e.rows_sent for e in group) / len(group),
    )
