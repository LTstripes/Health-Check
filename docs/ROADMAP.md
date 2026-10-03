# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas not committed to a release live in [Backlog Ideas](BACKLOG_IDEAS.md).

## Current state

Released to canonical `main`: R01–R05 plus deterministic Period Brief, durable Owner Runtime, Context Capture v0, Garmin Training/Recovery, source freshness/collection policy, Owner screenshot workflow and the completed reliability/correction slice.

Repository checkpoint before this closeout update: `0339088c52dcefac93bb372a3a460c12cc4b6152`; exact-main CI `37137153269` SUCCESS. The clean Owner operation checkout was also deployed/read back at this SHA. Re-read live GitHub main/CI before a later launch or integration.

Latest completed work includes:
- #238: explicit reversible collection policy/freshness alignment; disabled Google high-frequency HR is no longer treated as an enabled stale action.
- #148 + #252/#254: practical Google Drive ZIP recovery path and bounded backup capacity; a clean real-profile restore rehearsal passed.
- #251: three existing Linux CI lanes rebalanced by timing without dropping the complete test union.
- #256: Owner filesystem migrated to `D:\HealthCheck`, legacy cleanup reclaimed ~6.64 GiB, canonical workspace rules documented, and a fail-closed seven-day workspace janitor deployed as a daily 12:00 Scheduled Task.
- #181/#229 and the earlier reliability/correction work remain complete.

## Current backlog — 2026-10-03

Fifteen open issues, excluding pull requests:

| Issue | Current state | Next bounded action |
| --- | --- | --- |
| #246 | **Active CI optimization** | Finish Stage A docs-only PR fast path on refreshed post-#259 baseline; independent CI semantic review; Stage B event dedup remains separate |
| #243 | Windows CI investigation | Reproduce/resolve the exit-255 transcript blank-item mismatch without weakening process ownership/cleanup guarantees |
| #242 | Dependency maintenance | Reproduce advisory audit; minimally update urllib3/pytest and preserve CI completeness |
| #244 | Security hardening | Freeze and implement bounded loopback Host/Origin mutation guard; independent security review |
| #247 | Deferred security hardening | Replace non-Windows custom Google cipher with standard AEAD without changing Windows DPAPI or whole-profile threat boundary |
| #248 | CLI technical follow-up | Add explicit Period Brief JSON/text stdout without changing the deterministic packet |
| #240 | Owner screenshot metadata | Add explicit Owner-attested date/source metadata under the existing screenshot-import provenance boundary |
| #153 | Optional compatibility | openScale-sync numeric userId compatibility; not a Weight prerequisite |
| #228 | Research accepted / parked | No cross-image semantic auto-merge until trustworthy event identity exists |
| #189 | Deferred UI umbrella | No implementation during the current technical-maintenance track |
| #172 | Deferred UX follow-up | Coordinate with #189 later; do not duplicate redesign |
| #167 | Owner-deferred privacy/history operation | Requires explicit freeze/decision before any rewrite |
| #126 | Owner/capability decision | Recheck repository protection capability before settings changes |
| #105 | NOT_ELIGIBLE | No canonical sleep switch until the accepted device-pair evidence gate is met |
| #210 | Ongoing model journal | Record actual model roles/outcomes; not a product coding queue |

This is a status map, not an automatic Worker queue. The current technical track prioritizes CI/dependencies/security/runtime/CLI/provenance work; UI remains deferred.

### Operational disposition

The durable Owner runtime is `D:\HealthCheck\stable`; the clean control checkout is `D:\HealthCheck\main`; Owner Ops live in `D:\HealthCheck\ops`; new agent tasks use `D:\HealthCheck\workspaces\<client>\<issue-or-task>`. See [Owner Machine Layout](OWNER_MACHINE_LAYOUT.md).

Google high-frequency sample HR remains intentionally disabled under the accepted explicit collection policy; existing history is preserved and no broad backfill/re-enable is authorized merely to make freshness look green. Other accepted Garmin/Google/Training/wearables-sleep collection remains bounded by the existing operational contracts.

The tested off-site recovery path is a verified ordinary ZIP in the Owner's materialized Google Drive folder plus supported clean restore. Protected age-based publication remains optional rather than required for the Owner workflow.

Workspace cleanup runs daily at 12:00 with a seven-day minimum retention and fail-closed eligibility. Legacy roots such as `D:\Garmin` or old client roots are not in the janitor allowlist and require explicit/manual disposition.

Weight remains operational through screenshots; #229 provides explicit correction/replay semantics. #153 stays optional; #228 remains parked. UI #172/#189 remains deferred while the technical backlog above is active.

See [Current History](EXECUTION_HISTORY_CURRENT.md), [Owner Machine Layout](OWNER_MACHINE_LAYOUT.md), [Owner Refresh](OWNER_REFRESH.md), [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md) and [Model Journal](MODEL_BENCHMARK.md).

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

One persistent private cross-domain profile, supported backup/restore into disposable UAT clones, reproducible exploratory agreement, bounded provider refresh, stabilized Google identity and stale SyncRun recovery are canonical. #214 added successful automatic selected-stream operation; #238 later completed explicit reversible collection-intent/freshness semantics.

## Post-R05 Garmin Training & Recovery — completed

Parent #160 closed after #175 bounded discovery, #180 typed persistence and live replay proof, #183 normal refresh composition and #187 read-only Owner view with semantic review/UAT.

No custom Health-Check training/readiness score, medical/coaching claim, VO2 guessing or invented producer attribution. Technical presentation remains deferred to #189.

## Current owner-facing product work

### Source freshness / data quality

#147/#191/#193 delivered provider-call-free shared freshness from persisted facts. #238 completed explicit collection intent so intentionally disabled streams remain historically truthful/non-actionable without hiding enabled failures or rewriting history.

### Hardware/private Owner gates

#215 completed the first real private Context note/read-back. #148 off-site recovery is complete with a verified Google Drive ZIP and clean restore rehearsal. #153 remains optional openScale compatibility, not required for screenshots.

### Deferred product presentation

#172 Period Brief-specific UX and #189 whole-product Owner UI remain deferred.

## Engineering maintenance — CI feedback/reliability closeout

#123–#125 and #181 are complete. Historical measured accepted CI time changed from about 5m02s to 2m48s during the earlier maintenance campaign; this is not a promise for current runs. Exact Linux inventory plus focused native Windows DPAPI/startup/HTTP/cleanup proof remain mandatory.

#181 adds fail-closed root/child identity and CreationTime evidence, exact exit-255 grammar and full-rerun-only evidence. The post-main transient-WMI escape was retained and repaired before final green main. No retry-until-green or incompatible-attempt mixing. See [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md) and [Development Process](DEVELOPMENT_PROCESS.md).

#126 remains an Owner/capability decision. Current public visibility does not itself establish protection. No settings/visibility/history changes are authorized by this handoff.

## R06 — Context, Telegram, and read-only AI tools

Low-friction free-text event/exposure capture; typed read-only analytic tools over compact packets; conversational investigation over deterministic results; no unrestricted SQL/raw-series LLM mathematics. Context v0 and real Stable adoption #215 are accepted; Telegram and bounded AI remain separate later stages.

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
