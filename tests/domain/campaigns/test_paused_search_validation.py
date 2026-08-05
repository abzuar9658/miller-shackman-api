from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTerminalBehavior,
    PausedSearchTrack,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    PausedSearchValidationCode,
    PausedSearchValidationSeverity,
    validate_paused_search_track,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.template_registry import TemplateChannel, TemplateStatus, TemplateVersion
from app.domain.compliance import ContactChannel
from app.domain.outbound_drafting import DormantStepTemplateProfile

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
TRACK_ID = UUID("10000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("10000000-0000-0000-0000-000000000003")
STEP_ID = UUID("10000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000005")


def test_valid_track_is_publishable_with_structured_touch_warning() -> None:
    version = _version(max_total_touches=1)
    report = validate_paused_search_track(
        track=_track(),
        version=version,
        steps=(_step(max_occurrences=2),),
        for_publish=True,
    )

    assert report.publishable
    assert report.errors == ()
    assert [item.code for item in report.warnings] == [
        PausedSearchValidationCode.EXPECTED_TOUCHES_CAPPED
    ]
    assert report.warnings[0].severity is PausedSearchValidationSeverity.WARNING


def test_template_binding_is_required_and_must_match_step() -> None:
    template_id = UUID("10000000-0000-0000-0000-000000000009")
    step = replace(_step(), template_version_id=template_id)
    template = TemplateVersion(
        template_version_id=template_id,
        workspace_id=WORKSPACE_ID,
        template_key="different-key",
        version=1,
        channel=TemplateChannel.EMAIL,
        purpose="paused_search",
        content="{{message_body}}",
        subject="Checking in",
        prompt_text="Write a check-in.",
        allowed_variables=("message_body",),
        permitted_use_tags=(
            "no_prohibited_advice",
            "no_financial_advice",
            "no_legal_advice",
            "no_tax_advice",
            "no_investment_advice",
            "no_market_predictions",
            "no_unverified_listing_claims",
        ),
        status=TemplateStatus.APPROVED,
        approved_at=NOW,
        created_at=NOW,
    )

    report = validate_paused_search_track(
        track=_track(),
        version=_version(),
        steps=(step,),
        for_publish=True,
        templates={template_id: template},
    )

    assert not report.publishable
    assert PausedSearchValidationCode.TEMPLATE_KEY_MISMATCH in {
        finding.code for finding in report.errors
    }


def test_publish_validation_blocks_unresolved_template_binding() -> None:
    report = validate_paused_search_track(
        track=_track(),
        version=_version(),
        steps=(_step(),),
        for_publish=True,
        templates={},
    )

    assert not report.publishable
    assert report.errors[0].code is PausedSearchValidationCode.TEMPLATE_VERSION_MISSING


def test_draft_validation_blocks_unresolved_template_binding() -> None:
    report = validate_paused_search_track(
        track=_track(),
        version=_version(),
        steps=(_step(),),
        for_publish=False,
        templates={},
    )

    assert not report.publishable
    assert report.errors[0].code is PausedSearchValidationCode.TEMPLATE_VERSION_MISSING


def test_profile_based_step_does_not_require_legacy_template_binding() -> None:
    template_id = UUID("10000000-0000-0000-0000-000000000009")
    report = validate_paused_search_track(
        track=_track(),
        version=_version(),
        steps=(
            replace(
                _step(),
                template_version_id=template_id,
                template_profile=DormantStepTemplateProfile(),
            ),
        ),
        for_publish=True,
        templates={},
    )

    assert report.publishable
    assert report.errors == ()


def test_validation_reports_all_blocking_configuration_findings() -> None:
    version = replace(
        _version(),
        allowed_channels=(),
        selection_guidance="too short",
        max_total_touches=6,
        max_duration_days=20,
    )
    step = replace(
        _step(),
        step_order=2,
        channel=ContactChannel.SMS,
        delay_hours=-1,
        message_goal=" ",
        template_key=" ",
        max_attempts=0,
        max_occurrences=0,
        interval_days=7,
    )

    report = validate_paused_search_track(
        track=replace(_track(), track_key=" ", display_name=" "),
        version=version,
        steps=(step,),
        for_publish=True,
    )

    assert not report.publishable
    assert {
        PausedSearchValidationCode.EMPTY_TRACK_KEY,
        PausedSearchValidationCode.EMPTY_DISPLAY_NAME,
        PausedSearchValidationCode.NO_ALLOWED_CHANNELS,
        PausedSearchValidationCode.INVALID_SELECTION_GUIDANCE,
        PausedSearchValidationCode.INVALID_TOUCH_LIMIT,
        PausedSearchValidationCode.INVALID_DURATION,
        PausedSearchValidationCode.INVALID_STEP_ORDER,
        PausedSearchValidationCode.STEP_CHANNEL_NOT_ALLOWED,
        PausedSearchValidationCode.INVALID_STEP_DELAY,
        PausedSearchValidationCode.EMPTY_MESSAGE_GOAL,
        PausedSearchValidationCode.EMPTY_TEMPLATE_KEY,
        PausedSearchValidationCode.INVALID_MAX_ATTEMPTS,
        PausedSearchValidationCode.INVALID_MAX_OCCURRENCES,
        PausedSearchValidationCode.INVALID_RECURRING_INTERVAL,
    }.issubset({item.code for item in report.errors})


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="rented-year",
        display_name="Rented for a year",
        status=PausedSearchTrackStatus.DRAFT,
        active_version_id=None,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version(*, max_total_touches: int = 3) -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.DRAFT,
        selection_guidance="Select when a temporary renter plans to search again later.",
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=90,
        reactivation_window_days=45,
        max_total_touches=max_total_touches,
        created_by_user_id=USER_ID,
        created_at=NOW,
        terminal_behavior=PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
    )


def _step(
    *,
    interval_days: int | None = None,
    max_occurrences: int = 1,
) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=STEP_ID,
        workspace_id=WORKSPACE_ID,
        track_version_id=VERSION_ID,
        step_order=1,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        delay_hours=24,
        message_goal="Check whether plans changed.",
        template_key="paused-search-maintenance-email-1",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
        interval_days=interval_days,
        max_occurrences=max_occurrences,
    )
