from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.application.ports.repositories import OutboundMessageRepository
from app.application.services.email_threading import (
    resolve_lead_email_threading_headers,
    resolve_reply_email_subject,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    build_outbound_email_message_id,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import InboundMessage, InboundMessageClassificationStatus

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
INBOUND_ID = UUID("00000000-0000-0000-0000-000000000005")
PRIOR_OUTBOUND_ID = UUID("00000000-0000-0000-0000-000000000006")
CURRENT_OUTBOUND_ID = UUID("00000000-0000-0000-0000-000000000007")


class FakeInboundMessageRepository:
    def __init__(self, messages: tuple[InboundMessage, ...]) -> None:
        self.messages = messages

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> InboundMessage | None:
        for message in self.messages:
            if (
                message.workspace_id == workspace_id
                and message.inbound_message_id == inbound_message_id
            ):
                return message
        return None

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[InboundMessage, ...]:
        matches = [
            message
            for message in self.messages
            if message.workspace_id == workspace_id and message.lead_id == lead_id
        ]
        return tuple(sorted(matches, key=lambda message: message.received_at, reverse=True)[:limit])

    async def save(self, message: InboundMessage) -> InboundMessage:
        raise NotImplementedError


class FakeOutboundMessageRepository:
    def __init__(self, messages: tuple[OutboundMessage, ...]) -> None:
        self.messages = messages

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        matches = [
            message
            for message in self.messages
            if message.workspace_id == workspace_id and message.lead_id == lead_id
        ]
        return tuple(sorted(matches, key=lambda message: message.created_at, reverse=True)[:limit])


def _inbound_message() -> InboundMessage:
    return InboundMessage(
        inbound_message_id=INBOUND_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        lead_id=LEAD_ID,
        channel=ContactChannel.EMAIL,
        provider="mailgun",
        provider_message_id="<lead-message@example.com>",
        body="Can you send more details?",
        received_at=NOW,
        classification_status=InboundMessageClassificationStatus.CLASSIFIED,
        created_at=NOW,
    )


def _outbound_message(message_id: UUID, *, status: OutboundMessageStatus) -> OutboundMessage:
    occurred_at = NOW.replace(hour=11)
    return OutboundMessage(
        message_id=message_id,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="step-1",
        channel=ContactChannel.EMAIL,
        status=status,
        idempotency_key=f"message:{message_id}",
        body="Checking in.",
        subject="Quick check-in",
        created_at=occurred_at,
        updated_at=occurred_at,
        sent_at=occurred_at if status == OutboundMessageStatus.SENT else None,
    )


async def test_resolves_current_inbound_email_as_thread_anchor() -> None:
    prior_outbound_id = build_outbound_email_message_id(PRIOR_OUTBOUND_ID)

    headers = await resolve_lead_email_threading_headers(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        inbound_message_repository=FakeInboundMessageRepository((_inbound_message(),)),
        message_repository=cast(
            OutboundMessageRepository,
            FakeOutboundMessageRepository(
                (_outbound_message(PRIOR_OUTBOUND_ID, status=OutboundMessageStatus.SENT),)
            ),
        ),
        anchor_inbound_message_id=INBOUND_ID,
        current_outbound_message_id=CURRENT_OUTBOUND_ID,
    )

    assert headers.in_reply_to_message_id == "lead-message@example.com"
    assert headers.reference_message_ids == (prior_outbound_id, "lead-message@example.com")


async def test_resolves_latest_sent_outbound_email_when_no_inbound_exists() -> None:
    prior_outbound_id = build_outbound_email_message_id(PRIOR_OUTBOUND_ID)

    headers = await resolve_lead_email_threading_headers(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        inbound_message_repository=None,
        message_repository=cast(
            OutboundMessageRepository,
            FakeOutboundMessageRepository(
                (_outbound_message(PRIOR_OUTBOUND_ID, status=OutboundMessageStatus.SENT),)
            ),
        ),
        current_outbound_message_id=CURRENT_OUTBOUND_ID,
    )

    assert headers.in_reply_to_message_id == prior_outbound_id
    assert headers.reference_message_ids == (prior_outbound_id,)


def test_resolve_reply_email_subject_uses_inbound_subject_for_email_reply() -> None:
    assert (
        resolve_reply_email_subject(
            inbound_channel=ContactChannel.EMAIL,
            inbound_email_subject="Re: Downtown condo inquiry",
            drafted_subject="Quick follow-up",
        )
        == "Re: Downtown condo inquiry"
    )


def test_resolve_reply_email_subject_falls_back_to_drafted_subject_for_email() -> None:
    assert (
        resolve_reply_email_subject(
            inbound_channel=ContactChannel.EMAIL,
            inbound_email_subject=None,
            drafted_subject="Quick follow-up",
        )
        == "Quick follow-up"
    )


def test_resolve_reply_email_subject_falls_back_to_drafted_subject_for_sms() -> None:
    assert (
        resolve_reply_email_subject(
            inbound_channel=ContactChannel.SMS,
            inbound_email_subject="Re: Downtown condo inquiry",
            drafted_subject=None,
        )
        is None
    )


def test_resolve_reply_email_subject_ignores_whitespace_only_inbound_subject() -> None:
    assert (
        resolve_reply_email_subject(
            inbound_channel=ContactChannel.EMAIL,
            inbound_email_subject="   ",
            drafted_subject="Quick follow-up",
        )
        == "Quick follow-up"
    )
