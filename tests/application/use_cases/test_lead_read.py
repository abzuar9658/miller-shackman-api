import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.use_cases.lead_read import (
    LeadReadReasonCode,
    LeadReadStatus,
    get_lead_detail_view,
    list_lead_views,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.campaigns.rejected_draft_review import (
    RejectedDraftReview,
    RejectedDraftReviewStatus,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Handoff,
    HandoffReasonCode,
    InboundMessage,
    InboundMessageClassificationStatus,
)
from app.domain.crm_agent_mapping import CRMAgent
from app.domain.identity import (
    AuthenticatedActor,
    User,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)
from tests.application.use_cases._lead_read_fakes import (
    FakeCRMAgentRepository,
    FakeHandoffRepository,
    FakeInboundMessageRepository,
    FakeLeadActivityRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeRejectedDraftReviewRepository,
    FakeUserRepository,
    FakeWorkflowTransitionRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000005")
INBOUND_ID = UUID("00000000-0000-0000-0000-000000000006")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000007")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000008")


def test_list_lead_views_returns_owner_and_workflow() -> None:
    result = asyncio.run(
        list_lead_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_repository=FakeLeadRepository((_lead(),)),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            activity_repository=FakeLeadActivityRepository(_activity_items()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(
                (_rejected_draft_review(),)
            ),
            inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
            handoff_repository=FakeHandoffRepository((_handoff(),)),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository((_crm_agent(),)),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert result.views[0].assigned_agent_name == "Jordan Agent"
    assert result.views[0].ownership.crm_assigned_agent is not None
    assert result.views[0].ownership.crm_assigned_agent.name == "Jordan CRM Agent"
    assert result.views[0].ownership.mapped_app_user is not None
    assert result.views[0].ownership.mapped_app_user.full_name == "Jordan Agent"
    assert result.views[0].latest_workflow is not None
    assert result.views[0].activity_summary is not None
    assert result.views[0].activity_summary.activity_count == 3


def test_get_lead_detail_view_returns_messages_and_transitions() -> None:
    result = asyncio.run(
        get_lead_detail_view(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            lead_repository=FakeLeadRepository((_lead(),)),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            workflow_transition_repository=FakeWorkflowTransitionRepository((_transition(),)),
            activity_repository=FakeLeadActivityRepository(_activity_items()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(
                (_rejected_draft_review(),)
            ),
            inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
            outbound_message_repository=FakeOutboundMessageRepository((_outbound_message(),)),
            handoff_repository=FakeHandoffRepository((_handoff(),)),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository((_crm_agent(),)),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert result.view is not None
    assert len(result.view.workflow_transitions) == 1
    assert len(result.view.rejected_draft_reviews) == 1
    assert len(result.view.inbound_messages) == 1
    assert len(result.view.outbound_messages) == 1
    assert len(result.view.handoffs) == 1
    assert result.view.lead.ownership.crm_assigned_agent is not None
    assert result.view.lead.ownership.crm_assigned_agent.name == "Jordan CRM Agent"
    assert result.view.lead.ownership.mapped_app_user is not None
    assert result.view.lead.ownership.mapped_app_user.email == "agent@example.com"


def test_assigned_agent_list_lead_views_returns_only_owned_leads() -> None:
    result = asyncio.run(
        list_lead_views(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_repository=FakeLeadRepository((_lead(), _other_lead())),
            workflow_repository=FakeLeadWorkflowRepository((_workflow(),)),
            activity_repository=FakeLeadActivityRepository(_activity_items()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(()),
            inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
            handoff_repository=FakeHandoffRepository((_handoff(),)),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository((_crm_agent(),)),
        )
    )

    assert result.status == LeadReadStatus.OK
    assert len(result.views) == 1
    assert result.views[0].lead.lead_id == LEAD_ID


def test_assigned_agent_get_lead_detail_view_rejects_unowned_lead() -> None:
    result = asyncio.run(
        get_lead_detail_view(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            lead_id=UUID("00000000-0000-0000-0000-000000000099"),
            lead_repository=FakeLeadRepository((_other_lead(),)),
            workflow_repository=FakeLeadWorkflowRepository(()),
            workflow_transition_repository=FakeWorkflowTransitionRepository(()),
            activity_repository=FakeLeadActivityRepository(()),
            rejected_draft_review_repository=FakeRejectedDraftReviewRepository(()),
            inbound_message_repository=FakeInboundMessageRepository(()),
            outbound_message_repository=FakeOutboundMessageRepository(()),
            handoff_repository=FakeHandoffRepository(()),
            user_repository=FakeUserRepository({USER_ID: _user()}),
            crm_agent_repository=FakeCRMAgentRepository(()),
        )
    )

    assert result.status == LeadReadStatus.REJECTED
    assert result.reasons == (LeadReadReasonCode.PERMISSION_DENIED,)


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="agent-1",
        assigned_agent_user_id=USER_ID,
        effective_owner_user_id=USER_ID,
        primary_email="lead@example.com",
        primary_phone="+15555550123",
        mapped_custom_fields={"display_name": "Jordan Seller"},
    )


def _other_lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=UUID("00000000-0000-0000-0000-000000000099"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-2",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_user_id=UUID("00000000-0000-0000-0000-000000000098"),
        effective_owner_user_id=UUID("00000000-0000-0000-0000-000000000098"),
        primary_email="other@example.com",
        primary_phone="+15555550124",
        mapped_custom_fields={"display_name": "Casey Unowned"},
    )


def _crm_agent() -> CRMAgent:
    return CRMAgent(
        agent_record_id=UUID("00000000-0000-0000-0000-000000000012"),
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id="agent-1",
        name="Jordan CRM Agent",
        email="crm.agent@example.com",
        email_normalized="crm.agent@example.com",
        phone="+15555550155",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={"id": "agent-1"},
        created_at=NOW,
        updated_at=NOW,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="wf-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000009"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _transition() -> WorkflowTransition:
    return WorkflowTransition(
        transition_id=UUID("00000000-0000-0000-0000-000000000010"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        from_state=WorkflowState.ACTIVE_NURTURE,
        to_state=WorkflowState.WAITING_FOR_RESPONSE,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        created_at=NOW,
    )


def _inbound_message() -> InboundMessage:
    return InboundMessage(
        inbound_message_id=INBOUND_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=UUID("00000000-0000-0000-0000-000000000011"),
        lead_id=LEAD_ID,
        channel=ContactChannel.SMS,
        provider="twilio",
        provider_message_id="pm-1",
        body="Still interested",
        received_at=NOW,
        classification_status=InboundMessageClassificationStatus.CLASSIFIED,
        created_at=NOW,
    )


def _outbound_message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.SENT,
        idempotency_key="msg-1",
        body="Checking in",
        created_at=NOW,
        updated_at=NOW,
        provider_send_status=ProviderSendStatus.ACCEPTED,
    )


def _handoff() -> Handoff:
    return Handoff(
        handoff_id=HANDOFF_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked for a callback.",
        created_at=NOW,
    )


def _user() -> User:
    return User(
        user_id=USER_ID,
        email="agent@example.com",
        email_normalized="agent@example.com",
        full_name="Jordan Agent",
        status=UserStatus.ACTIVE,
        email_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _activity_items() -> tuple[LeadActivityItem, ...]:
    return (
        LeadActivityItem(
            activity_id=INBOUND_ID,
            lead_id=LEAD_ID,
            kind=LeadActivityKind.INBOUND_MESSAGE,
            occurred_at=NOW,
            title="Inbound reply received",
            preview="Still interested",
            channel="sms",
            direction="inbound",
            status="classified",
            actor_name="twilio",
        ),
        LeadActivityItem(
            activity_id=MESSAGE_ID,
            lead_id=LEAD_ID,
            kind=LeadActivityKind.OUTBOUND_MESSAGE,
            occurred_at=NOW,
            title="Outbound outreach logged",
            preview="Checking in",
            channel="sms",
            direction="outbound",
            status="sent",
        ),
        LeadActivityItem(
            activity_id=HANDOFF_ID,
            lead_id=LEAD_ID,
            kind=LeadActivityKind.HANDOFF,
            occurred_at=NOW,
            title="Human handoff created",
            preview="Lead asked for a callback.",
            status="created",
        ),
    )


def _rejected_draft_review() -> RejectedDraftReview:
    return RejectedDraftReview(
        review_id=UUID("00000000-0000-0000-0000-000000000012"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        workflow_transition_id=UUID("00000000-0000-0000-0000-000000000013"),
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=UUID("00000000-0000-0000-0000-000000000014"),
        cadence_step_id=UUID("00000000-0000-0000-0000-000000000015"),
        channel=ContactChannel.SMS,
        status=RejectedDraftReviewStatus.PENDING_REVIEW,
        reason_codes=("draft_rejected",),
        draft_reason_codes=("low_confidence",),
        review_blockers=(),
        draft_safety_flags=(),
        draft_personalization_notes=("Used safe canonical context.",),
        draft_body="Checking in about your plans.",
        explanation="Planning blocked: draft rejected.",
        draft_confidence=0.42,
        draft_model="openai/gpt-4o-mini",
        draft_prompt_version="outbound_message_draft:v1",
        can_approve_send=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000012"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )
