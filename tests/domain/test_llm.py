from uuid import UUID

from app.domain.llm import (
    DEFAULT_WORKSPACE_BEDROCK_CLASSIFICATION_MODEL,
    DEFAULT_WORKSPACE_BEDROCK_DRAFTING_MODEL,
    DEFAULT_WORKSPACE_OPENROUTER_MODEL,
    LLMProviderKind,
    WorkspaceLLMConfig,
    default_workspace_llm_config,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_default_config_uses_openrouter_provider_and_default_models() -> None:
    config = default_workspace_llm_config(WORKSPACE_ID)

    assert config.llm_provider is LLMProviderKind.OPENROUTER
    assert config.openrouter_model == DEFAULT_WORKSPACE_OPENROUTER_MODEL
    assert config.openrouter_drafting_model == DEFAULT_WORKSPACE_OPENROUTER_MODEL
    assert config.openrouter_classification_model == DEFAULT_WORKSPACE_OPENROUTER_MODEL
    assert config.bedrock_drafting_model == DEFAULT_WORKSPACE_BEDROCK_DRAFTING_MODEL
    assert config.bedrock_classification_model == (
        DEFAULT_WORKSPACE_BEDROCK_CLASSIFICATION_MODEL
    )


def test_default_config_task_models_fall_back_to_openrouter_model() -> None:
    config = default_workspace_llm_config(
        WORKSPACE_ID,
        default_openrouter_model="openai/gpt-4o",
    )

    assert config.openrouter_model == "openai/gpt-4o"
    assert config.openrouter_drafting_model == "openai/gpt-4o"
    assert config.openrouter_classification_model == "openai/gpt-4o"


def test_default_config_keeps_legacy_model_in_sync_with_drafting_model() -> None:
    config = default_workspace_llm_config(
        WORKSPACE_ID,
        default_openrouter_model="openai/gpt-4o-mini",
        default_openrouter_drafting_model="anthropic/claude-sonnet-4.5",
        default_openrouter_classification_model="anthropic/claude-haiku-4.5",
    )

    assert config.openrouter_drafting_model == "anthropic/claude-sonnet-4.5"
    assert config.openrouter_model == "anthropic/claude-sonnet-4.5"
    assert config.openrouter_classification_model == "anthropic/claude-haiku-4.5"


def test_default_config_accepts_explicit_provider_and_bedrock_models() -> None:
    config = default_workspace_llm_config(
        WORKSPACE_ID,
        default_llm_provider=LLMProviderKind.BEDROCK,
        default_bedrock_drafting_model="us.amazon.nova-pro-v1:0",
        default_bedrock_classification_model="us.amazon.nova-lite-v1:0",
    )

    assert config.llm_provider is LLMProviderKind.BEDROCK
    assert config.bedrock_drafting_model == "us.amazon.nova-pro-v1:0"
    assert config.bedrock_classification_model == "us.amazon.nova-lite-v1:0"


def test_config_dataclass_defaults_are_backward_compatible() -> None:
    config = WorkspaceLLMConfig(workspace_id=WORKSPACE_ID)

    assert config.llm_provider is LLMProviderKind.OPENROUTER
    assert config.openrouter_model == DEFAULT_WORKSPACE_OPENROUTER_MODEL
