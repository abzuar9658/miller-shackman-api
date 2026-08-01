"""Tests for the read-only FUB contact history checker."""

from typing import Any

import httpx
import pytest

from scripts.check_follow_up_boss_contact import (
    check_contact,
    parse_args,
    summarize_collection,
)


def test_summarize_collection_reports_count_and_redacted_samples() -> None:
    result: dict[str, Any] = {
        "status": 200,
        "ok": True,
        "payload": {
            "textMessages": [{"id": 7, "message": "private message", "created": "today"}],
            "total": 1,
        },
    }

    summary = summarize_collection(result, "textMessages")

    assert summary["status"] == 200
    assert summary["item_count"] == 1
    assert summary["reported_total"] == 1
    assert summary["redacted_samples"][0]["message"] == "***"


def test_parse_args_requires_person_id_and_supports_output() -> None:
    args = parse_args(["--person-id", "123", "--limit", "25", "--stdout"])

    assert args.person_id == "123"
    assert args.limit == 25
    assert args.stdout is True


@pytest.mark.asyncio
async def test_check_contact_queries_all_historical_activity_endpoints() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, dict(request.url.params)))
        endpoint = request.url.path.removeprefix("/v1")
        payloads = {
            "/me": {"role": "admin"},
            "/people/123": {"id": 123},
            "/events": {"events": [{"id": 1}]},
            "/notes": {"notes": [{"id": 2}]},
            "/textMessages": {"textMessages": [{"id": 3, "message": "secret"}]},
            "/calls": {"calls": [{"id": 4}]},
        }
        return httpx.Response(200, json=payloads[endpoint], request=request)

    report = await check_contact(
        "test-key",
        "123",
        base_url="https://fub.test/v1",
        limit=25,
        transport=httpx.MockTransport(handler),
    )

    assert [path for path, _ in requests] == [
        "/v1/me",
        "/v1/people/123",
        "/v1/events",
        "/v1/notes",
        "/v1/textMessages",
        "/v1/calls",
    ]
    assert report["activity"]["textMessages"]["item_count"] == 1
    assert report["activity"]["textMessages"]["redacted_samples"][0]["message"] == "***"
