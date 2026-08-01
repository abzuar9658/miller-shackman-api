"""Tests for the StreetEasy demo search script argument parsing."""

from decimal import Decimal

import pytest

from scripts.demo_streeteasy_search import parse_args


def test_parse_args_defaults() -> None:
    args = parse_args(["--location", "Bronx"])

    assert args.location == "Bronx"
    assert args.address == []
    assert args.keyword == []
    assert args.search_type == "sale"
    assert args.limit == 3
    assert args.min_price is None
    assert args.max_price is None
    assert args.min_beds is None


def test_parse_args_supports_effective_streeteasy_filters() -> None:
    args = parse_args(
        [
            "--location",
            "Bronx",
            "--search-type",
            "rent",
            "--min-price",
            "250000",
            "--max-price",
            "700000",
            "--min-beds",
            "2",
            "--limit",
            "5",
        ]
    )

    assert args.location == "Bronx"
    assert args.search_type == "rent"
    assert args.min_price == Decimal("250000")
    assert args.max_price == Decimal("700000")
    assert args.min_beds == Decimal("2")
    assert args.limit == 5


def test_parse_args_supports_address_and_keyword_inputs() -> None:
    args = parse_args(
        [
            "--address",
            "225 East 134th Street",
            "--keyword",
            "doorman",
            "--keyword",
            "co-op",
        ]
    )

    assert args.location is None
    assert args.address == ["225 East 134th Street"]
    assert args.keyword == ["doorman", "co-op"]


def test_parse_args_rejects_inverted_price_range() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--location",
                "Bronx",
                "--min-price",
                "700000",
                "--max-price",
                "250000",
            ]
        )


def test_parse_args_requires_at_least_one_search_input() -> None:
    with pytest.raises(SystemExit):
        parse_args([])
