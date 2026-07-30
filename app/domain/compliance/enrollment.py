from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.compliance.contactability import (
    ContactabilityDecision,
    ContactChannel,
)


class EnrollmentSource(StrEnum):
    NONE = "none"
    CRM_TAG = "crm_tag"
    DORMANT_SELECTOR = "dormant_selector"
    UNSUPPORTED = "unsupported"


class EnrollmentReasonCode(StrEnum):
    MISSING_ENROLLMENT_TRIGGER = "missing_enrollment_trigger"
    UNSUPPORTED_ENROLLMENT_SOURCE = "unsupported_enrollment_source"
    LEAD_NOT_DORMANT = "lead_not_dormant"
    ACTIVITY_DATA_INCOMPLETE = "activity_data_incomplete"
    NO_CAMPAIGN_CHANNELS_CONTACTABLE = "no_campaign_channels_contactable"


def _default_allowed_sources() -> frozenset[EnrollmentSource]:
    return frozenset({EnrollmentSource.CRM_TAG, EnrollmentSource.DORMANT_SELECTOR})


@dataclass(frozen=True)
class CampaignEnrollmentFacts:
    enrollment_sources: frozenset[EnrollmentSource]
    enrollment_tag_observed_at: datetime | None = None
    last_meaningful_communication_at: datetime | None = None
    activity_data_complete: bool | None = None
    enabled_channels: frozenset[ContactChannel] = field(default_factory=frozenset)
    channel_contactability: Mapping[ContactChannel, ContactabilityDecision] = field(
        default_factory=dict,
    )


@dataclass(frozen=True)
class CampaignEnrollmentPolicy:
    allowed_sources: frozenset[EnrollmentSource] = field(
        default_factory=_default_allowed_sources,
    )
    dormant_threshold_days: int = 60


@dataclass(frozen=True)
class CampaignEnrollmentDecision:
    eligible: bool
    source: EnrollmentSource
    eligible_at: datetime | None = None
    reasons: tuple[EnrollmentReasonCode, ...] = ()


def evaluate_campaign_enrollment(
    facts: CampaignEnrollmentFacts,
    policy: CampaignEnrollmentPolicy,
    now: datetime,
) -> CampaignEnrollmentDecision:
    unsupported = facts.enrollment_sources - policy.allowed_sources
    if unsupported:
        return CampaignEnrollmentDecision(
            eligible=False,
            source=EnrollmentSource.UNSUPPORTED,
            reasons=(EnrollmentReasonCode.UNSUPPORTED_ENROLLMENT_SOURCE,),
        )

    if EnrollmentSource.CRM_TAG in facts.enrollment_sources:
        return _evaluate_with_source(
            facts=facts,
            source=EnrollmentSource.CRM_TAG,
            eligible_at=facts.enrollment_tag_observed_at,
        )

    if EnrollmentSource.DORMANT_SELECTOR in facts.enrollment_sources:
        return _evaluate_dormant_selector(facts, policy, now)

    return CampaignEnrollmentDecision(
        eligible=False,
        source=EnrollmentSource.NONE,
        reasons=(EnrollmentReasonCode.MISSING_ENROLLMENT_TRIGGER,),
    )


def _evaluate_with_source(
    facts: CampaignEnrollmentFacts,
    source: EnrollmentSource,
    eligible_at: datetime | None,
) -> CampaignEnrollmentDecision:
    if not facts.enabled_channels:
        return CampaignEnrollmentDecision(
            eligible=False,
            source=source,
            reasons=(EnrollmentReasonCode.NO_CAMPAIGN_CHANNELS_CONTACTABLE,),
        )

    for channel in facts.enabled_channels:
        contactability = facts.channel_contactability.get(channel)
        if contactability is not None and contactability.allowed:
            return CampaignEnrollmentDecision(
                eligible=True,
                source=source,
                eligible_at=eligible_at,
            )

    return CampaignEnrollmentDecision(
        eligible=False,
        source=source,
        reasons=(EnrollmentReasonCode.NO_CAMPAIGN_CHANNELS_CONTACTABLE,),
    )


def _evaluate_dormant_selector(
    facts: CampaignEnrollmentFacts,
    policy: CampaignEnrollmentPolicy,
    now: datetime,
) -> CampaignEnrollmentDecision:
    if facts.activity_data_complete is not True:
        return CampaignEnrollmentDecision(
            eligible=False,
            source=EnrollmentSource.DORMANT_SELECTOR,
            reasons=(EnrollmentReasonCode.ACTIVITY_DATA_INCOMPLETE,),
        )

    if facts.last_meaningful_communication_at is None:
        return CampaignEnrollmentDecision(
            eligible=False,
            source=EnrollmentSource.DORMANT_SELECTOR,
            reasons=(EnrollmentReasonCode.ACTIVITY_DATA_INCOMPLETE,),
        )

    days_since_last = (now - facts.last_meaningful_communication_at).days
    if days_since_last < policy.dormant_threshold_days:
        return CampaignEnrollmentDecision(
            eligible=False,
            source=EnrollmentSource.DORMANT_SELECTOR,
            reasons=(EnrollmentReasonCode.LEAD_NOT_DORMANT,),
        )

    eligible_at = facts.last_meaningful_communication_at + timedelta(
        days=policy.dormant_threshold_days,
    )

    return _evaluate_with_source(
        facts=facts,
        source=EnrollmentSource.DORMANT_SELECTOR,
        eligible_at=eligible_at,
    )


def sort_enrollment_candidates_fifo(
    decisions: Iterable[CampaignEnrollmentDecision],
) -> tuple[CampaignEnrollmentDecision, ...]:
    eligible: list[CampaignEnrollmentDecision] = [
        d for d in decisions if d.eligible and d.eligible_at is not None
    ]

    def _eligible_at(d: CampaignEnrollmentDecision) -> datetime:
        assert d.eligible_at is not None
        return d.eligible_at

    return tuple(sorted(eligible, key=_eligible_at))
