import hashlib
import html
import json
import re
import unicodedata
from datetime import UTC, datetime

from app.domain.conversations.models import CrmConversationEventDirection

_HTML_TAG = re.compile(r"<[^>]+>")
_ACTIVITY_TYPE_ALIASES = {
    "sms": "text",
    "text": "text",
    "text message": "text",
    "text_message": "text",
}


def canonical_crm_event_identity(
    *,
    activity_type: str,
    occurred_at: datetime,
    content: str | None,
    direction: CrmConversationEventDirection | str | None,
) -> str:
    """Return a source-independent identity for one immutable CRM timeline event."""
    normalized_direction = (
        direction.value if isinstance(direction, CrmConversationEventDirection) else direction
    )
    source = json.dumps(
        {
            "activity_type": _normalize_activity_type(activity_type),
            "content": _normalize_content(content),
            "direction": (normalized_direction or "").strip().lower(),
            "occurred_at": occurred_at.astimezone(UTC).replace(microsecond=0).isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _normalize_activity_type(value: str) -> str:
    normalized = " ".join(value.strip().lower().replace("-", " ").split())
    return _ACTIVITY_TYPE_ALIASES.get(normalized, normalized)


def _normalize_content(value: str | None) -> str:
    if value is None:
        return ""
    without_tags = _HTML_TAG.sub(" ", html.unescape(value))
    return " ".join(unicodedata.normalize("NFKC", without_tags).split())