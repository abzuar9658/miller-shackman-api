from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactabilityDecision, ContactChannel
from app.domain.workflows import WorkflowState as WorkflowState


class ScheduledMessageStatus(StrEnum):
    PENDING = "pending"
    CANCELLED = "cancelled"
    SENT = "sent"


class ProviderSendStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    ACCEPTED = "accepted"
    UNCERTAIN = "uncertain"


class PreSendReasonCode(StrEnum):
    MISSING_REQUIRED_DATA = "missing_required_data"
    CAMPAIGN_NOT_ACTIVE = "campaign_not_active"
    WORKFLOW_NOT_SENDABLE = "workflow_not_sendable"
    MESSAGE_ALREADY_SENT = "message_already_sent"
    MESSAGE_CANCELLED = "message_cancelled"
    MESSAGE_VERSION_STALE = "message_version_stale"
    DUPLICATE_SEND_REQUEST = "duplicate_send_request"
    PROVIDER_STATUS_UNCERTAIN = "provider_status_uncertain"
    CHANNEL_NOT_ENABLED = "channel_not_enabled"
    CHANNEL_NOT_CONTACTABLE = "channel_not_contactable"
    PREFLIGHT_VETOED = "preflight_vetoed"
    HANDOFF_ACTIVE = "handoff_active"
    HUMAN_OWNED = "human_owned"
    LEAD_REPLIED_SINCE_SCHEDULED = "lead_replied_since_scheduled"
    RECENT_HUMAN_ACTIVITY = "recent_human_activity"
    OUTSIDE_ALLOWED_HOURS = "outside_allowed_hours"
    SIMULTANEOUS_CHANNEL_NOT_ALLOWED = "simultaneous_channel_not_allowed"


# Timing blocks are "not now, retry after next_allowed_at" conditions — unlike
# every other reason code, they clear on their own once the window passes, so
# callers may reschedule instead of requiring a human resume.
TIMING_PRE_SEND_REASON_CODES: frozenset[PreSendReasonCode] = frozenset(
    {
        PreSendReasonCode.OUTSIDE_ALLOWED_HOURS,
        PreSendReasonCode.SIMULTANEOUS_CHANNEL_NOT_ALLOWED,
    }
)


def _default_sendable_workflow_states() -> frozenset[WorkflowState]:
    return frozenset(
        {
            WorkflowState.ACTIVE_NURTURE,
            WorkflowState.WAITING_FOR_RESPONSE,
            WorkflowState.RESPONSE_PROCESSING,
        },
    )


@dataclass(frozen=True)
class PreSendPolicy:
    sendable_workflow_states: frozenset[WorkflowState] = field(
        default_factory=_default_sendable_workflow_states,
    )
    allowed_send_start_hour: int = 10
    allowed_send_end_hour: int = 17
    allow_simultaneous_channels: bool = False
    simultaneous_channel_window_minutes: int = 0
    timezone: str | None = None


@dataclass(frozen=True)
class PreSendFacts:
    channel: ContactChannel
    campaign_status: CampaignStatus
    workflow_state: WorkflowState
    message_status: ScheduledMessageStatus
    provider_send_status: ProviderSendStatus = ProviderSendStatus.NOT_ATTEMPTED
    scheduled_message_version: int = 1
    current_message_version: int = 1
    idempotency_key_already_used: bool = False
    channel_enabled: bool = True
    contactability_decision: ContactabilityDecision | None = None
    preflight_vetoed: bool = False
    handoff_active: bool = False
    human_owned: bool = False
    lead_replied_since_scheduled: bool = False
    recent_human_activity: bool = False
    other_channel_sent_at: datetime | None = None
    history_facts_available: bool = True


@dataclass(frozen=True)
class PreSendDecision:
    allowed: bool
    channel: ContactChannel
    evaluated_at: datetime
    reasons: tuple[PreSendReasonCode, ...] = ()
    next_allowed_at: datetime | None = None


def evaluate_pre_send_safety(
    facts: PreSendFacts,
    policy: PreSendPolicy,
    now: datetime,
) -> PreSendDecision:
    reasons: list[PreSendReasonCode] = []
    local_now = _to_policy_timezone(now, policy.timezone)

    if _missing_required_data(facts):
        reasons.append(PreSendReasonCode.MISSING_REQUIRED_DATA)

    if facts.campaign_status != CampaignStatus.ACTIVE:
        reasons.append(PreSendReasonCode.CAMPAIGN_NOT_ACTIVE)

    if facts.workflow_state not in policy.sendable_workflow_states:
        reasons.append(PreSendReasonCode.WORKFLOW_NOT_SENDABLE)

    reasons.extend(_message_state_reasons(facts))
    reasons.extend(_channel_reasons(facts))
    reasons.extend(_human_control_reasons(facts))

    if facts.preflight_vetoed:
        reasons.append(PreSendReasonCode.PREFLIGHT_VETOED)

    if _is_outside_allowed_hours(local_now, policy):
        reasons.append(PreSendReasonCode.OUTSIDE_ALLOWED_HOURS)

    simultaneous_block_until = _simultaneous_block_until(facts, policy)
    if simultaneous_block_until is not None and now < simultaneous_block_until:
        reasons.append(PreSendReasonCode.SIMULTANEOUS_CHANNEL_NOT_ALLOWED)

    return PreSendDecision(
        allowed=not reasons,
        channel=facts.channel,
        evaluated_at=now,
        reasons=tuple(reasons),
        next_allowed_at=_next_allowed_at(
            reasons=reasons,
            policy=policy,
            now=now,
            local_now=local_now,
            simultaneous_block_until=simultaneous_block_until,
        ),
    )


def _missing_required_data(facts: PreSendFacts) -> bool:
    return (
        not facts.history_facts_available
        or facts.contactability_decision is None
        or facts.contactability_decision.channel != facts.channel
    )


def _message_state_reasons(facts: PreSendFacts) -> list[PreSendReasonCode]:
    reasons: list[PreSendReasonCode] = []

    if facts.message_status == ScheduledMessageStatus.CANCELLED:
        reasons.append(PreSendReasonCode.MESSAGE_CANCELLED)

    if facts.message_status == ScheduledMessageStatus.SENT:
        reasons.append(PreSendReasonCode.MESSAGE_ALREADY_SENT)
    elif facts.provider_send_status == ProviderSendStatus.ACCEPTED:
        reasons.append(PreSendReasonCode.MESSAGE_ALREADY_SENT)

    if facts.scheduled_message_version != facts.current_message_version:
        reasons.append(PreSendReasonCode.MESSAGE_VERSION_STALE)

    if facts.idempotency_key_already_used:
        reasons.append(PreSendReasonCode.DUPLICATE_SEND_REQUEST)

    if facts.provider_send_status == ProviderSendStatus.UNCERTAIN:
        reasons.append(PreSendReasonCode.PROVIDER_STATUS_UNCERTAIN)

    return reasons


def _channel_reasons(facts: PreSendFacts) -> list[PreSendReasonCode]:
    reasons: list[PreSendReasonCode] = []

    if not facts.channel_enabled:
        reasons.append(PreSendReasonCode.CHANNEL_NOT_ENABLED)

    if facts.contactability_decision is not None and not facts.contactability_decision.allowed:
        reasons.append(PreSendReasonCode.CHANNEL_NOT_CONTACTABLE)

    return reasons


def _human_control_reasons(facts: PreSendFacts) -> list[PreSendReasonCode]:
    reasons: list[PreSendReasonCode] = []

    if facts.handoff_active:
        reasons.append(PreSendReasonCode.HANDOFF_ACTIVE)
    if facts.human_owned:
        reasons.append(PreSendReasonCode.HUMAN_OWNED)
    if facts.lead_replied_since_scheduled:
        reasons.append(PreSendReasonCode.LEAD_REPLIED_SINCE_SCHEDULED)
    if facts.recent_human_activity:
        reasons.append(PreSendReasonCode.RECENT_HUMAN_ACTIVITY)

    return reasons


def _simultaneous_block_until(
    facts: PreSendFacts,
    policy: PreSendPolicy,
) -> datetime | None:
    if (
        policy.allow_simultaneous_channels
        or facts.other_channel_sent_at is None
        or policy.simultaneous_channel_window_minutes <= 0
    ):
        return None
    return facts.other_channel_sent_at + timedelta(
        minutes=policy.simultaneous_channel_window_minutes,
    )


def _is_outside_allowed_hours(now: datetime, policy: PreSendPolicy) -> bool:
    return not (policy.allowed_send_start_hour <= now.hour < policy.allowed_send_end_hour)


def _next_allowed_at(
    *,
    reasons: list[PreSendReasonCode],
    policy: PreSendPolicy,
    now: datetime,
    local_now: datetime,
    simultaneous_block_until: datetime | None,
) -> datetime | None:
    if not reasons or any(
        reason not in TIMING_PRE_SEND_REASON_CODES for reason in reasons
    ):
        return None

    candidate = now
    if simultaneous_block_until is not None and candidate < simultaneous_block_until:
        candidate = simultaneous_block_until
    local_candidate = _to_policy_timezone(candidate, policy.timezone)
    local_candidate = _roll_forward_to_allowed_window(local_candidate, policy)
    return _from_policy_timezone(local_candidate, policy.timezone)


def _roll_forward_to_allowed_window(now: datetime, policy: PreSendPolicy) -> datetime:
    start_of_window = now.replace(
        hour=policy.allowed_send_start_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now.hour < policy.allowed_send_start_hour:
        return start_of_window
    if now.hour >= policy.allowed_send_end_hour:
        return start_of_window + timedelta(days=1)
    return now


def _to_policy_timezone(now: datetime, timezone: str | None) -> datetime:
    if timezone is None:
        return now
    tz = ZoneInfo(timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC).astimezone(tz)
    return now.astimezone(tz)


def _from_policy_timezone(local_now: datetime, timezone: str | None) -> datetime:
    if timezone is None or local_now.tzinfo is None:
        return local_now
    return local_now.astimezone(UTC)
