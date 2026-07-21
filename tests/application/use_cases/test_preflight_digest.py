from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.application.ports.notifications import (
    NotificationSendResult,
    PreflightDigestNotification,
)
from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightVetoRecord,
)
from app.application.use_cases.preflight_digest import (
    PreflightDigestCandidate,
    PreflightDigestPreparationStatus,
    PreflightDigestReasonCode,
    PreflightVetoPolicy,
    PreflightVetoStatus,
    VetoActorRole,
    campaign_start_context_from_digest,
    prepare_preflight_digest,
    record_preflight_veto,
)
from app.domain.campaigns.start_queue import (
    CampaignStartCandidate,
    CampaignStartContext,
    CampaignStartPolicy,
    CampaignStatus,
    StartQueueReasonCode,
    evaluate_campaign_start_batch,
)
from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.compliance.enrollment import CampaignEnrollmentDecision, EnrollmentSource

NOW = datetime(2026, 7, 6, 12, 0, 0)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
BATCH_ID = "batch-2026-07-06"


class FakePreflightDigestRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[WorkspaceId, CampaignId, str], PreflightDigestRecord] = {}
        self.save_count = 0

    async def list_digests_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        return tuple(
            record
            for (record_workspace_id, _, _), record in self.records.items()
            if record_workspace_id == workspace_id
        )[:limit]

    async def get_digest_by_id(
        self,
        workspace_id: WorkspaceId,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        for record in self.records.values():
            if record.workspace_id == workspace_id and record.digest_id == digest_id:
                return record
        return None

    async def get_digest(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        return self.records.get((workspace_id, campaign_id, batch_id))

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        self.save_count += 1
        self.records[(record.workspace_id, record.campaign_id, record.batch_id)] = record


class FakeNotificationProvider:
    def __init__(self, results: list[NotificationSendResult] | None = None) -> None:
        self.results = results or []
        self.notifications: list[PreflightDigestNotification] = []

    async def send_preflight_digest(
        self,
        notification: PreflightDigestNotification,
    ) -> NotificationSendResult:
        self.notifications.append(notification)
        if self.results:
            return self.results.pop(0)
        return NotificationSendResult(accepted=True, provider_reference="notification-1")

    async def send_handoff_notification(self, notification: object) -> NotificationSendResult:
        raise AssertionError("handoff notification should not be used in preflight digest tests")

    async def send_review_notification(self, notification: object) -> NotificationSendResult:
        raise AssertionError("review notification should not be used in preflight digest tests")


def _start_policy(veto_window_hours: int = 24) -> CampaignStartPolicy:
    return CampaignStartPolicy(veto_window_hours=veto_window_hours)


def _start_context(
    *,
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    digest_sent_at: datetime | None = None,
) -> CampaignStartContext:
    return CampaignStartContext(
        campaign_status=campaign_status,
        digest_sent_at=digest_sent_at,
    )


def _start_candidate(
    *,
    lead_id: UUID | None = None,
    source: EnrollmentSource = EnrollmentSource.DORMANT_SELECTOR,
    eligible: bool = True,
    eligible_at: datetime | None = NOW - timedelta(days=1),
    has_assigned_agent: bool | None = True,
    days_since_last_meaningful_communication: int | None = None,
) -> CampaignStartCandidate:
    return CampaignStartCandidate(
        lead_id=lead_id or uuid4(),
        enrollment_decision=CampaignEnrollmentDecision(
            eligible=eligible,
            source=source,
            eligible_at=eligible_at,
        ),
        has_assigned_agent=has_assigned_agent,
        days_since_last_meaningful_communication=days_since_last_meaningful_communication,
    )


def _digest_candidate(
    *,
    start_candidate: CampaignStartCandidate | None = None,
    recipient_id: str | None = "agent-1",
    recipient_destination: str | None = "agent@example.com",
    lead_display_name: str = "Ada Buyer",
) -> PreflightDigestCandidate:
    return PreflightDigestCandidate(
        start_candidate=start_candidate or _start_candidate(),
        recipient_id=recipient_id,
        recipient_destination=recipient_destination,
        lead_display_name=lead_display_name,
    )


def _issued_digest(
    *,
    lead_id: UUID | None = None,
    recipient_id: str = "agent-1",
    digest_sent_at: datetime = NOW,
    veto_window_expires_at: datetime | None = NOW + timedelta(hours=24),
    vetoes: tuple[PreflightVetoRecord, ...] = (),
    status: PreflightDigestIssueStatus = PreflightDigestIssueStatus.ISSUED,
) -> PreflightDigestRecord:
    resolved_lead_id = lead_id or uuid4()
    return PreflightDigestRecord(
        digest_id="digest-1",
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        status=status,
        entries=(
            PreflightDigestEntry(
                lead_id=resolved_lead_id,
                recipient_id=recipient_id,
                recipient_destination="agent@example.com",
                display_name="Ada Buyer",
            ),
        ),
        notification_records=(
            PreflightDigestNotificationRecord(
                recipient_id=recipient_id,
                idempotency_key="preflight-digest:key",
                accepted=True,
            ),
        ),
        digest_sent_at=digest_sent_at if status == PreflightDigestIssueStatus.ISSUED else None,
        veto_window_expires_at=veto_window_expires_at,
        vetoes=vetoes,
    )


async def test_digest_preparation_includes_only_candidates_requiring_review() -> None:
    dormant_candidate = _digest_candidate(lead_display_name="Dormant Lead")
    crm_tag_candidate = _digest_candidate(
        start_candidate=_start_candidate(source=EnrollmentSource.CRM_TAG),
        lead_display_name="Tagged Lead",
    )
    old_unassigned_candidate = _digest_candidate(
        start_candidate=_start_candidate(
            has_assigned_agent=False,
            days_since_last_meaningful_communication=90,
        ),
        recipient_id=None,
        recipient_destination=None,
        lead_display_name="Agentless Lead",
    )
    repository = FakePreflightDigestRepository()
    notifications = FakeNotificationProvider()

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[dormant_candidate, crm_tag_candidate, old_unassigned_candidate],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
        digest_id_factory=lambda: "digest-1",
    )

    assert result.status == PreflightDigestPreparationStatus.ISSUED
    assert result.included_lead_ids == (dormant_candidate.start_candidate.lead_id,)
    assert result.recipients_notified == ("agent-1",)
    assert [item.lead_id for item in notifications.notifications[0].leads] == [
        dormant_candidate.start_candidate.lead_id,
    ]
    assert [item.reasons for item in result.held_back] == [
        (PreflightDigestReasonCode.DIGEST_NOT_REQUIRED,),
        (PreflightDigestReasonCode.DIGEST_NOT_REQUIRED,),
    ]


async def test_digest_preparation_groups_notifications_by_recipient() -> None:
    agent_one_first = _digest_candidate(lead_display_name="Lead One")
    agent_one_second = _digest_candidate(lead_display_name="Lead Two")
    agent_two = _digest_candidate(
        recipient_id="agent-2",
        recipient_destination="agent2@example.com",
        lead_display_name="Lead Three",
    )
    notifications = FakeNotificationProvider()

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[agent_one_first, agent_two, agent_one_second],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=FakePreflightDigestRepository(),
        notification_provider=notifications,
        now=NOW,
        digest_id_factory=lambda: "digest-1",
    )

    assert result.status == PreflightDigestPreparationStatus.ISSUED
    assert result.recipients_notified == ("agent-1", "agent-2")
    assert len(notifications.notifications) == 2
    assert [lead.display_name for lead in notifications.notifications[0].leads] == [
        "Lead One",
        "Lead Two",
    ]
    assert [lead.display_name for lead in notifications.notifications[1].leads] == [
        "Lead Three",
    ]


async def test_missing_recipient_fails_safe_without_sending_digest() -> None:
    repository = FakePreflightDigestRepository()
    notifications = FakeNotificationProvider()

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[_digest_candidate(recipient_id=None, recipient_destination=None)],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
    )

    assert result.status == PreflightDigestPreparationStatus.FAILED
    assert result.reasons == (PreflightDigestReasonCode.MISSING_DIGEST_RECIPIENT,)
    assert result.held_back[0].reasons == (PreflightDigestReasonCode.MISSING_DIGEST_RECIPIENT,)
    assert notifications.notifications == []
    assert repository.save_count == 0


async def test_inactive_campaign_does_not_issue_digest() -> None:
    notifications = FakeNotificationProvider()

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[_digest_candidate()],
        start_policy=_start_policy(),
        start_context=_start_context(campaign_status=CampaignStatus.PAUSED),
        repository=FakePreflightDigestRepository(),
        notification_provider=notifications,
        now=NOW,
    )

    assert result.status == PreflightDigestPreparationStatus.FAILED
    assert result.reasons == (PreflightDigestReasonCode.CAMPAIGN_NOT_ACTIVE,)
    assert notifications.notifications == []


async def test_duplicate_digest_returns_existing_state_without_resending() -> None:
    repository = FakePreflightDigestRepository()
    existing = _issued_digest()
    await repository.save_digest(existing)
    notifications = FakeNotificationProvider()

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[_digest_candidate()],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
    )

    assert result.status == PreflightDigestPreparationStatus.ALREADY_ISSUED
    assert result.digest_id == existing.digest_id
    assert result.reasons == (PreflightDigestReasonCode.DIGEST_ALREADY_ISSUED,)
    assert notifications.notifications == []


async def test_failed_digest_can_be_retried_without_guessing_prior_success() -> None:
    repository = FakePreflightDigestRepository()
    failed = _issued_digest(status=PreflightDigestIssueStatus.FAILED)
    await repository.save_digest(failed)
    notifications = FakeNotificationProvider()

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[
            _digest_candidate(start_candidate=_start_candidate(lead_id=failed.entries[0].lead_id))
        ],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
        digest_id_factory=lambda: "digest-retry",
    )

    assert result.status == PreflightDigestPreparationStatus.ISSUED
    assert result.digest_id == "digest-retry"
    assert len(notifications.notifications) == 1


async def test_notification_failure_does_not_mark_digest_issued() -> None:
    repository = FakePreflightDigestRepository()
    notifications = FakeNotificationProvider([NotificationSendResult(accepted=False)])

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[_digest_candidate()],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
        digest_id_factory=lambda: "digest-1",
    )
    saved = await repository.get_digest(WORKSPACE_ID, CAMPAIGN_ID, BATCH_ID)

    assert result.status == PreflightDigestPreparationStatus.FAILED
    assert result.reasons == (PreflightDigestReasonCode.NOTIFICATION_FAILED,)
    assert saved is not None
    assert saved.status == PreflightDigestIssueStatus.FAILED
    assert saved.digest_sent_at is None


async def test_uncertain_notification_blocks_resend_until_reconciled() -> None:
    repository = FakePreflightDigestRepository()
    notifications = FakeNotificationProvider(
        [NotificationSendResult(accepted=False, uncertain=True)],
    )

    first_result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[_digest_candidate()],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
        digest_id_factory=lambda: "digest-1",
    )
    second_result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[_digest_candidate()],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
    )

    assert first_result.status == PreflightDigestPreparationStatus.UNCERTAIN
    assert second_result.status == PreflightDigestPreparationStatus.UNCERTAIN
    assert second_result.reasons == (PreflightDigestReasonCode.DIGEST_STATE_UNCERTAIN,)
    assert len(notifications.notifications) == 1


async def test_partial_notification_failure_is_marked_uncertain() -> None:
    repository = FakePreflightDigestRepository()
    notifications = FakeNotificationProvider(
        [NotificationSendResult(accepted=True), NotificationSendResult(accepted=False)],
    )

    result = await prepare_preflight_digest(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        candidates=[
            _digest_candidate(recipient_id="agent-1"),
            _digest_candidate(recipient_id="agent-2", recipient_destination="agent2@example.com"),
        ],
        start_policy=_start_policy(),
        start_context=_start_context(),
        repository=repository,
        notification_provider=notifications,
        now=NOW,
        digest_id_factory=lambda: "digest-1",
    )
    saved = await repository.get_digest(WORKSPACE_ID, CAMPAIGN_ID, BATCH_ID)

    assert result.status == PreflightDigestPreparationStatus.UNCERTAIN
    assert result.reasons == (PreflightDigestReasonCode.DIGEST_STATE_UNCERTAIN,)
    assert saved is not None
    assert saved.status == PreflightDigestIssueStatus.UNCERTAIN


async def test_veto_within_window_records_lead_id() -> None:
    lead_id = uuid4()
    repository = FakePreflightDigestRepository()
    await repository.save_digest(_issued_digest(lead_id=lead_id))

    result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=lead_id,
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=2),
        reason="Already working this lead",
    )
    saved = await repository.get_digest(WORKSPACE_ID, CAMPAIGN_ID, BATCH_ID)

    assert result.status == PreflightVetoStatus.RECORDED
    assert result.recorded is True
    assert result.recorded_at == NOW + timedelta(hours=2)
    assert saved is not None
    assert saved.vetoed_lead_ids == frozenset({lead_id})
    assert saved.vetoes[0].reason == "Already working this lead"


async def test_veto_for_lead_not_in_digest_is_rejected() -> None:
    repository = FakePreflightDigestRepository()
    await repository.save_digest(_issued_digest())

    result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=uuid4(),
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=1),
    )

    assert result.status == PreflightVetoStatus.REJECTED
    assert result.reasons == (PreflightDigestReasonCode.CANDIDATE_NOT_IN_DIGEST,)


async def test_veto_after_window_expires_is_rejected_without_mutation() -> None:
    lead_id = uuid4()
    repository = FakePreflightDigestRepository()
    await repository.save_digest(_issued_digest(lead_id=lead_id))

    result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=lead_id,
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=24),
    )
    saved = await repository.get_digest(WORKSPACE_ID, CAMPAIGN_ID, BATCH_ID)

    assert result.status == PreflightVetoStatus.REJECTED
    assert result.reasons == (PreflightDigestReasonCode.VETO_WINDOW_EXPIRED,)
    assert saved is not None
    assert saved.vetoes == ()


async def test_unauthorized_veto_actor_is_rejected() -> None:
    lead_id = uuid4()
    repository = FakePreflightDigestRepository()
    await repository.save_digest(_issued_digest(lead_id=lead_id, recipient_id="agent-1"))

    result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=lead_id,
        actor_id="agent-2",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=1),
    )

    assert result.status == PreflightVetoStatus.REJECTED
    assert result.reasons == (PreflightDigestReasonCode.UNAUTHORIZED_VETO_ACTOR,)


async def test_manager_or_admin_can_veto_digest_entry() -> None:
    lead_id = uuid4()
    repository = FakePreflightDigestRepository()
    await repository.save_digest(_issued_digest(lead_id=lead_id, recipient_id="agent-1"))

    result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=lead_id,
        actor_id="manager-1",
        actor_role=VetoActorRole.MANAGER,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=1),
    )

    assert result.status == PreflightVetoStatus.RECORDED
    assert result.recorded is True


async def test_duplicate_veto_request_is_idempotent_no_op() -> None:
    lead_id = uuid4()
    existing_veto = PreflightVetoRecord(
        lead_id=lead_id,
        actor_id="agent-1",
        recorded_at=NOW + timedelta(hours=1),
        idempotency_key="veto-key",
    )
    repository = FakePreflightDigestRepository()
    await repository.save_digest(_issued_digest(lead_id=lead_id, vetoes=(existing_veto,)))
    save_count_after_setup = repository.save_count

    result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=lead_id,
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW + timedelta(hours=2),
    )

    assert result.status == PreflightVetoStatus.DUPLICATE
    assert result.duplicate is True
    assert result.reasons == (PreflightDigestReasonCode.DUPLICATE_VETO,)
    assert repository.save_count == save_count_after_setup


async def test_veto_rejects_missing_or_uncertain_digest_state() -> None:
    repository = FakePreflightDigestRepository()
    missing_result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=uuid4(),
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW,
    )
    uncertain = _issued_digest(status=PreflightDigestIssueStatus.UNCERTAIN)
    await repository.save_digest(uncertain)
    uncertain_result = await record_preflight_veto(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id=BATCH_ID,
        lead_id=uncertain.entries[0].lead_id,
        actor_id="agent-1",
        actor_role=VetoActorRole.ASSIGNED_AGENT,
        repository=repository,
        policy=PreflightVetoPolicy(),
        now=NOW,
    )

    assert missing_result.reasons == (PreflightDigestReasonCode.MISSING_REQUIRED_DATA,)
    assert uncertain_result.reasons == (PreflightDigestReasonCode.DIGEST_STATE_UNCERTAIN,)


def test_persisted_digest_state_converts_to_campaign_start_context() -> None:
    vetoed_lead_id = uuid4()
    non_vetoed_candidate = _start_candidate(source=EnrollmentSource.DORMANT_SELECTOR)
    vetoed_candidate = _start_candidate(
        lead_id=vetoed_lead_id,
        source=EnrollmentSource.DORMANT_SELECTOR,
    )
    digest = _issued_digest(
        lead_id=vetoed_lead_id,
        digest_sent_at=NOW - timedelta(hours=30),
        veto_window_expires_at=NOW - timedelta(hours=6),
        vetoes=(
            PreflightVetoRecord(
                lead_id=vetoed_lead_id,
                actor_id="agent-1",
                recorded_at=NOW - timedelta(hours=29),
                idempotency_key="veto-key",
            ),
        ),
    )

    context = campaign_start_context_from_digest(
        campaign_status=CampaignStatus.ACTIVE,
        digest=digest,
    )
    decision = evaluate_campaign_start_batch(
        [vetoed_candidate, non_vetoed_candidate],
        _start_policy(),
        context,
        NOW,
    )

    assert context.digest_sent_at == NOW - timedelta(hours=30)
    assert context.vetoed_lead_ids == frozenset({vetoed_lead_id})
    assert [item.lead_id for item in decision.selected] == [non_vetoed_candidate.lead_id]
    assert decision.held_back[0].reasons == (StartQueueReasonCode.AGENT_VETOED,)


def test_missing_or_uncertain_digest_converts_to_fail_safe_context() -> None:
    uncertain_digest = _issued_digest(status=PreflightDigestIssueStatus.UNCERTAIN)

    missing_context = campaign_start_context_from_digest(
        campaign_status=CampaignStatus.ACTIVE,
        digest=None,
    )
    uncertain_context = campaign_start_context_from_digest(
        campaign_status=CampaignStatus.ACTIVE,
        digest=uncertain_digest,
    )

    assert missing_context.digest_sent_at is None
    assert missing_context.vetoed_lead_ids == frozenset()
    assert uncertain_context.digest_sent_at is None
    assert uncertain_context.vetoed_lead_ids == frozenset()
