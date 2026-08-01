from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditAction,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.common.ids import (
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode
from app.infrastructure.persistence.postgres.models import (
    PausedSearchReasonMappingModel,
    PausedSearchTrackAdminAuditLogModel,
    PausedSearchTrackModel,
    PausedSearchTrackStepModel,
    PausedSearchTrackVersionModel,
)


class PostgresPausedSearchTrackAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        result = await self._session.execute(
            select(PausedSearchTrackModel)
            .where(PausedSearchTrackModel.workspace_id == workspace_id)
            .order_by(
                PausedSearchTrackModel.updated_at.desc(), PausedSearchTrackModel.track_key.asc()
            ),
        )
        return tuple(_track_from_model(model) for model in result.scalars().all())

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

    async def replace_reason_mappings(
        self,
        *,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        track_version_id: PausedSearchTrackVersionId,
        reason_codes: tuple[PausedSearchReasonCode, ...],
        actor_user_id: UserId,
        now: datetime,
    ) -> tuple[PausedSearchReasonMapping, ...]:
        reason_values = [reason_code.value for reason_code in reason_codes]
        await self._session.execute(
            delete(PausedSearchReasonMappingModel)
            .where(PausedSearchReasonMappingModel.workspace_id == workspace_id)
            .where(
                or_(
                    PausedSearchReasonMappingModel.track_id == track_id,
                    PausedSearchReasonMappingModel.reason_code.in_(reason_values),
                )
            ),
        )
        mappings: list[PausedSearchReasonMapping] = []
        for reason_code in reason_codes:
            result = await self._session.execute(
                insert(PausedSearchReasonMappingModel)
                .values(
                    mapping_id=uuid4(),
                    workspace_id=workspace_id,
                    reason_code=reason_code.value,
                    track_id=track_id,
                    track_version_id=track_version_id,
                    created_by_user_id=actor_user_id,
                    created_at=now,
                )
                .returning(PausedSearchReasonMappingModel),
            )
            mappings.append(_mapping_from_model(result.scalar_one()))
        return tuple(mappings)

    async def clear_reason_mappings_for_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> None:
        await self._session.execute(
            delete(PausedSearchReasonMappingModel)
            .where(PausedSearchReasonMappingModel.workspace_id == workspace_id)
            .where(PausedSearchReasonMappingModel.track_id == track_id),
        )

    async def list_reason_mappings_for_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchReasonMapping, ...]:
        result = await self._session.execute(
            select(PausedSearchReasonMappingModel)
            .where(PausedSearchReasonMappingModel.workspace_id == workspace_id)
            .where(PausedSearchReasonMappingModel.track_version_id == track_version_id)
            .order_by(PausedSearchReasonMappingModel.reason_code.asc()),
        )
        return tuple(_mapping_from_model(model) for model in result.scalars().all())

    async def get_reason_mapping(
        self,
        workspace_id: WorkspaceId,
        reason_code: PausedSearchReasonCode,
    ) -> PausedSearchReasonMapping | None:
        result = await self._session.execute(
            select(PausedSearchReasonMappingModel)
            .where(PausedSearchReasonMappingModel.workspace_id == workspace_id)
            .where(PausedSearchReasonMappingModel.reason_code == reason_code.value),
        )
        model = result.scalar_one_or_none()
        return _mapping_from_model(model) if model is not None else None


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
        "track_family": version.track_family.value,
        "enabled": version.enabled,
        "allowed_channels": [channel.value for channel in version.allowed_channels],
        "default_for_reason_codes": [
            reason_code.value for reason_code in version.default_for_reason_codes
        ],
        "fallback_timing_policy": version.fallback_timing_policy.value,
        "maintenance_interval_days": version.maintenance_interval_days,
        "reactivation_window_days": version.reactivation_window_days,
        "max_total_touches": version.max_total_touches,
        "requires_review_before_publish": version.requires_review_before_publish,
        "default_pause_duration_days": version.default_pause_duration_days,
        "max_duration_days": version.max_duration_days,
        "terminal_behavior": version.terminal_behavior.value,
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
        track_family=PausedSearchTrackFamily(model.track_family),
        enabled=model.enabled,
        allowed_channels=tuple(ContactChannel(channel) for channel in model.allowed_channels),
        default_for_reason_codes=tuple(
            PausedSearchReasonCode(reason_code) for reason_code in model.default_for_reason_codes
        ),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy(model.fallback_timing_policy),
        maintenance_interval_days=model.maintenance_interval_days,
        reactivation_window_days=model.reactivation_window_days,
        max_total_touches=model.max_total_touches,
        requires_review_before_publish=model.requires_review_before_publish,
        default_pause_duration_days=model.default_pause_duration_days,
        max_duration_days=model.max_duration_days,
        terminal_behavior=PausedSearchTerminalBehavior(model.terminal_behavior),
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
        "max_attempts": step.max_attempts,
        "review_required": step.review_required,
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
        created_at=model.created_at,
        interval_days=model.interval_days,
        max_occurrences=model.max_occurrences,
    )


def _mapping_from_model(model: PausedSearchReasonMappingModel) -> PausedSearchReasonMapping:
    return PausedSearchReasonMapping(
        mapping_id=model.mapping_id,
        workspace_id=model.workspace_id,
        reason_code=PausedSearchReasonCode(model.reason_code),
        track_id=model.track_id,
        track_version_id=model.track_version_id,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
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
