from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, case, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_activity import (
    LeadActivityItem,
    LeadActivityKind,
    LeadActivitySummary,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.infrastructure.persistence.postgres.models import (
    CrmConversationEventModel,
    HandoffModel,
    InboundMessageModel,
    OutboundMessageModel,
)

MAX_ACTIVITY_PREVIEW_CHARS = 140


class PostgresLeadActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_summaries(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[LeadActivitySummary, ...]:
        if len(lead_ids) == 0:
            return ()

        activity = _activity_union(workspace_id, lead_ids)
        counts = (
            select(
                activity.c.lead_id,
                func.sum(_kind_count(activity, LeadActivityKind.INBOUND_MESSAGE)).label(
                    "inbound_message_count"
                ),
                func.sum(_kind_count(activity, LeadActivityKind.OUTBOUND_MESSAGE)).label(
                    "outbound_message_count"
                ),
                func.sum(_kind_count(activity, LeadActivityKind.CRM_CONVERSATION_EVENT)).label(
                    "crm_event_count"
                ),
                func.sum(_kind_count(activity, LeadActivityKind.HANDOFF)).label("handoff_count"),
            )
            .group_by(activity.c.lead_id)
            .subquery()
        )
        latest = _latest_activity_subquery(activity)

        result = await self._session.execute(
            select(
                counts.c.lead_id,
                counts.c.inbound_message_count,
                counts.c.outbound_message_count,
                counts.c.crm_event_count,
                counts.c.handoff_count,
                latest.c.kind,
                latest.c.occurred_at,
                latest.c.preview,
                latest.c.activity_type,
                latest.c.direction,
            ).join(
                latest,
                and_(latest.c.lead_id == counts.c.lead_id, latest.c.row_number == 1),
            )
        )
        return tuple(_row_to_summary(row) for row in result.all())

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadActivityItem, ...]:
        activity = _activity_union(workspace_id, (lead_id,))
        result = await self._session.execute(
            select(activity)
            .order_by(activity.c.occurred_at.desc(), activity.c.activity_id.desc())
            .limit(limit)
        )
        return tuple(_row_to_item(row) for row in result.all())


def _activity_union(workspace_id: WorkspaceId, lead_ids: tuple[LeadId, ...]) -> Any:
    null_string = cast(literal(None), String)
    return union_all(
        select(
            InboundMessageModel.inbound_message_id.label("activity_id"),
            InboundMessageModel.lead_id.label("lead_id"),
            literal(LeadActivityKind.INBOUND_MESSAGE.value).label("kind"),
            InboundMessageModel.received_at.label("occurred_at"),
            InboundMessageModel.body.label("preview"),
            InboundMessageModel.body.label("content"),
            InboundMessageModel.channel.label("channel"),
            literal("inbound").label("direction"),
            InboundMessageModel.classification_status.label("status"),
            InboundMessageModel.provider.label("actor_name"),
            literal("Inbound message").label("activity_type"),
        )
        .where(InboundMessageModel.workspace_id == workspace_id)
        .where(InboundMessageModel.lead_id.in_(lead_ids)),
        select(
            OutboundMessageModel.message_id.label("activity_id"),
            OutboundMessageModel.lead_id.label("lead_id"),
            literal(LeadActivityKind.OUTBOUND_MESSAGE.value).label("kind"),
            func.coalesce(
                OutboundMessageModel.sent_at,
                OutboundMessageModel.planned_at,
                OutboundMessageModel.scheduled_for,
                OutboundMessageModel.created_at,
            ).label("occurred_at"),
            OutboundMessageModel.body.label("preview"),
            OutboundMessageModel.body.label("content"),
            OutboundMessageModel.channel.label("channel"),
            literal("outbound").label("direction"),
            OutboundMessageModel.status.label("status"),
            OutboundMessageModel.provider_name.label("actor_name"),
            literal("Outbound message").label("activity_type"),
        )
        .where(OutboundMessageModel.workspace_id == workspace_id)
        .where(OutboundMessageModel.lead_id.in_(lead_ids)),
        select(
            CrmConversationEventModel.crm_conversation_event_id.label("activity_id"),
            CrmConversationEventModel.lead_id.label("lead_id"),
            literal(LeadActivityKind.CRM_CONVERSATION_EVENT.value).label("kind"),
            CrmConversationEventModel.occurred_at.label("occurred_at"),
            CrmConversationEventModel.content.label("preview"),
            CrmConversationEventModel.content.label("content"),
            null_string.label("channel"),
            CrmConversationEventModel.direction.label("direction"),
            CrmConversationEventModel.activity_type.label("status"),
            CrmConversationEventModel.actor_name.label("actor_name"),
            CrmConversationEventModel.activity_type.label("activity_type"),
        )
        .where(CrmConversationEventModel.workspace_id == workspace_id)
        .where(CrmConversationEventModel.lead_id.in_(lead_ids)),
        select(
            HandoffModel.handoff_id.label("activity_id"),
            HandoffModel.lead_id.label("lead_id"),
            literal(LeadActivityKind.HANDOFF.value).label("kind"),
            HandoffModel.created_at.label("occurred_at"),
            HandoffModel.summary.label("preview"),
            HandoffModel.summary.label("content"),
            null_string.label("channel"),
            null_string.label("direction"),
            HandoffModel.status.label("status"),
            null_string.label("actor_name"),
            HandoffModel.reason_code.label("activity_type"),
        )
        .where(HandoffModel.workspace_id == workspace_id)
        .where(HandoffModel.lead_id.in_(lead_ids)),
    ).subquery()


def _kind_count(activity: Any, kind: LeadActivityKind) -> Any:
    return case((activity.c.kind == kind.value, 1), else_=0)


def _latest_activity_subquery(activity: Any) -> Any:
    return select(
        activity.c.lead_id,
        activity.c.kind,
        activity.c.occurred_at,
        activity.c.preview,
        activity.c.activity_type,
        activity.c.direction,
        func.row_number()
        .over(
            partition_by=activity.c.lead_id,
            order_by=(activity.c.occurred_at.desc(), activity.c.activity_id.desc()),
        )
        .label("row_number"),
    ).subquery()


def _row_to_summary(row: Any) -> LeadActivitySummary:
    kind = LeadActivityKind(row.kind)
    return LeadActivitySummary(
        lead_id=row.lead_id,
        inbound_message_count=int(row.inbound_message_count or 0),
        outbound_message_count=int(row.outbound_message_count or 0),
        crm_event_count=int(row.crm_event_count or 0),
        handoff_count=int(row.handoff_count or 0),
        latest_activity_at=row.occurred_at,
        latest_activity_preview=_preview_text(row.preview) or _title_for(
            kind,
            activity_type=row.activity_type,
            direction=row.direction,
        ),
        latest_activity_kind=kind,
    )


def _row_to_item(row: Any) -> LeadActivityItem:
    kind = LeadActivityKind(row.kind)
    return LeadActivityItem(
        activity_id=_as_uuid(row.activity_id),
        lead_id=row.lead_id,
        kind=kind,
        occurred_at=row.occurred_at,
        title=_title_for(kind, activity_type=row.activity_type, direction=row.direction),
        preview=_preview_text(row.preview)
        or _title_for(kind, activity_type=row.activity_type, direction=row.direction),
        content=row.content,
        channel=row.channel,
        direction=row.direction,
        status=row.status,
        actor_name=row.actor_name,
    )


def _title_for(
    kind: LeadActivityKind,
    *,
    activity_type: str | None,
    direction: str | None,
) -> str:
    if kind == LeadActivityKind.INBOUND_MESSAGE:
        return "Inbound reply received"
    if kind == LeadActivityKind.OUTBOUND_MESSAGE:
        return "Outbound outreach logged"
    if kind == LeadActivityKind.HANDOFF:
        return "Human handoff created"
    if direction == "inbound":
        return "CRM reply logged"
    if direction == "outbound":
        return "CRM outbound logged"
    if direction == "internal":
        return "CRM note logged"
    label = (activity_type or "activity").strip().lower()
    return f"CRM {label} logged"


def _preview_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) <= MAX_ACTIVITY_PREVIEW_CHARS:
        return normalized
    return f"{normalized[: MAX_ACTIVITY_PREVIEW_CHARS - 1].rstrip()}…"


def _as_uuid(value: UUID) -> UUID:
    return value