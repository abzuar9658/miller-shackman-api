from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.preflight_read import (
    PreflightDigestSummaryView,
    PreflightReadStatus,
    get_preflight_digest_view,
    list_preflight_digest_views,
)
from app.domain.identity import AuthenticatedActor
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.preflight import (
    PreflightReadBundle,
    get_preflight_read_bundle,
)
from app.interfaces.api.schemas.preflight import (
    PreflightDigestDetailResponse,
    PreflightDigestEntryResponse,
    PreflightDigestListResponse,
    PreflightDigestNotificationResponse,
    PreflightDigestSummaryResponse,
    PreflightVetoResponse,
)

router = APIRouter(tags=["preflight"])


@router.get("/{workspace_id}/preflight-digests", response_model=PreflightDigestListResponse)
async def list_preflight_digests_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[PreflightReadBundle, Depends(get_preflight_read_bundle)],
) -> PreflightDigestListResponse:
    result = await list_preflight_digest_views(
        actor=actor,
        workspace_id=workspace_id,
        repository=bundle.repository,
        crm_agent_repository=bundle.crm_agent_repository,
        workspace_agent_crm_mapping_repository=bundle.workspace_agent_crm_mapping_repository,
        now=datetime.now(UTC),
    )
    if result.status == PreflightReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    return PreflightDigestListResponse(
        status=result.status.value,
        digests=[_summary_response(view) for view in result.views],
    )


@router.get(
    "/{workspace_id}/preflight-digests/{digest_id}",
    response_model=PreflightDigestDetailResponse,
)
async def get_preflight_digest_route(
    workspace_id: UUID,
    digest_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[PreflightReadBundle, Depends(get_preflight_read_bundle)],
) -> PreflightDigestDetailResponse:
    result = await get_preflight_digest_view(
        actor=actor,
        workspace_id=workspace_id,
        digest_id=str(digest_id),
        repository=bundle.repository,
        crm_agent_repository=bundle.crm_agent_repository,
        workspace_agent_crm_mapping_repository=bundle.workspace_agent_crm_mapping_repository,
        now=datetime.now(UTC),
    )
    if result.status == PreflightReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == PreflightReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.view is not None
    digest = result.view.digest
    vetoed_lead_ids = digest.vetoed_lead_ids
    return PreflightDigestDetailResponse(
        status=result.status.value,
        digest=_summary_response(result.view),
        entries=[
            PreflightDigestEntryResponse(
                lead_id=entry.lead_id,
                recipient_id=entry.recipient_id,
                recipient_destination=entry.recipient_destination,
                display_name=entry.display_name,
                vetoed=entry.lead_id in vetoed_lead_ids,
            )
            for entry in digest.entries
        ],
        notifications=[
            PreflightDigestNotificationResponse(
                recipient_id=record.recipient_id,
                idempotency_key=record.idempotency_key,
                accepted=record.accepted,
                provider_reference=record.provider_reference,
                uncertain=record.uncertain,
            )
            for record in digest.notification_records
        ],
        vetoes=[
            PreflightVetoResponse(
                lead_id=veto.lead_id,
                actor_id=veto.actor_id,
                recorded_at=veto.recorded_at,
                idempotency_key=veto.idempotency_key,
                reason=veto.reason,
            )
            for veto in digest.vetoes
        ],
    )


def _summary_response(view: PreflightDigestSummaryView) -> PreflightDigestSummaryResponse:
    return PreflightDigestSummaryResponse(
        digest_id=view.digest.digest_id,
        campaign_id=view.digest.campaign_id,
        batch_id=view.digest.batch_id,
        status=view.status.value,
        lead_count=view.lead_count,
        veto_count=view.veto_count,
        recipient_count=view.recipient_count,
        digest_sent_at=view.digest.digest_sent_at,
        veto_window_expires_at=view.digest.veto_window_expires_at,
    )
