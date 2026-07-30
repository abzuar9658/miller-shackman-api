"""Print the canonical paused-search reason codes visible to admins."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ruff: noqa: E402
from app.domain.leads import PausedSearchReasonCode

REASON_LABELS: dict[PausedSearchReasonCode, str] = {
    PausedSearchReasonCode.RENTED_TEMPORARILY: "Rented temporarily",
    PausedSearchReasonCode.TIMING_NOT_RIGHT: "Timing not right",
    PausedSearchReasonCode.WAITING_FOR_RATES: "Waiting for rates",
    PausedSearchReasonCode.WAITING_FOR_INVENTORY: "Waiting for inventory",
    PausedSearchReasonCode.FINANCIAL_PREP: "Financial prep",
    PausedSearchReasonCode.PERSONAL_LIFE_TIMING: "Personal life timing",
    PausedSearchReasonCode.OTHER_KNOWN_PAUSE: "Other known pause",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List paused-search reason codes that admins can assign to leads."
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format.",
    )
    return parser.parse_args(argv)


def build_reason_rows() -> list[dict[str, str]]:
    return [
        {
            "code": reason.value,
            "label": REASON_LABELS[reason],
        }
        for reason in PausedSearchReasonCode
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_reason_rows()

    if args.format == "json":
        print(json.dumps(rows, indent=2))
        return 0

    print("Admin-visible paused-search reason codes:")
    for row in rows:
        print(f"- {row['code']} | {row['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())