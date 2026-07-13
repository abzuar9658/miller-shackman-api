from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import (
    AuthAuditLogRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
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
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository


async def get_workspace_settings_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceSettingsBundle:
    return WorkspaceSettingsBundle(
        session=session,
        workspace_repository=PostgresWorkspaceRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        audit_log_repository=PostgresAuthAuditLogRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
    )
