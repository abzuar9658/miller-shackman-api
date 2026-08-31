"""Admin-confirmed send-now for deferred outbound messages.

A message deferred by a timing guard (quiet hours, simultaneous-channel window)
stays PENDING with a status_detail explanation. An explicit, permission-checked
operator action may retry it immediately, and consent, handoff, contactability,
and every other pre-send guard still applies to that retry.
"""

from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from app.application.use_cases.send_deferred_outbound_message_now import (
    SendDeferredMessageNowResult,
    SendDeferredMessageNowStatus,
    send_deferred_outbound_message_now,
)
from app.domain.campaigns import PausedSearchTrackStepPhase
from app.domain.campaigns.admin import CampaignAdminCampaign, CampaignAdminVersion
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.execution import (
    CampaignCadenceStep,
    CampaignExecutionConfig,
    CampaignVersionStatus,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    WorkspaceContactPolicy,
)
from app.domain.crm_sync import ExternalEvent
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    Workspace,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    WorkflowState,
    WorkflowTransitionReasonCode,
)
from tests.application.use_cases._campaign_admin_fakes import FakeCampaignAdminRepository
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadRepository,
    FakeOutboundMessageRepository,
    FakePausedSearchOccurrenceRepository,
    FakeSMSProvider,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceOperationalControlRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases.test_lead_paused_search import FakeExternalEventRepository

NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)  # 10 AM Chicago — inside allowed hours
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000005")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000006")
STEP_ONE_ID = UUID("00000000-0000-0000-0000-000000000007")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000008")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000009")
MESSAGE_ID = UUID("00000000-0000-0000-0000-00000000000a")
OCCURRENCE_ID = UUID("00000000-0000-0000-0000-00000000000b")
DEFERRAL_DETAIL = (
    "Sending blocked: pre send blocked. Pre-send checks blocked delivery: "
    "outside allowed hours. Next eligible send time: 2026-07-11T14:00:00+00:00."
)


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000010"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _lead(*, do_not_contact: bool = False) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        primary_email="lead@example.com",
        has_email=True,
        email_count=1,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=do_not_contact,
        mapped_custom_fields={"assigned_agent_user_id": str(USER_ID)},
    )


def _workflow(
    *,
    state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    paused_search: bool = True,
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id=f"lead-nurture:{LEAD_ID}:enrollment-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000011"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=3,
        created_at=NOW,
        updated_at=NOW,
        current_step_id=None if paused_search else STEP_ONE_ID,
        next_action_at=NOW + timedelta(hours=23),
        paused_search_track_version_id=TRACK_VERSION_ID if paused_search else None,
        paused_search_track_step_id=STEP_ONE_ID if paused_search else None,
    )



def _deferred_message(
    *,
    status: OutboundMessageStatus = OutboundMessageStatus.PENDING,
    status_detail: str | None = DEFERRAL_DETAIL,
    cadence_step_id: UUID = STEP_ONE_ID,
    workflow_id: UUID | None = WORKFLOW_ID,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        workflow_id=workflow_id,
        cadence_step_id=str(cadence_step_id),
        channel=ContactChannel.EMAIL,
        status=status,
        idempotency_key=f"outbound:test:{MESSAGE_ID}",
        body="Checking in on your home search timing.",
        subject="Checking in on your home search",
        scheduled_for=NOW + timedelta(hours=23),
        planned_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        message_version=1,
        provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
        status_detail=status_detail,
    )


def _earlier_sent_message() -> OutboundMessage:
    # Prior same-channel outreach an hour earlier: send spacing is owned by the
    # track cadence, so it must not block this send.
    return OutboundMessage(
        message_id=UUID("00000000-0000-0000-0000-000000000012"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id=str(STEP_ONE_ID),
        channel=ContactChannel.EMAIL,
        status=OutboundMessageStatus.SENT,
        idempotency_key="outbound:test:earlier",
        body="Earlier outreach",
        subject="Earlier outreach",
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        sent_at=NOW - timedelta(hours=1),
        provider_send_status=ProviderSendStatus.ACCEPTED,
        provider_name="mailgun",
    )


def _occurrence(
    status: RecurringOccurrenceStatus = RecurringOccurrenceStatus.PLANNED,
) -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=OCCURRENCE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=TRACK_VERSION_ID,
        step_id=STEP_ONE_ID,
        phase=PausedSearchTrackStepPhase.REACTIVATION,
        occurrence_number=1,
        scheduled_for=NOW + timedelta(hours=23),
        due_at=NOW,
        status=status,
        idempotency_key="occurrence-test",
        created_at=NOW,
    )


def _cadence_step(step_id: UUID, order: int) -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=step_id,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=VERSION_ID,
        step_order=order,
        channel=ContactChannel.EMAIL,
        delay_hours=24 * order,
        message_goal="Check whether the lead is still considering a move.",
        template_key=f"step-{order}",
        max_attempts=1,
        created_at=NOW,
    )


def _config() -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Paused Search",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(_cadence_step(STEP_ONE_ID, 1), _cadence_step(STEP_TWO_ID, 2)),
        created_at=NOW,
        published_at=NOW,
    )


def _campaign_repository(
    *,
    allow_assigned_agent_manual_enrollment: bool = True,
) -> FakeCampaignAdminRepository:
    repository = FakeCampaignAdminRepository()
    repository.campaigns[CAMPAIGN_ID] = CampaignAdminCampaign(
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        name="Paused Search",
        status=CampaignStatus.ACTIVE,
        active_version_id=VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )
    repository.versions[VERSION_ID] = CampaignAdminVersion(
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        allow_assigned_agent_manual_enrollment=allow_assigned_agent_manual_enrollment,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )
    return repository


class _RecordingExternalEventRepository(FakeExternalEventRepository):
    def __init__(self) -> None:
        self.events: list[ExternalEvent] = []

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.events.append(event)
        return event


class _Harness:
    def __init__(
        self,
        *,
        lead: CanonicalLeadRecord,
        workflow: LeadWorkflow,
        message: OutboundMessage,
        occurrence: RecurringOccurrence | None,
        allow_assigned_agent_manual_enrollment: bool = True,
        include_earlier_send: bool = True,
        campaign_execution_repository: FakeCampaignExecutionRepository | None = None,
        campaign_enrollment_repository: FakeCampaignEnrollmentRepository | None = None,
    ) -> None:
        self.campaign_execution_repository = campaign_execution_repository or (
            FakeCampaignExecutionRepository(_config())
        )
        self.campaign_enrollment_repository = campaign_enrollment_repository
        self.lead_repository = FakeLeadRepository(lead)
        self.workflow_repository = FakeLeadWorkflowRepository()
        self.workflow_repository.workflows[workflow.workflow_id] = workflow
        self.workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = workflow
        self.transition_repository = FakeWorkflowTransitionRepository()
        self.message_repository = FakeOutboundMessageRepository()
        self.message_repository.messages_by_idempotency_key[
            (message.workspace_id, message.idempotency_key)
        ] = message
        if include_earlier_send:
            earlier = _earlier_sent_message()
            self.message_repository.messages_by_idempotency_key[
                (earlier.workspace_id, earlier.idempotency_key)
            ] = earlier
        self.occurrence_repository = FakePausedSearchOccurrenceRepository(occurrence)
        self.signal_outbox_repository = FakeTemporalSignalOutboxRepository()
        self.external_event_repository = _RecordingExternalEventRepository()
        self.campaign_admin_repository = _campaign_repository(
            allow_assigned_agent_manual_enrollment=allow_assigned_agent_manual_enrollment
        )
        self.email_provider = FakeEmailProvider()
        self.sms_provider = FakeSMSProvider()
        self.commits = 0

    async def _commit(self) -> None:
        self.commits += 1

    async def run(
        self,
        *,
        role: WorkspaceMembershipRole = WorkspaceMembershipRole.BROKERAGE_ADMIN,
        reason: str = "Admin confirmed immediate send.",
    ) -> SendDeferredMessageNowResult:
        return await send_deferred_outbound_message_now(
            actor=_actor(role),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            message_id=MESSAGE_ID,
            reason=reason,
            lead_repository=self.lead_repository,
            lead_workflow_repository=self.workflow_repository,
            workflow_transition_repository=self.transition_repository,
            message_repository=self.message_repository,
            campaign_admin_repository=self.campaign_admin_repository,
            campaign_execution_repository=self.campaign_execution_repository,
            campaign_enrollment_repository=self.campaign_enrollment_repository,
            paused_search_occurrence_repository=self.occurrence_repository,
            workspace_repository=FakeWorkspaceRepository(
                Workspace(
                    workspace_id=WORKSPACE_ID,
                    name="Miller Schackman",
                    status=WorkspaceStatus.ACTIVE,
                    default_timezone="America/Chicago",
                    created_at=NOW,
                    updated_at=NOW,
                )
            ),
            workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
                WorkspaceContactPolicy(
                    workspace_id=WORKSPACE_ID,
                    quiet_hours_enabled=True,
                    quiet_hours_start=time(10, 0),
                    quiet_hours_end=time(17, 0),
                    inbound_email_address="reply@example.com",
                )
            ),
            workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(),
            external_event_repository=self.external_event_repository,
            temporal_signal_outbox_repository=self.signal_outbox_repository,
            crm_conversation_event_repository=FakeCrmConversationEventRepository(),
            commit=self._commit,
            sms_provider=self.sms_provider,
            email_provider=self.email_provider,
            now=NOW,
        )

    def stored_message(self) -> OutboundMessage:
        message = self.message_repository.messages_by_idempotency_key[
            (WORKSPACE_ID, f"outbound:test:{MESSAGE_ID}")
        ]
        return message



async def test_admin_send_now_sends_deferred_message_and_advances_paused_search() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.SENT
    assert result.outbound_message_id == MESSAGE_ID
    assert result.signal_queued is True
    assert harness.commits >= 1
    # Prior same-channel outreach does not block the retry — cadence owns spacing.
    assert len(harness.email_provider.messages) == 1

    sent_message = harness.stored_message()
    assert sent_message.status == OutboundMessageStatus.SENT
    assert sent_message.status_detail is None
    assert sent_message.sent_at == NOW

    occurrence = harness.occurrence_repository.occurrence
    assert occurrence is not None
    assert occurrence.status is RecurringOccurrenceStatus.SENT

    advanced = harness.workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert advanced.state == WorkflowState.WAITING_FOR_RESPONSE
    assert advanced.paused_search_track_step_id == STEP_TWO_ID

    assert any(
        transition.reason_code == WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT
        for transition in harness.transition_repository.transitions.values()
    )
    assert any(
        entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED
        for entry in harness.signal_outbox_repository.entries.values()
    )
    assert any(
        event.event_type == "lead.deferred_outbound_message_send_now_confirmed"
        for event in harness.external_event_repository.events
    )


async def test_admin_send_now_advances_dormant_workflow() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(paused_search=False),
        message=_deferred_message(),
        occurrence=None,
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.SENT
    assert len(harness.email_provider.messages) == 1
    advanced = harness.workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert advanced.state == WorkflowState.WAITING_FOR_RESPONSE
    assert advanced.current_step_id == STEP_TWO_ID


async def test_send_now_requires_reason() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(),
        occurrence=_occurrence(),
    )

    result = await harness.run(reason="   ")

    assert result.status == SendDeferredMessageNowStatus.REJECTED
    assert result.reasons == ("reason_required",)
    assert harness.email_provider.messages == []


async def test_send_now_rejected_for_unpermitted_agent() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(),
        occurrence=_occurrence(),
        allow_assigned_agent_manual_enrollment=False,
    )

    result = await harness.run(role=WorkspaceMembershipRole.ASSIGNED_AGENT)

    assert result.status == SendDeferredMessageNowStatus.REJECTED
    assert result.reasons == ("permission_denied",)
    assert harness.email_provider.messages == []


async def test_send_now_not_actionable_when_message_not_deferred() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(status_detail=None),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.NOT_ACTIONABLE
    assert result.reasons == ("message_not_deferred",)
    assert harness.email_provider.messages == []


async def test_send_now_not_actionable_when_message_not_pending() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(status=OutboundMessageStatus.CANCELLED),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.NOT_ACTIONABLE
    assert result.reasons == ("message_not_pending",)


async def test_send_now_not_actionable_when_workflow_not_active() -> None:
    # A lead back in human handoff must not be force-sent: the operator would
    # be overriding a human-in-control state, not just a timing guard.
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(state=WorkflowState.HUMAN_HANDOFF),
        message=_deferred_message(),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.NOT_ACTIONABLE
    assert result.reasons == ("workflow_not_active",)
    assert harness.email_provider.messages == []


async def test_send_now_not_actionable_on_step_mismatch() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(cadence_step_id=STEP_TWO_ID),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.NOT_ACTIONABLE
    assert result.reasons == ("step_mismatch",)


async def test_send_now_still_blocked_by_safety_guards() -> None:
    # do_not_contact keeps blocking the operator retry: consent and
    # contactability are never bypassed by a send-now action.
    harness = _Harness(
        lead=_lead(do_not_contact=True),
        workflow=_workflow(),
        message=_deferred_message(),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.SEND_REJECTED
    assert "channel_not_contactable" in result.reasons
    assert harness.email_provider.messages == []
    still_pending = harness.stored_message()
    assert still_pending.status == OutboundMessageStatus.PENDING
    assert still_pending.status_detail == DEFERRAL_DETAIL


async def test_send_now_is_idempotent_for_already_sent_message() -> None:
    harness = _Harness(
        lead=_lead(),
        workflow=_workflow(),
        message=_deferred_message(status=OutboundMessageStatus.SENT),
        occurrence=_occurrence(),
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.ALREADY_SENT
    assert harness.email_provider.messages == []


async def test_send_now_advances_via_pinned_version_after_republish() -> None:
    # A republish retires the enrolled version and regenerates every step id.
    # The deferred message must still send and the workflow must advance to
    # the pinned version's next step — not silently terminate because the
    # step id is absent from the newly active version.
    republished_version_id = UUID("00000000-0000-0000-0000-0000000000f0")
    republished_config = CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=republished_version_id,
        workspace_id=WORKSPACE_ID,
        campaign_name="Paused Search",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            _cadence_step(UUID("00000000-0000-0000-0000-0000000000f1"), 1),
            _cadence_step(UUID("00000000-0000-0000-0000-0000000000f2"), 2),
        ),
        created_at=NOW,
        published_at=NOW,
    )
    pinned_config = CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Paused Search",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.RETIRED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(_cadence_step(STEP_ONE_ID, 1), _cadence_step(STEP_TWO_ID, 2)),
        created_at=NOW,
        published_at=NOW,
    )
    workflow = _workflow(paused_search=False)
    enrollment_repository = FakeCampaignEnrollmentRepository()
    enrollment_repository.enrollments[(WORKSPACE_ID, LEAD_ID, CAMPAIGN_ID)] = CampaignEnrollment(
        campaign_enrollment_id=workflow.campaign_enrollment_id,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=VERSION_ID,
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        status=CampaignEnrollmentStatus.ACTIVE,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=NOW,
        ended_at=None,
        created_by_user_id=USER_ID,
        reason_codes=(),
        created_at=NOW,
        updated_at=NOW,
    )
    harness = _Harness(
        lead=_lead(),
        workflow=workflow,
        message=_deferred_message(),
        occurrence=None,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            (republished_config, pinned_config)
        ),
        campaign_enrollment_repository=enrollment_repository,
    )

    result = await harness.run()

    assert result.status == SendDeferredMessageNowStatus.SENT
    assert len(harness.email_provider.messages) == 1
    advanced = harness.workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert advanced.state == WorkflowState.WAITING_FOR_RESPONSE
    # The cursor advances to the pinned version's second step instead of
    # being cleared (silent cadence termination).
    assert advanced.current_step_id == STEP_TWO_ID

