from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.application.ports.crm_webhook import FollowUpBossWebhookEventBundle
from app.application.ports.repositories import LeadPausedSearchHistoryRepository
from app.application.use_cases.process_crm_human_activity_event import (
    CRMHumanActivityEvent,
    process_crm_human_activity_event,
)
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    CRMTagCampaignEnrollmentStatus,
    process_crm_tag_campaign_enrollment,
)
from app.domain.leads import CRMProvider, preserve_app_owned_lead_state
from app.infrastructure.crm.follow_up_boss.lead_mapper import (
    map_follow_up_boss_person_to_canonical_lead,
)
from app.infrastructure.crm.follow_up_boss.webhook_event_parsers import (
    extract_collection,
)

_PROVIDER = CRMProvider.FOLLOW_UP_BOSS.value


async def handle_people_event(
    workspace_id: UUID,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    uri: str,
    bundle: FollowUpBossWebhookEventBundle,
    now: datetime,
) -> tuple[int, int]:
    raw = await bundle.crm_client.fetch_resource_by_uri(workspace_id, uri)
    if raw is None:
        return 0, 1
    people = extract_collection(raw, "people")
    processed = 0
    ignored = 0
    for person in people:
        crm_lead_id = str(person.get("id", ""))
        if not crm_lead_id:
            ignored += 1
            continue
        existing = await bundle.lead_repository.get_by_crm_id(
            workspace_id, CRMProvider.FOLLOW_UP_BOSS, crm_lead_id
        )
        record = map_follow_up_boss_person_to_canonical_lead(
            workspace_id=workspace_id,
            payload=person,
            lead_id=existing.lead_id if existing else None,
            now=now,
        )
        saved = await bundle.lead_repository.upsert(
            preserve_app_owned_lead_state(record, existing)
        )
        person_processed = False
        activity = _people_activity_event(
            workspace_id, event_id, event_type, occurred_at, existing, saved
        )
        if activity is not None:
            await process_crm_human_activity_event(
                event=activity,
                lead_repository=bundle.lead_repository,
                external_event_repository=bundle.external_event_repository,
                lead_workflow_repository=bundle.lead_workflow_repository,
                workflow_transition_repository=bundle.workflow_transition_repository,
                temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
                now=now,
            )
            person_processed = True
        if event_type != "peopleDeleted":
            enrollment_result = await process_crm_tag_campaign_enrollment(
                workspace_id=workspace_id,
                lead=saved,
                observed_at=occurred_at,
                now=now,
                campaign_execution_repository=bundle.campaign_execution_repository,
                workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
                campaign_enrollment_repository=bundle.campaign_enrollment_repository,
                lead_workflow_repository=bundle.lead_workflow_repository,
                workflow_transition_repository=bundle.workflow_transition_repository,
                temporal_workflow_starter=bundle.temporal_workflow_starter,
                lead_repository=bundle.lead_repository,
                paused_search_history_repository=cast(
                    LeadPausedSearchHistoryRepository,
                    bundle.lead_repository,
                ),
                paused_search_track_repository=bundle.paused_search_track_repository,
                paused_search_track_assignment_repository=(
                    bundle.paused_search_track_assignment_repository
                ),
                artifact_repository=bundle.lead_classification_artifact_repository,
                crm_conversation_event_repository=bundle.crm_conversation_event_repository,
                workspace_llm_config_repository=bundle.workspace_llm_config_repository,
                llm_client=bundle.llm_client,
                event_bus=bundle.event_bus,
                workspace_operational_control_repository=bundle.workspace_operational_control_repository,
                handoff_repository=bundle.handoff_repository,
                handoff_completion_repository=bundle.handoff_completion_repository,
                workspace_handoff_config_repository=bundle.workspace_handoff_config_repository,
                crm_client=bundle.crm_client,
                notification_provider=bundle.notification_provider,
                user_repository=bundle.user_repository,
                commit=bundle.commit,
                rollback=bundle.rollback,
                default_openrouter_model=bundle.default_openrouter_model,
                routing_review_repository=bundle.routing_review_repository,
            )
            if enrollment_result.status != CRMTagCampaignEnrollmentStatus.NO_MATCHING_CAMPAIGN:
                person_processed = True
        if person_processed:
            processed += 1
        else:
            ignored += 1
    return processed, ignored


def _people_activity_event(
    workspace_id: UUID,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    previous: Any,
    current: Any,
) -> CRMHumanActivityEvent | None:
    if event_type in ("peopleCreated", "peopleDeleted"):
        return None
    if event_type == "peopleStageUpdated":
        return _human_activity(
            workspace_id,
            event_id,
            occurred_at,
            current.crm_lead_id,
            "stage_changed",
            None,
            "stage",
        )
    if event_type == "peopleTagsCreated":
        return _human_activity(
            workspace_id,
            event_id,
            occurred_at,
            current.crm_lead_id,
            "activity_created",
            "tags_changed",
            "tags",
        )
    changed_field = _detect_changed_field(previous, current)
    if changed_field == "assigned_agent":
        return _human_activity(
            workspace_id,
            event_id,
            occurred_at,
            current.crm_lead_id,
            "lead_reassigned",
            None,
            "assigned_agent",
        )
    if changed_field == "stage":
        return _human_activity(
            workspace_id,
            event_id,
            occurred_at,
            current.crm_lead_id,
            "stage_changed",
            None,
            "stage",
        )
    if changed_field == "contacted":
        return _human_activity(
            workspace_id,
            event_id,
            occurred_at,
            current.crm_lead_id,
            "status_changed",
            None,
            "contacted",
        )
    if changed_field == "tags":
        return _human_activity(
            workspace_id,
            event_id,
            occurred_at,
            current.crm_lead_id,
            "activity_created",
            "tags_changed",
            "tags",
        )
    return None


def _detect_changed_field(previous: Any, current: Any) -> str | None:
    if previous is None:
        return None
    if _contacted_count_increased(previous, current):
        return "contacted"
    if previous.lead_stage != current.lead_stage:
        return "stage"
    if previous.tags != current.tags:
        return "tags"
    if previous.assigned_agent_crm_id != current.assigned_agent_crm_id:
        return "assigned_agent"
    return None


def _contacted_count_increased(previous: Any, current: Any) -> bool:
    previous_count = previous.contacted_count or 0
    current_count = current.contacted_count or 0
    return current_count > previous_count


def _human_activity(
    workspace_id: UUID,
    event_id: str,
    occurred_at: datetime,
    crm_lead_id: str,
    event_type: str,
    activity_type: str | None,
    changed_field: str | None,
) -> CRMHumanActivityEvent:
    return CRMHumanActivityEvent(
        workspace_id=workspace_id,
        provider=_PROVIDER,
        provider_event_id=f"{event_id}:{crm_lead_id}",
        crm_lead_id=crm_lead_id,
        occurred_at=occurred_at,
        event_type=event_type,
        activity_type=activity_type,
        crm_activity_id=None,
        actor_agent_id=None,
        changed_field=changed_field,
        previous_value_redacted=None,
        new_value_redacted=None,
        payload_redacted={"fub_event_id": event_id},
    )
