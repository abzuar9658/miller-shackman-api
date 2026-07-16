from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import (
    AuthAuditLogRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceCRMSyncConfigRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
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
    workspace_operational_control_repository: WorkspaceOperationalControlRepository
    default_crm_sync_interval_seconds: int
    default_openrouter_model: str
    allowed_openrouter_models: tuple[str, ...]


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
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        default_crm_sync_interval_seconds=settings.crm_sync_incremental_interval_seconds,
        default_openrouter_model=settings.openrouter_model,
        allowed_openrouter_models=tuple(settings.openrouter_allowed_models),
    )
