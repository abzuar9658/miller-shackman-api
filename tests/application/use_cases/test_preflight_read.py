import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestRecord,
    PreflightDigestRepository,
    PreflightVetoRecord,
)
from app.application.use_cases.preflight_read import (
    PreflightDigestViewStatus,
    PreflightReadStatus,
    get_preflight_digest_view,
    list_preflight_digest_views,
)
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
DIGEST_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")


class FakePreflightDigestRepository(PreflightDigestRepository):
    def __init__(self, digests: tuple[PreflightDigestRecord, ...]) -> None:
        self._digests = {digest.digest_id: digest for digest in digests}

    async def list_digests_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        return tuple(d for d in self._digests.values() if d.workspace_id == workspace_id)[:limit]

    async def get_digest_by_id(
        self,
        workspace_id: UUID,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        digest = self._digests.get(digest_id)
        if digest is None or digest.workspace_id != workspace_id:
            return None
        return digest

    async def get_digest(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        _ = (campaign_id, batch_id)
        for digest in self._digests.values():
            if digest.workspace_id == workspace_id:
                return digest
        return None

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        self._digests[record.digest_id] = record


def test_list_preflight_digest_views_returns_summary_for_admin() -> None:
    result = asyncio.run(
        list_preflight_digest_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            repository=FakePreflightDigestRepository((_digest(),)),
            now=NOW - timedelta(hours=1),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.views[0].status == PreflightDigestViewStatus.PENDING
    assert result.views[0].lead_count == 1
    assert result.views[0].veto_count == 1


def test_list_preflight_digest_views_marks_issued_digest_ready_after_window_expires() -> None:
    result = asyncio.run(
        list_preflight_digest_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            repository=FakePreflightDigestRepository((_digest(),)),
            now=NOW + timedelta(hours=1),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.views[0].status == PreflightDigestViewStatus.READY


def test_get_preflight_digest_view_rejects_assigned_agent() -> None:
    result = asyncio.run(
        get_preflight_digest_view(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            digest_id=str(DIGEST_ID),
            repository=FakePreflightDigestRepository((_digest(),)),
        )
    )

    assert result.status == PreflightReadStatus.REJECTED


def test_get_preflight_digest_view_preserves_failed_digest_status() -> None:
    result = asyncio.run(
        get_preflight_digest_view(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            digest_id=str(DIGEST_ID),
            repository=FakePreflightDigestRepository((_digest(status=PreflightDigestIssueStatus.FAILED),)),
            now=NOW + timedelta(hours=1),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.view is not None
    assert result.view.status == PreflightDigestViewStatus.FAILED


def _digest(
    *, status: PreflightDigestIssueStatus = PreflightDigestIssueStatus.ISSUED
) -> PreflightDigestRecord:
    return PreflightDigestRecord(
        digest_id=str(DIGEST_ID),
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id="batch-1",
        status=status,
        entries=(
            PreflightDigestEntry(
                lead_id=LEAD_ID,
                recipient_id="agent-1",
                recipient_destination="agent@example.com",
                display_name="Jordan Seller",
            ),
        ),
        digest_sent_at=NOW,
        veto_window_expires_at=NOW,
        vetoes=(
            PreflightVetoRecord(
                lead_id=LEAD_ID,
                actor_id="agent-1",
                recorded_at=NOW,
                idempotency_key="veto-1",
                reason="Already contacted",
            ),
        ),
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=UUID("00000000-0000-0000-0000-000000000005"),
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000006"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )
