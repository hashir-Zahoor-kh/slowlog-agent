"""Application settings, loaded from SLOWLOG_* env vars and slowlog.toml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from slowlog_agent.errors import ConfigError

DEFAULT_CONFIG_FILENAME = "slowlog.toml"


class Settings(BaseSettings):
    """Resolved configuration. Env vars (SLOWLOG_*) take precedence over slowlog.toml."""

    model_config = SettingsConfigDict(
        env_prefix="SLOWLOG_",
        extra="ignore",
        toml_file=DEFAULT_CONFIG_FILENAME,
    )

    log_group_name: str
    aws_region: str
    aws_profile: str
    db_dsn: str | None = None
    window_hours: int = 24
    top_n: int = 10
    output_dir: Path = Path("./reports")
    agent_backend: Literal["claude", "copilot"] = "claude"
    agent_timeout_seconds: int = 300

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_settings() -> Settings:
    """Load settings, raising a remediation-bearing ConfigError on failure.

    Distinguishes "no config exists anywhere" (first run) from "config exists
    but is incomplete/invalid" so the CLI can point the user at `slowlog init`
    versus a specific field to fix.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except PydanticValidationError as exc:
        config_exists = Path(DEFAULT_CONFIG_FILENAME).exists()
        any_env_set = any(key.startswith("SLOWLOG_") for key in os.environ)
        if not config_exists and not any_env_set:
            raise ConfigError(
                "No configuration found.",
                "Run `slowlog init` to get started.",
            ) from exc
        missing = ", ".join(sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]}))
        raise ConfigError(
            f"Configuration is invalid or incomplete (fields: {missing}).",
            "Edit slowlog.toml, set the corresponding SLOWLOG_<FIELD> env var, "
            "or run `slowlog init` to regenerate the config.",
        ) from exc
