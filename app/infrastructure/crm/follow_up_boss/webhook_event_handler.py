from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from app.application.ports.crm_webhook import (
    FollowUpBossWebhookEventBundle,
    FollowUpBossWebhookEventHandler,
    FollowUpBossWebhookEventResult,
)
from app.domain.crm_sync import ExternalEventStatus
from app.infrastructure.crm.follow_up_boss.webhook_event_mappers import (
    handle_calls_created,
    handle_em_events_unsubscribed,
    handle_notes_created,
    handle_text_messages_created,
)
from app.infrastructure.crm.follow_up_boss.webhook_event_parsers import (
    envelope_event,
    parse_envelope,
)
from app.infrastructure.crm.follow_up_boss.webhook_event_people import (
    handle_people_event,
)

logger = structlog.get_logger(__name__)

_PROVIDER = "follow_up_boss"
_PEOPLE_EVENTS = frozenset({
    "peopleUpdated",
    "peopleCreated",
    "peopleDeleted",
    "peopleStageUpdated",
    "peopleTagsCreated",
})


@dataclass
class FollowUpBossWebhookEventHandlerImpl(FollowUpBossWebhookEventHandler):
    bundle: FollowUpBossWebhookEventBundle

    async def handle(
        self,
        workspace_id: UUID,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> FollowUpBossWebhookEventResult:
        parsed = parse_envelope(payload)
        if parsed is None:
            logger.warning(
                "follow_up_boss_webhook_rejected",
                workspace_id=str(workspace_id),
                reason="invalid_payload",
            )
            return FollowUpBossWebhookEventResult(status="rejected", reasons=["invalid_payload"])
        event_id, event_type, occurred_at, uri = parsed

        existing = await self.bundle.external_event_repository.get_by_provider_event_id(
            workspace_id, _PROVIDER, event_id
        )
        if existing is not None:
            logger.info(
                "follow_up_boss_webhook_duplicate",
                workspace_id=str(workspace_id),
                provider_event_id=event_id,
                event_type=event_type,
            )
            return FollowUpBossWebhookEventResult(
                status="duplicate",
                external_event_id=existing.external_event_id,
                event_type=event_type,
                duplicate_count=1,
                reasons=["duplicate_event"],
            )

        if event_type in _PEOPLE_EVENTS:
            processed, ignored = await handle_people_event(
                workspace_id, event_id, event_type, occurred_at, uri, self.bundle, now
            )
        elif event_type == "notesCreated":
            processed, ignored = await handle_notes_created(
                workspace_id, event_id, occurred_at, uri, self.bundle
            )
        elif event_type == "textMessagesCreated":
            processed, ignored = await handle_text_messages_created(
                workspace_id, event_id, occurred_at, uri, self.bundle
            )
        elif event_type == "callsCreated":
            processed, ignored = await handle_calls_created(
                workspace_id, event_id, occurred_at, uri, self.bundle
            )
        elif event_type == "emEventsUnsubscribed":
            processed, ignored = await handle_em_events_unsubscribed(
                workspace_id, event_id, occurred_at, uri, self.bundle
            )
        else:
            envelope = envelope_event(
                workspace_id,
                event_id,
                event_type,
                occurred_at,
                payload,
                now,
                ExternalEventStatus.IGNORED,
            )
            saved = await self.bundle.external_event_repository.save(envelope)
            logger.info(
                "follow_up_boss_webhook_ignored",
                workspace_id=str(workspace_id),
                provider_event_id=event_id,
                event_type=event_type,
                status="ignored",
                processed_count=0,
                ignored_count=1,
                reasons=["unsupported_event_type"],
            )
            return FollowUpBossWebhookEventResult(
                status="ignored",
                external_event_id=saved.external_event_id,
                event_type=event_type,
                ignored_count=1,
                reasons=["unsupported_event_type"],
            )

        envelope_status = (
            ExternalEventStatus.PROCESSED if processed > 0 else ExternalEventStatus.IGNORED
        )
        envelope = envelope_event(
            workspace_id, event_id, event_type, occurred_at, payload, now, envelope_status
        )
        saved = await self.bundle.external_event_repository.save(envelope)
        logger.info(
            "follow_up_boss_webhook_processed",
            workspace_id=str(workspace_id),
            provider_event_id=event_id,
            event_type=event_type,
            status="processed" if processed > 0 else "ignored",
            processed_count=processed,
            ignored_count=ignored,
            uri=uri,
            reasons=[] if processed > 0 else ["no_actionable_resources"],
        )
        return FollowUpBossWebhookEventResult(
            status="processed" if processed > 0 else "ignored",
            external_event_id=saved.external_event_id,
            event_type=event_type,
            processed_count=processed,
            ignored_count=ignored,
            reasons=[] if processed > 0 else ["no_actionable_resources"],
        )
