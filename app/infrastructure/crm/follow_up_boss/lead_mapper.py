from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactPermissionStatus, SuppressionType
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadType,
    PropertyEventType,
)

SOURCE_PAYLOAD_VERSION = "follow_up_boss_person:v1"
UNKNOWN = "unknown"
_EMPTY_MAPPING: Mapping[str, Any] = {}


def map_follow_up_boss_person_to_canonical_lead(
    *,
    workspace_id: WorkspaceId,
    payload: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]] = (),
    lead_id: LeadId | None = None,
    now: datetime | None = None,
    mapped_custom_field_keys: Iterable[str] = (),
) -> CanonicalLeadRecord:
    facts_derived_at = now or datetime.now(UTC)
    custom_fields = _custom_fields(payload)
    lead_type, reason, raw_type = _classify_lead_type(payload.get("type"))
    emails = _records(payload, "emails", fallback_key="email")
    phones = _records(payload, "phones", fallback_key="phone")
    latest_event = _latest_property_event(events)
    last_meaningful, reliability = _meaningful_activity(payload)
    assigned_agent_crm_id = _first_non_empty(
        payload.get("assignedUserId"),
        payload.get("assignedTo"),
    )
    assigned_agent_name = _text(payload.get("assignedTo"))
    display_name = _display_name(payload)
    sms_permission_status = _contact_permission_status(
        payload,
        custom_fields,
        keys=("sms_permission_status", "smsPermissionStatus", "sms_consent_status"),
    )
    email_permission_status = _contact_permission_status(
        payload,
        custom_fields,
        keys=("email_permission_status", "emailPermissionStatus"),
    )
    sms_opted_out = _bool_flag(
        payload,
        custom_fields,
        keys=("sms_opted_out", "smsOptedOut"),
    )
    email_unsubscribed = _bool_flag(
        payload,
        custom_fields,
        keys=("email_unsubscribed", "emailUnsubscribed"),
    )
    do_not_contact = _optional_bool_flag(
        payload,
        custom_fields,
        keys=("do_not_contact", "doNotContact"),
    )

    return CanonicalLeadRecord(
        workspace_id=workspace_id,
        lead_id=lead_id or uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=str(payload.get("id", "")),
        facts_derived_at=facts_derived_at,
        source_payload_version=SOURCE_PAYLOAD_VERSION,
        source_updated_at=_parse_datetime(payload.get("updated")),
        assigned_agent_crm_id=assigned_agent_crm_id,
        assigned_agent_name_present=_has_non_empty(payload.get("assignedTo")),
        has_accountable_owner=assigned_agent_crm_id is not None,
        lead_type=lead_type,
        classification_reason=reason,
        crm_type_raw=raw_type,
        lead_source=_text_or_unknown(payload.get("source")),
        lead_stage=_text_or_unknown(payload.get("stage")),
        created_via=_text_or_unknown(payload.get("createdVia")),
        tags=_tags(payload.get("tags")),
        mapped_custom_fields=_mapped_custom_fields(
            custom_fields,
            mapped_custom_field_keys,
            assigned_agent_name=assigned_agent_name,
            display_name=display_name,
        ),
        primary_email=_primary_email(emails),
        primary_phone=_primary_phone(phones),
        has_email=bool(emails),
        has_phone=bool(phones),
        has_sms_capable_phone=_has_sms_capable_phone(phones),
        email_count=len(emails),
        phone_count=len(phones),
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        sms_opted_out=sms_opted_out,
        email_unsubscribed=email_unsubscribed,
        do_not_contact=do_not_contact,
        suppression_types=_suppression_types(
            sms_opted_out=sms_opted_out,
            email_unsubscribed=email_unsubscribed,
        ),
        permission_evidence=_permission_evidence(
            sms_permission_status=sms_permission_status,
            email_permission_status=email_permission_status,
            sms_opted_out=sms_opted_out,
            email_unsubscribed=email_unsubscribed,
            do_not_contact=do_not_contact,
        ),
        crm_created_at=_parse_datetime(payload.get("created")),
        crm_updated_at=_parse_datetime(payload.get("updated")),
        last_activity_at=_parse_datetime(payload.get("lastActivity")),
        last_meaningful_communication_at=last_meaningful,
        contacted_count=_parse_int(payload.get("contacted")),
        activity_reliability=reliability,
        latest_property_event_type=latest_event.event_type if latest_event else None,
        latest_property_event_at=latest_event.occurred_at if latest_event else None,
        latest_property_price_band=latest_event.price_band if latest_event else None,
        latest_property_context_present=latest_event is not None,
    )


def _classify_lead_type(
    raw: object,
) -> tuple[LeadType, LeadClassificationReason, str | None]:
    value = _text(raw)
    if value is None:
        return LeadType.UNKNOWN, LeadClassificationReason.CRM_TYPE_MISSING, None
    normalized = value.casefold().replace(" ", "")
    if normalized == "buyer":
        return LeadType.BUYER, LeadClassificationReason.CRM_TYPE_BUYER, value
    if normalized == "seller":
        return LeadType.SELLER, LeadClassificationReason.CRM_TYPE_SELLER, value
    if normalized in {"buyer/seller", "seller/buyer", "buyerseller", "sellerbuyer"}:
        return LeadType.BUYER_SELLER, LeadClassificationReason.CRM_TYPE_BUYER_SELLER, value
    return LeadType.UNKNOWN, LeadClassificationReason.CRM_TYPE_UNSUPPORTED, value


def _records(
    payload: Mapping[str, Any],
    key: str,
    *,
    fallback_key: str,
) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(key)
    records: list[Mapping[str, Any]] = []
    if isinstance(value, list):
        records.extend(
            item for item in value if isinstance(item, Mapping) and _record_has_value(item)
        )
    fallback = _text(payload.get(fallback_key))
    if fallback and not records:
        records.append({"value": fallback})
    return tuple(records)


def _record_has_value(record: Mapping[str, Any]) -> bool:
    return any(_has_non_empty(record.get(key)) for key in ("value", "email", "phone", "number"))


def _has_sms_capable_phone(phones: tuple[Mapping[str, Any], ...]) -> bool:
    return any(_is_sms_capable_phone(phone) for phone in phones)


def _primary_email(emails: tuple[Mapping[str, Any], ...]) -> str | None:
    for email in emails:
        value = _record_value(email)
        if value is not None:
            return value
    return None


def _primary_phone(phones: tuple[Mapping[str, Any], ...]) -> str | None:
    for phone in phones:
        if _is_sms_capable_phone(phone):
            value = _record_value(phone)
            if value is not None:
                return value

    for phone in phones:
        value = _record_value(phone)
        if value is not None:
            return value
    return None


def _record_value(record: Mapping[str, Any]) -> str | None:
    return _first_non_empty(
        record.get("value"),
        record.get("email"),
        record.get("phone"),
        record.get("number"),
    )


def _is_sms_capable_phone(phone: Mapping[str, Any]) -> bool:
    return phone.get("isLandline") is not True


def _tags(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    tags: set[str] = set()
    for tag in raw:
        value = _text(tag)
        if value is not None:
            tags.add(value)
    return tuple(sorted(tags))


def _mapped_custom_fields(
    raw: object,
    allowed_keys: Iterable[str],
    *,
    assigned_agent_name: str | None,
    display_name: str | None,
) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        fields: dict[str, str] = {}
    else:
        allowed = set(allowed_keys)
        fields = {
            str(key): str(value)
            for key, value in raw.items()
            if str(key) in allowed and isinstance(value, str | int | float | bool)
        }
    if assigned_agent_name:
        fields.setdefault("assigned_agent_name", assigned_agent_name)
    if display_name:
        fields.setdefault("display_name", display_name)
    return fields


def _display_name(payload: Mapping[str, Any]) -> str | None:
    name = _text(payload.get("name"))
    if name:
        return name
    parts = [
        part for part in (_text(payload.get("firstName")), _text(payload.get("lastName"))) if part
    ]
    return " ".join(parts) or None


def _custom_fields(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = payload.get("customFields")
    if isinstance(raw, Mapping):
        return raw
    return _EMPTY_MAPPING


def _contact_permission_status(
    payload: Mapping[str, Any],
    custom_fields: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> ContactPermissionStatus:
    raw = _first_present_value(payload, custom_fields, keys)
    if raw is None:
        return ContactPermissionStatus.UNKNOWN
    if isinstance(raw, bool):
        return ContactPermissionStatus.CONFIRMED if raw else ContactPermissionStatus.DENIED
    normalized = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {
        "confirmed",
        "allow",
        "allowed",
        "yes",
        "true",
        "1",
        "opt_in",
        "opted_in",
        "granted",
        "subscribed",
    }:
        return ContactPermissionStatus.CONFIRMED
    if normalized in {
        "denied",
        "deny",
        "disallowed",
        "no",
        "false",
        "0",
        "opt_out",
        "opted_out",
        "revoked",
        "unsubscribed",
    }:
        return ContactPermissionStatus.DENIED
    return ContactPermissionStatus.UNKNOWN


def _bool_flag(
    payload: Mapping[str, Any],
    custom_fields: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> bool:
    result = _optional_bool_flag(payload, custom_fields, keys=keys)
    return bool(result)


def _optional_bool_flag(
    payload: Mapping[str, Any],
    custom_fields: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> bool | None:
    raw = _first_present_value(payload, custom_fields, keys)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    normalized = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"true", "1", "yes", "y", "on", "confirmed"}:
        return True
    if normalized in {"false", "0", "no", "n", "off", "denied"}:
        return False
    return None


def _first_present_value(
    payload: Mapping[str, Any],
    custom_fields: Mapping[str, Any],
    keys: tuple[str, ...],
) -> object | None:
    for key in keys:
        if key in payload:
            return payload.get(key)
        if key in custom_fields:
            return custom_fields.get(key)
    return None


def _suppression_types(
    *,
    sms_opted_out: bool,
    email_unsubscribed: bool,
) -> frozenset[SuppressionType]:
    suppressions: set[SuppressionType] = set()
    if sms_opted_out:
        suppressions.add(SuppressionType.SMS_OPT_OUT)
    if email_unsubscribed:
        suppressions.add(SuppressionType.EMAIL_UNSUBSCRIBED)
    return frozenset(suppressions)


def _permission_evidence(
    *,
    sms_permission_status: ContactPermissionStatus,
    email_permission_status: ContactPermissionStatus,
    sms_opted_out: bool,
    email_unsubscribed: bool,
    do_not_contact: bool | None,
) -> dict[str, str]:
    evidence: dict[str, str] = {}
    if sms_permission_status != ContactPermissionStatus.UNKNOWN:
        evidence["sms_permission_status_source"] = "follow_up_boss.customFields"
    if email_permission_status != ContactPermissionStatus.UNKNOWN:
        evidence["email_permission_status_source"] = "follow_up_boss.customFields"
    if sms_opted_out:
        evidence["sms_opted_out_source"] = "follow_up_boss.customFields"
    if email_unsubscribed:
        evidence["email_unsubscribed_source"] = "follow_up_boss.customFields"
    if do_not_contact is not None:
        evidence["do_not_contact_source"] = "follow_up_boss.customFields"
    return evidence


def _meaningful_activity(payload: Mapping[str, Any]) -> tuple[datetime | None, ActivityReliability]:
    last_communication = _parse_datetime(
        payload.get("lastCommunication") or payload.get("lastCommunicationAt"),
    )
    if last_communication is not None:
        return last_communication, ActivityReliability.RELIABLE
    if _parse_datetime(payload.get("lastActivity")) is not None:
        return None, ActivityReliability.PARTIAL
    return None, ActivityReliability.UNKNOWN


class _PropertyEvent:
    def __init__(
        self,
        event_type: PropertyEventType,
        occurred_at: datetime | None,
        price_band: str | None,
    ) -> None:
        self.event_type = event_type
        self.occurred_at = occurred_at
        self.price_band = price_band


def _latest_property_event(events: Iterable[Mapping[str, Any]]) -> _PropertyEvent | None:
    candidates: list[_PropertyEvent] = []
    for event in events:
        event_type = _property_event_type(event.get("type"))
        if event_type is None:
            continue
        property_data = event.get("property") if isinstance(event.get("property"), Mapping) else {}
        price = None if not isinstance(property_data, Mapping) else property_data.get("price")
        candidates.append(
            _PropertyEvent(
                event_type=event_type,
                occurred_at=_parse_datetime(event.get("created") or event.get("date")),
                price_band=_price_band(price),
            ),
        )
    return (
        max(candidates, key=lambda event: event.occurred_at or datetime.min) if candidates else None
    )


def _property_event_type(raw: object) -> PropertyEventType | None:
    value = _text(raw)
    if value == "Property Inquiry":
        return PropertyEventType.PROPERTY_INQUIRY
    if value == "Viewed Property":
        return PropertyEventType.VIEWED_PROPERTY
    return None


def _price_band(raw: object) -> str | None:
    try:
        price = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        return None
    if price <= 0:
        return None
    if price < 500_000:
        return "under_500k"
    if price < 1_000_000:
        return "500k_to_1m"
    if price < 2_000_000:
        return "1m_to_2m"
    return "2m_plus"


def _parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str | int | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_unknown(value: object) -> str:
    return _text(value) or UNKNOWN


def _text(value: object) -> str | None:
    if not isinstance(value, str | int | float):
        return None
    text = str(value).strip()
    return text or None


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _has_non_empty(value: object) -> bool:
    return _text(value) is not None
