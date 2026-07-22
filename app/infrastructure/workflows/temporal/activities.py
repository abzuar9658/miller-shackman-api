from collections.abc import Mapping
from datetime import datetime, timedelta

from temporalio import activity

from app.application.use_cases.campaign_cadence_execution import (
    CadenceStepExecutionResult,
    CadenceStepScheduleResult,
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.core.config import get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
    PostgresWorkspaceAgentMappingConfigRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_activity_repository import (
    PostgresLeadActivityRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingSnapshotRepository,
    PostgresListingSourceRepository,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageCRMCompletionRepository,
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.rejected_draft_review_repository import (
    PostgresRejectedDraftReviewRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.persistence.postgres.workspace_outbound_drafting_config_repository import (
    PostgresWorkspaceOutboundDraftingConfigRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_email_provider,
    build_listing_search_client,
    build_llm_client,
    build_sms_provider,
)
from app.infrastructure.workflows.temporal.lead_nurture import (
    ExecuteCadenceStepInput,
    ExecuteCadenceStepResult,
    ScheduleNextCadenceStepInput,
    ScheduleNextCadenceStepResult,
)


@activity.defn(name="schedule-next-campaign-cadence-step")
async def schedule_next_campaign_cadence_step_activity(
    input_: ScheduleNextCadenceStepInput,
) -> ScheduleNextCadenceStepResult:
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        outcome = await schedule_next_campaign_cadence_step(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
            campaign_version_id=input_.campaign_version_id,
            campaign_execution_repository=PostgresCampaignExecutionRepository(session),
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            now=input_.occurred_at,
        )
        await session.commit()
    return _schedule_outcome_to_result(outcome)


@activity.defn(name="execute-campaign-cadence-step")
async def execute_campaign_cadence_step_activity(
    input_: ExecuteCadenceStepInput,
) -> ExecuteCadenceStepResult:
    settings = get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        outcome = await execute_campaign_cadence_step(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
            campaign_version_id=input_.campaign_version_id,
            cadence_step_id=input_.cadence_step_id,
            scheduled_for=input_.scheduled_for,
            campaign_execution_repository=PostgresCampaignExecutionRepository(session),
            workspace_repository=PostgresWorkspaceRepository(session),
            workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
            workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
            workspace_outbound_drafting_config_repository=(
                PostgresWorkspaceOutboundDraftingConfigRepository(session)
            ),
            workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
                session
            ),
            lead_repository=PostgresLeadRepository(session),
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
            message_repository=PostgresOutboundMessageRepository(session),
            rejected_draft_review_repository=PostgresRejectedDraftReviewRepository(session),
            lead_activity_repository=PostgresLeadActivityRepository(session),
            crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
            listing_source_repository=PostgresListingSourceRepository(session),
            listing_snapshot_repository=PostgresListingSnapshotRepository(session),
            listing_search_client=build_listing_search_client(),
            listing_enrichment_enabled=settings.listing_context_enrichment_enabled,
            listing_cache_ttl=timedelta(
                minutes=settings.listing_context_enrichment_cache_ttl_minutes
            ),
            listing_max_results=settings.listing_context_enrichment_max_results,
            llm_client=build_llm_client(),
            sms_provider=build_sms_provider(),
            email_provider=build_email_provider(),
            crm_client=build_crm_client(settings),
            crm_agent_repository=PostgresCRMAgentRepository(session),
            workspace_agent_crm_mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(
                session,
            ),
            workspace_agent_mapping_config_repository=PostgresWorkspaceAgentMappingConfigRepository(
                session,
            ),
            workspace_membership_repository=PostgresWorkspaceMembershipRepository(session),
            user_repository=PostgresUserRepository(session),
            temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
            outbound_message_crm_completion_repository=(
                PostgresOutboundMessageCRMCompletionRepository(session)
            ),
            workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(
                session
            ),
            now=input_.occurred_at,
            default_openrouter_model=settings.openrouter_model,
        )
        await session.commit()
    return _execution_outcome_to_result(outcome)
def _reason_metadata(reason: str) -> Mapping[str, object]:
    return {"reason": reason}


def _signal_occurred_at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _schedule_outcome_to_result(
    outcome: CadenceStepScheduleResult,
) -> ScheduleNextCadenceStepResult:
    return ScheduleNextCadenceStepResult(
        status=outcome.status.value,
        workflow_id=outcome.workflow.workflow_id if outcome.workflow is not None else None,
        cadence_step_id=outcome.cadence_step_id,
        scheduled_for=outcome.scheduled_for,
        skip_reason=outcome.skip_reason,
    )


def _execution_outcome_to_result(
    outcome: CadenceStepExecutionResult,
) -> ExecuteCadenceStepResult:
    return ExecuteCadenceStepResult(
        status=outcome.status.value,
        workflow_id=outcome.workflow.workflow_id if outcome.workflow is not None else None,
        transition_id=outcome.transition_id,
        cadence_step_id=outcome.cadence_step_id,
        outbound_message_id=outcome.outbound_message_id,
        provider_message_id=outcome.provider_message_id,
        skip_reason=outcome.skip_reason,
        has_more_steps=outcome.has_more_steps,
    )
