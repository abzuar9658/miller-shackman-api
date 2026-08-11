from datetime import datetime

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchChannelSequence,
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchReplyPolicy,
    PausedSearchStepAction,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditAction,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackAssignment,
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackCatalogEntry,
    PausedSearchTrackLeadAssignment,
    PausedSearchTrackMode,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    effective_paused_search_step_action,
)
from app.domain.common.ids import (
    LeadId,
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.outbound_drafting import (
    dormant_step_template_profile_from_mapping,
    dormant_step_template_profile_to_mapping,
)
from app.domain.workflows import LeadWorkflow
from app.infrastructure.persistence.postgres.models import (
    LeadModel,
    PausedSearchTrackAdminAuditLogModel,
    PausedSearchTrackAssignmentModel,
    PausedSearchTrackModel,
    PausedSearchTrackStepModel,
    PausedSearchTrackVersionModel,
    RecurringOccurrenceModel,
)
from app.infrastructure.persistence.postgres.workflow_models import LeadWorkflowModel


class PostgresPausedSearchTrackAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_legacy_versions(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[tuple[PausedSearchTrackVersion, tuple[PausedSearchTrackStep, ...]], ...]:
        result = await self._session.execute(
            select(PausedSearchTrackVersionModel)
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .order_by(
                PausedSearchTrackVersionModel.track_id,
                PausedSearchTrackVersionModel.version_number,
            )
        )
        versions: list[tuple[PausedSearchTrackVersion, tuple[PausedSearchTrackStep, ...]]] = []
        for model in result.scalars().all():
            steps_result = await self._session.execute(
                select(PausedSearchTrackStepModel)
                .where(
                    PausedSearchTrackStepModel.workspace_id == workspace_id,
                    PausedSearchTrackStepModel.track_version_id == model.track_version_id,
                )
                .order_by(PausedSearchTrackStepModel.step_order)
            )
            steps = tuple(_step_from_model(step) for step in steps_result.scalars().all())
            version = _version_from_model(model)
            if any(step.action is None and step.review_required for step in steps):
                versions.append((version, steps))
        return tuple(versions)

    async def list_active_workflows_for_versions(
        self,
        workspace_id: WorkspaceId,
        track_version_ids: tuple[PausedSearchTrackVersionId, ...],
    ) -> tuple[LeadWorkflow, ...]:
        if not track_version_ids:
            return ()
        result = await self._session.execute(
            select(LeadWorkflowModel)
            .where(
                LeadWorkflowModel.workspace_id == workspace_id,
                LeadWorkflowModel.paused_search_track_version_id.in_(track_version_ids),
                LeadWorkflowModel.state.in_(
                    ("queued", "active_nurture", "waiting_for_response", "response_processing")
                ),
            )
            .order_by(LeadWorkflowModel.last_transition_at.asc())
        )
        from app.infrastructure.persistence.postgres.workflow_repository import _model_to_workflow

        return tuple(_model_to_workflow(model) for model in result.scalars().all())

    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        result = await self._session.execute(
            select(PausedSearchTrackModel)
            .where(PausedSearchTrackModel.workspace_id == workspace_id)
            .order_by(
                PausedSearchTrackModel.updated_at.desc(), PausedSearchTrackModel.track_key.asc()
            ),
        )
        return tuple(_track_from_model(model) for model in result.scalars().all())

    async def list_active_catalog(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[PausedSearchTrackCatalogEntry, ...]:
        result = await self._session.execute(
            select(PausedSearchTrackModel, PausedSearchTrackVersionModel)
            .join(
                PausedSearchTrackVersionModel,
                PausedSearchTrackVersionModel.track_version_id
                == PausedSearchTrackModel.active_version_id,
            )
            .where(
                PausedSearchTrackModel.workspace_id == workspace_id,
                PausedSearchTrackModel.status == PausedSearchTrackStatus.ACTIVE.value,
                PausedSearchTrackVersionModel.status == CampaignVersionStatus.PUBLISHED.value,
                PausedSearchTrackVersionModel.enabled.is_(True),
            )
            .order_by(PausedSearchTrackModel.track_key.asc())
        )
        return tuple(
            PausedSearchTrackCatalogEntry(
                track_key=track.track_key,
                display_name=track.display_name,
                selection_guidance=version.selection_guidance,
                track_id=track.track_id,
                track_version_id=version.track_version_id,
            )
            for track, version in result.all()
        )

    async def list_assigned_leads(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        *,
        limit: int = 100,
        lock: bool = False,
    ) -> tuple[PausedSearchTrackLeadAssignment, ...]:
        statement = (
            select(PausedSearchTrackAssignmentModel, LeadModel, LeadWorkflowModel)
            .join(
                LeadModel,
                and_(
                    LeadModel.workspace_id == PausedSearchTrackAssignmentModel.workspace_id,
                    LeadModel.lead_id == PausedSearchTrackAssignmentModel.lead_id,
                ),
            )
            .outerjoin(
                LeadWorkflowModel,
                and_(
                    LeadWorkflowModel.workspace_id == PausedSearchTrackAssignmentModel.workspace_id,
                    LeadWorkflowModel.lead_id == PausedSearchTrackAssignmentModel.lead_id,
                ),
            )
            .where(PausedSearchTrackAssignmentModel.workspace_id == workspace_id)
            .where(PausedSearchTrackAssignmentModel.track_id == track_id)
            .where(PausedSearchTrackAssignmentModel.released_at.is_(None))
        )
        if lock:
            statement = statement.order_by(
                PausedSearchTrackAssignmentModel.assigned_at.desc()
            ).with_for_update(of=(PausedSearchTrackAssignmentModel, LeadModel))
        else:
            statement = statement.order_by(
                PausedSearchTrackAssignmentModel.assigned_at.desc()
            ).limit(limit)
        result = await self._session.execute(statement)
        assignments: list[PausedSearchTrackLeadAssignment] = []
        for assignment, lead, workflow in result.all():
            assignments.append(
                PausedSearchTrackLeadAssignment(
                    lead_id=assignment.lead_id,
                    workflow_id=workflow.workflow_id if workflow is not None else None,
                    track_version_id=assignment.track_version_id,
                    crm_lead_id=lead.crm_lead_id,
                    primary_email=lead.primary_email,
                    lead_stage=lead.lead_stage,
                    workflow_state=workflow.state if workflow is not None else None,
                )
            )
            if lock and len(assignments) >= limit:
                break
        return tuple(assignments)

    async def delete_retired_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> None:
        version_result = await self._session.execute(
            select(PausedSearchTrackVersionModel.track_version_id)
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .where(PausedSearchTrackVersionModel.track_id == track_id)
        )
        version_ids = tuple(version_id for (version_id,) in version_result.all())
        if version_ids:
            await self._session.execute(
                delete(RecurringOccurrenceModel).where(
                    RecurringOccurrenceModel.workspace_id == workspace_id,
                    RecurringOccurrenceModel.track_version_id.in_(version_ids),
                )
            )
            await self._session.execute(
                delete(PausedSearchTrackStepModel).where(
                    PausedSearchTrackStepModel.workspace_id == workspace_id,
                    PausedSearchTrackStepModel.track_version_id.in_(version_ids),
                )
            )
            await self._session.execute(
                delete(PausedSearchTrackVersionModel).where(
                    PausedSearchTrackVersionModel.workspace_id == workspace_id,
                    PausedSearchTrackVersionModel.track_version_id.in_(version_ids),
                )
            )
        await self._session.execute(
            delete(PausedSearchTrackModel).where(
                PausedSearchTrackModel.workspace_id == workspace_id,
                PausedSearchTrackModel.track_id == track_id,
            )
        )

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        return await self._get_track(workspace_id, track_id, for_update=False)

    async def get_track_for_update(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        return await self._get_track(workspace_id, track_id, for_update=True)

    async def _get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        *,
        for_update: bool,
    ) -> PausedSearchTrack | None:
        statement = _track_statement(workspace_id, track_id, for_update=for_update)
        result = await self._session.execute(
            statement,
        )
        model = result.scalar_one_or_none()
        return _track_from_model(model) if model is not None else None

    async def get_track_by_key(
        self,
        workspace_id: WorkspaceId,
        track_key: str,
    ) -> PausedSearchTrack | None:
        result = await self._session.execute(
            select(PausedSearchTrackModel)
            .where(PausedSearchTrackModel.workspace_id == workspace_id)
            .where(PausedSearchTrackModel.track_key == track_key),
        )
        model = result.scalar_one_or_none()
        return _track_from_model(model) if model is not None else None

    async def save_track(self, track: PausedSearchTrack) -> PausedSearchTrack:
        values = _track_to_values(track)
        update_values = {key: value for key, value in values.items() if key != "track_id"}
        result = await self._session.execute(
            insert(PausedSearchTrackModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["track_id"], set_=update_values)
            .returning(PausedSearchTrackModel),
        )
        return _track_from_model(result.scalar_one())

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        result = await self._session.execute(
            select(PausedSearchTrackVersionModel)
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .where(PausedSearchTrackVersionModel.track_version_id == track_version_id),
        )
        model = result.scalar_one_or_none()
        return _version_from_model(model) if model is not None else None

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        result = await self._session.execute(
            select(PausedSearchTrackVersionModel)
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .where(PausedSearchTrackVersionModel.track_id == track_id)
            .where(PausedSearchTrackVersionModel.status == CampaignVersionStatus.DRAFT.value)
            .order_by(PausedSearchTrackVersionModel.version_number.desc())
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _version_from_model(model) if model is not None else None

    async def get_latest_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        result = await self._session.execute(
            select(PausedSearchTrackVersionModel)
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .where(PausedSearchTrackVersionModel.track_id == track_id)
            .order_by(PausedSearchTrackVersionModel.version_number.desc())
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _version_from_model(model) if model is not None else None

    async def get_latest_version_number(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> int:
        result = await self._session.execute(
            select(func.max(PausedSearchTrackVersionModel.version_number))
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .where(PausedSearchTrackVersionModel.track_id == track_id),
        )
        value = result.scalar()
        return int(value or 0)

    async def save_version(
        self,
        version: PausedSearchTrackVersion,
    ) -> PausedSearchTrackVersion:
        values = _version_to_values(version)
        update_values = {key: value for key, value in values.items() if key != "track_version_id"}
        result = await self._session.execute(
            insert(PausedSearchTrackVersionModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["track_version_id"], set_=update_values)
            .returning(PausedSearchTrackVersionModel),
        )
        return _version_from_model(result.scalar_one())

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        result = await self._session.execute(
            select(PausedSearchTrackStepModel)
            .where(PausedSearchTrackStepModel.workspace_id == workspace_id)
            .where(PausedSearchTrackStepModel.track_version_id == track_version_id)
            .order_by(PausedSearchTrackStepModel.step_order.asc()),
        )
        return tuple(_step_from_model(model) for model in result.scalars().all())

    async def replace_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
        steps: tuple[PausedSearchTrackStep, ...],
    ) -> tuple[PausedSearchTrackStep, ...]:
        await self._session.execute(
            delete(PausedSearchTrackStepModel)
            .where(PausedSearchTrackStepModel.workspace_id == workspace_id)
            .where(PausedSearchTrackStepModel.track_version_id == track_version_id),
        )
        saved_steps: list[PausedSearchTrackStep] = []
        for step in steps:
            result = await self._session.execute(
                insert(PausedSearchTrackStepModel)
                .values(**_step_to_values(step))
                .returning(PausedSearchTrackStepModel),
            )
            saved_steps.append(_step_from_model(result.scalar_one()))
        return tuple(saved_steps)

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        except_version_id: PausedSearchTrackVersionId | None,
    ) -> None:
        statement = (
            update(PausedSearchTrackVersionModel)
            .where(PausedSearchTrackVersionModel.workspace_id == workspace_id)
            .where(PausedSearchTrackVersionModel.track_id == track_id)
            .where(PausedSearchTrackVersionModel.status == CampaignVersionStatus.PUBLISHED.value)
        )
        if except_version_id is not None:
            statement = statement.where(
                PausedSearchTrackVersionModel.track_version_id != except_version_id,
            )
        await self._session.execute(statement.values(status=CampaignVersionStatus.RETIRED.value))

class PostgresPausedSearchTrackAdminAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        audit_log: PausedSearchTrackAdminAuditLog,
    ) -> PausedSearchTrackAdminAuditLog:
        result = await self._session.execute(
            insert(PausedSearchTrackAdminAuditLogModel)
            .values(**_audit_to_values(audit_log))
            .returning(PausedSearchTrackAdminAuditLogModel),
        )
        return _audit_from_model(result.scalar_one())


class PostgresPausedSearchTrackAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        return await self._get_active_for_lead(workspace_id, lead_id, for_update=False)

    async def get_active_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> PausedSearchTrackAssignment | None:
        return await self._get_active_for_lead(workspace_id, lead_id, for_update=True)

    async def _get_active_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        for_update: bool,
    ) -> PausedSearchTrackAssignment | None:
        result = await self._session.execute(
            _active_assignment_statement(workspace_id, lead_id, for_update=for_update)
        )
        model = result.scalar_one_or_none()
        return _assignment_from_model(model) if model is not None else None

    async def create(
        self,
        assignment: PausedSearchTrackAssignment,
    ) -> PausedSearchTrackAssignment:
        result = await self._session.execute(
            insert(PausedSearchTrackAssignmentModel)
            .values(**_assignment_to_values(assignment))
            .returning(PausedSearchTrackAssignmentModel)
        )
        return _assignment_from_model(result.scalar_one())

    async def release_active(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        released_at: datetime,
        released_by: UserId | None = None,
        release_reason: str | None = None,
    ) -> PausedSearchTrackAssignment | None:
        result = await self._session.execute(
            update(PausedSearchTrackAssignmentModel)
            .where(
                PausedSearchTrackAssignmentModel.workspace_id == workspace_id,
                PausedSearchTrackAssignmentModel.lead_id == lead_id,
                PausedSearchTrackAssignmentModel.released_at.is_(None),
            )
            .values(
                released_at=released_at,
                released_by_user_id=released_by,
                release_reason=release_reason,
            )
            .returning(PausedSearchTrackAssignmentModel)
        )
        model = result.scalar_one_or_none()
        return _assignment_from_model(model) if model is not None else None


def _track_statement(
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    *,
    for_update: bool,
) -> Select[tuple[PausedSearchTrackModel]]:
    statement = (
        select(PausedSearchTrackModel)
        .where(PausedSearchTrackModel.workspace_id == workspace_id)
        .where(PausedSearchTrackModel.track_id == track_id)
    )
    return statement.with_for_update() if for_update else statement


def _active_assignment_statement(
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    *,
    for_update: bool,
) -> Select[tuple[PausedSearchTrackAssignmentModel]]:
    statement = select(PausedSearchTrackAssignmentModel).where(
        PausedSearchTrackAssignmentModel.workspace_id == workspace_id,
        PausedSearchTrackAssignmentModel.lead_id == lead_id,
        PausedSearchTrackAssignmentModel.released_at.is_(None),
    )
    return statement.with_for_update() if for_update else statement


def _assignment_to_values(assignment: PausedSearchTrackAssignment) -> dict[str, object]:
    return {
        "assignment_id": assignment.assignment_id,
        "workspace_id": assignment.workspace_id,
        "lead_id": assignment.lead_id,
        "track_id": assignment.track_id,
        "track_version_id": assignment.track_version_id,
        "track_key_snapshot": assignment.track_key_snapshot,
        "track_name_snapshot": assignment.track_name_snapshot,
        "track_version_snapshot": assignment.track_version_snapshot,
        "source": assignment.source.value,
        "assigned_by_user_id": assignment.assigned_by_user_id,
        "assigned_at": assignment.assigned_at,
        "released_at": assignment.released_at,
        "released_by_user_id": assignment.released_by,
        "release_reason": assignment.release_reason,
    }


def _assignment_from_model(
    model: PausedSearchTrackAssignmentModel,
) -> PausedSearchTrackAssignment:
    return PausedSearchTrackAssignment(
        assignment_id=model.assignment_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        track_id=model.track_id,
        track_version_id=model.track_version_id,
        track_key_snapshot=model.track_key_snapshot,
        track_name_snapshot=model.track_name_snapshot,
        track_version_snapshot=model.track_version_snapshot,
        source=PausedSearchTrackAssignmentSource(model.source),
        assigned_by_user_id=model.assigned_by_user_id,
        assigned_at=model.assigned_at,
        released_at=model.released_at,
        released_by=model.released_by_user_id,
        release_reason=model.release_reason,
    )


def _track_to_values(track: PausedSearchTrack) -> dict[str, object]:
    return {
        "track_id": track.track_id,
        "workspace_id": track.workspace_id,
        "track_key": track.track_key,
        "display_name": track.display_name,
        "status": track.status.value,
        "active_version_id": track.active_version_id,
        "created_by_user_id": track.created_by_user_id,
        "created_at": track.created_at,
        "updated_at": track.updated_at,
    }


def _track_from_model(model: PausedSearchTrackModel) -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=model.track_id,
        workspace_id=model.workspace_id,
        track_key=model.track_key,
        display_name=model.display_name,
        status=PausedSearchTrackStatus(model.status),
        active_version_id=model.active_version_id,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _version_to_values(version: PausedSearchTrackVersion) -> dict[str, object]:
    return {
        "track_version_id": version.track_version_id,
        "workspace_id": version.workspace_id,
        "track_id": version.track_id,
        "version_number": version.version_number,
        "status": version.status.value,
        "selection_guidance": version.selection_guidance,
        "enabled": version.enabled,
        "allowed_channels": [channel.value for channel in version.allowed_channels],
        "fallback_timing_policy": version.fallback_timing_policy.value,
        "maintenance_interval_days": version.maintenance_interval_days,
        "reactivation_window_days": version.reactivation_window_days,
        "max_total_touches": version.max_total_touches,
        "default_pause_duration_days": version.default_pause_duration_days,
        "max_duration_days": version.max_duration_days,
        "terminal_behavior": version.terminal_behavior.value,
        "track_mode": version.track_mode.value,
        "interim_contact_policy": version.interim_contact_policy.value,
        "reply_policy": version.reply_policy.value,
        "channel_sequence": version.channel_sequence.value,
        "max_cycles": version.max_cycles,
        "max_ai_interactions": version.max_ai_interactions,
        "restart_delay_days": version.restart_delay_days,
        "email_writing_purpose": version.email_writing_purpose,
        "sms_writing_purpose": version.sms_writing_purpose,
        "created_by_user_id": version.created_by_user_id,
        "published_at": version.published_at,
        "created_at": version.created_at,
    }


def _version_from_model(model: PausedSearchTrackVersionModel) -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=model.track_version_id,
        workspace_id=model.workspace_id,
        track_id=model.track_id,
        version_number=model.version_number,
        status=CampaignVersionStatus(model.status),
        selection_guidance=model.selection_guidance,
        enabled=model.enabled,
        allowed_channels=tuple(ContactChannel(channel) for channel in model.allowed_channels),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy(model.fallback_timing_policy),
        maintenance_interval_days=model.maintenance_interval_days,
        reactivation_window_days=model.reactivation_window_days,
        max_total_touches=model.max_total_touches,
        default_pause_duration_days=model.default_pause_duration_days,
        max_duration_days=model.max_duration_days,
        terminal_behavior=PausedSearchTerminalBehavior(model.terminal_behavior),
        track_mode=PausedSearchTrackMode(model.track_mode),
        interim_contact_policy=PausedSearchInterimContactPolicy(model.interim_contact_policy),
        reply_policy=PausedSearchReplyPolicy(model.reply_policy),
        channel_sequence=PausedSearchChannelSequence(model.channel_sequence),
        max_cycles=model.max_cycles,
        max_ai_interactions=model.max_ai_interactions,
        restart_delay_days=model.restart_delay_days,
        email_writing_purpose=model.email_writing_purpose,
        sms_writing_purpose=model.sms_writing_purpose,
        created_by_user_id=model.created_by_user_id,
        published_at=model.published_at,
        created_at=model.created_at,
    )


def _step_to_values(step: PausedSearchTrackStep) -> dict[str, object]:
    return {
        "step_id": step.step_id,
        "workspace_id": step.workspace_id,
        "track_version_id": step.track_version_id,
        "step_order": step.step_order,
        "phase": step.phase.value,
        "timing_basis": step.timing_basis.value,
        "fallback_channel": step.fallback_channel.value if step.fallback_channel else None,
        "channel": step.channel.value,
        "delay_hours": step.delay_hours,
        "message_goal": step.message_goal,
        "template_key": step.template_key,
        "template_version_id": step.template_version_id,
        "template_profile": (
            dormant_step_template_profile_to_mapping(step.template_profile)
            if step.template_profile is not None
            else None
        ),
        "max_attempts": step.max_attempts,
        "review_required": step.review_required,
        "action": effective_paused_search_step_action(step).value,
        "interval_days": step.interval_days,
        "max_occurrences": step.max_occurrences,
        "created_at": step.created_at,
    }


def _step_from_model(model: PausedSearchTrackStepModel) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=model.step_id,
        workspace_id=model.workspace_id,
        track_version_id=model.track_version_id,
        step_order=model.step_order,
        phase=PausedSearchTrackStepPhase(model.phase),
        timing_basis=PausedSearchTimingBasis(model.timing_basis),
        fallback_channel=(
            ContactChannel(model.fallback_channel) if model.fallback_channel is not None else None
        ),
        channel=ContactChannel(model.channel),
        delay_hours=model.delay_hours,
        message_goal=model.message_goal,
        template_key=model.template_key,
        template_version_id=model.template_version_id,
        max_attempts=model.max_attempts,
        review_required=model.review_required,
        action=PausedSearchStepAction(model.action),
        created_at=model.created_at,
        interval_days=model.interval_days,
        max_occurrences=model.max_occurrences,
        template_profile=dormant_step_template_profile_from_mapping(model.template_profile),
    )


def _audit_to_values(audit_log: PausedSearchTrackAdminAuditLog) -> dict[str, object]:
    return {
        "audit_log_id": audit_log.audit_log_id,
        "workspace_id": audit_log.workspace_id,
        "track_id": audit_log.track_id,
        "track_version_id": audit_log.track_version_id,
        "actor_user_id": audit_log.actor_user_id,
        "action": audit_log.action.value,
        "details": dict(audit_log.details),
        "created_at": audit_log.created_at,
    }


def _audit_from_model(
    model: PausedSearchTrackAdminAuditLogModel,
) -> PausedSearchTrackAdminAuditLog:
    return PausedSearchTrackAdminAuditLog(
        audit_log_id=model.audit_log_id,
        workspace_id=model.workspace_id,
        track_id=model.track_id,
        track_version_id=model.track_version_id,
        actor_user_id=model.actor_user_id,
        action=PausedSearchTrackAdminAuditAction(model.action),
        details=dict(model.details),
        created_at=model.created_at,
    )
