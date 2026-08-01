from __future__ import annotations

from datetime import datetime

from app.domain.conversations import WorkspaceHandoffConfig

_SNAPSHOT_SUMMARY_MAX_CHARS = 1000
_SNAPSHOT_MESSAGE_MAX_CHARS = 500
_SNAPSHOT_STATUS_MAX_CHARS = 120


def has_crm_snapshot_fields(config: WorkspaceHandoffConfig | None) -> bool:
    if config is None:
        return False
    return any(
        (
            config.crm_snapshot_summary_field,
            config.crm_snapshot_status_field,
            config.crm_snapshot_latest_inbound_field,
            config.crm_snapshot_latest_outbound_field,
            config.crm_snapshot_last_activity_at_field,
        )
    )


def build_crm_snapshot_custom_fields(
    config: WorkspaceHandoffConfig | None,
    *,
    summary_text: str | None = None,
    status: str | None = None,
    latest_inbound_text: str | None = None,
    latest_outbound_text: str | None = None,
    last_activity_at: datetime | None = None,
) -> dict[str, str]:
    if config is None:
        return {}

    fields: dict[str, str] = {}
    _set_snapshot_field(
        fields,
        config.crm_snapshot_summary_field,
        summary_text,
        max_chars=_SNAPSHOT_SUMMARY_MAX_CHARS,
    )
    _set_snapshot_field(
        fields,
        config.crm_snapshot_status_field,
        status,
        max_chars=_SNAPSHOT_STATUS_MAX_CHARS,
    )
    _set_snapshot_field(
        fields,
        config.crm_snapshot_latest_inbound_field,
        latest_inbound_text,
        max_chars=_SNAPSHOT_MESSAGE_MAX_CHARS,
    )
    _set_snapshot_field(
        fields,
        config.crm_snapshot_latest_outbound_field,
        latest_outbound_text,
        max_chars=_SNAPSHOT_MESSAGE_MAX_CHARS,
    )
    _set_snapshot_field(
        fields,
        config.crm_snapshot_last_activity_at_field,
        last_activity_at.isoformat() if last_activity_at is not None else None,
    )
    return fields


def _set_snapshot_field(
    fields: dict[str, str],
    field_name: str | None,
    value: str | None,
    *,
    max_chars: int | None = None,
) -> None:
    normalized_field_name = _normalize_text(field_name)
    normalized_value = _normalize_text(value)
    if normalized_field_name is None or normalized_value is None:
        return
    if max_chars is not None and len(normalized_value) > max_chars:
        normalized_value = _truncate(normalized_value, max_chars)
    fields[normalized_field_name] = normalized_value


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    return f"{value[: max_chars - 1].rstrip()}…"
