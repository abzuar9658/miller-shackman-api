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
    render_outbound_template,
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


def test_detailed_length_overrides_default_brevity_prompt() -> None:
    profile = DormantStepTemplateProfile(length=DormantMessageLength.DETAILED)

    result = apply_dormant_step_template_profile(
        WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        profile,
        channel="email",
    )

    assert "keep it to a few short sentences" not in result.email_prompt_text
    assert "MINIMUM of 180 words" in result.email_prompt_text
    assert "overrides any earlier instruction" in result.email_prompt_text
    assert "Final length check" in result.email_prompt_text
    assert "under 180 words" in result.email_prompt_text


def test_moderate_length_is_capped_for_sms() -> None:
    profile = DormantStepTemplateProfile(length=DormantMessageLength.MODERATE)

    result = apply_dormant_step_template_profile(
        WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        profile,
        channel="sms",
    )

    assert "90 words" not in result.sms_prompt_text
    assert "45 words" in result.sms_prompt_text
    assert "under 320 characters" in result.sms_prompt_text
    assert "expand it" not in result.sms_prompt_text


def test_moderate_length_keeps_word_minimum_for_email() -> None:
    profile = DormantStepTemplateProfile(length=DormantMessageLength.MODERATE)

    result = apply_dormant_step_template_profile(
        WorkspaceOutboundDraftingConfig(workspace_id=WORKSPACE_ID),
        profile,
        channel="email",
    )

    assert "at least 90 words" in result.email_prompt_text
    assert "under 90 words" in result.email_prompt_text


def test_customized_channel_prompt_is_preserved() -> None:
    profile = DormantStepTemplateProfile(length=DormantMessageLength.DETAILED)
    custom_prompt = "Always write in the brokerage house style."

    result = apply_dormant_step_template_profile(
        WorkspaceOutboundDraftingConfig(
            workspace_id=WORKSPACE_ID,
            email_prompt_text=custom_prompt,
        ),
        profile,
        channel="email",
    )

    assert result.email_prompt_text.startswith(custom_prompt)
    assert "MINIMUM of 180 words" in result.email_prompt_text


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


RENDER_VALUES = {
    "agent_name": "Alex Agent",
    "brokerage_name": "My Brokerage",
    "lead_first_name": "Jordan",
}


def test_model_signature_is_stripped_when_template_supplies_sign_off() -> None:
    rendered = render_outbound_template(
        "Hi {{lead_first_name}},\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}",
        RENDER_VALUES
        | {
            "message_body": (
                "Just checking whether your plans changed.\n\n"
                "Miller Schackman\n"
                "AI Lead Nurturing for Real Estate\n"
                "Helping brokers turn old leads into conversations"
            )
        },
    )

    assert rendered == (
        "Hi Jordan,\n\nJust checking whether your plans changed.\n\nBest,\nMy Brokerage"
    )


def test_model_sign_off_is_stripped_when_template_sign_off_is_none() -> None:
    rendered = render_outbound_template(
        "Hi {{lead_first_name}},\n\n{{message_body}}",
        RENDER_VALUES
        | {"message_body": "Are you still looking?\n\nRegards,\nAlex Agent"},
    )

    assert rendered == "Hi Jordan,\n\nAre you still looking?"


def test_body_ending_in_a_sentence_is_left_intact() -> None:
    rendered = render_outbound_template(
        "{{message_body}}\n\nBest,\n{{brokerage_name}}",
        RENDER_VALUES
        | {"message_body": "Thanks for the update. Should I send over a few options?"},
    )

    assert rendered == (
        "Thanks for the update. Should I send over a few options?\n\nBest,\nMy Brokerage"
    )


def test_body_that_is_only_a_sign_off_is_left_intact() -> None:
    rendered = render_outbound_template(
        "{{message_body}}",
        RENDER_VALUES | {"message_body": "Regards,\nAlex Agent"},
    )

    assert rendered == "Regards,\nAlex Agent"


def test_single_line_signature_is_stripped() -> None:
    rendered = render_outbound_template(
        "Hi {{lead_first_name}},\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}",
        RENDER_VALUES
        | {
            "message_body": (
                "Just checking in.\n\nMiller Schackman / AI Lead Nurturing for Real Estate"
            )
        },
    )

    assert rendered == "Hi Jordan,\n\nJust checking in.\n\nBest,\nMy Brokerage"


def test_model_greeting_is_stripped_when_template_greeting_is_none() -> None:
    rendered = render_outbound_template(
        "{{message_body}}\n\nBest,\n{{brokerage_name}}",
        RENDER_VALUES | {"message_body": "Hi Jordan,\n\nAre you still looking?"},
    )

    assert rendered == "Are you still looking?\n\nBest,\nMy Brokerage"


def test_model_greeting_opening_a_sentence_keeps_the_sentence() -> None:
    rendered = render_outbound_template(
        "Hi {{lead_first_name}},\n\n{{message_body}}",
        RENDER_VALUES | {"message_body": "Hi Jordan, are you still looking?"},
    )

    assert rendered == "Hi Jordan,\n\nAre you still looking?"


def test_body_that_is_only_a_greeting_is_left_intact() -> None:
    rendered = render_outbound_template(
        "{{message_body}}",
        RENDER_VALUES | {"message_body": "Hi Jordan,"},
    )

    assert rendered == "Hi Jordan,"


def test_trailing_list_without_signature_signal_is_preserved() -> None:
    rendered = render_outbound_template(
        "Hi {{lead_first_name}},\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}",
        RENDER_VALUES
        | {"message_body": "Here are the areas we cover:\n\nOakland\nBerkeley\nAlameda"},
    )

    assert rendered == (
        "Hi Jordan,\n\nHere are the areas we cover:\n\n"
        "Oakland\nBerkeley\nAlameda\n\nBest,\nMy Brokerage"
    )