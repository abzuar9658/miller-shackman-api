from dataclasses import dataclass
from datetime import datetime

from app.domain.common.ids import UserId, WorkspaceId


@dataclass(frozen=True)
class AttentionAcknowledgement:
    workspace_id: WorkspaceId
    user_id: UserId
    attention_item_id: str
    attention_item_version: str
    acknowledged_at: datetime
