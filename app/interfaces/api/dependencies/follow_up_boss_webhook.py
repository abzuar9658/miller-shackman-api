from typing import Annotated

from fastapi import Depends

from app.application.ports.crm_webhook import (
    FollowUpBossWebhookEventBundle,
    FollowUpBossWebhookEventHandler,
)
from app.infrastructure.crm.follow_up_boss.webhook_event_handler import (
    FollowUpBossWebhookEventHandlerImpl,
)
from app.interfaces.api.dependencies.inbound import (
    InboundServiceBundle,
    get_inbound_service_bundle,
)


def get_follow_up_boss_webhook_event_handler(
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
) -> FollowUpBossWebhookEventHandler:
    return FollowUpBossWebhookEventHandlerImpl(
        bundle=FollowUpBossWebhookEventBundle(
            lead_repository=bundle.lead_repository,
            external_event_repository=bundle.external_event_repository,
            lead_workflow_repository=bundle.lead_workflow_repository,
            workflow_transition_repository=bundle.workflow_transition_repository,
            temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
            workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
            campaign_execution_repository=bundle.campaign_execution_repository,
            campaign_enrollment_repository=bundle.campaign_enrollment_repository,
            lead_classification_artifact_repository=bundle.lead_classification_artifact_repository,
            routing_review_repository=bundle.routing_review_repository,
            paused_search_track_repository=bundle.paused_search_track_repository,
            paused_search_track_assignment_repository=(
                bundle.paused_search_track_assignment_repository
            ),
            paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
            crm_conversation_event_repository=bundle.crm_conversation_event_repository,
            workspace_llm_config_repository=bundle.workspace_llm_config_repository,
            crm_client=bundle.crm_client,
            temporal_workflow_starter=bundle.temporal_workflow_starter,
            llm_client=bundle.llm_client,
            event_bus=bundle.event_bus,
            workspace_operational_control_repository=bundle.workspace_operational_control_repository,
            handoff_repository=bundle.handoff_repository,
            handoff_completion_repository=bundle.handoff_completion_repository,
            workspace_handoff_config_repository=bundle.workspace_handoff_config_repository,
            notification_provider=bundle.notification_provider,
            user_repository=bundle.user_repository,
            default_openrouter_model=bundle.default_openrouter_model,
            commit=bundle.session.commit,
        ),
    )
