from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.crm import CRMAgentDirectorySource
from app.application.ports.repositories import (
    CRMAgentRepository,
    UserRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceMembershipRepository,
)
from app.application.use_cases.sync_crm_agents import (
    SyncCRMAgentsResult,
    sync_crm_agents_for_workspace,
)
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
)
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    User,
    UserStatus,
    WorkspaceMembershipStatus,
    evaluate_permission,
)


class CRMAgentMappingAdminStatus(StrEnum):
    OK = "ok"
    UPDATED = "updated"
    DELETED = "deleted"
    SYNCED = "synced"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class CRMAgentMappingAdminReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    WORKSPACE_CONTEXT_MISMATCH = "workspace_context_mismatch"
    CRM_AGENT_NOT_FOUND = "crm_agent_not_found"
    MAPPING_NOT_FOUND = "mapping_not_found"
    APP_USER_NOT_FOUND = "app_user_not_found"
    APP_USER_NOT_ACTIVE = "app_user_not_active"
    APP_USER_MEMBERSHIP_NOT_ACTIVE = "app_user_membership_not_active"


@dataclass(frozen=True)
class CRMAgentMappingAdminRow:
    agent: CRMAgent
    mapping: WorkspaceAgentCRMMapping | None
    app_user: User | None


@dataclass(frozen=True)
class CRMAgentMappingAdminSummary:
    total_agents: int
    active_agents: int
    inactive_agents: int
    verified_count: int
    suggested_count: int
    overridden_count: int
    disputed_count: int
    unmapped_count: int
    last_agent_seen_at: datetime | None


@dataclass(frozen=True)
class CRMAgentMappingAdminListResult:
    status: CRMAgentMappingAdminStatus
    rows: tuple[CRMAgentMappingAdminRow, ...] = ()
    summary: CRMAgentMappingAdminSummary | None = None
    reasons: tuple[CRMAgentMappingAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class CRMAgentMappingAdminMutationResult:
    status: CRMAgentMappingAdminStatus
    mapping: WorkspaceAgentCRMMapping | None = None
    reasons: tuple[CRMAgentMappingAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class CRMAgentDirectorySyncAdminResult:
    status: CRMAgentMappingAdminStatus
    sync_result: SyncCRMAgentsResult | None = None
    summary: CRMAgentMappingAdminSummary | None = None
    reasons: tuple[CRMAgentMappingAdminReasonCode, ...] = ()


async def list_crm_agent_mapping_admin_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    crm_agent_repository: CRMAgentRepository,
    mapping_repository: WorkspaceAgentCRMMappingRepository,
    user_repository: UserRepository,
) -> CRMAgentMappingAdminListResult:
    rejection = _management_rejection(actor, workspace_id)
    if rejection is not None:
        return CRMAgentMappingAdminListResult(
            status=CRMAgentMappingAdminStatus.REJECTED,
            reasons=(rejection,),
        )

    agents = await crm_agent_repository.list_for_workspace(workspace_id)
    mappings = await mapping_repository.list_for_workspace(workspace_id)
    mappings_by_agent_id = {mapping.crm_agent_record_id: mapping for mapping in mappings}
    rows: list[CRMAgentMappingAdminRow] = []
    for agent in agents:
        mapping = mappings_by_agent_id.get(agent.agent_record_id)
        app_user = (
            await user_repository.get_by_id(mapping.app_user_id)
            if mapping is not None and mapping.app_user_id is not None
            else None
        )
        rows.append(CRMAgentMappingAdminRow(agent=agent, mapping=mapping, app_user=app_user))
    return CRMAgentMappingAdminListResult(
        status=CRMAgentMappingAdminStatus.OK,
        rows=tuple(rows),
        summary=_summary(agents, mappings),
    )


async def upsert_crm_agent_mapping_by_admin(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    crm_agent_record_id: UUID,
    app_user_id: UUID,
    crm_agent_repository: CRMAgentRepository,
    mapping_repository: WorkspaceAgentCRMMappingRepository,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    now: datetime,
) -> CRMAgentMappingAdminMutationResult:
    rejection = _management_rejection(actor, workspace_id)
    if rejection is not None:
        return CRMAgentMappingAdminMutationResult(
            status=CRMAgentMappingAdminStatus.REJECTED,
            reasons=(rejection,),
        )

    agent = await crm_agent_repository.get_by_record_id(workspace_id, crm_agent_record_id)
    if agent is None:
        return CRMAgentMappingAdminMutationResult(
            status=CRMAgentMappingAdminStatus.NOT_FOUND,
            reasons=(CRMAgentMappingAdminReasonCode.CRM_AGENT_NOT_FOUND,),
        )
    app_user_rejection = await _validate_app_user(
        workspace_id=workspace_id,
        app_user_id=app_user_id,
        user_repository=user_repository,
        membership_repository=membership_repository,
    )
    if app_user_rejection is not None:
        return CRMAgentMappingAdminMutationResult(
            status=CRMAgentMappingAdminStatus.REJECTED,
            reasons=(app_user_rejection,),
        )

    existing = await mapping_repository.get_by_crm_agent_record_id(
        workspace_id,
        crm_agent_record_id,
    )
    status = _manual_status(existing, app_user_id)
    mapping = WorkspaceAgentCRMMapping(
        mapping_id=existing.mapping_id if existing is not None else uuid4(),
        workspace_id=workspace_id,
        crm_agent_record_id=crm_agent_record_id,
        app_user_id=app_user_id,
        mapping_status=status,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
        resolved_by_user_id=actor.user_id,
        resolved_at=now,
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
    )
    saved = await mapping_repository.save(mapping)
    return CRMAgentMappingAdminMutationResult(
        status=CRMAgentMappingAdminStatus.UPDATED,
        mapping=saved,
    )


async def unlink_crm_agent_mapping_by_admin(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    mapping_id: UUID,
    mapping_repository: WorkspaceAgentCRMMappingRepository,
    now: datetime,
) -> CRMAgentMappingAdminMutationResult:
    rejection = _management_rejection(actor, workspace_id)
    if rejection is not None:
        return CRMAgentMappingAdminMutationResult(
            status=CRMAgentMappingAdminStatus.REJECTED,
            reasons=(rejection,),
        )
    mapping = await mapping_repository.get_by_id(workspace_id, mapping_id)
    if mapping is None:
        return CRMAgentMappingAdminMutationResult(
            status=CRMAgentMappingAdminStatus.NOT_FOUND,
            reasons=(CRMAgentMappingAdminReasonCode.MAPPING_NOT_FOUND,),
        )
    saved = await mapping_repository.save(
        replace(
            mapping,
            app_user_id=None,
            mapping_status=CRMAgentMappingStatus.UNMAPPED,
            resolution_source=CRMAgentMappingResolutionSource.SYSTEM_UNLINKED,
            resolved_by_user_id=actor.user_id,
            resolved_at=now,
            updated_at=now,
        )
    )
    return CRMAgentMappingAdminMutationResult(
        status=CRMAgentMappingAdminStatus.DELETED,
        mapping=saved,
    )


async def sync_crm_agent_directory_by_admin(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    crm_agent_directory_source: CRMAgentDirectorySource,
    crm_agent_repository: CRMAgentRepository,
    mapping_repository: WorkspaceAgentCRMMappingRepository,
    user_repository: UserRepository,
    now: datetime,
) -> CRMAgentDirectorySyncAdminResult:
    rejection = _management_rejection(actor, workspace_id)
    if rejection is not None:
        return CRMAgentDirectorySyncAdminResult(
            status=CRMAgentMappingAdminStatus.REJECTED,
            reasons=(rejection,),
        )
    sync_result = await sync_crm_agents_for_workspace(
        workspace_id=workspace_id,
        crm_agent_directory_source=crm_agent_directory_source,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=mapping_repository,
        user_repository=user_repository,
        now=now,
    )
    agents = await crm_agent_repository.list_for_workspace(workspace_id)
    mappings = await mapping_repository.list_for_workspace(workspace_id)
    return CRMAgentDirectorySyncAdminResult(
        status=CRMAgentMappingAdminStatus.SYNCED,
        sync_result=sync_result,
        summary=_summary(agents, mappings),
    )


def _management_rejection(
    actor: AuthenticatedActor,
    workspace_id: UUID,
) -> CRMAgentMappingAdminReasonCode | None:
    if actor.active_workspace_id != workspace_id:
        return CRMAgentMappingAdminReasonCode.WORKSPACE_CONTEXT_MISMATCH
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_CRM_AGENT_MAPPINGS)
    if not permission.allowed:
        return CRMAgentMappingAdminReasonCode.PERMISSION_DENIED
    return None


async def _validate_app_user(
    *,
    workspace_id: UUID,
    app_user_id: UUID,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> CRMAgentMappingAdminReasonCode | None:
    user = await user_repository.get_by_id(app_user_id)
    if user is None:
        return CRMAgentMappingAdminReasonCode.APP_USER_NOT_FOUND
    if user.status != UserStatus.ACTIVE:
        return CRMAgentMappingAdminReasonCode.APP_USER_NOT_ACTIVE
    membership = await membership_repository.get_by_user_and_workspace(app_user_id, workspace_id)
    if membership is None or membership.status != WorkspaceMembershipStatus.ACTIVE:
        return CRMAgentMappingAdminReasonCode.APP_USER_MEMBERSHIP_NOT_ACTIVE
    return None


def _manual_status(
    existing: WorkspaceAgentCRMMapping | None,
    app_user_id: UUID,
) -> CRMAgentMappingStatus:
    if existing is None:
        return CRMAgentMappingStatus.VERIFIED
    if (
        existing.app_user_id == app_user_id
        and existing.mapping_status == CRMAgentMappingStatus.SUGGESTED
    ):
        return CRMAgentMappingStatus.VERIFIED
    if (
        existing.app_user_id == app_user_id
        and existing.mapping_status == CRMAgentMappingStatus.VERIFIED
    ):
        return CRMAgentMappingStatus.VERIFIED
    return CRMAgentMappingStatus.OVERRIDDEN


def _summary(
    agents: tuple[CRMAgent, ...],
    mappings: tuple[WorkspaceAgentCRMMapping, ...],
) -> CRMAgentMappingAdminSummary:
    mapped_statuses = [mapping.mapping_status for mapping in mappings]
    mapped_agent_ids = {mapping.crm_agent_record_id for mapping in mappings}
    unmapped_agent_count = len(
        [agent for agent in agents if agent.agent_record_id not in mapped_agent_ids]
    )
    explicit_unmapped = mapped_statuses.count(CRMAgentMappingStatus.UNMAPPED)
    seen_times = tuple(agent.last_seen_at for agent in agents if agent.last_seen_at is not None)
    return CRMAgentMappingAdminSummary(
        total_agents=len(agents),
        active_agents=len([agent for agent in agents if agent.is_active]),
        inactive_agents=len([agent for agent in agents if not agent.is_active]),
        verified_count=mapped_statuses.count(CRMAgentMappingStatus.VERIFIED),
        suggested_count=mapped_statuses.count(CRMAgentMappingStatus.SUGGESTED),
        overridden_count=mapped_statuses.count(CRMAgentMappingStatus.OVERRIDDEN),
        disputed_count=mapped_statuses.count(CRMAgentMappingStatus.DISPUTED),
        unmapped_count=explicit_unmapped + unmapped_agent_count,
        last_agent_seen_at=max(seen_times) if seen_times else None,
    )