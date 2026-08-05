# Paused-Search Dynamic Track Classification Correction Plan
## Status
**Implemented for development. This document is the current contract; the earlier paused-search
category and mapping design is superseded.**
## 1. Purpose
Correct paused-search so each admin-defined track is itself a classification category. The application supplies the current published catalog, the LLM selects from that catalog using admin guidance, and the backend pins the exact selected version.
This replaces the earlier fixed-category routing design with one explicit catalog contract.
## 2. Target model
Each paused-search track contains:
- stable `track_key` and display name
- required, versioned `selection_guidance`
- enabled/retired lifecycle
- immutable draft/published versions
- ordered cadence steps, templates, timing, and touch limits
- code-owned safety capabilities
There is no separate classification-category enum or routing table. `PausedSearchTrackStepPhase` remains because it describes a cadence step, not a classification category.
## 3. Selection guidance
Every classification-eligible version must answer **“When should this track be selected?”** Guidance must:
- be required before publish and catalog inclusion
- be immutable after publication and editable through a new version
- be 30–1,000 characters, with inclusion and exclusion cues
- describe lead evidence, not permissions or safety exceptions
Example: “Select when the lead remains interested in buying but explicitly postpones the search until rates improve. Do not select for immediate buying intent, general financial preparation, or a request for an agent.”
## 4. Runtime contract
### Step 1 — Build a catalog
1. Load enabled, published, non-retired versions for the workspace.
2. Exclude versions with missing/invalid guidance.
3. Create a snapshot of `track_key`, exact `track_version_id`, display name, and guidance.
4. Pass that snapshot to classification and persist it in the classification artifact.
5. Do not send cadence steps, templates, or message content to the classifier.
Recommended bound: 20 active published classification tracks per workspace; drafts and retired tracks do not count.
### Step 2 — Classify
For a paused-search outcome, structured output contains:
- nullable `selected_track_key`
- `track_selection_status`: `selected`, `no_match`, or `ambiguous`
- overall paused-search confidence and track-selection confidence
- evidence/event IDs, timing facts, and summary
The LLM may select only a supplied key. It must not invent keys, choose the closest track when uncertain, or treat admin text as system instructions.
### Step 3 — Validate and pin
The application must validate the status/key combination, validate the key against the exact snapshot, re-check enabled/published/non-retired state, and pin the snapshot's exact `track_version_id`. Persist key, version, snapshot, confidence, evidence, and decision reason.
Unknown/stale keys, disabled or retired versions, low confidence, missing catalogs, no-match, ambiguity, and concurrent retirement never start automation.
### Step 4 — Hold safely
If paused-search is clear but selection is unsafe: stop pending AI outreach; preserve the classification; do not start/continue a cadence; create a routing-review record and audit event; show the lead in Attention; require an authorized, explicit track selection/resume action.
## 5. Admin lifecycle
- **Create:** draft only; unavailable to classification until published.
- **Publish:** validate guidance, cadence, templates, limits, permissions, and safety; make the new version available to future classifications.
- **Edit:** create a new immutable version; never mutate a published version.
- **Retire:** remove from future catalogs. Development does not provide a data migration for already-created lead assignments.
- **Delete:** only an unreferenced retired track; block deletion while assignments, workflows, history, or audit records reference it.
- **Restore:** return the track to draft and require validation and republishing.
- **Stable key:** immutable after first publication.
## 6. Safety ownership
Replace reason-derived safety routing with a universal code-owned baseline: consent, suppression, quiet hours, frequency, pre-send checks, human-activity pause, handoff pause, five-interaction cap, maximum duration/touches, and no financial, legal, tax, investment, market-prediction, or unverified-listing claims.
Any specialized restrictions remain code-owned safety capabilities, not categories. Admin settings may tighten but never weaken them.
## 7. Step-by-step delivery plan
### Phase 0 — Contract and schema correction
1. Make the track catalog the only classification source.
2. Rewrite the paused-search domain, ORM models, repositories, and Alembic history around track identity, immutable versions, guidance, and assignments.
3. Do not add compatibility migrations, backfills, default seeding, or existing-lead conversion paths.
4. Treat development data as disposable when the corrected schema is applied.
### Phase 1 — Domain and persistence
1. Require bounded `selection_guidance` on every published version.
2. Persist selected key, selected version, selection status, confidence, evidence, and review state in the classification artifact.
3. Enforce workspace-scoped keys, foreign keys, indexes, assignment uniqueness, and version immutability.
4. Keep safety limits code-owned; configuration may tighten but never weaken them.
### Phase 2 — Catalog classification
1. Load only active, published, enabled track versions into a workspace catalog.
2. Pass only catalog identity, display name, and selection guidance to the classifier.
3. Validate the returned status and key against the exact catalog snapshot.
4. Reject unknown, stale, disabled, retired, low-confidence, ambiguous, no-match, and empty-catalog results into review.
### Phase 3 — Assignment and Temporal execution
1. Assign a concrete catalog track and exact published version.
2. Recheck the pinned version immediately before scheduling and sending.
3. Use the pinned version for cadence steps, timers, retries, signals, and audit events.
4. Stop automation on uncertainty, human activity, suppression, handoff, or invalidated eligibility.
### Phase 4 — API and frontend
1. Expose CRUD, draft validation, preview, publish, retire, restore-to-draft, and guarded delete operations.
2. Require guidance in the admin editor and show catalog eligibility, version, status, and safety limits.
3. Make manual selection choose a concrete active published track; do not expose category or mapping controls.
4. Provide clear review, empty-catalog, permission, loading, error, and responsive states.
### Phase 5 — Tests, documentation, and verification
1. Cover domain, application, persistence, API, Temporal, frontend, and full business-flow behavior.
2. Verify idempotency, pessimistic pre-send locking, tenant isolation, version pinning, and safe review holds.
3. Run native ARM64 lint, type checks, tests, build, migration graph, and browser checks.
4. Scan the repository for removed concepts and compatibility paths before release.
## 8. Impacted areas
- **Domain:** paused-search tracks, validation, lead profile/history, and safety capabilities.
- **Application:** classification, catalog read, assignment/pinning, admin, manual lead controls, and workflow orchestration.
- **Persistence:** SQLAlchemy models, Alembic migrations, repositories, artifacts, history, and audit records.
- **Interfaces:** API schemas/routes, Temporal payloads, and frontend track/lead controls.
- **Docs:** `docs/business-rules/06-ai-nurture-classification-routing-and-reply-handling.md`, paused-search plans, and runbook.
## 9. Acceptance tests
- Guidance is required to publish and enter the catalog.
- Only an exact active catalog key can be assigned.
- Unknown, stale, retired, disabled, low-confidence, ambiguous, and empty-catalog cases hold for review.
- New leads use only currently active published versions; existing development data is not migrated.
- Retirement affects future classification only; deletion is blocked while referenced.
- Guidance/configuration cannot weaken safety.
- Duplicate events are idempotent; snapshots/audits round-trip with tenant isolation.
- UI contains no family/reason-mapping controls and the full conversation → classification → cadence → handoff flow passes with fakes.
## 10. Implementation status
The clean-development replacement is implemented across the backend domain, persistence, CRUD and
classification APIs, assignment and Temporal paths, frontend catalog studio, tests, and operational
documentation. No compatibility migration or existing-lead conversion is part of this implementation.
