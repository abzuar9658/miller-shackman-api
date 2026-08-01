from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.domain.leads import PausedSearchReasonCode


class CapabilityProfileResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    HOLD_FOR_REVIEW = "hold_for_review"


class CapabilityProfileResolutionReason(StrEnum):
    RESOLVED = "resolved"
    MISSING_REASON = "missing_reason"
    AMBIGUOUS_REASON = "ambiguous_reason"
    COMPETING_REASONS = "competing_reasons"


class CapabilityProfileOverrideError(StrEnum):
    MIN_INTERVAL_TOO_SHORT = "min_interval_too_short"
    MAX_INTERVAL_TOO_LONG = "max_interval_too_long"
    INTERVAL_RANGE_INVALID = "interval_range_invalid"
    MAX_TOUCHES_EXCEEDED = "max_touches_exceeded"
    MAX_DURATION_EXCEEDED = "max_duration_exceeded"
    REQUIRED_SAFETY_TAG_REMOVED = "required_safety_tag_removed"


@dataclass(frozen=True)
class CapabilityProfile:
    profile_key: str
    profile_version: int
    reason_code: PausedSearchReasonCode
    min_recurring_interval_days: int
    max_recurring_interval_days: int
    max_total_touches: int
    max_duration_days: int
    required_safety_tags: tuple[str, ...]
    restriction: str


@dataclass(frozen=True)
class CapabilityProfileResolution:
    status: CapabilityProfileResolutionStatus
    reason: CapabilityProfileResolutionReason
    profile: CapabilityProfile | None = None
    reason_codes: tuple[PausedSearchReasonCode, ...] = ()


@dataclass(frozen=True)
class CapabilityProfileOverride:
    min_recurring_interval_days: int | None = None
    max_recurring_interval_days: int | None = None
    max_total_touches: int | None = None
    max_duration_days: int | None = None
    required_safety_tags: tuple[str, ...] | None = None


def _profile(
    reason_code: PausedSearchReasonCode,
    *,
    min_interval: int,
    max_interval: int,
    max_touches: int,
    max_duration: int,
    restriction: str,
    required_safety_tags: tuple[str, ...] = ("no_prohibited_advice",),
) -> CapabilityProfile:
    return CapabilityProfile(
        profile_key=f"paused_search.{reason_code.value}",
        profile_version=1,
        reason_code=reason_code,
        min_recurring_interval_days=min_interval,
        max_recurring_interval_days=max_interval,
        max_total_touches=max_touches,
        max_duration_days=max_duration,
        required_safety_tags=required_safety_tags,
        restriction=restriction,
    )


CAPABILITY_PROFILES: Final[dict[PausedSearchReasonCode, CapabilityProfile]] = {
    PausedSearchReasonCode.RENTED_TEMPORARILY: _profile(
        PausedSearchReasonCode.RENTED_TEMPORARILY,
        min_interval=30,
        max_interval=180,
        max_touches=5,
        max_duration=730,
        restriction="prefer_customer_or_lease_date",
    ),
    PausedSearchReasonCode.TIMING_NOT_RIGHT: _profile(
        PausedSearchReasonCode.TIMING_NOT_RIGHT,
        min_interval=30,
        max_interval=180,
        max_touches=4,
        max_duration=365,
        restriction="generic_low_pressure_messages",
    ),
    PausedSearchReasonCode.WAITING_FOR_RATES: _profile(
        PausedSearchReasonCode.WAITING_FOR_RATES,
        min_interval=30,
        max_interval=90,
        max_touches=6,
        max_duration=365,
        restriction="no_rate_predictions_or_financial_advice",
        required_safety_tags=("no_financial_advice", "no_prohibited_advice"),
    ),
    PausedSearchReasonCode.WAITING_FOR_INVENTORY: _profile(
        PausedSearchReasonCode.WAITING_FOR_INVENTORY,
        min_interval=14,
        max_interval=60,
        max_touches=6,
        max_duration=180,
        restriction="approved_fresh_listing_context_only",
        required_safety_tags=("listing_context_allowed", "no_prohibited_advice"),
    ),
    PausedSearchReasonCode.FINANCIAL_PREP: _profile(
        PausedSearchReasonCode.FINANCIAL_PREP,
        min_interval=30,
        max_interval=90,
        max_touches=6,
        max_duration=365,
        restriction="no_mortgage_credit_tax_or_investment_advice",
        required_safety_tags=("no_financial_advice", "no_prohibited_advice"),
    ),
    PausedSearchReasonCode.PERSONAL_LIFE_TIMING: _profile(
        PausedSearchReasonCode.PERSONAL_LIFE_TIMING,
        min_interval=60,
        max_interval=180,
        max_touches=4,
        max_duration=730,
        restriction="respectful_content_no_sensitive_assumptions",
    ),
    PausedSearchReasonCode.OTHER_KNOWN_PAUSE: _profile(
        PausedSearchReasonCode.OTHER_KNOWN_PAUSE,
        min_interval=60,
        max_interval=180,
        max_touches=4,
        max_duration=365,
        restriction="generic_content_review_unclear_timing",
    ),
}


def capability_profile_for_reason(
    reason_code: PausedSearchReasonCode,
) -> CapabilityProfile | None:
    return CAPABILITY_PROFILES.get(reason_code)


def resolve_capability_profile(
    reason_codes: tuple[PausedSearchReasonCode, ...],
    *,
    ambiguous: bool = False,
) -> CapabilityProfileResolution:
    if ambiguous:
        return CapabilityProfileResolution(
            status=CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW,
            reason=CapabilityProfileResolutionReason.AMBIGUOUS_REASON,
            reason_codes=reason_codes,
        )
    if not reason_codes:
        return CapabilityProfileResolution(
            status=CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW,
            reason=CapabilityProfileResolutionReason.MISSING_REASON,
        )
    if len(reason_codes) != 1:
        return CapabilityProfileResolution(
            status=CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW,
            reason=CapabilityProfileResolutionReason.COMPETING_REASONS,
            reason_codes=reason_codes,
        )

    profile = capability_profile_for_reason(reason_codes[0])
    if profile is None:
        return CapabilityProfileResolution(
            status=CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW,
            reason=CapabilityProfileResolutionReason.MISSING_REASON,
            reason_codes=reason_codes,
        )
    return CapabilityProfileResolution(
        status=CapabilityProfileResolutionStatus.RESOLVED,
        reason=CapabilityProfileResolutionReason.RESOLVED,
        profile=profile,
        reason_codes=reason_codes,
    )


def validate_capability_profile_override(
    profile: CapabilityProfile,
    override: CapabilityProfileOverride,
) -> tuple[CapabilityProfileOverrideError, ...]:
    errors: list[CapabilityProfileOverrideError] = []
    min_interval = (
        override.min_recurring_interval_days
        if override.min_recurring_interval_days is not None
        else profile.min_recurring_interval_days
    )
    max_interval = (
        override.max_recurring_interval_days
        if override.max_recurring_interval_days is not None
        else profile.max_recurring_interval_days
    )

    if min_interval < profile.min_recurring_interval_days:
        errors.append(CapabilityProfileOverrideError.MIN_INTERVAL_TOO_SHORT)
    if max_interval > profile.max_recurring_interval_days:
        errors.append(CapabilityProfileOverrideError.MAX_INTERVAL_TOO_LONG)
    if min_interval > max_interval:
        errors.append(CapabilityProfileOverrideError.INTERVAL_RANGE_INVALID)
    if (
        override.max_total_touches is not None
        and override.max_total_touches > profile.max_total_touches
    ):
        errors.append(CapabilityProfileOverrideError.MAX_TOUCHES_EXCEEDED)
    if (
        override.max_duration_days is not None
        and override.max_duration_days > profile.max_duration_days
    ):
        errors.append(CapabilityProfileOverrideError.MAX_DURATION_EXCEEDED)
    if override.required_safety_tags is not None and not set(profile.required_safety_tags).issubset(
        override.required_safety_tags
    ):
        errors.append(CapabilityProfileOverrideError.REQUIRED_SAFETY_TAG_REMOVED)
    return tuple(errors)
