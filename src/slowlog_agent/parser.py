"""Parse MySQL slow query log text into SlowQueryEntry records.

Deliberately tolerant: administrator commands are skipped silently, and any
entry that can't be fully reconstructed (missing required fields, corrupted
fragments, dangling SQL with no header) is skipped and counted rather than
raising. CloudWatch may deliver one entry per log event or split an entry
across several events, so callers should reassemble the full text (see
`parse_events`) before parsing rather than parsing events individually.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from slowlog_agent.schemas import SlowQueryEntry

_TIME_RE = re.compile(r"^#\s*Time:\s*(?P<ts>\S+)")
_USER_HOST_RE = re.compile(
    r"^#\s*User@Host:\s*(?P<user>\S*)\[[^\]]*\]\s*@\s*(?P<host>\S*)\s*\[(?P<ip>[^\]]*)\]"
)
_QUERY_TIME_RE = re.compile(
    r"^#\s*Query_time:\s*(?P<query_time>[\d.]+)"
    r"(?:\s+Lock_time:\s*(?P<lock_time>[\d.]+))?"
    r"(?:\s+Rows_sent:\s*(?P<rows_sent>\d+))?"
    r"(?:\s+Rows_examined:\s*(?P<rows_examined>\d+))?"
)
_ADMIN_RE = re.compile(r"^#\s*[Aa]dministrator command:")
_SET_TIMESTAMP_RE = re.compile(r"^SET\s+timestamp\s*=\s*\d+\s*;?\s*$", re.IGNORECASE)
_USE_DB_RE = re.compile(r"^use\s+\S+\s*;?\s*$", re.IGNORECASE)
_COMMENT_RE = re.compile(r"^#")


@dataclass
class ParseResult:
    entries: list[SlowQueryEntry]
    skipped: int


@dataclass
class _PendingRecord:
    fields: dict[str, Any] = field(default_factory=dict)
    sql_lines: list[str] = field(default_factory=list)
    is_admin: bool = False
    invalid: bool = False


def _parse_timestamp(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class _SlowLogParser:
    def __init__(self) -> None:
        self.entries: list[SlowQueryEntry] = []
        self.skipped = 0
        self._pending: _PendingRecord | None = None
        self._orphan_fragment = False

    def feed(self, lines: list[str]) -> None:
        for raw_line in lines:
            self._feed_line(raw_line)
        self._finalize()

    def _feed_line(self, raw_line: str) -> None:
        stripped = raw_line.strip()
        if not stripped:
            return

        if m := _TIME_RE.match(stripped):
            self._finalize()
            timestamp = _parse_timestamp(m.group("ts"))
            self._pending = _PendingRecord()
            if timestamp is not None:
                self._pending.fields["timestamp"] = timestamp
            return

        if self._pending is None:
            if not stripped.startswith("#"):
                self._orphan_fragment = True
            return

        if m := _USER_HOST_RE.match(stripped):
            self._pending.fields["user"] = m.group("user") or "unknown"
            self._pending.fields["host"] = m.group("ip") or m.group("host") or "unknown"
            return

        if m := _QUERY_TIME_RE.match(stripped):
            try:
                self._pending.fields["query_time"] = float(m.group("query_time"))
                if m.group("lock_time") is not None:
                    self._pending.fields["lock_time"] = float(m.group("lock_time"))
                if m.group("rows_sent") is not None:
                    self._pending.fields["rows_sent"] = int(m.group("rows_sent"))
                if m.group("rows_examined") is not None:
                    self._pending.fields["rows_examined"] = int(m.group("rows_examined"))
            except ValueError:
                self._pending.invalid = True
            return

        if _ADMIN_RE.match(stripped):
            self._pending.is_admin = True
            return

        if _COMMENT_RE.match(stripped):
            return  # unrecognized comment/header line, ignore

        if _SET_TIMESTAMP_RE.match(stripped) or _USE_DB_RE.match(stripped):
            return

        self._pending.sql_lines.append(raw_line.strip())

    def _finalize(self) -> None:
        if self._orphan_fragment:
            self.skipped += 1
            self._orphan_fragment = False

        pending = self._pending
        self._pending = None
        if pending is None:
            return

        entry = self._build_entry(pending)
        if entry is not None:
            self.entries.append(entry)
        elif not pending.is_admin:
            self.skipped += 1

    @staticmethod
    def _build_entry(pending: _PendingRecord) -> SlowQueryEntry | None:
        if pending.is_admin or pending.invalid or not pending.sql_lines:
            return None
        sql = " ".join(part for part in pending.sql_lines if part).rstrip(";").strip()
        if not sql:
            return None
        try:
            return SlowQueryEntry(sql=sql, **pending.fields)
        except (ValidationError, TypeError):
            return None


def parse_log_text(text: str) -> ParseResult:
    parser = _SlowLogParser()
    parser.feed(text.splitlines())
    return ParseResult(entries=parser.entries, skipped=parser.skipped)


def parse_events(events: list[str]) -> ParseResult:
    """Reassemble CloudWatch log events (which may split entries across events)
    into a single text stream before parsing."""
    return parse_log_text("\n".join(events))
