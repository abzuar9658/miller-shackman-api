"""Read-only check of historical activity for one Follow Up Boss contact.

Usage:
    FUB_API_KEY=your_key uv run python -m scripts.check_follow_up_boss_contact \
        --person-id 12345 --stdout

The report is redacted before it is written. This script makes only GET requests
and does not import records into the application database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from scripts.explore_follow_up_boss import collect_field_keys, redact_payload

DEFAULT_BASE_URL = "https://api.followupboss.com/v1"
DEFAULT_OUTPUT = Path("tmp/fub-contact-history-report.json")
DEFAULT_LIMIT = 50


async def fetch_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.get(path, params=params, timeout=30.0)
    except httpx.RequestError as exc:
        return {"status": "request_error", "error": str(exc)}

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_response": "non-JSON response"}
    if not isinstance(payload, dict):
        payload = {"payload_type": type(payload).__name__}

    result: dict[str, Any] = {
        "status": response.status_code,
        "ok": response.is_success,
        "payload": payload,
    }
    if response.is_error:
        result["error"] = response.reason_phrase
    return result


def _items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def summarize_collection(result: dict[str, Any], key: str) -> dict[str, Any]:
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return {"status": result.get("status"), "error": result.get("error")}

    items = _items(payload, key)
    summary: dict[str, Any] = {
        "status": result.get("status"),
        "ok": result.get("ok", False),
        "item_count": len(items),
        "reported_total": payload.get("total"),
        "field_keys": sorted(collect_field_keys(items)),
        "redacted_samples": [redact_payload(item) for item in items[:3]],
    }
    if result.get("error"):
        summary["error"] = result["error"]
    return summary


async def check_contact(
    api_key: str,
    person_id: str,
    *,
    base_url: str,
    limit: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    auth = httpx.BasicAuth(api_key, "")
    async with httpx.AsyncClient(
        auth=auth,
        base_url=base_url.rstrip("/"),
        transport=transport,
    ) as client:
        authentication = await fetch_json(client, "/me")
        person = await fetch_json(client, f"/people/{person_id}")
        collections = {
            "events": await fetch_json(client, "/events", {"personId": person_id, "limit": limit}),
            "notes": await fetch_json(client, "/notes", {"personId": person_id, "limit": limit}),
            "textMessages": await fetch_json(
                client, "/textMessages", {"personId": person_id, "limit": limit}
            ),
            "calls": await fetch_json(client, "/calls", {"personId": person_id, "limit": limit}),
        }

    person_payload = person.get("payload")
    return {
        "person_id": person_id,
        "authentication": {
            "status": authentication.get("status"),
            "authenticated": authentication.get("status") == 200,
        },
        "person": {
            "status": person.get("status"),
            "ok": person.get("ok", False),
            "redacted_payload": redact_payload(person_payload),
        },
        "activity": {
            name: summarize_collection(result, name) for name, result in collections.items()
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check historical FUB activity for one contact.")
    parser.add_argument("--person-id", required=True, help="FUB person/contact ID.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--base-url", default=os.environ.get("FUB_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true", help="Print JSON instead of saving it.")
    return parser.parse_args(argv)


async def main() -> None:
    args = parse_args()
    api_key = os.environ.get("FUB_API_KEY")
    if not api_key:
        print("Set FUB_API_KEY in the environment before running this script.", file=sys.stderr)
        raise SystemExit(1)
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    report = await check_contact(
        api_key,
        args.person_id,
        base_url=args.base_url,
        limit=args.limit,
    )
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.stdout:
        print(serialized)
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    print(f"Saved redacted FUB contact history report to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
