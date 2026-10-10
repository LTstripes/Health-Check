# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas not committed to a task live in [Backlog Ideas](BACKLOG_IDEAS.md). Issues own detailed contracts; this document owns sequence and dependencies, not another copy of every Worker prompt.

## Current state — 2026-10-09

Released foundation in canonical `main`: R01–R05 plus deterministic Period Brief,
durable Owner Runtime, Context Capture v0, Garmin Training/Recovery, source
freshness/collection policy, Owner screenshot workflow and reliability/correction.

The #189 stages 1–7 and #306–#309 UI/UAT wave are historical completed work. The
subsequent A+ wave integrated desktop-only acceptance (#321), approved static
reference (#322), shared shell (#326), real Overview (#328), Sleep v3 (#317),
compact Activity A/B (#318), Activity v4 history (#335), sparse Weight-chart clarity
(#334), compact source attention (#333) and the #295 indexed Google freshness fix.

The [Project Wiki](PROJECT_WIKI.md#current-canonical-state) owns the
dated current engineering-status entry point. This roadmap owns sequence and
dependencies; read live issue/PR receipts for acceptance and remaining gates.

Owner-local activation used a verified disposable **copy of real data**, not
synthetic fixtures. Human UAT #330 is **PARTIAL**, with design and shorter Activity
history liked but data availability, Sleep experience and further functionality
still requiring work. The observed freshness request completes; that does not
prove provider recovery. Real-clone Overview remains slow. Exact integration,
latency/classification and UAT evidence are in [Current History](EXECUTION_HISTORY_CURRENT.md).
The [2026-10-06 handoff](OWNER_UAT_FOLLOWUP_2026-10-06.md) is historical, not an active queue.

<a id="current-backlog"></a>
<a id="current-backlog--2026-10-03"></a>
<a id="current-backlog--2026-10-06"></a>

## Current backlog — 2026-10-09

### First wave: integrated engineering, pending Owner acceptance

The initial source-diagnosis/Context/export wave is delivered or classified;
it is no longer a queue of new Workers. Private/Stable and human gates remain.

| Priority / issue | Accepted state | Smallest next gate |
| --- | --- | --- |
| **P1 #342 — source availability** | Offline real-clone Phase A/B classification ACCEPT; stored Google sleep exists, but exact-date and Compare cohort gates affect visibility | Trusted clone-origin and selected-date coverage notice; fresh provider auth/sync only by separate Owner authorization |
| **#294 Stage A — Context UI** | MERGED: original dated/optional-time notes, list/revise/history, secondary `/context` | Durable Owner-profile UAT; weight-goal Settings Stage B remains deferred |
| **#341 — health-chat evidence** | Standalone export and bounded read-only MCP endpoint integrated | Current private/connection gates live in #341; direct ChatGPT connection is deferred |

Research/diagnosis does not prove a current provider failure, data refresh or
app read bug; #342's full fresh DB integrity after cutoff is still UNVERIFIED.
No filter weakening, fabricated Google vendor score or automatic recovery.
See [#342 Integrator decision](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6087155625).
Garmin RHR projection was repaired in #353; later Owner acceptance stays with #340/#330.

A later `Поделиться данными для разбора` UI may reuse #341's accepted
interface, but the first private export and explicit Owner sharing come first.
ChatGPT direct read requires proven authenticated transport and permissions;
a local skill alone cannot access the Owner PC. Further #343–#348 implementation
requires its own assignment. Telegram is optional.

### Existing data, performance and Owner gates

| Issue | Current disposition |
| --- | --- |
| #295 | OPEN: indexed Google freshness optimization delivered, but new-code real-clone /brief is still slow; diagnose the remaining measured hot path before new caching/index changes |
| #305 | OPEN: request failure classification/import UI delivered; latest endpoint and human screen response progress do not establish healthy provider collection or complete Data acceptance |
| #333 | Source-attention engineering integrated; human visual follow-up and missingness tracked with #330/#342, RHR-specific repair in #340 |
| #340 | Stored RHR projection repair integrated (#353); Owner acceptance does not establish provider recovery |
| #319 | Evidence prerequisite for calories, max HR and distinct aerobic/anaerobic effects; new metrics cannot be inferred from requested cards |
| #330 | Consolidated real Owner UAT PARTIAL; preserve positive findings and unresolved per-screen/data/performance outcomes |

### Planned product slices after the first functional wave

| Issue | Planned result | Dependency / meaning boundary |
| --- | --- | --- |
| #343 | Primary Sleep 7/30-day Garmin+Google history, source toggles and point detail; Compare secondary | Independent source observations do not require accepted Agreement pairs; bounded range adapter retains source/role/ambiguity rules |
| #344 | Thin honest Weight connectors, useful intermediate Sleep ticks and quieter Overview freshness detail | No invented observations, EWMA change, lost source warning or extra costly page reads |
| #345 | One saved-activity detail view with useful metric cards | Existing duration/distance/average HR first; optional new fields use #319 |
| #346 | Meaningful weekly/monthly Training/Recovery cards beside the dated native snapshot | Define aggregate meaning/count/coverage first; no averaging categorical status or summing overlapping rolling loads |
| #347 | **Statistics: left-source/right-source columns, both visible by default** for steps, activity, distance, energy and sleep | Source-labelled periods/units/denominators; optional right-minus-left delta only when compatible; no pooling or combined total; reuse aggregates in Activity/Overview/chat |
| #348 | First laboratory-document upload → candidates → Owner confirmation → preserved original/results slice | R09 contract first, exact labels/units/report ranges/sample dates and revision/replay identity; no diagnostic inference |
| #294 Stage B | Durable weight-goal settings | Later than comments; narrow storage/migration only if needed |

For #347, incompatible windows or a missing side do not hide the other source.
Both columns remain useful with explicit coverage/absence; no Agreement gate is
required just to juxtapose independent values. A numeric difference is a separate
compatibility claim. Multiple identities need explicit source selection, not just
brand-labelled pooling. UI implementations are sequenced by actual shared files,
not all launched in parallel because branches differ.

### Parked / administrative work

- #228: artifact replay vs semantic weigh-in identity research accepted; no cross-image auto-merge without trustworthy event proof.
- #167: Owner-deferred privacy/history operation; explicit freeze/decision before rewriting history.
- #126: Owner/admin protection capability and enforcement decision; no billing/settings change implied.
- #105: NOT_ELIGIBLE for canonical sleep switching until its existing device-pair evidence gates are met.
- Dependabot #270/#271: independent review proposals, not housekeeping merges.

#317/#318/#321/#322/#326/#328/#334/#335 delivered engineering is not restarted by
new UI requirements. #295 was previously closed as not planned and then reopened
after new real latency evidence; the old closure is historical, not current.
#298 Stress diagnosis, #153 optional openScale work and #210 model bookkeeping
remain not-planned dispositions. GitHub owns exact live issue counts/statuses.

### Operational disposition

The durable Owner runtime is `D:\HealthCheck\stable`; clean control checkout is
`D:\HealthCheck\main`; Ops are `D:\HealthCheck\ops`; disposable UAT profiles are
under `D:\HealthCheck\uat`. Agent task workspaces are separate. See
[Owner Machine Layout](OWNER_MACHINE_LAYOUT.md).

A cloned real profile is a snapshot, not a demonstration and not automatically
updated Stable. Stored collection errors may be snapshot history. Updating code
alone cannot recover unavailable provider data. Routine comments must eventually
be written to the explicitly selected durable profile; UAT notes do not migrate
themselves. No local restart, backup, restore, provider call or scheduler change is
authorized merely by this roadmap update.

Google high-frequency sample HR remains intentionally disabled under explicit
collection policy; retained history is preserved. Do not broadly backfill/re-enable
it merely to make status green. Other collection remains bounded by existing
operational contracts.

The practical off-site recovery path is a verified ordinary ZIP in the Owner's
materialized Google Drive folder plus supported clean restore. Protected age-based
publication remains optional. Workspace cleanup runs daily at 12:00 with a
seven-day minimum retention and fail-closed eligibility; legacy roots are outside
the janitor allowlist and require explicit disposition.

Weight remains operational through screenshots. #229 preserves explicit
correction/replay, #240 metadata origins and date-only Owner attestation; #153 is
not planned and #228 parked. An unconfigured browser extractor is not failure of
the accepted screenshot-skill path. See [Owner UI](OWNER_UI_SHELL.md),
[Owner Refresh](OWNER_REFRESH.md) and [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md).

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

- Legacy comparison pairs sleep by local wake date and one eligible main overnight session per source/date; naps/ambiguous mains are excluded.
- `fitbit_device`/`device_pair` requires explicit persisted device metadata. Wearable-family and uncertain account cohorts are exploratory and not canonical-switch evidence.
- Manual Google-edited evidence is not strong 42-night evidence.
- Compare only compatible session duration/timing/TIB/stages/WASO. RHR/SpO2 may be agreement-only; HRV/respiration are outside v1 unless explicitly scoped. Scores remain display-only.
- Difference convention is `google - garmin`; N, bias, MAE, RMSE, Bland–Altman limits and robust summaries retain coverage. Association is secondary.
- Exploratory gate: 14 paired nights. Provisional canonical gate: 42 valid device-pair nights across at least six weeks plus coverage/stability.
- Garmin stays canonical until a reviewed versioned per-metric rule is accepted; no automatic source switch from N/correlation/coverage.

Implementation: #100 pairing, #101 projection, #102 immutable runs/replay, #103 statistics/gates, #104 reporting, #105 conditional canonical rule, #106 Owner closeout. R05 closed with exploratory agreement; #105 remains NOT_ELIGIBLE.

#317 later reuses accepted account-observation source/role rules for unpaired
source-only display without altering legacy Compare/Agreement. Planned #343 and
#347 independent source views likewise are not canonical-switch evidence.
See [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md) and
[Account Sleep Observations](R05_ACCOUNT_SLEEP_OBSERVATIONS.md).

## Post-R05 / #119 — deterministic Period Brief v1 (completed)

Deterministic bounded Weight/sleep/activity/data-quality packet, stable result hash, thin API/text/CLI renderers, direct R05 reuse, full bounded activity inventory and honest missing/unavailable/confirmed-empty distinctions. #203 fixes limited-encoding stdout; #227 coherent compound reads; #248 explicit JSON/text output. #172 UX and #283 backend performance are complete. #328/#334/#333 adapt Overview without changing packet mathematics. The new #341 evidence envelope must not silently change this packet or hash.

## Post-R05 Stable Owner Runtime — completed foundation

One persistent private cross-domain profile, supported backup/restore into disposable UAT clones, reproducible exploratory agreement, bounded provider refresh, stabilized Google identity and stale SyncRun recovery are canonical. #214 proved one automatic selected-stream run; #238 explicit reversible collection intent/freshness. These historical successes do not prove current auth or continuous collection health.

## Post-R05 Garmin Training & Recovery — completed

Parent #160 closed after #175 discovery, #180 typed persistence/live replay, #183 normal refresh composition and #187 read-only Owner view with semantic review/UAT. No custom recovery score, VO2 guessing, coaching/medical claim or invented producer attribution. New presentation is #345/#346; additional field evidence remains #319.

## Current owner-facing product work

### Source freshness / data quality

#147/#191/#193/#238 provide shared persisted freshness and explicit collection intent. #305 request diagnostics and #295 indexed Google reads are integrated. The observed source-freshness request completes; #342 accepted historical clone data classification but not current provider recovery. RHR surface eligibility remains #340. Keep request performance, collection health, data completeness and human acceptance separate.

### Hardware/private Owner gates

#215 completed the first real private Context note/read-back. #148 off-site recovery is complete with a verified Google Drive ZIP and clean restore rehearsal. #153 is not planned; screenshots remain the Weight workflow. New Context routine use requires an explicit durable-profile rollout after its UI is accepted.

### Owner UI

The A+ visual system and desktop-only scope are approved. Five main sections are
Обзор / Вес / Сон / Активность / Данные. Context `/context` is a shipped secondary
entry awaiting durable Owner UAT; Statistics is planned, not yet shipped.
The Owner likes the style and requests functionality first. See
[Owner UI](OWNER_UI_SHELL.md) for current versus planned behavior.

## Engineering maintenance — CI feedback/reliability closeout

#123–#125 and #181 are complete. Historical measured accepted CI time changed from about 5m02s to 2m48s during an earlier campaign; this is not a promise for current runs. Exact Linux inventory plus focused native Windows DPAPI/startup/HTTP/cleanup proof remain mandatory.

#181 adds fail-closed root/child identity and CreationTime evidence, exact exit-255 grammar and full-rerun-only evidence. The post-main transient-WMI escape was repaired before final green main. No retry-until-green or incompatible-attempt mixing. See [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md) and [Development Process](DEVELOPMENT_PROCESS.md).

#251 lane balance, #246 docs-route/event dedup, #242 dependency security, #243 Windows transcript, #244 Host/Origin and #302 deterministic Linux environment are complete. #126 remains an Owner/capability decision; no settings/visibility/history change is authorized by this plan.

## R06 — Context and read-only conversational evidence

Context v0 and historical Stable proof #215 are accepted. **Portal comments #294 Stage A** and **standalone health + Context evidence #341 Stage A** are merged into GitHub main. Durable Owner UAT and first real private export remain UNVERIFIED; in-app sharing and authenticated direct ChatGPT access are future scoped steps, not shipped. Telegram remains optional; no unrestricted SQL, LLM raw-series arithmetic or provider actions. R06 as a whole is not yet declared released.

## R07 — Saved reports and delivery

One deterministic report/evidence model for weekly/month-end/annual reviews, dashboard archive, selected chat/Telegram/email rendering and delivery audit/retry. Transport/scheduling remains future scoped work.

## R08 — Deeper personal analytics and experiments

Event-aligned/matched-control analysis, lagged comparisons/effect sizes with coverage gates, structured n-of-1 experiments; consider Recovery Score only for a demonstrated unmet need. Descriptive #346/#347 summaries must not silently become causal experiments or proprietary-score arithmetic.

## R09 — Laboratory, medication, supplement and document data

**#348 now owns the first planned lab-document contract:** original PDF/image outside Git, extraction candidates, explicit confirmation, original analyte/units/report ranges/sample dates and traceable corrections. It is not yet implemented and does not pull the whole medication/supplement roadmap into the first slice. Lab-derived interpretation remains bounded decision support, not diagnosis.

## R10 — Optional advanced work

Timezone/travel extensions, provider/mobile integration, secure remote access/notifications and Obsidian/food-diary integration only for demonstrated needs. Current desktop-only scope is unchanged; #341's bounded read connection is not public exposure of the full portal.

## Release gates that always apply

- No real health data, screenshots, tokens, secrets or databases in Git/CI.
- Every ingestion path is bounded, idempotent and coverage-aware.
- Source values survive canonical selection and reprocessing.
- Derived values identify algorithm/version/input provenance.
- Missing/null/zero/unavailable/unknown remain distinct.
- Device identity needs explicit evidence; donor reuse needs exact-version license review.
- Owner UAT is required when private runtime/provider behavior is part of release truth.
- Main is the only canonical source; exact final checks gate candidate/integration/main promotion. #126's unresolved enforcement is not disguised as a technical control.
