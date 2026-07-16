from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightDigestRepository,
    PreflightVetoRecord,
)
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.preflight import PreflightReadBundle, get_preflight_read_bundle
from app.main import create_app

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
DIGEST_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")


@dataclass
class PreflightTestClient:
    client: TestClient


class FakePreflightDigestRepository(PreflightDigestRepository):
    def __init__(self) -> None:
        self.digest = _digest()

    async def list_digests_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        return (self.digest,) if workspace_id == WORKSPACE_ID else ()

    async def get_digest_by_id(
        self,
        workspace_id: UUID,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        if workspace_id == WORKSPACE_ID and digest_id == self.digest.digest_id:
            return self.digest
        return None

    async def get_digest(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        _ = (workspace_id, campaign_id, batch_id)
        return None

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        self.digest = record


def test_preflight_routes_return_list_and_detail_for_brokerage_admin() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests")
    detail_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests/{DIGEST_ID}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["digests"][0]["status"] == "pending"
    assert list_response.json()["digests"][0]["lead_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["digest"]["status"] == "pending"
    assert detail_response.json()["entries"][0]["vetoed"] is True


def test_preflight_routes_reject_assigned_agent() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def _client_for_role(role: WorkspaceMembershipRole) -> PreflightTestClient:
    app = create_app()
    bundle = PreflightReadBundle(repository=FakePreflightDigestRepository())
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_preflight_read_bundle] = lambda: bundle
    return PreflightTestClient(client=TestClient(app))


def _digest() -> PreflightDigestRecord:
    return PreflightDigestRecord(
        digest_id=str(DIGEST_ID),
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id="batch-1",
        status=PreflightDigestIssueStatus.ISSUED,
        entries=(
            PreflightDigestEntry(
                lead_id=LEAD_ID,
                recipient_id="agent-1",
                recipient_destination="agent@example.com",
                display_name="Jordan Seller",
            ),
        ),
        notification_records=(
            PreflightDigestNotificationRecord(
                recipient_id="agent-1",
                idempotency_key="notif-1",
                accepted=True,
                provider_reference="provider-1",
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
