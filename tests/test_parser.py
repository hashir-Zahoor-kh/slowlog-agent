from pathlib import Path

from slowlog_agent.parser import parse_events, parse_log_text

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "slow_log_sample.txt"


def _load_fixture() -> str:
    return FIXTURE_PATH.read_text()


def test_fixture_parses_expected_entry_and_skip_counts() -> None:
    result = parse_log_text(_load_fixture())

    assert len(result.entries) == 6
    assert result.skipped == 2


def test_full_entry_fields_parsed_correctly() -> None:
    result = parse_log_text(_load_fixture())
    first = result.entries[0]

    assert first.user == "app"
    assert first.host == "10.0.1.5"
    assert first.query_time == 12.4
    assert first.lock_time == 0.001
    assert first.rows_sent == 3
    assert first.rows_examined == 4400312
    assert first.sql == "SELECT * FROM orders WHERE customer_email LIKE '%gmail%'"


def test_entry_missing_lock_time_defaults_to_zero() -> None:
    result = parse_log_text(_load_fixture())
    entry = result.entries[1]

    assert entry.query_time == 8.7
    assert entry.lock_time == 0.0
    assert entry.rows_sent == 1
    assert entry.rows_examined == 900123


def test_entry_missing_rows_sent_defaults_to_zero() -> None:
    result = parse_log_text(_load_fixture())
    entry = result.entries[2]

    assert entry.query_time == 5.1
    assert entry.lock_time == 0.003
    assert entry.rows_sent == 0
    assert entry.rows_examined == 120000


def test_use_db_line_is_excluded_from_sql() -> None:
    result = parse_log_text(_load_fixture())
    entry = result.entries[3]

    assert entry.user == "reporting"
    assert entry.host == "10.0.1.9"
    assert "use" not in entry.sql.lower()
    assert entry.sql == "SELECT * FROM orders WHERE status = 'pending'"


def test_multiline_sql_is_reassembled_into_one_statement() -> None:
    result = parse_log_text(_load_fixture())
    entry = result.entries[4]

    assert entry.sql == (
        "SELECT o.id, o.total, c.name FROM orders o "
        "JOIN customers c ON c.id = o.customer_id "
        "WHERE o.created_at > '2026-07-01'"
    )


def test_administrator_command_is_skipped_and_not_counted() -> None:
    result = parse_log_text(_load_fixture())

    assert all("administrator" not in e.sql.lower() for e in result.entries)
    # 2 skipped = dangling leading fragment + header-only entry with no SQL;
    # the admin command itself is intentionally excluded from both counts.
    assert result.skipped == 2


def test_final_entry_recovers_after_corrupted_ones() -> None:
    result = parse_log_text(_load_fixture())
    last = result.entries[-1]

    assert last.query_time == 15.0
    assert last.sql == "SELECT * FROM orders WHERE customer_email LIKE '%gmail%'"


def test_never_crashes_on_garbage_input() -> None:
    result = parse_log_text("not a slow log\nrandom garbage\n### broken header\n")

    assert result.entries == []


def test_empty_input_produces_no_entries_no_skips() -> None:
    result = parse_log_text("")

    assert result.entries == []
    assert result.skipped == 0


def test_parse_events_reassembles_across_cloudwatch_event_boundaries() -> None:
    text = _load_fixture()
    whole = parse_log_text(text)

    # Simulate CloudWatch delivering one log event per line.
    per_line_events = text.splitlines()
    reassembled = parse_events(per_line_events)

    assert len(reassembled.entries) == len(whole.entries)
    assert reassembled.skipped == whole.skipped
    assert [e.sql for e in reassembled.entries] == [e.sql for e in whole.entries]


def test_malformed_numeric_field_is_skipped_not_crashed() -> None:
    text = (
        "# Time: 2026-07-15T06:00:00.000Z\n"
        "# User@Host: app[app] @  [10.0.3.1]\n"
        "# Query_time: 1.2.3  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 5\n"
        "SET timestamp=1752559200;\n"
        "SELECT 1;\n"
        "# Time: 2026-07-15T06:01:00.000Z\n"
        "# User@Host: app[app] @  [10.0.3.1]\n"
        "# Query_time: 2.0  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 5\n"
        "SELECT 2;\n"
    )

    result = parse_log_text(text)

    assert result.skipped == 1
    assert len(result.entries) == 1
    assert result.entries[0].sql == "SELECT 2"


def test_unparseable_timestamp_is_skipped_not_crashed() -> None:
    text = (
        "# Time: not-a-timestamp\n"
        "# User@Host: app[app] @  [10.0.3.1]\n"
        "# Query_time: 1.0  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 5\n"
        "SELECT 1;\n"
    )

    result = parse_log_text(text)

    assert result.entries == []
    assert result.skipped == 1


def test_unrecognized_comment_line_is_ignored() -> None:
    text = (
        "# Time: 2026-07-15T06:02:00.000Z\n"
        "# User@Host: app[app] @  [10.0.3.1]\n"
        "# Some-Other-Header: value\n"
        "# Query_time: 1.0  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 5\n"
        "SELECT 1;\n"
    )

    result = parse_log_text(text)

    assert len(result.entries) == 1
    assert result.entries[0].sql == "SELECT 1"


def test_blank_lines_within_a_record_are_ignored() -> None:
    text = (
        "# Time: 2026-07-15T06:03:00.000Z\n"
        "\n"
        "# User@Host: app[app] @  [10.0.3.1]\n"
        "\n"
        "# Query_time: 1.0  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 5\n"
        "\n"
        "SELECT 1;\n"
    )

    result = parse_log_text(text)

    assert len(result.entries) == 1
    assert result.entries[0].sql == "SELECT 1"


def test_sql_that_reduces_to_empty_string_is_skipped() -> None:
    text = (
        "# Time: 2026-07-15T06:04:00.000Z\n"
        "# User@Host: app[app] @  [10.0.3.1]\n"
        "# Query_time: 1.0  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 5\n"
        ";\n"
    )

    result = parse_log_text(text)

    assert result.entries == []
    assert result.skipped == 1


def test_parse_events_handles_multiline_entry_split_across_multiple_events() -> None:
    events = [
        "# Time: 2026-07-15T05:00:00.000Z\n# User@Host: app[app] @  [10.0.2.1]",
        "# Query_time: 4.0  Lock_time: 0.0  Rows_sent: 1  Rows_examined: 10",
        "SET timestamp=1752556800;\nSELECT a\nFROM b\nWHERE c = 1;",
    ]

    result = parse_events(events)

    assert len(result.entries) == 1
    assert result.entries[0].sql == "SELECT a FROM b WHERE c = 1"
