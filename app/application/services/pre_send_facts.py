from dataclasses import dataclass
from datetime import datetime

from app.application.ports.repositories import (
    InboundMessageRepository,
    OutboundMessageRepository,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


@dataclass(frozen=True)
class PreSendHistoryFacts:
    other_channel_sent_at: datetime | None
    lead_replied_since_scheduled: bool


async def load_pre_send_history_facts(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    message: OutboundMessage,
    message_repository: OutboundMessageRepository,
    inbound_message_repository: InboundMessageRepository | None,
) -> PreSendHistoryFacts | None:
    try:
        latest_sent_at = getattr(message_repository, "get_latest_sent_at_for_lead", None)
        other_channel = _other_channel(message.channel)
        if callable(latest_sent_at):
            other_channel_sent_at = await latest_sent_at(
                workspace_id,
                lead_id,
                channel=other_channel,
            )
        else:
            history = await message_repository.list_for_lead(workspace_id, lead_id, limit=100)
            other_channel_sent_at = _latest_sent_at(history, channel=other_channel)
        lead_replied_since_scheduled = False
        if message.scheduled_for is not None and inbound_message_repository is not None:
            latest_received_at = getattr(
                inbound_message_repository,
                "get_latest_received_at_for_lead",
                None,
            )
            if callable(latest_received_at):
                latest_inbound_at = await latest_received_at(workspace_id, lead_id)
            else:
                inbound_history = await inbound_message_repository.list_for_lead(
                    workspace_id,
                    lead_id,
                    limit=100,
                )
                latest_inbound_at = max(
                    (item.received_at for item in inbound_history),
                    default=None,
                )
            lead_replied_since_scheduled = (
                latest_inbound_at is not None and latest_inbound_at > message.scheduled_for
            )
    except Exception:
        return None

    return PreSendHistoryFacts(
        other_channel_sent_at=other_channel_sent_at,
        lead_replied_since_scheduled=lead_replied_since_scheduled,
    )


def _other_channel(channel: ContactChannel) -> ContactChannel:
    return ContactChannel.EMAIL if channel == ContactChannel.SMS else ContactChannel.SMS


def _latest_sent_at(
    messages: tuple[OutboundMessage, ...],
    *,
    channel: ContactChannel | None = None,
) -> datetime | None:
    return max(
        (
            message.sent_at
            for message in messages
            if message.status == OutboundMessageStatus.SENT
            and message.sent_at is not None
            and (channel is None or message.channel == channel)
        ),
        default=None,
    )