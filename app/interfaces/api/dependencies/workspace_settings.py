from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.listing_search import ListingSearchClient
from app.application.ports.listing_sources import ListingSnapshotRepository, ListingSourceRepository
from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    CampaignAdminRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceCRMSyncConfigRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_admin_repository import (
    PostgresCampaignAdminRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingSnapshotRepository,
    PostgresListingSourceRepository,
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
from app.infrastructure.persistence.postgres.workspace_crm_sync_config_repository import (
    PostgresWorkspaceCRMSyncConfigRepository,
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
from app.infrastructure.providers import build_listing_search_client, build_llm_client


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class WorkspaceSettingsBundle:
    session: SessionCommitter
    workspace_repository: WorkspaceRepository
    membership_repository: WorkspaceMembershipRepository
    audit_log_repository: AuthAuditLogRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    workspace_crm_sync_config_repository: WorkspaceCRMSyncConfigRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    workspace_operational_control_repository: WorkspaceOperationalControlRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    default_crm_sync_interval_seconds: int
    default_openrouter_model: str
    allowed_openrouter_models: tuple[str, ...]
    allowed_bedrock_models: tuple[str, ...]
    bedrock_enabled: bool


@dataclass
class WorkspaceOutboundDraftingPreviewBundle:
    workspace_repository: WorkspaceRepository
    membership_repository: WorkspaceMembershipRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    listing_source_repository: ListingSourceRepository
    listing_snapshot_repository: ListingSnapshotRepository
    llm_client: LLMClient
    listing_search_client: ListingSearchClient
    listing_cache_ttl: timedelta
    default_openrouter_model: str
    campaign_admin_repository: CampaignAdminRepository


async def get_workspace_settings_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkspaceSettingsBundle:
    return WorkspaceSettingsBundle(
        session=session,
        workspace_repository=PostgresWorkspaceRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        audit_log_repository=PostgresAuthAuditLogRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workspace_crm_sync_config_repository=PostgresWorkspaceCRMSyncConfigRepository(session),
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        workspace_outbound_drafting_config_repository=PostgresWorkspaceOutboundDraftingConfigRepository(
            session
        ),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        default_crm_sync_interval_seconds=settings.crm_sync_incremental_interval_seconds,
        default_openrouter_model=settings.openrouter_model,
        allowed_openrouter_models=tuple(settings.openrouter_allowed_models),
        allowed_bedrock_models=tuple(settings.bedrock_allowed_models),
        bedrock_enabled=settings.bedrock_enabled,
    )


async def get_workspace_outbound_drafting_preview_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkspaceOutboundDraftingPreviewBundle:
    return WorkspaceOutboundDraftingPreviewBundle(
        workspace_repository=PostgresWorkspaceRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        workspace_outbound_drafting_config_repository=PostgresWorkspaceOutboundDraftingConfigRepository(
            session
        ),
        listing_source_repository=PostgresListingSourceRepository(session),
        listing_snapshot_repository=PostgresListingSnapshotRepository(session),
        llm_client=build_llm_client(settings),
        listing_search_client=build_listing_search_client(settings),
        listing_cache_ttl=timedelta(minutes=settings.listing_context_enrichment_cache_ttl_minutes),
        default_openrouter_model=settings.openrouter_model,
        campaign_admin_repository=PostgresCampaignAdminRepository(session),
    )
