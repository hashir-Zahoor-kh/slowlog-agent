"""Read-only DB DSN connectivity and privilege checks, shared by doctor and init."""

from __future__ import annotations

from urllib.parse import urlparse

import pymysql

_WRITE_PRIVILEGE_MARKERS = (
    "ALL PRIVILEGES",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "DROP",
    "ALTER",
    "GRANT OPTION",
    "INDEX",
    "REFERENCES",
    "TRIGGER",
    "LOCK TABLES",
    "EXECUTE",
    "REPLICATION",
    "EVENT",
    "SHUTDOWN",
    "PROCESS",
    "FILE",
    "SUPER",
    "RELOAD",
)


def connect(dsn: str) -> pymysql.connections.Connection:
    parsed = urlparse(dsn)
    return pymysql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=parsed.username or "",
        password=parsed.password or "",
        database=parsed.path.lstrip("/") or None,
        connect_timeout=5,
    )


def check_db_dsn(dsn: str) -> tuple[bool, str]:
    """Attempt a connection. Returns (ok, detail-or-error-message)."""
    try:
        conn = connect(dsn)
        conn.close()
        return True, "connected"
    except Exception as exc:  # noqa: BLE001 - surfacing any connection failure to the user
        return False, str(exc)


def check_no_write_grants(dsn: str) -> tuple[bool, list[str]]:
    """Returns (is_read_only, offending_grant_lines). Raises if the connection fails."""
    conn = connect(dsn)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            grants = [str(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()

    offending = [
        grant
        for grant in grants
        if any(marker in grant.upper() for marker in _WRITE_PRIVILEGE_MARKERS)
    ]
    return (len(offending) == 0, offending)
