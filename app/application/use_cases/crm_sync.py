from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID, uuid4

import structlog

from app.application.ports.crm import CRMActivity, CRMClient
from app.application.ports.crm_sync import CanonicalLeadSnapshotSource
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CRMAgentRepository,
    CrmConversationEventRepository,
    CRMSyncJobRepository,
    CRMSyncWindowStateRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceCRMSyncConfigRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.lead_assignment_resolution import (
    WorkspaceLeadAssignmentContext,
    apply_lead_assignment_resolution,
    load_workspace_lead_assignment_context,
)
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    process_crm_tag_campaign_enrollment,
)
from app.application.use_cases.reconcile_lead_assignment import (
    LeadAssignmentMessageRepository,
    reconcile_lead_assignment_change,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    CrmConversationTranscriptSegment,
)
from app.domain.crm_sync import (
    CRMSyncJob,
    CRMSyncJobStatus,
    CRMSyncLeadSort,
    CRMSyncType,
    CRMSyncWindowState,
)
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    preserve_app_owned_lead_state,
)
from app.domain.workspace_automation import WorkspaceAutomationStatus

logger = structlog.get_logger(__name__)


class RunFollowUpBossLeadSyncStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    LOST_LEASE = "lost_lease"


@dataclass(frozen=True)
class RunFollowUpBossLeadSyncResult:
    status: RunFollowUpBossLeadSyncStatus
    job: CRMSyncJob
    page_count: int
    next_cursor: str | None = None


class RequestCRMSyncStatus(StrEnum):
    REQUESTED = "requested"
    ALREADY_ACTIVE = "already_active"


@dataclass(frozen=True)
class RequestCRMSyncResult:
    status: RequestCRMSyncStatus
    job: CRMSyncJob


class ExecuteQueuedCRMSyncStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    LOST_LEASE = "lost_lease"
    NOT_CLAIMED = "not_claimed"


@dataclass(frozen=True)
class ExecuteQueuedCRMSyncResult:
    status: ExecuteQueuedCRMSyncStatus
    job: CRMSyncJob | None
    page_count: int = 0


@dataclass(frozen=True)
class EnqueueDueCRMSyncsResult:
    scanned_count: int
    requested_count: int
    skipped_disabled_count: int
    skipped_automation_blocked_count: int
    skipped_active_count: int
    skipped_not_due_count: int


class CRMActivitySource(Protocol):
    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        raise NotImplementedError


async def run_follow_up_boss_lead_snapshot_sync(
    *,
    workspace_id: WorkspaceId,
    lead_snapshot_source: CanonicalLeadSnapshotSource,
    lead_repository: LeadRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    now: datetime,
    sync_type: CRMSyncType = CRMSyncType.INCREMENTAL,
    page_size: int = 100,
    max_leads: int | None = None,
    latest_by: CRMSyncLeadSort | None = None,
    initial_cursor: str | None = None,
    created_by_user_id: UUID | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    mapped_custom_field_keys: tuple[str, ...] = (),
    sync_job_id_factory: Callable[[], UUID] | None = None,
    sync_job: CRMSyncJob | None = None,
    crm_activity_source: CRMActivitySource | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    campaign_execution_repository: CampaignExecutionRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    handoff_repository: HandoffRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    notification_provider: NotificationProvider | None = None,
    crm_agent_repository: CRMAgentRepository | None = None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None = None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None = None,
    workspace_membership_repository: WorkspaceMembershipRepository | None = None,
    user_repository: UserRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    outbound_message_repository: LeadAssignmentMessageRepository | None = None,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository | None = None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    llm_client: LLMClient | None = None,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    commit: Callable[[], Awaitable[None]] | None = None,
    activity_limit: int = 50,
    heartbeat_now_factory: Callable[[], datetime] | None = None,
    lease_lost_checker: Callable[[], bool] | None = None,
) -> RunFollowUpBossLeadSyncResult:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    max_leads, latest_by = _normalize_recent_limit(
        max_leads=max_leads,
        latest_by=latest_by,
    )
    heartbeat_now = heartbeat_now_factory or _default_heartbeat_now
    has_lost_lease = lease_lost_checker or _lease_not_lost

    cursor_started_at = await _resolve_cursor_started_at(
        workspace_id=workspace_id,
        crm_sync_job_repository=crm_sync_job_repository,
        sync_type=sync_type,
        updated_after=updated_after,
    )
    cursor_finished_at = updated_before or now
    initial_job = _running_sync_job(
        workspace_id=workspace_id,
        sync_type=sync_type,
        now=now,
        cursor_started_at=cursor_started_at,
        cursor_finished_at=cursor_finished_at,
        created_by_user_id=created_by_user_id,
        sync_job_id_factory=sync_job_id_factory,
        sync_job=sync_job,
    )
    job = await crm_sync_job_repository.save(initial_job) if sync_job is None else initial_job
    logger.info(
        "crm_sync_run_started",
        workspace_id=str(workspace_id),
        sync_job_id=str(job.sync_job_id),
        sync_type=sync_type.value,
        page_size=page_size,
        max_leads=max_leads,
        latest_by=latest_by.value if latest_by is not None else None,
        resume_cursor_present=initial_cursor is not None,
        cursor_started_at=(
            cursor_started_at.isoformat() if cursor_started_at is not None else None
        ),
        cursor_finished_at=cursor_finished_at.isoformat(),
    )

    next_cursor: str | None = initial_cursor
    remaining_leads = max_leads
    page_count = 0
    first_failure: str | None = None
    assignment_context = await _load_assignment_context(
        workspace_id=workspace_id,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
        workspace_membership_repository=workspace_membership_repository,
        user_repository=user_repository,
    )
    try:
        while True:
            if has_lost_lease():
                return await _lost_lease_result(
                    workspace_id=workspace_id,
                    crm_sync_job_repository=crm_sync_job_repository,
                    job=job,
                    sync_type=sync_type,
                    page_count=page_count,
                    phase="before_page_fetch",
                )
            request_page_size = page_size
            if remaining_leads is not None:
                if remaining_leads <= 0:
                    break
                request_page_size = min(page_size, remaining_leads)
            page = await lead_snapshot_source.list_lead_snapshots(
                workspace_id=workspace_id,
                page_size=request_page_size,
                cursor=next_cursor,
                updated_after=cursor_started_at,
                updated_before=cursor_finished_at,
                sort_by=latest_by,
                mapped_custom_field_keys=mapped_custom_field_keys,
            )
            page_next_cursor = page.next_cursor
            page_count += 1
            total_seen = job.total_seen + len(page.leads)
            total_upserted = job.total_upserted
            total_failed = job.total_failed
            for lead in page.leads:
                if has_lost_lease():
                    return await _lost_lease_result(
                        workspace_id=workspace_id,
                        crm_sync_job_repository=crm_sync_job_repository,
                        job=job,
                        sync_type=sync_type,
                        page_count=page_count,
                        phase="during_lead_processing",
                    )
                try:
                    existing_lead = await lead_repository.get_by_crm_id(
                        workspace_id,
                        lead.crm_provider,
                        lead.crm_lead_id,
                    )
                    resolved_lead = _resolve_lead_assignment(
                        preserve_app_owned_lead_state(lead, existing_lead),
                        assignment_context=assignment_context,
                        now=now,
                    )
                    upserted_lead = await lead_repository.upsert(resolved_lead)
                    await reconcile_lead_assignment_change(
                        previous_lead=existing_lead,
                        current_lead=upserted_lead,
                        lead_workflow_repository=lead_workflow_repository,
                        workflow_transition_repository=workflow_transition_repository,
                        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                        outbound_message_repository=outbound_message_repository,
                        event_bus=event_bus,
                        now=now,
                    )
                    total_upserted += 1
                    if (
                        crm_activity_source is not None
                        and crm_conversation_event_repository is not None
                    ):
                        await _sync_recent_crm_activity_for_lead(
                            workspace_id=workspace_id,
                            lead_id=upserted_lead.lead_id,
                            crm_provider=upserted_lead.crm_provider,
                            crm_lead_id=upserted_lead.crm_lead_id,
                            crm_activity_source=crm_activity_source,
                            crm_conversation_event_repository=crm_conversation_event_repository,
                            activity_limit=activity_limit,
                            now=now,
                        )
                    if _can_process_crm_tag_enrollment(
                        campaign_execution_repository=campaign_execution_repository,
                        workspace_contact_policy_repository=workspace_contact_policy_repository,
                        campaign_enrollment_repository=campaign_enrollment_repository,
                        lead_workflow_repository=lead_workflow_repository,
                        workflow_transition_repository=workflow_transition_repository,
                        temporal_workflow_starter=temporal_workflow_starter,
                        lead_repository=lead_repository,
                        paused_search_track_repository=paused_search_track_repository,
                        lead_classification_artifact_repository=lead_classification_artifact_repository,
                        crm_conversation_event_repository=crm_conversation_event_repository,
                        workspace_llm_config_repository=workspace_llm_config_repository,
                        llm_client=llm_client,
                    ):
                        assert campaign_execution_repository is not None
                        assert workspace_contact_policy_repository is not None
                        assert campaign_enrollment_repository is not None
                        assert lead_workflow_repository is not None
                        assert workflow_transition_repository is not None
                        assert temporal_workflow_starter is not None
                        assert lead_repository is not None
                        assert paused_search_track_repository is not None
                        assert lead_classification_artifact_repository is not None
                        assert crm_conversation_event_repository is not None
                        assert workspace_llm_config_repository is not None
                        assert llm_client is not None
                        await process_crm_tag_campaign_enrollment(
                            workspace_id=workspace_id,
                            lead=upserted_lead,
                            observed_at=_crm_tag_enrollment_observed_at(upserted_lead),
                            now=now,
                            campaign_execution_repository=campaign_execution_repository,
                            workspace_contact_policy_repository=workspace_contact_policy_repository,
                            campaign_enrollment_repository=campaign_enrollment_repository,
                            lead_workflow_repository=lead_workflow_repository,
                            workflow_transition_repository=workflow_transition_repository,
                            temporal_workflow_starter=temporal_workflow_starter,
                            lead_repository=lead_repository,
                            paused_search_history_repository=cast(
                                LeadPausedSearchHistoryRepository,
                                lead_repository,
                            ),
                            paused_search_track_repository=paused_search_track_repository,
                            artifact_repository=lead_classification_artifact_repository,
                            crm_conversation_event_repository=crm_conversation_event_repository,
                            workspace_llm_config_repository=workspace_llm_config_repository,
                            llm_client=llm_client,
                            event_bus=event_bus,
                            workspace_operational_control_repository=(
                                workspace_operational_control_repository
                            ),
                            handoff_repository=handoff_repository,
                            handoff_completion_repository=handoff_completion_repository,
                            workspace_handoff_config_repository=(
                                workspace_handoff_config_repository
                            ),
                            crm_client=cast(CRMClient, lead_snapshot_source),
                            notification_provider=notification_provider,
                            user_repository=user_repository,
                            commit=commit,
                            default_openrouter_model=default_openrouter_model,
                        )
                except Exception as exc:
                    total_failed += 1
                    if first_failure is None:
                        first_failure = str(exc) or exc.__class__.__name__
            page_updated_at = heartbeat_now()
            job = replace(
                job,
                total_seen=total_seen,
                total_upserted=total_upserted,
                total_failed=total_failed,
                last_heartbeat_at=page_updated_at,
                updated_at=page_updated_at,
            )
            # Persist progress and commit after every page so a long sync does
            # not hold lead row locks (blocking webhook updates) in one giant
            # transaction, and a crash loses at most one page of work.
            persisted_page_job = await crm_sync_job_repository.save_if_running(job)
            if persisted_page_job is None:
                return await _lost_lease_result(
                    workspace_id=workspace_id,
                    crm_sync_job_repository=crm_sync_job_repository,
                    job=job,
                    sync_type=sync_type,
                    page_count=page_count,
                    phase="page_progress_save",
                )
            job = persisted_page_job
            if commit is not None:
                await commit()
            logger.info(
                "crm_sync_page_processed",
                workspace_id=str(workspace_id),
                sync_job_id=str(job.sync_job_id),
                sync_type=sync_type.value,
                page_number=page_count,
                page_lead_count=len(page.leads),
                total_seen=job.total_seen,
                total_upserted=job.total_upserted,
                total_failed=job.total_failed,
                remaining_leads=remaining_leads,
                next_cursor_present=page_next_cursor is not None,
            )
            if remaining_leads is not None:
                remaining_leads -= len(page.leads)
            next_cursor = page_next_cursor
            if remaining_leads is not None and remaining_leads <= 0:
                break
            if page_next_cursor is None:
                break
    except Exception as exc:
        if has_lost_lease():
            return await _lost_lease_result(
                workspace_id=workspace_id,
                crm_sync_job_repository=crm_sync_job_repository,
                job=job,
                sync_type=sync_type,
                page_count=page_count,
                phase="exception_path",
            )
        logger.exception(
            "crm_sync_run_failed",
            workspace_id=str(workspace_id),
            sync_job_id=str(job.sync_job_id),
            sync_type=sync_type.value,
            page_count=page_count,
        )
        failed_at = heartbeat_now()
        failed_job = await crm_sync_job_repository.save_if_running(
            replace(
                job,
                status=CRMSyncJobStatus.FAILED,
                finished_at=failed_at,
                failure_reason=_page_failure_reason(exc),
                last_heartbeat_at=failed_at,
                updated_at=failed_at,
            ),
        )
        if failed_job is None:
            return await _lost_lease_result(
                workspace_id=workspace_id,
                crm_sync_job_repository=crm_sync_job_repository,
                job=job,
                sync_type=sync_type,
                page_count=page_count,
                phase="failed_finalize",
            )
        return RunFollowUpBossLeadSyncResult(
            status=RunFollowUpBossLeadSyncStatus.FAILED,
            job=failed_job,
            page_count=page_count,
        )

    final_status = (
        RunFollowUpBossLeadSyncStatus.PARTIAL
        if next_cursor is not None
        else (
            RunFollowUpBossLeadSyncStatus.COMPLETED
            if job.total_failed == 0
            else RunFollowUpBossLeadSyncStatus.FAILED
        )
    )
    if has_lost_lease():
        return await _lost_lease_result(
            workspace_id=workspace_id,
            crm_sync_job_repository=crm_sync_job_repository,
            job=job,
            sync_type=sync_type,
            page_count=page_count,
            phase="before_finalize",
        )
    finished_at = heartbeat_now()
    final_job = await crm_sync_job_repository.save_if_running(
        replace(
            job,
            status=(
                CRMSyncJobStatus.PARTIAL
                if final_status == RunFollowUpBossLeadSyncStatus.PARTIAL
                else (
                    CRMSyncJobStatus.COMPLETED
                    if final_status == RunFollowUpBossLeadSyncStatus.COMPLETED
                    else CRMSyncJobStatus.FAILED
                )
            ),
            finished_at=finished_at,
            failure_reason=_lead_failure_reason(job.total_failed, first_failure),
            last_heartbeat_at=finished_at,
            updated_at=finished_at,
        ),
    )
    if final_job is None:
        return await _lost_lease_result(
            workspace_id=workspace_id,
            crm_sync_job_repository=crm_sync_job_repository,
            job=job,
            sync_type=sync_type,
            page_count=page_count,
            phase="completed_finalize",
        )
    logger.info(
        "crm_sync_run_completed",
        workspace_id=str(workspace_id),
        sync_job_id=str(final_job.sync_job_id),
        status=final_status.value,
        sync_type=sync_type.value,
        page_count=page_count,
        total_seen=final_job.total_seen,
        total_upserted=final_job.total_upserted,
        total_failed=final_job.total_failed,
        next_cursor=next_cursor,
        cursor_started_at=(
            final_job.cursor_started_at.isoformat()
            if final_job.cursor_started_at is not None
            else None
        ),
        cursor_finished_at=(
            final_job.cursor_finished_at.isoformat()
            if final_job.cursor_finished_at is not None
            else None
        ),
        failure_reason=final_job.failure_reason,
    )
    return RunFollowUpBossLeadSyncResult(
        status=final_status,
        job=final_job,
        page_count=page_count,
        next_cursor=next_cursor,
    )


async def request_crm_sync(
    *,
    workspace_id: WorkspaceId,
    sync_type: CRMSyncType,
    max_leads: int | None = None,
    latest_by: CRMSyncLeadSort | None = None,
    resume_cursor: str | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    crm_sync_job_repository: CRMSyncJobRepository,
    event_bus: EventBus,
    now: datetime,
    created_by_user_id: UUID | None = None,
    sync_job_id_factory: Callable[[], UUID] | None = None,
) -> RequestCRMSyncResult:
    max_leads, latest_by = _normalize_recent_limit(
        max_leads=max_leads,
        latest_by=latest_by,
    )
    job = CRMSyncJob(
        sync_job_id=(sync_job_id_factory or uuid4)(),
        workspace_id=workspace_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        sync_type=sync_type,
        status=CRMSyncJobStatus.PENDING,
        started_at=None,
        finished_at=None,
        cursor_started_at=None,
        cursor_finished_at=None,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        last_heartbeat_at=None,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    inserted = await crm_sync_job_repository.insert_pending_if_no_active(job)
    if inserted is None:
        active = await crm_sync_job_repository.get_active_for_workspace_provider(
            workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if active is None:
            active = job
        logger.info(
            "crm_sync_request_skipped_active",
            workspace_id=str(workspace_id),
            requested_sync_type=sync_type.value,
            active_sync_job_id=str(active.sync_job_id),
            active_status=active.status.value,
            active_sync_type=active.sync_type.value,
            max_leads=max_leads,
            latest_by=latest_by.value if latest_by is not None else None,
            resume_cursor_present=resume_cursor is not None,
        )
        return RequestCRMSyncResult(status=RequestCRMSyncStatus.ALREADY_ACTIVE, job=active)

    await event_bus.publish(
        DomainEvent(
            workspace_id=workspace_id,
            aggregate_type=AggregateType.CRM_SYNC,
            aggregate_id=inserted.sync_job_id,
            event_type=DomainEventType.CRM_SYNC_REQUESTED,
            payload={
                "sync_job_id": str(inserted.sync_job_id),
                "crm_provider": inserted.crm_provider,
                "sync_type": inserted.sync_type.value,
                "max_leads": max_leads,
                "latest_by": latest_by.value if latest_by is not None else None,
                "resume_cursor": resume_cursor,
                "updated_after": updated_after.isoformat() if updated_after is not None else None,
                "updated_before": (
                    updated_before.isoformat() if updated_before is not None else None
                ),
            },
        ),
    )
    logger.info(
        "crm_sync_requested",
        workspace_id=str(workspace_id),
        sync_job_id=str(inserted.sync_job_id),
        sync_type=inserted.sync_type.value,
        max_leads=max_leads,
        latest_by=latest_by.value if latest_by is not None else None,
        resume_cursor_present=resume_cursor is not None,
        updated_after=updated_after.isoformat() if updated_after is not None else None,
        updated_before=updated_before.isoformat() if updated_before is not None else None,
    )
    return RequestCRMSyncResult(status=RequestCRMSyncStatus.REQUESTED, job=inserted)


async def execute_queued_follow_up_boss_crm_sync(
    *,
    workspace_id: WorkspaceId,
    sync_job_id: UUID,
    lead_snapshot_source: CanonicalLeadSnapshotSource,
    lead_repository: LeadRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    now: datetime,
    page_size: int = 100,
    max_leads: int | None = None,
    latest_by: CRMSyncLeadSort | None = None,
    resume_cursor: str | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    mapped_custom_field_keys: tuple[str, ...] = (),
    crm_activity_source: CRMActivitySource | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    crm_sync_window_state_repository: CRMSyncWindowStateRepository | None = None,
    campaign_execution_repository: CampaignExecutionRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    handoff_repository: HandoffRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    notification_provider: NotificationProvider | None = None,
    crm_agent_repository: CRMAgentRepository | None = None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None = None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None = None,
    workspace_membership_repository: WorkspaceMembershipRepository | None = None,
    user_repository: UserRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    outbound_message_repository: LeadAssignmentMessageRepository | None = None,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository | None = None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    llm_client: LLMClient | None = None,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    commit: Callable[[], Awaitable[None]] | None = None,
    activity_limit: int = 50,
    heartbeat_now_factory: Callable[[], datetime] | None = None,
    lease_lost_checker: Callable[[], bool] | None = None,
) -> ExecuteQueuedCRMSyncResult:
    claimed = await crm_sync_job_repository.claim_pending_by_id(
        workspace_id,
        sync_job_id,
        now=now,
    )
    if claimed is None:
        logger.info(
            "crm_sync_claim_not_acquired",
            workspace_id=str(workspace_id),
            sync_job_id=str(sync_job_id),
        )
        return ExecuteQueuedCRMSyncResult(status=ExecuteQueuedCRMSyncStatus.NOT_CLAIMED, job=None)

    if commit is not None:
        await commit()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=workspace_id,
        lead_snapshot_source=lead_snapshot_source,
        lead_repository=lead_repository,
        crm_sync_job_repository=crm_sync_job_repository,
        now=now,
        sync_type=claimed.sync_type,
        page_size=page_size,
        max_leads=max_leads,
        latest_by=latest_by,
        initial_cursor=resume_cursor,
        created_by_user_id=claimed.created_by_user_id,
        updated_after=updated_after,
        updated_before=updated_before,
        mapped_custom_field_keys=mapped_custom_field_keys,
        sync_job=claimed,
        crm_activity_source=crm_activity_source,
        crm_conversation_event_repository=crm_conversation_event_repository,
        campaign_execution_repository=campaign_execution_repository,
        workspace_contact_policy_repository=workspace_contact_policy_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=paused_search_track_repository,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        handoff_repository=handoff_repository,
        handoff_completion_repository=handoff_completion_repository,
        workspace_handoff_config_repository=workspace_handoff_config_repository,
        notification_provider=notification_provider,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
        workspace_membership_repository=workspace_membership_repository,
        user_repository=user_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        outbound_message_repository=outbound_message_repository,
        lead_classification_artifact_repository=lead_classification_artifact_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        default_openrouter_model=default_openrouter_model,
        commit=commit,
        activity_limit=activity_limit,
        heartbeat_now_factory=heartbeat_now_factory,
        lease_lost_checker=lease_lost_checker,
    )

    if crm_sync_window_state_repository is not None:
        if (
            result.status == RunFollowUpBossLeadSyncStatus.PARTIAL
            and result.next_cursor is not None
        ):
            await crm_sync_window_state_repository.save(
                CRMSyncWindowState(
                    workspace_id=workspace_id,
                    crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
                    sync_type=claimed.sync_type,
                    updated_after=result.job.cursor_started_at,
                    updated_before=result.job.cursor_finished_at or now,
                    next_cursor=result.next_cursor,
                    sort_by=latest_by,
                    created_at=now,
                    updated_at=now,
                )
            )
            logger.info(
                "crm_sync_window_state_saved",
                workspace_id=str(workspace_id),
                sync_job_id=str(claimed.sync_job_id),
                sync_type=claimed.sync_type.value,
                next_cursor=result.next_cursor,
                updated_after=(
                    result.job.cursor_started_at.isoformat()
                    if result.job.cursor_started_at is not None
                    else None
                ),
                updated_before=(
                    result.job.cursor_finished_at.isoformat()
                    if result.job.cursor_finished_at is not None
                    else None
                ),
                latest_by=latest_by.value if latest_by is not None else None,
            )
        elif result.status == RunFollowUpBossLeadSyncStatus.COMPLETED:
            await crm_sync_window_state_repository.delete(
                workspace_id,
                CRMProvider.FOLLOW_UP_BOSS.value,
            )
            logger.info(
                "crm_sync_window_state_cleared",
                workspace_id=str(workspace_id),
                sync_job_id=str(claimed.sync_job_id),
                sync_type=claimed.sync_type.value,
            )

    return ExecuteQueuedCRMSyncResult(
        status=ExecuteQueuedCRMSyncStatus(result.status.value),
        job=result.job,
        page_count=result.page_count,
    )


async def enqueue_due_follow_up_boss_crm_syncs(
    *,
    workspace_crm_sync_config_repository: WorkspaceCRMSyncConfigRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    crm_sync_window_state_repository: CRMSyncWindowStateRepository,
    event_bus: EventBus,
    now: datetime,
    default_interval_seconds: int,
    workspace_limit: int = 100,
) -> EnqueueDueCRMSyncsResult:
    schedule_targets = (
        await workspace_crm_sync_config_repository.list_active_workspace_schedule_targets(
            limit=workspace_limit,
            default_interval_seconds=default_interval_seconds,
        )
    )
    requested_count = 0
    skipped_disabled_count = 0
    skipped_automation_blocked_count = 0
    skipped_active_count = 0
    skipped_not_due_count = 0
    for target in schedule_targets:
        if not target.crm_sync_enabled:
            logger.info(
                "crm_sync_scheduler_decision",
                workspace_id=str(target.workspace_id),
                decision="disabled",
                interval_seconds=target.crm_sync_interval_seconds,
            )
            skipped_disabled_count += 1
            continue

        if target.automation_status != WorkspaceAutomationStatus.ACTIVE:
            logger.info(
                "crm_sync_scheduler_decision",
                workspace_id=str(target.workspace_id),
                decision="automation_blocked",
                automation_status=target.automation_status.value,
            )
            skipped_automation_blocked_count += 1
            continue

        active = await crm_sync_job_repository.get_active_for_workspace_provider(
            target.workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if active is not None:
            logger.info(
                "crm_sync_scheduler_decision",
                workspace_id=str(target.workspace_id),
                decision="active_job",
                active_sync_job_id=str(active.sync_job_id),
                active_status=active.status.value,
                active_sync_type=active.sync_type.value,
            )
            skipped_active_count += 1
            continue

        latest = await crm_sync_job_repository.get_latest_for_workspace_provider(
            target.workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if latest is not None and _latest_attempt_at(latest) > now - timedelta(
            seconds=target.crm_sync_interval_seconds,
        ):
            logger.info(
                "crm_sync_scheduler_decision",
                workspace_id=str(target.workspace_id),
                decision="not_due",
                latest_sync_job_id=(str(latest.sync_job_id) if latest is not None else None),
                latest_attempt_at=(
                    _latest_attempt_at(latest).isoformat() if latest is not None else None
                ),
                interval_seconds=target.crm_sync_interval_seconds,
            )
            skipped_not_due_count += 1
            continue

        window_state = await crm_sync_window_state_repository.get_by_workspace_provider(
            target.workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if window_state is not None:
            request = await request_crm_sync(
                workspace_id=target.workspace_id,
                sync_type=window_state.sync_type,
                max_leads=target.max_leads_per_sync_cycle,
                latest_by=window_state.sort_by,
                resume_cursor=window_state.next_cursor,
                updated_after=window_state.updated_after,
                updated_before=window_state.updated_before,
                crm_sync_job_repository=crm_sync_job_repository,
                event_bus=event_bus,
                now=now,
            )
            logger.info(
                "crm_sync_scheduler_decision",
                workspace_id=str(target.workspace_id),
                decision=(
                    "resume_window_requested"
                    if request.status == RequestCRMSyncStatus.REQUESTED
                    else "resume_window_already_active"
                ),
                sync_type=window_state.sync_type.value,
                max_leads=target.max_leads_per_sync_cycle,
                next_cursor=window_state.next_cursor,
            )
            if request.status == RequestCRMSyncStatus.REQUESTED:
                requested_count += 1
            continue

        latest_completed = (
            await crm_sync_job_repository.get_latest_completed_for_workspace_provider(
                target.workspace_id,
                CRMProvider.FOLLOW_UP_BOSS.value,
            )
        )
        sync_type = CRMSyncType.INCREMENTAL if latest_completed else CRMSyncType.FULL
        request = await request_crm_sync(
            workspace_id=target.workspace_id,
            sync_type=sync_type,
            max_leads=target.max_leads_per_sync_cycle,
            latest_by=(
                CRMSyncLeadSort.UPDATED if target.max_leads_per_sync_cycle is not None else None
            ),
            crm_sync_job_repository=crm_sync_job_repository,
            event_bus=event_bus,
            now=now,
        )
        logger.info(
            "crm_sync_scheduler_decision",
            workspace_id=str(target.workspace_id),
            decision=(
                "requested"
                if request.status == RequestCRMSyncStatus.REQUESTED
                else "already_active"
            ),
            sync_type=sync_type.value,
            max_leads=target.max_leads_per_sync_cycle,
            latest_completed_sync_job_id=(
                str(latest_completed.sync_job_id) if latest_completed is not None else None
            ),
        )
        if request.status == RequestCRMSyncStatus.REQUESTED:
            requested_count += 1

    return EnqueueDueCRMSyncsResult(
        scanned_count=len(schedule_targets),
        requested_count=requested_count,
        skipped_disabled_count=skipped_disabled_count,
        skipped_automation_blocked_count=skipped_automation_blocked_count,
        skipped_active_count=skipped_active_count,
        skipped_not_due_count=skipped_not_due_count,
    )


async def _resolve_cursor_started_at(
    *,
    workspace_id: WorkspaceId,
    crm_sync_job_repository: CRMSyncJobRepository,
    sync_type: CRMSyncType,
    updated_after: datetime | None,
) -> datetime | None:
    if updated_after is not None or sync_type == CRMSyncType.FULL:
        return updated_after
    recent_jobs = await crm_sync_job_repository.list_recent(workspace_id, limit=25)
    for job in recent_jobs:
        if job.crm_provider != CRMProvider.FOLLOW_UP_BOSS.value:
            continue
        if job.status != CRMSyncJobStatus.COMPLETED:
            continue
        return job.cursor_finished_at or job.finished_at
    return None


def _page_failure_reason(exc: Exception) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"sync page fetch failed: {detail}"


async def _sync_recent_crm_activity_for_lead(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    crm_provider: CRMProvider,
    crm_lead_id: str,
    crm_activity_source: CRMActivitySource,
    crm_conversation_event_repository: CrmConversationEventRepository,
    activity_limit: int,
    now: datetime,
) -> None:
    activities = await crm_activity_source.get_recent_activity(
        workspace_id=workspace_id,
        crm_lead_id=crm_lead_id,
        limit=activity_limit,
    )
    for activity in activities:
        event = _map_crm_activity_to_event(
            workspace_id=workspace_id,
            lead_id=lead_id,
            crm_provider=crm_provider,
            activity=activity,
            now=now,
        )
        await crm_conversation_event_repository.save(event)


def _map_crm_activity_to_event(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    crm_provider: CRMProvider,
    activity: CRMActivity,
    now: datetime,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        crm_provider=crm_provider.value,
        crm_activity_id=activity.crm_activity_id,
        activity_type=activity.activity_type,
        occurred_at=activity.timestamp,
        content=activity.content,
        actor_agent_id=activity.agent_id,
        actor_name=activity.actor_name,
        details=activity.details,
        transcript_segments=tuple(
            CrmConversationTranscriptSegment(
                text=segment.text,
                speaker_name=segment.speaker_name,
                speaker_role=segment.speaker_role,
                started_at=segment.started_at,
            )
            for segment in activity.transcript_segments
        ),
        direction=_crm_activity_direction(activity.direction),
        source_payload_version="follow_up_boss/v1",
        created_at=now,
        updated_at=now,
    )


def _crm_activity_direction(value: str | None) -> CrmConversationEventDirection | None:
    if value is None:
        return None
    try:
        return CrmConversationEventDirection(value)
    except ValueError:
        return None


def _can_process_crm_tag_enrollment(
    *,
    campaign_execution_repository: CampaignExecutionRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    temporal_workflow_starter: TemporalWorkflowStarter | None,
    lead_repository: LeadRepository | None,
    paused_search_track_repository: PausedSearchTrackRepository | None,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository | None,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    llm_client: LLMClient | None,
) -> bool:
    return all(
        dependency is not None
        for dependency in (
            campaign_execution_repository,
            workspace_contact_policy_repository,
            campaign_enrollment_repository,
            lead_workflow_repository,
            workflow_transition_repository,
            temporal_workflow_starter,
            lead_repository,
            paused_search_track_repository,
            lead_classification_artifact_repository,
            crm_conversation_event_repository,
            workspace_llm_config_repository,
            llm_client,
        )
    )


async def _load_assignment_context(
    *,
    workspace_id: WorkspaceId,
    crm_agent_repository: CRMAgentRepository | None,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository | None,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository | None,
    workspace_membership_repository: WorkspaceMembershipRepository | None,
    user_repository: UserRepository | None,
) -> WorkspaceLeadAssignmentContext | None:
    if not all(
        dependency is not None
        for dependency in (
            crm_agent_repository,
            workspace_agent_crm_mapping_repository,
            workspace_agent_mapping_config_repository,
            workspace_membership_repository,
            user_repository,
        )
    ):
        return None
    assert crm_agent_repository is not None
    assert workspace_agent_crm_mapping_repository is not None
    assert workspace_agent_mapping_config_repository is not None
    assert workspace_membership_repository is not None
    assert user_repository is not None
    return await load_workspace_lead_assignment_context(
        workspace_id=workspace_id,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
        workspace_agent_mapping_config_repository=workspace_agent_mapping_config_repository,
        workspace_membership_repository=workspace_membership_repository,
        user_repository=user_repository,
    )


def _resolve_lead_assignment(
    lead: CanonicalLeadRecord,
    *,
    assignment_context: WorkspaceLeadAssignmentContext | None,
    now: datetime,
) -> CanonicalLeadRecord:
    if assignment_context is None:
        return lead
    return apply_lead_assignment_resolution(
        lead,
        context=assignment_context,
        now=now,
    )


def _crm_tag_enrollment_observed_at(lead: CanonicalLeadRecord) -> datetime:
    return lead.source_updated_at or lead.crm_updated_at or lead.facts_derived_at


def _normalize_recent_limit(
    *,
    max_leads: int | None,
    latest_by: CRMSyncLeadSort | None,
) -> tuple[int | None, CRMSyncLeadSort | None]:
    if latest_by is not None and max_leads is None:
        raise ValueError("latest_by requires max_leads")
    if max_leads is None:
        return None, None
    if max_leads < 1:
        raise ValueError("max_leads must be greater than 0")
    return max_leads, latest_by or CRMSyncLeadSort.UPDATED


def _lead_failure_reason(total_failed: int, first_failure: str | None) -> str | None:
    if total_failed == 0:
        return None
    if first_failure:
        return f"{total_failed} lead(s) failed during sync; first failure: {first_failure}"
    return f"{total_failed} lead(s) failed during sync"


def _running_sync_job(
    *,
    workspace_id: WorkspaceId,
    sync_type: CRMSyncType,
    now: datetime,
    cursor_started_at: datetime | None,
    cursor_finished_at: datetime | None,
    created_by_user_id: UUID | None,
    sync_job_id_factory: Callable[[], UUID] | None,
    sync_job: CRMSyncJob | None,
) -> CRMSyncJob:
    if sync_job is None:
        return CRMSyncJob(
            sync_job_id=(sync_job_id_factory or uuid4)(),
            workspace_id=workspace_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
            sync_type=sync_type,
            status=CRMSyncJobStatus.RUNNING,
            started_at=now,
            finished_at=None,
            cursor_started_at=cursor_started_at,
            cursor_finished_at=cursor_finished_at,
            total_seen=0,
            total_upserted=0,
            total_failed=0,
            failure_reason=None,
            last_heartbeat_at=now,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
    return replace(
        sync_job,
        status=CRMSyncJobStatus.RUNNING,
        started_at=sync_job.started_at or now,
        finished_at=None,
        cursor_started_at=cursor_started_at,
        cursor_finished_at=cursor_finished_at,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        last_heartbeat_at=sync_job.last_heartbeat_at or now,
        updated_at=now,
    )


def _default_heartbeat_now() -> datetime:
    return datetime.now(UTC)


def _lease_not_lost() -> bool:
    return False


async def _lost_lease_result(
    *,
    workspace_id: WorkspaceId,
    crm_sync_job_repository: CRMSyncJobRepository,
    job: CRMSyncJob,
    sync_type: CRMSyncType,
    page_count: int,
    phase: str,
) -> RunFollowUpBossLeadSyncResult:
    persisted_job = await crm_sync_job_repository.get_by_id(workspace_id, job.sync_job_id) or job
    logger.info(
        "crm_sync_run_lease_lost",
        workspace_id=str(workspace_id),
        sync_job_id=str(job.sync_job_id),
        sync_type=sync_type.value,
        page_count=page_count,
        phase=phase,
    )
    return RunFollowUpBossLeadSyncResult(
        status=RunFollowUpBossLeadSyncStatus.LOST_LEASE,
        job=persisted_job,
        page_count=page_count,
    )


def _latest_attempt_at(job: CRMSyncJob) -> datetime:
    return job.finished_at or job.started_at or job.updated_at
