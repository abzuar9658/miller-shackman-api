# Listing Source Ingestion & Retrieval Plan

## Status

In progress — backend foundation and an initial **StreetEasy query-and-cache enrichment experiment** are implemented. The current implementation is feature-flagged, best-effort, and skips enrichment on failure.

## Implementation Progress

### Completed in code

The following backend foundation is now implemented:

- `listing_sources`, `listing_crawl_runs`, and `listing_snapshots` schema added via Alembic.
- pgvector-ready migration added with conditional `CREATE EXTENSION IF NOT EXISTS vector` when available.
- Local compose Postgres image updated to a pgvector-capable image.
- New domain module: `app/domain/listing_sources/`.
- New repository ports: `app/application/ports/listing_sources.py`.
- Postgres repositories for sources, crawl runs, and snapshots.
- Source registry backend API for:
  - list listing sources
  - get listing source
  - create listing source
  - update / enable / disable listing source
- Permission capability added so listing source management is limited to brokerage admins.
- `make migrate` succeeded locally for the new Alembic revision.
- Focused API and repository tests added.
- `app/infrastructure/listing_sources/streeteasy/` live search adapter added behind an internal `ListingSearchClient` port.
- Optional outbound listing-context enrichment added before outbound drafting in `plan_next_outbound_message_for_lead`.
- Listing matches are normalized into bounded approved LLM context and only included when enrichment succeeds.
- Cached/current listing snapshots are reused first; live StreetEasy lookup is attempted only when no fresh matching snapshot is available.
- Enrichment is controlled by settings and skips safely when StreetEasy is blocked, empty, or unavailable.
- Focused unit/integration tests added for prompt payloads, enrichment behavior, provider construction, and StreetEasy parsing/block detection.

### Intentionally not implemented yet

- No durable crawl orchestration use case yet.
- No full StreetEasy index/detail fixture corpus yet.
- No embeddings table or vector retrieval yet.
- No listing review UI yet.
- No audit/outbox event emission yet for listing source changes.
- No guarantee that live StreetEasy fetches will succeed in production environments.

### Current next step

Proceed to the next hardening slice:

- save sanitized StreetEasy fixture HTML for parser stability tests
- add explicit snapshot freshness and query-hash observability for enrichment
- decide whether to keep prompt enrichment experimental or move back behind manual review only

## StreetEasy feasibility and risk assessment

### Technical findings

- StreetEasy pages appear to include structured data that is usable for listing extraction.
- A narrow HTML-first adapter is feasible for simple sale/rent searches.
- In this local environment, direct StreetEasy fetches returned a **PerimeterX anti-bot block page** for basic requests.
- Because of that, StreetEasy enrichment must remain **optional** and must fail closed.

### Product implications

- Listing enrichment cannot be required for outbound drafting.
- Message planning must continue normally when StreetEasy returns no results, times out, or blocks the request.
- Cached normalized snapshots are preferable to repeated live fetches when possible.

### Legal/compliance note

- Building the adapter ourselves does **not** remove StreetEasy/Zillow terms-of-use or robots-related risk.
- The current implementation should be treated as an experiment and remain easy to disable.

## Problem

Outreach messages are currently generic:

> “Hi! Just checking in to see if you’re still considering a move.”

Leads often come from property searches (e.g., StreetEasy). If we can safely connect lead context with relevant, fresh, authorized listing data, we can make drafts more useful and handoffs more actionable.

## Goal

Build a controlled, admin-managed source ingestion and retrieval system that eventually makes AI drafts and agent handoffs more relevant, while keeping human oversight on any listing-specific communication.

## Non-Goals

- Do not replace the CRM or agent.
- Do not build an autonomous property-recommendation engine.
- Do not bypass consent, suppression, handoff, or pre-send safety rules.
- Do not integrate MLS/IDX in Phase One.
- Do not use listings in automated outbound messages until explicitly approved.

## V1 Safety Constraints

Per `AGENTS.md` and `CLAUDE.md`:

- AI drafts and classifies; it does not decide eligibility, consent, opt-out, or send.
- Human handoff wins: meaningful interest, viewing requests, reassignment, or manual agent activity pauses AI.
- AI must not give property, market, financing, legal, or investment advice.
- Unknown/stale listing data must not be used in automated sends.
- All external dependencies live behind internal ports/interfaces.

## Backend-Only Execution Direction

The first implementation should be backend-only and should stop before LLM usage.

The goal is to prove that we can safely ingest one authorized source, store listings cleanly, re-run the scraper without duplicates, and expose listings for review. Only after reviewed listings look reliable should we add retrieval, embeddings, or prompt usage.

### Database Options Considered

#### Option 1 — Same Postgres database, listing-specific tables, pgvector extension

Use the existing Postgres database and add `listing_*` tables plus `CREATE EXTENSION IF NOT EXISTS vector`.

Pros:

- Keeps deployment simple.
- Reuses current migration, RLS, backup, and repository patterns.
- Easy to enforce `workspace_id` and transactional consistency.
- Good enough for first source and review workflows.

Cons:

- Listings can become high-volume, so indexing and retention rules must be deliberate.
- pgvector availability must be confirmed in local and production Postgres images.

#### Option 2 — Separate Postgres database for listings, also with pgvector

Run a separate database or connection dedicated to listing ingestion and vector search.

Pros:

- Cleaner operational separation if listing volume grows quickly.
- Listing scrape/query load is isolated from core lead/campaign traffic.

Cons:

- Adds deployment, migration, backup, and tenant-isolation complexity immediately.
- Harder to join listing context with leads/workflows.
- More moving parts before we know ingestion quality.

#### Option 3 — Dedicated vector database

Use a vector database separate from Postgres.

Pros:

- Purpose-built semantic search.
- May scale better for very large datasets later.

Cons:

- Premature for the first source.
- Adds another vendor and another consistency boundary.
- Does not solve canonical listing storage; we still need Postgres.

### Recommendation

Use **Option 1** now: same Postgres database, separate listing tables, pgvector enabled by migration. Treat listings as a clean bounded module so it can be extracted later if volume justifies it.

Do not add embeddings to the first scraper milestone. Add pgvector support as foundation, but first prove source ingestion, dedupe, freshness, and review quality using plain relational storage.

## Backend Step-by-Step Implementation Plan

### Milestone 0 — Source legality and scrape shape

Before coding the StreetEasy adapter, confirm whether the source can be fetched and stored for this commercial use.

Deliverables:

- Document the approved first source and allowed URL patterns.
- Decide whether we are scraping public pages, using a feed, or using a manually supplied sample export.
- Save a small fixture set for parser tests.

Testing:

- No live network tests required.
- Parser tests use checked-in sanitized fixtures.

Acceptance:

- No scraper runs against a source until `terms_reviewed_at` and `data_use_policy` are present on the source config.

### Milestone 1 — Database foundation and pgvector enablement

Deliverables:

- Alembic migration `0022` enabling pgvector with `CREATE EXTENSION IF NOT EXISTS vector`.
- Tables:
  - `listing_sources`
  - `listing_crawl_runs`
  - `listing_snapshots`
  - optional later table placeholder: `listing_embeddings`
- SQLAlchemy models in `app/infrastructure/persistence/postgres/models.py` or a listing-specific model module if that file is too large.
- Workspace isolation on every listing-owned table.
- RLS policies aligned with existing workspace RLS approach.

Testing:

- Migration upgrade/downgrade test where practical.
- Repository integration tests against Postgres.
- Tenant isolation tests for source/listing reads.

Acceptance:

- `make migrate` succeeds locally.
- No listing table exists without `workspace_id`.
- Duplicate snapshot constraints prevent duplicate rows from repeated crawls.

### Milestone 2 — Domain models and repository ports

Deliverables:

- `app/domain/listing_sources/` with simple dataclasses/enums:
  - `ListingSource`
  - `ListingSourceType`
  - `ListingCrawlRun`
  - `ListingCrawlStatus`
  - `CanonicalListingSnapshot`
  - `ListingStatus`
- `app/application/ports/listing_sources.py` with repository protocols:
  - `ListingSourceRepository`
  - `ListingCrawlRunRepository`
  - `ListingSnapshotRepository`
- Postgres repository implementations.

Testing:

- Unit tests for domain validation: URL allowlist, required source review fields, crawl state transitions.
- Repository tests for create, update, list, get, and idempotent upsert.

Acceptance:

- Domain layer has no SQLAlchemy, HTTP, or vendor imports.
- Repositories always require `workspace_id` for tenant-owned reads.

### Milestone 3 — Source registry API, backend only

Deliverables:

- Backend CRUD endpoints for listing sources.
- Brokerage-admin-only permissions.
- Audit/outbox events for source changes.
- No frontend work in this phase.

Testing:

- API tests for create/update/disable/list.
- Permission tests: agent/manager cannot manage sources unless explicitly allowed.
- Validation tests for invalid URL patterns, disabled source, and missing data-use policy.

Acceptance:

- Admin can create StreetEasy as a disabled/approved source record.
- No crawl can run for disabled or unreviewed sources.

### Milestone 4 — StreetEasy adapter and bounded query layer

Deliverables:

- `app/infrastructure/listing_sources/streeteasy/` adapter.
- Explicit parser functions for bounded search-result formats.
- A canonical mapper that returns `CanonicalListingSnapshot`.
- No generic scrape-any-site engine.
- HTTP fetcher interface local to infrastructure so tests can use a fake client.
- Anti-bot/block-page detection with safe fallback.

Testing:

- Fixture/parser tests for representative listing result pages.
- Malformed fixture tests.
- Missing required fields tests.
- Snapshot hash stability tests.
- No tests depend on live StreetEasy network calls.

Acceptance:

- Given representative result HTML, adapter emits stable canonical snapshots.
- Provider-specific HTML/JSON does not leave infrastructure.
- Blocked StreetEasy responses produce safe skip-on-failure behavior.

### Milestone 5 — Re-runnable crawl use case

Deliverables:

- Application use case: `run_listing_source_crawl`.
- Creates a `listing_crawl_run` row with status and counts.
- Fetches source pages through the source adapter.
- Stores current snapshots idempotently.
- Marks superseded previous snapshots as not current.
- Records parse errors without failing the entire run unless failure threshold is exceeded.
- Supports dry-run mode that parses and reports without storing snapshots.

Re-runnable behavior:

- Same source + same payload hash = no duplicate snapshot.
- Changed payload hash = new snapshot version.
- Same crawl command can be retried safely after partial failure.
- Crawl run stores counts: discovered, fetched, parsed, inserted, unchanged, failed.

Testing:

- Application tests with fake adapter and fake repositories.
- Idempotency tests for repeated crawl.
- Partial failure tests.
- Dry-run tests.
- Superseded-current-version tests.

Acceptance:

- Running the same crawl twice results in unchanged count, not duplicate listings.
- Failed listing parses are visible in crawl run output.

### Milestone 6 — Admin/review read APIs and bounded prompt context

Deliverables:

- Backend endpoints to review:
  - source health
  - crawl run history
  - current listings
  - stale listings
  - parse errors
  - listing detail by snapshot ID
- Filtering by source, status, neighborhood, price range, freshness, and crawl run.
- Pagination for listings.

Testing:

- API tests for listing review filters.
- Tenant isolation tests.
- Permission tests.
- Pagination tests.

Acceptance:

- Backend exposes enough data for a future frontend review screen.
- Listing context may be passed to the LLM only behind an explicit feature flag and only as bounded approved context.

### Milestone 7 — Embeddings and pgvector retrieval, after review quality is good

Deliverables:

- Add `listing_embeddings` table using pgvector.
- Add an `EmbeddingClient` port if the existing `LLMClient` should not own embeddings.
- Generate embedding input from canonical listing fields only.
- Store `embedding_model`, `embedding_text_hash`, and `listing_snapshot_id`.
- Deterministic filters remain the first stage; vector similarity is only ranking.

Testing:

- Unit tests for embedding text construction.
- Repository tests for vector insert/query if pgvector is available in test DB.
- Retrieval tests proving stale/inactive listings are filtered before vector ranking.

Acceptance:

- Vector search never returns listings outside the workspace.
- Retrieval returns bounded, fresh, current listings only.

### Milestone 8 — Lead/listing review context, no sending

Deliverables:

- Backend service that takes lead context and returns matched listing review context.
- Endpoint for lead detail or dedicated listing-context read.
- No changes to outbound drafting yet.

Testing:

- Matching tests for location, price, property type, and freshness.
- Safety tests that stale listings are excluded.

Acceptance:

- Agents/admins can review relevant listing context.
- Automated SMS/email remains unchanged.

## Coding Rules for This Feature

- Keep business models in `domain/listing_sources`.
- Keep use cases in `application/use_cases`.
- Keep scraper/fetch/parser code in `infrastructure/listing_sources`.
- Keep SQLAlchemy in `infrastructure/persistence/postgres` only.
- Use explicit source adapters; do not build a dynamic scraper engine.
- Keep live listing usage feature-flagged, bounded, and easy to disable until reviewed listings are reliable.
- Do not add live-network tests.
- Use package manager commands for dependency changes; do not manually edit dependency files.

## Minimum Test Command Per Milestone

For each backend milestone, run the smallest relevant tests first, then the broader check:

1. New focused unit tests.
2. New repository/API tests.
3. `uv run ruff check .`
4. `uv run mypy app tests`
5. `uv run pytest` or the relevant package subset.

## Product Phases

### Phase A — Source Registry (V1-safe foundation)

Admin-managed source configuration with no scraping yet.

What gets built:

- `listing_sources` table and CRUD API.
- Backend source management API only; frontend source settings comes later.
- Audit events for source create/update/enable/disable.
- Role-based access: brokerage admins own sources.

Outcomes:

- Admins can declare and describe authorized sources.
- No automated ingestion or LLM usage yet.

### Phase B — Authorized Ingestion

Controlled, source-specific ingestion with explicit adapters.

What gets built:

- `CanonicalListingSnapshot` internal model.
- Source adapter interface + one controlled adapter (e.g., StreetEasy if legally allowed).
- Temporal workflow for durable crawl/retry.
- `listing_snapshots` table with versioning, freshness, and workspace isolation.
- Parse validation and source health monitoring.
- Optionally `listing_embeddings` if pgvector is available.

Outcomes:

- System extracts listing facts from approved sources.
- Snapshots are stored with source URL, scraped timestamp, and validity window.
- Admin can view current/stale listings and crawl health.

### Phase C — Retrieval & Context (Internal Review Only)

Match listings to lead context for admin/agent viewing, not automated sends.

What gets built:

- Deterministic filters (location, price, type, freshness).
- Optional semantic ranking via embeddings.
- Retrieval service that returns bounded results (max 3 fresh listings).
- Lead detail API returns matched listings for admin/agent review.
- Frontend display comes after backend review APIs are stable.

Outcomes:

- Agents see why a lead might be relevant to current listings.
- Listing context is visible and can be used experimentally in bounded drafts when the feature flag is enabled.

### Phase D — Human-Reviewed Listing-Informed Drafts

Use listing context during draft generation, but require human approval.

What gets built:

- LLM prompt includes bounded listing context (max 3, truncated descriptions, freshness metadata).
- Generated draft is stored in the rejected draft review / approval flow.
- UI shows which listings were used, the generated draft, and any policy warnings.
- Admin/agent must approve before the message sends.
- Audit log records: source, listing snapshots, prompt version, and approver.

Outcomes:

- Listing-informed drafts are possible, but only with explicit human approval.

### Phase E — Automated Listing-Informed Sends (Phase Two)

Only after policy, legal, and operational confidence.

Requirements:

- Source is explicitly authorized.
- Listing snapshot is fresh (e.g., scraped within 24 hours).
- Listing is still active/current.
- Lead has channel consent and no suppression/human-owned state.
- No recent human activity or ownership change.
- No property-specific advice language in the draft.
- No price/status claims that could be stale.
- Strict language rules enforced by prompt + post-hoc validator.
- Optional: always require human approval for property-specific messages.

## Source Registry

### Domain

- `app/domain/listing_sources/`

### Application

- `app/application/use_cases/listing_sources/`
- `app/application/ports/listing_source_repository.py`

### Infrastructure

- `app/infrastructure/persistence/postgres/listing_source_repository.py`
- `app/infrastructure/listing_sources/`

### Interface

- `app/interfaces/api/v1/listing_sources.py`

### `listing_sources` fields

| Field                       | Purpose                                   |
| --------------------------- | ----------------------------------------- |
| `source_id`                 | Internal UUID                             |
| `workspace_id`              | Tenant isolation                          |
| `name`                      | Display name                              |
| `source_type`               | `website`, `feed`, `manual_upload`, `api` |
| `base_url`                  | Origin URL                                |
| `allowed_url_patterns`      | Approved crawl patterns                   |
| `disallowed_url_patterns`   | Excluded patterns                         |
| `crawl_frequency`           | How often to crawl                        |
| `enabled`                   | On/off switch                             |
| `requires_auth`             | Whether credentials are needed            |
| `terms_reviewed_at`         | Legal/terms review timestamp              |
| `terms_reviewed_by_user_id` | Reviewer                                  |
| `data_use_policy`           | Notes on allowed use                      |

## Ingestion Architecture

### Adapter contract

Each source adapter returns `CanonicalListingSnapshot` objects, never provider-specific payloads.

```text
CanonicalListingSnapshot
- workspace_id
- source_id
- external_listing_id
- source_url
- title
- address_text
- city
- state
- postal_code
- neighborhood
- price (Decimal)
- beds
- baths
- property_type
- status
- description
- image_urls
- listed_at
- updated_at
- scraped_at
- valid_until
- source_payload_hash
- source_payload
```

### Crawl flow (Temporal)

1. Select source and crawl scope.
2. Fetch index/feed pages within allowed patterns.
3. Discover listing URLs/IDs.
4. Fetch listing detail pages.
5. Parse into canonical snapshots.
6. Validate required fields.
7. Deduplicate by `(workspace_id, source_id, external_listing_id, payload_hash)`.
8. Store snapshot and mark previous version as not current.
9. Optionally create/update embeddings.
10. Emit `listing.source_crawled`, `listing.snapshot_created` events.

### Source health

Track:

- last successful crawl
- last failed crawl
- parse errors
- listing count
- average crawl duration
- blocked/disallowed URL hits

## Storage Model

### Tables

#### `listing_sources`

Admin source configuration. Unique on `(workspace_id, source_id)`.

#### `listing_snapshots`

Versioned listing data.

Key constraints:

- `unique(workspace_id, source_id, external_listing_id, payload_hash)`
- Current listing lookup: `(workspace_id, source_id, external_listing_id, is_current)`

Indexes:

- workspace + source + external_id + is_current
- workspace + source + scraped_at
- workspace + source + status + is_current

#### `listing_embeddings` (optional, pgvector)

- `workspace_id`
- `listing_snapshot_id`
- `embedding_model`
- `embedding` (vector)
- `embedding_text_hash`
- `created_at`

Use only if pgvector is confirmed in the Postgres setup.

## Retrieval Model

### Two-stage retrieval

1. **Deterministic filters**
   - workspace
   - `is_current = true`
   - scraped within freshness window (default 24 hours)
   - status active
   - city / neighborhood matches lead context if known
   - price range if known
   - property type if known
   - beds / baths if known

2. **Semantic ranking** (if embeddings enabled)
   - Rank by cosine similarity to lead preference text or recent conversation.
   - Combine with deterministic score.
   - Return top 3.

### Output contract

Retrieval service returns a bounded `ListingContext` object:

- max 3 listings
- truncated description per listing
- `scraped_at`, `source_url`, `source_name`
- freshness flag
- match reason (deterministic or semantic)

## LLM Context Rules

When listing context is passed to the LLM:

### Allowed

- Mention that the assigned agent can review relevant options.
- Reference broad area or property-type interest.
- Ask if the lead would like the agent to follow up.

### Not Allowed Without Explicit Approval

- “I found the perfect listing.”
- “This is a great deal.”
- “You should buy this.”
- Market predictions or investment claims.
- Financing, legal, or tax advice.
- Stale price or availability claims.
- Unsupported showing availability.

### Safer generated language

Preferred:

> Your agent can review current options that match your interest in Upper East Side condos.

Avoid:

> You should tour this penthouse at $X.

## Future Admin UX

This is intentionally deferred until backend source ingestion and review APIs are reliable.

### Source settings page

Brokerage admins can:

- add/edit/disable sources
- set crawl frequency and allowed patterns
- view crawl status and health
- see last sync and parse errors
- review listing counts
- record terms/data-use policy

### Lead detail page

Show a “Relevant listing context” panel:

- matched listings
- why they matched
- freshness
- source URL
- option to use in a reviewed draft (Phase D)

### Draft review page (Phase D)

If listing context was used:

- show listings passed to the LLM
- show generated draft
- show policy warnings
- require approval before send
- record approver and audit trail

## Compliance & Legal Requirements

Before enabling any source, answer:

- Does the source allow scraping or data reuse?
- What do `robots.txt` and terms of service say?
- Can extracted data be stored and used for outbound marketing?
- Are images, prices, and descriptions licensed?
- Is there an official API, feed, or vendor agreement available?
- Are brokerage-owned listings a safer first source than third-party sites?

Default rule: if not clearly allowed, do not scrape. Prefer authorized APIs, feeds, or brokerage-owned data.

## Observability

Track per source and per listing:

- crawl duration and success rate
- parse errors
- snapshot freshness
- listing count and churn
- retrieval queries and match counts
- LLM drafts that used listing context
- policy warnings and rejections
- human approvals vs. rejections

Every listing-informed draft or handoff should record:

- workspace_id, lead_id, campaign_id, workflow_id
- source_id, listing_snapshot_ids
- prompt version, model, provider
- approver_id (Phase D)

## Testing Plan

- Unit tests for source adapter parsing with fixture HTML/JSON.
- Unit tests for deterministic retrieval filters.
- Unit tests for canonical snapshot deduplication.
- Integration tests for the crawl workflow using fake HTTP client.
- Policy tests: reject drafts with property-advice language.
- Idempotency tests: same external listing id does not create duplicate snapshots.
- Tenant isolation tests: workspace A cannot see workspace B sources/listings.

## Open Questions

1. Is StreetEasy scraping explicitly allowed by its terms, or should we use an API/feed/brokerage-owned source first?
2. Is pgvector available in the local and production Postgres environments?
3. Should Phase D require admin approval, manager approval, or assigned-agent approval?
4. Should listing-informed drafts be allowed for SMS, email, or both?
5. What is the maximum acceptable listing description length passed to the LLM?
6. Should images be stored, or only image URLs?
7. How do we detect a listing is no longer available (status change, delisting)?

## Recommended First Step

Approve this plan, then implement backend **Milestones 0–6** in order: source review, pgvector/database foundation, domain/repository layer, source registry API, first-source scraper adapter, re-runnable crawl use case, and listing review APIs. No frontend, no LLM usage, and no automated message changes until listings have been reviewed and accepted.
