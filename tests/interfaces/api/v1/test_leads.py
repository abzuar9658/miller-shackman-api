from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import (
    Handoff,
    HandoffReasonCode,
    InboundMessage,
    InboundMessageClassificationStatus,
)
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
from app.interfaces.api.dependencies.lead_resume import (
    LeadResumeActionBundle,
    LeadResumeReadBundle,
    get_lead_resume_action_bundle,
    get_lead_resume_read_bundle,
)
from app.interfaces.api.dependencies.lead_read import LeadReadBundle, get_lead_read_bundle
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._campaign_cadence_fakes import FakeWorkspaceContactPolicyRepository
from tests.application.use_cases._campaign_enrollment_fakes import FakeLeadNurtureWorkflowSignaler
from tests.application.use_cases._lead_read_fakes import (
    FakeHandoffRepository,
    FakeInboundMessageRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeUserRepository,
    FakeWorkflowTransitionRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000005")


@dataclass
class LeadsTestClient:
    client: TestClient
    signaler: FakeLeadNurtureWorkflowSignaler


def test_lead_routes_return_list_and_detail() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads")
    detail_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}")

    assert list_response.status_code == 200
    assert list_response.json()["leads"][0]["lead"]["display_name"] == "Jordan Seller"
    assert detail_response.status_code == 200
    assert len(detail_response.json()["workflow_transitions"]) == 1


def test_resume_routes_return_eligibility_and_request_resume() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    eligibility_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume-eligibility"
    )
    resume_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume",
        json={"reason": "Agent requested AI resume after manual follow-up."},
    )

    assert eligibility_response.status_code == 200
    assert eligibility_response.json()["can_resume"] is True
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "requested"
    assert client.signaler.calls[0]["temporal_workflow_id"] == "wf-1"


def test_assigned_agent_can_resume_own_lead() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/leads/{LEAD_ID}/resume",
        json={"reason": "Resuming my assigned lead after handoff."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "requested"


def test_lead_routes_reject_assigned_agent() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/leads")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def _client_for_role(role: WorkspaceMembershipRole) -> LeadsTestClient:
    app = create_app()
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        primary_email="lead@example.com",
        primary_phone="+15555550100",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        has_accountable_owner=True,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
        mapped_custom_fields={
            "assigned_agent_user_id": str(USER_ID),
            "display_name": "Jordan Seller",
        },
    )
    workflow = LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="wf-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000006"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.HUMAN_HANDOFF,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    policy_repository = FakeWorkspaceContactPolicyRepository(
        WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
        )
    )
    signaler = FakeLeadNurtureWorkflowSignaler()
    bundle = LeadReadBundle(
        lead_repository=FakeLeadRepository((lead,)),
        workflow_repository=FakeLeadWorkflowRepository((workflow,)),
        workflow_transition_repository=FakeWorkflowTransitionRepository(
            (
                WorkflowTransition(
                    transition_id=UUID("00000000-0000-0000-0000-000000000007"),
                    workspace_id=WORKSPACE_ID,
                    workflow_id=WORKFLOW_ID,
                    lead_id=LEAD_ID,
                    campaign_id=CAMPAIGN_ID,
                    from_state=WorkflowState.ACTIVE_NURTURE,
                    to_state=WorkflowState.WAITING_FOR_RESPONSE,
                    reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
                    created_at=NOW,
                ),
            )
        ),
        inbound_message_repository=FakeInboundMessageRepository(
            (
                InboundMessage(
                    inbound_message_id=UUID("00000000-0000-0000-0000-000000000008"),
                    workspace_id=WORKSPACE_ID,
                    conversation_id=UUID("00000000-0000-0000-0000-000000000009"),
                    lead_id=LEAD_ID,
                    channel=ContactChannel.SMS,
                    provider="twilio",
                    provider_message_id="pm-1",
                    body="Still interested",
                    received_at=NOW,
                    classification_status=InboundMessageClassificationStatus.CLASSIFIED,
                    created_at=NOW,
                ),
            )
        ),
        outbound_message_repository=FakeOutboundMessageRepository(
            (
                OutboundMessage(
                    message_id=UUID("00000000-0000-0000-0000-000000000010"),
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
                ),
            )
        ),
        handoff_repository=FakeHandoffRepository(
            (
                Handoff(
                    handoff_id=UUID("00000000-0000-0000-0000-000000000011"),
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    reason_code=HandoffReasonCode.HUMAN_REQUESTED,
                    summary="Lead asked for a callback.",
                    created_at=NOW,
                ),
            )
        ),
        user_repository=FakeUserRepository(
            {
                USER_ID: User(
                    user_id=USER_ID,
                    email="agent@example.com",
                    email_normalized="agent@example.com",
                    full_name="Jordan Agent",
                    status=UserStatus.ACTIVE,
                    email_verified_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            }
        ),
    )
    resume_read_bundle = LeadResumeReadBundle(
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        workspace_contact_policy_repository=policy_repository,
    )
    resume_action_bundle = LeadResumeActionBundle(
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        workspace_contact_policy_repository=policy_repository,
        lead_nurture_workflow_signaler=signaler,
    )
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_lead_read_bundle] = lambda: bundle
    app.dependency_overrides[get_lead_resume_read_bundle] = lambda: resume_read_bundle
    app.dependency_overrides[get_lead_resume_action_bundle] = lambda: resume_action_bundle
    return LeadsTestClient(client=TestClient(app), signaler=signaler)


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
