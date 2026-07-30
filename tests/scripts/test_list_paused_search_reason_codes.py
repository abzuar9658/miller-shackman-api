"""Tests for the paused-search reason listing script."""

import json

from app.domain.leads import PausedSearchReasonCode
from scripts.list_paused_search_reason_codes import build_reason_rows, parse_args


def test_build_reason_rows_lists_all_admin_visible_codes() -> None:
    rows = build_reason_rows()

    assert [row["code"] for row in rows] == [reason.value for reason in PausedSearchReasonCode]
    assert rows[0]["label"] == "Rented temporarily"
    assert rows[-1]["label"] == "Other known pause"


def test_parse_args_supports_json_output() -> None:
    args = parse_args(["--format", "json"])

    assert args.format == "json"


def test_reason_rows_are_json_serializable() -> None:
    payload = json.dumps(build_reason_rows())

    assert "waiting_for_rates" in payload