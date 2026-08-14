from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.handoff_actions import (
    HandoffActionReasonCode,
    HandoffActionResult,
    HandoffActionStatus,
    acknowledge_handoff,
    reassign_handoff,
)
from app.application.use_cases.handoff_read import (
    HandoffLeadSummary,
    HandoffReadStatus,
    HandoffReadView,
    get_handoff_view,
    list_handoff_views,
)
from app.domain.identity import AuthenticatedActor
from app.interfaces.api.dependencies.handoff import (
    HandoffActionBundle,
    HandoffReadBundle,
    get_handoff_action_bundle,
    get_handoff_read_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.handoffs import (
    HandoffActionResponse,
    HandoffDetailResponse,
    HandoffLeadResponse,
    HandoffListResponse,
    HandoffSummaryResponse,
    ReassignHandoffRequest,
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


@router.post(
    "/{workspace_id}/handoffs/{handoff_id}/acknowledge",
    response_model=HandoffActionResponse,
)
async def acknowledge_handoff_route(
    workspace_id: UUID,
    handoff_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[HandoffActionBundle, Depends(get_handoff_action_bundle)],
) -> HandoffActionResponse:
    result = await acknowledge_handoff(
        actor=actor,
        workspace_id=workspace_id,
        handoff_id=handoff_id,
        handoff_repository=bundle.handoff_repository,
        lead_repository=bundle.lead_repository,
        now=datetime.now(UTC),
    )
    _raise_for_action_failure(result)
    if result.status == HandoffActionStatus.ACKNOWLEDGED:
        await bundle.session.commit()
    assert result.handoff is not None
    return HandoffActionResponse(
        status=result.status.value,
        handoff=handoff_response(result.handoff),
    )


@router.post(
    "/{workspace_id}/handoffs/{handoff_id}/reassign",
    response_model=HandoffActionResponse,
)
async def reassign_handoff_route(
    workspace_id: UUID,
    handoff_id: UUID,
    request: ReassignHandoffRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[HandoffActionBundle, Depends(get_handoff_action_bundle)],
) -> HandoffActionResponse:
    result = await reassign_handoff(
        actor=actor,
        workspace_id=workspace_id,
        handoff_id=handoff_id,
        assigned_agent_user_id=request.assigned_agent_user_id,
        handoff_repository=bundle.handoff_repository,
        membership_repository=bundle.membership_repository,
    )
    _raise_for_action_failure(result)
    await bundle.session.commit()
    assert result.handoff is not None
    return HandoffActionResponse(
        status=result.status.value,
        handoff=handoff_response(result.handoff),
    )


def _raise_for_action_failure(result: HandoffActionResult) -> None:
    if result.status == HandoffActionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == HandoffActionStatus.REJECTED:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if HandoffActionReasonCode.PERMISSION_DENIED in result.reasons
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=[reason.value for reason in result.reasons],
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
