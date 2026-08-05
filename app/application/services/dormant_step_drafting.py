from dataclasses import replace

from app.application.services.llm.outbound_message_drafting import ApprovedOutboundLeadContext
from app.domain.outbound_drafting import (
    DormantListingContextBehavior,
    DormantPersonalizationField,
    DormantStepTemplateProfile,
    WorkspaceOutboundDraftingConfig,
    apply_dormant_step_template_profile,
)


def apply_dormant_step_drafting_profile(
    *,
    drafting_config: WorkspaceOutboundDraftingConfig,
    lead_context: ApprovedOutboundLeadContext,
    template_profile: DormantStepTemplateProfile,
    channel: str,
) -> tuple[WorkspaceOutboundDraftingConfig, ApprovedOutboundLeadContext]:
    profiled_config = apply_dormant_step_template_profile(
        drafting_config,
        template_profile,
        channel=channel,
    )
    listing_context_enabled = (
        DormantPersonalizationField.APPROVED_LISTING_CONTEXT
        in template_profile.personalization_fields
        and template_profile.listing_context != DormantListingContextBehavior.NEVER
    )
    if listing_context_enabled:
        return profiled_config, lead_context
    return profiled_config, replace(lead_context, listing_context=None)