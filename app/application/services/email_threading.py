from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.application.ports.repositories import InboundMessageRepository, OutboundMessageRepository
from app.domain.campaigns.outbound_message import (
    OutboundMessageStatus,
    build_outbound_email_message_id,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel

_EMAIL_THREAD_MESSAGE_FETCH_LIMIT = 20
_EMAIL_THREAD_REFERENCE_LIMIT = 12


@dataclass(frozen=True)
class EmailThreadingHeaders:
    in_reply_to_message_id: str | None = None
    reference_message_ids: tuple[str, ...] = ()

    @property
    def has_thread(self) -> bool:
        return self.in_reply_to_message_id is not None


@dataclass(frozen=True)
class _ThreadMessage:
    occurred_at: datetime
    message_id: str


async def resolve_lead_email_threading_headers(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    inbound_message_repository: InboundMessageRepository | None,
    message_repository: OutboundMessageRepository | None,
    anchor_inbound_message_id: UUID | None = None,
    current_outbound_message_id: UUID | None = None,
) -> EmailThreadingHeaders:
    messages: list[_ThreadMessage] = []
    anchor_message: _ThreadMessage | None = None

    if inbound_message_repository is not None:
        anchor_message = await _load_anchor_inbound_message(
            workspace_id=workspace_id,
            inbound_message_id=anchor_inbound_message_id,
            inbound_message_repository=inbound_message_repository,
        )
        inbound_messages = await inbound_message_repository.list_for_lead(
            workspace_id,
            lead_id,
            limit=_EMAIL_THREAD_MESSAGE_FETCH_LIMIT,
        )
        for message in inbound_messages:
            thread_message = _thread_message_from_inbound(message)
            if thread_message is not None:
                messages.append(thread_message)

    if message_repository is not None:
        outbound_messages = await message_repository.list_for_lead(
            workspace_id,
            lead_id,
            limit=_EMAIL_THREAD_MESSAGE_FETCH_LIMIT,
        )
        for message in outbound_messages:
            if message.message_id == current_outbound_message_id:
                continue
            if message.channel != ContactChannel.EMAIL:
                continue
            if message.status != OutboundMessageStatus.SENT:
                continue
            messages.append(
                _ThreadMessage(
                    occurred_at=message.sent_at or message.created_at,
                    message_id=build_outbound_email_message_id(message.message_id),
                )
            )

    if anchor_message is None:
        anchor_message = _latest_thread_message(messages)
    if anchor_message is None:
        return EmailThreadingHeaders()

    return EmailThreadingHeaders(
        in_reply_to_message_id=anchor_message.message_id,
        reference_message_ids=_reference_message_ids(messages, anchor_message.message_id),
    )


async def _load_anchor_inbound_message(
    *,
    workspace_id: WorkspaceId,
    inbound_message_id: UUID | None,
    inbound_message_repository: InboundMessageRepository,
) -> _ThreadMessage | None:
    if inbound_message_id is None:
        return None
    message = await inbound_message_repository.get_by_id(workspace_id, inbound_message_id)
    return _thread_message_from_inbound(message)


def _thread_message_from_inbound(message: Any | None) -> _ThreadMessage | None:
    if message is None:
        return None
    if message.channel != ContactChannel.EMAIL:
        return None
    message_id = _normalize_message_id(message.provider_message_id)
    if message_id is None:
        return None
    return _ThreadMessage(occurred_at=message.received_at, message_id=message_id)


def _latest_thread_message(messages: list[_ThreadMessage]) -> _ThreadMessage | None:
    if not messages:
        return None
    return max(messages, key=lambda message: message.occurred_at)


def _reference_message_ids(
    messages: list[_ThreadMessage],
    anchor_message_id: str,
) -> tuple[str, ...]:
    ordered_ids: list[str] = []
    for message in sorted(messages, key=lambda item: item.occurred_at):
        _append_unique(ordered_ids, message.message_id)
    _append_unique(ordered_ids, anchor_message_id)
    return tuple(ordered_ids[-_EMAIL_THREAD_REFERENCE_LIMIT:])


def _append_unique(values: list[str], value: str) -> None:
    normalized = _normalize_message_id(value)
    if normalized is not None and normalized not in values:
        values.append(normalized)


def _normalize_message_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().strip("<>")
    return normalized or None


def resolve_reply_email_subject(
    *,
    inbound_channel: ContactChannel,
    inbound_email_subject: str | None,
    drafted_subject: str | None,
) -> str | None:
    """Return the inbound email subject when replying to an email thread.

    Many email clients treat a changed subject as a new thread even when
    In-Reply-To / References headers are present. Reuse the inbound subject
    so follow-up replies stay in the same conversation.
    """
    if inbound_channel != ContactChannel.EMAIL:
        return drafted_subject
    if inbound_email_subject is not None:
        normalized_subject = inbound_email_subject.strip()
        if normalized_subject:
            return normalized_subject
    return drafted_subject
