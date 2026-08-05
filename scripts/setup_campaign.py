"""Create and publish an idempotent starter nurture campaign through the API."""

from __future__ import annotations

import argparse
import getpass
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
ALLOWED_ROLES = {"platform_super_admin", "brokerage_admin"}


class CampaignSetupError(RuntimeError):
    """Raised when campaign setup cannot safely continue."""


@dataclass(frozen=True)
class SetupResult:
    workspace_id: str
    campaign_id: str
    version_id: str
    campaign_status: str
    created: bool
    published: bool
    selector_result: dict[str, Any] | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sign in and create/publish a starter email nurture campaign.",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--workspace-id", type=UUID)
    parser.add_argument("--campaign-name", default="Dormant Lead Reactivation")
    parser.add_argument("--timezone", help="Defaults to the workspace timezone")
    parser.add_argument("--daily-start-cap", type=int, default=50)
    parser.add_argument("--dormant-threshold-days", type=int, default=60)
    parser.add_argument("--crm-enrollment-tag", default="ai_nurture")
    parser.add_argument("--approved-model", default="openai/gpt-4o-mini")
    parser.add_argument("--run-dormant-selector", action="store_true")
    parser.add_argument("--batch-id", help="Optional dormant-selector idempotency key")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args(argv)


def starter_campaign_payload(
    *,
    name: str,
    timezone: str,
    daily_start_cap: int,
    dormant_threshold_days: int,
    crm_enrollment_tag: str,
    approved_model: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "enabled_channels": ["email"],
        "daily_start_cap": daily_start_cap,
        "dormant_threshold_days": dormant_threshold_days,
        "quiet_hours_start": "10:00:00",
        "quiet_hours_end": "17:00:00",
        "timezone": timezone,
        "sms_compliance_required": True,
        "preflight_digest_enabled": True,
        "crm_enrollment_tag": crm_enrollment_tag,
        "allow_assigned_agent_manual_enrollment": True,
        "prompt_version": "starter-email-v1",
        "approved_model": approved_model,
        "cadence_steps": [
            {
                "channel": "email",
                "delay_hours": 0,
                "message_goal": "Ask whether the lead is still considering a move.",
                "template_key": "dormant-email-1",
                "max_attempts": 1,
            },
            {
                "channel": "email",
                "delay_hours": 72,
                "message_goal": "Offer help with the lead's current real estate plans.",
                "template_key": "dormant-email-2",
                "max_attempts": 1,
            },
        ],
    }


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise CampaignSetupError(
            f"API returned HTTP {response.status_code} with a non-JSON response."
        ) from exc
    if not response.is_success:
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        raise CampaignSetupError(f"API returned HTTP {response.status_code}: {detail}")
    if not isinstance(payload, dict):
        raise CampaignSetupError("API returned an unexpected response shape.")
    return cast(dict[str, Any], payload)


def sign_in(
    client: httpx.Client,
    *,
    email: str,
    password: str,
    workspace_id: UUID | None,
) -> tuple[str, dict[str, Any]]:
    body = {"email": email, "password": password}
    if workspace_id is not None:
        body["workspace_id"] = str(workspace_id)
    payload = _response_json(client.post("auth/signin", json=body))
    tokens = payload.get("tokens")
    workspace = payload.get("workspace")
    if not isinstance(tokens, dict) or not isinstance(workspace, dict):
        raise CampaignSetupError("Sign-in did not return tokens and a workspace.")
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str):
        raise CampaignSetupError("Sign-in did not return an access token.")
    return access_token, cast(dict[str, Any], workspace)


def require_campaign_admin_role(client: httpx.Client) -> None:
    payload = _response_json(client.get("auth/me"))
    membership = payload.get("membership")
    role = membership.get("role") if isinstance(membership, dict) else None
    if role not in ALLOWED_ROLES:
        allowed = ", ".join(sorted(ALLOWED_ROLES))
        raise CampaignSetupError(
            f"This script requires one of these roles: {allowed}. Found: {role}"
        )


def ensure_campaign(
    client: httpx.Client,
    *,
    workspace_id: str,
    name: str,
    payload: dict[str, Any],
    run_dormant_selector: bool,
    batch_id: str | None,
) -> SetupResult:
    list_payload = _response_json(client.get(f"workspaces/{workspace_id}/campaigns"))
    summaries = list_payload.get("campaigns", [])
    if not isinstance(summaries, list):
        raise CampaignSetupError("Campaign list returned an unexpected response shape.")
    matches = [
        item
        for item in summaries
        if isinstance(item, dict)
        and isinstance(item.get("campaign"), dict)
        and str(item["campaign"].get("name", "")).strip().casefold() == name.casefold()
    ]
    if len(matches) > 1:
        raise CampaignSetupError(f"Multiple campaigns match the name {name!r}; no changes made.")

    created = not matches
    admin_view = (
        _response_json(client.post(f"workspaces/{workspace_id}/campaigns", json=payload))
        if created
        else matches[0]
    )
    campaign = admin_view.get("campaign")
    version = admin_view.get("version") or admin_view.get("latest_version")
    if not isinstance(campaign, dict) or not isinstance(version, dict):
        raise CampaignSetupError("Campaign response is missing campaign or version data.")
    campaign_id = str(campaign["campaign_id"])
    version_id = str(version["campaign_version_id"])
    campaign_status = str(campaign["status"])
    if campaign_status == "active" and campaign.get("active_version_id") is not None:
        version_id = str(campaign["active_version_id"])
    published = False
    if campaign_status == "draft":
        admin_view = _response_json(
            client.post(
                f"workspaces/{workspace_id}/campaigns/{campaign_id}/versions/{version_id}/publish"
            )
        )
        campaign = cast(dict[str, Any], admin_view["campaign"])
        campaign_status = str(campaign["status"])
        published = True
    elif campaign_status != "active":
        raise CampaignSetupError(
            f"Existing campaign is {campaign_status!r}; resume or replace it explicitly."
        )

    selector_result = None
    if run_dormant_selector:
        selector_result = _response_json(
            client.post(
                f"workspaces/{workspace_id}/campaigns/{campaign_id}/dormant-selector-runs",
                json={"batch_id": batch_id},
            )
        )
    return SetupResult(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        version_id=version_id,
        campaign_status=campaign_status,
        created=created,
        published=published,
        selector_result=selector_result,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    email = input("Admin email: ").strip()
    password = getpass.getpass("Admin password: ")
    workspace_id = args.workspace_id
    with httpx.Client(
        base_url=f"{args.api_url.rstrip('/')}/",
        timeout=args.timeout_seconds,
    ) as client:
        try:
            try:
                token, workspace = sign_in(
                    client, email=email, password=password, workspace_id=workspace_id
                )
            except CampaignSetupError as exc:
                if workspace_id is not None or "workspace_selection_required" not in str(exc):
                    raise
                workspace_id = UUID(input("Workspace ID: ").strip())
                token, workspace = sign_in(
                    client, email=email, password=password, workspace_id=workspace_id
                )
            client.headers["Authorization"] = f"Bearer {token}"
            require_campaign_admin_role(client)
            resolved_workspace_id = str(workspace["workspace_id"])
            timezone = args.timezone or str(workspace["default_timezone"])
            result = ensure_campaign(
                client,
                workspace_id=resolved_workspace_id,
                name=args.campaign_name.strip(),
                payload=starter_campaign_payload(
                    name=args.campaign_name.strip(),
                    timezone=timezone,
                    daily_start_cap=args.daily_start_cap,
                    dormant_threshold_days=args.dormant_threshold_days,
                    crm_enrollment_tag=args.crm_enrollment_tag.strip(),
                    approved_model=args.approved_model.strip(),
                ),
                run_dormant_selector=args.run_dormant_selector,
                batch_id=args.batch_id,
            )
        except (CampaignSetupError, httpx.RequestError, ValueError) as exc:
            print(f"Campaign setup failed: {exc}")
            return 1

    action = "created" if result.created else "reused"
    print(f"Campaign {action} and active.")
    print(f"workspace_id={result.workspace_id}")
    print(f"campaign_id={result.campaign_id}")
    print(f"campaign_version_id={result.version_id}")
    if result.selector_result is not None:
        print(f"dormant_selector_status={result.selector_result.get('status')}")
        print(f"dormant_selector_batch_id={result.selector_result.get('batch_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
