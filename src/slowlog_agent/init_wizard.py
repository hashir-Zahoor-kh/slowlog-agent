"""Interactive `slowlog init` onboarding wizard.

Picks an AWS profile, a CloudWatch log group, and (optionally) a read-only DB
DSN, writes slowlog.toml, then runs the same checks as `slowlog doctor` as a
final confirmation. Every external call (AWS, DB, `claude` on PATH) degrades
to a clear prompt or warning rather than crashing the wizard.
"""

from __future__ import annotations

import configparser
import shutil
from pathlib import Path
from typing import Literal

import click
import questionary
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from slowlog_agent import db, fetcher
from slowlog_agent import doctor as doctor_mod
from slowlog_agent.config import DEFAULT_CONFIG_FILENAME, Settings

_CLOUDWATCH_AGENT_SNIPPET = """
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/mysql/mysql-slow.log",
            "log_group_name": "/mysql/slow-query-log",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%y-%m-%d %H:%M:%S"
          }
        ]
      }
    }
  }
}
""".strip()

_TYPE_MANUALLY_OPTION = "(type a different profile name)"


def list_aws_profiles() -> list[str]:
    profiles: set[str] = set()
    for path in (Path.home() / ".aws" / "config", Path.home() / ".aws" / "credentials"):
        if not path.exists():
            continue
        cfg = configparser.ConfigParser()
        cfg.read(path)
        for section in cfg.sections():
            if section == "default":
                profiles.add("default")
            elif section.startswith("profile "):
                profiles.add(section.removeprefix("profile "))
            else:
                profiles.add(section)
    return sorted(profiles)


def list_log_groups(*, region: str, profile: str) -> list[str]:
    client = fetcher.build_client(region=region, profile=profile)
    names: list[str] = []
    paginator = client.get_paginator("describe_log_groups")
    for page in paginator.paginate():
        names.extend(group["logGroupName"] for group in page.get("logGroups", []))
    return names


def run_init() -> int:
    click.secho("slowlog init — let's get you set up.\n", bold=True)

    profile = _pick_aws_profile()
    region = _pick_region(profile)
    log_group_name = _pick_log_group(region=region, profile=profile)
    db_dsn = _maybe_configure_db_dsn()
    agent_backend = _pick_agent_backend()

    _write_config(
        log_group_name=log_group_name,
        aws_region=region,
        aws_profile=profile,
        db_dsn=db_dsn,
        agent_backend=agent_backend,
    )
    click.secho(f"\nWrote {DEFAULT_CONFIG_FILENAME}\n", fg="green")

    click.secho("Running the same checks as `slowlog doctor`...\n", bold=True)
    settings = Settings(
        log_group_name=log_group_name,
        aws_region=region,
        aws_profile=profile,
        db_dsn=db_dsn,
        agent_backend=agent_backend,
    )
    doctor_mod.print_check("OK", "configuration", "settings loaded successfully")
    all_ok = doctor_mod.run_doctor_checks(settings)
    return 0 if all_ok else 1


def _pick_aws_profile() -> str:
    profiles = list_aws_profiles()
    if profiles:
        choice = questionary.select(
            "Which AWS profile should slowlog-agent use?",
            choices=[*profiles, _TYPE_MANUALLY_OPTION],
        ).ask()
        if choice != _TYPE_MANUALLY_OPTION:
            return str(choice)
    return str(questionary.text("AWS profile name:", default="default").ask())


def _pick_region(profile: str) -> str:
    default_region = _profile_default_region(profile) or "us-east-1"
    return str(questionary.text("AWS region the log group lives in:", default=default_region).ask())


def _profile_default_region(profile: str) -> str | None:
    path = Path.home() / ".aws" / "config"
    if not path.exists():
        return None
    cfg = configparser.ConfigParser()
    cfg.read(path)
    section = "default" if profile == "default" else f"profile {profile}"
    if cfg.has_section(section) and cfg.has_option(section, "region"):
        return cfg.get(section, "region")
    return None


def _pick_log_group(*, region: str, profile: str) -> str:
    click.echo(f"\nLooking up CloudWatch log groups in {region} (profile '{profile}')...")
    try:
        log_groups = list_log_groups(region=region, profile=profile)
    except (ClientError, NoCredentialsError, ProfileNotFound) as exc:
        click.secho(f"Could not list log groups: {exc}", fg="yellow")
        log_groups = []

    if not log_groups:
        click.secho(
            "\nNo CloudWatch log groups found (or slowlog-agent couldn't list them).", fg="yellow"
        )
        click.echo(
            "If the MySQL slow query log isn't shipping to CloudWatch yet, add this to the "
            "CloudWatch agent config on your MySQL host and restart the agent:\n"
        )
        click.echo(_CLOUDWATCH_AGENT_SNIPPET)
        click.echo()
        return str(questionary.text("Log group name to use once it exists:").ask())

    return str(
        questionary.autocomplete("Select the slow-query log group:", choices=log_groups).ask()
    )


def _maybe_configure_db_dsn() -> str | None:
    if not questionary.confirm(
        "\nConfigure a read-only DB DSN so the agent can run live EXPLAIN? (recommended)",
        default=True,
    ).ask():
        return None

    dsn = questionary.text(
        "Read-only DB DSN (e.g. mysql://readonly_user:pass@host:3306/dbname):"
    ).ask()
    if not dsn:
        return None
    dsn = str(dsn)

    click.echo("Checking connectivity...")
    ok, message = db.check_db_dsn(dsn)
    if not ok:
        click.secho(f"Could not connect: {message}", fg="red")
        click.echo("Skipping DB DSN — you can add db_dsn to slowlog.toml manually later.")
        return None

    click.secho("Connected.", fg="green")
    click.echo("Checking that this user has no write privileges...")
    try:
        is_read_only, offending = db.check_no_write_grants(dsn)
    except Exception as exc:  # noqa: BLE001 - a SHOW GRANTS failure shouldn't abort the wizard
        click.secho(f"Could not verify grants: {exc}", fg="yellow")
        return dsn

    if is_read_only:
        click.secho("Confirmed: this user has no write privileges.", fg="green")
        return dsn

    click.secho("\nWARNING: this DB user has write/DDL privileges:", fg="red", bold=True)
    for grant in offending:
        click.secho(f"  {grant}", fg="red")
    click.echo(
        "slowlog-agent only ever runs SELECT/EXPLAIN, but a write-capable user is still a "
        "real risk if anything goes wrong. Prefer a dedicated user:\n"
        "  GRANT SELECT, SHOW VIEW ON *.* TO 'slowlog_readonly'@'%' IDENTIFIED BY '...';\n"
    )
    if questionary.confirm("Use this DSN anyway?", default=False).ask():
        return dsn
    click.echo("Skipping DB DSN — you can add db_dsn to slowlog.toml manually later.")
    return None


def _pick_agent_backend() -> Literal["claude", "copilot"]:
    claude_present = shutil.which("claude") is not None
    copilot_present = shutil.which("copilot") is not None

    if claude_present and copilot_present:
        choice = questionary.select(
            "\nBoth `claude` and `copilot` are on PATH. Which should slowlog-agent use?",
            choices=["claude", "copilot"],
        ).ask()
        return "copilot" if choice == "copilot" else "claude"

    if claude_present:
        click.secho("\n`claude` binary found on PATH; using it as the agent backend.", fg="green")
        return "claude"

    if copilot_present:
        click.secho("\n`copilot` binary found on PATH; using it as the agent backend.", fg="green")
        return "copilot"

    click.secho("\nNeither `claude` nor `copilot` was found on PATH.", fg="yellow")
    click.echo("Install Claude Code:    npm install -g @anthropic-ai/claude-code")
    click.echo("Install Copilot CLI:    https://docs.github.com/copilot/github-copilot-in-the-cli")
    click.echo(
        '(defaulting agent_backend to "claude" — `slowlog doctor` will flag it as missing)\n'
    )
    return "claude"


def _write_config(
    *,
    log_group_name: str,
    aws_region: str,
    aws_profile: str,
    db_dsn: str | None,
    agent_backend: str,
) -> None:
    lines = [
        "# Generated by `slowlog init`. Env vars prefixed SLOWLOG_ override these.",
        f'log_group_name = "{_toml_escape(log_group_name)}"',
        f'aws_region = "{_toml_escape(aws_region)}"',
        f'aws_profile = "{_toml_escape(aws_profile)}"',
        f'agent_backend = "{_toml_escape(agent_backend)}"',
    ]
    if db_dsn:
        lines.append(f'db_dsn = "{_toml_escape(db_dsn)}"')
    Path(DEFAULT_CONFIG_FILENAME).write_text("\n".join(lines) + "\n")


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
