# Recorded opt-out preservation and bounded recovery — Issue 16-A

## Release status and authority

This is an **operator runbook, not production authorization**. The original revision `4bca9c3`
was rehearsed against disposable local Postgres but **predates the recovery review corrections**.
The [2026-09-10 remediation evidence](../planning/issue-16a-review-remediation-evidence.md) records
the corrected, currently unstaged source and its real-Postgres regression/interruption checks.
Do not use the historical pushed revision as the corrected recovery build. Production/Compose
containment, authenticated browser acceptance and real CRM/provider integration are
**not verified**. See [execution evidence](../planning/issue-16a-execution-contract.md).

The requesting owner is the merge/release/recovery operator. Keep the PR draft until its
outstanding gates are resolved. The existing GitHub workflow runs checks, builds and
**deploys after a push to main**: merging can trigger deployment. Coordinate containment
before that release; do not push main or trigger deployment just to obtain a CI result.
Recovery is never run automatically by migration, deployment or worker startup.

## What this repairs — and what it does not

- Preserves platform-recorded SMS, email and global do-not-contact restrictions during
  CRM refresh. Ordinary CRM fields still update; proven CRM-only restrictions may clear.
- Restores lost restrictions only from retained, verified platform evidence. Preserves
  existing valid provenance; otherwise chooses the earliest verified occurrence with
  provider/event-ID tie-breaking. Original history is not edited or replayed.
- Does not send, enroll, resume, change workflows, rerun an LLM, or call external providers.
- Does not deliver START/resubscribe or an audited human-clear route. A CRM permission
  edit, workflow resume or re-enrollment is not a platform opt-out lift.
- Twilio unsubscribe code 21610 and retained provider unsubscribe hints are review cases,
  not automatic repairs. Ordinary delivery failures are not opt-out evidence.
- Unknown/partial/conflicting evidence, ambiguous identity, missing history links and
  exhausted history bounds are unresolved. Do not guess consent in either direction.

**A recovery hold is only an exclusion from this tool.** `--hold-lead-id` does not pause
the lead, create a suppression, cancel a send or impose a runtime sending hold. Keep
unresolved cohorts contained separately. `clean` means no repair candidate was found in
the inspected retained history, not that outreach is authorized or history is complete.

## 1. Prepare and contain

1. Separately approve environment, immutable code/image revision, operator, exact workspace,
   at most 100 lead UUIDs, history ceiling and private report destination. Confirm both
   database settings point to that environment without printing URLs or credentials.
2. Inventory retained history and any later legitimate opt-ins/lifts known outside this
   schema. Put ambiguous or lifted leads on the explicit hold list. Apply requires an
   operator attestation that the rest of the cohort has been reviewed for later lifts.
3. Inventory queued/in-flight work and **every** old API/worker/manual process that can
   refresh or write leads. Preserve existing paused/handoff/terminal states. A UI pause
   alone is not proof all writers and every sending path have stopped.
4. For the checked-in production Compose deployment, use the following only after an
   authorized maintenance window. This intentionally stops the API too, preventing
   operator/on-demand writes. Keep databases, queues, Redis and Temporal infrastructure.

<augment_code_snippet path="compose.prod.yaml" mode="EXCERPT">
````bash
docker compose -f compose.prod.yaml stop api temporal-worker temporal-signal-dispatcher \
  outbound-send-dispatcher outbox-publisher crm-sync-worker crm-sync-scheduler \
  crm-webhook-retry-worker crm-history-import-worker inbound-message-worker
docker compose -f compose.prod.yaml ps --status running --services
````
</augment_code_snippet>

None of those application services may remain running. Stop separately supervised copies
using their actual supervisor; the Compose command cannot cover processes outside it.
Allow graceful shutdown and reconcile requests already submitted to a provider: stopping
a process does not retract them. Never reset an uncertain send's idempotency key. Plan
for webhook retry/retention while the API is unavailable and inspect it before reopening.
The exact production topology, shutdown/drain and callback-recovery checks require the
operator's staging rehearsal; this session did not execute them.

## 2. Install preservation before repairing

Use the approved release procedure to make the corrected version available to **all**
writers. Keep affected sending/writers contained while repairing. Do not start old workers
after repair; they could erase restored restrictions. No schema migration or new package
is required by this ticket. Do not run the normal deployment's blanket restart as a
substitute for scoped re-enablement approval.

The CLI is [scripts/recover_recorded_opt_outs.py](../../scripts/recover_recorded_opt_outs.py).
Run from the API repository with its existing configured environment; do not paste a
database URL or token into command arguments. On the local ARM Mac, use
`/usr/bin/arch -arm64 .venv/bin/python` in place of `uv run python` if necessary.

## 3. Dry-run and review

Set `RECOVERY_WORKSPACE_ID` and `RECOVERY_LEAD_ID` to the explicitly approved UUIDs;
`RECOVERY_AUDIT_DIR` must be an existing, private operator-owned directory outside the
checkout. Repeat `--lead-id` for the approved cohort. Use a new report name for every run.

<augment_code_snippet path="scripts/recover_recorded_opt_outs.py" mode="EXCERPT">
````bash
uv run python -m scripts.recover_recorded_opt_outs \
  --workspace-id "$RECOVERY_WORKSPACE_ID" --lead-id "$RECOVERY_LEAD_ID" \
  --report "$RECOVERY_AUDIT_DIR/dry-run.jsonl"
````
</augment_code_snippet>

For a held lead include its UUID in both `--lead-id` and `--hold-lead-id`. All hold IDs
must belong to the requested cohort. The default ceiling is 1,000 retained events per
lead, maximum 10,000 (`--max-events-per-lead`). Exceeding it is unresolved, never a
successful truncated repair. Do not narrow by date to evade missing earlier evidence.

For an authorized stopped Compose application, the same CLI can run as a one-off
container. The image must be the approved corrected revision. This overrides the API
command and avoids service startup, migrations and dependency synchronization:

<augment_code_snippet path="compose.prod.yaml" mode="EXCERPT">
````bash
docker compose -f compose.prod.yaml run --rm --no-deps -T \
  -v "$RECOVERY_AUDIT_DIR:/recovery" api /app/.venv/bin/python \
  -m scripts.recover_recorded_opt_outs --workspace-id "$RECOVERY_WORKSPACE_ID" \
  --lead-id "$RECOVERY_LEAD_ID" --report /recovery/dry-run.jsonl
````
</augment_code_snippet>

The image includes the CLI through Dockerfile's existing `COPY . .`. Container execution
and host report ownership still need staging validation; local CLI rehearsal is not proof
of container readiness. Inspect reports privately, not in public PRs or shared logs.

### Interpret the report before applying

- Files are exclusively created with mode `0600`, never overwrite existing paths/symlinks,
  and contain a durable header, one result per processed lead and a completion record.
- Reconcile `scoped == processed`. The status totals `clean + already_correct + would_change
  + changed + unresolved + failed` must equal `processed`. `candidate` overlaps these
  categories; it is not another status to add to that sum.
- Review every unresolved/failed result and its source references. Reports omit message
  bodies, contact destinations, credentials and raw payloads, but identifiers still need
  access control. Record external inventory/lift-review decisions alongside the report.
- References include `leads:<uuid>:<kind>` for retained platform provenance (including partial
  tuples requiring review), `external_events:<uuid>` for source events and `inbound_messages:<uuid>`
  for retained inbound rows. Distinct inbound references survive evidence deduplication; reports
  sort and deduplicate the reference strings. Referenced events belonging to another lead or
  conflicting local/history facts make the scoped lead unresolved; do not partially repair it.
- A complete valid local provenance tuple remains usable when its historical source is absent.
  This is not permission to overlook a retained contradictory source. An event-ceiling result is
  incomplete history, and its bounded references are not a complete inventory of unexamined rows.
- Exit `0`: enumeration completed without unresolved/failed leads. Exit `1`: unresolved,
  failed, storage or runtime failure. Exit `2`: invalid arguments. Exit `130`: interruption.
  A completion marker does not waive unresolved results; absence means incomplete.

## 4. Apply, verify, repeat

Only after the dry-run is reviewed and exact scope approved:

<augment_code_snippet path="scripts/recover_recorded_opt_outs.py" mode="EXCERPT">
````bash
uv run python -m scripts.recover_recorded_opt_outs \
  --workspace-id "$RECOVERY_WORKSPACE_ID" --lead-id "$RECOVERY_LEAD_ID" \
  --apply --reviewed-for-lifts --report "$RECOVERY_AUDIT_DIR/apply.jsonl"
````
</augment_code_snippet>

Retain the same hold flags and reviewed history ceiling. Apply re-reads and plans under
the lead row lock and commits per lead. Earlier successful repairs survive an interruption.
There is a possible commit-before-report-write window: if the report fails, stop, retain
the partial file and rerun the **same approved scope** with a new report filename. It will
reconcile already-correct rows without resending/replaying events. Never mark an incomplete
run complete manually, delete history, or remove a hold merely to obtain exit zero.

Controlled cancellation tests against real Postgres cover both rollback/lock release before
commit and a committed-but-unreported repair followed by retry. They do not establish behavior
under host power loss or validate the production containment/restart procedure.

Then execute a permitted CRM refresh with corrected code in the contained rehearsal and
re-read the lead. Verify original restriction evidence, updated CRM fields and unchanged
workflow/enrollment/message/handoff history. Re-run the same apply command with
`repeat.jsonl`: repaired leads should be `already_correct`, not newly changed. If there
was intervening evidence, review it rather than assuming every difference is a defect.

Use the existing lead-detail page's **Decision snapshot**, **SMS automation**, **Email
automation**, **Lead record**, **Handoff context** and **Lead activity** panels for the
stakeholder checks in the PR. Reload/reopen after refresh. Browser access must be provided
through a contained corrected build; do not restore all production writers merely to view
the page. A backend test with an actor override is not authenticated UI acceptance.

## 5. Re-enable or roll back

Keep unresolved scope excluded using approved runtime controls, independently of the CLI
hold list. Before reopening verified scope, confirm every writer uses the corrected image,
queued work rechecks restored restrictions, the unaffected control can still send through
sandbox/sink providers, existing handoffs/pauses remain intact, and callback backlog is
accounted for. Obtain release-owner acceptance. There is deliberately no blanket `start`
or resume/enrollment command here: a completed repair does not authorize more outreach.

If rollback is needed, use the containment command above **before** returning to older
writers. Keep the repaired lead restrictions and original audit history; do not undo
suppression facts or restore permissive flags as a rollback. If the previous version can
erase them, keep affected writers/sending stopped until a compatible correction is ready.
Do not remove database volumes, clear queues, or replay provider sends. Production rollback,
re-enablement, image changes and recovery each need explicit approval and observation.