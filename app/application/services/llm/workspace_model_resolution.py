from app.application.ports.repositories import WorkspaceLLMConfigRepository
from app.domain.common.ids import WorkspaceId
from app.domain.llm import default_workspace_llm_config


async def resolve_workspace_openrouter_model(
    *,
    workspace_id: WorkspaceId,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    default_openrouter_model: str,
) -> str:
    if workspace_llm_config_repository is None:
        return default_openrouter_model

    config = await workspace_llm_config_repository.get_by_workspace_id(workspace_id)
    if config is None:
        return default_workspace_llm_config(
            workspace_id,
            default_openrouter_model=default_openrouter_model,
        ).openrouter_model
    return config.openrouter_model