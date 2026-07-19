from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.outbound_drafting import (
    DEFAULT_EMAIL_PROMPT_TEXT,
    DEFAULT_PROMPT_TEXT,
    DEFAULT_SMS_PROMPT_TEXT,
    WorkspaceOutboundDraftingConfig,
    normalize_config_prompt_text,
    normalize_email_subject_template,
    normalize_email_template,
    normalize_enabled_extraction_fields,
    normalize_outbound_prompt_text,
    normalize_sms_template,
)
from app.infrastructure.persistence.postgres.models import WorkspaceOutboundDraftingConfigModel


class PostgresWorkspaceOutboundDraftingConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id,
    ) -> WorkspaceOutboundDraftingConfig | None:
        result = await self._session.execute(
            select(WorkspaceOutboundDraftingConfigModel).where(
                WorkspaceOutboundDraftingConfigModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _config_from_model(model) if model else None

    async def save(
        self,
        config: WorkspaceOutboundDraftingConfig,
    ) -> WorkspaceOutboundDraftingConfig:
        now = datetime.now(UTC)
        current = await self.get_by_workspace_id(config.workspace_id)
        revision = (current.revision + 1) if current is not None else max(config.revision, 1)
        statement = (
            insert(WorkspaceOutboundDraftingConfigModel)
            .values(
                workspace_id=config.workspace_id,
                revision=revision,
                sms_template=config.sms_template,
                email_template=config.email_template,
                email_subject_template=config.email_subject_template,
                sms_prompt_text=config.sms_prompt_text,
                email_prompt_text=config.email_prompt_text,
                prompt_text=config.prompt_text,
                enabled_extraction_fields=list(config.enabled_extraction_fields),
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_={
                    "revision": revision,
                    "sms_template": config.sms_template,
                    "email_template": config.email_template,
                    "email_subject_template": config.email_subject_template,
                    "sms_prompt_text": config.sms_prompt_text,
                    "email_prompt_text": config.email_prompt_text,
                    "prompt_text": config.prompt_text,
                    "enabled_extraction_fields": list(config.enabled_extraction_fields),
                    "updated_at": now,
                },
            )
            .returning(WorkspaceOutboundDraftingConfigModel)
        )
        result = await self._session.execute(statement)
        return _config_from_model(result.scalar_one())


def _config_from_model(
    model: WorkspaceOutboundDraftingConfigModel,
) -> WorkspaceOutboundDraftingConfig:
    return WorkspaceOutboundDraftingConfig(
        workspace_id=model.workspace_id,
        revision=model.revision,
        sms_template=normalize_sms_template(model.sms_template),
        email_template=normalize_email_template(model.email_template),
        email_subject_template=normalize_email_subject_template(
            model.email_subject_template,
        ),
        sms_prompt_text=normalize_outbound_prompt_text(
            getattr(model, "sms_prompt_text", None) or model.prompt_text,
            default_text=DEFAULT_SMS_PROMPT_TEXT,
        ),
        email_prompt_text=normalize_outbound_prompt_text(
            getattr(model, "email_prompt_text", None) or model.prompt_text,
            default_text=DEFAULT_EMAIL_PROMPT_TEXT,
        ),
        prompt_text=normalize_config_prompt_text(
            getattr(model, "prompt_text", None) or DEFAULT_PROMPT_TEXT,
        ),
        enabled_extraction_fields=normalize_enabled_extraction_fields(
            model.enabled_extraction_fields,
        ),
    )
