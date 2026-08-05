from typing import Any

import httpx

from app.interfaces.api.schemas.campaigns import CampaignDraftRequest
from scripts.setup_campaign import ensure_campaign, starter_campaign_payload

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
CAMPAIGN_ID = "00000000-0000-0000-0000-000000000002"
VERSION_ID = "00000000-0000-0000-0000-000000000003"


def _campaign_view(*, status: str) -> dict[str, Any]:
    return {
        "status": "created",
        "campaign": {
            "campaign_id": CAMPAIGN_ID,
            "name": "Dormant Lead Reactivation",
            "status": status,
            "active_version_id": VERSION_ID if status == "active" else None,
        },
        "version": {"campaign_version_id": VERSION_ID, "status": "draft"},
    }


def test_starter_payload_matches_campaign_api_schema() -> None:
    payload = starter_campaign_payload(
        name="Dormant Lead Reactivation",
        timezone="America/Chicago",
        daily_start_cap=50,
        dormant_threshold_days=60,
        crm_enrollment_tag="ai_nurture",
        approved_model="openai/gpt-4o-mini",
    )

    request = CampaignDraftRequest.model_validate(payload)

    assert request.enabled_channels == ["email"]
    assert request.preflight_digest_enabled is True
    assert len(request.cadence_steps) == 2


def test_ensure_campaign_creates_publishes_and_runs_selector() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "campaigns": []})
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(201, json=_campaign_view(status="draft"))
        if request.url.path.endswith("/publish"):
            return httpx.Response(200, json=_campaign_view(status="active"))
        return httpx.Response(
            200,
            json={"status": "no_candidates", "batch_id": "starter-batch"},
        )

    client = httpx.Client(
        base_url="https://api.test/api/v1/",
        transport=httpx.MockTransport(handler),
    )
    result = ensure_campaign(
        client,
        workspace_id=WORKSPACE_ID,
        name="Dormant Lead Reactivation",
        payload=starter_campaign_payload(
            name="Dormant Lead Reactivation",
            timezone="America/Chicago",
            daily_start_cap=50,
            dormant_threshold_days=60,
            crm_enrollment_tag="ai_nurture",
            approved_model="openai/gpt-4o-mini",
        ),
        run_dormant_selector=True,
        batch_id="starter-batch",
    )

    assert result.created is True
    assert result.published is True
    assert result.campaign_status == "active"
    assert result.selector_result == {"status": "no_candidates", "batch_id": "starter-batch"}
    assert [method for method, _ in requests] == ["GET", "POST", "POST", "POST"]


def test_ensure_campaign_reuses_existing_active_campaign() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        existing = _campaign_view(status="active")
        existing["latest_version"] = existing.pop("version")
        return httpx.Response(200, json={"status": "ok", "campaigns": [existing]})

    client = httpx.Client(
        base_url="https://api.test/api/v1/",
        transport=httpx.MockTransport(handler),
    )
    result = ensure_campaign(
        client,
        workspace_id=WORKSPACE_ID,
        name="dormant lead reactivation",
        payload={},
        run_dormant_selector=False,
        batch_id=None,
    )

    assert result.created is False
    assert result.published is False
    assert result.campaign_status == "active"
    assert result.version_id == VERSION_ID
