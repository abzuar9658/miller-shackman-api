from dataclasses import dataclass

from app.application.ports.repositories import WorkspaceLLMConfigRepository
from app.domain.common.ids import WorkspaceId
from app.domain.llm import (
    LLMProviderKind,
    LLMTaskKind,
    WorkspaceLLMConfig,
    default_workspace_llm_config,
)


@dataclass(frozen=True)
class WorkspaceLLMSelection:
    provider: LLMProviderKind
    model: str


async def resolve_workspace_llm_config(
    *,
    workspace_id: WorkspaceId,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    default_openrouter_model: str,
) -> WorkspaceLLMConfig:
    config = (
        await workspace_llm_config_repository.get_by_workspace_id(workspace_id)
        if workspace_llm_config_repository is not None
        else None
    )
    if config is None:
        return default_workspace_llm_config(
            workspace_id,
            default_openrouter_model=default_openrouter_model,
        )
    return config


def workspace_llm_selection_for_task(
    config: WorkspaceLLMConfig,
    task: LLMTaskKind,
) -> WorkspaceLLMSelection:
    if config.llm_provider is LLMProviderKind.BEDROCK:
        model = (
            config.bedrock_drafting_model
            if task is LLMTaskKind.DRAFTING
            else config.bedrock_classification_model
        )
    else:
        model = (
            config.openrouter_drafting_model
            if task is LLMTaskKind.DRAFTING
            else config.openrouter_classification_model
        )
    return WorkspaceLLMSelection(provider=config.llm_provider, model=model)


async def resolve_workspace_llm_selection(
    *,
    workspace_id: WorkspaceId,
    task: LLMTaskKind,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    default_openrouter_model: str,
) -> WorkspaceLLMSelection:
    config = await resolve_workspace_llm_config(
        workspace_id=workspace_id,
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
    )
    return workspace_llm_selection_for_task(config, task)
