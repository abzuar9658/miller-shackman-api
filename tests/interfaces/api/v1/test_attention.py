from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.domain.attention import AttentionAcknowledgement
from app.domain.identity import (
    AuthenticatedActor,
    User,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.interfaces.api.dependencies.attention import (
    AttentionAcknowledgementBundle,
    get_attention_acknowledgement_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._attention_acknowledgement_fakes import (
    FakeAttentionAcknowledgementRepository,
)
from tests.application.use_cases._handoff_read_fakes import FakeUserRepository

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000003")


@dataclass
class RecordingSession:
    commit_count: int = 0

    async def commit(self) -> None:
        self.commit_count += 1


@dataclass
class AttentionTestClient:
    client: TestClient
    repository: FakeAttentionAcknowledgementRepository
    session: RecordingSession


def test_list_attention_acknowledgements_returns_current_users_items() -> None:
    attention_client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)
    import asyncio

    asyncio.run(
        attention_client.repository.save(
            AttentionAcknowledgement(
                workspace_id=WORKSPACE_ID,
                user_id=ACTOR_ID,
                attention_item_id="lead-1",
                attention_item_version="v1",
                acknowledged_at=NOW,
            )
        )
    )

    response = attention_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/attention-acknowledgements"
    )

    assert response.status_code == 200
    acknowledgement = response.json()["acknowledgements"][0]
    assert acknowledgement["item_id"] == "lead-1"
    assert acknowledgement["acknowledged_by_user_id"] == str(ACTOR_ID)
    assert acknowledgement["acknowledged_by_name"] == "Olivia Operator"


def test_put_and_delete_attention_acknowledgement_commit_changes() -> None:
    attention_client = _client_for_role(WorkspaceMembershipRole.MANAGER)

    put_response = attention_client.client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/attention-acknowledgements/lead-1",
        json={"item_version": "v2"},
    )

    assert put_response.status_code == 200
    acknowledgement = put_response.json()["acknowledgement"]
    assert acknowledgement["item_version"] == "v2"
    assert acknowledgement["acknowledged_by_user_id"] == str(ACTOR_ID)
    assert acknowledgement["acknowledged_by_name"] == "Olivia Operator"
    assert attention_client.session.commit_count == 1

    delete_response = attention_client.client.delete(
        f"/api/v1/workspaces/{WORKSPACE_ID}/attention-acknowledgements/lead-1"
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["item_id"] == "lead-1"
    assert attention_client.session.commit_count == 2


def test_platform_super_admin_can_list_attention_acknowledgements() -> None:
    attention_client = _client_for_role(WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN)

    response = attention_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/attention-acknowledgements"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def _client_for_role(role: WorkspaceMembershipRole) -> AttentionTestClient:
    app = create_app()
    repository = FakeAttentionAcknowledgementRepository()
    session = RecordingSession()
    user_repository = FakeUserRepository()
    user_repository.users[ACTOR_ID] = _user()

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_attention_acknowledgement_bundle] = lambda: (
        AttentionAcknowledgementBundle(
            session=session,
            repository=repository,
            user_repository=user_repository,
        )
    )

    return AttentionTestClient(
        client=TestClient(app),
        repository=repository,
        session=session,
    )


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


def _user() -> User:
    return User(
        user_id=ACTOR_ID,
        email="operator@example.com",
        email_normalized="operator@example.com",
        full_name="Olivia Operator",
        status=UserStatus.ACTIVE,
        email_verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
