from uuid import UUID

from app.domain.outbound_drafting import (
    DormantCallToAction,
    DormantGreeting,
    DormantMessageLength,
    DormantMessageTone,
    DormantSignOff,
    DormantStepTemplateProfile,
    WorkspaceOutboundDraftingConfig,
    apply_dormant_step_template_profile,
    dormant_step_template_profile_from_mapping,
    dormant_step_template_profile_to_mapping,
    dormant_template_profile_is_valid_for_channel,
)

WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_profile_composes_validated_prompt_and_wrapper() -> None:
    profile = DormantStepTemplateProfile(
        tone=DormantMessageTone.PROFESSIONAL,
        length=DormantMessageLength.MODERATE,
        call_to_action=DormantCallToAction.ASK_IF_PLANS_CHANGED,
        greeting=DormantGreeting.HELLO_FIRST_NAME,
        sign_off=DormantSignOff.BEST_BROKERAGE,
    )

    result = apply_dormant_step_template_profile(
        WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        profile,
        channel="email",
    )

    assert "Tone: professional" in result.email_prompt_text
    assert "ask whether their plans have changed" in result.email_prompt_text
    assert result.email_template == (
        "Hello {{lead_first_name}},\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}"
    )


def test_profile_mapping_round_trip_is_stable() -> None:
    profile = DormantStepTemplateProfile(custom_instructions="Avoid exclamation marks.")

    result = dormant_step_template_profile_from_mapping(
        dormant_step_template_profile_to_mapping(profile)
    )

    assert result == profile


def test_detailed_length_is_rejected_for_sms() -> None:
    profile = DormantStepTemplateProfile(length=DormantMessageLength.DETAILED)

    assert dormant_template_profile_is_valid_for_channel(profile, channel="sms") is False
    assert dormant_template_profile_is_valid_for_channel(profile, channel="email") is True


def test_custom_sign_off_renders_admin_text_in_template() -> None:
    profile = DormantStepTemplateProfile(
        greeting=DormantGreeting.HI_THERE,
        sign_off=DormantSignOff.CUSTOM,
        custom_sign_off_text="Best regards,\nThe Miller Schackman Team",
    )

    result = apply_dormant_step_template_profile(
        WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        profile,
        channel="email",
    )

    assert result.email_template == (
        "Hi there,\n\n{{message_body}}\n\nBest regards,\nThe Miller Schackman Team"
    )


def test_custom_sign_off_mapping_round_trip_is_stable() -> None:
    profile = DormantStepTemplateProfile(
        sign_off=DormantSignOff.CUSTOM,
        custom_sign_off_text="Warmly,\n{{agent_name}}",
    )

    result = dormant_step_template_profile_from_mapping(
        dormant_step_template_profile_to_mapping(profile)
    )

    assert result == profile


def test_custom_sign_off_requires_text() -> None:
    profile = DormantStepTemplateProfile(sign_off=DormantSignOff.CUSTOM)

    assert dormant_template_profile_is_valid_for_channel(profile, channel="email") is False
    assert dormant_template_profile_is_valid_for_channel(profile, channel="sms") is False


def test_custom_sign_off_rejects_oversized_or_unknown_placeholders() -> None:
    too_long = DormantStepTemplateProfile(
        sign_off=DormantSignOff.CUSTOM,
        custom_sign_off_text="x" * 301,
    )
    unknown_placeholder = DormantStepTemplateProfile(
        sign_off=DormantSignOff.CUSTOM,
        custom_sign_off_text="Bye,\n{{message_body}}",
    )
    valid = DormantStepTemplateProfile(
        sign_off=DormantSignOff.CUSTOM,
        custom_sign_off_text="Best,\n{{brokerage_name}}",
    )

    assert dormant_template_profile_is_valid_for_channel(too_long, channel="email") is False
    assert (
        dormant_template_profile_is_valid_for_channel(unknown_placeholder, channel="email")
        is False
    )
    assert dormant_template_profile_is_valid_for_channel(valid, channel="email") is True