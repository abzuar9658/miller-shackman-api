from typing import Protocol, runtime_checkable

from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.leads import CanonicalLeadRecord


@runtime_checkable
class CRMConversationPublisher(Protocol):
    async def publish_outbound_message(
        self,
        *,
        lead: CanonicalLeadRecord,
        outbound_message: OutboundMessage,
    ) -> bool:
        """Publish an outbound message into the CRM conversation surface.

        Returns True when the message was published into the CRM-native
        conversation surface. Returns False when the publisher is disabled or
        the message is not eligible for that surface, allowing callers to fall
        back to note-based CRM sync.
        """
        raise NotImplementedError