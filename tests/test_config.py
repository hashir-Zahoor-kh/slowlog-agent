from pathlib import Path

import pytest

from slowlog_agent.config import load_settings
from slowlog_agent.errors import ConfigError

REQUIRED_ENV = {
    "SLOWLOG_LOG_GROUP_NAME": "/aws/rds/slowquery",
    "SLOWLOG_AWS_REGION": "us-east-1",
    "SLOWLOG_AWS_PROFILE": "prod",
}


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in [*REQUIRED_ENV, "SLOWLOG_DB_DSN", "SLOWLOG_WINDOW_HOURS", "SLOWLOG_TOP_N"]:
        monkeypatch.delenv(key, raising=False)


def test_loads_from_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    settings = load_settings()

    assert settings.log_group_name == "/aws/rds/slowquery"
    assert settings.aws_region == "us-east-1"
    assert settings.aws_profile == "prod"
    assert settings.window_hours == 24
    assert settings.top_n == 10
    assert settings.output_dir == Path("./reports")
    assert settings.agent_backend == "claude"
    assert settings.db_dsn is None


def test_loads_from_toml(tmp_path: Path) -> None:
    (tmp_path / "slowlog.toml").write_text(
        """
        log_group_name = "/aws/rds/slowquery"
        aws_region = "us-west-2"
        aws_profile = "readonly"
        window_hours = 48
        top_n = 5
        """
    )

    settings = load_settings()

    assert settings.aws_region == "us-west-2"
    assert settings.window_hours == 48
    assert settings.top_n == 5


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "slowlog.toml").write_text(
        """
        log_group_name = "/aws/rds/slowquery"
        aws_region = "us-west-2"
        aws_profile = "readonly"
        """
    )
    monkeypatch.setenv("SLOWLOG_AWS_REGION", "eu-central-1")

    settings = load_settings()

    assert settings.aws_region == "eu-central-1"
    assert settings.aws_profile == "readonly"


def test_no_config_anywhere_raises_first_run_error() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings()

    assert "slowlog init" in exc_info.value.remediation


def test_incomplete_config_names_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLOWLOG_LOG_GROUP_NAME", "/aws/rds/slowquery")

    with pytest.raises(ConfigError) as exc_info:
        load_settings()

    assert "aws_region" in exc_info.value.message
    assert "aws_profile" in exc_info.value.message
    assert "slowlog.toml" in exc_info.value.remediation
