from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.handoff_read import (
    HandoffLeadSummary,
    HandoffReadStatus,
    HandoffReadView,
    get_handoff_view,
    list_handoff_views,
)
from app.domain.identity import AuthenticatedActor
from app.interfaces.api.dependencies.handoff import HandoffReadBundle, get_handoff_read_bundle
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.handoffs import (
    HandoffDetailResponse,
    HandoffLeadResponse,
    HandoffListResponse,
    HandoffSummaryResponse,
)
from app.interfaces.api.serializers.handoffs import handoff_response

router = APIRouter(tags=["handoffs"])


@router.get("/{workspace_id}/handoffs", response_model=HandoffListResponse)
async def list_handoffs_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[HandoffReadBundle, Depends(get_handoff_read_bundle)],
) -> HandoffListResponse:
    result = await list_handoff_views(
        actor=actor,
        workspace_id=workspace_id,
        handoff_repository=bundle.handoff_repository,
        lead_repository=bundle.lead_repository,
        user_repository=bundle.user_repository,
    )
    if result.status == HandoffReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    return HandoffListResponse(
        status=result.status.value,
        handoffs=[_handoff_summary_response(view) for view in result.views],
    )


@router.get("/{workspace_id}/handoffs/{handoff_id}", response_model=HandoffDetailResponse)
async def get_handoff_route(
    workspace_id: UUID,
    handoff_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[HandoffReadBundle, Depends(get_handoff_read_bundle)],
) -> HandoffDetailResponse:
    result = await get_handoff_view(
        actor=actor,
        workspace_id=workspace_id,
        handoff_id=handoff_id,
        handoff_repository=bundle.handoff_repository,
        lead_repository=bundle.lead_repository,
        user_repository=bundle.user_repository,
    )
    if result.status == HandoffReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == HandoffReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.view is not None
    return HandoffDetailResponse(
        status=result.status.value,
        handoff=handoff_response(result.view.handoff),
        lead=_handoff_lead_response(result.view.lead),
        assigned_agent_name=result.view.assigned_agent_name,
        recommended_next_action=result.view.recommended_next_action,
    )


def _handoff_summary_response(view: HandoffReadView) -> HandoffSummaryResponse:
    return HandoffSummaryResponse(
        handoff=handoff_response(view.handoff),
        lead=_handoff_lead_response(view.lead),
        assigned_agent_name=view.assigned_agent_name,
        recommended_next_action=view.recommended_next_action,
    )


def _handoff_lead_response(lead: HandoffLeadSummary) -> HandoffLeadResponse:
    return HandoffLeadResponse(
        lead_id=lead.lead_id,
        display_name=lead.display_name,
        primary_email=lead.primary_email,
        primary_phone=lead.primary_phone,
    )
