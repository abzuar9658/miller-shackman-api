from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from app.application.ports.repositories import LeadRepository
from app.application.services.crm_lead_refresh import (
    CrmLeadRefreshStatus,
    refresh_lead_from_crm,
)
from app.application.use_cases.process_contact_suppression_event import (
    apply_contact_suppression_to_lead,
)
from app.domain.compliance.contactability import (
    ContactPermissionStatus,
    ContactSuppressionKind,
    SuppressionType,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from tests.application.use_cases._crm_history_import_fakes import (
    FakeCanonicalLeadRefreshSource,
    FakeLeadRepository,
)


class RecordingLeadRepository(FakeLeadRepository):
    def __init__(self, leads: tuple[CanonicalLeadRecord, ...]) -> None:
        super().__init__(leads)
        self.saved: list[CanonicalLeadRecord] = []

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.saved.append(record)
        return await super().upsert(record)


@pytest.mark.parametrize(
    "suppression", [SuppressionType.SMS_OPT_OUT, SuppressionType.EMAIL_UNSUBSCRIBED],
)
async def test_refresh_keeps_legacy_type_only_restriction_without_inventing_evidence(
    suppression: SuppressionType,
) -> None:
    fresh = _lead()
    existing = replace(fresh, suppression_types=frozenset({suppression}))
    repository = FakeLeadRepository((existing,))
    await refresh_lead_from_crm(
        workspace_id=existing.workspace_id, crm_provider=existing.crm_provider,
        crm_lead_id=existing.crm_lead_id,
        lead_refresh_source=FakeCanonicalLeadRefreshSource({existing.crm_lead_id: fresh}),
        lead_repository=cast(LeadRepository, repository), now=fresh.facts_derived_at,
    )
    saved = await repository.get_by_id(existing.workspace_id, existing.lead_id)
    assert saved is not None
    assert saved.suppression_types == frozenset({suppression})
    assert saved.sms_opted_out is (suppression is SuppressionType.SMS_OPT_OUT)
    assert saved.email_unsubscribed is (suppression is SuppressionType.EMAIL_UNSUBSCRIBED)
    assert saved.permission_evidence == {}


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=UUID("00000000-0000-0000-0000-000000001601"),
        lead_id=UUID("00000000-0000-0000-0000-000000001602"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="synthetic-refresh-16a",
        facts_derived_at=datetime(2026, 9, 8, 10, tzinfo=UTC),
        source_payload_version="test:v1",
        lead_stage="cold",
        primary_email="original@example.test",
        primary_phone="+15555550160",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        do_not_contact=False,
    )


@pytest.fixture
async def recorded_restrictions() -> tuple[CanonicalLeadRecord, RecordingLeadRepository]:
    lead = _lead()
    repository = RecordingLeadRepository((lead,))
    for kind, provider, event_id, occurred_at in (
        (
            ContactSuppressionKind.SMS_OPT_OUT,
            "twilio",
            "synthetic-sms-stop-16a",
            datetime(2026, 9, 8, 12, tzinfo=UTC),
        ),
        (
            ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
            "follow_up_boss",
            "synthetic-email-unsubscribe-16a",
            datetime(2026, 9, 8, 13, tzinfo=UTC),
        ),
        (
            ContactSuppressionKind.DO_NOT_CONTACT,
            "follow_up_boss",
            "synthetic-do-not-contact-16a",
            datetime(2026, 9, 8, 14, tzinfo=UTC),
        ),
    ):
        lead = await apply_contact_suppression_to_lead(
            lead=lead,
            suppression_kind=kind,
            source_provider=provider,
            source_event_id=event_id,
            occurred_at=occurred_at,
            lead_repository=cast(LeadRepository, repository),
        )
    repository.saved.clear()
    return lead, repository


def _assert_recorded_restrictions(lead: CanonicalLeadRecord) -> None:
    assert lead.sms_opted_out is True
    assert lead.email_unsubscribed is True
    assert lead.do_not_contact is True
    assert lead.suppression_types == frozenset(
        {SuppressionType.SMS_OPT_OUT, SuppressionType.EMAIL_UNSUBSCRIBED}
    )
    assert lead.permission_evidence == {
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "synthetic-sms-stop-16a",
        "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00",
        "email_unsubscribed_source_provider": "follow_up_boss",
        "email_unsubscribed_source_event_id": "synthetic-email-unsubscribe-16a",
        "email_unsubscribed_occurred_at": "2026-09-08T13:00:00+00:00",
        "do_not_contact_source_provider": "follow_up_boss",
        "do_not_contact_source_event_id": "synthetic-do-not-contact-16a",
        "do_not_contact_occurred_at": "2026-09-08T14:00:00+00:00",
    }


@pytest.mark.parametrize(
    ("crm_permission_status", "crm_do_not_contact"),
    [
        pytest.param(ContactPermissionStatus.CONFIRMED, False, id="permissive"),
        pytest.param(
            ContactPermissionStatus.CONFIRMED, None, id="permissive-missing-dnc"
        ),
        pytest.param(ContactPermissionStatus.UNKNOWN, None, id="unknown-missing-dnc"),
        pytest.param(ContactPermissionStatus.UNKNOWN, False, id="explicit-false"),
    ],
)
@pytest.mark.parametrize(
    (
        "suppression_kind", "source_provider", "source_event_id", "occurred_at",
        "expected_flags", "expected_suppressions", "expected_evidence",
    ),
    [
        pytest.param(
            ContactSuppressionKind.SMS_OPT_OUT,
            "twilio",
            "synthetic-sms-stop-16a",
            datetime(2026, 9, 8, 12, tzinfo=UTC),
            (True, False, False),
            frozenset({SuppressionType.SMS_OPT_OUT}),
            {
                "sms_opt_out_source_provider": "twilio",
                "sms_opt_out_source_event_id": "synthetic-sms-stop-16a",
                "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00",
            },
            id="sms",
        ),
        pytest.param(
            ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
            "follow_up_boss",
            "synthetic-email-unsubscribe-16a",
            datetime(2026, 9, 8, 13, tzinfo=UTC),
            (False, True, False),
            frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
            {
                "email_unsubscribed_source_provider": "follow_up_boss",
                "email_unsubscribed_source_event_id": "synthetic-email-unsubscribe-16a",
                "email_unsubscribed_occurred_at": "2026-09-08T13:00:00+00:00",
            },
            id="email",
        ),
        pytest.param(
            ContactSuppressionKind.DO_NOT_CONTACT,
            "follow_up_boss",
            "synthetic-do-not-contact-16a",
            datetime(2026, 9, 8, 14, tzinfo=UTC),
            (False, False, True),
            frozenset(),
            {
                "do_not_contact_source_provider": "follow_up_boss",
                "do_not_contact_source_event_id": "synthetic-do-not-contact-16a",
                "do_not_contact_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            id="dnc",
        ),
    ],
)
async def test_on_demand_refresh_keeps_recorded_opt_out_and_evidence(
    crm_permission_status: ContactPermissionStatus,
    crm_do_not_contact: bool | None,
    suppression_kind: ContactSuppressionKind,
    source_provider: str,
    source_event_id: str,
    occurred_at: datetime,
    expected_flags: tuple[bool, bool, bool],
    expected_suppressions: frozenset[SuppressionType],
    expected_evidence: dict[str, str],
) -> None:
    now = datetime(2026, 9, 9, 14, tzinfo=UTC)
    lead = _lead()
    repository = FakeLeadRepository((lead,))
    await apply_contact_suppression_to_lead(
        lead=lead,
        suppression_kind=suppression_kind,
        source_provider=source_provider,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        lead_repository=cast(LeadRepository, repository),
    )
    source = FakeCanonicalLeadRefreshSource(
        {
            lead.crm_lead_id: replace(
                lead,
                facts_derived_at=now,
                source_updated_at=now,
                lead_stage="nurture",
                tags=("updated-tag",),
                primary_email="updated@example.test",
                primary_phone="+15555550161",
                sms_permission_status=crm_permission_status,
                email_permission_status=crm_permission_status,
                do_not_contact=crm_do_not_contact,
            ),
        }
    )

    result = await refresh_lead_from_crm(
        workspace_id=lead.workspace_id,
        crm_provider=lead.crm_provider,
        crm_lead_id=lead.crm_lead_id,
        lead_refresh_source=source,
        lead_repository=cast(LeadRepository, repository),
        now=now,
    )

    saved = await repository.get_by_id(lead.workspace_id, lead.lead_id)
    assert result.status is CrmLeadRefreshStatus.REFRESHED
    assert saved is not None
    assert result.lead == saved
    assert saved.sms_opted_out is expected_flags[0]
    assert saved.email_unsubscribed is expected_flags[1]
    assert saved.do_not_contact is (True if expected_flags[2] else crm_do_not_contact)
    assert saved.suppression_types == expected_suppressions
    assert saved.permission_evidence == expected_evidence
    assert saved.sms_permission_status is crm_permission_status
    assert saved.email_permission_status is crm_permission_status
    assert saved.lead_stage == "nurture"
    assert saved.tags == ("updated-tag",)
    assert saved.primary_email == "updated@example.test"
    assert saved.primary_phone == "+15555550161"
    assert saved.facts_derived_at == now
    assert saved.source_updated_at == now
    assert source.calls == [(lead.workspace_id, lead.crm_lead_id, ())]


async def test_on_demand_refresh_adds_crm_restrictions_without_replacing_platform_evidence(
) -> None:
    now = datetime(2026, 9, 9, 14, tzinfo=UTC)
    lead = _lead()
    repository = FakeLeadRepository((lead,))
    await apply_contact_suppression_to_lead(
        lead=lead,
        suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
        source_provider="twilio",
        source_event_id="synthetic-sms-stop-16a",
        occurred_at=datetime(2026, 9, 8, 12, tzinfo=UTC),
        lead_repository=cast(LeadRepository, repository),
    )
    source = FakeCanonicalLeadRefreshSource(
        {
            lead.crm_lead_id: replace(
                lead,
                facts_derived_at=now,
                lead_stage="nurture",
                sms_permission_status=ContactPermissionStatus.CONFIRMED,
                email_permission_status=ContactPermissionStatus.DENIED,
                email_unsubscribed=True,
                do_not_contact=True,
                suppression_types=frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
                permission_evidence={
                    "sms_permission_status_source": "follow_up_boss.customFields",
                    "email_permission_status_source": "follow_up_boss.customFields",
                    "email_unsubscribed_source": "follow_up_boss.customFields",
                    "do_not_contact_source": "follow_up_boss.customFields",
                    "sms_opt_out_source_provider": "follow_up_boss",
                    "sms_opt_out_source_event_id": "synthetic-conflicting-crm-evidence-16a",
                    "sms_opt_out_occurred_at": "2026-09-09T12:00:00+00:00",
                },
            ),
        }
    )

    result = await refresh_lead_from_crm(
        workspace_id=lead.workspace_id,
        crm_provider=lead.crm_provider,
        crm_lead_id=lead.crm_lead_id,
        lead_refresh_source=source,
        lead_repository=cast(LeadRepository, repository),
        now=now,
    )

    saved = await repository.get_by_id(lead.workspace_id, lead.lead_id)
    assert result.status is CrmLeadRefreshStatus.REFRESHED
    assert saved is not None
    assert result.lead == saved
    assert saved.sms_opted_out is True
    assert saved.email_unsubscribed is True
    assert saved.do_not_contact is True
    assert saved.suppression_types == frozenset(
        {SuppressionType.SMS_OPT_OUT, SuppressionType.EMAIL_UNSUBSCRIBED}
    )
    assert saved.permission_evidence == {
        "sms_opt_out_source_provider": "twilio",
        "sms_opt_out_source_event_id": "synthetic-sms-stop-16a",
        "sms_opt_out_occurred_at": "2026-09-08T12:00:00+00:00",
        "sms_permission_status_source": "follow_up_boss.customFields",
        "email_permission_status_source": "follow_up_boss.customFields",
        "email_unsubscribed_source": "follow_up_boss.customFields",
        "do_not_contact_source": "follow_up_boss.customFields",
    }
    assert saved.sms_permission_status is ContactPermissionStatus.CONFIRMED
    assert saved.email_permission_status is ContactPermissionStatus.DENIED
    assert saved.lead_stage == "nurture"
    assert saved.facts_derived_at == now


@pytest.mark.parametrize(
    "refresh_order",
    [
        pytest.param(("older", "newer", "older", "newer"), id="old-new-old-new"),
        pytest.param(("newer", "older", "newer", "older"), id="new-old-new-old"),
    ],
)
async def test_repeated_reordered_on_demand_refresh_keeps_recorded_restrictions(
    recorded_restrictions: tuple[CanonicalLeadRecord, RecordingLeadRepository],
    refresh_order: tuple[str, ...],
) -> None:
    lead, repository = recorded_restrictions
    snapshots = {
        "older": replace(
            _lead(),
            source_updated_at=datetime(2026, 9, 8, 10, tzinfo=UTC),
            do_not_contact=None,
        ),
        "newer": replace(
            _lead(),
            facts_derived_at=datetime(2026, 9, 8, 11, tzinfo=UTC),
            source_updated_at=datetime(2026, 9, 8, 11, tzinfo=UTC),
            sms_permission_status=ContactPermissionStatus.CONFIRMED,
            email_permission_status=ContactPermissionStatus.CONFIRMED,
            do_not_contact=False,
        ),
    }
    source = FakeCanonicalLeadRefreshSource()

    for snapshot_name in refresh_order:
        source.snapshots[lead.crm_lead_id] = snapshots[snapshot_name]
        result = await refresh_lead_from_crm(
            workspace_id=lead.workspace_id,
            crm_provider=lead.crm_provider,
            crm_lead_id=lead.crm_lead_id,
            lead_refresh_source=source,
            lead_repository=cast(LeadRepository, repository),
            now=datetime(2026, 9, 9, 14, tzinfo=UTC),
        )

        saved = await repository.get_by_id(lead.workspace_id, lead.lead_id)
        assert result.status is CrmLeadRefreshStatus.REFRESHED
        assert saved is not None
        assert result.lead == saved
        _assert_recorded_restrictions(saved)

    for written in repository.saved:
        _assert_recorded_restrictions(written)
    assert source.calls == [(lead.workspace_id, lead.crm_lead_id, ())] * 4


@pytest.mark.parametrize(
    ("crm_error", "expected_status", "expected_failure_reason"),
    [
        pytest.param(None, CrmLeadRefreshStatus.LEAD_NOT_FOUND, None, id="missing"),
        pytest.param(
            RuntimeError("synthetic CRM unavailable"),
            CrmLeadRefreshStatus.FAILED,
            "synthetic CRM unavailable",
            id="error",
        ),
        pytest.param(
            TimeoutError("synthetic CRM timeout"),
            CrmLeadRefreshStatus.FAILED,
            "synthetic CRM timeout",
            id="timeout",
        ),
    ],
)
async def test_on_demand_refresh_failure_keeps_recorded_restrictions_without_upsert(
    recorded_restrictions: tuple[CanonicalLeadRecord, RecordingLeadRepository],
    crm_error: Exception | None,
    expected_status: CrmLeadRefreshStatus,
    expected_failure_reason: str | None,
) -> None:
    lead, repository = recorded_restrictions
    source = FakeCanonicalLeadRefreshSource(error=crm_error)

    result = await refresh_lead_from_crm(
        workspace_id=lead.workspace_id,
        crm_provider=lead.crm_provider,
        crm_lead_id=lead.crm_lead_id,
        lead_refresh_source=source,
        lead_repository=cast(LeadRepository, repository),
        now=datetime(2026, 9, 9, 14, tzinfo=UTC),
    )

    saved = await repository.get_by_id(lead.workspace_id, lead.lead_id)
    assert result.status is expected_status
    assert result.failure_reason == expected_failure_reason
    assert saved is not None
    assert saved == lead
    assert result.lead == saved
    _assert_recorded_restrictions(saved)
    assert repository.saved == []
    assert source.calls == [(lead.workspace_id, lead.crm_lead_id, ())]