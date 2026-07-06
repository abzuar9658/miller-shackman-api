import uuid
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
