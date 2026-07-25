from app.application.ports.messaging import EmailMessage, EmailProvider
from app.application.ports.notifications import (
    HandoffNotification,
    NotificationProvider,
    NotificationSendResult,
    PreflightDigestNotification,
    ReviewNotification,
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

    async def send_review_notification(
        self,
        notification: ReviewNotification,
    ) -> NotificationSendResult:
        provider_reference = await self._email_provider.send(
            EmailMessage(
                to_email=notification.recipient_destination,
                subject=f"Lead review required: {notification.lead_display_name}",
                body=_render_review_body(notification),
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
    assigned_user_line = notification.assigned_user_name or notification.recipient_id
    crm_lead_lines = [f"CRM lead ID: {notification.crm_lead_id}"]
    if notification.crm_lead_url:
        crm_lead_lines.append(f"CRM lead link: {notification.crm_lead_url}")
    crm_lead_text = "\n".join(crm_lead_lines)
    return (
        f"Lead handoff required for {notification.lead_display_name}.\n"
        f"Assigned user: {assigned_user_line}\n"
        f"Contact details: {contacts_text}\n"
        f"{crm_lead_text}\n"
        f"Reason: {notification.handoff_reason.value}\n"
        f"Latest inbound: {notification.latest_inbound_text}\n\n"
        f"Conversation summary:\n{notification.summary}\n\n"
        f"Extracted preferences:\n{preference_lines}\n\n"
        f"Recommended next action: {notification.recommended_next_action}"
    )


def _render_review_body(notification: ReviewNotification) -> str:
    lead_contacts = []
    if notification.lead_primary_email:
        lead_contacts.append(f"email: {notification.lead_primary_email}")
    if notification.lead_primary_phone:
        lead_contacts.append(f"phone: {notification.lead_primary_phone}")
    contacts_text = ", ".join(lead_contacts) if lead_contacts else "no direct contact found"
    recommended_action = (
        "Review the latest reply and resume AI outreach only if appropriate."
    )
    return (
        f"Lead review required for {notification.lead_display_name}.\n"
        f"Contact details: {contacts_text}\n"
        f"Channel: {notification.channel}\n"
        f"Reason: {notification.review_reason}\n"
        f"Latest inbound: {notification.latest_inbound_text}\n\n"
        f"Conversation summary:\n{notification.summary}\n\n"
        f"Recommended next action: {recommended_action}"
    )
