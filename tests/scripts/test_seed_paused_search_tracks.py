from app.domain.campaigns import (
    PausedSearchChannelSequence,
    PausedSearchStepAction,
    PausedSearchTrackStepPhase,
)
from app.domain.compliance.contactability import ContactChannel
from scripts.seed_paused_search_tracks import TRACK_DEFINITIONS, _config


def test_seed_defines_all_six_published_track_keys() -> None:
    assert [definition.key for definition in TRACK_DEFINITIONS] == [
        "specific_property_only",
        "waiting_for_inventory",
        "renter_now_future_buyer",
        "lease_expiration",
        "recently_renewed_lease",
        "search_fit_reassessment",
    ]


def test_specific_property_guidance_separates_pause_from_current_handoff() -> None:
    definition = next(
        definition
        for definition in TRACK_DEFINITIONS
        if definition.key == "specific_property_only"
    )

    assert "not asking for a showing" in definition.selection_guidance
    assert "Current requests for property help require human handoff" in (
        definition.selection_guidance
    )


def test_each_track_has_the_five_touch_dual_channel_sequence() -> None:
    for definition in TRACK_DEFINITIONS:
        config = _config(definition)
        assert config.enabled is True
        assert config.allowed_channels == (ContactChannel.EMAIL, ContactChannel.SMS)
        assert config.channel_sequence is PausedSearchChannelSequence.SEQUENTIAL
        assert config.max_total_touches == 5
        assert config.max_cycles == 1
        assert config.max_ai_interactions == 5
        assert len(config.steps) == 5
        assert sum(step.max_occurrences for step in config.steps) == 5
        assert all(step.action is PausedSearchStepAction.SEND for step in config.steps)
        assert all(step.template_profile is not None for step in config.steps)
        assert len({step.template_key for step in config.steps}) == 5

        assert [step.phase for step in config.steps] == [
            PausedSearchTrackStepPhase.MAINTENANCE,
            PausedSearchTrackStepPhase.MAINTENANCE,
            PausedSearchTrackStepPhase.REACTIVATION,
            PausedSearchTrackStepPhase.REACTIVATION,
            PausedSearchTrackStepPhase.REACTIVATION,
        ]
        assert [step.channel for step in config.steps] == [
            ContactChannel.EMAIL,
            ContactChannel.SMS,
            ContactChannel.EMAIL,
            ContactChannel.SMS,
            ContactChannel.EMAIL,
        ]
        assert [step.delay_hours for step in config.steps] == [0, 24, 0, 24, 120]


def test_each_track_has_distinct_email_and_sms_writing_purposes() -> None:
    purposes_by_field = {
        "maintenance_email_purpose": {
            definition.maintenance_email_purpose for definition in TRACK_DEFINITIONS
        },
        "maintenance_sms_purpose": {
            definition.maintenance_sms_purpose for definition in TRACK_DEFINITIONS
        },
        "reactivation_email_purpose": {
            definition.reactivation_email_purpose for definition in TRACK_DEFINITIONS
        },
        "reactivation_sms_purpose": {
            definition.reactivation_sms_purpose for definition in TRACK_DEFINITIONS
        },
    }

    for purposes in purposes_by_field.values():
        assert len(purposes) == len(TRACK_DEFINITIONS)
        assert all("track-specific" not in purpose for purpose in purposes)