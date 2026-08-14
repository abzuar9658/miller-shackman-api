"""Run an isolated paused-search lifecycle diagnostic.

This diagnostic never writes to Postgres, CRM, email, SMS, or Temporal. It uses
the real application use cases with in-memory repositories and provider fakes.

Usage:
    uv run python scripts/verify_paused_search_track.py
    uv run python scripts/verify_paused_search_track.py --mode live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

# Running a file under ``scripts/`` does not automatically put the project root
# on sys.path. Keep the diagnostic directly executable from the API directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.use_cases.campaign_cadence_execution import (
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.application.use_cases.lead_resume import resume_lead_workflow
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    process_crm_tag_campaign_enrollment,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    process_inbound_message_event,
)
from app.core.config import get_settings
from app.domain.campaigns import (
    CampaignStatus,
    CampaignVersionStatus,
    PausedSearchChannelSequence,
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchReplyPolicy,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.paused_search_tracks import PausedSearchStepAction
from app.domain.compliance import WorkspaceContactPolicy
from app.domain.compliance.contactability import ContactChannel, ContactPermissionStatus
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    Workspace,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider, LeadType
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config
from app.domain.workspace_automation import WorkspaceOperationalControl
from app.infrastructure.providers import build_llm_client
from tests.application.use_cases._campaign_admin_fakes import FakeEventBus
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
    FakeWorkspaceOperationalControlRepository,
    FakeWorkspaceOutboundDraftingConfigRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAssignmentRepository,
)
from tests.application.use_cases.paused_search_time_machine import (
    PausedSearchTimeMachineOccurrenceRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeConversationRepository,
    FakeConversationSummaryRepository,
    FakeExternalEventRepository,
    FakeHandoffRepository,
    FakeInboundMessageRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeLLMClient as FakeInboundLLMClient,
)

NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
INITIAL_REENGAGEMENT_DATE = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
REANCHORED_REENGAGEMENT_DATE = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("70000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("70000000-0000-0000-0000-000000000002")
TRACK_ID = UUID("0c2932da-c1a4-4e68-86d9-36fb62fab113")
TRACK_VERSION_ID = UUID("2e31c5d3-3b43-489e-861f-c41533f44310")
CAMPAIGN_ID = UUID("70000000-0000-0000-0000-000000000003")
CAMPAIGN_VERSION_ID = UUID("70000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("70000000-0000-0000-0000-000000000005")
EMAIL_STEP_ID = UUID("70000000-0000-0000-0000-000000000006")
SMS_STEP_ID = UUID("70000000-0000-0000-0000-000000000007")
REACTIVATION_STEP_ID = UUID("70000000-0000-0000-0000-000000000008")


class DiagnosticMode(StrEnum):
    STUB = "stub"
    LIVE = "live"


@dataclass
class DiagnosticRuntime:
    mode: DiagnosticMode
    now: datetime
    lead_repository: FakeLeadRepository
    workflow_repository: FakeLeadWorkflowRepository
    transitions: FakeWorkflowTransitionRepository
    track_repository: FakePausedSearchTrackAdminRepository
    occurrences: PausedSearchTimeMachineOccurrenceRepository
    email_provider: FakeEmailProvider
    sms_provider: FakeSMSProvider
    message_repository: FakeOutboundMessageRepository
    llm_client: LLMClient
    campaign_repository: FakeCampaignExecutionRepository
    contact_policy_repository: FakeWorkspaceContactPolicyRepository
    workspace_repository: FakeWorkspaceRepository
    operational_control_repository: FakeWorkspaceOperationalControlRepository
    artifact_repository: FakeLeadClassificationArtifactRepository
    crm_events: FakeCrmConversationEventRepository
    assignments: Any
    conversations: FakeConversationRepository
    inbound_messages: FakeInboundMessageRepository
    summaries: FakeConversationSummaryRepository
    external_events: FakeExternalEventRepository
    handoffs: FakeHandoffRepository


class LiveOrDiagnosticLLM:
    def __init__(self, mode: DiagnosticMode) -> None:
        self.mode = mode
        self.requests: list[LLMCompletionRequest] = []
        self.results: list[LLMResult] = []
        self._live = build_llm_client(get_settings()) if mode is DiagnosticMode.LIVE else None

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        if self._live is not None:
            result = await self._live.complete(request)
            self.results.append(result)
            return result
        if request.prompt_version.startswith("lead_state_classification"):
            date = (
                INITIAL_REENGAGEMENT_DATE
                if len(self.requests) == 1
                else REANCHORED_REENGAGEMENT_DATE
            )
            text = json.dumps(
                {
                    "outcome": "paused_search",
                    "confidence": 0.98,
                    "evidence": ["Lead explicitly asked to wait for rates to improve."],
                    "summary": "Lead wants to wait for rates before reconnecting.",
                    "selected_track_key": "waiting-for-rates",
                    "track_selection_status": "selected",
                    "reengagement_not_before": date.isoformat(),
                    "reengagement_window_label": "after rates improve",
                    "handoff_reason_code": None,
                }
            )
        elif request.prompt_version.startswith("inbound_reply_classification"):
            text = json.dumps(
                {
                    "intent": "general_reply",
                    "confidence": 0.97,
                    "asks_for_human": False,
                    "shows_buying_interest": False,
                    "shows_selling_interest": False,
                    "asks_property_or_advice": False,
                    "opt_out_detected": False,
                    "summary_text": "Lead confirms they still want to wait for rates.",
                    "preferences": {"timeline": "after rates improve"},
                }
            )
        else:
            text = json.dumps(
                {
                    "body": "Thanks for the update. We will check back at the right time.",
                    "subject": "A quick update",
                    "confidence": 0.98,
                    "personalization_notes": ["Synthetic paused-search diagnostic."],
                    "safety_flags": [],
                }
            )
        result = LLMResult(
            text=text,
            model="diagnostic/stub",
            prompt_version=request.prompt_version,
            latency_ms=1,
            usage_tokens=1,
        )
        self.results.append(result)
        return result


def build_runtime(mode: DiagnosticMode) -> DiagnosticRuntime:
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="synthetic-paused-search-lead",
        facts_derived_at=NOW,
        source_payload_version="diagnostic:v1",
        lead_type=LeadType.BUYER,
        primary_email="synthetic.lead@example.com",
        primary_phone="+15551234567",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        tags=("paused-search-diagnostic",),
    )
    track, version, steps = build_track()
    track_repository = FakePausedSearchTrackAdminRepository(
        tracks=(track,), versions=(version,), steps=steps
    )
    contact_policy = WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
    )
    campaign = CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Paused Search Diagnostic",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=contact_policy.quiet_hours_start,
        quiet_hours_end=contact_policy.quiet_hours_end,
        timezone="America/Chicago",
        preflight_digest_enabled=False,
        crm_enrollment_tag="paused-search-diagnostic",
        prompt_version="diagnostic",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(),
        created_at=NOW,
        published_at=NOW,
        outbound_drafting_config=default_workspace_outbound_drafting_config(WORKSPACE_ID),
    )
    initial_event = CrmConversationEvent(
        crm_conversation_event_id=UUID("70000000-0000-0000-0000-000000000009"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id="synthetic-initial-conversation",
        activity_type="Text message",
        direction=CrmConversationEventDirection.INBOUND,
        content="We still want to buy, but not until November 2026. Please check back then.",
        occurred_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    return DiagnosticRuntime(
        mode=mode,
        now=NOW,
        lead_repository=FakeLeadRepository(lead),
        workflow_repository=FakeLeadWorkflowRepository(),
        transitions=FakeWorkflowTransitionRepository(),
        track_repository=track_repository,
        occurrences=PausedSearchTimeMachineOccurrenceRepository(),
        email_provider=FakeEmailProvider("diagnostic-email"),
        sms_provider=FakeSMSProvider("diagnostic-sms"),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=LiveOrDiagnosticLLM(mode),
        campaign_repository=FakeCampaignExecutionRepository(campaign),
        contact_policy_repository=FakeWorkspaceContactPolicyRepository(contact_policy),
        workspace_repository=FakeWorkspaceRepository(
            Workspace(
                workspace_id=WORKSPACE_ID,
                name="Synthetic Diagnostic Brokerage",
                status=WorkspaceStatus.ACTIVE,
                default_timezone="America/Chicago",
                created_at=NOW,
                updated_at=NOW,
            )
        ),
        operational_control_repository=FakeWorkspaceOperationalControlRepository(
            WorkspaceOperationalControl(
                workspace_id=WORKSPACE_ID,
                recurring_paused_search_enabled=True,
            )
        ),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_events=FakeCrmConversationEventRepository((initial_event,)),
        assignments=FakePausedSearchTrackAssignmentRepository(),
        conversations=FakeConversationRepository(),
        inbound_messages=FakeInboundMessageRepository(),
        summaries=FakeConversationSummaryRepository(),
        external_events=FakeExternalEventRepository(),
        handoffs=FakeHandoffRepository(),
    )


def build_track() -> tuple[
    PausedSearchTrack, PausedSearchTrackVersion, tuple[PausedSearchTrackStep, ...]
]:
    version = PausedSearchTrackVersion(
        track_version_id=TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Select leads explicitly waiting for mortgage rates to improve.",
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=30,
        reactivation_window_days=1,
        max_total_touches=5,
        created_by_user_id=UUID("70000000-0000-0000-0000-000000000010"),
        created_at=NOW,
        published_at=NOW,
        default_pause_duration_days=60,
        max_duration_days=730,
        terminal_behavior=PausedSearchTerminalBehavior.CLOSE_AUTOMATION,
        track_mode=__import__(
            "app.domain.campaigns", fromlist=["PausedSearchTrackMode"]
        ).PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT,
        interim_contact_policy=PausedSearchInterimContactPolicy.ALLOWED_BY_PUBLISHED_TRACK,
        reply_policy=PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING,
        channel_sequence=PausedSearchChannelSequence.SEQUENTIAL,
        max_cycles=12,
        max_ai_interactions=5,
        restart_delay_days=30,
    )
    track = PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="waiting-for-rates",
        display_name="Waiting For Rates",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=TRACK_VERSION_ID,
        created_by_user_id=version.created_by_user_id,
        created_at=NOW,
        updated_at=NOW,
    )
    steps = (
        _step(
            EMAIL_STEP_ID,
            1,
            ContactChannel.EMAIL,
            "maintenance-email",
            0,
            30,
            2,
            PausedSearchTimingBasis.PREVIOUS_OCCURRENCE,
        ),
        _step(
            SMS_STEP_ID,
            2,
            ContactChannel.SMS,
            "maintenance-sms",
            0,
            30,
            2,
            PausedSearchTimingBasis.PREVIOUS_OCCURRENCE,
        ),
        _step(
            REACTIVATION_STEP_ID,
            3,
            ContactChannel.EMAIL,
            "reactivation-email",
            24,
            None,
            1,
            PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
            PausedSearchTrackStepPhase.REACTIVATION,
        ),
    )
    return track, version, steps


def _step(
    step_id: UUID,
    order: int,
    channel: ContactChannel,
    template: str,
    delay: int,
    interval: int | None,
    occurrences: int,
    basis: PausedSearchTimingBasis,
    phase: PausedSearchTrackStepPhase = PausedSearchTrackStepPhase.MAINTENANCE,
) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=step_id,
        workspace_id=WORKSPACE_ID,
        track_version_id=TRACK_VERSION_ID,
        step_order=order,
        phase=phase,
        channel=channel,
        delay_hours=delay,
        message_goal="Check whether the lead is ready to reconnect.",
        template_key=template,
        max_attempts=1,
        review_required=False,
        created_at=NOW,
        timing_basis=basis,
        interval_days=interval,
        max_occurrences=occurrences,
        action=PausedSearchStepAction.SEND,
    )


async def run_diagnostic(mode: DiagnosticMode) -> DiagnosticRuntime:
    runtime = build_runtime(mode)
    log("SETUP", runtime.now, "Synthetic lead and published track created; providers are fakes.")
    log("INPUT", runtime.now, runtime.crm_events.saved[0].content or "")

    enrollment = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=runtime.lead_repository.lead,
        observed_at=runtime.now,
        now=runtime.now,
        campaign_execution_repository=runtime.campaign_repository,
        workspace_contact_policy_repository=runtime.contact_policy_repository,
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        lead_workflow_repository=runtime.workflow_repository,
        workflow_transition_repository=runtime.transitions,
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        lead_repository=runtime.lead_repository,
        paused_search_history_repository=runtime.lead_repository,
        paused_search_track_repository=runtime.track_repository,
        paused_search_track_assignment_repository=runtime.assignments,
        artifact_repository=runtime.artifact_repository,
        crm_conversation_event_repository=runtime.crm_events,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=runtime.llm_client,
        event_bus=FakeEventBus(),
        workspace_operational_control_repository=runtime.operational_control_repository,
    )
    assert enrollment.route is not None
    classifier_result = runtime.llm_client.results[0]
    log(
        "CLASSIFIER",
        runtime.now,
        {
            "prompt_version": classifier_result.prompt_version,
            "model": classifier_result.model,
            "structured_output": classifier_result.text,
        },
    )
    log(
        "CLASSIFIED",
        runtime.now,
        {
            "status": enrollment.status.value,
            "route": enrollment.route.value,
            "track_version_id": str(enrollment.workflow_id) if enrollment.workflow_id else None,
            "reason_codes": enrollment.reason_codes,
        },
    )
    assert enrollment.route.value == "paused_search"
    if runtime.lead_repository.lead.reengagement_not_before is None:
        raise RuntimeError(
            "Classifier selected paused_search but did not provide a future reengagement date."
        )
    workflow = runtime.workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    log(
        "ENROLLED",
        runtime.now,
        {
            "workflow_id": str(workflow.workflow_id),
            "state": workflow.state.value,
            "track_version_id": str(workflow.paused_search_track_version_id),
        },
    )

    await execute_at(runtime, runtime.now, "initial email")
    await execute_at(runtime, runtime.now, "initial SMS immediately after email")
    sent_after_initial = len(runtime.email_provider.messages) + len(runtime.sms_provider.messages)
    await execute_at(runtime, NOW + timedelta(days=29), "one day before monthly boundary")
    assert (
        len(runtime.email_provider.messages) + len(runtime.sms_provider.messages)
        == sent_after_initial
    )
    monthly_time = NOW + timedelta(days=30)
    await execute_at(runtime, monthly_time, "monthly boundary email")
    await execute_at(runtime, monthly_time, "monthly SMS immediately after email")

    reply_time = NOW + timedelta(days=31)
    runtime.now = reply_time
    reply = InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id="synthetic-reply-event",
        provider_message_id="synthetic-reply-message",
        crm_lead_id="synthetic-paused-search-lead",
        channel=ContactChannel.EMAIL,
        body=(
            "Please update my timing: December 1, 2026—not November 2026—is the "
            "right time to reconnect."
        ),
        received_at=reply_time,
        payload_redacted={"diagnostic": True},
    )
    reply_result = await process_inbound_message_event(
        event=reply,
        lead_repository=runtime.lead_repository,
        external_event_repository=runtime.external_events,
        conversation_repository=runtime.conversations,
        inbound_message_repository=runtime.inbound_messages,
        crm_conversation_event_repository=runtime.crm_events,
        lead_classification_artifact_repository=runtime.artifact_repository,
        conversation_summary_repository=runtime.summaries,
        handoff_repository=runtime.handoffs,
        llm_client=(
            runtime.llm_client
            if mode is DiagnosticMode.LIVE
            else FakeInboundLLMClient(_reply_json(), _lead_state_json())
        ),
        now=reply_time,
        lead_workflow_repository=runtime.workflow_repository,
        workflow_transition_repository=runtime.transitions,
        paused_search_track_repository=runtime.track_repository,
        paused_search_track_assignment_repository=runtime.assignments,
        paused_search_occurrence_repository=runtime.occurrences,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        workspace_operational_control_repository=runtime.operational_control_repository,
    )
    if mode is DiagnosticMode.LIVE:
        for classifier_result in runtime.llm_client.results[1:]:
            log(
                "LLM",
                reply_time,
                {
                    "prompt_version": classifier_result.prompt_version,
                    "model": classifier_result.model,
                    "structured_output": classifier_result.text,
                },
            )
    log(
        "REPLY",
        reply_time,
        {
            "inbound_action": reply_result.inbound_action.value
            if reply_result.inbound_action
            else None,
            "paused_search_reply_decision": reply_result.paused_search_reply_decision.value
            if reply_result.paused_search_reply_decision
            else None,
            "continue_ai_provider_message_id": reply_result.continue_ai_provider_message_id,
        },
    )
    assert reply_result.paused_search_reply_decision is not None
    assert reply_result.paused_search_reply_decision.value == "reanchor"
    assert reply_result.continue_ai_provider_message_id is None
    log(
        "REANCHORED",
        runtime.lead_repository.lead.reengagement_not_before,
        {
            "track_key": runtime.lead_repository.lead.paused_search_track_key,
            "track_version_id": str(runtime.lead_repository.lead.paused_search_track_version_id),
        },
    )
    reactivation_date = runtime.lead_repository.lead.reengagement_not_before
    assert reactivation_date is not None
    assert reactivation_date.date() == REANCHORED_REENGAGEMENT_DATE.date(), (
        "same-track reply did not update the reengagement date to December 1, 2026"
    )
    await execute_at(runtime, reactivation_date - timedelta(days=2), "two days before reactivation")
    await execute_at(runtime, reactivation_date - timedelta(days=1), "one day before reactivation")
    assert (
        runtime.workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)].state.value == "paused"
    )
    assert len(runtime.email_provider.messages) + len(runtime.sms_provider.messages) == 4
    resume_time = reactivation_date - timedelta(days=1)
    resume = await resume_lead_workflow(
        actor=_admin_actor(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="Diagnostic: authorized resume after reviewing same-track reply.",
        lead_repository=runtime.lead_repository,
        workflow_repository=runtime.workflow_repository,
        lead_workflow_repository=runtime.workflow_repository,
        workspace_contact_policy_repository=runtime.contact_policy_repository,
        workflow_transition_repository=runtime.transitions,
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        external_event_repository=runtime.external_events,
        commit=_noop_commit,
        now=resume_time,
    )
    log(
        "RESUME",
        resume_time,
        {
            "status": resume.status.value,
            "workflow_state": resume.workflow_state.value if resume.workflow_state else None,
        },
    )
    assert resume.status.value == "requested"
    assert resume.workflow_state.value == "active_nurture"
    final_due = await execute_at(runtime, reactivation_date, "reactivation boundary")
    assert final_due is not None
    await execute_at(runtime, final_due - timedelta(minutes=1), "one minute before final due time")
    await execute_at(runtime, final_due, "reactivation step due after delay and quiet hours")
    await execute_at(runtime, final_due + timedelta(days=1), "after final touch")
    total_sends = len(runtime.email_provider.messages) + len(runtime.sms_provider.messages)
    assert total_sends == 5, f"expected five logical touches, got {total_sends}"
    log(
        "SUMMARY",
        final_due + timedelta(days=1),
        {
            "email_count": len(runtime.email_provider.messages),
            "sms_count": len(runtime.sms_provider.messages),
            "total_logical_touches": total_sends,
            "final_workflow_state": runtime.workflow_repository.latest_by_lead[
                (WORKSPACE_ID, LEAD_ID)
            ].state.value,
        },
    )
    return runtime


async def execute_at(runtime: DiagnosticRuntime, now: datetime, label: str) -> datetime | None:
    runtime.now = now
    schedule = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=runtime.campaign_repository,
        lead_workflow_repository=runtime.workflow_repository,
        lead_repository=runtime.lead_repository,
        paused_search_track_repository=runtime.track_repository,
        paused_search_occurrence_repository=runtime.occurrences,
        workflow_transition_repository=runtime.transitions,
        workspace_operational_control_repository=runtime.operational_control_repository,
        workspace_contact_policy_repository=runtime.contact_policy_repository,
        now=now,
    )
    log(
        "TIME",
        now,
        {
            "label": label,
            "status": schedule.status.value,
            "scheduled_for": schedule.scheduled_for,
            "step_id": str(schedule.cadence_step_id) if schedule.cadence_step_id else None,
            "reason": schedule.skip_reason,
        },
    )
    if schedule.scheduled_for is None or schedule.scheduled_for > now:
        return schedule.scheduled_for
    before_email = len(runtime.email_provider.messages)
    before_sms = len(runtime.sms_provider.messages)
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=schedule.cadence_step_id,
        scheduled_for=schedule.scheduled_for,
        campaign_execution_repository=runtime.campaign_repository,
        paused_search_track_repository=runtime.track_repository,
        paused_search_occurrence_repository=runtime.occurrences,
        workspace_repository=runtime.workspace_repository,
        workspace_contact_policy_repository=runtime.contact_policy_repository,
        workspace_operational_control_repository=runtime.operational_control_repository,
        workspace_outbound_drafting_config_repository=FakeWorkspaceOutboundDraftingConfigRepository(
            default_workspace_outbound_drafting_config(WORKSPACE_ID)
        ),
        lead_repository=runtime.lead_repository,
        lead_workflow_repository=runtime.workflow_repository,
        workflow_transition_repository=runtime.transitions,
        message_repository=runtime.message_repository,
        llm_client=(runtime.llm_client if runtime.mode is DiagnosticMode.LIVE else FakeLLMClient()),
        sms_provider=runtime.sms_provider,
        email_provider=runtime.email_provider,
        now=now,
    )
    log(
        "SEND",
        now,
        {
            "status": result.status.value,
            "provider_message_id": result.provider_message_id,
            "step_id": str(result.cadence_step_id) if result.cadence_step_id else None,
        },
    )
    for message in runtime.email_provider.messages[before_email:]:
        print(f"      EMAIL {json.dumps(message.model_dump(), default=str, sort_keys=True)}")
    for message in runtime.sms_provider.messages[before_sms:]:
        print(f"      SMS   {json.dumps(message.model_dump(), default=str, sort_keys=True)}")
    return schedule.scheduled_for


def _reply_json() -> str:
    return json.dumps(
        {
            "intent": "general_reply",
            "confidence": 0.97,
            "asks_for_human": False,
            "shows_buying_interest": False,
            "shows_selling_interest": False,
            "asks_property_or_advice": False,
            "opt_out_detected": False,
            "summary_text": "Lead confirms they still want to wait for rates.",
            "preferences": {"timeline": "after rates improve"},
        }
    )


def _lead_state_json() -> str:
    return json.dumps(
        {
            "outcome": "paused_search",
            "confidence": 0.98,
            "evidence": ["Lead explicitly asked to wait for rates to improve."],
            "summary": "Lead wants to wait for rates before reconnecting.",
            "selected_track_key": "waiting-for-rates",
            "track_selection_status": "selected",
            "reengagement_not_before": REANCHORED_REENGAGEMENT_DATE.isoformat(),
            "reengagement_window_label": "after rates improve",
            "handoff_reason_code": None,
        }
    )


def _admin_actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=UUID("70000000-0000-0000-0000-000000000010"),
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("70000000-0000-0000-0000-000000000011"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


async def _noop_commit() -> None:
    return None


def log(stage: str, timestamp: datetime | None, details: object) -> None:
    rendered_time = timestamp.isoformat() if isinstance(timestamp, datetime) else "n/a"
    print(f"[{stage:<10}] {rendered_time} | {json.dumps(details, default=str, sort_keys=True)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[mode.value for mode in DiagnosticMode], default="stub")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_diagnostic(DiagnosticMode(args.mode)))
    print("\nRESULT: isolated paused-search diagnostic completed successfully")


if __name__ == "__main__":
    main()
