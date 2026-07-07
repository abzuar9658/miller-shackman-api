from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.infrastructure.persistence.postgres.models import LeadModel


class PostgresLeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
    )


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