from dataclasses import replace
from uuid import UUID

import pytest

from app.domain.compliance.contactability import (
    ContactabilityReasonCode,
    ContactChannel,
    ContactPermissionStatus,
    LeadContactabilityFacts,
    SmsComplianceState,
    SuppressionType,
    WorkspaceContactPolicy,
    evaluate_contactability,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def _base_facts() -> LeadContactabilityFacts:
    return LeadContactabilityFacts(
        do_not_contact=False,
        has_sms_destination=True,
        has_email_destination=True,
        sms_consent_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
    )


def _approved_policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
    )


@pytest.mark.parametrize("channel", [ContactChannel.SMS, ContactChannel.EMAIL])
def test_do_not_contact_blocks_both_channels(channel: ContactChannel) -> None:
    facts = replace(_base_facts(), do_not_contact=True)

    decision = evaluate_contactability(facts, _approved_policy(), channel)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.DO_NOT_CONTACT,)


def test_sms_opt_out_blocks_sms_even_with_confirmed_consent() -> None:
    facts = replace(_base_facts(), suppressions=frozenset({SuppressionType.SMS_OPT_OUT}))

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.SMS)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.SMS_OPTED_OUT,)


def test_email_unsubscribe_blocks_email_even_with_confirmed_permission() -> None:
    facts = replace(
        _base_facts(),
        suppressions=frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
    )

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.EMAIL)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.EMAIL_UNSUBSCRIBED,)


def test_unknown_sms_consent_with_sms_destination_is_allowed() -> None:
    facts = replace(_base_facts(), sms_consent_status=ContactPermissionStatus.UNKNOWN)

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.SMS)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_unknown_sms_consent_without_sms_destination_blocks_sms() -> None:
    facts = replace(
        _base_facts(),
        sms_consent_status=ContactPermissionStatus.UNKNOWN,
        has_sms_destination=False,
    )

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.SMS)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.MISSING_SMS_CONSENT,)


def test_unknown_email_permission_with_email_destination_is_allowed() -> None:
    facts = replace(_base_facts(), email_permission_status=ContactPermissionStatus.UNKNOWN)

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.EMAIL)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_unknown_email_permission_without_email_destination_blocks_email() -> None:
    facts = replace(
        _base_facts(),
        email_permission_status=ContactPermissionStatus.UNKNOWN,
        has_email_destination=False,
    )

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.EMAIL)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.MISSING_EMAIL_PERMISSION,)


def test_denied_sms_permission_blocks_sms() -> None:
    facts = replace(_base_facts(), sms_consent_status=ContactPermissionStatus.DENIED)

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.SMS)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.SMS_PERMISSION_DENIED,)


def test_denied_email_permission_blocks_email() -> None:
    facts = replace(_base_facts(), email_permission_status=ContactPermissionStatus.DENIED)

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.EMAIL)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.EMAIL_PERMISSION_DENIED,)


def test_sms_contactability_ignores_compliance_state_in_v1() -> None:
    decision = evaluate_contactability(
        _base_facts(),
        WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.NOT_APPROVED,
        ),
        ContactChannel.SMS,
    )

    assert decision.allowed is True
    assert decision.reasons == ()


def test_confirmed_sms_consent_with_approved_workspace_allows_sms() -> None:
    decision = evaluate_contactability(_base_facts(), _approved_policy(), ContactChannel.SMS)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_confirmed_email_permission_allows_email() -> None:
    decision = evaluate_contactability(_base_facts(), _approved_policy(), ContactChannel.EMAIL)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_multiple_sms_blockers_return_deterministic_precedence() -> None:
    facts = replace(
        _base_facts(),
        sms_consent_status=ContactPermissionStatus.DENIED,
        suppressions=frozenset({SuppressionType.SMS_OPT_OUT}),
    )
    policy = WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.NOT_APPROVED,
    )

    decision = evaluate_contactability(facts, policy, ContactChannel.SMS)

    assert decision.allowed is False
    assert decision.reasons == (
        ContactabilityReasonCode.SMS_OPTED_OUT,
        ContactabilityReasonCode.SMS_PERMISSION_DENIED,
    )


def test_missing_do_not_contact_state_fails_safe() -> None:
    facts = replace(_base_facts(), do_not_contact=None)

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.EMAIL)

    assert decision.allowed is False
    assert decision.reasons == (ContactabilityReasonCode.INSUFFICIENT_DATA,)


def test_missing_do_not_contact_state_is_reported_after_channel_reasons() -> None:
    facts = replace(
        _base_facts(),
        do_not_contact=None,
        sms_consent_status=ContactPermissionStatus.UNKNOWN,
        has_sms_destination=False,
        suppressions=frozenset({SuppressionType.SMS_OPT_OUT}),
    )

    decision = evaluate_contactability(facts, _approved_policy(), ContactChannel.SMS)

    assert decision.allowed is False
    assert decision.reasons == (
        ContactabilityReasonCode.SMS_OPTED_OUT,
        ContactabilityReasonCode.MISSING_SMS_CONSENT,
        ContactabilityReasonCode.INSUFFICIENT_DATA,
    )
