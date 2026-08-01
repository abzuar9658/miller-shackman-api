from app.domain.attention import AttentionAcknowledgement
from app.domain.common.ids import UserId, WorkspaceId


class FakeAttentionAcknowledgementRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[WorkspaceId, UserId, str], AttentionAcknowledgement] = {}

    async def list_for_user(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
    ) -> tuple[AttentionAcknowledgement, ...]:
        items = [
            item
            for key, item in self._items.items()
            if key[0] == workspace_id and key[1] == user_id
        ]
        items.sort(
            key=lambda item: (item.acknowledged_at, item.attention_item_id),
            reverse=True,
        )
        return tuple(items)

    async def get_by_item_id(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        attention_item_id: str,
    ) -> AttentionAcknowledgement | None:
        return self._items.get((workspace_id, user_id, attention_item_id))

    async def save(
        self,
        acknowledgement: AttentionAcknowledgement,
    ) -> AttentionAcknowledgement:
        key = (
            acknowledgement.workspace_id,
            acknowledgement.user_id,
            acknowledgement.attention_item_id,
        )
        self._items[key] = acknowledgement
        return acknowledgement

    async def delete(
        self,
        workspace_id: WorkspaceId,
        user_id: UserId,
        attention_item_id: str,
    ) -> None:
        self._items.pop((workspace_id, user_id, attention_item_id), None)
