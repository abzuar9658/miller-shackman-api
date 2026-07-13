from dataclasses import replace

from app.application.ports.event_bus import EventBus
from app.domain.campaigns.admin import (
    CampaignAdminAuditLog,
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, WorkspaceId
from app.domain.events import DomainEvent


class FakeCampaignAdminRepository:
    def __init__(self) -> None:
        self.campaigns: dict[CampaignId, CampaignAdminCampaign] = {}
        self.versions: dict[CampaignVersionId, CampaignAdminVersion] = {}
        self.steps: dict[CampaignVersionId, tuple[CampaignAdminCadenceStep, ...]] = {}
        self.retired_except: CampaignVersionId | None = None

    async def list_campaigns(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[CampaignAdminCampaign, ...]:
        campaigns = [
            campaign
            for campaign in self.campaigns.values()
            if campaign.workspace_id == workspace_id
        ]
        return tuple(
            sorted(
                campaigns, key=lambda campaign: (campaign.updated_at, campaign.name), reverse=True
            )
        )

    async def get_campaign(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignAdminCampaign | None:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None or campaign.workspace_id != workspace_id:
            return None
        return campaign

    async def get_campaign_by_name(
        self,
        workspace_id: WorkspaceId,
        name: str,
    ) -> CampaignAdminCampaign | None:
        return next(
            (
                campaign
                for campaign in self.campaigns.values()
                if campaign.workspace_id == workspace_id and campaign.name == name
            ),
            None,
        )

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
    ) -> CampaignAdminVersion | None:
        version = self.versions.get(campaign_version_id)
        if version is None or version.workspace_id != workspace_id:
            return None
        return version

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignAdminVersion | None:
        drafts = [
            version
            for version in self.versions.values()
            if version.workspace_id == workspace_id
            and version.campaign_id == campaign_id
            and version.status == CampaignVersionStatus.DRAFT
        ]
        return max(drafts, key=lambda version: version.version_number, default=None)

    async def get_latest_version(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignAdminVersion | None:
        versions = [
            version
            for version in self.versions.values()
            if version.workspace_id == workspace_id and version.campaign_id == campaign_id
        ]
        return max(versions, key=lambda version: version.version_number, default=None)

    async def get_latest_version_number(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> int:
        versions = [
            version.version_number
            for version in self.versions.values()
            if version.workspace_id == workspace_id and version.campaign_id == campaign_id
        ]
        return max(versions, default=0)

    async def get_cadence_steps(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
    ) -> tuple[CampaignAdminCadenceStep, ...]:
        return tuple(
            step
            for step in self.steps.get(campaign_version_id, ())
            if step.workspace_id == workspace_id
        )

    async def save_campaign(self, campaign: CampaignAdminCampaign) -> CampaignAdminCampaign:
        self.campaigns[campaign.campaign_id] = campaign
        return campaign

    async def save_version(self, version: CampaignAdminVersion) -> CampaignAdminVersion:
        self.versions[version.campaign_version_id] = version
        return version

    async def replace_cadence_steps(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
        steps: tuple[CampaignAdminCadenceStep, ...],
    ) -> tuple[CampaignAdminCadenceStep, ...]:
        saved = tuple(step for step in steps if step.workspace_id == workspace_id)
        self.steps[campaign_version_id] = saved
        return saved

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        except_version_id: CampaignVersionId,
    ) -> None:
        self.retired_except = except_version_id
        for version_id, version in tuple(self.versions.items()):
            if (
                version.workspace_id == workspace_id
                and version.campaign_id == campaign_id
                and version.campaign_version_id != except_version_id
                and version.status == CampaignVersionStatus.PUBLISHED
            ):
                self.versions[version_id] = replace(version, status=CampaignVersionStatus.RETIRED)


class FakeCampaignAdminAuditLogRepository:
    def __init__(self) -> None:
        self.logs: list[CampaignAdminAuditLog] = []

    async def append(self, audit_log: CampaignAdminAuditLog) -> CampaignAdminAuditLog:
        self.logs.append(audit_log)
        return audit_log


class FakeEventBus(EventBus):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)
