from dataclasses import dataclass
from enum import StrEnum

from app.domain.common.ids import WorkspaceId


class LLMProviderKind(StrEnum):
    OPENROUTER = "openrouter"
    BEDROCK = "bedrock"


class LLMTaskKind(StrEnum):
    DRAFTING = "drafting"
    CLASSIFICATION = "classification"


DEFAULT_WORKSPACE_LLM_PROVIDER = LLMProviderKind.OPENROUTER
DEFAULT_WORKSPACE_OPENROUTER_MODEL = "openai/gpt-4o-mini"
DEFAULT_WORKSPACE_OPENROUTER_DRAFTING_MODEL = DEFAULT_WORKSPACE_OPENROUTER_MODEL
DEFAULT_WORKSPACE_OPENROUTER_CLASSIFICATION_MODEL = DEFAULT_WORKSPACE_OPENROUTER_MODEL
DEFAULT_WORKSPACE_BEDROCK_DRAFTING_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_WORKSPACE_BEDROCK_CLASSIFICATION_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@dataclass(frozen=True)
class WorkspaceLLMConfig:
    workspace_id: WorkspaceId
    # Deprecated: kept for API back-compat; write sites keep it equal to
    # openrouter_drafting_model.
    openrouter_model: str = DEFAULT_WORKSPACE_OPENROUTER_MODEL
    llm_provider: LLMProviderKind = DEFAULT_WORKSPACE_LLM_PROVIDER
    openrouter_drafting_model: str = DEFAULT_WORKSPACE_OPENROUTER_DRAFTING_MODEL
    openrouter_classification_model: str = DEFAULT_WORKSPACE_OPENROUTER_CLASSIFICATION_MODEL
    bedrock_drafting_model: str = DEFAULT_WORKSPACE_BEDROCK_DRAFTING_MODEL
    bedrock_classification_model: str = DEFAULT_WORKSPACE_BEDROCK_CLASSIFICATION_MODEL


def default_workspace_llm_config(
    workspace_id: WorkspaceId,
    *,
    default_openrouter_model: str = DEFAULT_WORKSPACE_OPENROUTER_MODEL,
    default_llm_provider: LLMProviderKind = DEFAULT_WORKSPACE_LLM_PROVIDER,
    default_openrouter_drafting_model: str | None = None,
    default_openrouter_classification_model: str | None = None,
    default_bedrock_drafting_model: str = DEFAULT_WORKSPACE_BEDROCK_DRAFTING_MODEL,
    default_bedrock_classification_model: str = DEFAULT_WORKSPACE_BEDROCK_CLASSIFICATION_MODEL,
) -> WorkspaceLLMConfig:
    drafting_model = default_openrouter_drafting_model or default_openrouter_model
    return WorkspaceLLMConfig(
        workspace_id=workspace_id,
        openrouter_model=drafting_model,
        llm_provider=default_llm_provider,
        openrouter_drafting_model=drafting_model,
        openrouter_classification_model=(
            default_openrouter_classification_model or default_openrouter_model
        ),
        bedrock_drafting_model=default_bedrock_drafting_model,
        bedrock_classification_model=default_bedrock_classification_model,
    )
