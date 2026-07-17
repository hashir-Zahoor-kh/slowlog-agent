from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from slowlog_agent.cli import main
from slowlog_agent.config import Settings
from slowlog_agent.errors import AgentError, ConfigError, FetchError
from slowlog_agent.schemas import AnalysisReport, Finding

RAW_EVENTS = [
    "# Time: 2026-07-15T04:12:33.001Z",
    "# User@Host: app[app] @  [10.0.1.5]",
    "# Query_time: 12.4  Lock_time: 0.001  Rows_sent: 3  Rows_examined: 4400312",
    "SET timestamp=1752552753;",
    "SELECT * FROM orders WHERE customer_email LIKE '%gmail%';",
]


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "log_group_name": "/aws/rds/slowquery",
        "aws_region": "us-east-1",
        "aws_profile": "readonly",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _report() -> AnalysisReport:
    return AnalysisReport(
        findings=[
            Finding(
                fingerprint="select * from orders where customer_email like ?",
                severity="critical",
                problem="Full table scan.",
                evidence="rows=4400312",
                recommendation="Add an index.",
                suggested_ddl="CREATE INDEX idx ON orders (customer_email);",
                estimated_impact="Big win.",
            )
        ],
        summary="One critical finding.",
        analyzed_patterns=1,
        db_verified=False,
    )


class _Patched:
    """Context manager bundling the standard set of analyze()-path patches."""

    def __enter__(self) -> "_Patched":
        self.load_settings = patch("slowlog_agent.cli.load_settings").start()
        self.build_client = patch("slowlog_agent.cli.fetcher.build_client").start()
        self.fetch_events = patch("slowlog_agent.cli.fetcher.fetch_events").start()
        self.analyze = patch("slowlog_agent.cli.analyzer.analyze").start()

        self.load_settings.return_value = _settings()
        self.build_client.return_value = MagicMock()
        self.fetch_events.return_value = list(RAW_EVENTS)
        self.analyze.return_value = _report()
        return self

    def __exit__(self, *exc: object) -> None:
        patch.stopall()


# --- analyze: happy path -----------------------------------------------------


def test_analyze_success_writes_reports_and_exits_0(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 0, result.output
    json_files = list(tmp_path.glob("report_*.json"))
    md_files = list(tmp_path.glob("report_*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1
    assert "Top findings" in result.output
    assert "CRITICAL" in result.output
    assert "customer_email" in result.output


def test_analyze_json_only_skips_markdown(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        result = runner.invoke(main, ["analyze", "--json-only"])

    assert result.exit_code == 0, result.output
    assert len(list(tmp_path.glob("report_*.json"))) == 1
    assert len(list(tmp_path.glob("report_*.md"))) == 0


def test_analyze_no_db_flag_forces_db_dsn_none(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path, db_dsn="mysql://u@h/db")
        runner.invoke(main, ["analyze", "--no-db"])

    assert p.analyze.call_args.kwargs["db_dsn"] is None


def test_analyze_hours_and_top_options_override_config(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path, window_hours=24, top_n=10)
        result = runner.invoke(main, ["analyze", "--hours", "6", "--top", "3"])

    assert result.exit_code == 0, result.output
    fetch_call = p.fetch_events.call_args
    start, end = fetch_call.args[2], fetch_call.args[3]
    assert (end - start).total_seconds() == 6 * 3600


# --- analyze: exit codes ------------------------------------------------------


def test_analyze_config_error_exits_5() -> None:
    runner = CliRunner()
    with patch("slowlog_agent.cli.load_settings") as load_settings:
        load_settings.side_effect = ConfigError("No configuration found.", "Run `slowlog init`.")
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 5
    assert "slowlog init" in result.output


def test_analyze_fetch_error_exits_3(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        p.fetch_events.side_effect = FetchError("Log group not found.", "Check the name.")
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 3
    assert "Log group not found" in result.output


def test_analyze_agent_error_exits_4(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        p.analyze.side_effect = AgentError("Agent failed.", "Retry later.")
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 4
    assert "Agent failed" in result.output


def test_analyze_no_slow_queries_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        p.fetch_events.return_value = []
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 2
    assert "Clean bill of health" in result.output
    assert list(tmp_path.glob("report_*")) == []


def test_analyze_unexpected_exception_exits_1_with_remediation(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        p.analyze.side_effect = RuntimeError("kaboom")
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 1
    assert "unexpected failure" in result.output
    assert "issue" in result.output.lower()


# --- doctor --------------------------------------------------------------------


def test_doctor_all_checks_pass_exits_0() -> None:
    runner = CliRunner()
    with (
        patch("slowlog_agent.cli.load_settings") as load_settings,
        patch("slowlog_agent.doctor.fetcher.build_client") as build_client,
        patch("slowlog_agent.doctor.shutil.which", return_value="/usr/local/bin/claude"),
    ):
        load_settings.return_value = _settings()
        build_client.return_value = MagicMock()

        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "[  OK] configuration" in result.output
    assert "[  OK] claude" in result.output
    assert "[SKIP] database" in result.output


def test_doctor_config_error_exits_1() -> None:
    runner = CliRunner()
    with patch("slowlog_agent.cli.load_settings") as load_settings:
        load_settings.side_effect = ConfigError("No configuration found.", "Run `slowlog init`.")
        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert "slowlog init" in result.output


def test_doctor_aws_failure_exits_1() -> None:
    from botocore.exceptions import ClientError

    runner = CliRunner()
    with (
        patch("slowlog_agent.cli.load_settings") as load_settings,
        patch("slowlog_agent.doctor.fetcher.build_client") as build_client,
        patch("slowlog_agent.doctor.shutil.which", return_value="/usr/local/bin/claude"),
    ):
        load_settings.return_value = _settings()
        client = MagicMock()
        client.describe_log_groups.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}}, "DescribeLogGroups"
        )
        build_client.return_value = client

        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert "[FAIL] AWS" in result.output


def test_doctor_claude_missing_exits_1() -> None:
    runner = CliRunner()
    with (
        patch("slowlog_agent.cli.load_settings") as load_settings,
        patch("slowlog_agent.doctor.fetcher.build_client") as build_client,
        patch("slowlog_agent.doctor.shutil.which", return_value=None),
    ):
        load_settings.return_value = _settings()
        build_client.return_value = MagicMock()

        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert "[FAIL] claude" in result.output


def test_doctor_db_dsn_ok() -> None:
    runner = CliRunner()
    with (
        patch("slowlog_agent.cli.load_settings") as load_settings,
        patch("slowlog_agent.doctor.fetcher.build_client") as build_client,
        patch("slowlog_agent.doctor.shutil.which", return_value="/usr/local/bin/claude"),
        patch("slowlog_agent.doctor.db.check_db_dsn", return_value=(True, "connected")),
    ):
        load_settings.return_value = _settings(db_dsn="mysql://u:p@localhost/db")
        build_client.return_value = MagicMock()

        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "[  OK] database" in result.output


def test_doctor_db_dsn_failure_exits_1() -> None:
    runner = CliRunner()
    with (
        patch("slowlog_agent.cli.load_settings") as load_settings,
        patch("slowlog_agent.doctor.fetcher.build_client") as build_client,
        patch("slowlog_agent.doctor.shutil.which", return_value="/usr/local/bin/claude"),
        patch("slowlog_agent.doctor.db.check_db_dsn", return_value=(False, "connection refused")),
    ):
        load_settings.return_value = _settings(db_dsn="mysql://u:p@localhost/db")
        build_client.return_value = MagicMock()

        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert "[FAIL] database" in result.output
    assert "connection refused" in result.output


def test_analyze_no_findings_prints_no_findings_message(tmp_path: Path) -> None:
    runner = CliRunner()
    with _Patched() as p:
        p.load_settings.return_value = _settings(output_dir=tmp_path)
        p.analyze.return_value = AnalysisReport(
            findings=[], summary="Nothing to report.", analyzed_patterns=1, db_verified=False
        )
        result = runner.invoke(main, ["analyze"])

    assert result.exit_code == 0, result.output
    assert "No findings." in result.output


def test_doctor_unexpected_exception_exits_1_with_remediation() -> None:
    runner = CliRunner()
    with (
        patch("slowlog_agent.cli.load_settings") as load_settings,
        patch("slowlog_agent.cli.doctor_mod.run_doctor_checks") as run_doctor_checks,
    ):
        load_settings.return_value = _settings()
        run_doctor_checks.side_effect = RuntimeError("kaboom")

        result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert "unexpected failure" in result.output
    assert "issue" in result.output.lower()


# --- init ------------------------------------------------------------------------


def test_init_command_delegates_to_wizard_and_uses_its_exit_code() -> None:
    runner = CliRunner()
    with patch("slowlog_agent.cli.init_wizard.run_init", return_value=0) as run_init:
        result = runner.invoke(main, ["init"])

    assert result.exit_code == 0
    run_init.assert_called_once()


def test_init_command_nonzero_exit_when_wizard_reports_failure() -> None:
    runner = CliRunner()
    with patch("slowlog_agent.cli.init_wizard.run_init", return_value=1):
        result = runner.invoke(main, ["init"])

    assert result.exit_code == 1


def test_init_unexpected_exception_exits_1_with_remediation() -> None:
    runner = CliRunner()
    with patch("slowlog_agent.cli.init_wizard.run_init", side_effect=RuntimeError("kaboom")):
        result = runner.invoke(main, ["init"])

    assert result.exit_code == 1
    assert "unexpected failure" in result.output
    assert "issue" in result.output.lower()


# --- version -------------------------------------------------------------------


def test_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])

    assert result.exit_code == 0
    assert "slowlog" in result.output
