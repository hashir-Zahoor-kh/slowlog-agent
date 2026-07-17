import pytest

from slowlog_agent.backends import ClaudeBackend, CopilotBackend, get_backend
from slowlog_agent.errors import ConfigError


def test_get_backend_claude() -> None:
    assert isinstance(get_backend("claude"), ClaudeBackend)


def test_get_backend_copilot() -> None:
    assert isinstance(get_backend("copilot"), CopilotBackend)


def test_get_backend_unknown_name_raises_config_error_listing_valid_names() -> None:
    with pytest.raises(ConfigError) as exc_info:
        get_backend("bogus")

    assert "bogus" in exc_info.value.message
    assert "claude" in exc_info.value.remediation
    assert "copilot" in exc_info.value.remediation
