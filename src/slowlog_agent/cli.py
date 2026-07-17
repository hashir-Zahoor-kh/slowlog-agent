"""CLI entrypoint: `slowlog analyze`, `slowlog doctor`, and `slowlog init`."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import click

from slowlog_agent import __version__, analyzer, fetcher, init_wizard, parser
from slowlog_agent import digest as digest_mod
from slowlog_agent import doctor as doctor_mod
from slowlog_agent import report as report_mod
from slowlog_agent.backends import get_backend
from slowlog_agent.config import load_settings
from slowlog_agent.errors import ConfigError, SlowlogError
from slowlog_agent.schemas import AnalysisReport

EXIT_OK = 0
EXIT_NO_SLOW_QUERIES = 2
EXIT_UNEXPECTED_ERROR = 1

_SEVERITY_COLOR = {"critical": "red", "high": "red", "medium": "yellow", "low": "cyan"}


@click.group()
@click.version_option(version=__version__, prog_name="slowlog")
def main() -> None:
    """slowlog: on-demand MySQL slow query log analysis."""


@main.command()
@click.option(
    "--hours", type=int, default=None, help="Lookback window in hours (overrides config)."
)
@click.option("--top", "top_n", type=int, default=None, help="Number of query patterns to analyze.")
@click.option("--no-db", is_flag=True, default=False, help="Skip EXPLAIN even if a DB DSN is set.")
@click.option("--json-only", is_flag=True, default=False, help="Write only the JSON report.")
def analyze(hours: int | None, top_n: int | None, no_db: bool, json_only: bool) -> None:
    """Fetch, parse, digest, and analyze the slow query log."""
    try:
        settings = load_settings()

        window_hours = hours if hours is not None else settings.window_hours
        effective_top_n = top_n if top_n is not None else settings.top_n
        end = datetime.now(UTC)
        start = end - timedelta(hours=window_hours)

        client = fetcher.build_client(region=settings.aws_region, profile=settings.aws_profile)
        events = fetcher.fetch_events(
            client, settings.log_group_name, start, end, profile=settings.aws_profile
        )
        parse_result = parser.parse_events(events)

        if not parse_result.entries:
            click.echo(
                f"No slow queries found in the last {window_hours}h in "
                f"'{settings.log_group_name}'. Clean bill of health."
            )
            sys.exit(EXIT_NO_SLOW_QUERIES)

        digest = digest_mod.build_digest(
            parse_result.entries,
            parse_skipped=parse_result.skipped,
            window_start=start,
            window_end=end,
            top_n=effective_top_n,
        )

        effective_db_dsn = None if no_db else settings.db_dsn
        backend = get_backend(settings.agent_backend)
        analysis = analyzer.analyze(
            digest,
            db_dsn=effective_db_dsn,
            timeout=settings.agent_timeout_seconds,
            output_dir=settings.output_dir,
            backend=backend,
        )

        settings.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = end.strftime("%Y%m%dT%H%M%SZ")
        json_path = settings.output_dir / f"report_{timestamp}.json"
        json_path.write_text(analysis.model_dump_json(indent=2))

        if json_only:
            click.echo(f"Wrote {json_path}")
        else:
            md_path = settings.output_dir / f"report_{timestamp}.md"
            md_path.write_text(report_mod.render_markdown(analysis, digest, generated_at=end))
            click.echo(f"Wrote {json_path} and {md_path}")

        _print_top_findings(analysis)
        sys.exit(EXIT_OK)
    except SlowlogError as exc:
        _print_error(exc)
        sys.exit(exc.exit_code)
    except Exception as exc:  # noqa: BLE001 - last-resort safety net, never a bare traceback
        _handle_unexpected(exc)


@main.command()
def doctor() -> None:
    """Run preflight checks: AWS credentials, log group, claude binary, DB DSN."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        doctor_mod.print_check("FAIL", "configuration", exc.message, exc.remediation)
        sys.exit(EXIT_UNEXPECTED_ERROR)

    try:
        doctor_mod.print_check("OK", "configuration", "settings loaded successfully")
        all_ok = doctor_mod.run_doctor_checks(settings)
        sys.exit(EXIT_OK if all_ok else EXIT_UNEXPECTED_ERROR)
    except SlowlogError as exc:
        _print_error(exc)
        sys.exit(exc.exit_code)
    except Exception as exc:  # noqa: BLE001 - last-resort safety net, never a bare traceback
        _handle_unexpected(exc)


@main.command()
def init() -> None:
    """Interactive setup wizard: pick an AWS profile, log group, and DB DSN."""
    try:
        sys.exit(init_wizard.run_init())
    except Exception as exc:  # noqa: BLE001 - last-resort safety net, never a bare traceback
        _handle_unexpected(exc)


def _print_error(exc: SlowlogError) -> None:
    click.secho(f"Error: {exc.message}", fg="red", err=True)
    click.secho(f"  -> {exc.remediation}", fg="yellow", err=True)


def _handle_unexpected(exc: Exception) -> None:
    click.secho(f"Error: unexpected failure: {exc}", fg="red", err=True)
    click.secho(
        "  -> This looks like a bug in slowlog-agent. Please file an issue with the "
        "output above at https://github.com/hashir-Zahoor-kh/slowlog-agent/issues.",
        fg="yellow",
        err=True,
    )
    sys.exit(EXIT_UNEXPECTED_ERROR)


def _print_top_findings(analysis: AnalysisReport) -> None:
    top = analysis.findings[:3]
    if not top:
        click.echo("\nNo findings.")
        return
    click.echo("\nTop findings:")
    for i, finding in enumerate(top, start=1):
        color = _SEVERITY_COLOR.get(finding.severity, "white")
        click.secho(f"{i}. [{finding.severity.upper()}] {finding.fingerprint}", fg=color, bold=True)
        click.echo(f"   {finding.problem}")
