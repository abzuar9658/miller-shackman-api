from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactPermissionStatus, SuppressionType
from app.domain.leads import (
    ActivityReliability,
    AssignmentResolutionStatus,
    CanonicalLeadRecord,
    CRMProvider,
    EffectiveOwnerSource,
    LeadClassificationReason,
    LeadPausedSearchHistoryEntry,
    LeadPausedSearchProfile,
    LeadType,
    PausedSearchAction,
    PausedSearchReasonCode,
    PausedSearchSource,
    PropertyEventType,
)
from app.infrastructure.persistence.postgres.models import LeadModel, LeadPausedSearchHistoryModel


class PostgresLeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalLeadRecord, ...]:
        result = await self._session.execute(
            select(LeadModel)
            .where(LeadModel.workspace_id == workspace_id)
            .order_by(
                LeadModel.last_activity_at.desc().nulls_last(), LeadModel.facts_derived_at.desc()
            )
            .limit(limit),
        )
        return tuple(_model_to_record(model) for model in result.scalars().all())

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        result = await self._session.execute(
            _by_id_statement(
                workspace_id=workspace_id,
                lead_id=lead_id,
                for_update=False,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_record(model) if model else None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        result = await self._session.execute(
            _by_id_statement(
                workspace_id=workspace_id,
                lead_id=lead_id,
                for_update=True,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_record(model) if model else None

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        result = await self._session.execute(
            select(LeadModel).where(
                LeadModel.workspace_id == workspace_id,
                LeadModel.crm_provider == crm_provider.value,
                LeadModel.crm_lead_id == crm_lead_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_record(model) if model else None

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: WorkspaceId,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        normalized_agent_id = assigned_agent_crm_id.strip()
        if not normalized_agent_id:
            return ()
        result = await self._session.execute(
            select(LeadModel)
            .where(
                LeadModel.workspace_id == workspace_id,
                LeadModel.assigned_agent_crm_id == normalized_agent_id,
            )
            .order_by(LeadModel.updated_at.desc()),
        )
        return tuple(_model_to_record(model) for model in result.scalars().all())

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        normalized_candidates = _phone_match_candidates(phone_number)
        if not normalized_candidates:
            return None
        normalized_phone = func.regexp_replace(LeadModel.primary_phone, "[^0-9]", "", "g")
        result = await self._session.execute(
            select(LeadModel)
            .where(LeadModel.workspace_id == workspace_id)
            .where(LeadModel.primary_phone.is_not(None))
            .where(normalized_phone.in_(tuple(normalized_candidates)))
            .limit(2),
        )
        models = result.scalars().all()
        if len(models) != 1:
            return None
        return _model_to_record(models[0])

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        normalized_email = _normalized_email(email_address)
        if normalized_email is None:
            return None
        normalized_primary_email = func.lower(func.btrim(LeadModel.primary_email))
        result = await self._session.execute(
            select(LeadModel)
            .where(LeadModel.workspace_id == workspace_id)
            .where(LeadModel.primary_email.is_not(None))
            .where(normalized_primary_email == normalized_email)
            .limit(2),
        )
        models = result.scalars().all()
        if len(models) != 1:
            return None
        return _model_to_record(models[0])

    async def list_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        normalized_email = _normalized_email(email_address)
        if normalized_email is None:
            return ()
        normalized_primary_email = func.lower(func.btrim(LeadModel.primary_email))
        result = await self._session.execute(
            select(LeadModel)
            .where(LeadModel.workspace_id == workspace_id)
            .where(LeadModel.primary_email.is_not(None))
            .where(normalized_primary_email == normalized_email),
        )
        return tuple(_model_to_record(model) for model in result.scalars().all())

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        now = datetime.now(UTC)
        values = _record_to_values(record, created_at=now, updated_at=now)
        update_values = {
            key: value for key, value in values.items() if key not in {"lead_id", "created_at"}
        }
        update_values["updated_at"] = now

        statement = (
            insert(LeadModel)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_leads_workspace_crm_identity",
                set_=update_values,
            )
            .returning(LeadModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one()
        return _model_to_record(model)

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadPausedSearchHistoryEntry, ...]:
        result = await self._session.execute(
            select(LeadPausedSearchHistoryModel)
            .where(
                LeadPausedSearchHistoryModel.workspace_id == workspace_id,
                LeadPausedSearchHistoryModel.lead_id == lead_id,
            )
            .order_by(
                LeadPausedSearchHistoryModel.created_at.desc(),
                LeadPausedSearchHistoryModel.history_id.desc(),
            )
            .limit(limit)
        )
        return tuple(_history_model_to_entry(model) for model in result.scalars().all())

    async def append(
        self,
        entry: LeadPausedSearchHistoryEntry,
    ) -> LeadPausedSearchHistoryEntry:
        statement = (
            insert(LeadPausedSearchHistoryModel)
            .values(**_history_entry_to_values(entry))
            .returning(LeadPausedSearchHistoryModel)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one()
        return _history_model_to_entry(model)


def _record_to_values(
    record: CanonicalLeadRecord,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> dict[str, object]:
    return {
        "lead_id": record.lead_id,
        "workspace_id": record.workspace_id,
        "crm_provider": record.crm_provider.value,
        "crm_lead_id": record.crm_lead_id,
        "source_payload_version": record.source_payload_version,
        "source_updated_at": record.source_updated_at,
        "facts_derived_at": record.facts_derived_at,
        "assigned_agent_crm_id": record.assigned_agent_crm_id,
        "assigned_agent_user_id": record.assigned_agent_user_id,
        "effective_owner_user_id": record.effective_owner_user_id,
        "effective_owner_source": record.effective_owner_source.value
        if record.effective_owner_source is not None
        else None,
        "assignment_resolution_status": record.assignment_resolution_status.value,
        "assignment_last_resolved_at": record.assignment_last_resolved_at,
        "assigned_agent_name_present": record.assigned_agent_name_present,
        "has_accountable_owner": record.has_accountable_owner,
        "ownership_last_changed_at": record.ownership_last_changed_at,
        "lead_type": record.lead_type.value,
        "classification_reason": record.classification_reason.value,
        "crm_type_raw": record.crm_type_raw,
        "lead_source": record.lead_source,
        "lead_stage": record.lead_stage,
        "created_via": record.created_via,
        "tags": list(record.tags),
        "mapped_custom_fields": dict(record.mapped_custom_fields),
        "primary_email": record.primary_email,
        "primary_phone": record.primary_phone,
        "has_email": record.has_email,
        "has_phone": record.has_phone,
        "has_sms_capable_phone": record.has_sms_capable_phone,
        "email_count": record.email_count,
        "phone_count": record.phone_count,
        "sms_permission_status": record.sms_permission_status.value,
        "email_permission_status": record.email_permission_status.value,
        "sms_opted_out": record.sms_opted_out,
        "email_unsubscribed": record.email_unsubscribed,
        "do_not_contact": record.do_not_contact,
        "suppression_types": sorted(suppression.value for suppression in record.suppression_types),
        "permission_evidence": dict(record.permission_evidence),
        "crm_created_at": record.crm_created_at,
        "crm_updated_at": record.crm_updated_at,
        "last_activity_at": record.last_activity_at,
        "last_meaningful_communication_at": record.last_meaningful_communication_at,
        "last_agent_activity_at": record.last_agent_activity_at,
        "contacted_count": record.contacted_count,
        "activity_reliability": record.activity_reliability.value,
        "latest_property_event_type": record.latest_property_event_type.value
        if record.latest_property_event_type
        else None,
        "latest_property_event_at": record.latest_property_event_at,
        "latest_property_price_band": record.latest_property_price_band,
        "latest_property_context_present": record.latest_property_context_present,
        "paused_search_active": record.paused_search_active,
        "pause_reason_code": record.pause_reason_code.value if record.pause_reason_code else None,
        "pause_reason_note": record.pause_reason_note,
        "reengagement_not_before": record.reengagement_not_before,
        "reengagement_window_label": record.reengagement_window_label,
        "paused_search_source": record.paused_search_source.value
        if record.paused_search_source
        else None,
        "paused_search_recorded_at": record.paused_search_recorded_at,
        "paused_search_recorded_by_user_id": record.paused_search_recorded_by_user_id,
        "paused_search_last_confirmed_at": record.paused_search_last_confirmed_at,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _model_to_record(model: LeadModel) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        crm_provider=CRMProvider(model.crm_provider),
        crm_lead_id=model.crm_lead_id,
        source_payload_version=model.source_payload_version,
        source_updated_at=model.source_updated_at,
        facts_derived_at=model.facts_derived_at,
        assigned_agent_crm_id=model.assigned_agent_crm_id,
        assigned_agent_user_id=model.assigned_agent_user_id,
        effective_owner_user_id=model.effective_owner_user_id,
        effective_owner_source=EffectiveOwnerSource(model.effective_owner_source)
        if model.effective_owner_source
        else None,
        assignment_resolution_status=AssignmentResolutionStatus(
            model.assignment_resolution_status,
        ),
        assignment_last_resolved_at=model.assignment_last_resolved_at,
        assigned_agent_name_present=model.assigned_agent_name_present,
        has_accountable_owner=model.has_accountable_owner,
        ownership_last_changed_at=model.ownership_last_changed_at,
        lead_type=LeadType(model.lead_type),
        classification_reason=LeadClassificationReason(model.classification_reason),
        crm_type_raw=model.crm_type_raw,
        lead_source=model.lead_source,
        lead_stage=model.lead_stage,
        created_via=model.created_via,
        tags=tuple(model.tags),
        mapped_custom_fields=dict(model.mapped_custom_fields),
        primary_email=model.primary_email,
        primary_phone=model.primary_phone,
        has_email=model.has_email,
        has_phone=model.has_phone,
        has_sms_capable_phone=model.has_sms_capable_phone,
        email_count=model.email_count,
        phone_count=model.phone_count,
        sms_permission_status=ContactPermissionStatus(model.sms_permission_status),
        email_permission_status=ContactPermissionStatus(model.email_permission_status),
        sms_opted_out=model.sms_opted_out,
        email_unsubscribed=model.email_unsubscribed,
        do_not_contact=model.do_not_contact,
        suppression_types=frozenset(SuppressionType(item) for item in model.suppression_types),
        permission_evidence=dict(model.permission_evidence),
        crm_created_at=model.crm_created_at,
        crm_updated_at=model.crm_updated_at,
        last_activity_at=model.last_activity_at,
        last_meaningful_communication_at=model.last_meaningful_communication_at,
        last_agent_activity_at=model.last_agent_activity_at,
        contacted_count=model.contacted_count,
        activity_reliability=ActivityReliability(model.activity_reliability),
        latest_property_event_type=PropertyEventType(model.latest_property_event_type)
        if model.latest_property_event_type
        else None,
        latest_property_event_at=model.latest_property_event_at,
        latest_property_price_band=model.latest_property_price_band,
        latest_property_context_present=model.latest_property_context_present,
        paused_search_active=model.paused_search_active,
        pause_reason_code=PausedSearchReasonCode(model.pause_reason_code)
        if model.pause_reason_code
        else None,
        pause_reason_note=model.pause_reason_note,
        reengagement_not_before=model.reengagement_not_before,
        reengagement_window_label=model.reengagement_window_label,
        paused_search_source=PausedSearchSource(model.paused_search_source)
        if model.paused_search_source
        else None,
        paused_search_recorded_at=model.paused_search_recorded_at,
        paused_search_recorded_by_user_id=model.paused_search_recorded_by_user_id,
        paused_search_last_confirmed_at=model.paused_search_last_confirmed_at,
    )


def _history_entry_to_values(entry: LeadPausedSearchHistoryEntry) -> dict[str, object]:
    values: dict[str, object] = {
        "history_id": entry.history_id,
        "workspace_id": entry.workspace_id,
        "lead_id": entry.lead_id,
        "action": entry.action.value,
        "actor_user_id": entry.actor_user_id,
        "created_at": entry.created_at,
    }
    values.update(_profile_values("previous", entry.previous_profile))
    values.update(_profile_values("current", entry.current_profile))
    return values


def _profile_values(prefix: str, profile: LeadPausedSearchProfile | None) -> dict[str, object]:
    if profile is None:
        return {
            f"{prefix}_active": False,
            f"{prefix}_reason_code": None,
            f"{prefix}_reason_note": None,
            f"{prefix}_reengagement_not_before": None,
            f"{prefix}_reengagement_window_label": None,
            f"{prefix}_source": None,
            f"{prefix}_recorded_at": None,
            f"{prefix}_recorded_by_user_id": None,
            f"{prefix}_last_confirmed_at": None,
        }
    return {
        f"{prefix}_active": profile.paused_search_active,
        f"{prefix}_reason_code": (
            profile.pause_reason_code.value if profile.pause_reason_code else None
        ),
        f"{prefix}_reason_note": profile.pause_reason_note,
        f"{prefix}_reengagement_not_before": profile.reengagement_not_before,
        f"{prefix}_reengagement_window_label": profile.reengagement_window_label,
        f"{prefix}_source": (
            profile.paused_search_source.value if profile.paused_search_source else None
        ),
        f"{prefix}_recorded_at": profile.paused_search_recorded_at,
        f"{prefix}_recorded_by_user_id": profile.paused_search_recorded_by_user_id,
        f"{prefix}_last_confirmed_at": profile.paused_search_last_confirmed_at,
    }


def _history_model_to_entry(model: LeadPausedSearchHistoryModel) -> LeadPausedSearchHistoryEntry:
    return LeadPausedSearchHistoryEntry(
        history_id=model.history_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        action=PausedSearchAction(model.action),
        previous_profile=_profile_from_model(model, "previous"),
        current_profile=_profile_from_model(model, "current"),
        actor_user_id=model.actor_user_id,
        created_at=model.created_at,
    )


def _profile_from_model(
    model: LeadPausedSearchHistoryModel,
    prefix: str,
) -> LeadPausedSearchProfile | None:
    is_active = getattr(model, f"{prefix}_active")
    reason_code = getattr(model, f"{prefix}_reason_code")
    reason_note = getattr(model, f"{prefix}_reason_note")
    reengagement_not_before = getattr(model, f"{prefix}_reengagement_not_before")
    reengagement_window_label = getattr(model, f"{prefix}_reengagement_window_label")
    source = getattr(model, f"{prefix}_source")
    recorded_at = getattr(model, f"{prefix}_recorded_at")
    recorded_by_user_id = getattr(model, f"{prefix}_recorded_by_user_id")
    last_confirmed_at = getattr(model, f"{prefix}_last_confirmed_at")
    if not is_active and all(
        value is None
        for value in (
            reason_code,
            reason_note,
            reengagement_not_before,
            reengagement_window_label,
            source,
            recorded_at,
            recorded_by_user_id,
            last_confirmed_at,
        )
    ):
        return None
    return LeadPausedSearchProfile(
        paused_search_active=is_active,
        pause_reason_code=PausedSearchReasonCode(reason_code) if reason_code else None,
        pause_reason_note=reason_note,
        reengagement_not_before=reengagement_not_before,
        reengagement_window_label=reengagement_window_label,
        paused_search_source=PausedSearchSource(source) if source else None,
        paused_search_recorded_at=recorded_at,
        paused_search_recorded_by_user_id=recorded_by_user_id,
        paused_search_last_confirmed_at=last_confirmed_at,
    )


def _phone_match_candidates(phone_number: str) -> tuple[str, ...]:
    digits_only = "".join(character for character in phone_number if character.isdigit())
    if not digits_only:
        return ()
    candidates: list[str] = [digits_only]
    if len(digits_only) == 11 and digits_only.startswith("1"):
        candidates.append(digits_only[1:])
    elif len(digits_only) == 10:
        candidates.append(f"1{digits_only}")
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return tuple(ordered)


def _normalized_email(email_address: str) -> str | None:
    normalized = email_address.strip().lower()
    return normalized or None


def _by_id_statement(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    for_update: bool,
) -> Select[tuple[LeadModel]]:
    statement = select(LeadModel).where(
        LeadModel.workspace_id == workspace_id,
        LeadModel.lead_id == lead_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return statement
