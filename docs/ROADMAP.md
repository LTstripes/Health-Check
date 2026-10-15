# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas not committed to a task live in [Backlog Ideas](BACKLOG_IDEAS.md). Issues own detailed contracts; this document owns sequence and dependencies, not another copy of every Worker prompt.

## Current #357 follow-up - 2026-10-15

The source-only daily stress adapter and applicability correction are integrated
([PR #425](https://github.com/LTstripes/Health-Check/pull/425),
[PR #426](https://github.com/LTstripes/Health-Check/pull/426));
[PR #428](https://github.com/LTstripes/Health-Check/pull/428) adds the explicit
Owner-selected Moscow analysis-day policy in backend adapter v3;
[PR #430](https://github.com/LTstripes/Health-Check/pull/430) adds the accepted
explicit arithmetic-mean comparison in v4. Omitting `comparison_method` retains
the strict v2 / explicit Moscow v3 median-mode bodies and hashes; original Garmin
dates/values are preserved. The
[current Wiki receipt](PROJECT_WIKI.md#current-canonical-state) binds accepted
code, review, exact post-main CI and the retained clock-proof limitation.

#357 remains OPEN for a separately authorized single UI surface and proof of
mean-mode saved coverage/readiness on a real copy, followed by Owner UAT. The
earlier real-copy applicability check covered median mode only. Backend
availability does not prove actual 21/28 coverage or authorize Stable/provider
operations, rollout, automatic opt-in or additional technical panels. The older
checkpoint and unrelated backlog rows retain their dated scope.

## Previous checkpoint - 2026-10-12 night closeout

Canonical accepted product is `main 8100b7ae7051af181a6bf3151ce3bc3e1d4c4151`;
[post-main CI 38319794454](https://github.com/LTstripes/Health-Check/actions/runs/38319794454)
SUCCESS. PRs #407–#411 and their exact receipts are indexed once in the
[current Wiki](PROJECT_WIKI.md#current-canonical-state).
Installed Stable is the daytime rollout `aca4b8f65eb276dddb3ae5de718a734afd19f369`,
not the night product SHA. Night rollout and Owner UAT remain pending.

Do not relaunch delivered #375 history, #376 RHR foundation, #380 bounded long
windows, #395 refresh wiring, Comments navigation/timezone, saved-session detail
or Statistics drilldown. #319 max-HR/anaerobic B1 is done; calories are blocked.
The Oct-11 clone checkpoint remains historical UAT evidence, not a current
provider/Stable/performance pass. No assignment or deployment follows from docs.

<a id="current-backlog"></a>
<a id="current-backlog--2026-10-03"></a>
<a id="current-backlog--2026-10-06"></a>

## Current backlog — 2026-10-12 (post #411)

The right column records **next delta**; open issue does not mean delivered stages
need to be repeated. None of these rows launches a Worker, provider call or Stable write.

| Owning issue(s) | Exact next product/evidence slice | Status and dependency |
| --- | --- | --- |
| **#377 — Garmin daily Steps** | Owner UAT of completed-day view and actual latency; retain latest proved post-day acquisition, honest ties/missingness and v1/history | #395 wiring CLOSED/PR #398 delivered; #410 merged. Cooperative elapsed guard is not a hard SQL deadline or final-day guarantee |
| **#392 — Google daily Steps** | Prove exact eligible Google endpoint/type/scopes, units, interval vs daily/count and overlapping sources; then small typed acquisition and stored evidence | No current Google steps production stream; C3 source proof first; no Garmin→Google copy |
| **#393 — Overview resting pulse mean** | Owner decision on minimum eligible days/coverage, precision/rounding and custom windows >400 days, then separately authorize implementation | [Stage A research ACCEPT; Stage B PARKED](https://github.com/LTstripes/Health-Check/issues/393#issuecomment-6115459995); #376 reader/card already merged |
| **#394 — Body Battery interpretation** | Prove direct daily max or honestly distinct saved-sample maximum; never relabel latest snapshot as day peak | Current UI is latest saved snapshot; C3 source meaning gate before UI |
| **#379 — A+ style umbrella** | Remaining scoped style/Owner acceptance only; preserve exact raw values and rows in disclosure | Weight numeric polish and #408 readable dates delivered; do not repeat #375 history or formatting slice |
| **#347 + #342 — Statistics sources** | General per-metric eligible-source discovery/autoselection under its own contract, no pooling | #411 provider-first presentation merged; metadata inventory is not metric eligibility; Sleep-only #342 default remains separate |
| **#294 — Comments** | Durable-profile save/edit/timezone-persistence Owner UAT; Stage B weight-goal Settings deferred | Primary navigation and city/IANA chooser delivered; no repeat UI assignment |
| **#305 + #376 — Data and dated evidence** | Eligible saved metric value/date/age and clone snapshot age adapters | #409 compact status/action and stream disclosure merged; generic evidence dates are not eligible metric dates; #305 stays OPEN |
| **#380 — Statistics history** | 365/CY/YTD already integrated; separately bound all-history request and eligible coverage before implementation | Do not repeat accepted 365/year backend/UI; calories blocked |
| **#319 — Energy/calories** | One authoritative field unit/category/interval/inclusion + separately authorized saved-coverage proof | BLOCKED; existing max-HR/anaerobic B1 already merged; no active+resting addition |
| **#378 / #345 — Activity** | Remaining Owner-led functional discovery and acceptance; no speculative redesign | Detail/A-B and Statistics session drilldown delivered; #408 duration/km follow-up merged |
| **#330 — Owner operations** | Separately authorized night-code rollout and human UAT, including Google #406 live verification | Daytime Stable rollout receipt proves aca4b8f; #407–#411 not installed. Synthetic Google fix is not live recovery |
| **#357 - personal stress baseline** | Verify mean-mode real-copy coverage/readiness and separately authorize one UI surface, then Owner UAT; preserve original Garmin dates/values and explicit policy/source proof | Backend #425/#426, opt-in Moscow policy #428 and arithmetic-mean v4 #430 integrated; legacy v2/v3 retained, mean real-copy/UI/UAT OPEN, no rollout |
| **#348 - later** | Laboratory evidence research on separate Owner direction | Deferred, no unverified health inference |

### Design and data rules for the next wave

- Provider names **Garmin/Google** are Owner-level concepts. Preserved source
  identities (Fitbit device, Google family, Garmin account) are provenance, not
  license to combine duplicate observations. Missing, excluded, unknown, zero
  and currentness remain distinct.
- Unfiltered UI may show **last saved eligible observation from D** even when
  today is empty, always with its true date/age and source. Explicit date windows
  must not silently shift; separate two-source dates never justify a false
  same-window comparison or day-zero claim.
- Weight+body composition uses one longitudinal history table; join by verified
  measurement identity, never just date or coincidental weight. Derived fat+lean
  partition differs from source muscle, and incompatible methods must not make
  continuous synthetic chart lines.
- Context time entry needs one human city/IANA selector. The persisted UTC offset
  is still mandatory for precise instants; date-only has no invented midnight and
  DST ambiguity is resolved explicitly only when it occurs.
- Long-history, Google Steps and Energy metrics require accepted data/semantics gates;
  source/provider collection problems are never silently turned into null/zero
  cells or repaired through an UI change. #341 direct ChatGPT connection is deferred.
- Changes involving `dashboard.css`, `web/pages.py`, source readers or common
  components have one active writer; compatible independent read-only research
  and separated UI slices may proceed in parallel only by explicit assignment.

### Parked and Owner operations

#228 weight-artifact dedup is parked; #167 privacy/history remains Owner-deferred;
#126 repository protection is an administrative decision; #105 canonical Sleep
switch is NOT_ELIGIBLE without its paired device evidence; #270/#271 Dependabot
remain unmerged proposals. #153 openScale and #210 model benchmarking remain
not planned. #341 direct ChatGPT connection remains paused. Do not add model
evidence or performance-comparison logs.

The clean Owner control checkout, durable Stable profile, disposable UAT profile
and Agent workspaces are separate roles ([Owner Machine Layout](OWNER_MACHINE_LAYOUT.md)).
GitHub merges **do not automatically update** Stable, restore providers or make a
UAT clone current. Real data stays outside Git; Owner-local operation/read/write
scope follows [Owner Data Workflow](OWNER_DATA_WORKFLOW.md). The normal Google
high-frequency heart-rate collection flag remains intentionally OFF. Owner screenshot
correction/provenance is handled by #229/#240 (one disputed observed date still
requires its own private review). No runtime/server/backup/provider/scheduler operation
is authorised by editing this roadmap.

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

#317 and delivered #343/#347 source-specific Sleep/Statistics views reuse accepted
account-observation/source rules without altering legacy Compare/Agreement.
Independent display itself is not canonical-switch evidence.
See [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md) and
[Account Sleep Observations](R05_ACCOUNT_SLEEP_OBSERVATIONS.md).

## Post-R05 / #119 — deterministic Period Brief v1 (completed)

Deterministic bounded Weight/sleep/activity/data-quality packet, stable result hash, thin API/text/CLI renderers, direct R05 reuse, full bounded activity inventory and honest missing/unavailable/confirmed-empty distinctions. #203 fixes limited-encoding stdout; #227 coherent compound reads; #248 explicit JSON/text output. #172 UX and #283 backend performance are complete. #328/#334/#333 adapt Overview without changing packet mathematics. The new #341 evidence envelope must not silently change this packet or hash.

## Post-R05 Stable Owner Runtime — completed foundation

One persistent private cross-domain profile, supported backup/restore into disposable UAT clones, reproducible exploratory agreement, bounded provider refresh, stabilized Google identity and stale SyncRun recovery are canonical. #214 proved one automatic selected-stream run; #238 explicit reversible collection intent/freshness. These historical successes do not prove current auth or continuous collection health.

## Post-R05 Garmin Training & Recovery — completed

Parent #160 closed after #175 discovery, #180 typed persistence/live replay, #183 normal refresh composition and #187 read-only Owner view with semantic review/UAT. #345 session detail is now delivered; #346 duplicate summaries remain held for #378 product discovery. No custom recovery score, VO2 guessing, coaching/medical claim or invented producer attribution. #319 has typed max-HR/anaerobic but unresolved calories and separate Owner historical replay.

## Current owner-facing product work

### Source freshness / data quality

#147/#191/#193/#238 provide shared persisted freshness and explicit collection intent. #305 request diagnostics/compact presentation and #295 indexed Google/request-local Overview reads are integrated. The observed source-freshness request completes; #342 accepted historical clone data classification but not current provider recovery. RHR surface eligibility was repaired via #340/#353; #376 latest eligible RHR reader/Overview consumer is delivered, while broader eligible metric value/date/age and clone-age adapters remain open. Keep request performance, collection health, data completeness and human acceptance separate.

### Hardware/private Owner gates

#215 completed the first real private Context note/read-back. #148 off-site recovery is complete with a verified Google Drive ZIP and clean restore rehearsal. #153 is not planned; screenshots remain the Weight workflow. Comments navigation/city-IANA UI is included in the daytime installed Stable `aca4b8f…`; durable save/edit/timezone-persistence Owner UAT remains separate. See the [rollout receipt attribution](PROJECT_WIKI.md#current-canonical-state).

### Owner UI

The A+ visual system and desktop-only scope are approved. Seven primary sections
are Обзор / Вес / Сон / Активность / Статистика / Данные / Комментарии.
`/context` primary navigation and city/IANA timezone input are delivered;
durable save/edit/persistence Owner UAT remains separate. Statistics 7/30,
trailing365, calendar-year/YTD, readable source labels and provider-first
presentation are integrated. General per-metric eligible-source discovery,
all-history and unsupported new fields remain separately gated. See
[Owner UI](OWNER_UI_SHELL.md) for delivered surfaces and remaining limits.

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
