from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slowlog_agent import init_wizard


def _ask(value: object) -> MagicMock:
    """Build a fake questionary Question whose .ask() returns `value`."""
    q = MagicMock()
    q.ask.return_value = value
    return q


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- list_aws_profiles -----------------------------------------------------------


def test_list_aws_profiles_reads_config_and_credentials(_isolated_home: Path) -> None:
    aws_dir = _isolated_home / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text(
        "[default]\nregion = us-east-1\n\n[profile readonly]\nregion = us-west-2\n"
    )
    (aws_dir / "credentials").write_text(
        "[default]\naws_access_key_id = x\n\n[prod]\naws_access_key_id = y\n"
    )

    profiles = init_wizard.list_aws_profiles()

    assert profiles == ["default", "prod", "readonly"]


def test_list_aws_profiles_empty_when_no_aws_dir(_isolated_home: Path) -> None:
    assert init_wizard.list_aws_profiles() == []


# --- list_log_groups ---------------------------------------------------------------


def test_list_log_groups_paginates() -> None:
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"logGroups": [{"logGroupName": "/a"}, {"logGroupName": "/b"}]},
        {"logGroups": [{"logGroupName": "/c"}]},
    ]
    client.get_paginator.return_value = paginator

    with patch("slowlog_agent.init_wizard.fetcher.build_client", return_value=client):
        names = init_wizard.list_log_groups(region="us-east-1", profile="default")

    assert names == ["/a", "/b", "/c"]


# --- _profile_default_region --------------------------------------------------------


def test_profile_default_region_from_default_section(_isolated_home: Path) -> None:
    aws_dir = _isolated_home / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("[default]\nregion = eu-west-1\n")

    assert init_wizard._profile_default_region("default") == "eu-west-1"


def test_profile_default_region_from_named_profile(_isolated_home: Path) -> None:
    aws_dir = _isolated_home / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("[profile readonly]\nregion = ap-south-1\n")

    assert init_wizard._profile_default_region("readonly") == "ap-south-1"


def test_profile_default_region_missing_returns_none(_isolated_home: Path) -> None:
    assert init_wizard._profile_default_region("nope") is None


def test_profile_default_region_section_exists_without_region_key(_isolated_home: Path) -> None:
    aws_dir = _isolated_home / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("[profile readonly]\noutput = json\n")

    assert init_wizard._profile_default_region("readonly") is None


# --- _pick_region --------------------------------------------------------------------


def test_pick_region_uses_profile_default() -> None:
    with (
        patch("slowlog_agent.init_wizard._profile_default_region", return_value="ap-south-1"),
        patch(
            "slowlog_agent.init_wizard.questionary.text", return_value=_ask("ap-south-1")
        ) as text,
    ):
        assert init_wizard._pick_region("readonly") == "ap-south-1"
        assert text.call_args.kwargs["default"] == "ap-south-1"


def test_pick_region_falls_back_to_us_east_1() -> None:
    with (
        patch("slowlog_agent.init_wizard._profile_default_region", return_value=None),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("us-east-1")) as text,
    ):
        assert init_wizard._pick_region("readonly") == "us-east-1"
        assert text.call_args.kwargs["default"] == "us-east-1"


# --- _write_config -----------------------------------------------------------------


def test_write_config_produces_parseable_toml(_isolated_home: Path) -> None:
    import tomllib

    init_wizard._write_config(
        log_group_name="/aws/rds/slow",
        aws_region="us-east-1",
        aws_profile="readonly",
        db_dsn="mysql://u:p@host/db",
    )

    data = tomllib.loads((_isolated_home / "slowlog.toml").read_text())
    assert data == {
        "log_group_name": "/aws/rds/slow",
        "aws_region": "us-east-1",
        "aws_profile": "readonly",
        "db_dsn": "mysql://u:p@host/db",
    }


def test_write_config_omits_db_dsn_when_none(_isolated_home: Path) -> None:
    import tomllib

    init_wizard._write_config(
        log_group_name="/aws/rds/slow", aws_region="us-east-1", aws_profile="readonly", db_dsn=None
    )

    data = tomllib.loads((_isolated_home / "slowlog.toml").read_text())
    assert "db_dsn" not in data


def test_write_config_escapes_quotes_and_backslashes(_isolated_home: Path) -> None:
    import tomllib

    init_wizard._write_config(
        log_group_name='weird"name\\path',
        aws_region="us-east-1",
        aws_profile="readonly",
        db_dsn=None,
    )

    data = tomllib.loads((_isolated_home / "slowlog.toml").read_text())
    assert data["log_group_name"] == 'weird"name\\path'


# --- _maybe_configure_db_dsn ---------------------------------------------------------


def test_maybe_configure_db_dsn_declines() -> None:
    with patch("slowlog_agent.init_wizard.questionary.confirm", return_value=_ask(False)):
        assert init_wizard._maybe_configure_db_dsn() is None


def test_maybe_configure_db_dsn_empty_text_returns_none() -> None:
    with (
        patch("slowlog_agent.init_wizard.questionary.confirm", return_value=_ask(True)),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("")),
    ):
        assert init_wizard._maybe_configure_db_dsn() is None


def test_maybe_configure_db_dsn_connection_fails_returns_none() -> None:
    with (
        patch("slowlog_agent.init_wizard.questionary.confirm", return_value=_ask(True)),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("mysql://x@h/db")),
        patch("slowlog_agent.init_wizard.db.check_db_dsn", return_value=(False, "refused")),
    ):
        assert init_wizard._maybe_configure_db_dsn() is None


def test_maybe_configure_db_dsn_read_only_succeeds() -> None:
    with (
        patch("slowlog_agent.init_wizard.questionary.confirm", return_value=_ask(True)),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("mysql://x@h/db")),
        patch("slowlog_agent.init_wizard.db.check_db_dsn", return_value=(True, "connected")),
        patch("slowlog_agent.init_wizard.db.check_no_write_grants", return_value=(True, [])),
    ):
        assert init_wizard._maybe_configure_db_dsn() == "mysql://x@h/db"


def test_maybe_configure_db_dsn_write_grants_declined() -> None:
    confirm_calls = [_ask(True), _ask(False)]  # configure? yes; use anyway? no
    with (
        patch("slowlog_agent.init_wizard.questionary.confirm", side_effect=confirm_calls),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("mysql://x@h/db")),
        patch("slowlog_agent.init_wizard.db.check_db_dsn", return_value=(True, "connected")),
        patch(
            "slowlog_agent.init_wizard.db.check_no_write_grants",
            return_value=(False, ["GRANT INSERT ON db.* TO x"]),
        ),
    ):
        assert init_wizard._maybe_configure_db_dsn() is None


def test_maybe_configure_db_dsn_write_grants_accepted_anyway() -> None:
    confirm_calls = [_ask(True), _ask(True)]  # configure? yes; use anyway? yes
    with (
        patch("slowlog_agent.init_wizard.questionary.confirm", side_effect=confirm_calls),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("mysql://x@h/db")),
        patch("slowlog_agent.init_wizard.db.check_db_dsn", return_value=(True, "connected")),
        patch(
            "slowlog_agent.init_wizard.db.check_no_write_grants",
            return_value=(False, ["GRANT INSERT ON db.* TO x"]),
        ),
    ):
        assert init_wizard._maybe_configure_db_dsn() == "mysql://x@h/db"


def test_maybe_configure_db_dsn_grants_check_error_still_returns_dsn() -> None:
    with (
        patch("slowlog_agent.init_wizard.questionary.confirm", return_value=_ask(True)),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("mysql://x@h/db")),
        patch("slowlog_agent.init_wizard.db.check_db_dsn", return_value=(True, "connected")),
        patch("slowlog_agent.init_wizard.db.check_no_write_grants", side_effect=RuntimeError("x")),
    ):
        assert init_wizard._maybe_configure_db_dsn() == "mysql://x@h/db"


# --- _check_claude_binary ----------------------------------------------------------


def test_check_claude_binary_found() -> None:
    with patch("slowlog_agent.init_wizard.shutil.which", return_value="/usr/bin/claude"):
        init_wizard._check_claude_binary()  # should not raise


def test_check_claude_binary_missing() -> None:
    with patch("slowlog_agent.init_wizard.shutil.which", return_value=None):
        init_wizard._check_claude_binary()  # should not raise


# --- _pick_log_group -----------------------------------------------------------------


def test_pick_log_group_offers_snippet_when_none_found() -> None:
    with (
        patch("slowlog_agent.init_wizard.list_log_groups", return_value=[]),
        patch(
            "slowlog_agent.init_wizard.questionary.text",
            return_value=_ask("/future/log-group"),
        ),
    ):
        result = init_wizard._pick_log_group(region="us-east-1", profile="default")

    assert result == "/future/log-group"


def test_pick_log_group_selects_from_autocomplete() -> None:
    with (
        patch("slowlog_agent.init_wizard.list_log_groups", return_value=["/a", "/b"]),
        patch(
            "slowlog_agent.init_wizard.questionary.autocomplete", return_value=_ask("/b")
        ) as autocomplete,
    ):
        result = init_wizard._pick_log_group(region="us-east-1", profile="default")

    assert result == "/b"
    autocomplete.assert_called_once()


def test_pick_log_group_handles_list_error_gracefully() -> None:
    from botocore.exceptions import ClientError

    with (
        patch(
            "slowlog_agent.init_wizard.list_log_groups",
            side_effect=ClientError({"Error": {"Code": "AccessDeniedException"}}, "Describe"),
        ),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("/typed")),
    ):
        result = init_wizard._pick_log_group(region="us-east-1", profile="default")

    assert result == "/typed"


# --- _pick_aws_profile ---------------------------------------------------------------


def test_pick_aws_profile_selects_existing() -> None:
    with (
        patch("slowlog_agent.init_wizard.list_aws_profiles", return_value=["default", "prod"]),
        patch("slowlog_agent.init_wizard.questionary.select", return_value=_ask("prod")),
    ):
        assert init_wizard._pick_aws_profile() == "prod"


def test_pick_aws_profile_type_manually_option() -> None:
    with (
        patch("slowlog_agent.init_wizard.list_aws_profiles", return_value=["default"]),
        patch(
            "slowlog_agent.init_wizard.questionary.select",
            return_value=_ask(init_wizard._TYPE_MANUALLY_OPTION),
        ),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("custom")),
    ):
        assert init_wizard._pick_aws_profile() == "custom"


def test_pick_aws_profile_no_profiles_found_prompts_text() -> None:
    with (
        patch("slowlog_agent.init_wizard.list_aws_profiles", return_value=[]),
        patch("slowlog_agent.init_wizard.questionary.text", return_value=_ask("manual")),
    ):
        assert init_wizard._pick_aws_profile() == "manual"


# --- run_init end-to-end (fully mocked) -----------------------------------------------


def test_run_init_end_to_end_success(_isolated_home: Path) -> None:
    with (
        patch("slowlog_agent.init_wizard._pick_aws_profile", return_value="readonly"),
        patch("slowlog_agent.init_wizard._pick_region", return_value="us-east-1"),
        patch("slowlog_agent.init_wizard._pick_log_group", return_value="/aws/rds/slow"),
        patch("slowlog_agent.init_wizard._maybe_configure_db_dsn", return_value=None),
        patch("slowlog_agent.init_wizard._check_claude_binary"),
        patch("slowlog_agent.doctor.run_doctor_checks", return_value=True),
    ):
        exit_code = init_wizard.run_init()

    assert exit_code == 0
    assert (_isolated_home / "slowlog.toml").exists()


def test_run_init_end_to_end_doctor_fails(_isolated_home: Path) -> None:
    with (
        patch("slowlog_agent.init_wizard._pick_aws_profile", return_value="readonly"),
        patch("slowlog_agent.init_wizard._pick_region", return_value="us-east-1"),
        patch("slowlog_agent.init_wizard._pick_log_group", return_value="/aws/rds/slow"),
        patch("slowlog_agent.init_wizard._maybe_configure_db_dsn", return_value=None),
        patch("slowlog_agent.init_wizard._check_claude_binary"),
        patch("slowlog_agent.doctor.run_doctor_checks", return_value=False),
    ):
        exit_code = init_wizard.run_init()

    assert exit_code == 1
