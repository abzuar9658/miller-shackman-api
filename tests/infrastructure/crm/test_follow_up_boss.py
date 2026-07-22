import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.domain.crm_sync import CRMSyncLeadSort
from app.infrastructure.crm.follow_up_boss.client import FollowUpBossCRMClient


def _transport(payload: dict[str, Any], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


async def test_validate_connection_success(workspace_id: uuid.UUID) -> None:
    client = FollowUpBossCRMClient(
        api_key="key",
        base_url="https://api.followupboss.com/v1",
    )
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport({"id": 1}),
    )
    result = await client.validate_connection(workspace_id)
    assert result is True


async def test_get_lead_maps_payload(workspace_id: uuid.UUID) -> None:
    payload = {
        "id": 123,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": "ada@example.com",
        "phone": "+15551234567",
        "assignedTo": 42,
        "tags": ["nurture"],
        "customFields": {"budget": "650000"},
        "created": "2024-01-01T00:00:00Z",
        "updated": "2024-01-02T00:00:00Z",
    }
    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport(payload),
    )
    lead = await client.get_lead(workspace_id, "123")
    assert lead is not None
    assert lead.crm_lead_id == "123"
    assert lead.first_name == "Ada"
    assert lead.email == "ada@example.com"
    assert lead.assigned_agent_id == "42"
    assert lead.tags == ["nurture"]
    assert lead.custom_fields == {"budget": "650000"}


async def test_get_lead_snapshot_maps_payload_to_canonical_record(
    workspace_id: uuid.UUID,
) -> None:
    payload = {
        "id": 123,
        "assignedUserId": 42,
        "assignedTo": "Agent Name",
        "type": "Buyer",
        "source": "Zillow",
        "stage": "Lead",
        "createdVia": "Email Parsing",
        "emails": [{"value": "ada@example.com"}],
        "phones": [{"value": "+15551234567", "isLandline": False}],
        "customFields": {"budget": "650000", "other": "ignore"},
        "created": "2024-01-01T00:00:00Z",
        "updated": "2024-01-02T00:00:00Z",
    }
    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport(payload),
    )

    lead = await client.get_lead_snapshot(
        workspace_id=workspace_id,
        crm_lead_id="123",
        mapped_custom_field_keys=("budget",),
    )

    assert lead is not None
    assert lead.crm_lead_id == "123"
    assert lead.assigned_agent_crm_id == "42"
    assert lead.primary_email == "ada@example.com"
    assert lead.primary_phone == "+15551234567"
    assert lead.has_sms_capable_phone is True
    assert lead.source_payload_version == "follow_up_boss_person:v1"
    assert lead.mapped_custom_fields == {
        "budget": "650000",
        "assigned_agent_name": "Agent Name",
    }


async def test_get_lead_prefers_assigned_user_id_over_assigned_to_name(
    workspace_id: uuid.UUID,
) -> None:
    payload = {
        "id": 123,
        "firstName": "Ada",
        "assignedUserId": 42,
        "assignedTo": "The Miller Schackman Team Test",
    }
    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport(payload),
    )

    lead = await client.get_lead(workspace_id, "123")

    assert lead is not None
    assert lead.assigned_agent_id == "42"


async def test_get_assigned_agent_ignores_team_name_assigned_to_without_user_id(
    workspace_id: uuid.UUID,
) -> None:
    request_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        if request.url.path == "/v1/people/123":
            return httpx.Response(
                200,
                json={
                    "id": 123,
                    "assignedTo": "The Miller Schackman Team Test",
                },
            )
        return httpx.Response(500, json={"message": "unexpected downstream user lookup"})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    agent = await client.get_assigned_agent(workspace_id, "123")

    assert agent is None
    assert request_paths == ["/v1/people/123"]


async def test_list_lead_snapshots_maps_payload_and_pagination_metadata(
    workspace_id: uuid.UUID,
) -> None:
    payload = {
        "_metadata": {"next": "cursor-2"},
        "people": [
            {
                "id": 123,
                "assignedUserId": 42,
                "assignedTo": "Agent Name",
                "type": "Buyer",
                "source": "Zillow",
                "stage": "Lead",
                "createdVia": "Email Parsing",
                "emails": [{"value": "ada@example.com"}],
                "phones": [{"value": "+15551234567", "isLandline": False}],
                "customFields": {"budget": "650000", "other": "ignore"},
            }
        ],
    }
    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport(payload),
    )

    page = await client.list_lead_snapshots(
        workspace_id=workspace_id,
        page_size=25,
        mapped_custom_field_keys=("budget",),
    )

    assert page.next_cursor == "cursor-2"
    assert len(page.leads) == 1
    assert page.leads[0].crm_lead_id == "123"
    assert page.leads[0].lead_source == "Zillow"
    assert page.leads[0].mapped_custom_fields == {
        "budget": "650000",
        "assigned_agent_name": "Agent Name",
    }


async def test_list_lead_snapshots_sends_incremental_filters_and_cursor(
    workspace_id: uuid.UUID,
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"_metadata": {}, "people": []})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    await client.list_lead_snapshots(
        workspace_id=workspace_id,
        page_size=50,
        cursor="cursor-2",
        updated_after=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        updated_before=datetime(2026, 7, 8, 0, 0, tzinfo=UTC),
    )

    assert captured["limit"] == "50"
    assert captured["next"] == "cursor-2"
    assert captured["updatedAfter"] == "2026-07-01T00:00:00Z"
    assert captured["updatedBefore"] == "2026-07-08T00:00:00Z"


async def test_list_lead_snapshots_sends_sort_for_recent_limited_sync(
    workspace_id: uuid.UUID,
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"_metadata": {}, "people": []})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    await client.list_lead_snapshots(
        workspace_id=workspace_id,
        page_size=50,
        sort_by=CRMSyncLeadSort.UPDATED,
    )

    assert captured["limit"] == "50"
    assert captured["sort"] == "-updated"


async def test_list_agents_maps_users_payload_and_paginates(workspace_id: uuid.UUID) -> None:
    captured_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.append(dict(request.url.params))
        if request.url.params.get("next") == "cursor-2":
            return httpx.Response(
                200,
                json={
                    "users": [
                        {
                            "id": 8,
                            "name": "Grace Hopper",
                            "email": "grace@example.com",
                            "cellPhone": "+15550000008",
                            "status": "inactive",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "_metadata": {"next": "cursor-2"},
                "users": [
                    {
                        "id": 7,
                        "firstName": "Ada",
                        "lastName": "Lovelace",
                        "email": "ada@example.com",
                        "phone": "+15550000007",
                        "isActive": True,
                    }
                ],
            },
        )

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    agents = await client.list_agents(workspace_id)

    assert [params.get("next") for params in captured_params] == [None, "cursor-2"]
    assert len(agents) == 2
    assert agents[0].crm_agent_id == "7"
    assert agents[0].name == "Ada Lovelace"
    assert agents[0].phone == "+15550000007"
    assert agents[0].is_active is True
    assert agents[1].crm_agent_id == "8"
    assert agents[1].is_active is False


async def test_get_recent_activity_uses_events_endpoint_with_person_id(
    workspace_id: uuid.UUID,
) -> None:
    captured_requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        captured_requests.append((request.url.path, params))
        if request.url.path == "/v1/events":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": 99,
                            "type": "Inquiry",
                            "created": "2026-07-14T10:00:00Z",
                            "message": "We are hoping to move before school starts.",
                            "userId": 42,
                            "userName": "Agent Ada",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/notes":
            return httpx.Response(
                200,
                json={
                    "notes": [
                        {
                            "id": 17,
                            "created": "2026-07-14T10:05:00Z",
                            "body": "<p>Agent follow-up note</p>",
                            "isHtml": True,
                            "userId": 7,
                            "userName": "Agent Ada",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/textMessages":
            return httpx.Response(
                200,
                json={
                    "textMessages": [
                        {
                            "id": 88,
                            "created": "2026-07-14T10:10:00Z",
                            "message": "Checking whether you are still looking.",
                            "isIncoming": False,
                            "userId": 42,
                            "userName": "Agent Ada",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/calls":
            return httpx.Response(
                200,
                json={
                    "calls": [
                        {
                            "id": 55,
                            "created": "2026-07-14T10:15:00Z",
                            "description": "Left voicemail",
                            "isIncoming": False,
                            "userId": 42,
                            "userName": "Agent Ada",
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    activities = await client.get_recent_activity(workspace_id, "12401", limit=25)

    assert [path for path, _ in captured_requests] == [
        "/v1/events",
        "/v1/notes",
        "/v1/textMessages",
        "/v1/calls",
    ]
    for _, params in captured_requests:
        assert params["personId"] == "12401"
        assert params["limit"] == "25"
    assert [activity.crm_activity_id for activity in activities] == [
        "call:55",
        "text_message:88",
        "note:17",
        "99",
    ]
    assert activities[0].activity_type == "Call"
    assert activities[0].direction == "outbound"
    assert activities[1].activity_type == "Text message"
    assert activities[1].actor_name == "Agent Ada"
    assert activities[2].content == "Agent follow-up note"
    assert activities[2].direction == "internal"
    assert activities[3].activity_type == "Inquiry"
    assert activities[3].content == "We are hoping to move before school starts."
    assert activities[3].agent_id == "42"


async def test_add_note_posts_to_notes_collection_with_person_id_and_body(
    workspace_id: uuid.UUID,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["json"] = request.read().decode("utf-8")
        return httpx.Response(200, json={})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    await client.add_note(workspace_id, "12443", "AI outbound email message sent")

    assert captured == {
        "path": "/v1/notes",
        "method": "POST",
        "json": '{"personId":12443,"body":"AI outbound email message sent"}',
    }


async def test_add_note_includes_subject_when_provided(workspace_id: uuid.UUID) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = request.read().decode("utf-8")
        return httpx.Response(200, json={})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    await client.add_note(
        workspace_id,
        "12443",
        "AI outbound email message sent",
        subject="AI OUTBOUND · EMAIL",
    )

    assert captured["json"] == (
        '{"personId":12443,"body":"AI outbound email message sent",'
        '"subject":"AI OUTBOUND \u00b7 EMAIL"}'
    )


async def test_add_note_raises_for_http_error(workspace_id: uuid.UUID) -> None:
    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport({"message": "bad request"}, status=400),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.add_note(workspace_id, "12443", "AI outbound email message sent")


async def test_update_custom_fields_raises_for_http_error(workspace_id: uuid.UUID) -> None:
    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=_transport({"message": "bad request"}, status=400),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.update_custom_fields(workspace_id, "12443", {"ai_summary": "test"})


async def test_get_recent_activity_accepts_empty_events_list(
    workspace_id: uuid.UUID,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/events":
            return httpx.Response(200, json={"events": []})
        if request.url.path == "/v1/notes":
            return httpx.Response(200, json={"notes": []})
        if request.url.path == "/v1/textMessages":
            return httpx.Response(200, json={"textMessages": []})
        if request.url.path == "/v1/calls":
            return httpx.Response(200, json={"calls": []})
        return httpx.Response(404, json={"message": "not found"})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    activities = await client.get_recent_activity(workspace_id, "12401")

    assert activities == []


async def test_get_recent_activity_continues_when_one_surface_fails(
    workspace_id: uuid.UUID,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/events":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": 99,
                            "type": "Inquiry",
                            "created": "2026-07-14T10:00:00Z",
                            "message": "Need more info.",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/notes":
            return httpx.Response(500, json={"message": "boom"})
        if request.url.path == "/v1/textMessages":
            return httpx.Response(200, json={"textMessages": []})
        if request.url.path == "/v1/calls":
            return httpx.Response(200, json={"calls": []})
        return httpx.Response(404, json={"message": "not found"})

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    activities = await client.get_recent_activity(workspace_id, "12401")

    assert len(activities) == 1
    assert activities[0].crm_activity_id == "99"


async def test_get_recent_activity_retries_rate_limited_collection_with_retry_after(
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_paths: list[str] = []
    sleep_delays: list[float] = []
    attempts = {"events": 0}

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        if request.url.path == "/v1/events":
            attempts["events"] += 1
            if attempts["events"] == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "2"},
                    json={"message": "rate limited"},
                )
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": 99,
                            "type": "Inquiry",
                            "created": "2026-07-14T10:00:00Z",
                            "message": "Need more info.",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/notes":
            return httpx.Response(200, json={"notes": []})
        if request.url.path == "/v1/textMessages":
            return httpx.Response(200, json={"textMessages": []})
        if request.url.path == "/v1/calls":
            return httpx.Response(200, json={"calls": []})
        return httpx.Response(404, json={"message": "not found"})

    monkeypatch.setattr("app.infrastructure.crm.follow_up_boss.client.asyncio.sleep", fake_sleep)

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    activities = await client.get_recent_activity(workspace_id, "12401")

    assert sleep_delays == [2.0]
    assert request_paths == [
        "/v1/events",
        "/v1/events",
        "/v1/notes",
        "/v1/textMessages",
        "/v1/calls",
    ]
    assert len(activities) == 1
    assert activities[0].crm_activity_id == "99"


async def test_get_recent_activity_uses_exponential_backoff_without_retry_after(
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_delays: list[float] = []
    attempts = {"events": 0}

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/events":
            attempts["events"] += 1
            if attempts["events"] < 3:
                return httpx.Response(429, json={"message": "rate limited"})
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": 99,
                            "type": "Inquiry",
                            "created": "2026-07-14T10:00:00Z",
                            "message": "Need more info.",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/notes":
            return httpx.Response(200, json={"notes": []})
        if request.url.path == "/v1/textMessages":
            return httpx.Response(200, json={"textMessages": []})
        if request.url.path == "/v1/calls":
            return httpx.Response(200, json={"calls": []})
        return httpx.Response(404, json={"message": "not found"})

    monkeypatch.setattr("app.infrastructure.crm.follow_up_boss.client.asyncio.sleep", fake_sleep)

    client = FollowUpBossCRMClient(api_key="key")
    client._client = httpx.AsyncClient(
        auth=client._auth,
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )

    activities = await client.get_recent_activity(workspace_id, "12401")

    assert sleep_delays == [1.0, 2.0]
    assert len(activities) == 1
    assert activities[0].crm_activity_id == "99"
