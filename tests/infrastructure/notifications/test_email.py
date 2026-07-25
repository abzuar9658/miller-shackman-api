from uuid import UUID

from app.application.ports.notifications import HandoffNotification
from app.domain.conversations import HandoffReasonCode
from app.infrastructure.notifications.email import _render_handoff_body


def test_render_handoff_body_includes_crm_link_and_assigned_user() -> None:
    notification = HandoffNotification(
        workspace_id=UUID("50000000-0000-0000-0000-000000000001"),
        handoff_id=UUID("50000000-0000-0000-0000-000000000002"),
        lead_id=UUID("50000000-0000-0000-0000-000000000003"),
        recipient_id=str(UUID("50000000-0000-0000-0000-000000000004")),
        recipient_destination="assigned@example.com",
        assigned_user_name="Avery Demo Agent",
        lead_display_name="Jordan Buyer",
        lead_primary_email="lead@example.com",
        lead_primary_phone="+15555550123",
        crm_lead_id="crm-123",
        crm_lead_url="https://app.followupboss.com/2/people/crm-123",
        handoff_reason=HandoffReasonCode.HUMAN_REQUESTED,
        latest_inbound_text="Can an agent call me?",
        summary="Lead asked for a callback.",
        preferences={"timeline": "today"},
        recommended_next_action="Call the lead today.",
        idempotency_key="handoff:test:v1",
    )

    body = _render_handoff_body(notification)

    assert "Assigned user: Avery Demo Agent" in body
    assert "CRM lead ID: crm-123" in body
    assert "CRM lead link: https://app.followupboss.com/2/people/crm-123" in body
    assert "Recommended next action: Call the lead today." in body