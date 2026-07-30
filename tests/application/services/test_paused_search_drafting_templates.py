from uuid import UUID

from app.application.services.paused_search_drafting_templates import (
    apply_paused_search_drafting_template,
    get_paused_search_drafting_template,
    paused_search_template_keys,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.outbound_drafting import (
    default_workspace_outbound_drafting_config,
    render_outbound_subject_template,
    render_outbound_template,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000501")
PROHIBITED_TERMS = ("guarantee", "predict", "forecast", "investment advice")


def test_paused_search_templates_exist_and_render_cleanly() -> None:
    for template_key in paused_search_template_keys():
        template = get_paused_search_drafting_template(template_key)

        assert template is not None
        rendered_subject = render_outbound_subject_template(
            template.email_subject_template,
            {
                "agent_name": "Alex Agent",
                "brokerage_name": "Miller Schackman",
                "lead_first_name": "Jordan",
                "message_subject": "ignored",
            },
        )
        rendered_body = render_outbound_template(
            template.email_template,
            {
                "agent_name": "Alex Agent",
                "brokerage_name": "Miller Schackman",
                "lead_first_name": "Jordan",
                "message_body": "If your timing changed, just reply and I can help you reconnect.",
            },
        )

        assert "{{" not in rendered_subject
        assert "{{" not in rendered_body
        assert rendered_subject.strip()
        assert rendered_body.startswith("Hi Jordan,")
        assert "Alex Agent" in rendered_body
        assert "Miller Schackman" in rendered_body
        assert "If your timing changed" in rendered_body
        for prohibited_term in PROHIBITED_TERMS:
            assert prohibited_term not in rendered_subject.lower()
            assert prohibited_term not in rendered_body.lower()


def test_apply_paused_search_drafting_template_overrides_email_config_only() -> None:
    base_config = default_workspace_outbound_drafting_config(WORKSPACE_ID)

    email_config = apply_paused_search_drafting_template(
        drafting_config=base_config,
        channel=ContactChannel.EMAIL,
        template_key="paused-search-waiting-for-rates-maintenance-email-1",
    )
    sms_config = apply_paused_search_drafting_template(
        drafting_config=base_config,
        channel=ContactChannel.SMS,
        template_key="paused-search-waiting-for-rates-maintenance-email-1",
    )

    assert email_config.email_subject_template == "Still planning to wait on rates for now?"
    assert "waiting on rates" in email_config.email_template
    assert sms_config == base_config