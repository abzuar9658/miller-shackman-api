from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.messaging import EmailMessage, SMSMessage
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundSendReconciliationRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceRepository,
)
from app.application.use_cases.revalidate_outbound_send_request import (
    LockingOutboundMessageRepository,
    LockingOutboundSendRequestRepository,
    OutboundSendRevalidationReason,
    revalidate_outbound_send_request,
)
from app.domain.campaigns.execution import (
    CampaignCadenceStep,
    CampaignExecutionConfig,
    CampaignVersionStatus,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.pre_send import PreSendReasonCode, ProviderSendStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SuppressionType,
    WorkspaceContactPolicy,
)
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.domain.workspace_automation import WorkspaceOperationalControl

NOW = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")
WORKFLOW_ID = UUID("33333333-3333-3333-3333-333333333333")
MESSAGE_ID = UUID("44444444-4444-4444-4444-444444444444")
REQUEST_ID = UUID("55555555-5555-5555-5555-555555555555")
RECONCILIATION_ID = UUID("66666666-6666-6666-6666-666666666666")
CAMPAIGN_ID = UUID("77777777-7777-7777-7777-777777777777")
CAMPAIGN_VERSION_ID = UUID("88888888-8888-8888-8888-888888888888")
CADENCE_STEP_ID = UUID("99999999-9999-9999-9999-999999999999")


class FakeRepositories:
    def __init__(self) -> None:
        self.lock_order: list[str] = []
        self.lead = _lead()
        self.workflow = _workflow()
        self.message = _message()
        self.request = _request()
        self.reconciliation = _reconciliation()
        self.campaign = _campaign()

    async def get_by_id_for_update(self, workspace_id: UUID, object_id: UUID) -> object | None:
        _ = workspace_id
        if object_id == LEAD_ID:
            self.lock_order.append("lead")
            return self.lead
        if object_id == MESSAGE_ID:
            self.lock_order.append("message")
            return self.message
        if object_id == REQUEST_ID:
            self.lock_order.append("request")
            return self.request
        self.lock_order.append("reconciliation")
        return self.reconciliation

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> LeadWorkflow:
        _ = (workspace_id, lead_id)
        self.lock_order.append("workflow")
        return self.workflow

    async def get_by_id(self, workspace_id: UUID) -> Workspace:
        _ = workspace_id
        return _workspace()

    async def get_by_workspace_id(self, workspace_id: UUID) -> object:
        _ = workspace_id
        return WorkspaceOperationalControl(workspace_id=WORKSPACE_ID)

    async def get_active_for_campaign(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
    ) -> CampaignExecutionConfig:
        _ = (workspace_id, campaign_id)
        return self.campaign

    async def get_latest_sent_at_for_lead(self, *args: object, **kwargs: object) -> None:
        _ = (args, kwargs)

    async def get_latest_received_at_for_lead(self, workspace_id: UUID, lead_id: UUID) -> None:
        _ = (workspace_id, lead_id)


class FakeContactPolicyRepository:
    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceContactPolicy:
        return WorkspaceContactPolicy(
            workspace_id=workspace_id,
            quiet_hours_start=time(10),
            quiet_hours_end=time(17),
        )


async def test_sms_opt_out_after_enqueue_is_rejected_under_all_dispatch_locks() -> None:
    repositories = FakeRepositories()

    result = await revalidate_outbound_send_request(
        request=repositories.request,
        lead_repository=cast(LeadRepository, repositories),
        workflow_repository=cast(LeadWorkflowRepository, repositories),
        message_repository=cast(LockingOutboundMessageRepository, repositories),
        request_repository=cast(LockingOutboundSendRequestRepository, repositories),
        reconciliation_repository=cast(OutboundSendReconciliationRepository, repositories),
        campaign_repository=cast(CampaignExecutionRepository, repositories),
        workspace_repository=cast(WorkspaceRepository, repositories),
        workspace_control_repository=cast(WorkspaceOperationalControlRepository, repositories),
        contact_policy_repository=cast(
            WorkspaceContactPolicyRepository,
            FakeContactPolicyRepository(),
        ),
        inbound_message_repository=cast(InboundMessageRepository, repositories),
        now=NOW,
    )

    assert result.allowed is False
    assert result.reasons == (OutboundSendRevalidationReason.PRE_SEND_BLOCKED,)
    assert result.pre_send_decision is not None
    assert PreSendReasonCode.CHANNEL_NOT_CONTACTABLE in result.pre_send_decision.reasons
    assert repositories.lock_order == [
        "lead",
        "workflow",
        "message",
        "request",
        "reconciliation",
    ]


async def test_explicit_live_crm_activity_fact_is_rejected_under_dispatch_locks() -> None:
    repositories = FakeRepositories()
    repositories.lead = _lead(sms_opted_out=False)

    result = await revalidate_outbound_send_request(
        request=repositories.request,
        lead_repository=cast(LeadRepository, repositories),
        workflow_repository=cast(LeadWorkflowRepository, repositories),
        message_repository=cast(LockingOutboundMessageRepository, repositories),
        request_repository=cast(LockingOutboundSendRequestRepository, repositories),
        reconciliation_repository=cast(OutboundSendReconciliationRepository, repositories),
        campaign_repository=cast(CampaignExecutionRepository, repositories),
        workspace_repository=cast(WorkspaceRepository, repositories),
        workspace_control_repository=cast(WorkspaceOperationalControlRepository, repositories),
        contact_policy_repository=cast(
            WorkspaceContactPolicyRepository,
            FakeContactPolicyRepository(),
        ),
        inbound_message_repository=cast(InboundMessageRepository, repositories),
        now=NOW,
        recent_human_activity=True,
    )

    assert result.allowed is False
    assert result.pre_send_decision is not None
    assert PreSendReasonCode.RECENT_HUMAN_ACTIVITY in result.pre_send_decision.reasons
    assert repositories.lock_order == [
        "lead",
        "workflow",
        "message",
        "request",
        "reconciliation",
    ]


async def test_email_with_unknown_permission_is_allowed() -> None:
    repositories = FakeRepositories()
    _configure_email(repositories)

    result = await revalidate_outbound_send_request(
        request=repositories.request,
        lead_repository=cast(LeadRepository, repositories),
        workflow_repository=cast(LeadWorkflowRepository, repositories),
        message_repository=cast(LockingOutboundMessageRepository, repositories),
        request_repository=cast(LockingOutboundSendRequestRepository, repositories),
        reconciliation_repository=cast(OutboundSendReconciliationRepository, repositories),
        campaign_repository=cast(CampaignExecutionRepository, repositories),
        workspace_repository=cast(WorkspaceRepository, repositories),
        workspace_control_repository=cast(WorkspaceOperationalControlRepository, repositories),
        contact_policy_repository=cast(
            WorkspaceContactPolicyRepository,
            FakeContactPolicyRepository(),
        ),
        inbound_message_repository=cast(InboundMessageRepository, repositories),
        now=NOW,
    )

    assert result.allowed is True


async def test_email_unsubscribed_is_still_rejected() -> None:
    repositories = FakeRepositories()
    _configure_email(repositories, email_unsubscribed=True)

    result = await revalidate_outbound_send_request(
        request=repositories.request,
        lead_repository=cast(LeadRepository, repositories),
        workflow_repository=cast(LeadWorkflowRepository, repositories),
        message_repository=cast(LockingOutboundMessageRepository, repositories),
        request_repository=cast(LockingOutboundSendRequestRepository, repositories),
        reconciliation_repository=cast(OutboundSendReconciliationRepository, repositories),
        campaign_repository=cast(CampaignExecutionRepository, repositories),
        workspace_repository=cast(WorkspaceRepository, repositories),
        workspace_control_repository=cast(WorkspaceOperationalControlRepository, repositories),
        contact_policy_repository=cast(
            WorkspaceContactPolicyRepository,
            FakeContactPolicyRepository(),
        ),
        inbound_message_repository=cast(InboundMessageRepository, repositories),
        now=NOW,
    )

    assert result.allowed is False
    assert result.pre_send_decision is not None
    assert PreSendReasonCode.CHANNEL_NOT_CONTACTABLE in result.pre_send_decision.reasons


async def test_sms_with_unknown_consent_is_allowed() -> None:
    repositories = FakeRepositories()
    repositories.lead = replace(
        _lead(sms_opted_out=False),
        sms_permission_status=ContactPermissionStatus.UNKNOWN,
    )

    result = await revalidate_outbound_send_request(
        request=repositories.request,
        lead_repository=cast(LeadRepository, repositories),
        workflow_repository=cast(LeadWorkflowRepository, repositories),
        message_repository=cast(LockingOutboundMessageRepository, repositories),
        request_repository=cast(LockingOutboundSendRequestRepository, repositories),
        reconciliation_repository=cast(OutboundSendReconciliationRepository, repositories),
        campaign_repository=cast(CampaignExecutionRepository, repositories),
        workspace_repository=cast(WorkspaceRepository, repositories),
        workspace_control_repository=cast(WorkspaceOperationalControlRepository, repositories),
        contact_policy_repository=cast(
            WorkspaceContactPolicyRepository,
            FakeContactPolicyRepository(),
        ),
        inbound_message_repository=cast(InboundMessageRepository, repositories),
        now=NOW,
    )

    assert result.allowed is True


async def test_sms_with_denied_consent_is_rejected() -> None:
    repositories = FakeRepositories()
    repositories.lead = replace(
        _lead(sms_opted_out=False),
        sms_permission_status=ContactPermissionStatus.DENIED,
    )

    result = await revalidate_outbound_send_request(
        request=repositories.request,
        lead_repository=cast(LeadRepository, repositories),
        workflow_repository=cast(LeadWorkflowRepository, repositories),
        message_repository=cast(LockingOutboundMessageRepository, repositories),
        request_repository=cast(LockingOutboundSendRequestRepository, repositories),
        reconciliation_repository=cast(OutboundSendReconciliationRepository, repositories),
        campaign_repository=cast(CampaignExecutionRepository, repositories),
        workspace_repository=cast(WorkspaceRepository, repositories),
        workspace_control_repository=cast(WorkspaceOperationalControlRepository, repositories),
        contact_policy_repository=cast(
            WorkspaceContactPolicyRepository,
            FakeContactPolicyRepository(),
        ),
        inbound_message_repository=cast(InboundMessageRepository, repositories),
        now=NOW,
    )

    assert result.allowed is False
    assert result.pre_send_decision is not None
    assert PreSendReasonCode.CHANNEL_NOT_CONTACTABLE in result.pre_send_decision.reasons


def _configure_email(
    repositories: FakeRepositories,
    *,
    email_unsubscribed: bool = False,
) -> None:
    repositories.lead = _email_lead(email_unsubscribed=email_unsubscribed)
    repositories.message = replace(
        repositories.message,
        channel=ContactChannel.EMAIL,
        subject="Checking in",
    )
    repositories.request = replace(
        repositories.request,
        channel=ContactChannel.EMAIL,
        provider_name="mailpit",
        provider_payload=EmailMessage(
            to_email="lead@example.com",
            subject="Checking in",
            body="Checking in.",
            idempotency_key="outbound:test",
        ).model_dump(mode="json"),
    )
    repositories.reconciliation = replace(
        repositories.reconciliation,
        provider_name="mailpit",
    )
    repositories.campaign = _campaign(channel=ContactChannel.EMAIL)


def _lead(*, sms_opted_out: bool = True) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        primary_phone="+15551234567",
        has_phone=True,
        has_sms_capable_phone=True,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
        suppression_types=(
            frozenset({SuppressionType.SMS_OPT_OUT}) if sms_opted_out else frozenset()
        ),
    )


def _email_lead(*, email_unsubscribed: bool = False) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.UNKNOWN,
        do_not_contact=False,
        suppression_types=(
            frozenset({SuppressionType.EMAIL_UNSUBSCRIBED})
            if email_unsubscribed
            else frozenset()
        ),
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id=str(CADENCE_STEP_ID),
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key="outbound:test",
        body="Checking in.",
        scheduled_for=NOW - timedelta(minutes=1),
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=1),
        provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
    )


def _request() -> OutboundSendRequest:
    return OutboundSendRequest(
        request_id=REQUEST_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-1",
        outbound_message_id=MESSAGE_ID,
        reconciliation_id=RECONCILIATION_ID,
        idempotency_key="outbound:test",
        channel=ContactChannel.SMS,
        provider_name="twilio",
        provider_payload=SMSMessage(
            to_phone="+15551234567",
            body="Checking in.",
            idempotency_key="outbound:test",
        ).model_dump(mode="json"),
        status=OutboundSendRequestStatus.DISPATCHING,
        attempt_count=1,
        available_at=NOW,
        claimed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _reconciliation() -> OutboundSendReconciliation:
    return OutboundSendReconciliation(
        reconciliation_id=RECONCILIATION_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-1",
        outbound_message_id=MESSAGE_ID,
        idempotency_key="outbound:test",
        status=OutboundSendReconciliationStatus.PENDING,
        provider_name="twilio",
        provider_message_id=None,
        provider_delivery_status=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Test Brokerage",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="UTC",
        created_at=NOW,
        updated_at=NOW,
    )


def _campaign(channel: ContactChannel = ContactChannel.SMS) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant leads",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(channel,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10),
        quiet_hours_end=time(17),
        timezone="UTC",
        preflight_digest_enabled=True,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=CADENCE_STEP_ID,
                workspace_id=WORKSPACE_ID,
                campaign_version_id=CAMPAIGN_VERSION_ID,
                step_order=1,
                channel=channel,
                delay_hours=0,
                message_goal="Check in",
                template_key="step-1",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )