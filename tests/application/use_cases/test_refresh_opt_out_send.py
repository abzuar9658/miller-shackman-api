from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from app.application.ports.repositories import LeadRepository, OutboundMessageRepository
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.use_cases.process_contact_suppression_event import (
    apply_contact_suppression_to_lead,
)
from app.application.use_cases.send_outbound_message import (
    SendOutboundMessageReasonCode,
    SendOutboundMessageResult,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.outbound_message import OutboundMessageStatus
from app.domain.campaigns.pre_send import PreSendReasonCode, ProviderSendStatus
from app.domain.compliance.contactability import (
    ContactabilityReasonCode,
    ContactChannel,
    ContactPermissionStatus,
    ContactSuppressionKind,
    SuppressionType,
    evaluate_contactability,
)
from app.domain.leads import CanonicalLeadRecord
from tests.application.use_cases._campaign_cadence_fakes import FakeLeadRepository
from tests.application.use_cases._crm_history_import_fakes import FakeCanonicalLeadRefreshSource
from tests.application.use_cases.test_send_outbound_message import (
    FakeEmailProvider,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    _crm_refresh_context,
    _lead,
    _message,
    _send_context,
)

NOW = datetime(2026, 9, 9, 14, tzinfo=UTC)


@pytest.fixture(
    params=[
        pytest.param((ContactPermissionStatus.CONFIRMED, False), id="permissive"),
        pytest.param((ContactPermissionStatus.UNKNOWN, None), id="unknown-missing-dnc"),
        pytest.param((ContactPermissionStatus.UNKNOWN, False), id="explicit-false"),
    ],
)
def crm_snapshot(request: pytest.FixtureRequest) -> CanonicalLeadRecord:
    permission, do_not_contact = cast(tuple[ContactPermissionStatus, bool | None], request.param)
    return replace(
        _lead(),
        facts_derived_at=NOW,
        lead_stage="nurture",
        primary_email="updated@example.test",
        primary_phone="+15555550160",
        sms_permission_status=permission,
        email_permission_status=permission,
        do_not_contact=do_not_contact,
    )


async def _send_with_refresh(
    repository: FakeLeadRepository,
    channel: ContactChannel,
    snapshot: CanonicalLeadRecord,
) -> tuple[SendOutboundMessageResult, FakeSMSProvider, FakeEmailProvider]:
    message = replace(
        _message(channel=channel, subject="Checking in"),
        created_at=NOW - timedelta(minutes=10),
        updated_at=NOW,
    )
    messages = FakeOutboundMessageRepository(message)
    sms_provider = FakeSMSProvider()
    email_provider = FakeEmailProvider()
    source = FakeCanonicalLeadRefreshSource({snapshot.crm_lead_id: snapshot})
    refresh_context = replace(
        _crm_refresh_context(lead=snapshot),
        lead_refresh_source=source,
    )

    result = await send_outbound_message(
        workspace_id=message.workspace_id,
        idempotency_key=message.idempotency_key,
        context=_send_context(),
        lead_repository=cast(LeadRepository, repository),
        message_repository=cast(OutboundMessageRepository, messages),
        sms_provider=sms_provider,
        email_provider=email_provider,
        crm_refresh_context=refresh_context,
        now=NOW,
    )

    assert source.calls == [(snapshot.workspace_id, snapshot.crm_lead_id, ())]
    assert result.message == await messages.get_by_id(message.workspace_id, message.message_id)
    saved = await repository.get_by_id(snapshot.workspace_id, snapshot.lead_id)
    assert saved is not None
    assert saved.lead_stage == "nurture"
    assert saved.primary_email == "updated@example.test"
    assert saved.primary_phone == "+15555550160"
    assert saved.facts_derived_at == NOW
    assert saved.sms_permission_status is snapshot.sms_permission_status
    assert saved.email_permission_status is snapshot.email_permission_status
    return result, sms_provider, email_provider


@pytest.mark.parametrize("channel", [ContactChannel.SMS, ContactChannel.EMAIL])
async def test_pre_send_refresh_dispatches_unrestricted_control(
    channel: ContactChannel,
    crm_snapshot: CanonicalLeadRecord,
) -> None:
    lead = _lead()
    repository = FakeLeadRepository(lead)

    result, sms_provider, email_provider = await _send_with_refresh(
        repository, channel, crm_snapshot,
    )

    assert result.status is SendOutboundMessageStatus.SENT
    assert result.reasons == ()
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.allowed is True
    assert result.pre_send_decision.reasons == ()
    assert result.message is not None
    assert result.message.status is OutboundMessageStatus.SENT
    assert result.message.provider_send_status is ProviderSendStatus.ACCEPTED
    assert result.message.sent_at == NOW
    if channel is ContactChannel.SMS:
        assert len(sms_provider.messages) == 1
        assert sms_provider.messages[0].to_phone == "+15555550160"
        assert email_provider.messages == []
    else:
        assert len(email_provider.messages) == 1
        assert email_provider.messages[0].to_email == "updated@example.test"
        assert sms_provider.messages == []
    saved = await repository.get_by_id(lead.workspace_id, lead.lead_id)
    assert saved is not None
    assert saved.sms_opted_out is False
    assert saved.email_unsubscribed is False
    assert saved.do_not_contact is crm_snapshot.do_not_contact
    assert saved.suppression_types == frozenset()
    assert saved.permission_evidence == {}


@pytest.mark.parametrize(
    (
        "suppression_kind", "channel", "source_provider", "expected_reason",
        "expected_flags", "expected_suppressions", "expected_evidence",
    ),
    [
        pytest.param(
            ContactSuppressionKind.SMS_OPT_OUT,
            ContactChannel.SMS,
            "twilio",
            ContactabilityReasonCode.SMS_OPTED_OUT,
            (True, False, False),
            frozenset({SuppressionType.SMS_OPT_OUT}),
            {
                "sms_opt_out_source_provider": "twilio",
                "sms_opt_out_source_event_id": "synthetic-sms_opt_out-send-16a",
                "sms_opt_out_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            id="sms",
        ),
        pytest.param(
            ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
            ContactChannel.EMAIL,
            "follow_up_boss",
            ContactabilityReasonCode.EMAIL_UNSUBSCRIBED,
            (False, True, False),
            frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
            {
                "email_unsubscribed_source_provider": "follow_up_boss",
                "email_unsubscribed_source_event_id": "synthetic-email_unsubscribed-send-16a",
                "email_unsubscribed_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            id="email",
        ),
        pytest.param(
            ContactSuppressionKind.DO_NOT_CONTACT,
            ContactChannel.SMS,
            "follow_up_boss",
            ContactabilityReasonCode.DO_NOT_CONTACT,
            (False, False, True),
            frozenset(),
            {
                "do_not_contact_source_provider": "follow_up_boss",
                "do_not_contact_source_event_id": "synthetic-do_not_contact-send-16a",
                "do_not_contact_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            id="dnc-sms",
        ),
        pytest.param(
            ContactSuppressionKind.DO_NOT_CONTACT,
            ContactChannel.EMAIL,
            "follow_up_boss",
            ContactabilityReasonCode.DO_NOT_CONTACT,
            (False, False, True),
            frozenset(),
            {
                "do_not_contact_source_provider": "follow_up_boss",
                "do_not_contact_source_event_id": "synthetic-do_not_contact-send-16a",
                "do_not_contact_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            id="dnc-email",
        ),
    ],
)
async def test_pre_send_refresh_blocks_recorded_opt_out_not_unrelated_guard(
    suppression_kind: ContactSuppressionKind,
    channel: ContactChannel,
    source_provider: str,
    expected_reason: ContactabilityReasonCode,
    expected_flags: tuple[bool, bool, bool],
    expected_suppressions: frozenset[SuppressionType],
    expected_evidence: dict[str, str],
    crm_snapshot: CanonicalLeadRecord,
) -> None:
    lead = _lead()
    repository = FakeLeadRepository(lead)
    # The real consent writer is the approved seam here, not the separate
    # workflow transition that could hide a forgotten opt-out behind a pause.
    await apply_contact_suppression_to_lead(
        lead=lead,
        suppression_kind=suppression_kind,
        source_provider=source_provider,
        source_event_id=f"synthetic-{suppression_kind.value}-send-16a",
        occurred_at=NOW - timedelta(days=1),
        lead_repository=cast(LeadRepository, repository),
    )

    result, sms_provider, email_provider = await _send_with_refresh(
        repository, channel, crm_snapshot,
    )

    assert result.status is SendOutboundMessageStatus.REJECTED
    assert result.reasons == (SendOutboundMessageReasonCode.PRE_SEND_BLOCKED,)
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.allowed is False
    assert result.pre_send_decision.reasons == (PreSendReasonCode.CHANNEL_NOT_CONTACTABLE,)
    assert result.message is not None
    assert result.message.status is OutboundMessageStatus.PENDING
    assert result.message.provider_send_status is ProviderSendStatus.NOT_ATTEMPTED
    assert result.message.sent_at is None
    assert sms_provider.messages == []
    assert email_provider.messages == []
    saved = await repository.get_by_id(lead.workspace_id, lead.lead_id)
    assert saved is not None
    assert saved.sms_opted_out is expected_flags[0]
    assert saved.email_unsubscribed is expected_flags[1]
    assert saved.do_not_contact is (True if expected_flags[2] else crm_snapshot.do_not_contact)
    assert saved.suppression_types == expected_suppressions
    assert saved.permission_evidence == expected_evidence
    decision = evaluate_contactability(contactability_facts_from_canonical_lead(saved), channel)
    assert decision.allowed is False
    assert decision.reasons == (expected_reason,)