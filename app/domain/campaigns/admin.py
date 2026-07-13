from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, UserId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class CampaignAdminAuditAction(StrEnum):
    DRAFT_CREATED = "campaign_draft_created"
    DRAFT_UPDATED = "campaign_draft_updated"
    VERSION_PUBLISHED = "campaign_version_published"
    CAMPAIGN_PAUSED = "campaign_paused"
    BATCH_LAUNCHED = "campaign_batch_launched"


def _empty_details() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class CampaignAdminAuditLog:
    audit_log_id: UUID
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    action: CampaignAdminAuditAction
    actor_user_id: UserId
    created_at: datetime
    campaign_version_id: CampaignVersionId | None = None
    details: Mapping[str, object] = field(default_factory=_empty_details)


@dataclass(frozen=True)
class CampaignAdminCampaign:
    campaign_id: CampaignId
    workspace_id: WorkspaceId
    name: str
    status: CampaignStatus
    active_version_id: CampaignVersionId | None
    created_by_user_id: UserId
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CampaignAdminVersion:
    campaign_version_id: CampaignVersionId
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    version_number: int
    status: CampaignVersionStatus
    enabled_channels: tuple[ContactChannel, ...]
    daily_start_cap: int
    dormant_threshold_days: int
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str
    sms_compliance_required: bool
    preflight_digest_enabled: bool
    prompt_version: str
    approved_model: str
    created_by_user_id: UserId
    created_at: datetime
    published_at: datetime | None = None


@dataclass(frozen=True)
class CampaignAdminCadenceStep:
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


@dataclass(frozen=True)
class CampaignAdminView:
    campaign: CampaignAdminCampaign
    version: CampaignAdminVersion
    cadence_steps: tuple[CampaignAdminCadenceStep, ...]
