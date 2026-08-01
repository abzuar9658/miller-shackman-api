from dataclasses import dataclass

from app.domain.common.ids import WorkspaceId

DEFAULT_WORKSPACE_OPENROUTER_MODEL = "openai/gpt-4o-mini"


@dataclass(frozen=True)
class WorkspaceLLMConfig:
    workspace_id: WorkspaceId
    openrouter_model: str = DEFAULT_WORKSPACE_OPENROUTER_MODEL


def default_workspace_llm_config(
    workspace_id: WorkspaceId,
    *,
    default_openrouter_model: str = DEFAULT_WORKSPACE_OPENROUTER_MODEL,
) -> WorkspaceLLMConfig:
    return WorkspaceLLMConfig(
        workspace_id=workspace_id,
        openrouter_model=default_openrouter_model,
    )
