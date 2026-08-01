from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.application.ports.listing_search import ListingSearchQuery
from app.domain.listing_sources import CanonicalListingSnapshot, ListingSnapshotStatus


def select_matching_snapshots(
    snapshots: tuple[CanonicalListingSnapshot, ...],
    *,
    query: ListingSearchQuery,
    now: datetime,
    cache_ttl: timedelta,
    max_results: int,
) -> tuple[CanonicalListingSnapshot, ...]:
    fresh_after = now - cache_ttl
    active_and_fresh = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.status == ListingSnapshotStatus.ACTIVE
        and not (
            snapshot.scraped_at < fresh_after
            and (snapshot.valid_until is None or snapshot.valid_until < now)
        )
    )
    return rank_matching_snapshots(active_and_fresh, query=query, max_results=max_results)


def rank_matching_snapshots(
    snapshots: tuple[CanonicalListingSnapshot, ...],
    *,
    query: ListingSearchQuery,
    max_results: int,
) -> tuple[CanonicalListingSnapshot, ...]:
    ranked: list[tuple[int, CanonicalListingSnapshot]] = []
    for snapshot in snapshots:
        score = snapshot_match_score(snapshot, query)
        if score <= 0:
            continue
        ranked.append((score, snapshot))

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].scraped_at,
            item[1].price is not None,
        ),
        reverse=True,
    )
    return tuple(snapshot for _, snapshot in ranked[:max_results])


def rerank_live_response_snapshots(
    snapshots: tuple[CanonicalListingSnapshot, ...],
    *,
    query: ListingSearchQuery,
    max_results: int,
) -> tuple[CanonicalListingSnapshot, ...]:
    if not snapshots:
        return ()
    if not query.addresses and not query.keywords:
        return snapshots[:max_results]

    scored: list[tuple[int, CanonicalListingSnapshot]] = []
    for snapshot in snapshots:
        scored.append((live_response_match_score(snapshot, query), snapshot))

    if max(score for score, _ in scored) <= 0:
        return snapshots[:max_results]

    scored.sort(
        key=lambda item: (
            item[0],
            item[1].price is not None,
            item[1].scraped_at,
        ),
        reverse=True,
    )
    return tuple(snapshot for _, snapshot in scored[:max_results])


def snapshot_match_score(snapshot: CanonicalListingSnapshot, query: ListingSearchQuery) -> int:
    haystack = " ".join(
        part.lower()
        for part in (
            snapshot.title,
            snapshot.address_text,
            snapshot.neighborhood,
            snapshot.city,
            snapshot.description,
        )
        if part
    )
    score = 0
    if query.locations:
        if not any(term.lower() in haystack for term in query.locations):
            return 0
        score += 4
    if query.addresses:
        if not any(term.lower() in haystack for term in query.addresses):
            return 0
        score += 5
    if query.keywords and any(term.lower() in haystack for term in query.keywords):
        score += 1
    if (
        query.min_price is not None
        and snapshot.price is not None
        and snapshot.price < query.min_price
    ):
        return 0
    if (
        query.max_price is not None
        and snapshot.price is not None
        and snapshot.price > query.max_price
    ):
        return 0
    if query.min_price is not None or query.max_price is not None:
        score += 2
    if query.min_beds is not None and snapshot.beds is not None and snapshot.beds < query.min_beds:
        return 0
    if query.min_beds is not None:
        score += 1
    if snapshot.price is not None:
        score += 1
    return score


def live_response_match_score(snapshot: CanonicalListingSnapshot, query: ListingSearchQuery) -> int:
    haystack = _snapshot_haystack(snapshot)
    score = 0

    if query.locations and any(term.lower() in haystack for term in query.locations):
        score += 2
    if query.addresses:
        score += max(_address_match_score(address, haystack) for address in query.addresses)
    if query.keywords:
        score += sum(3 for term in query.keywords if term.lower() in haystack)
    if (
        query.min_price is not None
        and snapshot.price is not None
        and snapshot.price < query.min_price
    ):
        score -= 2
    if (
        query.max_price is not None
        and snapshot.price is not None
        and snapshot.price > query.max_price
    ):
        score -= 2
    if query.min_beds is not None and snapshot.beds is not None and snapshot.beds < query.min_beds:
        score -= 1
    if snapshot.price is not None:
        score += 1
    return score


def _snapshot_haystack(snapshot: CanonicalListingSnapshot) -> str:
    return " ".join(
        part.lower()
        for part in (
            snapshot.title,
            snapshot.address_text,
            snapshot.neighborhood,
            snapshot.city,
            snapshot.description,
            snapshot.property_type,
        )
        if part
    )


def _address_match_score(address: str, haystack: str) -> int:
    lowered = address.lower().strip()
    if lowered and lowered in haystack:
        return 8

    tokens = [token for token in _address_tokens(lowered) if token]
    if not tokens:
        return 0
    overlap = sum(1 for token in tokens if token in haystack)
    return overlap * 2


def _address_tokens(value: str) -> tuple[str, ...]:
    generic_tokens = {
        "street",
        "st",
        "avenue",
        "ave",
        "road",
        "rd",
        "boulevard",
        "blvd",
        "lane",
        "ln",
        "drive",
        "dr",
        "place",
        "pl",
        "court",
        "ct",
        "terrace",
        "ter",
        "east",
        "west",
        "north",
        "south",
    }
    parts = [token for token in re.split(r"[^a-z0-9]+", value) if token]
    return tuple(token for token in parts if token not in generic_tokens)
