from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from app.application.ports import repositories as ports
from app.application.ports.crm import CRMClient
from app.application.ports.crm_webhook import FollowUpBossWebhookEventBundle
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.use_cases.process_contact_suppression_event import (
    apply_contact_suppression_to_lead,
)
from app.domain.compliance.contactability import (
    ContactabilityReasonCode,
    ContactChannel,
    ContactPermissionStatus,
    ContactSuppressionKind,
    SuppressionType,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.crm_sync import ExternalEventStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.crm.follow_up_boss.webhook_event_handler import (
    FollowUpBossWebhookEventHandlerImpl,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeExternalEventRepository,
)
from tests.interfaces.api.v1.test_webhooks import _FakeCRMClientForWebhook

NOW = datetime(2026, 9, 9, 14, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000001601")
LEAD_ID = UUID("00000000-0000-0000-0000-000000001602")
CRM_LEAD_ID = "synthetic-refresh-16a"
RESOURCE_URI = "https://api.followupboss.com/v1/people?id=synthetic-refresh-16a"


def _bundle(
    repository: FakeLeadRepository,
    crm_client: _FakeCRMClientForWebhook,
    events: FakeExternalEventRepository,
) -> FollowUpBossWebhookEventBundle:
    return FollowUpBossWebhookEventBundle(
        lead_repository=cast(ports.LeadRepository, repository),
        external_event_repository=cast(ports.ExternalEventRepository, events),
        lead_workflow_repository=cast(ports.LeadWorkflowRepository, FakeLeadWorkflowRepository()),
        workflow_transition_repository=cast(
            ports.WorkflowTransitionRepository, FakeWorkflowTransitionRepository(),
        ),
        temporal_signal_outbox_repository=cast(
            ports.TemporalSignalOutboxRepository, FakeTemporalSignalOutboxRepository(),
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(workspace_id=WORKSPACE_ID),
        ),
        campaign_execution_repository=FakeCampaignExecutionRepository(None),
        campaign_enrollment_repository=cast(
            ports.CampaignEnrollmentRepository, FakeCampaignEnrollmentRepository(),
        ),
        lead_classification_artifact_repository=FakeLeadClassificationArtifactRepository(),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        crm_client=cast(CRMClient, crm_client),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        llm_client=FakeLLMClient(),
        event_bus=None,
        workspace_operational_control_repository=None,
    )


@pytest.mark.parametrize(
    ("crm_fields", "expected_permission", "expected_dnc", "expected_crm_evidence"),
    [
        pytest.param({}, ContactPermissionStatus.UNKNOWN, None, {}, id="missing"),
        pytest.param(
            {
                "smsPermissionStatus": "unknown",
                "emailPermissionStatus": "unknown",
                "smsOptedOut": None,
                "emailUnsubscribed": None,
                "doNotContact": None,
            },
            ContactPermissionStatus.UNKNOWN,
            None,
            {},
            id="unknown-null",
        ),
        pytest.param(
            {"smsOptedOut": False, "emailUnsubscribed": False, "doNotContact": False},
            ContactPermissionStatus.UNKNOWN,
            False,
            {"do_not_contact_source": "follow_up_boss.customFields"},
            id="explicit-false",
        ),
        pytest.param(
            {
                "customFields": {
                    "smsPermissionStatus": "allowed",
                    "emailPermissionStatus": "subscribed",
                    "smsOptedOut": False,
                    "emailUnsubscribed": False,
                    "doNotContact": False,
                },
            },
            ContactPermissionStatus.CONFIRMED,
            False,
            {
                "sms_permission_status_source": "follow_up_boss.customFields",
                "email_permission_status_source": "follow_up_boss.customFields",
                "do_not_contact_source": "follow_up_boss.customFields",
            },
            id="permissive-custom-fields",
        ),
    ],
)
@pytest.mark.parametrize(
    (
        "suppression_kind", "source_provider", "expected_flags", "expected_suppressions",
        "expected_platform_evidence", "expected_channel_reasons",
    ),
    [
        pytest.param(
            ContactSuppressionKind.SMS_OPT_OUT,
            "twilio",
            (True, False, False),
            frozenset({SuppressionType.SMS_OPT_OUT}),
            {
                "sms_opt_out_source_provider": "twilio",
                "sms_opt_out_source_event_id": "synthetic-sms_opt_out-people-16a",
                "sms_opt_out_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            ((ContactabilityReasonCode.SMS_OPTED_OUT,), ()),
            id="sms",
        ),
        pytest.param(
            ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
            "follow_up_boss",
            (False, True, False),
            frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
            {
                "email_unsubscribed_source_provider": "follow_up_boss",
                "email_unsubscribed_source_event_id": "synthetic-email_unsubscribed-people-16a",
                "email_unsubscribed_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            ((), (ContactabilityReasonCode.EMAIL_UNSUBSCRIBED,)),
            id="email",
        ),
        pytest.param(
            ContactSuppressionKind.DO_NOT_CONTACT,
            "follow_up_boss",
            (False, False, True),
            frozenset(),
            {
                "do_not_contact_source_provider": "follow_up_boss",
                "do_not_contact_source_event_id": "synthetic-do_not_contact-people-16a",
                "do_not_contact_occurred_at": "2026-09-08T14:00:00+00:00",
            },
            (
                (ContactabilityReasonCode.DO_NOT_CONTACT,),
                (ContactabilityReasonCode.DO_NOT_CONTACT,),
            ),
            id="dnc",
        ),
        pytest.param(None, None, (False, False, False), frozenset(), {}, ((), ()), id="clean"),
    ],
)
async def test_people_refresh_keeps_recorded_opt_out_through_real_mapping(
    crm_fields: dict[str, object],
    expected_permission: ContactPermissionStatus,
    expected_dnc: bool | None,
    expected_crm_evidence: dict[str, str],
    suppression_kind: ContactSuppressionKind | None,
    source_provider: str | None,
    expected_flags: tuple[bool, bool, bool],
    expected_suppressions: frozenset[SuppressionType],
    expected_platform_evidence: dict[str, str],
    expected_channel_reasons: tuple[
        tuple[ContactabilityReasonCode, ...], tuple[ContactabilityReasonCode, ...],
    ],
) -> None:
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=CRM_LEAD_ID,
        facts_derived_at=datetime(2026, 9, 8, 10, tzinfo=UTC),
        source_payload_version="test:v1",
        lead_stage="cold",
        primary_email="original@example.test",
        primary_phone="+15555550160",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        do_not_contact=False,
    )
    repository = FakeLeadRepository(lead)
    if suppression_kind is not None:
        assert source_provider is not None
        await apply_contact_suppression_to_lead(
            lead=lead,
            suppression_kind=suppression_kind,
            source_provider=source_provider,
            source_event_id=f"synthetic-{suppression_kind.value}-people-16a",
            occurred_at=datetime(2026, 9, 8, 14, tzinfo=UTC),
            lead_repository=cast(ports.LeadRepository, repository),
        )
    person = {
        "id": CRM_LEAD_ID,
        "stage": "cold",
        "firstName": "Fresh",
        "lastName": "Contact",
        "emails": [{"value": "updated@example.test"}],
        "phones": [{"value": "+15555550160"}],
        "updated": "2026-09-09T14:00:00Z",
        **crm_fields,
    }
    crm_client = _FakeCRMClientForWebhook({"people": [person]})
    events = FakeExternalEventRepository()
    bundle = _bundle(repository, crm_client, events)
    handler = FollowUpBossWebhookEventHandlerImpl(bundle)

    result = await handler.handle(
        WORKSPACE_ID,
        {
            "eventId": "synthetic-people-refresh-16a",
            "event": "peopleUpdated",
            "eventCreated": "2026-09-09T14:00:00Z",
            "resourceIds": [CRM_LEAD_ID],
            "uri": RESOURCE_URI,
        },
        NOW,
    )

    # No matching campaign or human-activity change: the ordinary contact update
    # still refreshes the lead but must not start a workflow to make this pass.
    assert result.status == "ignored"
    assert result.processed_count == 0
    assert result.ignored_count == 1
    assert result.reasons == ["no_actionable_resources"]
    assert crm_client.requested_uris == [RESOURCE_URI]
    saved = await repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert saved is not None
    assert saved.sms_opted_out is expected_flags[0]
    assert saved.email_unsubscribed is expected_flags[1]
    assert saved.do_not_contact is (True if expected_flags[2] else expected_dnc)
    assert saved.suppression_types == expected_suppressions
    assert saved.permission_evidence == {**expected_crm_evidence, **expected_platform_evidence}
    assert saved.sms_permission_status is expected_permission
    assert saved.email_permission_status is expected_permission
    assert saved.primary_email == "updated@example.test"
    assert saved.mapped_custom_fields["display_name"] == "Fresh Contact"
    assert saved.source_updated_at == NOW
    assert saved.facts_derived_at == NOW
    for channel, reasons in zip(
        (ContactChannel.SMS, ContactChannel.EMAIL), expected_channel_reasons, strict=True,
    ):
        decision = evaluate_contactability(contactability_facts_from_canonical_lead(saved), channel)
        assert decision.reasons == reasons
        assert decision.allowed is (not reasons)
    envelope = await events.get_by_provider_event_id(
        WORKSPACE_ID, "follow_up_boss", "synthetic-people-refresh-16a",
    )
    assert envelope is not None
    assert envelope.status is ExternalEventStatus.IGNORED
    assert cast(FakeTemporalWorkflowStarter, bundle.temporal_workflow_starter).calls == []
    assert cast(FakeLLMClient, bundle.llm_client).requests == []