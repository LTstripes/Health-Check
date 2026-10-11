# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas not committed to a task live in [Backlog Ideas](BACKLOG_IDEAS.md). Issues own detailed contracts; this document owns sequence and dependencies, not another copy of every Worker prompt.

## Current state — 2026-10-11

Canonical engineering `main f0e6c36c4d10f03069111665f10201575ee6ea0e`
has [full post-main CI 38070804783](https://github.com/LTstripes/Health-Check/actions/runs/38070804783)
**SUCCESS** (quality, three Linux lanes, Windows, final checks).
R01–R05, the A+ desktop Owner UI and the whole accepted #343/#358/#347/#295/#345/#344
package are integrated. The most recent increments are Sleep source timelines
[#368](https://github.com/LTstripes/Health-Check/pull/368), multidomain synthetic
demo [#369](https://github.com/LTstripes/Health-Check/pull/369),
acceptance parity [#370/#371](https://github.com/LTstripes/Health-Check/pull/370),
request-local /brief reads [#372](https://github.com/LTstripes/Health-Check/pull/372),
Activity detail [#373](https://github.com/LTstripes/Health-Check/pull/373) and
Overview readability [#374](https://github.com/LTstripes/Health-Check/pull/374).
Do not restart their completed implementation stages.

**Human Owner UAT #330 is PARTIAL**, not an engineering or live-provider failure.
Owner personally reviewed code on a verified disposable copy of real data
(snapshot as of 2026-10-08). A+ look, Sleep 7/30 history and working Activity detail
were positively assessed; perceived navigation speed improved. Real `/brief`
first visit exceeded 30 seconds while repeat was about 14 seconds, so cold speed
is not proven. The snapshot does not establish current Stable/provider freshness;
new durable Context writes, fresh full-DB integrity and release to Stable are
separate gates. [Owner decision/feedback](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6106537913),
[Current History](EXECUTION_HISTORY_CURRENT.md), and [Project Wiki](PROJECT_WIKI.md#current-canonical-state)
are the dated status entry points.

<a id="current-backlog"></a>
<a id="current-backlog--2026-10-03"></a>
<a id="current-backlog--2026-10-06"></a>

## Current backlog — 2026-10-11

New requests are **scoped follow-ups**, not permission to relaunch completed
engineering, run providers, write Stable or start a Worker automatically.

| Order / owning issue | Smallest next output | Dependencies / status |
| --- | --- | --- |
| **P1 #342 / #343 / #347 — Google source meaning** | Read-only exact-source coverage/overlap inventory; choose an evidence-backed **two-provider** Garmin/Google everyday display contract | Existing B1/R05 semantics preserved; no automatic Fitbit+family merge; #343 chart already delivered |
| **#375 — Weight composition** | One dated full-history Weight+composition table; one metric-selectable chart with distinct incompatible method segments | C2 UI, no formula/replay change; coordinate CSS with #379 |
| **#376 — latest available values** | Last eligible saved value + date/age when no observation today; explicit requested date/period remains exact | Phase A source selection/coverage contract before shared UI; past value never labelled current |
| **#294 — Comments UI** | Promote 'Комментарии' to primary navigation; city/IANA zone select derives internal offset, retains date-only and DST correctness | Stage A CRUD already merged; no durable Owner-profile write without release/UAT authority |
| **#347 — Statistics usability** | Human source labels, evidence-backed useful Garmin/Google default and honest empty states; no silent multi-device pooling | Depends on #342 source classification, #376 date behaviour |
| **#380 — Statistics longer windows** | Accepted bounded trailing-365/calendar-year/all-history aggregate contract, later selector | Reuse #347; source-specific coverage, performance and fail-closed required |
| **#377 — Steps** | Source/coverage/units research, then approved typed daily steps import/projection and display | No producer inference; C3 ingestion; #347 consumer later |
| **#319 — Calories / energy** | Resolve `calories` vs `bmrCalories`, units and activity/active/total scopes before typed source/UI | maxHR and anaerobic B1 already merged, no repeat/historical replay by default |
| **#305 — Data** | Stored last-eligible dates/coverage separate from clone/provider refresh/reauth/failure state; one readable provider action | Use #376/#342; no automatic refresh |
| **#379 — A+ consistency** | Review forms/tables/style drift application-wide, then small nonoverlapping presentation slices | Frozen 1024/1440 A+ tokens, no new design system |
| **#378 / #346 — Activity research** | Owner-requested product discovery for genuinely useful activity analytics, not redundant summary cards | #345 session detail works; product choice before implementation |
| **#357 / #348** | Later stress personal baseline and laboratory document contract | Deferred; no premature health inference |

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
- Long-history and new Steps/Energy metrics require accepted data/semantics gates;
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
