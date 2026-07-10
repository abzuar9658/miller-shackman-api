from app.application.ports.messaging import EmailMessage, EmailProvider
from app.application.ports.notifications import (
    HandoffNotification,
    NotificationProvider,
    NotificationSendResult,
    PreflightDigestNotification,
)


class EmailNotificationProvider(NotificationProvider):
    def __init__(self, email_provider: EmailProvider) -> None:
        self._email_provider = email_provider

    async def send_preflight_digest(
        self,
        notification: PreflightDigestNotification,
    ) -> NotificationSendResult:
        provider_reference = await self._email_provider.send(
            EmailMessage(
                to_email=notification.recipient_destination,
                subject=f"Preflight digest for campaign {notification.campaign_id}",
                body=_render_preflight_digest_body(notification),
                idempotency_key=notification.idempotency_key,
            ),
        )
        return NotificationSendResult(accepted=True, provider_reference=provider_reference)

    async def send_handoff_notification(
        self,
        notification: HandoffNotification,
    ) -> NotificationSendResult:
        provider_reference = await self._email_provider.send(
            EmailMessage(
                to_email=notification.recipient_destination,
                subject=f"Lead handoff required: {notification.lead_display_name}",
                body=_render_handoff_body(notification),
                idempotency_key=notification.idempotency_key,
            ),
        )
        return NotificationSendResult(accepted=True, provider_reference=provider_reference)


def _render_preflight_digest_body(notification: PreflightDigestNotification) -> str:
    lead_lines = "\n".join(f"- {lead.display_name}" for lead in notification.leads)
    return (
        f"Campaign {notification.campaign_id} has a preflight digest.\n"
        f"Batch: {notification.batch_id}\n"
        f"Veto window expires at: {notification.veto_window_expires_at.isoformat()}\n\n"
        f"Leads:\n{lead_lines}"
    )


def _render_handoff_body(notification: HandoffNotification) -> str:
    preference_lines = (
        "\n".join(f"- {key}: {value}" for key, value in sorted(notification.preferences.items()))
        or "- none extracted"
    )
    lead_contacts = []
    if notification.lead_primary_email:
        lead_contacts.append(f"email: {notification.lead_primary_email}")
    if notification.lead_primary_phone:
        lead_contacts.append(f"phone: {notification.lead_primary_phone}")
    contacts_text = ", ".join(lead_contacts) if lead_contacts else "no direct contact found"
    assigned_agent_line = notification.assigned_agent_name or notification.recipient_id
    return (
        f"Lead handoff required for {notification.lead_display_name}.\n"
        f"Assigned agent: {assigned_agent_line}\n"
        f"Contact details: {contacts_text}\n"
        f"Reason: {notification.handoff_reason.value}\n"
        f"Latest inbound: {notification.latest_inbound_text}\n\n"
        f"Conversation summary:\n{notification.summary}\n\n"
        f"Extracted preferences:\n{preference_lines}\n\n"
        f"Recommended next action: {notification.recommended_next_action}"
    )
