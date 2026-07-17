import contextlib
from unittest.mock import MagicMock, patch

from slowlog_agent import db


def test_check_db_dsn_reports_failure_for_unreachable_host() -> None:
    ok, message = db.check_db_dsn("mysql://baduser:badpass@127.0.0.1:1/nonexistent")

    assert ok is False
    assert message


def test_check_db_dsn_success() -> None:
    with patch("slowlog_agent.db.connect") as connect:
        connect.return_value = MagicMock()

        ok, message = db.check_db_dsn("mysql://u:p@host:3306/db")

    assert ok is True
    assert message == "connected"


def test_connect_parses_dsn_components() -> None:
    with patch("slowlog_agent.db.pymysql.connect") as pymysql_connect:
        db.connect("mysql://readonly:secret@dbhost:3307/mydb")

        pymysql_connect.assert_called_once_with(
            host="dbhost",
            port=3307,
            user="readonly",
            password="secret",
            database="mydb",
            connect_timeout=5,
        )


def test_connect_uses_defaults_when_dsn_parts_missing() -> None:
    with patch("slowlog_agent.db.pymysql.connect") as pymysql_connect:
        db.connect("mysql:///")

        pymysql_connect.assert_called_once_with(
            host="localhost",
            port=3306,
            user="",
            password="",
            database=None,
            connect_timeout=5,
        )


def test_check_no_write_grants_reports_read_only_user() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [("GRANT SELECT, SHOW VIEW ON `db`.* TO `ro`@`%`",)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    with patch("slowlog_agent.db.connect", return_value=conn):
        is_read_only, offending = db.check_no_write_grants("mysql://ro@host/db")

    assert is_read_only is True
    assert offending == []
    conn.close.assert_called_once()


def test_check_no_write_grants_flags_write_privileges() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("GRANT SELECT, SHOW VIEW ON `db`.* TO `rw`@`%`",),
        ("GRANT INSERT, UPDATE, DELETE ON `db`.* TO `rw`@`%`",),
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    with patch("slowlog_agent.db.connect", return_value=conn):
        is_read_only, offending = db.check_no_write_grants("mysql://rw@host/db")

    assert is_read_only is False
    assert len(offending) == 1
    assert "INSERT" in offending[0]


def test_check_no_write_grants_closes_connection_even_on_cursor_error() -> None:
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("boom")

    with (
        patch("slowlog_agent.db.connect", return_value=conn),
        contextlib.suppress(RuntimeError),
    ):
        db.check_no_write_grants("mysql://x@host/db")

    conn.close.assert_called_once()
