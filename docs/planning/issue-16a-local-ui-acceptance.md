# Issue 16-A — local sink-only UI acceptance

Date: **2026-09-10**. The separately approved frontend correction and **agent-run local acceptance
now pass**. All 12 refused actions display truthful feedback; no opted-out channel sent. Two clean
controls remain untouched for independent stakeholder testing. This is not stakeholder or release approval.

## Authorization and access

The user answered **“yes please”** to preparing a local, sink-only UI acceptance environment with
synthetic data and no live-provider calls. This authorizes the preparation/rehearsal described here,
not publication, CI setup, deployment, production recovery or re-enablement. Subsequently, the user
approved the frontend-only correction: **“please. but first checkout to same name branch on frontend
as well”**. The frontend was switched to **16A-preserve-opt-outs** before editing, matching the API.
The owner remains the sole release/recovery operator. All corrected application work stays unstaged.

- Open **[the local application](http://127.0.0.1:4173)** on the same Mac as this workspace.
  There is no public tunnel or staging deployment; the URL is not reachable from another machine.
- Use the real sign-in form. Read `signin.json` privately with Finder/a local editor in the
  [ignored local harness directory](/Users/sivvi/Documents/repos/miller-schackman/miller-schackman-api/tmp/issue16a-ui-acceptance).
  It contains only the synthetic admin's credentials; do not paste it into chat, logs or VFS.
  Directory permissions are 0700 and private JSON files are 0600. No auth bypass was installed.
- The workspace is **Issue 16-A — SYNTHETIC / SINK ONLY**. Navigate to **Leads**, open a row's
  contextual drawer, then its full record. Names below all end in **— Synthetic**.
- API: loopback port **8016**. Synthetic FUB HTTP service: loopback port **8017**.
  Web/API/stub each returned HTTP 200 at final handoff; authenticated reads verified all 16 leads.

## Isolation and operating limits

- An isolated, migrated database on the existing local Postgres instance (port 55432) uses a new
  restricted runtime role: no superuser or RLS bypass. The ordinary application database is untouched.
- API, web, CRM stub and acceptance commands run under `loopback.sb`; a reserved non-loopback
  connection must fail with OS permission denial before execution. Browser routing also permits
  only the local web/API ports. No external request was observed in the completed browser run.
- Runtime runners clear ambient configuration and do not load repository dotenv files. SMS and
  email use the existing **sink** adapters; FUB points to the synthetic server. External provider
  credentials are not passed to the application. No real customer or provider delivery is claimed.
- No Temporal worker, outbox publisher, CRM sync worker or scheduler is running for this cohort.
  Temporal/LLM/queue/cache targets are intentionally disabled. Quiet hours are disabled only for
  this synthetic workspace, to isolate consent checks from wall-clock timing.
- **Do not** enable providers/workers, change integrations, resume, enroll, clear restrictions, or
  use **Import FUB history** / agent-directory **Sync now** as a substitute for the prepared refresh.
  These are not approved acceptance actions. There is no lead-level refresh or recovery UI button.
- Manual-start options are unavailable: their GET dependency eagerly connects to Temporal.
  A targeted authenticated probe returned HTTP 500; secret-safe traceback locations identified
  `lead_manual_enrollment.py` → `build_temporal_workflow_starter` → `connect_temporal_client`.
  This explains a reproduced server RuntimeError, not a consent failure. No fake success response,
  dependency override or worker was added to hide it. Manual-start/resume execution is not tested.

## Prepared cohort

| Visible name, excluding the Synthetic suffix | Current expectation |
| --- | --- |
| Recorded SMS Opt Out | SMS blocked; email sendable; original platform evidence retained |
| Recorded Email Unsubscribe | Email blocked; SMS sendable; original evidence retained |
| Recorded DNC SMS / Recorded DNC Email | Both channels blocked; separate parked SMS/email messages |
| Recovered SMS Opt Out / Recovered Email Unsubscribe / Recovered Do Not Contact | Historical restriction and original source/event/time restored; correct channel scope |
| Paused Lifecycle Control / Human Handoff Control | Remain paused / human_handoff; handoff context retained; no resume or send |
| Completed Lifecycle Control / Suppressed Lifecycle Control / Closed Lifecycle Control | Remain in their terminal states; no restart or send |
| Clean SMS Control / Clean Email Control | Already exercised once against sinks; one sent record each, now waiting_for_response |
| Stakeholder Clean SMS / Stakeholder Clean Email | **Untouched**, one valid deferred pending message each; reserved for the owner's first send |

## Original preparation and first browser run — historical

The browser/API journey used real application authentication and persistence; recovery used the
actual CLI and repositories. The CRM transport was synthetic and messaging used local sinks.
There were no application dependency overrides. Helper unit tests separately exercised pure harness logic.

| Check | Actual result |
| --- | --- |
| Runtime helper unit tests and web-runner syntax | **23 tests passed**, exit 0; `node --check` exit 0 |
| Authentication / reads | Real password sign-in; unauthenticated lead list HTTP 401; authenticated list and 16 details passed |
| Recovery through actual CLI subprocesses | Preview: 8 would-change, 4 already-correct, 4 clean. Apply: 8 changed. Repeat: 0 changed, 12 already-correct, 4 clean. All three CLI runs exit 0 |
| Real FUB adapter against local HTTP stub | 32 stale refreshes, 16 missing responses, 16 failures and 1 transport timeout; restrictions/provenance retained; ordinary fields update on successful refresh |
| Preparation side effects | Snapshots of 10 populated lifecycle/history tables unchanged through recovery/refresh/repeat; **zero sends during preparation** |
| Browser journey | Real Chromium sign-in → 16 list rows → keyboard drawer/full-record navigation → all channel panels and reload durability |
| Viewports | Desktop 1440×1000, tablet 768×1024, mobile 390×844; sampled channel panels readable and no document-level horizontal overflow |
| Refused Send now actions | 7 consent-blocked results (`send_rejected`) and 5 inactive-workflow results (`not_actionable`). Persisted histories unchanged; provider status not_attempted. **All 12 showed false success** |
| Permitted controls | Clean SMS/email accepted by sinks once each across the browser runs. Replays returned already_sent without a second record or further advancement. No previously sent control was reset or re-sent |
| Confirmation | Reason required; cancel left message/lifecycle state unchanged |
| Completed browser run | 20260910T105403279646Z: 14 outcomes, 12 UI findings; 0 page errors and 0 HTTP errors in that run's requested routes. Final assertion intentionally returned **exit 1**, not acceptance success |
| Final health/readback after API restart | Web/API/stub HTTP 200; 12 restrictions retained, 2 persisted sink sends, 2 untouched stakeholder controls; exit 0; no additional send requests |

The completed run contains one clean-control `already_sent` replay and one new `sent` result; SMS
was exercised in the earlier pass. Earlier harness runs failed on navigation timing/selectors and
a provider-status expectation (`accepted`, not `sent`); only harness expectations were corrected.
An invalid synthetic handoff enum was also corrected before the completed preparation. Application
assertions were not weakened to hide the UI defect. The later manual-start HTTP 500 probe above is
separate from the completed browser run; this record does not claim that all API routes are healthy.

Private reports remain in the ignored harness directory (`preparation-result.json`, bounded recovery
JSONL reports, and `browser-result-20260910T105403279646Z.json`). Do not publish runtime/sign-in files.
Synthetic screenshots: [desktop decision panel](https://cosmos.augmentcode.com/files/20260910t105403279646z-desktop-decision-0a87dd966fd2477ab72e08a1ceefa306),
[mobile decision panel](https://cosmos.augmentcode.com/files/20260910t105403279646z-mobile-decision-a92a9870572a4fd28540552cc1070b16),
[false-success toast](https://cosmos.augmentcode.com/files/20260910t105403279646z-blocked-send-toast-beb84f798eda49728a9031d38f5ac5d1).

## Approved frontend correction and current revalidation

The original defect confused HTTP 200 with a successful send: `LeadDetailPage` supplied unconditional
success metadata and closed its dialog for semantic refusals. The approved approach keeps the API
contract and existing notification system, rather than broadening the backend error contract.

- `sent` confirms provider acceptance, not delivery; `already_sent` explicitly reports no duplicate.
  Refused/inactive sends show their actual reasons; uncertain/error outcomes advise checking status
  before retrying. The shared generic success toast is suppressed only for this mutation.
- Refusal/error leaves the dialog and reason intact. A transient failed status refresh retains the
  warning and disables sending until readback succeeds. HTTP 401/403/404 still removes the cached
  lead surface; malformed/unreadable HTTP error bodies now preserve `ApiError.status`.
- Sending is disabled offline, while a send is pending, or while readback is fetching/paused.
  Send mutations neither retry automatically nor queue for reconnection. A lost connection during
  readback does not hide the completed send attempt's outcome behind an indefinite Sending label.
- No consent, fallback, workflow, provider, API response schema, dependency or release-policy change.

| Current check | Actual result |
| --- | --- |
| Frontend lint, typecheck and formatting | `pnpm check`: all pass; exit 0 |
| Full frontend tests | **156 passed, 1 existing skipped**, 23 files; exit 0, 62.69s. Includes 46 lead-route and 7 API-client cases |
| Production build | `pnpm build`: exit 0; existing large-chunk warning remains, not a build failure |
| Local helper unit tests | **23 passed**, exit 0 |
| Authenticated browser | Complete run **20260910T174712060438Z**, exit 0: real login/list/drawer, all 16 detail/reload checks, 7 consent refusals, 5 inactive-workflow refusals, 2 already-sent API replays |
| Notifications and layout | All 12 browser-confirmed refusals have exact truthful title/type/reason and retained inline feedback. Desktop/tablet/mobile and dark-mode dialog checks pass |
| Fault/reconnection | One intentionally aborted POST and two aborted readbacks; warning/reason persist, read-only recovery succeeds. Actual Chromium offline/online events disable confirmation and never queue a send |
| Side effects and errors | **13 browser POST attempts:** 12 real refusals, 1 aborted before reaching the API. Histories/guards preserved; 0 UI findings, 0 page errors, 0 nonlocal requests, 0 HTTP errors in this run; stakeholder controls untouched |
| Independent closeout | `issue16a-final-offline-closeout`: no actionable defects; static review only, not runtime execution or release approval |

The skipped test is the pre-existing `AdminOperationsRoutes.test.tsx` outbound-drafting save/preview
case; it is also skipped at frontend HEAD. No test was newly skipped or weakened. Fresh `sent` and
UI `already_sent` outcomes are exercised through the real App route/notification provider in frontend
tests. The browser rerun deliberately does not reset previously sent controls or consume the reserved
stakeholder controls, so it is not a new clean-send/provider-delivery test.

Two earlier final-validation attempts stopped at the closed-lead toast assertion; the isolated case
and subsequent complete run passed. The harness now inspects the short-lived notification before
waiting for background network-idle, retaining exact title/type/count assertions. Failed reports are
retained and are not counted as passes. No application behavior was changed to bypass that assertion.

Run frontend commands with the supported Node 20.19.5 binary on PATH. Browser execution must retain
the OS loopback sandbox and private synthetic runtime:

<augment_code_snippet mode="EXCERPT">
````bash
export PATH="/usr/local/Cellar/node@20/20.19.5/bin:$PATH"
pnpm check && pnpm build
# From the API repository:
/usr/bin/sandbox-exec -f tmp/issue16a-ui-acceptance/loopback.sb /usr/local/bin/python3 -B tmp/issue16a-ui-acceptance/inspect_browser.py
````
</augment_code_snippet>

Current synthetic screenshots: [desktop](https://cosmos.augmentcode.com/files/20260910t174712060438z-desktop-corrected-send-feedback-1595625a3581426c94f71223f5a4dad7),
[tablet](https://cosmos.augmentcode.com/files/20260910t174712060438z-tablet-corrected-send-feedback-fc620ef9e79b4c5397716d613abe463d),
[mobile](https://cosmos.augmentcode.com/files/20260910t174712060438z-mobile-corrected-send-feedback-dc9b379edb734f33850b9e76437944eb),
[dark mode](https://cosmos.augmentcode.com/files/20260910t174712060438z-desktop-dark-corrected-send-feedback-3bab6c025651436bb81945b4eeb4cbe5),
[failed readback](https://cosmos.augmentcode.com/files/20260910t174712060438z-mobile-readback-failure-712ab189aff147958b3691c680557d44),
[offline guard](https://cosmos.augmentcode.com/files/20260910t174712060438z-mobile-offline-send-guard-112398e5564643ecba962a6542d784d3).

## Stakeholder checklist — independent check remains open

- [ ] Open the prepared SMS/email/DNC and recovered records; verify channel-specific reasons under
  **Decision snapshot**, ordinary refreshed fields under **Lead record**, then reload.
- [ ] Verify paused/handoff/terminal states and histories are unchanged by repair/refresh.
- [ ] Independently confirm blocked Send now reports refusal, not success, and
  **Lead activity** contains no successful blocked-channel send. Do not clear consent to proceed.
- [ ] Use **Stakeholder Clean SMS** and **Stakeholder Clean Email** once each: enter a test Reason,
  confirm Send now, then reload. Expect one sink-accepted sent message; no duplicate action/advance.
- [ ] Record independent owner acceptance. Agent-run checks and screenshots are not owner sign-off.

## Runtime lifecycle and source integrity

The three servers are left running for local inspection; this is session-managed, not a persistent
deployment. Stopping them does not delete the database or private files. A restart loses in-memory
sink/stub logs, not persisted send/idempotency evidence. Do not reseed or erase records to rerun sends.

If processes have stopped, a developer can restart the existing prepared environment from the API
repository, one terminal per command, with the original loopback sandbox. Never invoke bare runners:

<augment_code_snippet mode="EXCERPT">
````bash
/usr/bin/sandbox-exec -f tmp/issue16a-ui-acceptance/loopback.sb /usr/bin/arch -arm64 .venv/bin/python -B tmp/issue16a-ui-acceptance/service.py
/usr/bin/sandbox-exec -f tmp/issue16a-ui-acceptance/loopback.sb /usr/bin/arch -arm64 .venv/bin/python -B tmp/issue16a-ui-acceptance/run_api.py
/usr/bin/sandbox-exec -f tmp/issue16a-ui-acceptance/loopback.sb node tmp/issue16a-ui-acceptance/run_web.mjs
````
</augment_code_snippet>

Bootstrap, seed and first preparation are one-shot and refuse to overwrite their existing artifacts.
Further bounded recovery must use the guarded local wrapper and a fresh private report, never the
production configuration. No database/role/file cleanup was performed; cleanup needs an explicitly
verified exact target and separate authorization. Do not stop the shared Postgres/Compose stack.

Backend application source stayed identical to the tested **733-file** aggregate
`4852b99a7c7b180509f936c42737a47f8a32fe4eba16b22bb31563865a0dc4b9`.
API HEAD is `f5dbf4e679810f6dc558acb7bee3645eb748a2ca`; frontend HEAD remains
`04d43619d7beaf77799871eb9f985b60d5bb8fe5` with four unstaged changed/new files:
`src/pages/LeadDetailPage.tsx`, `src/app/LeadsRoutes.test.tsx`, `src/lib/api/client.ts`,
`src/lib/api/client.test.ts`. Their combined SHA256 is
`fbd7ff5adcb5b4dcf5b00eacc1315bcb14bb7bf648f1c8e8cd54d85b43452a81` using the remediation document's
relative Path ordering and path-NUL-content-NUL recipe over exactly those four files.
Both branches are `16A-preserve-opt-outs`; neither index contains staged content. The prior
1841-pass backend suite applies to the unchanged backend aggregate; it was not rerun for this
frontend-only correction. Helpers stay git-ignored and are not a portable committed test environment.
See [remediation evidence](issue-16a-review-remediation-evidence.md) and [handoff](issue-16a-pr-handoff.md).
Independent stakeholder acceptance, safe non-deploying CI, publication and owner-operated
release/recovery remain open. Agent-run local acceptance is complete within the stated sandbox limits.