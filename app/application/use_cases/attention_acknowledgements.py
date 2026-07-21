from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.repositories import AttentionAcknowledgementRepository
from app.domain.attention import AttentionAcknowledgement
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)


class AttentionAcknowledgementStatus(StrEnum):
    OK = "ok"
    ACKNOWLEDGED = "acknowledged"
    CLEARED = "cleared"
    REJECTED = "rejected"


class AttentionAcknowledgementReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    INVALID_ITEM_ID = "invalid_item_id"
    INVALID_ITEM_VERSION = "invalid_item_version"


@dataclass(frozen=True)
class AttentionAcknowledgementListResult:
    status: AttentionAcknowledgementStatus
    acknowledgements: tuple[AttentionAcknowledgement, ...] = ()
    reasons: tuple[AttentionAcknowledgementReasonCode, ...] = ()


@dataclass(frozen=True)
class AttentionAcknowledgementResult:
    status: AttentionAcknowledgementStatus
    acknowledgement: AttentionAcknowledgement | None = None
    item_id: str | None = None
    reasons: tuple[AttentionAcknowledgementReasonCode, ...] = ()


async def list_attention_acknowledgements(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    repository: AttentionAcknowledgementRepository,
) -> AttentionAcknowledgementListResult:
    if not _has_attention_access(actor=actor, workspace_id=workspace_id):
        return AttentionAcknowledgementListResult(
            status=AttentionAcknowledgementStatus.REJECTED,
            reasons=(AttentionAcknowledgementReasonCode.PERMISSION_DENIED,),
        )

    return AttentionAcknowledgementListResult(
        status=AttentionAcknowledgementStatus.OK,
        acknowledgements=await repository.list_for_user(workspace_id, actor.user_id),
    )


async def acknowledge_attention_item(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    attention_item_id: str,
    attention_item_version: str,
    repository: AttentionAcknowledgementRepository,
    now: datetime,
) -> AttentionAcknowledgementResult:
    if not _has_attention_access(actor=actor, workspace_id=workspace_id):
        return AttentionAcknowledgementResult(
            status=AttentionAcknowledgementStatus.REJECTED,
            reasons=(AttentionAcknowledgementReasonCode.PERMISSION_DENIED,),
        )

    normalized_item_id = attention_item_id.strip()
    if not normalized_item_id:
        return AttentionAcknowledgementResult(
            status=AttentionAcknowledgementStatus.REJECTED,
            reasons=(AttentionAcknowledgementReasonCode.INVALID_ITEM_ID,),
        )

    normalized_item_version = attention_item_version.strip()
    if not normalized_item_version:
        return AttentionAcknowledgementResult(
            status=AttentionAcknowledgementStatus.REJECTED,
            reasons=(AttentionAcknowledgementReasonCode.INVALID_ITEM_VERSION,),
        )

    acknowledgement = AttentionAcknowledgement(
        workspace_id=workspace_id,
        user_id=actor.user_id,
        attention_item_id=normalized_item_id,
        attention_item_version=normalized_item_version,
        acknowledged_at=now,
    )
    return AttentionAcknowledgementResult(
        status=AttentionAcknowledgementStatus.ACKNOWLEDGED,
        acknowledgement=await repository.save(acknowledgement),
        item_id=normalized_item_id,
    )


async def clear_attention_acknowledgement(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    attention_item_id: str,
    repository: AttentionAcknowledgementRepository,
) -> AttentionAcknowledgementResult:
    if not _has_attention_access(actor=actor, workspace_id=workspace_id):
        return AttentionAcknowledgementResult(
            status=AttentionAcknowledgementStatus.REJECTED,
            reasons=(AttentionAcknowledgementReasonCode.PERMISSION_DENIED,),
        )

    normalized_item_id = attention_item_id.strip()
    if not normalized_item_id:
        return AttentionAcknowledgementResult(
            status=AttentionAcknowledgementStatus.REJECTED,
            reasons=(AttentionAcknowledgementReasonCode.INVALID_ITEM_ID,),
        )

    await repository.delete(workspace_id, actor.user_id, normalized_item_id)
    return AttentionAcknowledgementResult(
        status=AttentionAcknowledgementStatus.CLEARED,
        item_id=normalized_item_id,
    )


def _has_attention_access(*, actor: AuthenticatedActor, workspace_id: UUID) -> bool:
    return (
        actor.user_status == UserStatus.ACTIVE
        and actor.active_role
        in {
            WorkspaceMembershipRole.BROKERAGE_ADMIN,
            WorkspaceMembershipRole.MANAGER,
            WorkspaceMembershipRole.ASSIGNED_AGENT,
        }
        and actor.active_workspace_id == workspace_id
        and actor.active_membership_status == WorkspaceMembershipStatus.ACTIVE
    )