from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import CRMAgentRecordId, WorkspaceAgentCRMMappingId, WorkspaceId
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
    WorkspaceAgentMappingConfig,
)
from app.domain.leads import CRMProvider
from app.infrastructure.persistence.postgres.models import (
    CRMAgentModel,
    WorkspaceAgentCRMMappingModel,
    WorkspaceAgentMappingConfigModel,
)


class PostgresCRMAgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_record_id(
        self,
        workspace_id: WorkspaceId,
        agent_record_id: CRMAgentRecordId,
    ) -> CRMAgent | None:
        result = await self._session.execute(
            select(CRMAgentModel).where(
                CRMAgentModel.workspace_id == workspace_id,
                CRMAgentModel.id == agent_record_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _agent_from_model(model) if model is not None else None

    async def get_by_external_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        result = await self._session.execute(
            select(CRMAgentModel).where(
                CRMAgentModel.workspace_id == workspace_id,
                CRMAgentModel.crm_provider == crm_provider.value,
                CRMAgentModel.crm_agent_id == external_agent_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _agent_from_model(model) if model is not None else None

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[CRMAgent, ...]:
        result = await self._session.execute(
            select(CRMAgentModel)
            .where(CRMAgentModel.workspace_id == workspace_id)
            .order_by(CRMAgentModel.name.asc(), CRMAgentModel.crm_agent_id.asc()),
        )
        return _agent_models_to_domain(result.scalars().all())

    async def save(self, agent: CRMAgent) -> CRMAgent:
        values = _agent_to_values(agent)
        result = await self._session.execute(
            insert(CRMAgentModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "crm_provider", "crm_agent_id"],
                set_=_agent_update_values(agent),
            )
            .returning(CRMAgentModel)
        )
        return _agent_from_model(result.scalar_one())


class PostgresWorkspaceAgentCRMMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        mapping_id: WorkspaceAgentCRMMappingId,
    ) -> WorkspaceAgentCRMMapping | None:
        result = await self._session.execute(
            select(WorkspaceAgentCRMMappingModel).where(
                WorkspaceAgentCRMMappingModel.workspace_id == workspace_id,
                WorkspaceAgentCRMMappingModel.mapping_id == mapping_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _mapping_from_model(model) if model is not None else None

    async def get_by_crm_agent_record_id(
        self,
        workspace_id: WorkspaceId,
        crm_agent_record_id: CRMAgentRecordId,
    ) -> WorkspaceAgentCRMMapping | None:
        result = await self._session.execute(
            select(WorkspaceAgentCRMMappingModel).where(
                WorkspaceAgentCRMMappingModel.workspace_id == workspace_id,
                WorkspaceAgentCRMMappingModel.crm_agent_id == crm_agent_record_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _mapping_from_model(model) if model is not None else None

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[WorkspaceAgentCRMMapping, ...]:
        result = await self._session.execute(
            select(WorkspaceAgentCRMMappingModel)
            .where(WorkspaceAgentCRMMappingModel.workspace_id == workspace_id)
            .order_by(
                WorkspaceAgentCRMMappingModel.created_at.asc(),
                WorkspaceAgentCRMMappingModel.mapping_id.asc(),
            ),
        )
        return _mapping_models_to_domain(result.scalars().all())

    async def save(self, mapping: WorkspaceAgentCRMMapping) -> WorkspaceAgentCRMMapping:
        result = await self._session.execute(
            insert(WorkspaceAgentCRMMappingModel)
            .values(**_mapping_to_values(mapping))
            .on_conflict_do_update(
                index_elements=["workspace_id", "crm_agent_id"],
                set_=_mapping_update_values(mapping),
            )
            .returning(WorkspaceAgentCRMMappingModel)
        )
        return _mapping_from_model(result.scalar_one())


class PostgresWorkspaceAgentMappingConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceAgentMappingConfig | None:
        result = await self._session.execute(
            select(WorkspaceAgentMappingConfigModel).where(
                WorkspaceAgentMappingConfigModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _config_from_model(model) if model is not None else None

    async def save(self, config: WorkspaceAgentMappingConfig) -> WorkspaceAgentMappingConfig:
        result = await self._session.execute(
            insert(WorkspaceAgentMappingConfigModel)
            .values(**_config_to_values(config))
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_={
                    "unmapped_assignment_fallback_user_id": (
                        config.unmapped_assignment_fallback_user_id
                    ),
                    "updated_at": config.updated_at,
                },
            )
            .returning(WorkspaceAgentMappingConfigModel)
        )
        return _config_from_model(result.scalar_one())


def _agent_from_model(model: CRMAgentModel) -> CRMAgent:
    return CRMAgent(
        agent_record_id=model.id,
        workspace_id=model.workspace_id,
        crm_provider=CRMProvider(model.crm_provider),
        external_agent_id=model.crm_agent_id,
        name=model.name,
        email=model.email,
        email_normalized=model.email_normalized,
        phone=model.phone,
        is_active=model.is_active,
        last_seen_at=model.last_seen_at,
        raw_payload=dict(model.raw_payload),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _agent_models_to_domain(models: Sequence[CRMAgentModel]) -> tuple[CRMAgent, ...]:
    return tuple(_agent_from_model(model) for model in models)


def _agent_to_values(agent: CRMAgent) -> dict[str, object]:
    return {
        "id": agent.agent_record_id,
        "workspace_id": agent.workspace_id,
        "crm_provider": agent.crm_provider.value,
        "crm_agent_id": agent.external_agent_id,
        "name": agent.name,
        "email": agent.email,
        "email_normalized": agent.email_normalized,
        "phone": agent.phone,
        "is_active": agent.is_active,
        "last_seen_at": agent.last_seen_at,
        "raw_payload": dict(agent.raw_payload),
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }


def _agent_update_values(agent: CRMAgent) -> dict[str, object]:
    values = _agent_to_values(agent)
    return {key: value for key, value in values.items() if key not in {"id", "created_at"}}


def _mapping_from_model(model: WorkspaceAgentCRMMappingModel) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=model.mapping_id,
        workspace_id=model.workspace_id,
        crm_agent_record_id=model.crm_agent_id,
        app_user_id=model.app_user_id,
        mapping_status=CRMAgentMappingStatus(model.mapping_status),
        resolution_source=CRMAgentMappingResolutionSource(model.resolution_source),
        resolved_by_user_id=model.resolved_by_user_id,
        resolved_at=model.resolved_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _mapping_models_to_domain(
    models: Sequence[WorkspaceAgentCRMMappingModel],
) -> tuple[WorkspaceAgentCRMMapping, ...]:
    return tuple(_mapping_from_model(model) for model in models)


def _mapping_to_values(mapping: WorkspaceAgentCRMMapping) -> dict[str, object]:
    return {
        "mapping_id": mapping.mapping_id,
        "workspace_id": mapping.workspace_id,
        "crm_agent_id": mapping.crm_agent_record_id,
        "app_user_id": mapping.app_user_id,
        "mapping_status": mapping.mapping_status.value,
        "resolution_source": mapping.resolution_source.value,
        "resolved_by_user_id": mapping.resolved_by_user_id,
        "resolved_at": mapping.resolved_at,
        "created_at": mapping.created_at,
        "updated_at": mapping.updated_at,
    }


def _mapping_update_values(mapping: WorkspaceAgentCRMMapping) -> dict[str, object]:
    values = _mapping_to_values(mapping)
    return {key: value for key, value in values.items() if key not in {"mapping_id", "created_at"}}


def _config_from_model(model: WorkspaceAgentMappingConfigModel) -> WorkspaceAgentMappingConfig:
    return WorkspaceAgentMappingConfig(
        workspace_id=model.workspace_id,
        unmapped_assignment_fallback_user_id=model.unmapped_assignment_fallback_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _config_to_values(config: WorkspaceAgentMappingConfig) -> dict[str, object]:
    return {
        "workspace_id": config.workspace_id,
        "unmapped_assignment_fallback_user_id": config.unmapped_assignment_fallback_user_id,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }