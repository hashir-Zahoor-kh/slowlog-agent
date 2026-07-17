import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from slowlog_agent import fetcher
from slowlog_agent.errors import FetchError
from slowlog_agent.fetcher import build_client, fetch_events

START = datetime(2026, 7, 14, 0, 0, 0)
END = datetime(2026, 7, 15, 0, 0, 0)


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, operation)


# --- pagination (isolated with a mocked client) ---------------------------------


def test_fetch_events_paginates_across_three_pages() -> None:
    client = MagicMock()
    client.filter_log_events.side_effect = [
        {"events": [{"message": "line-1"}, {"message": "line-2"}], "nextToken": "token-a"},
        {"events": [{"message": "line-3"}], "nextToken": "token-b"},
        {"events": [{"message": "line-4"}]},
    ]

    result = fetch_events(client, "/aws/rds/slowquery", START, END)

    assert result == ["line-1", "line-2", "line-3", "line-4"]
    assert client.filter_log_events.call_count == 3
    second_call_kwargs = client.filter_log_events.call_args_list[1].kwargs
    assert second_call_kwargs["nextToken"] == "token-a"


# --- real moto-backed integration tests -----------------------------------------


@mock_aws
def test_fetch_events_empty_log_group_returns_empty_list() -> None:
    client = boto3.client("logs", region_name="us-east-1")
    client.create_log_group(logGroupName="/aws/rds/slowquery")

    result = fetch_events(client, "/aws/rds/slowquery", START, END)

    assert result == []


@mock_aws
def test_fetch_events_missing_log_group_raises_fetch_error() -> None:
    client = boto3.client("logs", region_name="us-east-1")

    with pytest.raises(FetchError) as exc_info:
        fetch_events(client, "/does/not/exist", START, END, profile="readonly")

    assert "/does/not/exist" in exc_info.value.message
    assert "readonly" in exc_info.value.remediation


@mock_aws
def test_fetch_events_happy_path_returns_put_messages() -> None:
    client = boto3.client("logs", region_name="us-east-1")
    client.create_log_group(logGroupName="/aws/rds/slowquery")
    client.create_log_stream(logGroupName="/aws/rds/slowquery", logStreamName="stream-1")
    now_ms = int(datetime(2026, 7, 14, 12, 0, 0).timestamp() * 1000)
    client.put_log_events(
        logGroupName="/aws/rds/slowquery",
        logStreamName="stream-1",
        logEvents=[
            {"timestamp": now_ms, "message": "# Time: 2026-07-14T12:00:00.000Z"},
            {"timestamp": now_ms + 1, "message": "SELECT 1;"},
        ],
    )

    result = fetch_events(client, "/aws/rds/slowquery", START, END)

    assert "# Time: 2026-07-14T12:00:00.000Z" in result
    assert "SELECT 1;" in result


# --- access denied (mocked client error) ----------------------------------------


def test_fetch_events_access_denied_raises_fetch_error() -> None:
    client = MagicMock()
    client.filter_log_events.side_effect = _client_error("AccessDeniedException", "FilterLogEvents")

    with pytest.raises(FetchError) as exc_info:
        fetch_events(client, "/aws/rds/slowquery", START, END, profile="readonly")

    assert "Access denied" in exc_info.value.message
    assert "readonly" in exc_info.value.remediation


def test_fetch_events_unexpected_client_error_is_wrapped() -> None:
    client = MagicMock()
    client.filter_log_events.side_effect = _client_error("ThrottlingException", "FilterLogEvents")

    with pytest.raises(FetchError) as exc_info:
        fetch_events(client, "/aws/rds/slowquery", START, END)

    assert "ThrottlingException" in exc_info.value.message


# --- Insights fallback -----------------------------------------------------------


def test_fetch_events_switches_to_insights_when_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetcher, "_MAX_FILTER_EVENTS", 2)
    client = MagicMock()
    client.filter_log_events.return_value = {
        "events": [{"message": "a"}, {"message": "b"}, {"message": "c"}]
    }
    client.start_query.return_value = {"queryId": "q1"}
    client.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [{"field": "@message", "value": "insights-line-1"}],
            [{"field": "@message", "value": "insights-line-2"}],
        ],
    }

    result = fetch_events(client, "/aws/rds/slowquery", START, END)

    assert result == ["insights-line-1", "insights-line-2"]
    client.start_query.assert_called_once()


def test_insights_polls_until_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher, "_MAX_FILTER_EVENTS", 0)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    client = MagicMock()
    client.filter_log_events.return_value = {"events": [{"message": "a"}]}
    client.start_query.return_value = {"queryId": "q1"}
    client.get_query_results.side_effect = [
        {"status": "Running"},
        {"status": "Running"},
        {"status": "Complete", "results": [[{"field": "@message", "value": "x"}]]},
    ]

    result = fetch_events(client, "/aws/rds/slowquery", START, END)

    assert result == ["x"]
    assert len(sleeps) == 2


def test_insights_failed_status_raises_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher, "_MAX_FILTER_EVENTS", 0)
    client = MagicMock()
    client.filter_log_events.return_value = {"events": [{"message": "a"}]}
    client.start_query.return_value = {"queryId": "q1"}
    client.get_query_results.return_value = {"status": "Failed"}

    with pytest.raises(FetchError) as exc_info:
        fetch_events(client, "/aws/rds/slowquery", START, END)

    assert "failed" in exc_info.value.message.lower()


def test_insights_timeout_raises_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetcher, "_MAX_FILTER_EVENTS", 0)
    monkeypatch.setattr(fetcher, "_INSIGHTS_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    client = MagicMock()
    client.filter_log_events.return_value = {"events": [{"message": "a"}]}
    client.start_query.return_value = {"queryId": "q1"}
    client.get_query_results.return_value = {"status": "Running"}

    with pytest.raises(FetchError) as exc_info:
        fetch_events(client, "/aws/rds/slowquery", START, END)

    assert "timed out" in exc_info.value.message.lower()


# --- build_client ------------------------------------------------------------


def test_build_client_constructs_session_with_profile_and_region() -> None:
    with patch("slowlog_agent.fetcher.boto3.Session") as session_cls:
        session_instance = MagicMock()
        session_cls.return_value = session_instance

        build_client(region="us-west-2", profile="readonly")

        session_cls.assert_called_once_with(profile_name="readonly", region_name="us-west-2")
        session_instance.client.assert_called_once_with("logs")
