from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.use_cases.review_queue_read import (
    ReviewQueueReadStatus,
    list_pending_routing_reviews,
)
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadRoutingReview,
    LeadRoutingReviewStatus,
    LeadStateClassificationOutcome,
)
from tests.application.use_cases._campaign_cadence_fakes import FakeLeadRoutingReviewRepository
from tests.application.use_cases._lead_read_fakes import (
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000003")
REVIEW_ID = UUID("00000000-0000-0000-0000-000000000004")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")


@pytest.mark.asyncio
async def test_list_pending_routing_reviews_requires_workspace_reporting_permission() -> None:
    result = await list_pending_routing_reviews(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_repository=FakeLeadRepository((_lead(),)),
        artifact_repository=FakeLeadClassificationArtifactRepository((_artifact(),)),
        routing_review_repository=_review_repository(),
    )

    assert result.status == ReviewQueueReadStatus.REJECTED


@pytest.mark.asyncio
async def test_list_pending_routing_reviews_returns_pending_views() -> None:
    result = await list_pending_routing_reviews(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_repository=FakeLeadRepository((_lead(),)),
        artifact_repository=FakeLeadClassificationArtifactRepository((_artifact(),)),
        routing_review_repository=_review_repository(),
    )

    assert result.status == ReviewQueueReadStatus.OK
    assert len(result.views) == 1
    assert result.views[0].review.review_id == REVIEW_ID
    assert result.views[0].lead.lead_id == LEAD_ID
    assert result.views[0].artifact.artifact_id == ARTIFACT_ID


def _review_repository() -> FakeLeadRoutingReviewRepository:
    repository = FakeLeadRoutingReviewRepository()
    repository.saved.append(
        LeadRoutingReview(
            review_id=REVIEW_ID,
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            artifact_id=ARTIFACT_ID,
            status=LeadRoutingReviewStatus.PENDING,
            reason_codes=("classification_rejected",),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return repository


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="agent-1",
        has_accountable_owner=True,
        primary_email="lead@example.com",
        has_email=True,
    )


def _artifact() -> LeadClassificationArtifact:
    return LeadClassificationArtifact(
        artifact_id=ARTIFACT_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        source="ai_conversation_classification",
        outcome=LeadStateClassificationOutcome.REVIEW_HOLD,
        pause_reason_code=None,
        reengagement_not_before=None,
        reengagement_window_label=None,
        confidence=0.51,
        evidence=("Low confidence route.",),
        summary="Needs operator review.",
        model="openai/gpt-4o-mini",
        prompt_version="lead_state_classification:v1",
        latency_ms=10,
        usage_tokens=20,
        applied_status=LeadClassificationAppliedStatus.REVIEW,
        applied_at=None,
        created_at=NOW,
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
