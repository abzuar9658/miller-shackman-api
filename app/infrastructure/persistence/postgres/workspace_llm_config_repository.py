from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.llm import LLMProviderKind, WorkspaceLLMConfig
from app.infrastructure.persistence.postgres.models import WorkspaceLLMConfigModel


class PostgresWorkspaceLLMConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceLLMConfig | None:
        result = await self._session.execute(
            select(WorkspaceLLMConfigModel).where(
                WorkspaceLLMConfigModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _config_from_model(model) if model else None

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        now = datetime.now(UTC)
        statement = (
            insert(WorkspaceLLMConfigModel)
            .values(
                workspace_id=config.workspace_id,
                openrouter_model=config.openrouter_model,
                llm_provider=config.llm_provider.value,
                openrouter_drafting_model=config.openrouter_drafting_model,
                openrouter_classification_model=config.openrouter_classification_model,
                bedrock_drafting_model=config.bedrock_drafting_model,
                bedrock_classification_model=config.bedrock_classification_model,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_={
                    "openrouter_model": config.openrouter_model,
                    "llm_provider": config.llm_provider.value,
                    "openrouter_drafting_model": config.openrouter_drafting_model,
                    "openrouter_classification_model": config.openrouter_classification_model,
                    "bedrock_drafting_model": config.bedrock_drafting_model,
                    "bedrock_classification_model": config.bedrock_classification_model,
                    "updated_at": now,
                },
            )
            .returning(WorkspaceLLMConfigModel)
        )
        result = await self._session.execute(statement)
        return _config_from_model(result.scalar_one())


def _config_from_model(model: WorkspaceLLMConfigModel) -> WorkspaceLLMConfig:
    return WorkspaceLLMConfig(
        workspace_id=model.workspace_id,
        openrouter_model=model.openrouter_model,
        llm_provider=LLMProviderKind(model.llm_provider),
        openrouter_drafting_model=model.openrouter_drafting_model,
        openrouter_classification_model=model.openrouter_classification_model,
        bedrock_drafting_model=model.bedrock_drafting_model,
        bedrock_classification_model=model.bedrock_classification_model,
    )
