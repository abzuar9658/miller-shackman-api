"""Tests for the Follow Up Boss exploration script's redaction helpers."""

from collections import Counter
from typing import Any

import pytest

from scripts.explore_follow_up_boss import (
    DEFAULT_OUTPUT,
    collect_field_keys,
    collect_values,
    parse_args,
    redact_payload,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"email": "john@example.com"}, {"email": "j***@example.com"}),
        ({"phone": "+15551234567"}, {"phone": "***4567"}),
        (
            {"firstName": "John", "lastName": "Smith"},
            {"firstName": "J***", "lastName": "S***"},
        ),
        (
            {"address": {"street": "1 Main St", "city": "Austin"}},
            {"address": {"street": "1***", "city": "A***"}},
        ),
        (
            {"phones": [{"value": "+15551234567"}, "+15559876543"]},
            {"phones": [{"value": "***4567"}, "***6543"]},
        ),
        (
            {"customFields": {"lead_type": "Buyer", "budget": "500000"}},
            {"customFields": {"lead_type": "***", "budget": "***"}},
        ),
        (
            {"nested": {"email": "a@b.com"}},
            {"nested": {"email": "a***@b.com"}},
        ),
        (
            {"algoliaKey": "secret", "nested": {"accessToken": "token-value"}},
            {"algoliaKey": "***", "nested": {"accessToken": "***"}},
        ),
        (
            {"signature": "--<br />Agent<br />(555) 111-2222<br />"},
            {"signature": "***"},
        ),
        (
            {"message": "john@example.com asked about 123 Main St"},
            {"message": "***"},
        ),
        (
            {"socialData": {"bio": "private bio", "linkedIn": "https://example.com/me"}},
            {"socialData": {"bio": "***", "linkedIn": "***"}},
        ),
        (
            {"sourceUrl": "https://example.com/private-path"},
            {"sourceUrl": "url[redacted]"},
        ),
    ],
)
def test_redact_payload(raw: dict[str, Any], expected: dict[str, Any]) -> None:
    assert redact_payload(raw) == expected


def test_redact_payload_preserves_unknown_fields() -> None:
    payload = {"id": "123", "source": "Zillow", "unknown_field": {"foo": "bar"}}
    expected = {"id": "123", "source": "Zillow", "unknown_field": {"foo": "bar"}}
    assert redact_payload(payload) == expected


def test_collect_field_keys() -> None:
    payloads = [
        {"id": 1, "name": "a", "nested": {"x": 1, "y": [1, 2, 3]}},
        {"id": 2, "name": "b", "nested": {"x": 4, "z": "z"}},
    ]
    keys = collect_field_keys(payloads)
    assert keys == {"id", "name", "nested", "nested.x", "nested.y", "nested.z"}


def test_collect_values() -> None:
    payloads: list[dict[str, Any]] = [
        {"id": 1, "source": "A", "tags": ["x"], "customFields": None},
        {"id": 2, "source": "B", "tags": ["x", "y"], "customFields": {"a": "b"}},
        {"id": 3, "source": None, "tags": [], "customFields": {"a": "b", "c": "d"}},
    ]
    assert collect_values(payloads, "source") == Counter(
        {"A": 1, "B": 1, "(null)": 1}
    )
    assert collect_values(payloads, "tags") == Counter(
        {"list[1]": 1, "list[2]": 1, "list[0]": 1}
    )
    assert collect_values(payloads, "customFields") == Counter(
        {"(null)": 1, "dict[1]": 1, "dict[2]": 1}
    )


def test_parse_args_defaults_to_local_report_file() -> None:
    args = parse_args([])
    assert args.output == DEFAULT_OUTPUT
    assert args.limit == 5
    assert args.stdout is False
    assert args.include_me is False
    assert args.include_users is False


def test_parse_args_supports_output_and_limit() -> None:
    args = parse_args(["--output", "tmp/custom.txt", "--limit", "25", "--stdout"])
    assert str(args.output) == "tmp/custom.txt"
    assert args.limit == 25
    assert args.stdout is True
