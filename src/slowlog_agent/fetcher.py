"""Fetch MySQL slow query log lines from AWS CloudWatch Logs.

Uses FilterLogEvents with full pagination for ordinary windows. If the
number of matching events looks like it will exceed the per-call practical
limit, switches to a CloudWatch Logs Insights query instead (StartQuery +
GetQueryResults, polled with exponential backoff up to a hard timeout).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from slowlog_agent.errors import FetchError

if TYPE_CHECKING:
    from mypy_boto3_logs.client import CloudWatchLogsClient

_MAX_FILTER_EVENTS = 10_000
_INSIGHTS_POLL_INTERVAL_SECONDS = 1.0
_INSIGHTS_MAX_POLL_INTERVAL_SECONDS = 10.0
_INSIGHTS_TIMEOUT_SECONDS = 120
_INSIGHTS_QUERY = "fields @message | sort @timestamp asc"

_ACCESS_DENIED_CODES = {"AccessDeniedException", "UnrecognizedClientException"}


def build_client(*, region: str, profile: str | None) -> CloudWatchLogsClient:
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("logs")


def fetch_events(
    client: CloudWatchLogsClient,
    log_group: str,
    start: datetime,
    end: datetime,
    *,
    profile: str | None = None,
) -> list[str]:
    """Fetch raw slow-log lines from `log_group` within [start, end)."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    try:
        events = _fetch_via_filter(client, log_group, start_ms, end_ms)
        if events is None:
            return _fetch_via_insights(client, log_group, start_ms, end_ms)
        return events
    except ClientError as exc:
        raise _translate_client_error(exc, log_group, profile) from exc


def _fetch_via_filter(
    client: CloudWatchLogsClient, log_group: str, start_ms: int, end_ms: int
) -> list[str] | None:
    messages: list[str] = []
    next_token: str | None = None
    while True:
        kwargs: dict[str, str | int] = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "endTime": end_ms,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        response = client.filter_log_events(**kwargs)  # type: ignore[arg-type]
        messages.extend(event["message"] for event in response.get("events", []))
        if len(messages) > _MAX_FILTER_EVENTS:
            return None
        next_token = response.get("nextToken")
        if not next_token:
            break
    return messages


def _fetch_via_insights(
    client: CloudWatchLogsClient, log_group: str, start_ms: int, end_ms: int
) -> list[str]:
    start_response = client.start_query(
        logGroupName=log_group,
        startTime=start_ms // 1000,
        endTime=end_ms // 1000,
        queryString=_INSIGHTS_QUERY,
        limit=10000,
    )
    query_id = start_response["queryId"]

    deadline = time.monotonic() + _INSIGHTS_TIMEOUT_SECONDS
    interval = _INSIGHTS_POLL_INTERVAL_SECONDS
    while True:
        result = client.get_query_results(queryId=query_id)
        status = result["status"]
        if status == "Complete":
            return [
                field["value"]
                for row in result["results"]
                for field in row
                if field["field"] == "@message"
            ]
        if status in ("Failed", "Cancelled", "Timeout"):
            raise FetchError(
                f"CloudWatch Logs Insights query {status.lower()} for log group '{log_group}'.",
                "Retry the analysis; if it keeps failing, inspect the query in the "
                "CloudWatch Logs Insights console.",
            )
        if time.monotonic() >= deadline:
            raise FetchError(
                f"CloudWatch Logs Insights query timed out after "
                f"{_INSIGHTS_TIMEOUT_SECONDS}s for log group '{log_group}'.",
                "Narrow the --hours window and retry, or check the query status in the "
                "CloudWatch console.",
            )
        time.sleep(interval)
        interval = min(interval * 2, _INSIGHTS_MAX_POLL_INTERVAL_SECONDS)


def _translate_client_error(exc: ClientError, log_group: str, profile: str | None) -> FetchError:
    code = exc.response.get("Error", {}).get("Code", "")
    profile_label = profile or "default"

    if code == "ResourceNotFoundException":
        return FetchError(
            f"Log group '{log_group}' was not found.",
            f"Verify the log group name and that AWS profile '{profile_label}' can see it "
            "(`aws logs describe-log-groups`), or run `slowlog init` to reselect it.",
        )
    if code in _ACCESS_DENIED_CODES:
        return FetchError(
            f"Access denied fetching log group '{log_group}'.",
            f"Check that AWS profile '{profile_label}' has logs:FilterLogEvents, "
            "logs:StartQuery, and logs:GetQueryResults permissions on this log group "
            "(see terraform/main.tf for the scoped policy).",
        )
    return FetchError(
        f"Failed to fetch logs from '{log_group}': {code or exc}.",
        f"Check AWS connectivity and credentials for profile '{profile_label}', then retry.",
    )
