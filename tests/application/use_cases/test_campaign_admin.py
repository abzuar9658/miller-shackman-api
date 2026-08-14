from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

from app.application.use_cases.campaign_admin import (
    CampaignCadenceStepInput,
    CampaignConfigInput,
    CampaignReadStatus,
    CreateDraftCampaignStatus,
    PauseCampaignStatus,
    PublishCampaignVersionStatus,
    ResumeCampaignStatus,
    UpdateDraftCampaignStatus,
    create_draft_campaign,
    get_campaign_admin_view,
    list_campaign_admin_views,
    pause_campaign,
    publish_campaign_version,
    resume_campaign,
    update_draft_campaign,
)
from app.domain.campaigns.admin import (
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEventType
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config
from tests.application.use_cases._campaign_admin_fakes import (
    FakeCampaignAdminAuditLogRepository,
    FakeCampaignAdminRepository,
    FakeEventBus,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
PREVIOUS_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")


def test_create_draft_campaign_persists_audit_and_event() -> None:
    repo = FakeCampaignAdminRepository()
    audit_repo = FakeCampaignAdminAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        create_draft_campaign(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            name="Dormant Buyers",
            config=_config(),
            campaign_admin_repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            now=NOW,
        ),
    )

    assert result.status == CreateDraftCampaignStatus.CREATED
    assert result.view is not None
    assert result.view.campaign.status == CampaignStatus.DRAFT
    assert result.view.version.status == CampaignVersionStatus.DRAFT
    assert len(result.view.cadence_steps) == 1
    assert audit_repo.logs[-1].action.value == "campaign_draft_created"
    assert event_bus.events[-1].event_type == DomainEventType.CAMPAIGN_DRAFT_CREATED


def test_create_draft_campaign_rejects_assigned_agent() -> None:
    result = _run(
        create_draft_campaign(
            actor=_actor(role=WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            name="Dormant Buyers",
            config=_config(),
            campaign_admin_repository=FakeCampaignAdminRepository(),
            audit_log_repository=FakeCampaignAdminAuditLogRepository(),
            now=NOW,
        ),
    )

    assert result.status == CreateDraftCampaignStatus.REJECTED
    assert result.reasons[0].value == "permission_denied"


def test_create_draft_campaign_rejects_duplicate_template_keys() -> None:
    config = _config()
    duplicate_step = replace(config.cadence_steps[0], delay_hours=48)

    result = _run(
        create_draft_campaign(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            name="Dormant Buyers",
            config=replace(
                config,
                cadence_steps=(config.cadence_steps[0], duplicate_step),
            ),
            campaign_admin_repository=FakeCampaignAdminRepository(),
            audit_log_repository=FakeCampaignAdminAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status == CreateDraftCampaignStatus.REJECTED
    assert result.reasons[0].value == "invalid_configuration"


def test_campaign_read_views_require_reporting_permission_and_include_latest_version() -> None:
    repo = FakeCampaignAdminRepository()
    repo.campaigns[CAMPAIGN_ID] = _campaign(status=CampaignStatus.ACTIVE)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.PUBLISHED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)

    list_result = _run(
        list_campaign_admin_views(
            actor=_actor(role=WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            campaign_admin_repository=repo,
        )
    )
    detail_result = _run(
        get_campaign_admin_view(
            actor=_actor(role=WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_admin_repository=repo,
        )
    )
    rejected_result = _run(
        list_campaign_admin_views(
            actor=_actor(role=WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            campaign_admin_repository=repo,
        )
    )

    assert list_result.status == CampaignReadStatus.OK
    assert list_result.views[0].version.campaign_version_id == VERSION_ID
    assert detail_result.status == CampaignReadStatus.OK
    assert detail_result.view is not None
    assert detail_result.view.cadence_steps == _step_tuple(VERSION_ID)
    assert rejected_result.status == CampaignReadStatus.REJECTED
    assert rejected_result.reasons[0].value == "permission_denied"


def test_update_published_campaign_creates_next_draft_version() -> None:
    repo = FakeCampaignAdminRepository()
    repo.campaigns[CAMPAIGN_ID] = _campaign(status=CampaignStatus.ACTIVE)
    repo.versions[PREVIOUS_VERSION_ID] = _version(
        campaign_version_id=PREVIOUS_VERSION_ID,
        status=CampaignVersionStatus.PUBLISHED,
        version_number=1,
    )
    audit_repo = FakeCampaignAdminAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        update_draft_campaign(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            name="Dormant Buyers Updated",
            config=_config(daily_start_cap=25),
            campaign_admin_repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            now=NOW,
        ),
    )

    assert result.status == UpdateDraftCampaignStatus.UPDATED
    assert result.view is not None
    assert result.view.campaign.name == "Dormant Buyers Updated"
    assert result.view.version.version_number == 2
    assert result.view.version.status == CampaignVersionStatus.DRAFT
    assert result.view.version.daily_start_cap == 25
    assert event_bus.events[-1].event_type == DomainEventType.CAMPAIGN_DRAFT_UPDATED


def test_publish_draft_activates_campaign_and_retires_previous_version() -> None:
    repo = FakeCampaignAdminRepository()
    repo.campaigns[CAMPAIGN_ID] = _campaign(status=CampaignStatus.PAUSED)
    repo.versions[PREVIOUS_VERSION_ID] = _version(
        campaign_version_id=PREVIOUS_VERSION_ID,
        status=CampaignVersionStatus.PUBLISHED,
        version_number=1,
    )
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.DRAFT, version_number=2)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    audit_repo = FakeCampaignAdminAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        publish_campaign_version(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=VERSION_ID,
            campaign_admin_repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            now=NOW,
        ),
    )

    assert result.status == PublishCampaignVersionStatus.PUBLISHED
    assert result.view is not None
    assert result.view.campaign.status == CampaignStatus.ACTIVE
    assert result.view.campaign.active_version_id == VERSION_ID
    assert repo.versions[PREVIOUS_VERSION_ID].status == CampaignVersionStatus.RETIRED
    assert event_bus.events[-1].event_type == DomainEventType.CAMPAIGN_PUBLISHED


def test_manager_can_pause_active_campaign() -> None:
    repo = FakeCampaignAdminRepository()
    repo.campaigns[CAMPAIGN_ID] = _campaign(status=CampaignStatus.ACTIVE)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.PUBLISHED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    event_bus = FakeEventBus()

    result = _run(
        pause_campaign(
            actor=_actor(role=WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            reason="Pilot pause",
            campaign_admin_repository=repo,
            audit_log_repository=FakeCampaignAdminAuditLogRepository(),
            event_bus=event_bus,
            now=NOW,
        ),
    )

    assert result.status == PauseCampaignStatus.PAUSED
    assert result.view is not None
    assert result.view.campaign.status == CampaignStatus.PAUSED
    assert event_bus.events[-1].event_type == DomainEventType.CAMPAIGN_PAUSED


def test_manager_can_resume_paused_campaign() -> None:
    repo = FakeCampaignAdminRepository()
    repo.campaigns[CAMPAIGN_ID] = _campaign(status=CampaignStatus.PAUSED)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.PUBLISHED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    event_bus = FakeEventBus()

    result = _run(
        resume_campaign(
            actor=_actor(role=WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            reason="Resume after review",
            campaign_admin_repository=repo,
            audit_log_repository=FakeCampaignAdminAuditLogRepository(),
            event_bus=event_bus,
            now=NOW,
        ),
    )

    assert result.status == ResumeCampaignStatus.RESUMED
    assert result.view is not None
    assert result.view.campaign.status == CampaignStatus.ACTIVE
    assert event_bus.events[-1].event_type == DomainEventType.CAMPAIGN_RESUMED


def _config(*, daily_start_cap: int = 50) -> CampaignConfigInput:
    return CampaignConfigInput(
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=daily_start_cap,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=True,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=True,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStepInput(
                channel=ContactChannel.EMAIL,
                delay_hours=24,
                message_goal="Check whether the lead is still considering a move.",
                template_key="dormant-email-1",
                max_attempts=1,
            ),
        ),
        outbound_drafting_config=default_workspace_outbound_drafting_config(WORKSPACE_ID),
    )


def _campaign(*, status: CampaignStatus) -> CampaignAdminCampaign:
    return CampaignAdminCampaign(
        campaign_id=CAMPAIGN_ID,
        workspace_id=WORKSPACE_ID,
        name="Dormant Buyers",
        status=status,
        active_version_id=VERSION_ID,
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version(
    *,
    campaign_version_id: UUID = VERSION_ID,
    status: CampaignVersionStatus,
    version_number: int = 1,
) -> CampaignAdminVersion:
    return CampaignAdminVersion(
        campaign_version_id=campaign_version_id,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        version_number=version_number,
        status=status,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        preflight_digest_enabled=True,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=True,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
        published_at=NOW if status == CampaignVersionStatus.PUBLISHED else None,
    )


def _step_tuple(campaign_version_id: UUID) -> tuple[CampaignAdminCadenceStep, ...]:
    config = _config()
    return (
        CampaignAdminCadenceStep(
            cadence_step_id=UUID("00000000-0000-0000-0000-000000000007"),
            workspace_id=WORKSPACE_ID,
            campaign_version_id=campaign_version_id,
            step_order=1,
            channel=config.cadence_steps[0].channel,
            delay_hours=config.cadence_steps[0].delay_hours,
            message_goal=config.cadence_steps[0].message_goal,
            template_key=config.cadence_steps[0].template_key,
            max_attempts=config.cadence_steps[0].max_attempts,
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
