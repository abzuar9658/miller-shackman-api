from datetime import datetime, timedelta

from app.domain.compliance.contactability import (
    ContactabilityDecision,
    ContactChannel,
)
from app.domain.compliance.enrollment import (
    CampaignEnrollmentDecision,
    CampaignEnrollmentFacts,
    CampaignEnrollmentPolicy,
    EnrollmentReasonCode,
    EnrollmentSource,
    evaluate_campaign_enrollment,
    sort_enrollment_candidates_fifo,
)

NOW = datetime(2026, 7, 6, 12, 0, 0)


def _base_policy() -> CampaignEnrollmentPolicy:
    return CampaignEnrollmentPolicy()


def _sms_contactability_decision(allowed: bool) -> ContactabilityDecision:
    return ContactabilityDecision(
        allowed=allowed,
        channel=ContactChannel.SMS,
        reasons=(),
    )


def _email_contactability_decision(allowed: bool) -> ContactabilityDecision:
    return ContactabilityDecision(
        allowed=allowed,
        channel=ContactChannel.EMAIL,
        reasons=(),
    )


def _contactable_sms_facts() -> CampaignEnrollmentFacts:
    return CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )


def test_default_policy_allows_both_v1_sources() -> None:
    policy = CampaignEnrollmentPolicy()

    assert EnrollmentSource.CRM_TAG in policy.allowed_sources
    assert EnrollmentSource.DORMANT_SELECTOR in policy.allowed_sources


def test_crm_tag_eligible_when_channel_contactable() -> None:
    decision = evaluate_campaign_enrollment(_contactable_sms_facts(), _base_policy(), NOW)

    assert decision.eligible is True
    assert decision.source == EnrollmentSource.CRM_TAG


def test_dormant_selector_eligible_when_threshold_met_and_data_complete() -> None:
    last_comm = NOW - timedelta(days=90)
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
        last_meaningful_communication_at=last_comm,
        activity_data_complete=True,
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is True
    assert decision.source == EnrollmentSource.DORMANT_SELECTOR
    assert decision.eligible_at == last_comm + timedelta(days=60)


def test_dormant_selector_blocked_when_lead_not_dormant() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
        last_meaningful_communication_at=NOW - timedelta(days=30),
        activity_data_complete=True,
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.LEAD_NOT_DORMANT,)


def test_incomplete_activity_data_blocks_dormant_selector() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
        last_meaningful_communication_at=NOW - timedelta(days=90),
        activity_data_complete=False,
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.ACTIVITY_DATA_INCOMPLETE,)


def test_uncertain_activity_data_blocks_dormant_selector() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
        last_meaningful_communication_at=NOW - timedelta(days=90),
        activity_data_complete=None,
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.ACTIVITY_DATA_INCOMPLETE,)


def test_no_contactable_enabled_channels_blocks_enrollment() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=False),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.NO_CAMPAIGN_CHANNELS_CONTACTABLE,)



def test_unsupported_enrollment_source_excluded() -> None:
    policy = CampaignEnrollmentPolicy(allowed_sources=frozenset({EnrollmentSource.CRM_TAG}))
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, policy, NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.UNSUPPORTED_ENROLLMENT_SOURCE,)


def test_both_sources_apply_crm_tag_wins() -> None:
    last_comm = NOW - timedelta(days=90)
    tag_observed = NOW - timedelta(days=1)
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG, EnrollmentSource.DORMANT_SELECTOR}),
        enrollment_tag_observed_at=tag_observed,
        last_meaningful_communication_at=last_comm,
        activity_data_complete=True,
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is True
    assert decision.source == EnrollmentSource.CRM_TAG
    assert decision.eligible_at == tag_observed


def test_missing_enrollment_trigger_not_eligible() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset(),
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.MISSING_ENROLLMENT_TRIGGER,)


def test_empty_enabled_channels_blocks_enrollment() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=frozenset(),
        channel_contactability={},
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.NO_CAMPAIGN_CHANNELS_CONTACTABLE,)


def test_missing_contactability_decision_treated_as_not_contactable() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={},
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is False
    assert decision.reasons == (EnrollmentReasonCode.NO_CAMPAIGN_CHANNELS_CONTACTABLE,)


def test_mixed_channels_eligible_if_at_least_one_contactable() -> None:
    facts = CampaignEnrollmentFacts(
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=frozenset({ContactChannel.SMS, ContactChannel.EMAIL}),
        channel_contactability={
            ContactChannel.SMS: _sms_contactability_decision(allowed=False),
            ContactChannel.EMAIL: _email_contactability_decision(allowed=True),
        },
    )

    decision = evaluate_campaign_enrollment(facts, _base_policy(), NOW)

    assert decision.eligible is True
    assert decision.source == EnrollmentSource.CRM_TAG


def test_fifo_sorts_by_oldest_eligible_at() -> None:
    decisions = [
        CampaignEnrollmentDecision(
            eligible=True,
            source=EnrollmentSource.CRM_TAG,
            eligible_at=NOW - timedelta(days=1),
        ),
        CampaignEnrollmentDecision(
            eligible=True,
            source=EnrollmentSource.DORMANT_SELECTOR,
            eligible_at=NOW - timedelta(days=5),
        ),
        CampaignEnrollmentDecision(
            eligible=True,
            source=EnrollmentSource.CRM_TAG,
            eligible_at=NOW - timedelta(days=2),
        ),
    ]

    sorted_decisions = sort_enrollment_candidates_fifo(decisions)

    assert [d.eligible_at for d in sorted_decisions] == [
        NOW - timedelta(days=5),
        NOW - timedelta(days=2),
        NOW - timedelta(days=1),
    ]


def test_fifo_skips_ineligible_and_missing_eligible_at() -> None:
    decisions = [
        CampaignEnrollmentDecision(
            eligible=False,
            source=EnrollmentSource.DORMANT_SELECTOR,
            reasons=(EnrollmentReasonCode.LEAD_NOT_DORMANT,),
        ),
        CampaignEnrollmentDecision(
            eligible=True,
            source=EnrollmentSource.CRM_TAG,
            eligible_at=NOW - timedelta(days=1),
        ),
        CampaignEnrollmentDecision(
            eligible=True,
            source=EnrollmentSource.CRM_TAG,
            eligible_at=None,
        ),
    ]

    sorted_decisions = sort_enrollment_candidates_fifo(decisions)

    assert len(sorted_decisions) == 1
    assert sorted_decisions[0].eligible_at == NOW - timedelta(days=1)
