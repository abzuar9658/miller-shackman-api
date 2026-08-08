from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from app.application.use_cases.paused_search_track_admin import (
    PausedSearchTrackConfigInput,
    PausedSearchTrackDeleteStatus,
    PausedSearchTrackDraftStatus,
    PausedSearchTrackPublishStatus,
    PausedSearchTrackRestoreStatus,
    PausedSearchTrackStepInput,
    create_draft_paused_search_track,
    delete_retired_paused_search_track,
    list_paused_search_track_views,
    publish_paused_search_track_version,
    restore_retired_paused_search_track,
    retire_paused_search_track,
    update_draft_paused_search_track,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackAdminView,
    PausedSearchTrackCatalogEntry,
    PausedSearchTrackLeadAssignment,
    PausedSearchTrackMode,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.template_registry import TemplateChannel, TemplateStatus, TemplateVersion
from app.domain.common.ids import PausedSearchTrackId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent, DomainEventType
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.outbound_drafting import DormantStepTemplateProfile

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
PREVIOUS_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")


def test_list_paused_search_tracks_hides_retired_tracks() -> None:
    repository = FakePausedSearchTrackAdminRepository()
    repository.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repository.tracks[PREVIOUS_VERSION_ID] = replace(
        _track(status=PausedSearchTrackStatus.RETIRED),
        track_id=PREVIOUS_VERSION_ID,
        active_version_id=PREVIOUS_VERSION_ID,
    )
    repository.versions[VERSION_ID] = _version(status=CampaignVersionStatus.PUBLISHED)
    repository.versions[PREVIOUS_VERSION_ID] = replace(
        _version(track_version_id=PREVIOUS_VERSION_ID, status=CampaignVersionStatus.RETIRED),
        track_id=PREVIOUS_VERSION_ID,
    )
    repository.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    repository.steps[PREVIOUS_VERSION_ID] = _step_tuple(PREVIOUS_VERSION_ID)

    result = _run(
        list_paused_search_track_views(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            repository=repository,
        )
    )

    assert result.status.value == "ok"
    assert [view.track.track_id for view in result.views] == [TRACK_ID]


def test_create_draft_paused_search_track_persists_audit_and_event() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    audit_repo = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        create_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_key="rented-year",
            display_name="Rented for a year",
            config=_config(),
            repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            template_repository=FakeTemplateRepository(),
            now=NOW,
        )
    )

    assert result.status == PausedSearchTrackDraftStatus.CREATED
    assert result.view is not None
    assert result.view.track.status == PausedSearchTrackStatus.DRAFT
    assert result.view.version.status == CampaignVersionStatus.DRAFT
    assert result.view.steps[0].phase == PausedSearchTrackStepPhase.MAINTENANCE
    assert audit_repo.logs[-1].action.value == "paused_search_track_draft_created"
    assert event_bus.events[-1].event_type == DomainEventType.PAUSED_SEARCH_TRACK_DRAFT_CREATED


def test_create_draft_derives_safety_limits_from_configured_cadence() -> None:
    base = _config(max_total_touches=3)
    email = replace(
        base.steps[0],
        interval_days=30,
        max_occurrences=2,
        timing_basis=PausedSearchTimingBasis.WORKFLOW_CREATED_AT,
    )
    sms = replace(
        email,
        channel=ContactChannel.SMS,
        template_key="paused-search-maintenance-sms-1",
    )
    reactivation = replace(
        base.steps[0],
        phase=PausedSearchTrackStepPhase.REACTIVATION,
        delay_hours=24,
        template_key="paused-search-reactivation-email-1",
        timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
    )
    config = replace(
        base,
        allowed_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
        track_mode=PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT,
        interim_contact_policy=PausedSearchInterimContactPolicy.ALLOWED_BY_PUBLISHED_TRACK,
        max_duration_days=365,
        steps=(email, sms, reactivation),
    )

    result = _run(
        create_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_key="waiting-for-rates-derived-limits",
            display_name="Waiting for rates derived limits",
            config=config,
            repository=FakePausedSearchTrackAdminRepository(),
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackDraftStatus.CREATED
    assert result.view is not None
    assert result.view.version.max_total_touches == 5
    assert result.view.version.max_duration_days == 730


def test_create_draft_rejects_assigned_agent_and_short_guidance() -> None:
    permission_result = _run(
        create_draft_paused_search_track(
            actor=_actor(role=WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            track_key="rented-year",
            display_name="Rented for a year",
            config=_config(),
            repository=FakePausedSearchTrackAdminRepository(),
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )
    guidance_result = _run(
        create_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_key="rented-year",
            display_name="Rented for a year",
            config=_config(selection_guidance="too short"),
            repository=FakePausedSearchTrackAdminRepository(),
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert permission_result.status == PausedSearchTrackDraftStatus.REJECTED
    assert permission_result.reasons[0].value == "permission_denied"
    assert guidance_result.status == PausedSearchTrackDraftStatus.REJECTED
    assert guidance_result.reasons[0].value == "invalid_configuration"


def test_create_draft_rejects_legacy_review_configuration() -> None:
    config = replace(
        _config(),
        steps=(replace(_config().steps[0], review_required=True),),
    )

    result = _run(
        create_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_key="legacy-review",
            display_name="Legacy review track",
            config=config,
            repository=FakePausedSearchTrackAdminRepository(),
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackDraftStatus.REJECTED
    assert result.reasons[0].value == "legacy_configuration_not_allowed"


def test_existing_legacy_version_remains_readable() -> None:
    version = _version(status=CampaignVersionStatus.PUBLISHED)
    legacy_step = replace(_step_tuple(VERSION_ID)[0], review_required=True)
    view = PausedSearchTrackAdminView(
        _track(status=PausedSearchTrackStatus.ACTIVE),
        version,
        (legacy_step,),
    )

    assert version.maintenance_interval_days == 90
    assert version.restart_delay_days == 30
    assert view.compatibility.value == "legacy"


def test_publish_track_version_retires_previous_version() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repo.versions[PREVIOUS_VERSION_ID] = _version(
        track_version_id=PREVIOUS_VERSION_ID,
        status=CampaignVersionStatus.PUBLISHED,
    )
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.DRAFT, version_number=2)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    audit_repo = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        publish_paused_search_track_version(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            track_version_id=VERSION_ID,
            repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            template_repository=FakeTemplateRepository(),
            now=NOW,
        )
    )

    assert result.status == PausedSearchTrackPublishStatus.PUBLISHED
    assert result.view is not None
    assert result.view.track.active_version_id == VERSION_ID
    assert repo.versions[PREVIOUS_VERSION_ID].status == CampaignVersionStatus.RETIRED
    assert repo.versions[PREVIOUS_VERSION_ID].track_version_id == PREVIOUS_VERSION_ID
    assert repo.locked_track_ids == [TRACK_ID]
    assert repo.publish_operations == [
        "lock_track",
        "replace_steps",
        "retire_versions",
        "save_version",
        "save_track",
    ]
    evidence = audit_repo.logs[-1].details["publish_evidence"]
    assert isinstance(evidence, dict)
    assert evidence["steps"][0]["template_version_id"]
    assert result.validation is not None
    assert result.validation.publishable
    publish_evidence = audit_repo.logs[-1].details["publish_evidence"]
    assert isinstance(publish_evidence, dict)
    assert publish_evidence["track_version_id"] == str(VERSION_ID)
    assert len(str(audit_repo.logs[-1].details["preview_reference"])) == 64
    assert event_bus.events[-1].event_type == DomainEventType.PAUSED_SEARCH_TRACK_PUBLISHED


def test_update_published_track_creates_new_draft_without_mutating_active_version() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repo.versions[PREVIOUS_VERSION_ID] = _version(
        track_version_id=PREVIOUS_VERSION_ID,
        status=CampaignVersionStatus.PUBLISHED,
    )
    repo.steps[PREVIOUS_VERSION_ID] = _step_tuple(PREVIOUS_VERSION_ID)
    config = _config(max_total_touches=3)
    config = replace(
        config,
        steps=(
            *config.steps,
            PausedSearchTrackStepInput(
                phase=PausedSearchTrackStepPhase.REACTIVATION,
                channel=ContactChannel.EMAIL,
                delay_hours=24,
                message_goal="Reconnect when the lead may be ready to act.",
                template_key="paused-search-reactivation-email-2",
                template_version_id=PREVIOUS_VERSION_ID,
                max_attempts=1,
                template_profile=DormantStepTemplateProfile(),
            ),
        ),
    )

    result = _run(
        update_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            track_key="rented-year",
            display_name="Rented for a year updated",
            config=config,
            repository=repo,
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status == PausedSearchTrackDraftStatus.UPDATED
    assert result.view is not None
    assert result.view.version.version_number == 2
    assert result.view.version.status == CampaignVersionStatus.DRAFT
    assert len(result.view.steps) == 2
    assert repo.versions[PREVIOUS_VERSION_ID].status == CampaignVersionStatus.PUBLISHED
    assert repo.tracks[TRACK_ID].active_version_id == PREVIOUS_VERSION_ID

    readback = _run(
        list_paused_search_track_views(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            repository=repo,
        )
    )

    assert readback.views[0].version.track_version_id == result.view.version.track_version_id
    assert readback.views[0].steps == result.view.steps


def test_retire_track_keeps_pinned_version_readable() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.PUBLISHED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)

    result = _run(
        retire_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            repository=repo,
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status.value == "retired"
    assert repo.tracks[TRACK_ID].status == PausedSearchTrackStatus.RETIRED
    assert repo.versions[VERSION_ID].status == CampaignVersionStatus.RETIRED
    assert repo.versions[VERSION_ID].track_version_id == VERSION_ID


def test_restore_retired_track_returns_it_as_an_unpublished_draft() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.RETIRED)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.RETIRED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    audit_repo = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        restore_retired_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackRestoreStatus.RESTORED
    assert result.view is not None
    assert repo.tracks[TRACK_ID].status is PausedSearchTrackStatus.DRAFT
    assert repo.tracks[TRACK_ID].active_version_id is None
    assert repo.versions[VERSION_ID].status is CampaignVersionStatus.RETIRED
    assert result.view.version.track_version_id != VERSION_ID
    assert result.view.version.status is CampaignVersionStatus.DRAFT
    assert audit_repo.logs[-1].action.value == "paused_search_track_restored"
    assert event_bus.events[-1].event_type is DomainEventType.PAUSED_SEARCH_TRACK_RESTORED


def test_delete_retired_track_is_blocked_while_leads_are_assigned() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.RETIRED)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.RETIRED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    repo.assigned_leads[TRACK_ID] = (
        PausedSearchTrackLeadAssignment(
            lead_id=UUID("00000000-0000-0000-0000-000000000009"),
            workflow_id=UUID("00000000-0000-0000-0000-00000000000a"),
            track_version_id=VERSION_ID,
            crm_lead_id="fub-123",
            primary_email="lead@example.com",
            lead_stage="paused",
            workflow_state="paused",
        ),
    )
    audit_repo = FakePausedSearchTrackAuditLogRepository()

    result = _run(
        delete_retired_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            repository=repo,
            audit_log_repository=audit_repo,
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackDeleteStatus.BLOCKED
    assert result.view is not None
    assert len(result.view.assigned_leads) == 1
    assert repo.tracks[TRACK_ID].status is PausedSearchTrackStatus.RETIRED
    assert repo.locked_track_ids == [TRACK_ID]
    assert audit_repo.logs == []


def test_delete_retired_track_audits_then_removes_track_after_leads_move() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.RETIRED)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.RETIRED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    audit_repo = FakePausedSearchTrackAuditLogRepository()

    result = _run(
        delete_retired_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            repository=repo,
            audit_log_repository=audit_repo,
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackDeleteStatus.DELETED
    assert TRACK_ID not in repo.tracks
    assert VERSION_ID not in repo.versions
    assert audit_repo.logs[-1].action.value == "paused_search_track_deleted"
    assert audit_repo.logs[-1].track_id == TRACK_ID


class FakePausedSearchTrackAdminRepository:
    def __init__(self) -> None:
        self.tracks: dict[PausedSearchTrackId, PausedSearchTrack] = {}
        self.versions: dict[PausedSearchTrackVersionId, PausedSearchTrackVersion] = {}
        self.steps: dict[PausedSearchTrackVersionId, tuple[PausedSearchTrackStep, ...]] = {}
        self.locked_track_ids: list[PausedSearchTrackId] = []
        self.publish_operations: list[str] = []
        self.assigned_leads: dict[
            PausedSearchTrackId, tuple[PausedSearchTrackLeadAssignment, ...]
        ] = {}

    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        return tuple(track for track in self.tracks.values() if track.workspace_id == workspace_id)

    async def list_active_catalog(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[PausedSearchTrackCatalogEntry, ...]:
        entries: list[PausedSearchTrackCatalogEntry] = []
        for track in self.tracks.values():
            version_id = track.active_version_id
            if track.workspace_id != workspace_id or version_id is None:
                continue
            entries.append(
                PausedSearchTrackCatalogEntry(
                    track_key=track.track_key,
                    display_name=track.display_name,
                    selection_guidance=self.versions[version_id].selection_guidance,
                    track_id=track.track_id,
                    track_version_id=version_id,
                )
            )
        return tuple(entries)

    async def list_assigned_leads(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        *,
        limit: int = 100,
        lock: bool = False,
    ) -> tuple[PausedSearchTrackLeadAssignment, ...]:
        return self.assigned_leads.get(track_id, ())[:limit]

    async def delete_retired_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> None:
        self.tracks.pop(track_id, None)
        for version_id, version in tuple(self.versions.items()):
            if version.track_id == track_id:
                self.versions.pop(version_id)
                self.steps.pop(version_id, None)

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        track = self.tracks.get(track_id)
        return track if track is not None and track.workspace_id == workspace_id else None

    async def get_track_for_update(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        self.locked_track_ids.append(track_id)
        self.publish_operations.append("lock_track")
        return await self.get_track(workspace_id, track_id)

    async def get_track_by_key(
        self,
        workspace_id: WorkspaceId,
        track_key: str,
    ) -> PausedSearchTrack | None:
        return next(
            (
                track
                for track in self.tracks.values()
                if track.workspace_id == workspace_id and track.track_key == track_key
            ),
            None,
        )

    async def save_track(self, track: PausedSearchTrack) -> PausedSearchTrack:
        self.publish_operations.append("save_track")
        self.tracks[track.track_id] = track
        return track

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        version = self.versions.get(track_version_id)
        return version if version is not None and version.workspace_id == workspace_id else None

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        return max(
            (
                version
                for version in self.versions.values()
                if version.workspace_id == workspace_id
                and version.track_id == track_id
                and version.status == CampaignVersionStatus.DRAFT
            ),
            key=lambda version: version.version_number,
            default=None,
        )

    async def get_latest_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        return max(
            (
                version
                for version in self.versions.values()
                if version.workspace_id == workspace_id and version.track_id == track_id
            ),
            key=lambda version: version.version_number,
            default=None,
        )

    async def get_latest_version_number(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> int:
        return max(
            (
                version.version_number
                for version in self.versions.values()
                if version.workspace_id == workspace_id and version.track_id == track_id
            ),
            default=0,
        )

    async def save_version(
        self,
        version: PausedSearchTrackVersion,
    ) -> PausedSearchTrackVersion:
        self.publish_operations.append("save_version")
        self.versions[version.track_version_id] = version
        return version

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        return tuple(
            step
            for step in self.steps.get(track_version_id, ())
            if step.workspace_id == workspace_id
        )

    async def replace_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
        steps: tuple[PausedSearchTrackStep, ...],
    ) -> tuple[PausedSearchTrackStep, ...]:
        self.publish_operations.append("replace_steps")
        saved = tuple(step for step in steps if step.workspace_id == workspace_id)
        self.steps[track_version_id] = saved
        return saved

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        except_version_id: PausedSearchTrackVersionId | None,
    ) -> None:
        self.publish_operations.append("retire_versions")
        for version_id, version in tuple(self.versions.items()):
            if (
                version.workspace_id == workspace_id
                and version.track_id == track_id
                and version.track_version_id != except_version_id
                and version.status == CampaignVersionStatus.PUBLISHED
            ):
                self.versions[version_id] = replace(version, status=CampaignVersionStatus.RETIRED)


class FakePausedSearchTrackAuditLogRepository:
    def __init__(self) -> None:
        self.logs: list[PausedSearchTrackAdminAuditLog] = []

    async def append(
        self,
        audit_log: PausedSearchTrackAdminAuditLog,
    ) -> PausedSearchTrackAdminAuditLog:
        self.logs.append(audit_log)
        return audit_log


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeTemplateRepository:
    def __init__(self) -> None:
        self.templates: dict[UUID, TemplateVersion] = {}

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        template_version_id: UUID,
    ) -> TemplateVersion | None:
        template = self.templates.get(template_version_id)
        return template if template is not None and template.workspace_id == workspace_id else None

    async def get_by_key_and_version(
        self,
        workspace_id: WorkspaceId,
        template_key: str,
        version: int,
    ) -> TemplateVersion | None:
        return next(
            (
                template
                for template in self.templates.values()
                if template.workspace_id == workspace_id
                and template.template_key == template_key
                and template.version == version
            ),
            None,
        )

    async def get_latest_approved_by_key(
        self,
        workspace_id: WorkspaceId,
        template_key: str,
    ) -> TemplateVersion:
        existing = next(
            (
                template
                for template in self.templates.values()
                if template.workspace_id == workspace_id
                and template.template_key == template_key
                and template.status is TemplateStatus.APPROVED
            ),
            None,
        )
        if existing is not None:
            return existing
        template = TemplateVersion(
            template_version_id=uuid5(WORKSPACE_ID, template_key),
            workspace_id=workspace_id,
            template_key=template_key,
            version=1,
            channel=TemplateChannel.EMAIL,
            purpose="paused_search",
            content="{{message_body}}",
            subject="Checking in",
            prompt_text="Write a concise check-in.",
            allowed_variables=("agent_name", "brokerage_name", "lead_first_name", "message_body"),
            permitted_use_tags=(
                "no_prohibited_advice",
                "no_financial_advice",
                "no_legal_advice",
                "no_tax_advice",
                "no_investment_advice",
                "no_market_predictions",
                "no_unverified_listing_claims",
                "listing_context_allowed",
            ),
            status=TemplateStatus.APPROVED,
            approved_at=NOW,
            created_at=NOW,
        )
        self.templates[template.template_version_id] = template
        return template

    async def save(self, template: TemplateVersion) -> TemplateVersion:
        self.templates[template.template_version_id] = template
        return template

    async def list_approved(self, workspace_id: WorkspaceId) -> tuple[TemplateVersion, ...]:
        return tuple(
            template
            for template in self.templates.values()
            if template.workspace_id == workspace_id and template.status is TemplateStatus.APPROVED
        )


def _config(
    *,
    max_total_touches: int = 2,
    selection_guidance: str = "Select when a temporary renter plans to search again later.",
) -> PausedSearchTrackConfigInput:
    return PausedSearchTrackConfigInput(
        selection_guidance=selection_guidance,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=90,
        reactivation_window_days=45,
        max_total_touches=max_total_touches,
        steps=(
            PausedSearchTrackStepInput(
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                channel=ContactChannel.EMAIL,
                delay_hours=24 * 90,
                message_goal="Check whether the lead's plans have changed.",
                template_key="paused-search-maintenance-email-1",
                max_attempts=1,
            ),
        ),
    )


def _track(*, status: PausedSearchTrackStatus) -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="rented-year",
        display_name="Rented for a year",
        status=status,
        active_version_id=PREVIOUS_VERSION_ID,
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version(
    *,
    track_version_id: UUID = VERSION_ID,
    status: CampaignVersionStatus,
    version_number: int = 1,
) -> PausedSearchTrackVersion:
    config = _config()
    return PausedSearchTrackVersion(
        track_version_id=track_version_id,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=version_number,
        status=status,
        selection_guidance=config.selection_guidance,
        enabled=config.enabled,
        allowed_channels=config.allowed_channels,
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=config.max_total_touches,
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
        published_at=NOW if status == CampaignVersionStatus.PUBLISHED else None,
    )


def _step_tuple(track_version_id: UUID) -> tuple[PausedSearchTrackStep, ...]:
    config = _config()
    return (
        PausedSearchTrackStep(
            step_id=UUID("00000000-0000-0000-0000-000000000007"),
            workspace_id=WORKSPACE_ID,
            track_version_id=track_version_id,
            step_order=1,
            phase=config.steps[0].phase,
            channel=config.steps[0].channel,
            delay_hours=config.steps[0].delay_hours,
            message_goal=config.steps[0].message_goal,
            template_key=config.steps[0].template_key,
            max_attempts=config.steps[0].max_attempts,
            review_required=config.steps[0].review_required,
            created_at=NOW,
        ),
    )


def _actor(
    *,
    role: WorkspaceMembershipRole = WorkspaceMembershipRole.BROKERAGE_ADMIN,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
