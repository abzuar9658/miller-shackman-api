from dataclasses import replace
from uuid import UUID

from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import load_only

from app.application.use_cases.recover_recorded_opt_outs import (
    LeadOptOutRecoveryResult,
    RecordedOptOut,
    RecoverOptOutsRequest,
    RecoveryStatus,
    lead_opt_out_provenance_references,
    plan_recorded_opt_out_recovery,
)
from app.core.database import set_postgres_workspace_context
from app.domain.compliance import ContactSuppressionKind
from app.domain.crm_sync import INBOUND_MESSAGE_RECEIVED_EVENT_TYPE
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    ExternalEventModel,
    InboundMessageModel,
    OutboundMessageModel,
    ProviderMessageEventModel,
)


class PostgresOptOutRecoveryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def recover_lead(
        self, *, request: RecoverOptOutsRequest, lead_id: UUID,
    ) -> LeadOptOutRecoveryResult:
        try:
            return await self._recover_lead(request=request, lead_id=lead_id)
        except (SQLAlchemyError, TimeoutError, OSError):
            # The session context rolls back before reporting. Never render DB
            # exceptions: their text may contain connection details or row values.
            return LeadOptOutRecoveryResult(
                lead_id=lead_id, status=RecoveryStatus.FAILED,
                reasons=("recovery_storage_failure",),
            )

    async def _recover_lead(
        self, *, request: RecoverOptOutsRequest, lead_id: UUID,
    ) -> LeadOptOutRecoveryResult:
        async with self._sessions() as session:
            await set_postgres_workspace_context(session, str(request.workspace_id))
            leads = PostgresLeadRepository(session)
            lead = await leads.get_by_id_for_update(request.workspace_id, lead_id)
            if lead is None:
                return LeadOptOutRecoveryResult(
                    lead_id=lead_id, status=RecoveryStatus.UNRESOLVED,
                    reasons=("lead_not_found",),
                )
            references = set(lead_opt_out_provenance_references(lead))
            # A retained source can contradict a lead's provenance even when its
            # owner/CRM identity keeps it out of that lead's ordinary history.
            source_ids = []
            for kind in ContactSuppressionKind:
                provider = lead.permission_evidence.get(f"{kind.value}_source_provider")
                event_id = lead.permission_evidence.get(f"{kind.value}_source_event_id")
                if isinstance(provider, str) and isinstance(event_id, str):
                    source_ids.append((provider, event_id))
            referenced_source = tuple_(
                ExternalEventModel.provider, ExternalEventModel.provider_event_id,
            ).in_(source_ids)
            result = await session.execute(
                select(ExternalEventModel).where(
                    ExternalEventModel.workspace_id == request.workspace_id,
                    or_(
                        and_(
                            or_(
                                ExternalEventModel.lead_id == lead_id,
                                ExternalEventModel.crm_lead_id == lead.crm_lead_id,
                            ),
                            ExternalEventModel.event_type.startswith(
                                "contact_suppression.", autoescape=True,
                            ),
                        ),
                        and_(
                            referenced_source,
                            ExternalEventModel.event_type != INBOUND_MESSAGE_RECEIVED_EVENT_TYPE,
                        ),
                    ),
                ).limit(request.max_events_per_lead + 1)
            )
            events = result.scalars().all()
            references.update(f"external_events:{event.external_event_id}" for event in events)
            if len(events) > request.max_events_per_lead:
                return LeadOptOutRecoveryResult(
                    lead_id=lead_id, status=RecoveryStatus.UNRESOLVED, candidate=True,
                    reasons=("event_limit_exceeded",), references=tuple(sorted(references)),
                )
            evidence: list[RecordedOptOut] = []
            reasons: set[str] = set()
            for event in events:
                try:
                    evidence.append(_suppression_evidence(event, lead))
                except UnresolvedEvidence as exc:
                    reasons.add(exc.reason)
            inbound_result = await session.execute(
                select(InboundMessageModel, ExternalEventModel).outerjoin(
                    ExternalEventModel,
                    and_(
                        ExternalEventModel.workspace_id == InboundMessageModel.workspace_id,
                        ExternalEventModel.external_event_id
                        == InboundMessageModel.external_event_id,
                    ),
                    full=True,
                ).where(
                    or_(
                        InboundMessageModel.workspace_id == request.workspace_id,
                        ExternalEventModel.workspace_id == request.workspace_id,
                    ),
                    or_(
                        InboundMessageModel.lead_id == lead_id,
                        ExternalEventModel.lead_id == lead_id,
                        ExternalEventModel.crm_lead_id == lead.crm_lead_id,
                        referenced_source,
                    ),
                    or_(
                        InboundMessageModel.inbound_message_id.is_not(None),
                        ExternalEventModel.event_type == INBOUND_MESSAGE_RECEIVED_EVENT_TYPE,
                    ),
                ).options(load_only(
                    InboundMessageModel.inbound_message_id, InboundMessageModel.workspace_id,
                    InboundMessageModel.lead_id, InboundMessageModel.provider,
                    InboundMessageModel.channel, InboundMessageModel.received_at,
                    InboundMessageModel.classification_status,
                )).limit(request.max_events_per_lead - len(events) + 1)
            )
            inbounds = inbound_result.all()
            for inbound, source_event in inbounds:
                if inbound is not None:
                    references.add(f"inbound_messages:{inbound.inbound_message_id}")
                if source_event is not None:
                    references.add(f"external_events:{source_event.external_event_id}")
            if len(events) + len(inbounds) > request.max_events_per_lead:
                return LeadOptOutRecoveryResult(
                    lead_id=lead_id, status=RecoveryStatus.UNRESOLVED, candidate=True,
                    reasons=("event_limit_exceeded",), references=tuple(sorted(references)),
                )
            for inbound, source_event in inbounds:
                try:
                    recorded = _inbound_evidence(inbound, source_event, lead)
                    if recorded is not None:
                        evidence.append(recorded)
                except UnresolvedEvidence as exc:
                    reasons.add(exc.reason)
            delivery_result = await session.execute(
                select(ProviderMessageEventModel).join(
                    OutboundMessageModel,
                    and_(
                        OutboundMessageModel.workspace_id == ProviderMessageEventModel.workspace_id,
                        OutboundMessageModel.message_id
                        == ProviderMessageEventModel.outbound_message_id,
                    ),
                ).where(
                    ProviderMessageEventModel.workspace_id == request.workspace_id,
                    OutboundMessageModel.lead_id == lead_id,
                ).limit(request.max_events_per_lead - len(events) - len(inbounds) + 1)
            )
            deliveries = delivery_result.scalars().all()
            if len(events) + len(inbounds) + len(deliveries) > request.max_events_per_lead:
                return LeadOptOutRecoveryResult(
                    lead_id=lead_id, status=RecoveryStatus.UNRESOLVED, candidate=True,
                    reasons=("event_limit_exceeded",), references=tuple(sorted(references)),
                )
            for delivery in deliveries:
                # The current callback writer stores delivery, not a platform
                # consent decision. Retain explicit unsubscribe hints for review;
                # never turn an arbitrary bounce/failure into an opt-out.
                if (
                    delivery.provider == "twilio"
                    and delivery.payload_redacted.get("error_code") == "21610"
                ) or delivery.event_type in {"unsubscribe", "group_unsubscribe", "unsubscribed"}:
                    reasons.add("provider_unsubscribe_requires_review")
                    references.add(f"provider_message_events:{delivery.provider_event_id}")
            if reasons:
                return LeadOptOutRecoveryResult(
                    lead_id=lead_id, status=RecoveryStatus.UNRESOLVED, candidate=True,
                    reasons=tuple(sorted(reasons)), references=tuple(sorted(references)),
                )
            restored, report = plan_recorded_opt_out_recovery(lead=lead, evidence=tuple(evidence))
            report = replace(report, references=tuple(sorted(references.union(report.references))))
            if request.apply and report.status == RecoveryStatus.WOULD_CHANGE:
                await leads.upsert(restored)
                await session.commit()
                return replace(report, status=RecoveryStatus.CHANGED)
            return report


class UnresolvedEvidence(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _suppression_evidence(event: ExternalEventModel, lead: CanonicalLeadRecord) -> RecordedOptOut:
    if not event.event_type.startswith("contact_suppression."):
        raise UnresolvedEvidence("unverified_suppression_event")
    if event.lead_id is None:
        if event.provider != "follow_up_boss" or lead.crm_provider != CRMProvider.FOLLOW_UP_BOSS:
            raise UnresolvedEvidence("ambiguous_event_identity")
        if event.crm_lead_id != lead.crm_lead_id:
            raise UnresolvedEvidence("conflicting_event_identity")
        if event.status != "ignored" or event.failure_reason != "lead_not_found":
            raise UnresolvedEvidence("unverified_suppression_event")
    elif event.lead_id != lead.lead_id or (
        event.crm_lead_id is not None and event.crm_lead_id != lead.crm_lead_id
    ):
        raise UnresolvedEvidence("conflicting_event_identity")
    elif event.status != "processed":
        raise UnresolvedEvidence("unverified_suppression_event")
    try:
        kind = ContactSuppressionKind(event.event_type.removeprefix("contact_suppression."))
    except ValueError as exc:
        raise UnresolvedEvidence("unknown_suppression_kind") from exc
    try:
        return RecordedOptOut(
            kind=kind, source_provider=event.provider, source_event_id=event.provider_event_id,
            occurred_at=event.received_at, reference=f"external_events:{event.external_event_id}",
        )
    except ValueError as exc:
        raise UnresolvedEvidence("invalid_event_provenance") from exc


def _inbound_evidence(
    inbound: InboundMessageModel | None,
    event: ExternalEventModel | None,
    lead: CanonicalLeadRecord,
) -> RecordedOptOut | None:
    if inbound is None:
        # Retained audit without its matching message is incomplete, not clean.
        raise UnresolvedEvidence("missing_inbound_message")
    if event is None:
        raise UnresolvedEvidence("missing_inbound_source_event")
    if event.event_type != INBOUND_MESSAGE_RECEIVED_EVENT_TYPE:
        raise UnresolvedEvidence("unverified_inbound_processing")
    if (
        inbound.lead_id != lead.lead_id or event.lead_id != lead.lead_id
        or (event.crm_lead_id is not None and event.crm_lead_id != lead.crm_lead_id)
        or inbound.provider != event.provider
    ):
        raise UnresolvedEvidence("conflicting_inbound_identity")
    audit = event.payload_redacted.get("processing_audit")
    if not isinstance(audit, dict):
        raise UnresolvedEvidence("missing_inbound_processing_audit")
    classifier = audit.get("classifier")
    decision = audit.get("decision")
    if not isinstance(classifier, dict) or not isinstance(decision, dict):
        raise UnresolvedEvidence("invalid_inbound_processing_audit")
    if (
        event.status != "processed" or inbound.classification_status != "classified"
        or classifier.get("status") != "classified"
    ):
        raise UnresolvedEvidence("unverified_inbound_processing")
    # These are the recorded application decisions that actually wrote a block.
    # Never infer one from the body, intent label, or provider message ID.
    if not isinstance(classifier.get("opt_out_detected"), bool):
        raise UnresolvedEvidence("invalid_inbound_processing_audit")
    if classifier.get("opt_out_detected") is not True and decision.get("reply_route") != "suppress":
        if decision.get("inbound_action") == "suppress":
            raise UnresolvedEvidence("unverified_inbound_suppression")
        if any(
            lead.permission_evidence.get(f"{kind.value}_source_provider") == event.provider
            and lead.permission_evidence.get(f"{kind.value}_source_event_id")
            == event.provider_event_id
            for kind in ContactSuppressionKind
        ):
            raise UnresolvedEvidence("conflicting_platform_provenance")
        return None
    if decision.get("inbound_action") != "suppress":
        raise UnresolvedEvidence("conflicting_inbound_processing_audit")
    kinds = {"sms": ContactSuppressionKind.SMS_OPT_OUT,
             "email": ContactSuppressionKind.EMAIL_UNSUBSCRIBED}
    if inbound.channel not in kinds:
        raise UnresolvedEvidence("unknown_inbound_channel")
    try:
        return RecordedOptOut(
            kind=kinds[inbound.channel], source_provider=event.provider,
            source_event_id=event.provider_event_id, occurred_at=inbound.received_at,
            reference=f"external_events:{event.external_event_id}",
        )
    except ValueError as exc:
        raise UnresolvedEvidence("invalid_event_provenance") from exc