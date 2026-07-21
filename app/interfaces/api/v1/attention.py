from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.attention_acknowledgements import (
    AttentionAcknowledgementReasonCode,
    AttentionAcknowledgementStatus,
    acknowledge_attention_item,
    clear_attention_acknowledgement,
    list_attention_acknowledgements,
)
from app.domain.attention import AttentionAcknowledgement
from app.domain.identity import AuthenticatedActor
from app.interfaces.api.dependencies.attention import (
    AttentionAcknowledgementBundle,
    get_attention_acknowledgement_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.attention import (
    AttentionAcknowledgementListResponse,
    AttentionAcknowledgementRequest,
    AttentionAcknowledgementResponse,
    AttentionAcknowledgementResultResponse,
    ClearAttentionAcknowledgementResponse,
)

router = APIRouter(tags=["attention"])


@router.get(
    "/{workspace_id}/attention-acknowledgements",
    response_model=AttentionAcknowledgementListResponse,
)
async def list_attention_acknowledgements_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        AttentionAcknowledgementBundle,
        Depends(get_attention_acknowledgement_bundle),
    ],
) -> AttentionAcknowledgementListResponse:
    result = await list_attention_acknowledgements(
        actor=actor,
        workspace_id=workspace_id,
        repository=bundle.repository,
    )
    if result.status == AttentionAcknowledgementStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    return AttentionAcknowledgementListResponse(
        status=result.status.value,
        acknowledgements=[_response(item) for item in result.acknowledgements],
    )


@router.put(
    "/{workspace_id}/attention-acknowledgements/{item_id}",
    response_model=AttentionAcknowledgementResultResponse,
)
async def acknowledge_attention_item_route(
    workspace_id: UUID,
    item_id: str,
    request: AttentionAcknowledgementRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        AttentionAcknowledgementBundle,
        Depends(get_attention_acknowledgement_bundle),
    ],
) -> AttentionAcknowledgementResultResponse:
    result = await acknowledge_attention_item(
        actor=actor,
        workspace_id=workspace_id,
        attention_item_id=item_id,
        attention_item_version=request.item_version,
        repository=bundle.repository,
        now=datetime.now(UTC),
    )
    if result.status == AttentionAcknowledgementStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    await bundle.session.commit()
    return AttentionAcknowledgementResultResponse(
        status=result.status.value,
        acknowledgement=_response(result.acknowledgement) if result.acknowledgement else None,
    )


@router.delete(
    "/{workspace_id}/attention-acknowledgements/{item_id}",
    response_model=ClearAttentionAcknowledgementResponse,
)
async def clear_attention_acknowledgement_route(
    workspace_id: UUID,
    item_id: str,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        AttentionAcknowledgementBundle,
        Depends(get_attention_acknowledgement_bundle),
    ],
) -> ClearAttentionAcknowledgementResponse:
    result = await clear_attention_acknowledgement(
        actor=actor,
        workspace_id=workspace_id,
        attention_item_id=item_id,
        repository=bundle.repository,
    )
    if result.status == AttentionAcknowledgementStatus.REJECTED:
        _raise_for_reasons(result.reasons)
    await bundle.session.commit()
    assert result.item_id is not None
    return ClearAttentionAcknowledgementResponse(
        status=result.status.value,
        item_id=result.item_id,
    )


def _raise_for_reasons(
    reasons: tuple[AttentionAcknowledgementReasonCode, ...],
) -> None:
    status_code = (
        status.HTTP_403_FORBIDDEN
        if AttentionAcknowledgementReasonCode.PERMISSION_DENIED in reasons
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(status_code=status_code, detail=[reason.value for reason in reasons])


def _response(item: AttentionAcknowledgement) -> AttentionAcknowledgementResponse:
    return AttentionAcknowledgementResponse(
        item_id=item.attention_item_id,
        item_version=item.attention_item_version,
        acknowledged_at=item.acknowledged_at,
    )