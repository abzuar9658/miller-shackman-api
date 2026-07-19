"""Tests for the outbound demo script query parsing helpers."""

from scripts.demo_outbound_message_from_query import (
    _broad_search_summaries,
    _extract_preferences,
)


def test_extract_preferences_for_broad_rental_budget_query() -> None:
    preferences = _extract_preferences(
        "I'm interested in some nearby apartments in queens for rent and less than $2k/month"
    )

    assert preferences == {
        "search_type": "rent",
        "location": "Queens",
        "max_price": "2000",
    }


def test_extract_preferences_supports_bedroom_and_budget_filters() -> None:
    preferences = _extract_preferences("Looking for 2 bedroom rentals in Brooklyn under $3.5k")

    assert preferences["search_type"] == "rent"
    assert preferences["location"] == "Brooklyn"
    assert preferences["beds"] == "2"
    assert preferences["max_price"] == "3500"


def test_extract_preferences_supports_specific_address_queries() -> None:
    preferences = _extract_preferences(
        "I'm interested in 420 East 72nd Street #2E. Is there a dedicated hvac unit?"
    )

    assert preferences == {"address": "420 East 72nd Street #2E"}


def test_broad_search_summaries_are_dynamic_and_budget_aware() -> None:
    summary, memory = _broad_search_summaries(
        {
            "search_type": "rent",
            "location": "Queens",
            "beds": "2",
            "max_price": "2000",
        }
    )

    assert "Queens" in summary
    assert "2 bedrooms" in summary
    assert "stated budget" in summary
    assert memory.startswith("Recent memory:")
