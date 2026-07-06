from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from app.domain.campaigns.start_queue import (
    CampaignStartCandidate,
    CampaignStartContext,
    CampaignStartPolicy,
    CampaignStatus,
    StartQueueReasonCode,
    evaluate_campaign_start_batch,
)
from app.domain.compliance.enrollment import (
    CampaignEnrollmentDecision,
    EnrollmentSource,
)

NOW = datetime(2026, 7, 6, 12, 0, 0)
USE_DEFAULT_ELIGIBLE_AT: Final = object()


def _policy(
    daily_start_cap: int = 50,
    require_preflight_digest_for_first_batch: bool = True,
    veto_window_hours: int = 24,
    agentless_dormant_threshold_days: int = 60,
) -> CampaignStartPolicy:
    return CampaignStartPolicy(
        daily_start_cap=daily_start_cap,
        require_preflight_digest_for_first_batch=require_preflight_digest_for_first_batch,
        veto_window_hours=veto_window_hours,
        agentless_dormant_threshold_days=agentless_dormant_threshold_days,
    )


def _context(
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    started_today_count: int = 0,
    is_first_batch: bool = True,
    digest_sent_at: datetime | None = None,
    vetoed_lead_ids: frozenset[UUID] | None = None,
) -> CampaignStartContext:
    return CampaignStartContext(
        campaign_status=campaign_status,
        started_today_count=started_today_count,
        is_first_batch=is_first_batch,
        digest_sent_at=digest_sent_at,
        vetoed_lead_ids=vetoed_lead_ids or frozenset(),
    )


def _candidate(
    *,
    eligible: bool = True,
    eligible_at: datetime | None | object = USE_DEFAULT_ELIGIBLE_AT,
    source: EnrollmentSource = EnrollmentSource.CRM_TAG,
    has_assigned_agent: bool | None = True,
    days_since_last_meaningful_communication: int | None = None,
    lead_id: UUID | None = None,
) -> CampaignStartCandidate:
    resolved_eligible_at: datetime | None
    if eligible_at is USE_DEFAULT_ELIGIBLE_AT:
        resolved_eligible_at = NOW - timedelta(days=1) if eligible else None
    else:
        assert isinstance(eligible_at, datetime) or eligible_at is None
        resolved_eligible_at = eligible_at

    return CampaignStartCandidate(
        lead_id=lead_id or uuid4(),
        enrollment_decision=CampaignEnrollmentDecision(
            eligible=eligible,
            source=source,
            eligible_at=resolved_eligible_at,
        ),
        has_assigned_agent=has_assigned_agent,
        days_since_last_meaningful_communication=days_since_last_meaningful_communication,
    )


def test_active_campaign_selects_oldest_candidates_up_to_daily_cap() -> None:
    oldest = _candidate(eligible_at=NOW - timedelta(days=5))
    middle = _candidate(eligible_at=NOW - timedelta(days=3))
    newest = _candidate(eligible_at=NOW - timedelta(days=1))

    decision = evaluate_campaign_start_batch(
        [newest, middle, oldest],
        _policy(daily_start_cap=2, require_preflight_digest_for_first_batch=False),
        _context(is_first_batch=False),
        NOW,
    )

    assert [item.lead_id for item in decision.selected] == [oldest.lead_id, middle.lead_id]
    assert decision.held_back[0].reasons == (StartQueueReasonCode.DAILY_CAP_REACHED,)


def test_inactive_campaign_holds_back_all_candidates() -> None:
    candidate = _candidate()

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(require_preflight_digest_for_first_batch=False),
        _context(campaign_status=CampaignStatus.PAUSED, is_first_batch=False),
        NOW,
    )

    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.CAMPAIGN_INACTIVE,)


def test_unassigned_leads_are_held_back() -> None:
    candidate = _candidate(has_assigned_agent=False)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(require_preflight_digest_for_first_batch=False),
        _context(is_first_batch=False),
        NOW,
    )

    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.MISSING_ASSIGNED_AGENT,)


def test_crm_tag_candidate_skips_preflight_digest_before_selection() -> None:
    candidate = _candidate(source=EnrollmentSource.CRM_TAG)

    decision = evaluate_campaign_start_batch([candidate], _policy(), _context(), NOW)

    assert decision.digest_required is False
    assert [item.lead_id for item in decision.selected] == [candidate.lead_id]
    assert not decision.held_back


def test_assigned_dormant_selector_first_batch_requires_preflight_digest() -> None:
    candidate = _candidate(source=EnrollmentSource.DORMANT_SELECTOR)

    decision = evaluate_campaign_start_batch([candidate], _policy(), _context(), NOW)

    assert decision.digest_required is True
    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.PREFLIGHT_DIGEST_PENDING,)


def test_veto_window_not_expired_holds_back_candidates() -> None:
    candidate = _candidate(source=EnrollmentSource.DORMANT_SELECTOR)
    digest_sent_at = NOW - timedelta(hours=2)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(veto_window_hours=24),
        _context(digest_sent_at=digest_sent_at),
        NOW,
    )

    assert not decision.selected
    assert decision.veto_window_expires_at == digest_sent_at + timedelta(hours=24)
    assert decision.held_back[0].reasons == (StartQueueReasonCode.VETO_WINDOW_NOT_EXPIRED,)


def test_vetoed_lead_is_held_back_after_window_expires() -> None:
    candidate = _candidate(source=EnrollmentSource.DORMANT_SELECTOR)
    digest_sent_at = NOW - timedelta(hours=30)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(veto_window_hours=24),
        _context(digest_sent_at=digest_sent_at, vetoed_lead_ids=frozenset({candidate.lead_id})),
        NOW,
    )

    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.AGENT_VETOED,)


def test_non_vetoed_lead_starts_after_window_expires() -> None:
    candidate = _candidate(source=EnrollmentSource.DORMANT_SELECTOR)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(veto_window_hours=24),
        _context(digest_sent_at=NOW - timedelta(hours=30)),
        NOW,
    )

    assert [item.lead_id for item in decision.selected] == [candidate.lead_id]
    assert not decision.held_back


def test_old_unassigned_dormant_selector_lead_starts_without_digest() -> None:
    candidate = _candidate(
        source=EnrollmentSource.DORMANT_SELECTOR,
        has_assigned_agent=False,
        days_since_last_meaningful_communication=60,
    )

    decision = evaluate_campaign_start_batch([candidate], _policy(), _context(), NOW)

    assert decision.digest_required is False
    assert [item.lead_id for item in decision.selected] == [candidate.lead_id]
    assert not decision.held_back


def test_unassigned_dormant_selector_below_threshold_is_held_back() -> None:
    candidate = _candidate(
        source=EnrollmentSource.DORMANT_SELECTOR,
        has_assigned_agent=False,
        days_since_last_meaningful_communication=59,
    )

    decision = evaluate_campaign_start_batch([candidate], _policy(), _context(), NOW)

    assert not decision.selected
    assert decision.digest_required is False
    assert decision.held_back[0].reasons == (StartQueueReasonCode.MISSING_ASSIGNED_AGENT,)


def test_agentless_dormant_threshold_is_configurable() -> None:
    candidate = _candidate(
        source=EnrollmentSource.DORMANT_SELECTOR,
        has_assigned_agent=False,
        days_since_last_meaningful_communication=60,
    )

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(agentless_dormant_threshold_days=90),
        _context(),
        NOW,
    )

    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.MISSING_ASSIGNED_AGENT,)


def test_duplicate_candidates_are_deduplicated_and_count_once() -> None:
    lead_id = uuid4()
    first = _candidate(lead_id=lead_id, eligible_at=NOW - timedelta(days=4))
    duplicate = _candidate(lead_id=lead_id, eligible_at=NOW - timedelta(days=2))

    decision = evaluate_campaign_start_batch(
        [first, duplicate],
        _policy(require_preflight_digest_for_first_batch=False),
        _context(is_first_batch=False),
        NOW,
    )

    assert len(decision.selected) == 1
    assert decision.selected[0].lead_id == lead_id
    assert decision.held_back[0].reasons == (StartQueueReasonCode.DUPLICATE_CANDIDATE,)


def test_non_enrollment_eligible_candidates_are_held_back() -> None:
    candidate = _candidate(eligible=False, eligible_at=None)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(require_preflight_digest_for_first_batch=False),
        _context(is_first_batch=False),
        NOW,
    )

    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.NOT_ENROLLMENT_ELIGIBLE,)


def test_missing_eligible_timestamp_fails_safe() -> None:
    candidate = _candidate(eligible=True, eligible_at=None)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(require_preflight_digest_for_first_batch=False),
        _context(is_first_batch=False),
        NOW,
    )

    assert not decision.selected
    assert decision.held_back[0].reasons == (StartQueueReasonCode.MISSING_ELIGIBLE_AT,)


def test_started_today_reduces_remaining_daily_capacity() -> None:
    oldest = _candidate(eligible_at=NOW - timedelta(days=3))
    newest = _candidate(eligible_at=NOW - timedelta(days=1))

    decision = evaluate_campaign_start_batch(
        [newest, oldest],
        _policy(daily_start_cap=2, require_preflight_digest_for_first_batch=False),
        _context(is_first_batch=False, started_today_count=1),
        NOW,
    )

    assert [item.lead_id for item in decision.selected] == [oldest.lead_id]
    assert decision.held_back[0].reasons == (StartQueueReasonCode.DAILY_CAP_REACHED,)


def test_multiple_blocking_reasons_are_returned_in_precedence_order() -> None:
    candidate = _candidate(eligible=False, eligible_at=None, has_assigned_agent=None)

    decision = evaluate_campaign_start_batch(
        [candidate],
        _policy(),
        _context(campaign_status=CampaignStatus.DRAFT),
        NOW,
    )

    assert decision.held_back[0].reasons == (
        StartQueueReasonCode.CAMPAIGN_INACTIVE,
        StartQueueReasonCode.NOT_ENROLLMENT_ELIGIBLE,
        StartQueueReasonCode.MISSING_ASSIGNED_AGENT,
    )