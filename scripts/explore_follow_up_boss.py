"""Read-only exploration of the Follow Up Boss API.

This script is intended for local development only. It makes only GET requests,
limits result sets, and redacts personally identifiable information before printing.

Usage:
    FUB_API_KEY=your_key uv run python scripts/explore_follow_up_boss.py \
        --output tmp/fub-exploration-report.txt
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO, cast

import httpx
import structlog

logger = structlog.get_logger(__name__)

FUB_BASE_URL = "https://api.followupboss.com/v1"
SAMPLE_LIMIT = 5
DEFAULT_OUTPUT = Path("tmp/fub-exploration-report.txt")

PHONE_LIKE_PATTERN = re.compile(r"^[+\d\s\-\(\)\.extEXT,]+$")
SENSITIVE_KEY_FRAGMENTS = (
    "apikey",
    "api_key",
    "token",
    "secret",
    "password",
    "hash",
    "signature",
)
FULL_REDACT_KEYS = {
    "age",
    "bio",
    "body",
    "company",
    "content",
    "description",
    "facebook",
    "gender",
    "googleplus",
    "googleprofile",
    "leademailaddress",
    "linkedin",
    "location",
    "message",
    "note",
    "notes",
    "subject",
    "title",
    "topics",
    "twitter",
}
URL_REDACT_KEYS = {"pageurl", "sourceurl", "url"}


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    if "@" in value:
        local, domain = value.split("@", 1)
        return f"{local[0]}***@{domain}"
    if PHONE_LIKE_PATTERN.match(value) and any(character.isdigit() for character in value):
        return f"***{value[-4:]}" if len(value) >= 4 else "***"
    return f"{value[0]}***" if len(value) > 1 else "***"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized.endswith("key") or any(
        fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS
    )


def redact_payload(payload: Any) -> Any:
    """Return a redacted copy of a FUB payload suitable for stdout inspection."""
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            lower_key = key.lower()
            if _is_sensitive_key(key):
                redacted[key] = "***"
            elif lower_key in FULL_REDACT_KEYS:
                redacted[key] = "***" if value is not None else None
            elif lower_key in URL_REDACT_KEYS:
                redacted[key] = "url[redacted]" if value else value
            elif lower_key in {
                "firstname",
                "first_name",
                "last_name",
                "lastname",
                "name",
                "email",
                "phone",
                "phones",
                "emails",
                "address",
                "addresses",
                "assignedlendername",
                "assignedto",
                "street",
                "city",
                "state",
                "zip",
                "postalcode",
                "picture",
            }:
                if isinstance(value, list):
                    redacted_items: list[Any] = []
                    for item in value:
                        if isinstance(item, dict):
                            redacted_items.append({k: _mask(str(v)) for k, v in item.items()})
                        else:
                            redacted_items.append(_mask(str(item)))
                    redacted[key] = redacted_items
                elif isinstance(value, dict):
                    redacted[key] = {k: _mask(str(v)) for k, v in value.items()}
                else:
                    redacted[key] = _mask(str(value))
            elif lower_key in {"customfields", "custom_fields"} and isinstance(value, dict):
                redacted[key] = {k: "***" if v is not None else None for k, v in value.items()}
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


def collect_field_keys(payload: Any, prefix: str = "", found: set[str] | None = None) -> set[str]:
    if found is None:
        found = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            found.add(path)
            collect_field_keys(value, path, found)
    elif isinstance(payload, list):
        for item in payload:
            collect_field_keys(item, prefix, found)
    return found


def collect_values(payloads: list[dict[str, Any]], key: str) -> Counter[str]:
    values: Counter[str] = Counter()
    for payload in payloads:
        value = payload.get(key)
        if value is None:
            values["(null)"] += 1
        elif isinstance(value, list):
            values[f"list[{len(value)}]"] += 1
        elif isinstance(value, dict):
            values[f"dict[{len(value)}]"] += 1
        else:
            values[str(value)] += 1
    return values


def _items_from_response(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = response.get(key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _write(output: TextIO, value: object = "") -> None:
    print(value, file=output)


async def get_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        response = await client.get(path, params=params, timeout=30.0)
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "FUB request failed",
            path=path,
            status=exc.response.status_code,
        )
        return None
    except httpx.RequestError as exc:
        logger.warning("FUB request error", path=path, error=str(exc))
        return None


async def explore(
    api_key: str,
    *,
    output: TextIO,
    limit: int = SAMPLE_LIMIT,
    include_me: bool = False,
    include_users: bool = False,
) -> None:
    auth = httpx.BasicAuth(api_key, "")
    async with httpx.AsyncClient(auth=auth, base_url=FUB_BASE_URL) as client:
        me = await get_json(client, "/me")
        if me is None:
            _write(output, "Failed to authenticate with Follow Up Boss. Check FUB_API_KEY.")
            return

        if include_me:
            _write(output, "=== /me (redacted) ===")
            _write(output, redact_payload(me))
            _write(output)
        else:
            _write(output, "=== authentication ===")
            _write(
                output,
                {
                    "authenticated": True,
                    "role": me.get("role"),
                    "account": me.get("account"),
                    "me_payload": "skipped; pass --include-me to inspect redacted /me shape",
                },
            )
            _write(output)

        people_resp = await get_json(client, "/people", params={"limit": limit})
        if people_resp is None:
            _write(output, "Failed to fetch /people.")
            return

        people = _items_from_response(people_resp, "people")
        if not people:
            _write(output, "No people returned from /people.")
            return

        _write(output, f"=== /people (first {len(people)} records) ===")
        _write(output, f"total reported: {people_resp.get('total', 'unknown')}")
        _write(output, "field keys found:")
        for key in sorted(collect_field_keys(people)):
            _write(output, f"  {key}")
        _write(output)

        people_fields = (
            "type",
            "source",
            "stage",
            "createdVia",
            "tags",
            "customFields",
            "assignedUserId",
            "contacted",
            "price",
            "created",
            "updated",
        )
        for field in people_fields:
            _write(output, f"  {field}: {dict(collect_values(people, field))}")
        _write(output)

        _write(output, "redacted sample records:")
        for person in people:
            _write(output, redact_payload(person))
        _write(output)

        events = await get_json(client, "/events", params={"limit": limit})
        if events is not None:
            items = _items_from_response(events, "events")
            _write(output, f"=== /events (first {len(items)} records) ===")
            _write(output, "field keys found:")
            for key in sorted(collect_field_keys(items)):
                _write(output, f"  {key}")
            _write(output, "redacted sample records:")
            for item in items:
                _write(output, redact_payload(item))
            _write(output)

        if include_users:
            users = await get_json(client, "/users", params={"limit": limit})
            if users is not None:
                items = _items_from_response(users, "users")
                _write(output, f"=== /users (first {len(items)} records, redacted) ===")
                _write(output, "field keys found:")
                for key in sorted(collect_field_keys(items)):
                    _write(output, f"  {key}")
                _write(output, "redacted sample records:")
                for item in items:
                    _write(output, redact_payload(item))
                _write(output)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explore FUB lead data with redacted output.")
    parser.add_argument("--limit", type=int, default=SAMPLE_LIMIT, help="Sample size per endpoint.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Local file path for the redacted report.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the report instead of saving it.",
    )
    parser.add_argument("--include-me", action="store_true", help="Include redacted /me payload.")
    parser.add_argument(
        "--include-users",
        action="store_true",
        help="Include redacted /users payload.",
    )
    return parser.parse_args(argv)


async def main() -> None:
    args = parse_args()
    api_key = os.environ.get("FUB_API_KEY")
    if not api_key:
        print(
            "Set FUB_API_KEY in the environment, e.g. "
            "FUB_API_KEY=... uv run python scripts/explore_follow_up_boss.py"
        )
        raise SystemExit(1)

    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    if args.stdout:
        await explore(
            api_key,
            output=sys.stdout,
            limit=args.limit,
            include_me=args.include_me,
            include_users=args.include_users,
        )
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        await explore(
            api_key,
            output=output,
            limit=args.limit,
            include_me=args.include_me,
            include_users=args.include_users,
        )
    print(f"Saved redacted Follow Up Boss exploration report to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
