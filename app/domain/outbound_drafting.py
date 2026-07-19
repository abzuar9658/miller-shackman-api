import re
from collections.abc import Mapping
from dataclasses import dataclass, field

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
    "message_body",
    "message_subject",
)
DEFAULT_PROMPT_TEXT = (
    "You are an administrative follow-up assistant for a real estate brokerage.\n"
    "Draft one compliant outbound message using only the approved JSON context below."
)
DEFAULT_SMS_TEMPLATE = "Hi there,\n\n{{message_body}}"
DEFAULT_EMAIL_TEMPLATE = "Hi there,\n\n{{message_body}}\n\nBest,\n{{brokerage_name}}"
DEFAULT_EMAIL_SUBJECT_TEMPLATE = "{{message_subject}} | {{brokerage_name}}"
DEFAULT_SMS_PROMPT_TEXT = (
    "Write a short, conversational SMS body for a real estate lead follow-up. Keep "
    "it warm, specific, and operationally safe. Personalize only from the approved "
    "context, avoid repeating recent outbound phrasing, and prefer plain human "
    "language over salesy wording. Do not add a greeting or sign-off when the "
    "template already provides that formatting."
)
DEFAULT_EMAIL_PROMPT_TEXT = (
    "Write a concise follow-up email body with a short subject line. Keep it warm, "
    "specific, and operationally safe. Personalize only from the approved context, "
    "avoid repeating recent outbound phrasing, and prefer plain human language over "
    "salesy wording. Do not add a greeting, sign-off, sender name, or brokerage "
    "name when the templates already provide that formatting."
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
    message_body = values.get("message_body", "").strip()

    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip().lower()
        return values.get(placeholder, match.group(0))

    rendered_template = TEMPLATE_PLACEHOLDER_PATTERN.sub(replace, normalized_template)

    if "{{message_body}}" not in normalized_template:
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
