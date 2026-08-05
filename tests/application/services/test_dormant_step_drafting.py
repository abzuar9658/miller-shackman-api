from uuid import UUID

from app.application.services.dormant_step_drafting import (
    apply_dormant_step_drafting_profile,
)
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    ApprovedOutboundListingContext,
)
from app.domain.outbound_drafting import (
    DormantListingContextBehavior,
    DormantPersonalizationField,
    DormantStepTemplateProfile,
    WorkspaceOutboundDraftingConfig,
)

WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LISTING_CONTEXT = ApprovedOutboundListingContext(
    source_name="Brokerage feed",
    search_summary="2 approved matches",
    result_count=2,
)


def test_profile_removes_listing_context_when_admin_disables_it() -> None:
    _, lead_context = apply_dormant_step_drafting_profile(
        drafting_config=WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        lead_context=ApprovedOutboundLeadContext(listing_context=LISTING_CONTEXT),
        template_profile=DormantStepTemplateProfile(
            listing_context=DormantListingContextBehavior.NEVER
        ),
        channel="sms",
    )

    assert lead_context.listing_context is None


def test_profile_requires_listing_personalization_permission() -> None:
    _, lead_context = apply_dormant_step_drafting_profile(
        drafting_config=WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        lead_context=ApprovedOutboundLeadContext(listing_context=LISTING_CONTEXT),
        template_profile=DormantStepTemplateProfile(
            personalization_fields=(DormantPersonalizationField.LEAD_FIRST_NAME,)
        ),
        channel="email",
    )

    assert lead_context.listing_context is None