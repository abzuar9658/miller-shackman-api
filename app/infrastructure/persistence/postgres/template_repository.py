from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.template_registry import (
    TemplateChannel,
    TemplateStatus,
    TemplateVersion,
)
from app.domain.common.ids import WorkspaceId
from app.infrastructure.persistence.postgres.models import TemplateVersionModel


class PostgresTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        template_version_id: UUID,
    ) -> TemplateVersion | None:
        result = await self._session.execute(
            select(TemplateVersionModel).where(
                TemplateVersionModel.workspace_id == workspace_id,
                TemplateVersionModel.template_version_id == template_version_id,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_by_key_and_version(
        self,
        workspace_id: WorkspaceId,
        template_key: str,
        version: int,
    ) -> TemplateVersion | None:
        result = await self._session.execute(
            select(TemplateVersionModel).where(
                TemplateVersionModel.workspace_id == workspace_id,
                TemplateVersionModel.template_key == template_key,
                TemplateVersionModel.version == version,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_latest_approved_by_key(
        self,
        workspace_id: WorkspaceId,
        template_key: str,
    ) -> TemplateVersion | None:
        result = await self._session.execute(
            select(TemplateVersionModel)
            .where(
                TemplateVersionModel.workspace_id == workspace_id,
                TemplateVersionModel.template_key == template_key,
                TemplateVersionModel.status == TemplateStatus.APPROVED.value,
            )
            .order_by(TemplateVersionModel.version.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def save(self, template: TemplateVersion) -> TemplateVersion:
        values = _to_values(template)
        await self._session.execute(
            insert(TemplateVersionModel)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "template_key", "version"],
            )
        )
        saved = await self.get_by_key_and_version(
            template.workspace_id,
            template.template_key,
            template.version,
        )
        assert saved is not None
        return saved

    async def list_approved(self, workspace_id: WorkspaceId) -> tuple[TemplateVersion, ...]:
        result = await self._session.execute(
            select(TemplateVersionModel)
            .where(
                TemplateVersionModel.workspace_id == workspace_id,
                TemplateVersionModel.status == TemplateStatus.APPROVED.value,
            )
            .order_by(TemplateVersionModel.template_key, TemplateVersionModel.version)
        )
        return tuple(_from_model(model) for model in result.scalars().all())


def _to_values(template: TemplateVersion) -> dict[str, object]:
    return {
        "template_version_id": template.template_version_id,
        "workspace_id": template.workspace_id,
        "template_key": template.template_key,
        "version": template.version,
        "channel": template.channel.value,
        "purpose": template.purpose,
        "content": template.content,
        "subject": template.subject,
        "prompt_text": template.prompt_text,
        "allowed_variables": list(template.allowed_variables),
        "permitted_use_tags": list(template.permitted_use_tags),
        "status": template.status.value,
        "approved_at": template.approved_at,
        "created_at": template.created_at,
    }


def _from_model(model: TemplateVersionModel) -> TemplateVersion:
    return TemplateVersion(
        template_version_id=model.template_version_id,
        workspace_id=model.workspace_id,
        template_key=model.template_key,
        version=model.version,
        channel=TemplateChannel(model.channel),
        purpose=model.purpose,
        content=model.content,
        subject=model.subject,
        prompt_text=model.prompt_text,
        allowed_variables=tuple(model.allowed_variables),
        permitted_use_tags=tuple(model.permitted_use_tags),
        status=TemplateStatus(model.status),
        approved_at=model.approved_at,
        created_at=model.created_at,
    )
