"""Resolution of the campaign version an in-flight workflow is bound to.

Publishing a campaign version regenerates every cadence step id and retires the
previous version, so any code that reads campaign configuration on behalf of an
already-enrolled lead must read the version that lead was enrolled on. Reading
the campaign's currently active version instead makes a republish reject
in-flight sends (the pinned step id is absent from the new version) and silently
redraft mid-track conversations from the first step.

The enrollment row is the pin: `lead_workflows.campaign_enrollment_id` points at
the enrollment whose `campaign_version_id` was active when the lead entered the
track, and neither the version nor its steps are ever mutated afterwards.
"""

from typing import cast
from uuid import UUID

from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
)
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.workflows import LeadWorkflow


async def resolve_pinned_campaign_config(
    *,
    workspace_id: WorkspaceId,
    workflow: LeadWorkflow,
    campaign_execution_repository: CampaignExecutionRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
) -> CampaignExecutionConfig | None:
    """Return the campaign config the workflow is pinned to.

    Falls back to the campaign's active version only when the enrollment or its
    pinned version cannot be read, so callers without an enrollment repository
    keep their previous behaviour rather than losing configuration entirely.
    """
    pinned = await _config_for_enrollment(
        workspace_id=workspace_id,
        campaign_enrollment_id=workflow.campaign_enrollment_id,
        campaign_execution_repository=campaign_execution_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
    )
    if pinned is not None:
        return pinned
    fallback = await campaign_execution_repository.get_active_for_campaign(
        workspace_id,
        workflow.campaign_id,
    )
    return cast("CampaignExecutionConfig | None", fallback)


async def _config_for_enrollment(
    *,
    workspace_id: WorkspaceId,
    campaign_enrollment_id: UUID,
    campaign_execution_repository: CampaignExecutionRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
) -> CampaignExecutionConfig | None:
    if campaign_enrollment_repository is None:
        return None
    enrollment = await campaign_enrollment_repository.get_by_id(
        workspace_id,
        campaign_enrollment_id,
    )
    pinned_version_id: UUID | None = getattr(enrollment, "campaign_version_id", None)
    if pinned_version_id is None:
        return None
    config = await campaign_execution_repository.get_by_version_id(
        workspace_id,
        pinned_version_id,
    )
    return cast("CampaignExecutionConfig | None", config)


async def resolve_pinned_campaign_config_for_campaign(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    workflow: LeadWorkflow | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
) -> CampaignExecutionConfig | None:
    """Pinned-version variant for callers whose workflow may be absent.

    Without a workflow there is no enrollment to pin to, so the campaign's
    active version is the only available answer.
    """
    if campaign_execution_repository is None:
        return None
    if workflow is None:
        fallback = await campaign_execution_repository.get_active_for_campaign(
            workspace_id,
            campaign_id,
        )
        return cast("CampaignExecutionConfig | None", fallback)
    return await resolve_pinned_campaign_config(
        workspace_id=workspace_id,
        workflow=workflow,
        campaign_execution_repository=campaign_execution_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
    )
