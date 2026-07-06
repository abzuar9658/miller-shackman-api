from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.common.ids import LeadId
from app.domain.compliance.enrollment import CampaignEnrollmentDecision, EnrollmentSource


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"


class StartQueueReasonCode(StrEnum):
    CAMPAIGN_INACTIVE = "campaign_inactive"
    NOT_ENROLLMENT_ELIGIBLE = "not_enrollment_eligible"
    MISSING_ASSIGNED_AGENT = "missing_assigned_agent"
    PREFLIGHT_DIGEST_PENDING = "preflight_digest_pending"
    VETO_WINDOW_NOT_EXPIRED = "veto_window_not_expired"
    AGENT_VETOED = "agent_vetoed"
    DAILY_CAP_REACHED = "daily_cap_reached"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    MISSING_ELIGIBLE_AT = "missing_eligible_at"


@dataclass(frozen=True)
class CampaignStartPolicy:
    daily_start_cap: int = 50
    require_preflight_digest_for_first_batch: bool = True
    veto_window_hours: int = 24
    agentless_dormant_threshold_days: int = 60


@dataclass(frozen=True)
class CampaignStartContext:
    campaign_status: CampaignStatus
    started_today_count: int = 0
    is_first_batch: bool = True
    digest_sent_at: datetime | None = None
    vetoed_lead_ids: frozenset[LeadId] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CampaignStartCandidate:
    lead_id: LeadId
    enrollment_decision: CampaignEnrollmentDecision
    has_assigned_agent: bool | None
    days_since_last_meaningful_communication: int | None = None


@dataclass(frozen=True)
class CampaignStartCandidateDecision:
    selected: bool
    lead_id: LeadId
    selected_at: datetime | None = None
    reasons: tuple[StartQueueReasonCode, ...] = ()


@dataclass(frozen=True)
class CampaignStartBatchDecision:
    selected: tuple[CampaignStartCandidateDecision, ...]
    held_back: tuple[CampaignStartCandidateDecision, ...]
    digest_required: bool
    veto_window_expires_at: datetime | None = None


def evaluate_campaign_start_batch(
    candidates: Iterable[CampaignStartCandidate],
    policy: CampaignStartPolicy,
    context: CampaignStartContext,
    now: datetime,
) -> CampaignStartBatchDecision:
    candidate_list = tuple(candidates)
    digest_required = _digest_required(candidate_list, policy, context)
    veto_window_expires_at = _batch_veto_window_expires_at(candidate_list, policy, context)
    seen_lead_ids: set[LeadId] = set()
    held_back: list[CampaignStartCandidateDecision] = []
    startable: list[CampaignStartCandidate] = []

    for candidate in candidate_list:
        if candidate.lead_id in seen_lead_ids:
            held_back.append(
                CampaignStartCandidateDecision(
                    selected=False,
                    lead_id=candidate.lead_id,
                    reasons=(StartQueueReasonCode.DUPLICATE_CANDIDATE,),
                ),
            )
            continue

        seen_lead_ids.add(candidate.lead_id)
        reasons = _candidate_reasons(candidate, policy, context, now)
        if reasons:
            held_back.append(
                CampaignStartCandidateDecision(
                    selected=False,
                    lead_id=candidate.lead_id,
                    reasons=tuple(reasons),
                ),
            )
            continue

        startable.append(candidate)

    ordered = sorted(startable, key=_eligible_at)
    remaining_capacity = max(policy.daily_start_cap - context.started_today_count, 0)
    selected = tuple(
        CampaignStartCandidateDecision(
            selected=True,
            lead_id=candidate.lead_id,
            selected_at=now,
        )
        for candidate in ordered[:remaining_capacity]
    )
    held_back.extend(
        CampaignStartCandidateDecision(
            selected=False,
            lead_id=candidate.lead_id,
            reasons=(StartQueueReasonCode.DAILY_CAP_REACHED,),
        )
        for candidate in ordered[remaining_capacity:]
    )

    return CampaignStartBatchDecision(
        selected=selected,
        held_back=tuple(held_back),
        digest_required=digest_required,
        veto_window_expires_at=veto_window_expires_at,
    )


def _candidate_reasons(
    candidate: CampaignStartCandidate,
    policy: CampaignStartPolicy,
    context: CampaignStartContext,
    now: datetime,
) -> list[StartQueueReasonCode]:
    reasons: list[StartQueueReasonCode] = []

    if context.campaign_status != CampaignStatus.ACTIVE:
        reasons.append(StartQueueReasonCode.CAMPAIGN_INACTIVE)
    if not candidate.enrollment_decision.eligible:
        reasons.append(StartQueueReasonCode.NOT_ENROLLMENT_ELIGIBLE)
    if candidate.has_assigned_agent is not True and not _can_start_without_assigned_agent(
        candidate,
        policy,
    ):
        reasons.append(StartQueueReasonCode.MISSING_ASSIGNED_AGENT)
    if candidate.enrollment_decision.eligible and candidate.enrollment_decision.eligible_at is None:
        reasons.append(StartQueueReasonCode.MISSING_ELIGIBLE_AT)
    if not _preflight_applies(candidate, policy, context):
        return reasons
    if context.digest_sent_at is None:
        reasons.append(StartQueueReasonCode.PREFLIGHT_DIGEST_PENDING)
        return reasons

    veto_window_expires_at = _veto_window_expires_at(policy, context)
    assert veto_window_expires_at is not None
    if now < veto_window_expires_at:
        reasons.append(StartQueueReasonCode.VETO_WINDOW_NOT_EXPIRED)
    elif candidate.lead_id in context.vetoed_lead_ids:
        reasons.append(StartQueueReasonCode.AGENT_VETOED)

    return reasons


def _preflight_applies(
    candidate: CampaignStartCandidate,
    policy: CampaignStartPolicy,
    context: CampaignStartContext,
) -> bool:
    return (
        policy.require_preflight_digest_for_first_batch
        and context.is_first_batch
        and candidate.enrollment_decision.eligible
        and candidate.enrollment_decision.eligible_at is not None
        and candidate.enrollment_decision.source == EnrollmentSource.DORMANT_SELECTOR
        and candidate.has_assigned_agent is True
    )


def _can_start_without_assigned_agent(
    candidate: CampaignStartCandidate,
    policy: CampaignStartPolicy,
) -> bool:
    return (
        candidate.enrollment_decision.source == EnrollmentSource.DORMANT_SELECTOR
        and candidate.days_since_last_meaningful_communication is not None
        and candidate.days_since_last_meaningful_communication
        >= policy.agentless_dormant_threshold_days
    )


def _digest_required(
    candidates: tuple[CampaignStartCandidate, ...],
    policy: CampaignStartPolicy,
    context: CampaignStartContext,
) -> bool:
    return any(
        _preflight_applies(candidate, policy, context) for candidate in candidates
    ) and context.digest_sent_at is None


def _batch_veto_window_expires_at(
    candidates: tuple[CampaignStartCandidate, ...],
    policy: CampaignStartPolicy,
    context: CampaignStartContext,
) -> datetime | None:
    if not any(_preflight_applies(candidate, policy, context) for candidate in candidates):
        return None
    return _veto_window_expires_at(policy, context)


def _veto_window_expires_at(
    policy: CampaignStartPolicy,
    context: CampaignStartContext,
) -> datetime | None:
    if context.digest_sent_at is None:
        return None
    return context.digest_sent_at + timedelta(hours=policy.veto_window_hours)


def _eligible_at(candidate: CampaignStartCandidate) -> datetime:
    eligible_at = candidate.enrollment_decision.eligible_at
    assert eligible_at is not None
    return eligible_at