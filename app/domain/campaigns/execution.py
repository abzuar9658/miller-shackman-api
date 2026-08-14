from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.outbound_drafting import (
    DormantStepTemplateProfile,
    WorkspaceOutboundDraftingConfig,
)


class CampaignVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


@dataclass(frozen=True)
class CampaignCadenceStep:
    cadence_step_id: UUID
    workspace_id: WorkspaceId
    campaign_version_id: CampaignVersionId
    step_order: int
    channel: ContactChannel
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    created_at: datetime
    template_version_id: UUID | None = None
    template_profile: DormantStepTemplateProfile | None = None


@dataclass(frozen=True)
class CampaignExecutionConfig:
    campaign_id: CampaignId
    campaign_version_id: CampaignVersionId
    workspace_id: WorkspaceId
    campaign_name: str
    campaign_status: CampaignStatus
    version_status: CampaignVersionStatus
    enabled_channels: tuple[ContactChannel, ...]
    daily_start_cap: int
    dormant_threshold_days: int
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str
    preflight_digest_enabled: bool
    crm_enrollment_tag: str | None
    prompt_version: str
    approved_model: str
    cadence_steps: tuple[CampaignCadenceStep, ...]
    created_at: datetime
    published_at: datetime | None = None
    outbound_drafting_config: WorkspaceOutboundDraftingConfig | None = None
