# Paused-Search Dynamic Track Classification Correction Plan
## Status
**Draft for product and engineering approval. No application code or migration changes until approved.**
## 1. Purpose
Correct paused-search so each admin-defined track is itself a classification category. The application supplies the current published catalog, the LLM selects from that catalog using admin guidance, and the backend pins the exact selected version.
This replaces the current separate `PausedSearchTrackFamily` plus fixed `PausedSearchReasonCode`-to-track mapping model.
## 2. Target model
Each paused-search track contains:
- stable `track_key` and display name
- required, versioned `selection_guidance`
- enabled/retired lifecycle
- immutable draft/published versions
- ordered cadence steps, templates, timing, and touch limits
- code-owned safety capabilities
There is no separate track-family enum and no reason-code mapping table. `PausedSearchTrackStepPhase` may remain because it describes a cadence step, not a category.
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
- **Retire:** remove from future catalogs; existing assignments remain pinned and are not migrated automatically.
- **Delete:** only an unreferenced retired track; block deletion while assignments, workflows, history, or audit records reference it.
- **Stable key:** immutable after first publication.
## 6. Safety ownership
Replace reason-derived safety routing with a universal code-owned baseline: consent, suppression, quiet hours, frequency, pre-send checks, human-activity pause, handoff pause, five-interaction cap, maximum duration/touches, and no financial, legal, tax, investment, market-prediction, or unverified-listing claims.
Any specialized restrictions remain code-owned safety capabilities, not categories. Admin settings may tighten but never weaken them.
## 7. Step-by-step delivery plan
### Phase 0 — Approval and baseline
1. Approve this target model and decisions in section 9.
2. Update the business-rule terminology.
3. Run focused backend/frontend checks and record the baseline.
4. Keep all legacy fields and read paths during transition.
### Phase 1 — Additive persistence
1. Add nullable `selection_guidance` to track versions.
2. Persist selected key, exact version, catalog snapshot, confidence, and review status.
3. Add workspace-scoped indexes/constraints.
4. Preserve family, reason, mapping, and legacy history fields; never fabricate guidance.
### Phase 2 — Domain and validation
1. Add guidance to domain, config, API, and persistence models.
2. Remove family/mapping fields from new write paths.
3. Validate stable keys, catalog size, duplicate keys, cadence, publication, and version immutability.
4. Enforce code-owned safety independently of track category.
### Phase 3 — Catalog and classification
1. Add an application-layer catalog read contract.
2. Update the prompt and structured LLM result to select a catalog key.
3. Keep provider objects inside the LLM adapter.
4. Validate against the supplied snapshot and persist evidence/review outcomes.
### Phase 4 — Assignment and workflow
1. Replace reason-to-track resolution with snapshot-key-to-version assignment.
2. Update classification application, enrollment, rescheduling, manual override, and Temporal signal paths.
3. Preserve exact pins for existing workflows.
4. Ensure uncertain selection pauses safely and retirement never silently migrates a lead.
### Phase 5 — API and UI
1. Remove family dropdowns/badges and reason checkboxes.
2. Add required “When should this track be selected?” guidance input and accessible validation.
3. Show catalog eligibility, publish errors, version, status, and safety limits.
4. Preview the exact catalog entry supplied to classification.
5. Make manual lead controls select an active published track and show its guidance/version.
6. Add empty-catalog, review, permission, loading, and error states.
### Phase 6 — Tests, docs, and observability
1. Update domain, application, persistence, API, frontend, and business-flow tests.
2. Add migration round-trip, idempotency, and workspace-isolation tests.
3. Update business rules, planning docs, API docs, completion status, and operations runbook.
4. Measure catalog size, selected track/version, no-match, ambiguity, low confidence, stale key, concurrent retirement, and manual correction.
### Phase 7 — Rollout and cleanup
1. Gate catalog routing by workspace/runtime control.
2. Monitor review and correction rates before broad enablement.
3. Keep legacy reads/fields for rollback.
4. Remove obsolete writes, then perform a separate cleanup migration dropping family and mapping structures.
5. Preserve historical reason values as legacy audit data where needed.
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
- New leads use new published versions; existing leads retain pinned versions.
- Retirement affects future classification only; deletion is blocked while referenced.
- Guidance/configuration cannot weaken safety.
- Duplicate events are idempotent; snapshots/audits round-trip with tenant isolation.
- UI contains no family/reason-mapping controls and the full conversation → classification → cadence → handoff flow passes with fakes.
## 10. Approval decisions
Please approve or change these before implementation:
1. Admin-defined tracks are the only classification categories.
2. `selection_guidance` is required, versioned, and bounded to 30–1,000 characters.
3. Maximum 20 active published classification tracks per workspace.
4. No-match, ambiguity, low confidence, missing catalog, and stale selection always hold for review.
5. Existing assignments remain pinned through publication and retirement.
6. Safety is universal/code-owned; tracks can only tighten limits.
7. Migration is additive first; cleanup follows rollout stability.
**Implementation begins only after explicit approval of this document and any changes above.**
