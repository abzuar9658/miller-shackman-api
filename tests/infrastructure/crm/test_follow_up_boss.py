import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

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
    assert page.leads[0].mapped_custom_fields == {"budget": "650000"}


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
