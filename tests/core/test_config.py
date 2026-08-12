import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_include_curated_allowed_models() -> None:
    settings = Settings(_env_file=None)

    assert "openai/gpt-4o-mini" in settings.openrouter_allowed_models
    assert len(settings.openrouter_allowed_models) >= 2
    assert settings.bedrock_drafting_model in settings.bedrock_allowed_models
    assert settings.bedrock_classification_model in settings.bedrock_allowed_models
    assert settings.bedrock_enabled is False


def test_openrouter_task_models_default_to_openrouter_model() -> None:
    settings = Settings()

    assert settings.openrouter_drafting_model == ""
    assert settings.resolved_openrouter_drafting_model == settings.openrouter_model
    assert settings.resolved_openrouter_classification_model == settings.openrouter_model


def test_openrouter_task_models_resolve_when_set() -> None:
    settings = Settings(
        openrouter_drafting_model="openai/gpt-4o",
        openrouter_classification_model="anthropic/claude-haiku-4.5",
    )

    assert settings.resolved_openrouter_drafting_model == "openai/gpt-4o"
    assert settings.resolved_openrouter_classification_model == "anthropic/claude-haiku-4.5"


def test_openrouter_task_model_must_be_in_allowed_list() -> None:
    with pytest.raises(ValidationError, match="openrouter_drafting_model"):
        Settings(openrouter_drafting_model="openai/not-in-list")


def test_bedrock_task_model_must_be_in_allowed_list() -> None:
    with pytest.raises(ValidationError, match="bedrock_classification_model"):
        Settings(bedrock_classification_model="us.anthropic.not-in-list")


def test_allowed_models_lists_must_be_non_empty() -> None:
    with pytest.raises(ValidationError, match="at least one model"):
        Settings(
            openrouter_allowed_models=[" "],
            openrouter_model="openai/gpt-4o-mini",
        )
    with pytest.raises(ValidationError, match="at least one model"):
        Settings(
            bedrock_allowed_models=[],
            bedrock_drafting_model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        )


def test_allowed_models_are_deduplicated_and_stripped() -> None:
    settings = Settings(
        bedrock_allowed_models=[
            " us.amazon.nova-pro-v1:0 ",
            "us.amazon.nova-pro-v1:0",
        ],
        bedrock_drafting_model="us.amazon.nova-pro-v1:0",
        bedrock_classification_model="us.amazon.nova-pro-v1:0",
    )

    assert settings.bedrock_allowed_models == ["us.amazon.nova-pro-v1:0"]
