from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.attention import AttentionAcknowledgement
from app.domain.common.ids import UserId, WorkspaceId
from app.infrastructure.persistence.postgres.models import AttentionAcknowledgementModel


class PostgresAttentionAcknowledgementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> tuple[AttentionAcknowledgement, ...]:
        result = await self._session.execute(
            select(AttentionAcknowledgementModel)
            .where(AttentionAcknowledgementModel.workspace_id == workspace_id)
            .where(AttentionAcknowledgementModel.user_id == user_id)
            .order_by(
                AttentionAcknowledgementModel.acknowledged_at.desc(),
                AttentionAcknowledgementModel.attention_item_id.asc(),
            )
        )
        return tuple(_acknowledgement_from_model(model) for model in result.scalars().all())

    async def get_by_item_id(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        attention_item_id: str,
    ) -> AttentionAcknowledgement | None:
        result = await self._session.execute(
            select(AttentionAcknowledgementModel)
            .where(AttentionAcknowledgementModel.workspace_id == workspace_id)
            .where(AttentionAcknowledgementModel.user_id == user_id)
            .where(AttentionAcknowledgementModel.attention_item_id == attention_item_id)
        )
        model = result.scalar_one_or_none()
        return _acknowledgement_from_model(model) if model is not None else None

    async def save(
        self,
        acknowledgement: AttentionAcknowledgement,
    ) -> AttentionAcknowledgement:
        values = _acknowledgement_to_values(acknowledgement)
        update_values = {
            "attention_item_version": acknowledgement.attention_item_version,
            "acknowledged_at": acknowledgement.acknowledged_at,
        }
        result = await self._session.execute(
            insert(AttentionAcknowledgementModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "user_id", "attention_item_id"],
                set_=update_values,
            )
            .returning(AttentionAcknowledgementModel)
        )
        return _acknowledgement_from_model(result.scalar_one())

    async def delete(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        attention_item_id: str,
    ) -> None:
        await self._session.execute(
            delete(AttentionAcknowledgementModel)
            .where(AttentionAcknowledgementModel.workspace_id == workspace_id)
            .where(AttentionAcknowledgementModel.user_id == user_id)
            .where(AttentionAcknowledgementModel.attention_item_id == attention_item_id)
        )


def _acknowledgement_from_model(
    model: AttentionAcknowledgementModel,
) -> AttentionAcknowledgement:
    return AttentionAcknowledgement(
        workspace_id=model.workspace_id,
        user_id=model.user_id,
        attention_item_id=model.attention_item_id,
        attention_item_version=model.attention_item_version,
        acknowledged_at=model.acknowledged_at,
    )


def _acknowledgement_to_values(
    acknowledgement: AttentionAcknowledgement,
) -> dict[str, object]:
    return {
        "workspace_id": acknowledgement.workspace_id,
        "user_id": acknowledgement.user_id,
        "attention_item_id": acknowledgement.attention_item_id,
        "attention_item_version": acknowledgement.attention_item_version,
        "acknowledged_at": acknowledgement.acknowledged_at,
    }