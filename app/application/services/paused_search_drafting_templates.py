from dataclasses import dataclass, replace

from app.domain.compliance.contactability import ContactChannel
from app.domain.outbound_drafting import WorkspaceOutboundDraftingConfig


@dataclass(frozen=True)
class PausedSearchDraftingTemplate:
    template_key: str
    email_subject_template: str
    email_template: str
    email_prompt_text: str


def _email_template(*paragraphs: str) -> str:
    body = "\n\n".join(paragraphs)
    return (
        "Hi {{lead_first_name}},\n\n"
        f"{body}\n\n"
        "{{message_body}}\n\nBest,\n{{agent_name}}\n{{brokerage_name}}"
    )


def _template(
    *,
    template_key: str,
    subject: str,
    intro: str,
    prompt: str,
) -> PausedSearchDraftingTemplate:
    return PausedSearchDraftingTemplate(
        template_key=template_key,
        email_subject_template=subject,
        email_template=_email_template(intro),
        email_prompt_text=prompt,
    )


_TEMPLATES = {
    "paused-search-rented-temporarily-maintenance-email-1": _template(
        template_key="paused-search-rented-temporarily-maintenance-email-1",
        subject="Checking in while your rental timeline plays out",
        intro=(
            "You mentioned being set for now because of your current rental "
            "timeline, so I wanted to check in without rushing anything."
        ),
        prompt=(
            "Write one or two short sentences for a paused-search email to a lead who is "
            "temporarily renting. Keep it calm and practical. Ask whether their timeline is "
            "still the same or whether they want to reconnect closer to the end of the lease."
        ),
    ),
    "paused-search-rented-temporarily-reactivation-email-1": _template(
        template_key="paused-search-rented-temporarily-reactivation-email-1",
        subject="Want to reconnect as your rental timeline gets closer?",
        intro=(
            "I wanted to reach back out as the timeline you mentioned gets closer, "
            "in case you want to restart the conversation."
        ),
        prompt=(
            "Write one or two short sentences for a reactivation email to a lead who may be "
            "approaching the end of a temporary rental period. Ask whether they want to reopen "
            "their search now or later."
        ),
    ),
    "paused-search-timing-not-right-maintenance-email-1": _template(
        template_key="paused-search-timing-not-right-maintenance-email-1",
        subject="Still best to reconnect later?",
        intro=(
            "When we last spoke, the timing did not seem right, so I wanted to send "
            "a light check-in."
        ),
        prompt=(
            "Write one or two short sentences for a low-pressure paused-search email when the "
            "lead said the timing was not right. Keep it generic, polite, and easy to ignore."
        ),
    ),
    "paused-search-timing-not-right-reactivation-email-1": _template(
        template_key="paused-search-timing-not-right-reactivation-email-1",
        subject="Would it help to reconnect now?",
        intro=(
            "I wanted to check back in in case the timing feels different now and you "
            "would like to reopen the conversation."
        ),
        prompt=(
            "Write one or two short sentences for a soft reactivation email when the lead had "
            "previously said the timing was not right. Ask one simple question about whether "
            "they want to reconnect."
        ),
    ),
    "paused-search-waiting-for-rates-maintenance-email-1": _template(
        template_key="paused-search-waiting-for-rates-maintenance-email-1",
        subject="Still planning to wait on rates for now?",
        intro=(
            "You mentioned waiting on rates before reopening your search, so I "
            "wanted to check in without making assumptions about the market."
        ),
        prompt=(
            "Write one or two short sentences for a paused-search email to a rate-sensitive "
            "lead. Stay non-advisory and do not predict rate movements. Ask whether the timing "
            "still feels the same or whether they want to talk through next steps with their "
            "agent."
        ),
    ),
    "paused-search-waiting-for-rates-reactivation-email-1": _template(
        template_key="paused-search-waiting-for-rates-reactivation-email-1",
        subject="Want to revisit your search timing?",
        intro=(
            "I wanted to reach back out in case you are closer to revisiting your "
            "plans and want to restart the conversation."
        ),
        prompt=(
            "Write one or two short sentences for a reactivation email to a lead who had paused "
            "while waiting on rates. Stay factual and operationally safe."
        ),
    ),
    "paused-search-waiting-for-inventory-maintenance-email-1": _template(
        template_key="paused-search-waiting-for-inventory-maintenance-email-1",
        subject="Want us to keep an eye on the market a little longer?",
        intro=(
            "You mentioned not seeing the right inventory yet, so I wanted to send "
            "a quick, low-pressure check-in."
        ),
        prompt=(
            "Write one or two short sentences for a paused-search email to a buyer waiting for "
            "better inventory. Do not mention specific listings unless they are verified in the "
            "approved context."
        ),
    ),
    "paused-search-waiting-for-inventory-reactivation-email-1": _template(
        template_key="paused-search-waiting-for-inventory-reactivation-email-1",
        subject="Would you like to revisit your search now?",
        intro=(
            "I wanted to reach back out in case you are open to restarting your "
            "search or updating what you want to see next."
        ),
        prompt=(
            "Write one or two short sentences for a reactivation email to a lead who had paused "
            "because inventory was not a fit. Keep it low-pressure and ask whether preferences "
            "or timing changed."
        ),
    ),
    "paused-search-financial-prep-maintenance-email-1": _template(
        template_key="paused-search-financial-prep-maintenance-email-1",
        subject="Checking in while you get ready",
        intro=(
            "You mentioned taking some time to get the financial side in place, so I "
            "wanted to send a supportive check-in without adding pressure."
        ),
        prompt=(
            "Write one or two short sentences for a supportive paused-search email to a lead "
            "doing financial preparation. Stay non-judgmental and do not provide lending, "
            "legal, tax, or investment advice."
        ),
    ),
    "paused-search-financial-prep-reactivation-email-1": _template(
        template_key="paused-search-financial-prep-reactivation-email-1",
        subject="Would it help to reconnect as you get closer?",
        intro=(
            "I wanted to check back in in case you are getting closer to the point "
            "where a conversation would be useful again."
        ),
        prompt=(
            "Write one or two short sentences for a reactivation email to a lead who had paused "
            "for financial preparation. Keep it supportive and operationally safe."
        ),
    ),
    "paused-search-personal-life-timing-maintenance-email-1": _template(
        template_key="paused-search-personal-life-timing-maintenance-email-1",
        subject="Checking in respectfully on timing",
        intro=(
            "You mentioned some personal timing factors, so I wanted to check in in "
            "a way that respects your bandwidth."
        ),
        prompt=(
            "Write one or two short sentences for a respectful paused-search email to a lead "
            "whose timing is affected by personal or family circumstances. Keep it simple and "
            "empathetic."
        ),
    ),
    "paused-search-personal-life-timing-reactivation-email-1": _template(
        template_key="paused-search-personal-life-timing-reactivation-email-1",
        subject="Would it help to reconnect when the timing feels better?",
        intro=(
            "I wanted to check back in in case the timing feels more manageable now "
            "and you want to pick the conversation back up."
        ),
        prompt=(
            "Write one or two short sentences for a reactivation email that stays empathetic and "
            "does not sound transactional. Ask whether they want to reconnect now or later."
        ),
    ),
    "paused-search-other-known-pause-maintenance-email-1": _template(
        template_key="paused-search-other-known-pause-maintenance-email-1",
        subject="Just checking in for now",
        intro="I wanted to send a light check-in while things are on pause on your side.",
        prompt=(
            "Write one or two short sentences for a gentle paused-search email when the lead has "
            "a known pause reason that does not fit a more specific category."
        ),
    ),
    "paused-search-other-known-pause-reactivation-email-1": _template(
        template_key="paused-search-other-known-pause-reactivation-email-1",
        subject="Would you like to restart the conversation?",
        intro=(
            "I wanted to check back in in case now is a better time to reopen the "
            "conversation."
        ),
        prompt=(
            "Write one or two short sentences for a simple reactivation email to a lead whose "
            "pause reason is known but not part of a more specific curated reason."
        ),
    ),
}


def get_paused_search_drafting_template(
    template_key: str,
) -> PausedSearchDraftingTemplate | None:
    return _TEMPLATES.get(template_key)


def paused_search_template_keys() -> tuple[str, ...]:
    return tuple(_TEMPLATES)


def apply_paused_search_drafting_template(
    *,
    drafting_config: WorkspaceOutboundDraftingConfig,
    channel: ContactChannel,
    template_key: str | None,
) -> WorkspaceOutboundDraftingConfig:
    if channel != ContactChannel.EMAIL or template_key is None:
        return drafting_config
    template = get_paused_search_drafting_template(template_key)
    if template is None:
        return drafting_config
    return replace(
        drafting_config,
        email_template=template.email_template,
        email_subject_template=template.email_subject_template,
        email_prompt_text=template.email_prompt_text,
    )