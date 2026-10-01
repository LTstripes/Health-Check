# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas not committed to a release live in [Backlog Ideas](BACKLOG_IDEAS.md).

## Current state

Released to canonical `main`: R01–R05 plus deterministic Period Brief, durable Owner Runtime, Context Capture v0, Garmin Training/Recovery, source freshness, Owner screenshot workflow and the completed reliability/correction slice.

Repository checkpoint before this operational docs update: `4029fd8c70e5bde0120bdf7902f2016faec118ed`; exact-main CI `36820492189` SUCCESS. Re-read live GitHub main/CI before launch/integration.

Latest completed work:
- #217/#219/#221: screenshot -> repo skill -> strict Owner-assisted extraction -> R01 pipeline -> Stable.
- #203: limited-encoding Period Brief stdout.
- #226: screenshot algorithm/provenance guard.
- #227: coherent SQLite/ORM compound reads.
- #233: collision-safe Garmin Training privacy test oracle.
- #181: Windows cleanup and full-rerun-only CI provenance, including post-main WMI follow-up PR #237.
- #229: reviewable changed-sidecar corrections with signed-zero-stable replay identity.
- #214: accepted automatic/logon selected-stream refresh, Scheduler result 0, complete successful report, all four layers succeeded; one-run duration 19m03.819s.
- #147/#191/#193 source freshness and #199/#206/#207/#212 Google HR performance/reliability remain complete.

#214 completion is not an all-fresh claim: Owner/Google aggregates remain stale solely from intentionally disabled Google HR; #238 now owns explicit collection-policy/freshness alignment. Optional Garmin chronology warnings remain unknown. See [closeout](OWNER_REFRESH_CLOSEOUT_2026-10-01.md).

## Current backlog — 2026-10-01

Eleven open issues after closing #214 and opening #238, excluding pull requests:

| Issue | Current state | Next bounded action |
| --- | --- | --- |
| #215 | Owner input required | One real private Context note and supported read-back; do not fabricate text or require daily notes |
| #238 | New collection-policy/freshness gap | Freeze explicit durable-versus-per-run collection intent, then implement shared-consumer behavior without hiding real stale enabled streams |
| #148 | Durability/security not complete | Define protection/publication/retention and recovery contract; then implementation/review and separate Owner rehearsal |
| #228 | Phase 1 research accepted; implementation parked | Wait for trustworthy event identity; no date/value/fuzzy auto-merge |
| #153 | Optional compatibility | Numeric userId from openScale-sync versus current string receiver; not a Weight prerequisite |
| #172 | Deferred UX follow-up | Coordinate with #189; do not duplicate the redesign |
| #189 | Deferred Owner UI umbrella | Revisit after current operational/durability priorities or explicit Owner reprioritization |
| #167 | Owner-deferred | No history rewrite/visibility change without explicit decision and freeze |
| #126 | Owner/capability decision | Recheck capability before settings changes; preserve manual exact-SHA gate |
| #105 | NOT_ELIGIBLE | No canonical sleep switch until existing device-pair gate is met |
| #210 | Ongoing journal | Record actual model roles/outcomes and Owner-confirmed labels; not a product coding task |

This is a status/priority map, not an automatic Worker queue. #215 Owner-only capture and read-only #238 design can proceed independently. UI remains deferred.

### Operational disposition

Phase A audit did not justify a broad Garmin/all-stream Google rebuild. The identified historical sample-HR gap remains intentionally deferred while Google high-frequency HR is OFF in the local Ops runner. Existing history stays intact; re-enabling/backfill needs an explicit bounded decision.

Other Google streams, fixed wearables sleep, Garmin and Garmin Training remain enabled with the accepted seven-day reconciliation horizon. #214's successful run proves actual automatic selected-stream execution; it does not prove every day, graceful cancellation, continuous execution during sleep or once-per-day deduplication. Earlier interrupted attempts remain interrupted.

The last observed local Owner checkout was `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`. A newer GitHub main is not local deployment. An idle/clean safe update is an Owner operation, not another broad refresh or a license to modify Stable.

Weight is operational through screenshots; #229 adds explicit correction/replay semantics. #153 stays optional. #228 research does not add cross-image dedup. #238 must preserve historical age/coverage and unknown states, not simply set disabled data fresh.

See [Current History](EXECUTION_HISTORY_CURRENT.md), [Owner Refresh](OWNER_REFRESH.md), [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md) and [Model Journal](MODEL_BENCHMARK.md).

## R00 — Final architecture (complete)

Delivered product boundaries, source priorities, local-first Python/FastAPI/SQLite architecture, provenance/canonical/coverage rules, donor/license audit and first implementation contracts.

## R01 — Weight & Body Composition (released)

Delivered local runtime/migrations, Xiaomi historical photo import with confirmation/provenance, openScale/openScale-sync contract, canonical selection/sparse coverage, deterministic Weight/body-composition analytics, local dashboard and safe profile backup/restore.

See [R01 Release Closeout](R01_RELEASE_CLOSEOUT.md).

## R02 — Garmin ingestion and backfill (released)

Delivered protected Owner-assisted session reuse, reviewed read capability/normalization/persistence, typed current/source/observation records, incremental sync/trailing reconciliation, bounded resumable backfill, explicit coverage/checkpoints and completed-rerun idempotency.

Owner gates exposed real-provider convergence defects that synthetic CI had not proven; focused repairs preceded release. See [R02 Release Closeout](R02_RELEASE_CLOSEOUT.md).

## R03 — Garmin analytics and activity comparison (released)

Delivered reviewed metric/time/coverage contracts, immutable evidence manifests, personal baselines/quantiles/trends, activity/cycling comparison, bounded lagged cross-metric associations with explicit direction and no causal claims, read-only Garmin dashboard and populated-database migration hardening. Provider-native scores remain provider-native. R03 is Garmin-only; cross-source comparison belongs to R05.

## R04 — Google Health ingestion (released)

Released from `integration/r04-google-health` through PR #114.

- Google Health API v4 only; no new legacy Fitbit Web API path.
- Web Application OAuth and fixed registered loopback callback; exactly accepted read scopes.
- Windows user-scoped protected auth/session state outside Git.
- Explicit Google source/raw/typed persistence, bounded incremental/backfill/refresh, coverage/checkpoints/request budgets/resume/completed-window skip semantics.
- Privacy-safe structural diagnostics and fail-closed provider-shape handling.
- Owner-live auth, pagination, bounded refresh/backfill and populated-DB integrity proof.

#110 accepts only the live-proven terminal missing-collection/no-token LIST/RECONCILE empty case. Null, non-array and malformed variants remain invalid.

Release candidate `406f4044ffb0d010c64a8635d402016ae916fc5a`; merge `bb5776e98d259cb6256c95bd49d400dc1238af61`; exact-main CI `34768452960` SUCCESS; #80 closed.

See [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md).

## R05 — Garmin / Google wearable agreement and canonical sleep (released)

Released to canonical main; design #97, closeout #106.

```text
source evidence -> pairing / eligibility -> comparable projection
 -> immutable versioned agreement run -> optional canonical-source rule
```

- Sleep uses local wake date and one main overnight session per source/date; naps excluded, ambiguous multiple-main sessions fail closed.
- `fitbit_device`/`device_pair` requires explicit persisted device metadata. Wearable-family and uncertain account cohorts are exploratory and not canonical-switch evidence.
- Manual Google-edited evidence is not strong 42-night evidence.
- Compare only compatible session duration/timing/TIB/stages/WASO. RHR/SpO2 may be agreement-only; HRV/respiration are outside v1 unless explicitly scoped. Scores remain display-only.
- Difference convention is `google - garmin`; N, bias, MAE, RMSE, Bland–Altman limits and robust summaries retain coverage. Association is secondary.
- Exploratory gate: 14 paired nights. Provisional canonical gate: 42 valid device-pair nights across at least six weeks plus coverage/stability.
- Garmin stays canonical until a reviewed versioned per-metric rule is accepted; no automatic source switch from N/correlation/coverage.

Implementation: #100 pairing, #101 projection, #102 immutable runs/replay, #103 statistics/gates, #104 reporting, #105 conditional canonical rule, #106 Owner closeout. R05 closed with exploratory agreement; #105 remains NOT_ELIGIBLE.

See [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md).

## Post-R05 / #119 — deterministic Period Brief v1 (completed)

Deterministic bounded Weight/sleep/activity/data-quality packet, stable result hash, thin API/text/CLI renderers, direct R05 reuse, full bounded activity inventory and honest missing/unavailable/confirmed-empty distinctions. #203 fixes limited-encoding stdout; #227 provides coherent compound reads without changing packet mathematics. No new score or LLM/Telegram delivery.

## Post-R05 Stable Owner Runtime — completed foundation

One persistent private cross-domain profile, supported backup/restore into disposable UAT clones, reproducible exploratory agreement, bounded provider refresh, stabilized Google identity and stale SyncRun recovery are canonical. #214 now adds one successful automatic selected-stream run. #238 remains a distinct collection-intent/freshness contract gap, not a failure of that run.

## Post-R05 Garmin Training & Recovery — completed

Parent #160 closed after #175 bounded discovery, #180 typed persistence and live replay proof, #183 normal refresh composition and #187 read-only Owner view with semantic review/UAT.

No custom Health-Check training/readiness score, medical/coaching claim, VO2 guessing or invented producer attribution. Technical presentation remains deferred to #189.

## Current owner-facing product work

### Source freshness / data quality

#147/#191/#193 delivered provider-call-free shared freshness from persisted facts. Daily wearable streams, event-driven activities, voluntary Weight and optional evidence remain distinct. #238 requires explicit collection intent to be handled consistently without hiding failures or rewriting history.

### Hardware/private Owner gates

#215 is first real private Context note/read-back. #148 requires protection design and implementation acceptance before live off-site rehearsal. #153 remains optional openScale compatibility, not required for screenshots.

### Deferred product presentation

#172 Period Brief-specific UX and #189 whole-product Owner UI remain deferred.

## Engineering maintenance — CI feedback/reliability closeout

#123–#125 and #181 are complete. Historical measured accepted CI time changed from about 5m02s to 2m48s during the earlier maintenance campaign; this is not a promise for current runs. Exact Linux inventory plus focused native Windows DPAPI/startup/HTTP/cleanup proof remain mandatory.

#181 adds fail-closed root/child identity and CreationTime evidence, exact exit-255 grammar and full-rerun-only evidence. The post-main transient-WMI escape was retained and repaired before final green main. No retry-until-green or incompatible-attempt mixing. See [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md) and [Development Process](DEVELOPMENT_PROCESS.md).

#126 remains an Owner/capability decision. Current public visibility does not itself establish protection. No settings/visibility/history changes are authorized by this handoff.

## R06 — Context, Telegram, and read-only AI tools

Low-friction free-text event/exposure capture; typed read-only analytic tools over compact packets; conversational investigation over deterministic results; no unrestricted SQL/raw-series LLM mathematics. Context v0 is accepted, but real Stable adoption #215, Telegram and bounded AI are separate stages.

## R07 — Saved reports and delivery

One deterministic report/evidence model for weekly/month-end/annual reviews, dashboard archive, Telegram/email rendering and delivery audit/retry.

## R08 — Deeper personal analytics and experiments

Event-aligned/matched-control analysis, lagged comparisons/effect sizes with coverage gates, structured n-of-1 experiments; consider Recovery Score only for a demonstrated unmet need.

## R09 — Laboratory, medication, supplement and document data

Original documents outside Git, confirmed structured analytes/units/reference ranges, exposure timelines and longitudinal context without causal overclaiming.

## R10 — Optional advanced work

Timezone/travel semantics, providers/mobile integration, secure remote access/notifications and Obsidian/food-diary integration only for demonstrated needs.

## Release gates that always apply

- No real health data, screenshots, tokens, secrets or databases in Git/CI.
- Every ingestion path is bounded, idempotent and coverage-aware.
- Source values survive canonical selection and reprocessing.
- Derived values identify algorithm/version/input provenance.
- Missing/null/zero/unavailable/unknown remain distinct.
- Device identity needs explicit evidence; donor reuse needs exact-version license review.
- Owner UAT is required when private runtime/provider behavior is part of release truth.
- Main is the only canonical source; exact final checks gate candidate/integration/main promotion. #126's unresolved enforcement is not disguised as a technical control.
