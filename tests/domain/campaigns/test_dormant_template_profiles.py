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