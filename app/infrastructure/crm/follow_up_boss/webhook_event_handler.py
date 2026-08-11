from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from app.application.ports.crm import CRMResourceFetchError
from app.application.ports.crm_webhook import (
    FollowUpBossWebhookEventBundle,
    FollowUpBossWebhookEventHandler,
    FollowUpBossWebhookEventResult,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventFailureKind, ExternalEventStatus
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
_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = timedelta(seconds=1)
_RETRY_MAX_DELAY = timedelta(seconds=60)
_PEOPLE_EVENTS = frozenset(
    {
        "peopleUpdated",
        "peopleCreated",
        "peopleDeleted",
        "peopleStageUpdated",
        "peopleTagsCreated",
    }
)


@dataclass
class FollowUpBossWebhookEventHandlerImpl(FollowUpBossWebhookEventHandler):
    bundle: FollowUpBossWebhookEventBundle

    async def handle(
        self,
        workspace_id: UUID,
        payload: Mapping[str, Any],
        now: datetime,
        replay: bool = False,
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
        if existing is not None and not (
            replay and existing.status is ExternalEventStatus.RETRYABLE_FAILURE
        ):
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

        base_event = existing or envelope_event(
            workspace_id,
            event_id,
            event_type,
            occurred_at,
            payload,
            now,
            ExternalEventStatus.PENDING,
        )

        try:
            processed, ignored = await self._dispatch(
                workspace_id=workspace_id,
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                uri=uri,
                now=now,
            )
        except Exception as exc:
            return await self._record_fetch_failure(
                event=base_event,
                now=now,
                error=exc,
                event_type=event_type,
            )

        if event_type not in _PEOPLE_EVENTS | {
            "notesCreated",
            "textMessagesCreated",
            "callsCreated",
            "emEventsUnsubscribed",
        }:
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
        saved = await self.bundle.external_event_repository.save(
            replace(
                base_event,
                status=envelope_status,
                processed_at=now,
                failure_reason=(None if processed > 0 else "no_actionable_resources"),
                failure_kind=None,
                next_retry_at=None,
                updated_at=now,
            )
        )
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

    async def _dispatch(
        self,
        *,
        workspace_id: UUID,
        event_id: str,
        event_type: str,
        occurred_at: datetime,
        uri: str,
        now: datetime,
    ) -> tuple[int, int]:
        if event_type in _PEOPLE_EVENTS:
            return await handle_people_event(
                workspace_id, event_id, event_type, occurred_at, uri, self.bundle, now
            )
        if event_type == "notesCreated":
            return await handle_notes_created(workspace_id, event_id, occurred_at, uri, self.bundle)
        if event_type == "textMessagesCreated":
            return await handle_text_messages_created(
                workspace_id, event_id, occurred_at, uri, self.bundle
            )
        if event_type == "callsCreated":
            return await handle_calls_created(workspace_id, event_id, occurred_at, uri, self.bundle)
        if event_type == "emEventsUnsubscribed":
            return await handle_em_events_unsubscribed(
                workspace_id, event_id, occurred_at, uri, self.bundle
            )
        return 0, 1

    async def _record_fetch_failure(
        self,
        *,
        event: ExternalEvent,
        now: datetime,
        error: Exception,
        event_type: str,
    ) -> FollowUpBossWebhookEventResult:
        if isinstance(error, CRMResourceFetchError):
            failure_kind = ExternalEventFailureKind(error.kind.value)
            failure_reason = error.reason
        else:
            failure_kind = ExternalEventFailureKind.UNKNOWN
            failure_reason = "crm_webhook_processing_unknown_failure"

        is_permanent = failure_kind is ExternalEventFailureKind.PERMANENT
        exhausted = event.attempt_count >= _MAX_ATTEMPTS and not is_permanent
        status = (
            ExternalEventStatus.PERMANENT_FAILURE
            if is_permanent
            else ExternalEventStatus.EXHAUSTED
            if exhausted
            else ExternalEventStatus.RETRYABLE_FAILURE
        )
        next_retry_at = None
        if status is ExternalEventStatus.RETRYABLE_FAILURE:
            delay = min(
                _RETRY_BASE_DELAY * (2 ** max(event.attempt_count - 1, 0)),
                _RETRY_MAX_DELAY,
            )
            next_retry_at = now + delay
        saved = await self.bundle.external_event_repository.save(
            replace(
                event,
                status=status,
                processed_at=now if status is not ExternalEventStatus.RETRYABLE_FAILURE else None,
                failure_reason=failure_reason,
                failure_kind=failure_kind,
                next_retry_at=next_retry_at,
                updated_at=now,
            )
        )
        logger.warning(
            "follow_up_boss_webhook_fetch_failed",
            workspace_id=str(event.workspace_id),
            provider_event_id=event.provider_event_id,
            event_type=event_type,
            status=status.value,
            failure_kind=failure_kind.value,
            attempt_count=event.attempt_count,
            next_retry_at=next_retry_at.isoformat() if next_retry_at else None,
        )
        return FollowUpBossWebhookEventResult(
            status=status.value,
            external_event_id=saved.external_event_id,
            event_type=event_type,
            reasons=[failure_reason],
        )
