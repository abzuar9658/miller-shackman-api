from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum

from app.domain.common.ids import WorkspaceId


class ContactChannel(StrEnum):
    SMS = "sms"
    EMAIL = "email"


class ContactPermissionStatus(StrEnum):
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    DENIED = "denied"


class SmsComplianceState(StrEnum):
    APPROVED = "approved"
    NOT_APPROVED = "not_approved"
    UNKNOWN = "unknown"


class SuppressionType(StrEnum):
    SMS_OPT_OUT = "sms_opt_out"
    EMAIL_UNSUBSCRIBED = "email_unsubscribed"


class ContactSuppressionKind(StrEnum):
    SMS_OPT_OUT = "sms_opt_out"
    EMAIL_UNSUBSCRIBED = "email_unsubscribed"
    DO_NOT_CONTACT = "do_not_contact"


class ContactabilityReasonCode(StrEnum):
    DO_NOT_CONTACT = "do_not_contact"
    INSUFFICIENT_DATA = "insufficient_data"
    SMS_OPTED_OUT = "sms_opted_out"
    SMS_COMPLIANCE_NOT_APPROVED = "sms_compliance_not_approved"
    MISSING_SMS_CONSENT = "missing_sms_consent"
    SMS_PERMISSION_DENIED = "sms_permission_denied"
    EMAIL_UNSUBSCRIBED = "email_unsubscribed"
    MISSING_EMAIL_PERMISSION = "missing_email_permission"
    EMAIL_PERMISSION_DENIED = "email_permission_denied"


def _empty_suppressions() -> frozenset[SuppressionType]:
    return frozenset()


@dataclass(frozen=True)
class LeadContactabilityFacts:
    do_not_contact: bool | None
    has_sms_destination: bool = False
    has_email_destination: bool = False
    sms_consent_status: ContactPermissionStatus | None = None
    email_permission_status: ContactPermissionStatus | None = None
    suppressions: frozenset[SuppressionType] = field(default_factory=_empty_suppressions)


def _default_quiet_hours_start() -> time:
    return time(10, 0)


def _default_quiet_hours_end() -> time:
    return time(17, 0)


@dataclass(frozen=True)
class WorkspaceContactPolicy:
    workspace_id: WorkspaceId
    sms_compliance_state: SmsComplianceState = SmsComplianceState.NOT_APPROVED
    quiet_hours_start: time | None = field(default_factory=_default_quiet_hours_start)
    quiet_hours_end: time | None = field(default_factory=_default_quiet_hours_end)


def default_workspace_contact_policy(workspace_id: WorkspaceId) -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(workspace_id=workspace_id)


@dataclass(frozen=True)
class ContactabilityDecision:
    allowed: bool
    channel: ContactChannel
    reasons: tuple[ContactabilityReasonCode, ...] = ()


def evaluate_contactability(
    facts: LeadContactabilityFacts,
    policy: WorkspaceContactPolicy,
    channel: ContactChannel,
) -> ContactabilityDecision:
    _ = policy

    if facts.do_not_contact is True:
        return ContactabilityDecision(
            allowed=False,
            channel=channel,
            reasons=(ContactabilityReasonCode.DO_NOT_CONTACT,),
        )

    reasons: list[ContactabilityReasonCode] = []

    if channel == ContactChannel.SMS:
        reasons.extend(_evaluate_sms_reasons(facts))
    else:
        reasons.extend(_evaluate_email_reasons(facts))

    if facts.do_not_contact is None:
        reasons.append(ContactabilityReasonCode.INSUFFICIENT_DATA)

    return ContactabilityDecision(
        allowed=not reasons,
        channel=channel,
        reasons=tuple(reasons),
    )


def _evaluate_sms_reasons(facts: LeadContactabilityFacts) -> list[ContactabilityReasonCode]:
    reasons: list[ContactabilityReasonCode] = []

    if SuppressionType.SMS_OPT_OUT in facts.suppressions:
        reasons.append(ContactabilityReasonCode.SMS_OPTED_OUT)

    if (
        facts.sms_consent_status in (None, ContactPermissionStatus.UNKNOWN)
        and not facts.has_sms_destination
    ):
        reasons.append(ContactabilityReasonCode.MISSING_SMS_CONSENT)
    elif facts.sms_consent_status == ContactPermissionStatus.DENIED:
        reasons.append(ContactabilityReasonCode.SMS_PERMISSION_DENIED)

    return reasons


def _evaluate_email_reasons(
    facts: LeadContactabilityFacts,
) -> list[ContactabilityReasonCode]:
    reasons: list[ContactabilityReasonCode] = []

    if SuppressionType.EMAIL_UNSUBSCRIBED in facts.suppressions:
        reasons.append(ContactabilityReasonCode.EMAIL_UNSUBSCRIBED)

    if (
        facts.email_permission_status in (None, ContactPermissionStatus.UNKNOWN)
        and not facts.has_email_destination
    ):
        reasons.append(ContactabilityReasonCode.MISSING_EMAIL_PERMISSION)
    elif facts.email_permission_status == ContactPermissionStatus.DENIED:
        reasons.append(ContactabilityReasonCode.EMAIL_PERMISSION_DENIED)

    return reasons
