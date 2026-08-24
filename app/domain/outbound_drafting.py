import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from app.domain.common.ids import WorkspaceId

SUPPORTED_QUERY_EXTRACTION_FIELDS = (
    "address",
    "location",
    "keywords",
    "search_type",
    "beds",
    "min_price",
    "max_price",
    "price_band",
)
SUPPORTED_TEMPLATE_PLACEHOLDERS = (
    "agent_name",
    "brokerage_name",
    "lead_first_name",
    "message_body",
    "message_subject",
)
DEFAULT_PROMPT_TEXT = (
    "You write follow-up messages for a real estate brokerage in the voice of a "
    "busy, friendly human agent.\n"
    "Draft one compliant outbound message using only the approved context below. "
    "Write like a real person: plain everyday words, contractions, short "
    "sentences, one thought at a time. Never sound like marketing copy or an AI "
    "assistant."
)
DEFAULT_SMS_TEMPLATE = "Hi there,\n\n{{message_body}}"
DEFAULT_EMAIL_TEMPLATE = "Hi there,\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}"
DEFAULT_EMAIL_SUBJECT_TEMPLATE = "{{message_subject}} | {{brokerage_name}}"
DEFAULT_SMS_PROMPT_TEXT = (
    "Write a short SMS that reads like a quick, casual text from a real person. "
    "Use contractions and everyday words, keep it to one or two brief sentences "
    "with a single thought, and ask at most one easy question. No marketing "
    "phrases, no forced enthusiasm, no emojis, and nothing that sounds automated. "
    "Personalize only from the approved context and don't repeat recent outbound "
    "phrasing. Do not add a greeting or sign-off when the template already "
    "provides that formatting."
)
DEFAULT_EMAIL_PROMPT_TEXT = (
    "Write a brief, natural follow-up email body with a short, plain subject "
    "line, like a busy agent typing a quick personal note. Use contractions and "
    "everyday words, keep it to a few short sentences, and ask at most one easy "
    "question. Avoid marketing language, filler openers like 'I hope you're doing "
    "well' or 'I wanted to reach out', and anything that sounds automated or "
    "templated. Personalize only from the approved context and don't repeat "
    "recent outbound phrasing. Do not add a greeting, sign-off, sender name, or "
    "brokerage name when the templates already provide that formatting."
)
LEGACY_SMS_INSTRUCTION_TEMPLATE = (
    "Write a short, conversational SMS. Acknowledge the lead's latest request, "
    "use approved listing context only when it is present, and end with a clear "
    "offer to have the assigned agent follow up."
)
LEGACY_EMAIL_INSTRUCTION_TEMPLATE = (
    "Write a concise follow-up email with a short subject line. Acknowledge the "
    "lead's latest request, use approved listing context only when it is present, "
    "and end with a clear offer to have the assigned agent follow up."
)
TEMPLATE_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-z_]+)\s*}}")


class OutboundJourneyKind(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"


@dataclass(frozen=True)
class OutboundJourneyChange:
    """The lead's previous journey, when it differs from the current draft's journey.

    Earlier outreach in the lead's history was written for a different journey
    or track; the drafting prompt uses this to keep the LLM from reusing that
    copy's framing as if it still applied.
    """

    previous_journey_kind: OutboundJourneyKind
    track_changed: bool = False


class DormantMessageTone(StrEnum):
    WARM = "warm"
    CONVERSATIONAL = "conversational"
    PROFESSIONAL = "professional"
    EMPATHETIC = "empathetic"
    CONFIDENT = "confident"
    LOW_PRESSURE = "low_pressure"


class DormantMessageStyle(StrEnum):
    SHORT_CHECK_IN = "short_check_in"
    FRIENDLY_FOLLOW_UP = "friendly_follow_up"
    CONSULTATIVE = "consultative"
    DIRECT_CONCISE = "direct_concise"
    HELPFUL_UPDATE = "helpful_update"
    REENGAGEMENT_QUESTION = "reengagement_question"


class DormantMessageLength(StrEnum):
    VERY_SHORT = "very_short"
    SHORT = "short"
    MODERATE = "moderate"
    DETAILED = "detailed"


class DormantCallToAction(StrEnum):
    ASK_SIMPLE_QUESTION = "ask_simple_question"
    INVITE_REPLY = "invite_reply"
    ASK_IF_PLANS_CHANGED = "ask_if_plans_changed"
    OFFER_AGENT_HELP = "offer_agent_help"
    REQUEST_UPDATED_CRITERIA = "request_updated_criteria"
    OFFER_HUMAN_FOLLOW_UP = "offer_human_follow_up"


class DormantGreeting(StrEnum):
    NONE = "none"
    LEAD_FIRST_NAME = "lead_first_name"
    HELLO_FIRST_NAME = "hello_first_name"
    HI_THERE = "hi_there"


class DormantSignOff(StrEnum):
    NONE = "none"
    BEST_BROKERAGE = "best_brokerage"
    REGARDS_AGENT = "regards_agent"
    CUSTOM = "custom"


MAX_CUSTOM_SIGN_OFF_LENGTH = 300


class DormantListingContextBehavior(StrEnum):
    NEVER = "never"
    WHEN_AVAILABLE = "when_available"
    GENERAL_CRITERIA_ONLY = "general_criteria_only"


class DormantPersonalizationField(StrEnum):
    LEAD_FIRST_NAME = "lead_first_name"
    LOCATION = "location"
    PROPERTY_TYPE = "property_type"
    BEDROOMS = "bedrooms"
    BUDGET = "budget"
    TIMELINE = "timeline"
    RECENT_CONVERSATION = "recent_conversation"
    APPROVED_LISTING_CONTEXT = "approved_listing_context"


def _default_dormant_personalization_fields() -> tuple[DormantPersonalizationField, ...]:
    return (
        DormantPersonalizationField.LEAD_FIRST_NAME,
        DormantPersonalizationField.LOCATION,
        DormantPersonalizationField.RECENT_CONVERSATION,
        DormantPersonalizationField.APPROVED_LISTING_CONTEXT,
    )


@dataclass(frozen=True)
class DormantStepTemplateProfile:
    tone: DormantMessageTone = DormantMessageTone.WARM
    style: DormantMessageStyle = DormantMessageStyle.FRIENDLY_FOLLOW_UP
    length: DormantMessageLength = DormantMessageLength.SHORT
    call_to_action: DormantCallToAction = DormantCallToAction.INVITE_REPLY
    greeting: DormantGreeting = DormantGreeting.LEAD_FIRST_NAME
    sign_off: DormantSignOff = DormantSignOff.NONE
    listing_context: DormantListingContextBehavior = (
        DormantListingContextBehavior.WHEN_AVAILABLE
    )
    personalization_fields: tuple[DormantPersonalizationField, ...] = field(
        default_factory=_default_dormant_personalization_fields
    )
    custom_instructions: str | None = None
    custom_sign_off_text: str | None = None


def _default_enabled_extraction_fields() -> tuple[str, ...]:
    return SUPPORTED_QUERY_EXTRACTION_FIELDS


@dataclass(frozen=True)
class WorkspaceOutboundDraftingConfig:
    workspace_id: WorkspaceId
    revision: int = 1
    sms_template: str = DEFAULT_SMS_TEMPLATE
    email_template: str = DEFAULT_EMAIL_TEMPLATE
    email_subject_template: str = DEFAULT_EMAIL_SUBJECT_TEMPLATE
    sms_prompt_text: str = DEFAULT_SMS_PROMPT_TEXT
    email_prompt_text: str = DEFAULT_EMAIL_PROMPT_TEXT
    prompt_text: str = DEFAULT_PROMPT_TEXT
    enabled_extraction_fields: tuple[str, ...] = field(
        default_factory=_default_enabled_extraction_fields,
    )


def default_workspace_outbound_drafting_config(
    workspace_id: WorkspaceId,
) -> WorkspaceOutboundDraftingConfig:
    return WorkspaceOutboundDraftingConfig(workspace_id=workspace_id)


def apply_dormant_step_template_profile(
    drafting_config: WorkspaceOutboundDraftingConfig,
    profile: DormantStepTemplateProfile,
    *,
    channel: str,
) -> WorkspaceOutboundDraftingConfig:
    channel_prompt = (
        drafting_config.sms_prompt_text
        if channel == "sms"
        else drafting_config.email_prompt_text
    )
    profiled_prompt = f"{channel_prompt}\n\n{_dormant_profile_prompt(profile)}"
    template = _dormant_profile_template(profile)
    if channel == "sms":
        return replace(
            drafting_config,
            sms_prompt_text=profiled_prompt,
            sms_template=template,
        )
    return replace(
        drafting_config,
        email_prompt_text=profiled_prompt,
        email_template=template,
    )


def dormant_step_template_profile_to_mapping(
    profile: DormantStepTemplateProfile,
) -> dict[str, object]:
    return {
        "tone": profile.tone.value,
        "style": profile.style.value,
        "length": profile.length.value,
        "call_to_action": profile.call_to_action.value,
        "greeting": profile.greeting.value,
        "sign_off": profile.sign_off.value,
        "listing_context": profile.listing_context.value,
        "personalization_fields": [value.value for value in profile.personalization_fields],
        "custom_instructions": profile.custom_instructions,
        "custom_sign_off_text": profile.custom_sign_off_text,
    }


def dormant_step_template_profile_from_mapping(
    value: Mapping[str, object] | None,
) -> DormantStepTemplateProfile | None:
    if value is None:
        return None
    try:
        raw_fields = value.get("personalization_fields", [])
        fields = (
            tuple(DormantPersonalizationField(str(item)) for item in raw_fields)
            if isinstance(raw_fields, list)
            else ()
        )
        raw_custom_instructions = value.get("custom_instructions")
        custom_instructions = (
            str(raw_custom_instructions).strip() or None
            if raw_custom_instructions is not None
            else None
        )
        raw_custom_sign_off = value.get("custom_sign_off_text")
        custom_sign_off_text = (
            str(raw_custom_sign_off).strip() or None
            if raw_custom_sign_off is not None
            else None
        )
        return DormantStepTemplateProfile(
            tone=DormantMessageTone(str(value["tone"])),
            style=DormantMessageStyle(str(value["style"])),
            length=DormantMessageLength(str(value["length"])),
            call_to_action=DormantCallToAction(str(value["call_to_action"])),
            greeting=DormantGreeting(str(value["greeting"])),
            sign_off=DormantSignOff(str(value["sign_off"])),
            listing_context=DormantListingContextBehavior(str(value["listing_context"])),
            personalization_fields=fields,
            custom_instructions=custom_instructions,
            custom_sign_off_text=custom_sign_off_text,
        )
    except (KeyError, TypeError, ValueError):
        return None


def dormant_template_profile_is_valid_for_channel(
    profile: DormantStepTemplateProfile | None,
    *,
    channel: str,
) -> bool:
    if profile is None:
        return True
    if channel == "sms" and profile.length == DormantMessageLength.DETAILED:
        return False
    if len(profile.custom_instructions or "") > 1000:
        return False
    return _custom_sign_off_is_valid(profile)


def _custom_sign_off_is_valid(profile: DormantStepTemplateProfile) -> bool:
    if profile.sign_off != DormantSignOff.CUSTOM:
        return True
    text = (profile.custom_sign_off_text or "").strip()
    if not text or len(text) > MAX_CUSTOM_SIGN_OFF_LENGTH:
        return False
    allowed = {"agent_name", "brokerage_name", "lead_first_name"}
    return all(
        placeholder in allowed for placeholder in extract_template_placeholders(text)
    )


def _dormant_profile_prompt(profile: DormantStepTemplateProfile) -> str:
    personalization = ", ".join(
        value.value.replace("_", " ") for value in profile.personalization_fields
    )
    directives = [
        "Apply this validated dormant-step writing profile:",
        f"- Tone: {profile.tone.value.replace('_', ' ')}.",
        f"- Style: {profile.style.value.replace('_', ' ')}.",
        f"- Length: {_length_directive(profile.length)}.",
        f"- Call to action: {_cta_directive(profile.call_to_action)}.",
        f"- Personalize only with these categories when present: {personalization or 'none'}.",
        f"- Listing context: {_listing_context_directive(profile.listing_context)}.",
        "- Ask no more than one question and never add pressure or urgency.",
    ]
    if profile.custom_instructions:
        directives.append(f"- Additional admin guidance: {profile.custom_instructions.strip()}")
    return "\n".join(directives)


def _length_directive(length: DormantMessageLength) -> str:
    return {
        DormantMessageLength.VERY_SHORT: "one or two brief sentences",
        DormantMessageLength.SHORT: "two or three concise sentences",
        DormantMessageLength.MODERATE: "one short paragraph",
        DormantMessageLength.DETAILED: "two short email paragraphs",
    }[length]


def _cta_directive(call_to_action: DormantCallToAction) -> str:
    return {
        DormantCallToAction.ASK_SIMPLE_QUESTION: "end with one simple question",
        DormantCallToAction.INVITE_REPLY: "invite a brief reply",
        DormantCallToAction.ASK_IF_PLANS_CHANGED: "ask whether their plans have changed",
        DormantCallToAction.OFFER_AGENT_HELP: "offer help from their assigned agent",
        DormantCallToAction.REQUEST_UPDATED_CRITERIA: "invite updated search criteria",
        DormantCallToAction.OFFER_HUMAN_FOLLOW_UP: "offer a human follow-up",
    }[call_to_action]


def _listing_context_directive(behavior: DormantListingContextBehavior) -> str:
    return {
        DormantListingContextBehavior.NEVER: "do not mention listings or current matches",
        DormantListingContextBehavior.WHEN_AVAILABLE: (
            "mention approved current context only when the application provides it"
        ),
        DormantListingContextBehavior.GENERAL_CRITERIA_ONLY: (
            "when approved context is present, mention only general areas or property types"
        ),
    }[behavior]


def _dormant_profile_template(profile: DormantStepTemplateProfile) -> str:
    greeting = {
        DormantGreeting.NONE: "",
        DormantGreeting.LEAD_FIRST_NAME: "Hi {{lead_first_name}},",
        DormantGreeting.HELLO_FIRST_NAME: "Hello {{lead_first_name}},",
        DormantGreeting.HI_THERE: "Hi there,",
    }[profile.greeting]
    sign_off = {
        DormantSignOff.NONE: "",
        DormantSignOff.BEST_BROKERAGE: "Best,\n{{brokerage_name}}",
        DormantSignOff.REGARDS_AGENT: "Regards,\n{{agent_name}}",
        DormantSignOff.CUSTOM: (profile.custom_sign_off_text or "").strip(),
    }[profile.sign_off]
    return "\n\n".join(part for part in (greeting, "{{message_body}}", sign_off) if part)


def normalize_enabled_extraction_fields(fields: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in fields:
        value = str(raw).strip().lower()
        if value not in SUPPORTED_QUERY_EXTRACTION_FIELDS or value in normalized:
            continue
        normalized.append(value)
    return tuple(normalized)


def normalize_outbound_template(template: str) -> str:
    return template.replace("\r\n", "\n").strip()


def normalize_sms_template(template: str) -> str:
    normalized = normalize_outbound_template(template)
    if not normalized or normalized == LEGACY_SMS_INSTRUCTION_TEMPLATE:
        return DEFAULT_SMS_TEMPLATE
    return normalized


def normalize_email_template(template: str) -> str:
    normalized = normalize_outbound_template(template)
    if not normalized or normalized == LEGACY_EMAIL_INSTRUCTION_TEMPLATE:
        return DEFAULT_EMAIL_TEMPLATE
    return normalized


def normalize_email_subject_template(template: str) -> str:
    normalized = normalize_outbound_template(template)
    return normalized or DEFAULT_EMAIL_SUBJECT_TEMPLATE


def normalize_outbound_prompt_text(prompt_text: str, *, default_text: str) -> str:
    normalized = prompt_text.replace("\r\n", "\n").strip()
    return normalized or default_text


def normalize_config_prompt_text(prompt_text: str) -> str:
    normalized = normalize_outbound_prompt_text(
        prompt_text,
        default_text=DEFAULT_PROMPT_TEXT,
    )
    if normalized in {
        LEGACY_SMS_INSTRUCTION_TEMPLATE,
        LEGACY_EMAIL_INSTRUCTION_TEMPLATE,
        DEFAULT_SMS_PROMPT_TEXT,
        DEFAULT_EMAIL_PROMPT_TEXT,
    }:
        return DEFAULT_PROMPT_TEXT
    return normalized


def extract_template_placeholders(template: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for match in TEMPLATE_PLACEHOLDER_PATTERN.findall(template):
        placeholder = match.strip().lower()
        if placeholder and placeholder not in normalized:
            normalized.append(placeholder)
    return tuple(normalized)


def render_outbound_template(template: str, values: Mapping[str, str]) -> str:
    normalized_template = normalize_outbound_template(template)
    message_body_match = _message_body_placeholder_match(normalized_template)
    message_body = _deduplicate_message_body(
        template=normalized_template,
        values=values,
    )
    render_values = dict(values)
    render_values["message_body"] = message_body

    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip().lower()
        return render_values.get(placeholder, match.group(0))

    rendered_template = TEMPLATE_PLACEHOLDER_PATTERN.sub(replace, normalized_template)

    if message_body_match is None:
        if not rendered_template:
            return message_body
        if not message_body:
            return rendered_template
        return f"{rendered_template}\n\n{message_body}"

    return rendered_template


def render_outbound_subject_template(template: str, values: Mapping[str, str]) -> str:
    normalized_template = normalize_outbound_template(template)
    message_subject = values.get("message_subject", "").strip()

    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip().lower()
        return values.get(placeholder, match.group(0))

    if not normalized_template:
        return message_subject
    return TEMPLATE_PLACEHOLDER_PATTERN.sub(replace, normalized_template)


def _deduplicate_message_body(
    *,
    template: str,
    values: Mapping[str, str],
) -> str:
    message_body = values.get("message_body", "").replace("\r\n", "\n").strip()
    if not message_body:
        return ""

    prefix, suffix = _rendered_template_wrapper_parts(template, values)
    without_prefix = _strip_matching_wrapper_from_start(message_body, prefix)
    without_suffix = _strip_matching_wrapper_from_end(without_prefix, suffix)
    return without_suffix.strip()


def _rendered_template_wrapper_parts(
    template: str,
    values: Mapping[str, str],
) -> tuple[str, str]:
    message_body_match = _message_body_placeholder_match(template)
    if message_body_match is None:
        return _render_template_fragment(template, values), ""

    prefix = template[: message_body_match.start()]
    suffix = template[message_body_match.end() :]
    return _render_template_fragment(prefix, values), _render_template_fragment(suffix, values)


def _message_body_placeholder_match(template: str) -> re.Match[str] | None:
    for match in TEMPLATE_PLACEHOLDER_PATTERN.finditer(template):
        if match.group(1).strip().lower() == "message_body":
            return match
    return None


def _render_template_fragment(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip().lower()
        if placeholder == "message_body":
            return ""
        return values.get(placeholder, match.group(0))

    return TEMPLATE_PLACEHOLDER_PATTERN.sub(replace, template).strip()


def _strip_matching_wrapper_from_start(body: str, wrapper: str) -> str:
    wrapper_lines = _meaningful_lines(wrapper)
    if not wrapper_lines:
        return body

    if _is_greeting_line(wrapper_lines[0]):
        stripped_greeting = _strip_greeting_prefix(body, wrapper_lines[0])
        if stripped_greeting is not None:
            body = stripped_greeting

    body_lines = body.split("\n")
    start_index = _leading_blank_line_count(body_lines)
    cursor = start_index
    for wrapper_line in wrapper_lines:
        cursor = _skip_blank_lines(body_lines, cursor, step=1)
        if cursor >= len(body_lines):
            return body
        lines_match = _wrapper_lines_match(body_lines[cursor], wrapper_line)
        if cursor == start_index and _is_greeting_line(wrapper_line):
            lines_match = lines_match or _is_greeting_line(body_lines[cursor])
        if not lines_match:
            return body
        cursor += 1

    removal_end = cursor
    while removal_end < len(body_lines) and not body_lines[removal_end].strip():
        removal_end += 1
    return "\n".join(body_lines[removal_end:])


def _strip_matching_wrapper_from_end(body: str, wrapper: str) -> str:
    wrapper_lines = _meaningful_lines(wrapper)
    if not wrapper_lines:
        return body

    body_lines = body.split("\n")
    end_index = _trailing_blank_line_start(body_lines)
    cursor = end_index - 1
    for wrapper_line in reversed(wrapper_lines):
        cursor = _skip_blank_lines(body_lines, cursor, step=-1)
        if cursor < 0 or not _wrapper_lines_match(body_lines[cursor], wrapper_line):
            return body
        cursor -= 1

    removal_start = cursor + 1
    while removal_start > 0 and not body_lines[removal_start - 1].strip():
        removal_start -= 1
    return "\n".join(body_lines[:removal_start])


def _meaningful_lines(value: str) -> tuple[str, ...]:
    return tuple(line for line in value.split("\n") if line.strip())


def _leading_blank_line_count(lines: list[str]) -> int:
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def _trailing_blank_line_start(lines: list[str]) -> int:
    index = len(lines)
    while index > 0 and not lines[index - 1].strip():
        index -= 1
    return index


def _skip_blank_lines(lines: list[str], index: int, *, step: int) -> int:
    cursor = index
    while 0 <= cursor < len(lines) and not lines[cursor].strip():
        cursor += step
    return cursor


def _wrapper_lines_match(body_line: str, wrapper_line: str) -> bool:
    return _normalize_wrapper_line(body_line) == _normalize_wrapper_line(wrapper_line)


def _strip_greeting_prefix(body: str, wrapper_line: str) -> str | None:
    body_lines = body.split("\n")
    start_index = _leading_blank_line_count(body_lines)
    if start_index >= len(body_lines):
        return None

    greeting = _normalize_wrapper_line(wrapper_line)
    greeting_words = greeting.split()
    if not greeting_words:
        return None
    candidates = [greeting, greeting_words[0]]
    for candidate in sorted(set(candidates), key=len, reverse=True):
        match = re.match(
            rf"(?i)^\s*{re.escape(candidate)}(?:\s*[,;:!?]|\s+|$)",
            body_lines[start_index],
        )
        if match is None:
            continue
        remainder = body_lines[start_index][match.end() :].lstrip()
        if not remainder:
            return None
        body_lines[start_index] = remainder
        return "\n".join(body_lines)
    return None


def _is_greeting_line(value: str) -> bool:
    normalized = _normalize_wrapper_line(value)
    return bool(re.match(r"^(?:hi|hello|hey|dear)(?:\s|$)", normalized))


def _normalize_wrapper_line(value: str) -> str:
    compact = re.sub(r"\s+", " ", value.strip().lower())
    return compact.rstrip(".,;:!?")
