from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from slowlog_agent import doctor
from slowlog_agent.config import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "log_group_name": "/aws/rds/slowquery",
        "aws_region": "us-east-1",
        "aws_profile": "readonly",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_run_doctor_checks_all_pass_without_db_dsn() -> None:
    with (
        patch("slowlog_agent.doctor.fetcher.build_client") as build_client,
        patch("slowlog_agent.backends.claude.shutil.which", return_value="/usr/bin/claude"),
    ):
        build_client.return_value = MagicMock()

        assert doctor.run_doctor_checks(_settings()) is True


def test_run_doctor_checks_aws_failure() -> None:
    client = MagicMock()
    client.describe_log_groups.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "DescribeLogGroups"
    )
    with (
        patch("slowlog_agent.doctor.fetcher.build_client", return_value=client),
        patch("slowlog_agent.backends.claude.shutil.which", return_value="/usr/bin/claude"),
    ):
        assert doctor.run_doctor_checks(_settings()) is False


def test_run_doctor_checks_claude_missing() -> None:
    with (
        patch("slowlog_agent.doctor.fetcher.build_client", return_value=MagicMock()),
        patch("slowlog_agent.backends.claude.shutil.which", return_value=None),
    ):
        assert doctor.run_doctor_checks(_settings()) is False


def test_run_doctor_checks_uses_configured_backend() -> None:
    with (
        patch("slowlog_agent.doctor.fetcher.build_client", return_value=MagicMock()),
        patch("slowlog_agent.backends.copilot.shutil.which", return_value="/usr/bin/copilot"),
    ):
        assert doctor.run_doctor_checks(_settings(agent_backend="copilot")) is True


def test_run_doctor_checks_copilot_missing() -> None:
    with (
        patch("slowlog_agent.doctor.fetcher.build_client", return_value=MagicMock()),
        patch("slowlog_agent.backends.copilot.shutil.which", return_value=None),
    ):
        assert doctor.run_doctor_checks(_settings(agent_backend="copilot")) is False


def test_run_doctor_checks_db_dsn_ok() -> None:
    with (
        patch("slowlog_agent.doctor.fetcher.build_client", return_value=MagicMock()),
        patch("slowlog_agent.backends.claude.shutil.which", return_value="/usr/bin/claude"),
        patch("slowlog_agent.doctor.db.check_db_dsn", return_value=(True, "connected")),
    ):
        assert doctor.run_doctor_checks(_settings(db_dsn="mysql://u@h/db")) is True


def test_run_doctor_checks_db_dsn_failure() -> None:
    with (
        patch("slowlog_agent.doctor.fetcher.build_client", return_value=MagicMock()),
        patch("slowlog_agent.backends.claude.shutil.which", return_value="/usr/bin/claude"),
        patch("slowlog_agent.doctor.db.check_db_dsn", return_value=(False, "refused")),
    ):
        assert doctor.run_doctor_checks(_settings(db_dsn="mysql://u@h/db")) is False


def test_print_check_handles_all_known_statuses() -> None:
    doctor.print_check("OK", "thing", "detail")
    doctor.print_check("FAIL", "thing", "detail", "fix it")
    doctor.print_check("SKIP", "thing", "detail")
