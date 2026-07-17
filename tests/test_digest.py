from datetime import datetime

import pytest

from slowlog_agent.digest import _percentile, build_digest, fingerprint
from slowlog_agent.schemas import SlowQueryEntry

# --- fingerprint pattern pairs ------------------------------------------------

MUST_COLLAPSE = [
    (
        "SELECT * FROM orders WHERE id = 1",
        "SELECT * FROM orders WHERE id = 2",
    ),
    (
        "SELECT * FROM orders WHERE email = 'a@x.com'",
        "SELECT * FROM orders WHERE email = 'b@y.com'",
    ),
    (
        "select * from orders where id=1",
        "SELECT   *   FROM   orders WHERE id = 1",
    ),
    (
        "SELECT * FROM orders WHERE id IN (1,2,3)",
        "SELECT * FROM orders WHERE id IN (4,5,6)",
    ),
    (
        "SELECT * FROM orders WHERE id IN (1)",
        "SELECT * FROM orders WHERE id IN (1,2,3)",
    ),
    (
        "SELECT 1;",
        "SELECT 1",
    ),
]

MUST_NOT_COLLAPSE = [
    (
        "SELECT * FROM orders WHERE id = 1",
        "SELECT * FROM customers WHERE id = 1",
    ),
    (
        "SELECT id FROM orders",
        "SELECT id, name FROM orders",
    ),
    (
        "SELECT * FROM orders WHERE status = 'pending'",
        "SELECT * FROM orders WHERE status != 'pending'",
    ),
    (
        "SELECT * FROM orders",
        "SELECT * FROM orders WHERE id = 1",
    ),
    (
        "UPDATE orders SET status = 'shipped' WHERE id = 1",
        "SELECT * FROM orders WHERE id = 1",
    ),
]


@pytest.mark.parametrize("a,b", MUST_COLLAPSE)
def test_fingerprint_collapses(a: str, b: str) -> None:
    assert fingerprint(a) == fingerprint(b)


@pytest.mark.parametrize("a,b", MUST_NOT_COLLAPSE)
def test_fingerprint_does_not_collapse(a: str, b: str) -> None:
    assert fingerprint(a) != fingerprint(b)


def test_fingerprint_collapses_in_list_to_single_placeholder() -> None:
    fp = fingerprint("SELECT * FROM t WHERE id IN (1, 2, 3, 4, 5)")
    assert fp == "select * from t where id in (?)"


def test_fingerprint_does_not_touch_digits_embedded_in_identifiers() -> None:
    fp = fingerprint("SELECT col1 FROM table_2")
    assert fp == "select col1 from table_2"


# --- percentile helper ----------------------------------------------------------


def test_percentile_of_empty_list_is_zero() -> None:
    assert _percentile([], 0.95) == 0.0


def test_percentile_of_single_value() -> None:
    assert _percentile([7.0], 0.95) == 7.0


def test_percentile_at_exact_integer_rank() -> None:
    assert _percentile([1.0, 2.0, 3.0], 0.5) == 2.0


# --- aggregation ---------------------------------------------------------------


def _entry(
    sql: str, query_time: float, rows_examined: int = 100, rows_sent: int = 1
) -> SlowQueryEntry:
    return SlowQueryEntry(
        timestamp=datetime(2026, 7, 15, 4, 0, 0),
        user="app",
        host="10.0.1.5",
        query_time=query_time,
        rows_examined=rows_examined,
        rows_sent=rows_sent,
        sql=sql,
    )


def test_build_digest_aggregates_by_fingerprint() -> None:
    entries = [
        _entry("SELECT * FROM orders WHERE id = 1", 1.0),
        _entry("SELECT * FROM orders WHERE id = 2", 3.0),
        _entry("SELECT * FROM customers WHERE id = 1", 5.0),
    ]

    digest = build_digest(
        entries,
        parse_skipped=2,
        window_start=datetime(2026, 7, 14),
        window_end=datetime(2026, 7, 15),
    )

    assert digest.total_entries == 3
    assert digest.parse_skipped == 2
    assert len(digest.patterns) == 2

    orders_pattern = next(p for p in digest.patterns if "orders" in p.fingerprint)
    assert orders_pattern.count == 2
    assert orders_pattern.total_time == 4.0
    assert orders_pattern.max_time == 3.0


def test_build_digest_sorts_by_total_time_descending() -> None:
    entries = [
        _entry("SELECT * FROM a", 1.0),
        _entry("SELECT * FROM b", 100.0),
        _entry("SELECT * FROM c", 50.0),
    ]

    digest = build_digest(
        entries,
        parse_skipped=0,
        window_start=datetime(2026, 7, 14),
        window_end=datetime(2026, 7, 15),
    )

    assert [p.example_sql for p in digest.patterns] == [
        "SELECT * FROM b",
        "SELECT * FROM c",
        "SELECT * FROM a",
    ]


def test_build_digest_respects_top_n() -> None:
    entries = [_entry(f"SELECT * FROM t{i}", float(i)) for i in range(20)]

    digest = build_digest(
        entries,
        parse_skipped=0,
        window_start=datetime(2026, 7, 14),
        window_end=datetime(2026, 7, 15),
        top_n=5,
    )

    assert len(digest.patterns) == 5
    assert digest.total_entries == 20  # summary stats reflect all entries, not just top N


def test_build_digest_computes_averages_and_p95() -> None:
    entries = [
        _entry("SELECT * FROM t", 1.0, rows_examined=10, rows_sent=1),
        _entry("SELECT * FROM t", 2.0, rows_examined=20, rows_sent=2),
        _entry("SELECT * FROM t", 3.0, rows_examined=30, rows_sent=3),
        _entry("SELECT * FROM t", 4.0, rows_examined=40, rows_sent=4),
        _entry("SELECT * FROM t", 5.0, rows_examined=50, rows_sent=5),
    ]

    digest = build_digest(
        entries,
        parse_skipped=0,
        window_start=datetime(2026, 7, 14),
        window_end=datetime(2026, 7, 15),
    )

    pattern = digest.patterns[0]
    assert pattern.avg_rows_examined == 30.0
    assert pattern.avg_rows_sent == 3.0
    assert pattern.p95_time == pytest.approx(4.8)


def test_build_digest_empty_entries() -> None:
    digest = build_digest(
        [],
        parse_skipped=5,
        window_start=datetime(2026, 7, 14),
        window_end=datetime(2026, 7, 15),
    )

    assert digest.patterns == []
    assert digest.total_entries == 0
    assert digest.parse_skipped == 5
