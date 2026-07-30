import re
from collections.abc import Mapping
from dataclasses import dataclass, field
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


class OutboundJourneyKind(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"


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

    body_lines = body.split("\n")
    start_index = _leading_blank_line_count(body_lines)
    cursor = start_index
    for wrapper_line in wrapper_lines:
        cursor = _skip_blank_lines(body_lines, cursor, step=1)
        if cursor >= len(body_lines) or not _wrapper_lines_match(body_lines[cursor], wrapper_line):
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


def _normalize_wrapper_line(value: str) -> str:
    compact = re.sub(r"\s+", " ", value.strip().lower())
    return compact.rstrip(".,;:!?")
