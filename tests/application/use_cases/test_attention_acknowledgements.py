from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.use_cases.attention_acknowledgements import (
    AttentionAcknowledgementStatus,
    acknowledge_attention_item,
    clear_attention_acknowledgement,
    list_attention_acknowledgements,
)
from app.domain.attention import AttentionAcknowledgement
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from tests.application.use_cases._attention_acknowledgement_fakes import (
    FakeAttentionAcknowledgementRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000003")


def test_active_manager_can_list_acknowledgements() -> None:
    repository = FakeAttentionAcknowledgementRepository()
    _run(
        repository.save(
            AttentionAcknowledgement(
                workspace_id=WORKSPACE_ID,
                user_id=ACTOR_ID,
                attention_item_id="lead-1",
                attention_item_version="v1",
                acknowledged_at=NOW,
            )
        )
    )

    result = _run(
        list_attention_acknowledgements(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            repository=repository,
        )
    )

    assert result.status == AttentionAcknowledgementStatus.OK
    assert len(result.acknowledgements) == 1
    assert result.acknowledgements[0].attention_item_id == "lead-1"


def test_acknowledging_attention_item_upserts_latest_version() -> None:
    repository = FakeAttentionAcknowledgementRepository()

    first = _run(
        acknowledge_attention_item(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            attention_item_id="lead-1",
            attention_item_version="v1",
            repository=repository,
            now=NOW,
        )
    )
    second = _run(
        acknowledge_attention_item(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            attention_item_id="lead-1",
            attention_item_version="v2",
            repository=repository,
            now=LATER,
        )
    )

    assert first.status == AttentionAcknowledgementStatus.ACKNOWLEDGED
    assert second.status == AttentionAcknowledgementStatus.ACKNOWLEDGED
    assert second.acknowledgement is not None
    assert second.acknowledgement.attention_item_version == "v2"
    assert second.acknowledgement.acknowledged_at == LATER


def test_platform_super_admin_cannot_manage_workspace_attention_acknowledgements() -> None:
    repository = FakeAttentionAcknowledgementRepository()

    result = _run(
        clear_attention_acknowledgement(
            actor=_actor(WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN),
            workspace_id=WORKSPACE_ID,
            attention_item_id="lead-1",
            repository=repository,
        )
    )

    assert result.status == AttentionAcknowledgementStatus.REJECTED
    assert [reason.value for reason in result.reasons] == ["permission_denied"]


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)