"""Preflight checks shared by `slowlog doctor` and the final step of `slowlog init`."""

from __future__ import annotations

import shutil

import click
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from slowlog_agent import db, fetcher
from slowlog_agent.config import Settings


def print_check(status: str, name: str, detail: str, remediation: str | None = None) -> None:
    color = {"OK": "green", "FAIL": "red", "SKIP": "yellow"}[status]
    click.secho(f"[{status:>4}] {name}: {detail}", fg=color)
    if remediation:
        click.echo(f"       -> {remediation}")


def run_doctor_checks(settings: Settings) -> bool:
    """Run the AWS/claude/DB preflight checks, printing pass/fail as it goes.

    Assumes settings already loaded successfully (config itself isn't
    re-checked here — the caller handles that, since it differs slightly
    between `slowlog doctor` and `slowlog init`).
    """
    all_ok = True

    try:
        client = fetcher.build_client(region=settings.aws_region, profile=settings.aws_profile)
        client.describe_log_groups(logGroupNamePrefix=settings.log_group_name, limit=1)
        print_check("OK", "AWS", f"profile '{settings.aws_profile}' can reach CloudWatch Logs")
    except (ClientError, NoCredentialsError, ProfileNotFound) as exc:
        all_ok = False
        print_check(
            "FAIL",
            "AWS",
            str(exc),
            f"Verify AWS profile '{settings.aws_profile}' exists (~/.aws/config) and has "
            "logs:DescribeLogGroups permission on this log group.",
        )

    if shutil.which("claude"):
        print_check("OK", "claude", "binary found on PATH")
    else:
        all_ok = False
        print_check(
            "FAIL",
            "claude",
            "binary not found on PATH",
            "Install Claude Code: https://docs.claude.com/claude-code",
        )

    if settings.db_dsn:
        ok, message = db.check_db_dsn(settings.db_dsn)
        if ok:
            print_check("OK", "database", "DSN connects")
        else:
            all_ok = False
            print_check(
                "FAIL",
                "database",
                message,
                "Verify the DB DSN and that the user has SELECT/SHOW VIEW privileges.",
            )
    else:
        print_check(
            "SKIP", "database", "no db_dsn configured; analysis will run without live EXPLAIN"
        )

    return all_ok
