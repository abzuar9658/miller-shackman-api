from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.application.use_cases.process_contact_suppression_event import (
    lead_with_contact_suppression,
)
from app.domain.compliance import ContactSuppressionKind, SuppressionType
from app.domain.leads import CanonicalLeadRecord

_PROVENANCE_SUFFIXES = ("source_provider", "source_event_id", "occurred_at")


class RecordedOptOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ContactSuppressionKind
    source_provider: str = Field(min_length=1, pattern=r"\S")
    source_event_id: str = Field(min_length=1, pattern=r"\S")
    occurred_at: AwareDatetime
    reference: str


class RecoverOptOutsRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: UUID
    lead_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    apply: bool = False
    reviewed_for_lifts: bool = False
    consent_review_hold_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    max_events_per_lead: int = Field(default=1000, ge=1, le=10000)

    @field_validator("lead_ids", "consent_review_hold_ids")
    @classmethod
    def unique_lead_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if any(lead_id.int == 0 for lead_id in value):
            raise ValueError("lead IDs must be non-nil")
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.workspace_id.int == 0:
            raise ValueError("workspace ID must be non-nil")
        if self.apply and not self.reviewed_for_lifts:
            raise ValueError("apply requires explicit review for later legitimate lifts")
        if not set(self.consent_review_hold_ids).issubset(self.lead_ids):
            raise ValueError("consent-review holds must be in the requested lead scope")
        return self


class RecoveryStatus(StrEnum):
    CLEAN = "clean"
    WOULD_CHANGE = "would_change"
    CHANGED = "changed"
    ALREADY_CORRECT = "already_correct"
    UNRESOLVED = "unresolved"
    FAILED = "failed"


@dataclass(frozen=True)
class LeadOptOutRecoveryResult:
    lead_id: UUID
    status: RecoveryStatus
    candidate: bool = False
    reasons: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptOutRecoveryReport:
    leads: tuple[LeadOptOutRecoveryResult, ...]

    @property
    def candidate(self) -> int:
        return sum(lead.candidate for lead in self.leads)

    @property
    def changed(self) -> int:
        return sum(lead.status == RecoveryStatus.CHANGED for lead in self.leads)

    @property
    def would_change(self) -> int:
        return sum(lead.status == RecoveryStatus.WOULD_CHANGE for lead in self.leads)

    @property
    def already_correct(self) -> int:
        return sum(lead.status == RecoveryStatus.ALREADY_CORRECT for lead in self.leads)

    @property
    def unresolved(self) -> int:
        return sum(lead.status == RecoveryStatus.UNRESOLVED for lead in self.leads)

    @property
    def failed(self) -> int:
        return sum(lead.status == RecoveryStatus.FAILED for lead in self.leads)


class OptOutRecoveryRepository(Protocol):
    async def recover_lead(
        self, *, request: RecoverOptOutsRequest, lead_id: UUID,
    ) -> LeadOptOutRecoveryResult: ...


def lead_opt_out_provenance_references(lead: CanonicalLeadRecord) -> tuple[str, ...]:
    # Partial tuples are evidence for an operator to inspect, not accepted facts.
    return tuple(
        f"leads:{lead.lead_id}:{kind.value}"
        for kind in ContactSuppressionKind
        if any(
            f"{kind.value}_{suffix}" in lead.permission_evidence for suffix in _PROVENANCE_SUFFIXES
        )
    )


def plan_recorded_opt_out_recovery(
    *, lead: CanonicalLeadRecord, evidence: tuple[RecordedOptOut, ...],
) -> tuple[CanonicalLeadRecord, LeadOptOutRecoveryResult]:
    selected: dict[ContactSuppressionKind, RecordedOptOut] = {}
    seen: dict[tuple[str, str], RecordedOptOut] = {}
    reasons: set[str] = set()
    for event in sorted(
        evidence, key=lambda item: (item.occurred_at, item.source_provider, item.source_event_id),
    ):
        previous = seen.setdefault((event.source_provider, event.source_event_id), event)
        if previous.kind != event.kind or previous.occurred_at != event.occurred_at:
            reasons.add("conflicting_event_provenance")
        selected.setdefault(event.kind, event)
    original_evidence: dict[str, str] = {}
    active_restrictions = {
        ContactSuppressionKind.SMS_OPT_OUT:
            lead.sms_opted_out or SuppressionType.SMS_OPT_OUT in lead.suppression_types,
        ContactSuppressionKind.EMAIL_UNSUBSCRIBED:
            lead.email_unsubscribed or SuppressionType.EMAIL_UNSUBSCRIBED in lead.suppression_types,
        ContactSuppressionKind.DO_NOT_CONTACT: lead.do_not_contact is True,
    }
    for kind in ContactSuppressionKind:
        prefix = kind.value
        keys = tuple(f"{prefix}_{suffix}" for suffix in _PROVENANCE_SUFFIXES)
        if any(key in lead.permission_evidence for key in keys):
            try:
                recorded = RecordedOptOut(
                    kind=kind, source_provider=lead.permission_evidence.get(keys[0], ""),
                    source_event_id=lead.permission_evidence.get(keys[1], ""),
                    occurred_at=datetime.fromisoformat(lead.permission_evidence.get(keys[2], "")),
                    reference=f"leads:{lead.lead_id}:{prefix}",
                )
            except (TypeError, ValueError):
                reasons.add("partial_platform_provenance")
                continue
            # Use the same source-identity ledger for retained history and local
            # tuples; one event cannot establish contradictory channel facts.
            previous = seen.setdefault(
                (recorded.source_provider, recorded.source_event_id), recorded,
            )
            if previous.kind != recorded.kind or previous.occurred_at != recorded.occurred_at:
                reasons.add("conflicting_platform_provenance")
            selected[kind] = recorded
            original_evidence.update({key: lead.permission_evidence[key] for key in keys})
        elif active_restrictions[kind] and kind not in selected:
            crm_marker = "sms_opted_out_source" if kind == ContactSuppressionKind.SMS_OPT_OUT else (
                f"{prefix}_source"
            )
            if lead.permission_evidence.get(crm_marker) != "follow_up_boss.customFields":
                reasons.add("missing_evidence")
    references = tuple(sorted(
        {event.reference for event in evidence}.union(lead_opt_out_provenance_references(lead)),
    ))
    if reasons:
        return lead, LeadOptOutRecoveryResult(
            lead_id=lead.lead_id, status=RecoveryStatus.UNRESOLVED, candidate=True,
            reasons=tuple(sorted(reasons)), references=references,
        )
    restored = lead
    for event in selected.values():
        restored = lead_with_contact_suppression(
            lead=restored, suppression_kind=event.kind,
            source_provider=event.source_provider, source_event_id=event.source_event_id,
            occurred_at=event.occurred_at,
        )
    # Keep the exact recorded text as well as the instant (including its offset).
    restored = replace(restored, permission_evidence={
        **restored.permission_evidence, **original_evidence,
    })
    status = RecoveryStatus.CLEAN
    if selected:
        status = RecoveryStatus.WOULD_CHANGE if restored != lead else RecoveryStatus.ALREADY_CORRECT
    return restored, LeadOptOutRecoveryResult(
        lead_id=lead.lead_id, status=status, candidate=bool(selected),
        references=references,
    )


async def recover_recorded_opt_outs(
    *, request: RecoverOptOutsRequest, repository: OptOutRecoveryRepository,
) -> OptOutRecoveryReport:
    results = []
    for lead_id in request.lead_ids:
        if lead_id in request.consent_review_hold_ids:
            results.append(LeadOptOutRecoveryResult(
                lead_id=lead_id, status=RecoveryStatus.UNRESOLVED,
                reasons=("operator_consent_review_hold",),
            ))
            continue
        results.append(await repository.recover_lead(request=request, lead_id=lead_id))
    return OptOutRecoveryReport(leads=tuple(results))