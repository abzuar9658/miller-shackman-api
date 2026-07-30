"""Deterministic future-timing detection for lead conversation context.

This module extracts explicit future timeline statements from CRM conversation
events (e.g. "January 2027") for bounded supporting evidence and validation.
It must not replace the structured LLM classification used for paused-search
routing decisions.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from re import IGNORECASE, compile

from app.domain.conversations import CrmConversationEvent

FUTURE_TIMING_ARTIFACT_SOURCE = "deterministic_future_timing"

_MONTH_NAME = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)

_MONTH_YEAR_PATTERN = compile(
    rf"\b(?P<month>{_MONTH_NAME})[.,]?\s+(?:of\s+)?(?P<year>\d{{4}})\b",
    IGNORECASE,
)
_YEAR_MONTH_PATTERN = compile(
    rf"\b(?P<year>\d{{4}})\s+(?:of\s+)?(?P<month>{_MONTH_NAME})\b",
    IGNORECASE,
)

_MONTH_NAME_TO_NUMBER = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_MONTH_CODE_TO_LABEL = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}

_MAX_EVIDENCE_LENGTH = 200


@dataclass(frozen=True)
class FutureTimingDetection:
    detected: bool
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    evidence: str | None = None


def detect_future_timing_from_crm_events(
    *,
    crm_events: tuple[CrmConversationEvent, ...],
    now: datetime,
) -> FutureTimingDetection:
    """Scan CRM conversation events for explicit future month/year phrases.

    Returns a FutureTimingDetection with the first future date found, or
    ``detected=False`` when no future date is present.
    """
    for event in crm_events:
        content = event.content or ""
        detection = _detect_future_timing(content=content, now=now)
        if detection.detected:
            return detection
    return FutureTimingDetection(detected=False)


def _detect_future_timing(*, content: str, now: datetime) -> FutureTimingDetection:
    for pattern in (_MONTH_YEAR_PATTERN, _YEAR_MONTH_PATTERN):
        match = pattern.search(content)
        if match is None:
            continue
        month = _month_number(match.group("month"))
        year = int(match.group("year"))
        reengagement_not_before = datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)
        if reengagement_not_before <= now:
            continue
        month_code = match.group("month").strip(".,").lower()[:3]
        month_name = _MONTH_CODE_TO_LABEL.get(month_code, match.group("month").title())
        return FutureTimingDetection(
            detected=True,
            reengagement_not_before=reengagement_not_before,
            reengagement_window_label=f"{month_name} {year}",
            evidence=content[:_MAX_EVIDENCE_LENGTH].strip(),
        )
    return FutureTimingDetection(detected=False)


def _month_number(month_name: str) -> int:
    normalized = month_name.strip(".,").lower()[:3]
    return _MONTH_NAME_TO_NUMBER[normalized]
