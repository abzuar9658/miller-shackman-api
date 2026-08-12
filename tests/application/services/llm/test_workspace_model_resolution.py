from uuid import uuid4

from app.application.services.llm.workspace_model_resolution import (
    resolve_workspace_llm_config,
    resolve_workspace_llm_selection,
    workspace_llm_selection_for_task,
)
from app.domain.common.ids import WorkspaceId
from app.domain.llm import (
    LLMProviderKind,
    LLMTaskKind,
    WorkspaceLLMConfig,
)

WORKSPACE_ID = uuid4()


class FakeWorkspaceLLMConfigRepository:
    def __init__(self, config: WorkspaceLLMConfig | None) -> None:
        self._config = config

    async def get_by_workspace_id(self, workspace_id: WorkspaceId) -> WorkspaceLLMConfig | None:
        return self._config

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        self._config = config
        return config


def _config(**overrides: object) -> WorkspaceLLMConfig:
    return WorkspaceLLMConfig(
        workspace_id=WORKSPACE_ID,
        openrouter_model="openai/gpt-4.1-mini",
        openrouter_drafting_model="anthropic/claude-sonnet-4.5",
        openrouter_classification_model="anthropic/claude-haiku-4.5",
        bedrock_drafting_model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        bedrock_classification_model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        **overrides,  # type: ignore[arg-type]
    )


async def test_resolve_config_returns_defaults_without_repository() -> None:
    config = await resolve_workspace_llm_config(
        workspace_id=WORKSPACE_ID,
        workspace_llm_config_repository=None,
        default_openrouter_model="openai/gpt-4o-mini",
    )

    assert config.llm_provider is LLMProviderKind.OPENROUTER
    assert config.openrouter_drafting_model == "openai/gpt-4o-mini"
    assert config.openrouter_classification_model == "openai/gpt-4o-mini"


async def test_resolve_config_returns_defaults_when_workspace_has_no_config() -> None:
    config = await resolve_workspace_llm_config(
        workspace_id=WORKSPACE_ID,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(None),
        default_openrouter_model="openai/gpt-4o-mini",
    )

    assert config.llm_provider is LLMProviderKind.OPENROUTER
    assert config.openrouter_drafting_model == "openai/gpt-4o-mini"


async def test_resolve_config_returns_stored_config() -> None:
    stored = _config()
    config = await resolve_workspace_llm_config(
        workspace_id=WORKSPACE_ID,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(stored),
        default_openrouter_model="openai/gpt-4o-mini",
    )

    assert config is stored


def test_selection_for_openrouter_tasks() -> None:
    config = _config(llm_provider=LLMProviderKind.OPENROUTER)

    drafting = workspace_llm_selection_for_task(config, LLMTaskKind.DRAFTING)
    classification = workspace_llm_selection_for_task(config, LLMTaskKind.CLASSIFICATION)

    assert drafting.provider is LLMProviderKind.OPENROUTER
    assert drafting.model == "anthropic/claude-sonnet-4.5"
    assert classification.provider is LLMProviderKind.OPENROUTER
    assert classification.model == "anthropic/claude-haiku-4.5"


def test_selection_for_bedrock_tasks() -> None:
    config = _config(llm_provider=LLMProviderKind.BEDROCK)

    drafting = workspace_llm_selection_for_task(config, LLMTaskKind.DRAFTING)
    classification = workspace_llm_selection_for_task(config, LLMTaskKind.CLASSIFICATION)

    assert drafting.provider is LLMProviderKind.BEDROCK
    assert drafting.model == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert classification.provider is LLMProviderKind.BEDROCK
    assert classification.model == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


async def test_resolve_selection_combines_config_and_task() -> None:
    selection = await resolve_workspace_llm_selection(
        workspace_id=WORKSPACE_ID,
        task=LLMTaskKind.CLASSIFICATION,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(
            _config(llm_provider=LLMProviderKind.BEDROCK)
        ),
        default_openrouter_model="openai/gpt-4o-mini",
    )

    assert selection.provider is LLMProviderKind.BEDROCK
    assert selection.model == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


async def test_resolve_selection_falls_back_to_platform_default() -> None:
    selection = await resolve_workspace_llm_selection(
        workspace_id=WORKSPACE_ID,
        task=LLMTaskKind.DRAFTING,
        workspace_llm_config_repository=None,
        default_openrouter_model="openai/gpt-4o-mini",
    )

    assert selection.provider is LLMProviderKind.OPENROUTER
    assert selection.model == "openai/gpt-4o-mini"
