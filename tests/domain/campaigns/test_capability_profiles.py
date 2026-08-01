import pytest

from app.domain.campaigns import (
    CAPABILITY_PROFILES,
    CapabilityProfileOverride,
    CapabilityProfileOverrideError,
    CapabilityProfileResolutionReason,
    CapabilityProfileResolutionStatus,
    resolve_capability_profile,
    validate_capability_profile_override,
)
from app.domain.leads import PausedSearchReasonCode


def test_every_pause_reason_has_one_code_defined_profile() -> None:
    assert set(CAPABILITY_PROFILES) == set(PausedSearchReasonCode)
    assert all(profile.profile_version == 1 for profile in CAPABILITY_PROFILES.values())


@pytest.mark.parametrize("reason_code", tuple(PausedSearchReasonCode))
def test_single_reason_resolves_to_profile(reason_code: PausedSearchReasonCode) -> None:
    resolution = resolve_capability_profile((reason_code,))

    assert resolution.status == CapabilityProfileResolutionStatus.RESOLVED
    assert resolution.reason == CapabilityProfileResolutionReason.RESOLVED
    assert resolution.profile is not None
    assert resolution.profile.reason_code == reason_code


def test_competing_reasons_are_held_without_choosing_strictest_profile() -> None:
    resolution = resolve_capability_profile(
        (
            PausedSearchReasonCode.TIMING_NOT_RIGHT,
            PausedSearchReasonCode.WAITING_FOR_RATES,
        )
    )

    assert resolution.status == CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW
    assert resolution.reason == CapabilityProfileResolutionReason.COMPETING_REASONS
    assert resolution.profile is None


def test_missing_or_ambiguous_reason_is_held_for_review() -> None:
    missing = resolve_capability_profile(())
    ambiguous = resolve_capability_profile(
        (PausedSearchReasonCode.TIMING_NOT_RIGHT,), ambiguous=True
    )

    assert missing.reason == CapabilityProfileResolutionReason.MISSING_REASON
    assert ambiguous.reason == CapabilityProfileResolutionReason.AMBIGUOUS_REASON
    assert missing.status == CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW
    assert ambiguous.status == CapabilityProfileResolutionStatus.HOLD_FOR_REVIEW


def test_override_may_only_tighten_profile_limits_and_retain_safety_tags() -> None:
    profile = CAPABILITY_PROFILES[PausedSearchReasonCode.WAITING_FOR_RATES]
    errors = validate_capability_profile_override(
        profile,
        CapabilityProfileOverride(
            min_recurring_interval_days=45,
            max_recurring_interval_days=60,
            max_total_touches=4,
            max_duration_days=180,
            required_safety_tags=profile.required_safety_tags,
        ),
    )

    assert errors == ()


def test_override_cannot_relax_maximums_or_remove_safety_tags() -> None:
    profile = CAPABILITY_PROFILES[PausedSearchReasonCode.WAITING_FOR_RATES]
    errors = validate_capability_profile_override(
        profile,
        CapabilityProfileOverride(
            min_recurring_interval_days=15,
            max_recurring_interval_days=120,
            max_total_touches=7,
            max_duration_days=730,
            required_safety_tags=("no_prohibited_advice",),
        ),
    )

    assert errors == (
        CapabilityProfileOverrideError.MIN_INTERVAL_TOO_SHORT,
        CapabilityProfileOverrideError.MAX_INTERVAL_TOO_LONG,
        CapabilityProfileOverrideError.MAX_TOUCHES_EXCEEDED,
        CapabilityProfileOverrideError.MAX_DURATION_EXCEEDED,
        CapabilityProfileOverrideError.REQUIRED_SAFETY_TAG_REMOVED,
    )
