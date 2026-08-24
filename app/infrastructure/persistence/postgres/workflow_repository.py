from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    LeadWorkflowOverrideAction,
    LeadWorkflowOverrideAuditLog,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)
from app.infrastructure.persistence.postgres.models import LeadWorkflowOverrideAuditLogModel
from app.infrastructure.persistence.postgres.workflow_models import (
    LeadWorkflowModel,
    WorkflowTransitionModel,
)


class PostgresLeadWorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_latest_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        result = await self._session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == workspace_id)
            .distinct(LeadWorkflowModel.lead_id)
            .order_by(LeadWorkflowModel.lead_id, *_LATEST_WORKFLOW_ORDERING)
            .limit(limit),
        )
        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def list_latest_for_leads(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[LeadWorkflow, ...]:
        if not lead_ids:
            return ()
        result = await self._session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == workspace_id)
            .where(LeadWorkflowModel.lead_id.in_(lead_ids))
            .distinct(LeadWorkflowModel.lead_id)
            .order_by(LeadWorkflowModel.lead_id, *_LATEST_WORKFLOW_ORDERING),
        )
        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        result = await self._session.execute(
            _latest_for_lead_statement(workspace_id, lead_id, for_update=False),
        )
        model = result.scalar_one_or_none()
        return _model_to_workflow(model) if model is not None else None

    async def list_active_paused_search_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        result = await self._session.execute(
            _active_paused_search_statement(workspace_id, lead_id, for_update=False),
        )
        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def list_active_paused_search_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        result = await self._session.execute(
            _active_paused_search_statement(workspace_id, lead_id, for_update=True),
        )
        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        result = await self._session.execute(
            _latest_for_lead_statement(workspace_id, lead_id, for_update=True),
        )
        model = result.scalar_one_or_none()
        return _model_to_workflow(model) if model is not None else None

    async def list_recent_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 5,
    ) -> tuple[LeadWorkflow, ...]:
        result = await self._session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == workspace_id)
            .where(LeadWorkflowModel.lead_id == lead_id)
            .order_by(*_LATEST_WORKFLOW_ORDERING)
            .limit(limit),
        )
        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def list_paused_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        result = await self._session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == workspace_id)
            .where(LeadWorkflowModel.state == WorkflowState.PAUSED.value)
            .order_by(LeadWorkflowModel.last_transition_at.asc())
            .limit(limit),
        )
        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        values = _workflow_to_values(workflow)
        update_values = {key: value for key, value in values.items() if key != "workflow_id"}
        statement = (
            insert(LeadWorkflowModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["workflow_id"], set_=update_values)
            .returning(LeadWorkflowModel)
        )
        result = await self._session.execute(statement)
        return _model_to_workflow(result.scalar_one())


class PostgresWorkflowTransitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, transition: WorkflowTransition) -> WorkflowTransition:
        statement = (
            insert(WorkflowTransitionModel)
            .values(_transition_to_values(transition))
            .returning(WorkflowTransitionModel)
        )
        result = await self._session.execute(statement)
        return _model_to_transition(result.scalar_one())

    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        statement = (
            select(WorkflowTransitionModel)
            .where(WorkflowTransitionModel.workspace_id == workspace_id)
            .where(WorkflowTransitionModel.workflow_id == workflow_id)
            .order_by(WorkflowTransitionModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return tuple(_model_to_transition(model) for model in result.scalars().all())


class PostgresLeadWorkflowOverrideAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        audit_log: LeadWorkflowOverrideAuditLog,
    ) -> LeadWorkflowOverrideAuditLog:
        result = await self._session.execute(
            insert(LeadWorkflowOverrideAuditLogModel)
            .values(_override_audit_to_values(audit_log))
            .returning(LeadWorkflowOverrideAuditLogModel),
        )
        return _model_to_override_audit(result.scalar_one())

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflowOverrideAuditLog, ...]:
        result = await self._session.execute(
            select(LeadWorkflowOverrideAuditLogModel)
            .where(LeadWorkflowOverrideAuditLogModel.workspace_id == workspace_id)
            .where(LeadWorkflowOverrideAuditLogModel.lead_id == lead_id)
            .order_by(LeadWorkflowOverrideAuditLogModel.created_at.desc())
            .limit(limit),
        )
        return tuple(_model_to_override_audit(model) for model in result.scalars().all())


# Ordering by last_transition_at alone is not a total order: close-and-create
# writes the closed old run and the fresh replacement in one transaction with
# the same timestamp, and an arbitrary winner here can make "latest" resolve to
# the terminal row and strand the live one. created_at breaks that tie toward
# the newer lifecycle; workflow_id keeps the result deterministic regardless.
_LATEST_WORKFLOW_ORDERING = (
    LeadWorkflowModel.last_transition_at.desc(),
    LeadWorkflowModel.created_at.desc(),
    LeadWorkflowModel.workflow_id.desc(),
)


def _latest_for_lead_statement(
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    *,
    for_update: bool,
) -> Select[tuple[LeadWorkflowModel]]:
    statement = (
        select(LeadWorkflowModel)
        .where(LeadWorkflowModel.workspace_id == workspace_id)
        .where(LeadWorkflowModel.lead_id == lead_id)
        .order_by(*_LATEST_WORKFLOW_ORDERING)
        .limit(1)
    )
    return statement.with_for_update() if for_update else statement


def _active_paused_search_statement(
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    *,
    for_update: bool,
) -> Select[tuple[LeadWorkflowModel]]:
    statement = (
        select(LeadWorkflowModel)
        .where(LeadWorkflowModel.workspace_id == workspace_id)
        .where(LeadWorkflowModel.lead_id == lead_id)
        .where(LeadWorkflowModel.paused_search_track_version_id.is_not(None))
        .where(
            LeadWorkflowModel.state.in_(
                (
                    WorkflowState.QUEUED.value,
                    WorkflowState.ACTIVE_NURTURE.value,
                    WorkflowState.WAITING_FOR_RESPONSE.value,
                    WorkflowState.RESPONSE_PROCESSING.value,
                )
            )
        )
        .order_by(*_LATEST_WORKFLOW_ORDERING)
    )
    return statement.with_for_update() if for_update else statement


def _workflow_to_values(workflow: LeadWorkflow) -> dict[str, object]:
    return {
        "workflow_id": workflow.workflow_id,
        "temporal_workflow_id": workflow.temporal_workflow_id,
        "workspace_id": workflow.workspace_id,
        "campaign_enrollment_id": workflow.campaign_enrollment_id,
        "campaign_id": workflow.campaign_id,
        "lead_id": workflow.lead_id,
        "state": workflow.state.value,
        "current_step_id": workflow.current_step_id,
        "paused_search_track_version_id": workflow.paused_search_track_version_id,
        "paused_search_track_step_id": workflow.paused_search_track_step_id,
        "next_action_at": workflow.next_action_at,
        "last_transition_at": workflow.last_transition_at,
        "pause_reason": workflow.pause_reason,
        "resume_reason": workflow.resume_reason,
        "state_version": workflow.state_version,
        "logical_touch_count": workflow.logical_touch_count,
        "ai_interaction_count": workflow.ai_interaction_count,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
    }


def _model_to_workflow(model: LeadWorkflowModel) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=model.workflow_id,
        temporal_workflow_id=model.temporal_workflow_id,
        workspace_id=model.workspace_id,
        campaign_enrollment_id=model.campaign_enrollment_id,
        campaign_id=model.campaign_id,
        lead_id=model.lead_id,
        state=WorkflowState(model.state),
        current_step_id=model.current_step_id,
        paused_search_track_version_id=model.paused_search_track_version_id,
        paused_search_track_step_id=model.paused_search_track_step_id,
        next_action_at=model.next_action_at,
        last_transition_at=model.last_transition_at,
        pause_reason=model.pause_reason,
        resume_reason=model.resume_reason,
        state_version=model.state_version,
        logical_touch_count=getattr(model, "logical_touch_count", 0) or 0,
        ai_interaction_count=getattr(model, "ai_interaction_count", 0) or 0,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _transition_to_values(transition: WorkflowTransition) -> dict[object, object]:
    return {
        WorkflowTransitionModel.transition_id: transition.transition_id,
        WorkflowTransitionModel.workspace_id: transition.workspace_id,
        WorkflowTransitionModel.workflow_id: transition.workflow_id,
        WorkflowTransitionModel.lead_id: transition.lead_id,
        WorkflowTransitionModel.campaign_id: transition.campaign_id,
        WorkflowTransitionModel.from_state: (
            transition.from_state.value if transition.from_state is not None else None
        ),
        WorkflowTransitionModel.to_state: transition.to_state.value,
        WorkflowTransitionModel.reason_code: transition.reason_code.value,
        WorkflowTransitionModel.actor_user_id: transition.actor_user_id,
        WorkflowTransitionModel.external_event_id: transition.external_event_id,
        WorkflowTransitionModel.created_at: transition.created_at,
        WorkflowTransitionModel.metadata_: dict(transition.metadata),
    }


def _model_to_transition(model: WorkflowTransitionModel) -> WorkflowTransition:
    return WorkflowTransition(
        transition_id=model.transition_id,
        workspace_id=model.workspace_id,
        workflow_id=model.workflow_id,
        lead_id=model.lead_id,
        campaign_id=model.campaign_id,
        from_state=WorkflowState(model.from_state) if model.from_state is not None else None,
        to_state=WorkflowState(model.to_state),
        reason_code=WorkflowTransitionReasonCode(model.reason_code),
        actor_user_id=model.actor_user_id,
        external_event_id=model.external_event_id,
        created_at=model.created_at,
        metadata=model.metadata_,
    )


def _override_audit_to_values(
    audit_log: LeadWorkflowOverrideAuditLog,
) -> dict[object, object]:
    return {
        LeadWorkflowOverrideAuditLogModel.audit_log_id: audit_log.audit_log_id,
        LeadWorkflowOverrideAuditLogModel.workspace_id: audit_log.workspace_id,
        LeadWorkflowOverrideAuditLogModel.lead_id: audit_log.lead_id,
        LeadWorkflowOverrideAuditLogModel.workflow_id: audit_log.workflow_id,
        LeadWorkflowOverrideAuditLogModel.actor_user_id: audit_log.actor_user_id,
        LeadWorkflowOverrideAuditLogModel.action: audit_log.action.value,
        LeadWorkflowOverrideAuditLogModel.reason: audit_log.reason,
        LeadWorkflowOverrideAuditLogModel.details: dict(audit_log.details),
        LeadWorkflowOverrideAuditLogModel.created_at: audit_log.created_at,
    }


def _model_to_override_audit(
    model: LeadWorkflowOverrideAuditLogModel,
) -> LeadWorkflowOverrideAuditLog:
    return LeadWorkflowOverrideAuditLog(
        audit_log_id=model.audit_log_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        actor_user_id=model.actor_user_id,
        action=LeadWorkflowOverrideAction(model.action),
        reason=model.reason,
        details=dict(model.details),
        created_at=model.created_at,
    )
