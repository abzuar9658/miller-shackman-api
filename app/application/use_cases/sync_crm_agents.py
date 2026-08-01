from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.crm import CRMAgentDirectoryEntry, CRMAgentDirectorySource
from app.application.ports.repositories import (
    CRMAgentRepository,
    UserRepository,
    WorkspaceAgentCRMMappingRepository,
)
from app.domain.common.ids import WorkspaceId
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
)
from app.domain.identity import User, WorkspaceMembershipRole
from app.domain.leads import CRMProvider

_AUTO_MATCH_ROLES = (
    WorkspaceMembershipRole.BROKERAGE_ADMIN,
    WorkspaceMembershipRole.MANAGER,
    WorkspaceMembershipRole.ASSIGNED_AGENT,
)
_LOCKED_MAPPING_STATUSES = frozenset(
    {
        CRMAgentMappingStatus.VERIFIED,
        CRMAgentMappingStatus.OVERRIDDEN,
        CRMAgentMappingStatus.DISPUTED,
    }
)


class SyncCRMAgentsStatus(StrEnum):
    COMPLETED = "completed"


@dataclass(frozen=True)
class SyncCRMAgentsResult:
    status: SyncCRMAgentsStatus
    total_seen: int
    created_count: int
    updated_count: int
    deactivated_count: int
    suggested_mapping_count: int
    unmapped_mapping_count: int


async def sync_crm_agents_for_workspace(
    *,
    workspace_id: WorkspaceId,
    crm_agent_directory_source: CRMAgentDirectorySource,
    crm_agent_repository: CRMAgentRepository,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository,
    user_repository: UserRepository,
    now: datetime,
    crm_provider: CRMProvider = CRMProvider.FOLLOW_UP_BOSS,
    allowed_match_roles: tuple[WorkspaceMembershipRole, ...] = _AUTO_MATCH_ROLES,
    agent_record_id_factory: Callable[[], UUID] | None = None,
    mapping_id_factory: Callable[[], UUID] | None = None,
) -> SyncCRMAgentsResult:
    source_agents = _dedupe_source_agents(
        await crm_agent_directory_source.list_agents(workspace_id),
    )
    existing_agents = await crm_agent_repository.list_for_workspace(workspace_id)
    existing_mappings = await workspace_agent_crm_mapping_repository.list_for_workspace(
        workspace_id,
    )

    existing_agents_by_external_id = {
        agent.external_agent_id: agent
        for agent in existing_agents
        if agent.crm_provider == crm_provider
    }
    existing_mappings_by_agent_id = {
        mapping.crm_agent_record_id: mapping for mapping in existing_mappings
    }

    created_count = 0
    updated_count = 0
    deactivated_count = 0
    suggested_mapping_count = 0
    unmapped_mapping_count = 0
    seen_external_ids: set[str] = set()

    for source_agent in source_agents:
        external_agent_id = source_agent.crm_agent_id.strip()
        if not external_agent_id:
            continue
        seen_external_ids.add(external_agent_id)

        existing_agent = existing_agents_by_external_id.get(external_agent_id)
        stored_agent = _build_stored_agent(
            workspace_id=workspace_id,
            crm_provider=crm_provider,
            source_agent=source_agent,
            now=now,
            existing_agent=existing_agent,
            agent_record_id_factory=agent_record_id_factory,
        )
        saved_agent = await crm_agent_repository.save(stored_agent)
        if existing_agent is None:
            created_count += 1
        elif _agent_changed(existing_agent, stored_agent):
            updated_count += 1

        existing_mapping = existing_mappings_by_agent_id.get(saved_agent.agent_record_id)
        if _mapping_locked_for_admin(existing_mapping):
            continue

        match = await _find_workspace_user_match(
            workspace_id=workspace_id,
            email_normalized=saved_agent.email_normalized,
            user_repository=user_repository,
            allowed_match_roles=allowed_match_roles,
        )
        desired_status = (
            CRMAgentMappingStatus.SUGGESTED if match is not None else CRMAgentMappingStatus.UNMAPPED
        )
        desired_user_id = match.user_id if match is not None else None
        desired_resolved_at = now if match is not None else None

        if existing_mapping is None:
            saved_mapping = await workspace_agent_crm_mapping_repository.save(
                WorkspaceAgentCRMMapping(
                    mapping_id=(mapping_id_factory or uuid4)(),
                    workspace_id=workspace_id,
                    crm_agent_record_id=saved_agent.agent_record_id,
                    app_user_id=desired_user_id,
                    mapping_status=desired_status,
                    resolution_source=CRMAgentMappingResolutionSource.AUTO_EMAIL_MATCH,
                    resolved_by_user_id=None,
                    resolved_at=desired_resolved_at,
                    created_at=now,
                    updated_at=now,
                ),
            )
            existing_mappings_by_agent_id[saved_agent.agent_record_id] = saved_mapping
            if desired_status == CRMAgentMappingStatus.SUGGESTED:
                suggested_mapping_count += 1
            else:
                unmapped_mapping_count += 1
            continue

        if not _auto_mapping_changed(
            existing_mapping=existing_mapping,
            desired_user_id=desired_user_id,
            desired_status=desired_status,
            desired_resolved_at=desired_resolved_at,
        ):
            continue

        saved_mapping = await workspace_agent_crm_mapping_repository.save(
            replace(
                existing_mapping,
                app_user_id=desired_user_id,
                mapping_status=desired_status,
                resolution_source=CRMAgentMappingResolutionSource.AUTO_EMAIL_MATCH,
                resolved_by_user_id=None,
                resolved_at=desired_resolved_at,
                updated_at=now,
            ),
        )
        existing_mappings_by_agent_id[saved_agent.agent_record_id] = saved_mapping
        if desired_status == CRMAgentMappingStatus.SUGGESTED:
            suggested_mapping_count += 1
        else:
            unmapped_mapping_count += 1

    for existing_agent in existing_agents:
        if existing_agent.crm_provider != crm_provider:
            continue
        if existing_agent.external_agent_id in seen_external_ids or not existing_agent.is_active:
            continue
        await crm_agent_repository.save(
            replace(
                existing_agent,
                is_active=False,
                updated_at=now,
            ),
        )
        deactivated_count += 1

    return SyncCRMAgentsResult(
        status=SyncCRMAgentsStatus.COMPLETED,
        total_seen=len(seen_external_ids),
        created_count=created_count,
        updated_count=updated_count,
        deactivated_count=deactivated_count,
        suggested_mapping_count=suggested_mapping_count,
        unmapped_mapping_count=unmapped_mapping_count,
    )


def _dedupe_source_agents(
    source_agents: list[CRMAgentDirectoryEntry],
) -> tuple[CRMAgentDirectoryEntry, ...]:
    ordered: dict[str, CRMAgentDirectoryEntry] = {}
    for source_agent in source_agents:
        external_agent_id = source_agent.crm_agent_id.strip()
        if external_agent_id:
            ordered[external_agent_id] = source_agent
    return tuple(ordered.values())


def _build_stored_agent(
    *,
    workspace_id: WorkspaceId,
    crm_provider: CRMProvider,
    source_agent: CRMAgentDirectoryEntry,
    now: datetime,
    existing_agent: CRMAgent | None,
    agent_record_id_factory: Callable[[], UUID] | None,
) -> CRMAgent:
    normalized_email = _normalize_email(source_agent.email)
    agent_record_id = (
        existing_agent.agent_record_id
        if existing_agent is not None
        else (agent_record_id_factory or uuid4)()
    )
    return CRMAgent(
        agent_record_id=agent_record_id,
        workspace_id=workspace_id,
        crm_provider=crm_provider,
        external_agent_id=source_agent.crm_agent_id.strip(),
        name=_normalize_optional_text(source_agent.name),
        email=_normalize_optional_text(source_agent.email),
        email_normalized=normalized_email,
        phone=_normalize_optional_text(source_agent.phone),
        is_active=source_agent.is_active,
        last_seen_at=now,
        raw_payload=dict(source_agent.raw_payload),
        created_at=existing_agent.created_at if existing_agent is not None else now,
        updated_at=now,
    )


async def _find_workspace_user_match(
    *,
    workspace_id: WorkspaceId,
    email_normalized: str | None,
    user_repository: UserRepository,
    allowed_match_roles: tuple[WorkspaceMembershipRole, ...],
) -> User | None:
    if email_normalized is None:
        return None
    return await user_repository.get_active_by_workspace_email_normalized(
        workspace_id,
        email_normalized,
        allowed_roles=allowed_match_roles,
    )


def _mapping_locked_for_admin(mapping: WorkspaceAgentCRMMapping | None) -> bool:
    if mapping is None:
        return False
    if mapping.mapping_status in _LOCKED_MAPPING_STATUSES:
        return True
    return mapping.resolution_source == CRMAgentMappingResolutionSource.SYSTEM_UNLINKED


def _auto_mapping_changed(
    *,
    existing_mapping: WorkspaceAgentCRMMapping,
    desired_user_id: UUID | None,
    desired_status: CRMAgentMappingStatus,
    desired_resolved_at: datetime | None,
) -> bool:
    return (
        existing_mapping.app_user_id != desired_user_id
        or existing_mapping.mapping_status != desired_status
        or existing_mapping.resolution_source != CRMAgentMappingResolutionSource.AUTO_EMAIL_MATCH
        or existing_mapping.resolved_at != desired_resolved_at
        or existing_mapping.resolved_by_user_id is not None
    )


def _agent_changed(existing_agent: CRMAgent, candidate: CRMAgent) -> bool:
    return (
        existing_agent.name != candidate.name
        or existing_agent.email != candidate.email
        or existing_agent.email_normalized != candidate.email_normalized
        or existing_agent.phone != candidate.phone
        or existing_agent.is_active != candidate.is_active
        or existing_agent.last_seen_at != candidate.last_seen_at
        or dict(existing_agent.raw_payload) != dict(candidate.raw_payload)
    )


def _normalize_email(email_address: str | None) -> str | None:
    normalized = _normalize_optional_text(email_address)
    return normalized.lower() if normalized is not None else None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
