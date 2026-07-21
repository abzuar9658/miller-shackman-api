# ruff: noqa: E402
"""Interactive wizard for end-to-end testing of CRM-sync tag auto-enrollment.

This script walks a human through the full local flow:
  1. Verify environment and infrastructure
  2. Seed the demo workspace (or reuse it)
  3. Disable the preflight digest so the workflow starts immediately
  4. Tag a lead in Follow Up Boss with the configured campaign tag
  5. Trigger a full CRM sync and watch it complete
  6. Verify the DB shows a lead, crm_tag enrollment, and lead workflow
  7. Verify the workflow in Temporal UI and the first outbound message in Mailpit/logs
  8. Re-run the sync to prove idempotency

Run with:
    arch -arm64 uv run python scripts/run_sync_enrollment_wizard.py
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.use_cases.crm_sync import RequestCRMSyncStatus, request_crm_sync
from app.core.config import Settings, get_settings
from app.core.database import enable_postgres_service_access
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.crm_sync import CRMSyncType
from app.infrastructure.persistence.postgres.crm_sync_repository import PostgresCRMSyncJobRepository
from app.infrastructure.persistence.postgres.models import (
    CampaignModel,
    CampaignVersionModel,
    CRMSyncJobModel,
    LeadModel,
    WorkspaceModel,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)
from scripts.create_demo_workspace import (
    DemoSeedOptions,
    seed_demo_workspace,
)

TAG_NAME = "ai_nurture"
PREFLIGHT_DISABLE_SQL = "Disabled preflight digest so workflow can start immediately."
REQUIRED_ENV_KEYS = ("FUB_API_KEY", "CRM_PROVIDER")


def _color(code: int, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _green(text: str) -> str: return _color(32, text)
def _red(text: str) -> str: return _color(31, text)
def _yellow(text: str) -> str: return _color(33, text)
def _cyan(text: str) -> str: return _color(36, text)
def _bold(text: str) -> str: return _color(1, text)


def _print_step(number: int, title: str) -> None:
    print(f"\n{_bold(_cyan(f'== Step {number}: {title} =='))}")


def _print_ok(text: str) -> None:
    print(f"  {_green('✓')} {text}")


def _print_warn(text: str) -> None:
    print(f"  {_yellow('⚠')} {text}")


def _print_fail(text: str) -> None:
    print(f"  {_red('✗')} {text}")


def _prompt(text: str, default: str = "") -> str:
    prompt = f"\n{_cyan('>')} {text}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    return input(prompt).strip() or default


def _confirm(text: str) -> bool:
    answer = _prompt(f"{text} (y/n)", "y").lower()
    return answer in {"y", "yes"}


def _wait_for_enter(text: str = "Press Enter to continue...") -> None:
    input(f"\n{_cyan(text)} ")


def _run_shell(
    cmd: str,
    *,
    cwd: Path = PROJECT_ROOT,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    print(f"\n  Running: {_bold(cmd)}")
    return subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _make_engine(settings: Settings) -> Any:
    return create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)


@dataclass
class WizardState:
    settings: Settings = field(default_factory=get_settings)
    workspace_id: UUID | None = None
    campaign_id: UUID | None = None
    campaign_version_id: UUID | None = None
    lead_id: UUID | None = None
    crm_lead_id: str | None = None
    lead_email: str | None = None
    sync_job_id: UUID | None = None
    enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    enrollment_count_before: int = 0
    workflow_count_before: int = 0
    checks: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def _async_session_factory(self) -> async_sessionmaker[AsyncSession]:
        engine = _make_engine(self.settings)
        return async_sessionmaker(engine, expire_on_commit=False)

    async def session(self) -> AsyncSession:
        factory = self._async_session_factory()
        return factory()


async def _check_env(state: WizardState) -> bool:
    _print_step(1, "Environment and .env")
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        _print_fail(".env file not found. Copy .env.example to .env and fill it in.")
        return False
    _print_ok(".env file exists")

    missing = []
    for key in REQUIRED_ENV_KEYS:
        value = getattr(state.settings, key.lower(), None)
        if value is None or str(value) == "":
            missing.append(key)

    if missing:
        _print_fail(f"Missing required env values: {', '.join(missing)}")
        return False

    _print_ok(f"Required env values present: {', '.join(REQUIRED_ENV_KEYS)}")
    _print_ok(f"CRM_PROVIDER={state.settings.crm_provider}")
    _print_ok(f"SMS_PROVIDER={state.settings.sms_provider}")
    _print_ok(f"EMAIL_PROVIDER={state.settings.email_provider}")

    if state.settings.crm_provider.lower() != "follow_up_boss":
        _print_warn("This wizard is only tested with CRM_PROVIDER=follow_up_boss")
    return True


async def _check_infra(state: WizardState) -> bool:
    _print_step(2, "Infrastructure reachability")
    ports = {
        "Postgres": ("localhost", 55432),
        "RabbitMQ": ("localhost", 55672),
        "Temporal gRPC": ("localhost", 57233),
        "Temporal UI": ("localhost", 58080),
        "Mailpit web": ("localhost", 58025),
        "Mailpit SMTP": ("localhost", 51025),
    }
    all_open = True
    for name, (host, port) in ports.items():
        if _port_is_open(host, port):
            _print_ok(f"{name} reachable on {host}:{port}")
        else:
            _print_fail(f"{name} NOT reachable on {host}:{port}")
            all_open = False

    if not all_open:
        _print_warn("Start infrastructure with: make infra-up && make migrate")
        if _confirm("Try to run 'make infra-up && make migrate' now?"):
            for subcmd in ("make infra-up", "make migrate"):
                result = _run_shell(subcmd)
                if result.returncode != 0:
                    print(result.stdout)
                    print(result.stderr)
                    _print_fail(f"{subcmd} failed")
                    return False
                _print_ok(f"{subcmd} completed")
            return await _check_infra(state)
        return False
    return True


async def _check_workers(state: WizardState) -> bool:
    _print_step(3, "Worker processes")
    _print_warn("The wizard cannot reliably detect background worker processes.")
    print("  Please ensure these are running in separate terminals:")
    print("    Terminal A (optional): make run")
    print("    Terminal B (required):  make worker")
    print("    Terminal C (required):  make crm-sync-worker")
    print("    Terminal D (optional):  make outbox-publisher")
    _wait_for_enter("Press Enter after the workers are running...")
    return True


async def _prepare_demo_workspace(state: WizardState) -> bool:
    _print_step(4, "Prepare demo workspace")
    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await enable_postgres_service_access(session)
        existing_result = await session.execute(
            select(WorkspaceModel).where(WorkspaceModel.name == "Demo: Miller Schackman")
        )
        existing_workspace = existing_result.scalar_one_or_none()

    if existing_workspace is None:
        _print_warn("Demo workspace not found. It will be seeded now.")
        _print_warn("The demo seed requires SMS_PROVIDER=sink and EMAIL_PROVIDER=sink.")
        if not _confirm("Seed the demo workspace now?"):
            return False

        async with session_factory() as session:
            await enable_postgres_service_access(session)
            result = await seed_demo_workspace(
                session,
                settings=state.settings,
                options=DemoSeedOptions(),
            )
            await session.commit()
            state.workspace_id = result.workspace_id
            state.campaign_id = result.campaign_id
            state.campaign_version_id = result.campaign_version_id
        _print_ok(f"Demo workspace seeded: {state.workspace_id}")
        _print_ok(f"Campaign seeded: {state.campaign_id}")
        return True

    state.workspace_id = existing_workspace.workspace_id
    _print_ok(f"Demo workspace: {state.workspace_id}")

    await engine.dispose()
    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await enable_postgres_service_access(session)
        tagged_version_result = await session.execute(
            select(CampaignVersionModel)
            .join(CampaignModel)
            .where(CampaignVersionModel.workspace_id == state.workspace_id)
            .where(CampaignVersionModel.crm_enrollment_tag == TAG_NAME)
            .where(CampaignModel.status == "active")
        )
        tagged_version = tagged_version_result.scalar_one_or_none()
        if tagged_version is not None:
            campaign_result = await session.execute(
                select(CampaignModel).where(CampaignModel.campaign_id == tagged_version.campaign_id)
            )
            campaign = campaign_result.scalar_one_or_none()
            if campaign is not None:
                state.campaign_id = campaign.campaign_id
                state.campaign_version_id = campaign.active_version_id
                _print_ok(f"Campaign with tag '{TAG_NAME}' found: {state.campaign_id}")
                await engine.dispose()
                return True

        # No campaign with the tag. Try to find an active campaign to repurpose.
        any_active_result = await session.execute(
            select(CampaignModel)
            .where(CampaignModel.workspace_id == state.workspace_id)
            .where(CampaignModel.status == "active")
            .order_by(CampaignModel.created_at.desc())
        )
        any_active = any_active_result.scalar_one_or_none()
        if any_active is None:
            _print_fail("No active campaign found in the workspace")
            await engine.dispose()
            return False

        _print_warn(
            f"No campaign with tag '{TAG_NAME}' found. "
            f"Active campaign: '{any_active.name}' ({any_active.campaign_id})."
        )
        if not _confirm(
            f"Set crm_enrollment_tag='{TAG_NAME}' and disable preflight digest on "
            f"'{any_active.name}' for this test?"
        ):
            _print_fail("A campaign with the configured tag is required to continue")
            await engine.dispose()
            return False

        active_version_id = any_active.active_version_id
        if active_version_id is None:
            _print_fail("Active campaign has no published version")
            await engine.dispose()
            return False

        await session.execute(
            update(CampaignVersionModel)
            .where(CampaignVersionModel.campaign_version_id == active_version_id)
            .values(crm_enrollment_tag=TAG_NAME, preflight_digest_enabled=False)
        )
        await session.commit()
        state.campaign_id = any_active.campaign_id
        state.campaign_version_id = active_version_id
        _print_ok(f"Campaign prepared: {state.campaign_id}")
        _print_ok(f"  tag={TAG_NAME}")
        _print_ok("  preflight digest disabled")

    await engine.dispose()
    return True



async def _disable_preflight_digest(state: WizardState) -> bool:
    _print_step(5, "Disable preflight digest for immediate workflow start")
    if state.campaign_version_id is None:
        _print_fail("No campaign version selected")
        return False

    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await enable_postgres_service_access(session)
        version_result = await session.execute(
            select(CampaignVersionModel)
            .where(CampaignVersionModel.campaign_version_id == state.campaign_version_id)
        )
        version = version_result.scalar_one_or_none()
        if version is None:
            _print_fail("Campaign version not found")
            await engine.dispose()
            return False

        if not version.preflight_digest_enabled:
            _print_ok("Preflight digest is already disabled")
            await engine.dispose()
            return True

        if not _confirm("Disable preflight digest so the workflow starts immediately?"):
            _print_warn("Workflow will be held in preflight digest for 24 hours.")
            await engine.dispose()
            return True

        await session.execute(
            update(CampaignVersionModel)
            .where(CampaignVersionModel.campaign_version_id == state.campaign_version_id)
            .values(preflight_digest_enabled=False)
        )
        await session.commit()
        _print_ok("Preflight digest disabled for this campaign version")

    await engine.dispose()
    return True


async def _manual_tag_prompt(state: WizardState) -> bool:
    _print_step(6, "Tag a lead in Follow Up Boss")
    print(
        "  In your FUB test account, open a fresh lead that has an email and/or phone number."
    )
    print("  Make sure that lead has never already been enrolled in this campaign.")
    print(f"  Add the tag: {_bold(TAG_NAME)}")
    print(f"  The campaign {state.campaign_id} is configured to auto-enroll leads with this tag.")
    _wait_for_enter("Press Enter after you have tagged the lead in FUB...")
    return True


async def _trigger_sync(state: WizardState) -> bool:
    _print_step(7, "Trigger full CRM sync")
    if state.workspace_id is None:
        _print_fail("No workspace selected")
        return False

    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await enable_postgres_service_access(session)
        result = await request_crm_sync(
            workspace_id=state.workspace_id,
            sync_type=CRMSyncType.FULL,
            crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
            event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            now=datetime.now(UTC),
        )
        await session.commit()

    if result.status != RequestCRMSyncStatus.REQUESTED:
        _print_fail(f"Sync request rejected: {result.status.value}")
        if result.job:
            _print_warn(f"Existing job: {result.job.sync_job_id}")
        await engine.dispose()
        return False

    state.sync_job_id = result.job.sync_job_id
    _print_ok(f"Requested full sync job: {state.sync_job_id}")
    await engine.dispose()
    return True


async def _wait_for_sync(state: WizardState) -> bool:
    _print_step(8, "Wait for CRM sync to complete")
    if state.sync_job_id is None:
        _print_fail("No sync job ID")
        return False

    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    deadline = datetime.now(UTC) + timedelta(minutes=5)

    while datetime.now(UTC) < deadline:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            job_result = await session.execute(
                select(CRMSyncJobModel)
                .where(CRMSyncJobModel.sync_job_id == state.sync_job_id)
            )
            job = job_result.scalar_one_or_none()

        if job is None:
            _print_fail("Sync job disappeared from the database")
            await engine.dispose()
            return False

        if job.status in {"completed", "failed"}:
            _print_ok(f"Sync job finished with status={job.status}")
            print(
                f"  seen={job.total_seen} "
                f"upserted={job.total_upserted} "
                f"failed={job.total_failed}"
            )
            if job.status == "failed":
                _print_fail(f"Failure reason: {job.failure_reason}")
                await engine.dispose()
                return False
            await engine.dispose()
            return True

        _print_warn(f"Sync job status={job.status} ... waiting")
        await asyncio.sleep(2)

    _print_fail("Timed out waiting for CRM sync to complete")
    await engine.dispose()
    return False


async def _verify_db_state(state: WizardState) -> bool:
    _print_step(9, "Verify database state")
    if (
        state.workspace_id is None
        or state.campaign_id is None
        or state.campaign_version_id is None
        or state.sync_job_id is None
    ):
        _print_fail("Missing workspace, campaign, version, or sync job ID")
        return False

    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await enable_postgres_service_access(session)

        sync_job_result = await session.execute(
            select(CRMSyncJobModel).where(CRMSyncJobModel.sync_job_id == state.sync_job_id)
        )
        sync_job = sync_job_result.scalar_one_or_none()
        if sync_job is None:
            _print_fail("Sync job not found during DB verification")
            await engine.dispose()
            return False

        enrollment_result = await session.execute(
            select(CampaignEnrollmentModel)
            .where(CampaignEnrollmentModel.workspace_id == state.workspace_id)
            .where(CampaignEnrollmentModel.campaign_id == state.campaign_id)
            .where(CampaignEnrollmentModel.campaign_version_id == state.campaign_version_id)
            .where(CampaignEnrollmentModel.source == CampaignEnrollmentSource.CRM_TAG.value)
            .where(CampaignEnrollmentModel.created_at >= sync_job.created_at)
            .order_by(CampaignEnrollmentModel.created_at.desc())
            .limit(2)
        )
        enrollments = enrollment_result.scalars().all()

        if not enrollments:
            recent_lead_result = await session.execute(
                select(LeadModel)
                .where(LeadModel.workspace_id == state.workspace_id)
                .where(LeadModel.tags.has_key(TAG_NAME))
                .order_by(LeadModel.updated_at.desc())
                .limit(5)
            )
            recent_leads = recent_lead_result.scalars().all()
            if recent_leads:
                lead = recent_leads[0]
                state.lead_id = lead.lead_id
                state.crm_lead_id = lead.crm_lead_id
                state.lead_email = lead.primary_email
                if len(recent_leads) > 1:
                    _print_warn(
                        f"Multiple leads with tag '{TAG_NAME}' were synced; "
                        "checking most recent candidates"
                    )
                _print_ok(f"Lead found: {lead.lead_id}")
                _print_ok(f"  crm_lead_id={lead.crm_lead_id}")
                _print_ok(f"  primary_email={lead.primary_email}")
                _print_ok(f"  primary_phone={lead.primary_phone}")

                existing_enrollment_result = await session.execute(
                    select(CampaignEnrollmentModel)
                    .where(CampaignEnrollmentModel.workspace_id == state.workspace_id)
                    .where(CampaignEnrollmentModel.campaign_id == state.campaign_id)
                    .where(
                        CampaignEnrollmentModel.lead_id.in_(
                            [recent_lead.lead_id for recent_lead in recent_leads]
                        )
                    )
                    .order_by(CampaignEnrollmentModel.created_at.desc())
                )
                existing_enrollments = existing_enrollment_result.scalars().all()
                if existing_enrollments:
                    example = existing_enrollments[0]
                    _print_fail(
                        "No new crm_tag enrollment was created. The tagged lead appears to already "
                        "have an existing enrollment in this campaign."
                    )
                    print(
                        f"  Example existing enrollment: lead_id={example.lead_id} "
                        f"source={example.source} status={example.status} "
                        f"created_at={example.created_at.isoformat()}"
                    )
                    print(
                        "  Use a fresh FUB lead that has never been enrolled in this campaign, "
                        "tag it with ai_nurture, then rerun the wizard."
                    )
                    await engine.dispose()
                    return False

            _print_fail(
                "No new crm_tag enrollment was created during this sync. Check worker logs for "
                "eligibility/hold reasons or retry with a fresh lead."
            )
            await engine.dispose()
            return False

        if len(enrollments) > 1:
            _print_warn(
                "Multiple crm_tag enrollments were created during this sync; using the newest one"
            )

        enrollment = enrollments[0]

        lead_result = await session.execute(
            select(LeadModel)
            .where(LeadModel.workspace_id == state.workspace_id)
            .where(LeadModel.lead_id == enrollment.lead_id)
        )
        enrolled_lead = lead_result.scalar_one_or_none()
        if enrolled_lead is None:
            _print_fail("Enrollment was found, but the corresponding lead could not be loaded")
            await engine.dispose()
            return False

        state.lead_id = enrolled_lead.lead_id
        state.crm_lead_id = enrolled_lead.crm_lead_id
        state.lead_email = enrolled_lead.primary_email
        _print_ok(f"Lead found: {enrolled_lead.lead_id}")
        _print_ok(f"  crm_lead_id={enrolled_lead.crm_lead_id}")
        _print_ok(f"  primary_email={enrolled_lead.primary_email}")
        _print_ok(f"  primary_phone={enrolled_lead.primary_phone}")

        state.enrollment_id = enrollment.campaign_enrollment_id
        _print_ok(f"Enrollment found: {enrollment.campaign_enrollment_id}")
        _print_ok(f"  source={enrollment.source}")
        _print_ok(f"  status={enrollment.status}")

        workflow_result = await session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == state.workspace_id)
            .where(LeadWorkflowModel.campaign_id == state.campaign_id)
            .where(LeadWorkflowModel.lead_id == enrolled_lead.lead_id)
            .where(
                LeadWorkflowModel.campaign_enrollment_id == enrollment.campaign_enrollment_id
            )
            .order_by(LeadWorkflowModel.created_at.desc())
            .limit(2)
        )
        workflows = workflow_result.scalars().all()
        if not workflows:
            _print_fail("No lead workflow found for this lead")
            await engine.dispose()
            return False

        if len(workflows) > 1:
            _print_warn("Multiple workflows found; using the newest workflow for the enrollment")

        workflow = workflows[0]

        state.workflow_id = workflow.workflow_id
        state.temporal_workflow_id = workflow.temporal_workflow_id
        _print_ok(f"Workflow found: {workflow.workflow_id}")
        _print_ok(f"  state={workflow.state}")
        _print_ok(f"  temporal_workflow_id={workflow.temporal_workflow_id}")

    await engine.dispose()
    return True


async def _manual_verification_prompts(state: WizardState) -> bool:
    _print_step(10, "Manual verification of Temporal UI and first outbound message")
    print("  Open Temporal UI: http://localhost:58080")
    print("  Search for workflow name: lead-nurture-workflow")
    print(f"  Expected temporal_workflow_id: {state.temporal_workflow_id}")
    _wait_for_enter("Press Enter after you have checked the Temporal UI...")

    print("\n  Open Mailpit: http://localhost:58025")
    print("  Look for an outbound email from the campaign to the lead.")
    print(f"  Lead email: {state.lead_email or 'unknown'}")
    if not _confirm("Did you see the outbound email in Mailpit?"):
        _print_warn("You can verify via worker logs instead.")
        print("  Look for log lines containing:")
        print(f"    - 'lead-nurture-workflow' and '{state.temporal_workflow_id}'")
        print("    - 'EmailProvider.send' or 'SinkEmailProvider' (depending on EMAIL_PROVIDER)")
        print("    - 'CadenceStepExecutionStatus.SCHEDULED' or 'SENT'")
        _wait_for_enter("Press Enter after you have checked the worker logs...")
    return True


async def _idempotency_test(state: WizardState) -> bool:
    _print_step(11, "Idempotency test: re-run the same full sync")
    if state.workspace_id is None or state.lead_id is None:
        _print_fail("Missing workspace_id or lead_id for idempotency test")
        return False

    if not _confirm("Run the full sync again to prove no duplicate workflow is created?"):
        _print_warn("Skipping idempotency test")
        return True

    engine = _make_engine(state.settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await enable_postgres_service_access(session)
        before_enrollments = await session.execute(
            select(CampaignEnrollmentModel)
            .where(CampaignEnrollmentModel.workspace_id == state.workspace_id)
            .where(CampaignEnrollmentModel.lead_id == state.lead_id)
        )
        before_workflows = await session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == state.workspace_id)
            .where(LeadWorkflowModel.lead_id == state.lead_id)
        )
        enrollment_count_before = len(before_enrollments.scalars().all())
        workflow_count_before = len(before_workflows.scalars().all())

    async with session_factory() as session:
        await enable_postgres_service_access(session)
        result = await request_crm_sync(
            workspace_id=state.workspace_id,
            sync_type=CRMSyncType.FULL,
            crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
            event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            now=datetime.now(UTC),
        )
        await session.commit()

    if result.status != RequestCRMSyncStatus.REQUESTED:
        _print_fail(f"Second sync request rejected: {result.status.value}")
        await engine.dispose()
        return False

    second_sync_job_id = result.job.sync_job_id
    _print_ok(f"Second sync requested: {second_sync_job_id}")
    state.checks["second_sync_job_id"] = second_sync_job_id

    deadline = datetime.now(UTC) + timedelta(minutes=5)
    while datetime.now(UTC) < deadline:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            job_result = await session.execute(
                select(CRMSyncJobModel).where(CRMSyncJobModel.sync_job_id == second_sync_job_id)
            )
            job = job_result.scalar_one_or_none()
        if job is not None and job.status in {"completed", "failed"}:
            _print_ok(f"Second sync finished: {job.status}")
            break
        await asyncio.sleep(2)
    else:
        _print_fail("Second sync timed out")
        await engine.dispose()
        return False

    async with session_factory() as session:
        await enable_postgres_service_access(session)
        after_enrollments = await session.execute(
            select(CampaignEnrollmentModel)
            .where(CampaignEnrollmentModel.workspace_id == state.workspace_id)
            .where(CampaignEnrollmentModel.lead_id == state.lead_id)
        )
        after_workflows = await session.execute(
            select(LeadWorkflowModel)
            .where(LeadWorkflowModel.workspace_id == state.workspace_id)
            .where(LeadWorkflowModel.lead_id == state.lead_id)
        )
        enrollment_count_after = len(after_enrollments.scalars().all())
        workflow_count_after = len(after_workflows.scalars().all())

    if enrollment_count_after != enrollment_count_before:
        change = f"{enrollment_count_before} -> {enrollment_count_after}"
        _print_fail(f"Enrollment count changed: {change}")
        await engine.dispose()
        return False

    if workflow_count_after != workflow_count_before:
        _print_fail(f"Workflow count changed: {workflow_count_before} -> {workflow_count_after}")
        await engine.dispose()
        return False

    _print_ok(
        f"Idempotency verified: "
        f"{enrollment_count_after} enrollment(s), {workflow_count_after} workflow(s)"
    )
    await engine.dispose()
    return True


async def _print_report(state: WizardState) -> None:
    _print_step(12, "Final report")
    print("\n" + _bold("Copy this report and paste it back if you want me to review it."))
    print("-" * 60)
    print(f"workspace_id:          {state.workspace_id}")
    print(f"campaign_id:           {state.campaign_id}")
    print(f"campaign_version_id:   {state.campaign_version_id}")
    print(f"lead_id:               {state.lead_id}")
    print(f"crm_lead_id:           {state.crm_lead_id}")
    print(f"sync_job_id:           {state.sync_job_id}")
    print(f"enrollment_id:         {state.enrollment_id}")
    print(f"workflow_id:           {state.workflow_id}")
    print(f"temporal_workflow_id:  {state.temporal_workflow_id}")
    print(f"tag:                   {TAG_NAME}")
    print(f"second_sync_job_id:    {state.checks.get('second_sync_job_id')}")
    print("-" * 60)

    if state.failures:
        print(_red("Failures:"))
        for failure in state.failures:
            print(f"  - {failure}")
    else:
        print(_green("All automated checks passed."))


async def _run_wizard() -> int:
    print(_bold(_cyan("\nWelcome to the CRM-sync tag auto-enrollment end-to-end wizard.\n")))
    state = WizardState()

    steps = [
        _check_env,
        _check_infra,
        _check_workers,
        _prepare_demo_workspace,
        _disable_preflight_digest,
        _manual_tag_prompt,
        _trigger_sync,
        _wait_for_sync,
        _verify_db_state,
        _manual_verification_prompts,
        _idempotency_test,
        _print_report,
    ]

    for step in steps:
        try:
            if not await step(state):
                state.failures.append(f"Step {step.__name__} failed or was aborted")
                _print_fail(
                    f"Wizard stopped at {step.__name__}. "
                    "Final report will still be generated."
                )
                break
        except Exception as exc:
            state.failures.append(f"Step {step.__name__} raised: {exc}")
            _print_fail(f"Unexpected error in {step.__name__}: {exc}")
            break

    await _print_report(state)
    return 0 if not state.failures else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run_wizard()))


if __name__ == "__main__":
    main()
