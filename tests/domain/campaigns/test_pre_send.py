from datetime import datetime, timedelta
from typing import Final

from app.domain.campaigns.pre_send import (
    PreSendFacts,
    PreSendPolicy,
    PreSendReasonCode,
    ProviderSendStatus,
    ScheduledMessageStatus,
    WorkflowState,
    evaluate_pre_send_safety,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactabilityDecision, ContactChannel

NOW = datetime(2026, 7, 6, 12, 0, 0)
USE_DEFAULT_CONTACTABILITY: Final = object()


def _policy(
    *,
    allowed_send_start_hour: int = 10,
    allowed_send_end_hour: int = 17,
    global_frequency_limit_hours: int | None = 24,
    campaign_frequency_limit_hours: int | None = None,
    channel_frequency_limit_hours: int | None = None,
    allow_simultaneous_channels: bool = False,
    simultaneous_channel_window_minutes: int = 0,
    timezone: str | None = None,
) -> PreSendPolicy:
    return PreSendPolicy(
        allowed_send_start_hour=allowed_send_start_hour,
        allowed_send_end_hour=allowed_send_end_hour,
        global_frequency_limit_hours=global_frequency_limit_hours,
        campaign_frequency_limit_hours=campaign_frequency_limit_hours,
        channel_frequency_limit_hours=channel_frequency_limit_hours,
        allow_simultaneous_channels=allow_simultaneous_channels,
        simultaneous_channel_window_minutes=simultaneous_channel_window_minutes,
        timezone=timezone,
    )


def _contactability(
    *,
    channel: ContactChannel = ContactChannel.SMS,
    allowed: bool = True,
) -> ContactabilityDecision:
    return ContactabilityDecision(allowed=allowed, channel=channel)


def _facts(
    *,
    channel: ContactChannel = ContactChannel.SMS,
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    workflow_state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    message_status: ScheduledMessageStatus = ScheduledMessageStatus.PENDING,
    provider_send_status: ProviderSendStatus = ProviderSendStatus.NOT_ATTEMPTED,
    scheduled_message_version: int = 1,
    current_message_version: int = 1,
    idempotency_key_already_used: bool = False,
    channel_enabled: bool = True,
    contactability_decision: ContactabilityDecision | None | object = USE_DEFAULT_CONTACTABILITY,
    preflight_vetoed: bool = False,
    handoff_active: bool = False,
    human_owned: bool = False,
    lead_replied_since_scheduled: bool = False,
    recent_human_activity: bool = False,
    last_global_outreach_at: datetime | None = None,
    last_campaign_outreach_at: datetime | None = None,
    last_channel_outreach_at: datetime | None = None,
    other_channel_sent_at: datetime | None = None,
) -> PreSendFacts:
    resolved_contactability: ContactabilityDecision | None
    if contactability_decision is USE_DEFAULT_CONTACTABILITY:
        resolved_contactability = _contactability(channel=channel)
    else:
        assert (
            isinstance(contactability_decision, ContactabilityDecision)
            or contactability_decision is None
        )
        resolved_contactability = contactability_decision

    return PreSendFacts(
        channel=channel,
        campaign_status=campaign_status,
        workflow_state=workflow_state,
        message_status=message_status,
        provider_send_status=provider_send_status,
        scheduled_message_version=scheduled_message_version,
        current_message_version=current_message_version,
        idempotency_key_already_used=idempotency_key_already_used,
        channel_enabled=channel_enabled,
        contactability_decision=resolved_contactability,
        preflight_vetoed=preflight_vetoed,
        handoff_active=handoff_active,
        human_owned=human_owned,
        lead_replied_since_scheduled=lead_replied_since_scheduled,
        recent_human_activity=recent_human_activity,
        last_global_outreach_at=last_global_outreach_at,
        last_campaign_outreach_at=last_campaign_outreach_at,
        last_channel_outreach_at=last_channel_outreach_at,
        other_channel_sent_at=other_channel_sent_at,
    )


def test_send_is_allowed_when_all_checks_pass() -> None:
    decision = evaluate_pre_send_safety(_facts(), _policy(), NOW)

    assert decision.allowed is True
    assert decision.reasons == ()
    assert decision.next_allowed_at is None


def test_inactive_campaign_blocks_sending() -> None:
    decision = evaluate_pre_send_safety(
        _facts(campaign_status=CampaignStatus.PAUSED),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.CAMPAIGN_NOT_ACTIVE,)


def test_non_sendable_workflow_state_blocks_sending() -> None:
    decision = evaluate_pre_send_safety(
        _facts(workflow_state=WorkflowState.PAUSED),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.WORKFLOW_NOT_SENDABLE,)


def test_already_sent_message_blocks_duplicate_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(message_status=ScheduledMessageStatus.SENT),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.MESSAGE_ALREADY_SENT,)


def test_reused_idempotency_key_blocks_duplicate_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(idempotency_key_already_used=True),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.DUPLICATE_SEND_REQUEST,)


def test_stale_message_version_blocks_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(scheduled_message_version=1, current_message_version=2),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.MESSAGE_VERSION_STALE,)


def test_uncertain_provider_status_blocks_retry() -> None:
    decision = evaluate_pre_send_safety(
        _facts(provider_send_status=ProviderSendStatus.UNCERTAIN),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.PROVIDER_STATUS_UNCERTAIN,)


def test_disabled_or_uncontactable_channel_blocks_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(channel_enabled=False, contactability_decision=_contactability(allowed=False)),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (
        PreSendReasonCode.CHANNEL_NOT_ENABLED,
        PreSendReasonCode.CHANNEL_NOT_CONTACTABLE,
    )


def test_preflight_veto_blocks_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(preflight_vetoed=True),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.PREFLIGHT_VETOED,)


def test_human_control_conditions_block_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(
            handoff_active=True,
            human_owned=True,
            lead_replied_since_scheduled=True,
            recent_human_activity=True,
        ),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (
        PreSendReasonCode.HANDOFF_ACTIVE,
        PreSendReasonCode.HUMAN_OWNED,
        PreSendReasonCode.LEAD_REPLIED_SINCE_SCHEDULED,
        PreSendReasonCode.RECENT_HUMAN_ACTIVITY,
    )


def test_outside_allowed_hours_returns_next_window_start() -> None:
    early_morning = datetime(2026, 7, 6, 8, 30, 0)

    decision = evaluate_pre_send_safety(_facts(), _policy(), early_morning)

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.OUTSIDE_ALLOWED_HOURS,)
    assert decision.next_allowed_at == datetime(2026, 7, 6, 10, 0, 0)


def test_outside_allowed_hours_uses_policy_timezone() -> None:
    from datetime import UTC

    utc_1300 = datetime(2026, 7, 6, 13, 0, 0, tzinfo=UTC)
    policy = _policy(timezone="America/Chicago")

    decision = evaluate_pre_send_safety(_facts(), policy, utc_1300)

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.OUTSIDE_ALLOWED_HOURS,)
    # 10:00 America/Chicago = 15:00 UTC on this date.
    assert decision.next_allowed_at == datetime(2026, 7, 6, 15, 0, 0, tzinfo=UTC)


def test_strictest_frequency_limit_blocks_and_returns_latest_retry_time() -> None:
    decision = evaluate_pre_send_safety(
        _facts(
            last_global_outreach_at=NOW - timedelta(hours=23),
            last_campaign_outreach_at=NOW - timedelta(hours=3),
            last_channel_outreach_at=NOW - timedelta(minutes=30),
        ),
        _policy(
            global_frequency_limit_hours=24,
            campaign_frequency_limit_hours=4,
            channel_frequency_limit_hours=2,
        ),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.FREQUENCY_LIMIT_REACHED,)
    assert decision.next_allowed_at == NOW + timedelta(hours=1, minutes=30)


def test_simultaneous_channel_protection_blocks_send() -> None:
    decision = evaluate_pre_send_safety(
        _facts(other_channel_sent_at=NOW - timedelta(minutes=30)),
        _policy(
            global_frequency_limit_hours=None,
            allow_simultaneous_channels=False,
            simultaneous_channel_window_minutes=90,
        ),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.SIMULTANEOUS_CHANNEL_NOT_ALLOWED,)
    assert decision.next_allowed_at == NOW + timedelta(minutes=60)


def test_missing_required_data_fails_safe() -> None:
    decision = evaluate_pre_send_safety(
        _facts(contactability_decision=None),
        _policy(),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (PreSendReasonCode.MISSING_REQUIRED_DATA,)


def test_multiple_blocking_reasons_follow_precedence_order() -> None:
    decision = evaluate_pre_send_safety(
        _facts(
            campaign_status=CampaignStatus.DRAFT,
            workflow_state=WorkflowState.PAUSED,
            message_status=ScheduledMessageStatus.CANCELLED,
            channel_enabled=False,
            contactability_decision=None,
            handoff_active=True,
            preflight_vetoed=True,
            last_global_outreach_at=NOW - timedelta(hours=23),
            other_channel_sent_at=NOW - timedelta(minutes=30),
        ),
        _policy(simultaneous_channel_window_minutes=90),
        NOW,
    )

    assert decision.allowed is False
    assert decision.reasons == (
        PreSendReasonCode.MISSING_REQUIRED_DATA,
        PreSendReasonCode.CAMPAIGN_NOT_ACTIVE,
        PreSendReasonCode.WORKFLOW_NOT_SENDABLE,
        PreSendReasonCode.MESSAGE_CANCELLED,
        PreSendReasonCode.CHANNEL_NOT_ENABLED,
        PreSendReasonCode.HANDOFF_ACTIVE,
        PreSendReasonCode.PREFLIGHT_VETOED,
        PreSendReasonCode.FREQUENCY_LIMIT_REACHED,
        PreSendReasonCode.SIMULTANEOUS_CHANNEL_NOT_ALLOWED,
    )
    assert decision.next_allowed_at is None
