# Health-Check Roadmap

The roadmap is organized as usable vertical releases. Each release must work locally on Windows, preserve source evidence, and remain reproducible without live provider access in CI.

Future ideas not committed to a release live in [Backlog Ideas](BACKLOG_IDEAS.md).

## Current state

Released foundation in canonical `main`: R01–R05 plus deterministic Period Brief, durable Owner Runtime, Context Capture v0, Garmin Training/Recovery, source freshness/collection policy, Owner screenshot workflow and the completed reliability/correction slice.

The Owner UI redesign **#189 stages 1–7 is integrated and closed**. The 2026-10-06 UAT created #305–#309; the following integration wave and consolidated Owner UAT reached product checkpoint `29cc9fcf53c508fa5f4994e3170e697726c0514c` on 2026-10-07. #306–#309 are complete; #305 retains one real functional timeout. Exact repository/CI evidence and recorded Owner UAT are separated in [Current History](EXECUTION_HISTORY_CURRENT.md). The [2026-10-06 UAT handoff](OWNER_UAT_FOLLOWUP_2026-10-06.md) is historical, not the current execution queue.

Latest completed work includes:
- #305 / PR #311: sanitized freshness failure classes, honest extractor configuration and calmer import history are integrated; this does not close the real Stable timeout.
- #306 / PR #312: responsive human-readable Weight/composition timelines with separate compatibility-group spans.
- #307 / PR #313: source-explicit Overview v2; the Google display window is bounded and disclosed without narrowing long custom Period Brief ranges.
- #308 / PR #314: Sleep v2 Garmin / Google / Compare views, one-row Garmin nightly history and evidence-gated comparisons.
- #309 / PRs #315/#316: Garmin-backed Activity v2, explicit A/B comparison and the real-evidence-backed `tennis_v2` presentation alias; no persisted-code rewrite.
- #240 / PR #273: per-candidate metadata-origin provenance, legacy-safe replay and strict date-only Owner attestation for screenshots.
- #247 / PR #278: non-Windows Google purpose-bound AEAD v2, authenticated legacy reads and write-time-only migration; Windows DPAPI unchanged.
- #248 / PR #276: explicit Period Brief JSON/text stdout with unchanged default output and deterministic packet.
- #172 / #283 / PR #284: Owner-first Period Brief UX plus measured backend reads. Full-size synthetic median 55.108 s -> 6.520 s with equal packets/hashes; no migration, new index or cache. These are synthetic proxy measurements, not exact Owner Stable timings.
- #251/#246/#243/#242/#244 and #302: completed CI lane/dedup/docs-route, Windows transcript, dependency/security, loopback Host/Origin and deterministic Linux-environment maintenance. Detailed rollout evidence remains in the [CI optimization closeout](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md) and current history.
- #274 / PR #277: completed measured NO-GO for the tested sync-fixture optimization; no optimization code retained.
- #148/#238/#256 and earlier durability/runtime maintenance remain complete.

<a id="current-backlog"></a>
<a id="current-backlog--2026-10-03"></a>
<a id="current-backlog--2026-10-06"></a>

## Current backlog — 2026-10-07

Nine open issues at the live read-back, excluding pull requests: five product follow-ups and four parked/deferred/admin-gated items.

| Issue | Current state | Next bounded action |
| --- | --- | --- |
| #305 | OPEN; implementation slice integrated, real UAT timeout reproduced | Diagnose the 15-second persisted-source freshness timeout; no blind timeout increase, provider collection or freshness-policy change |
| #317 | OPEN; Sleep Owner v3, design review before implementation | Fuller Garmin/Google source-specific nightly views from existing accepted evidence; keep daily vitals separate and comparison semantics unchanged |
| #318 | OPEN; Activity Owner v3, design review before implementation | Quieter A/B comparison, human durations and useful fields without changing B−A, percent-to-A or missing/zero semantics |
| #319 | OPEN; evidence inventory first | Sanitized read-only inventory for calories, max HR and separate aerobic/anaerobic effects; decide the smallest supported slice before code/schema/ingestion changes |
| #294 | OPEN; separately scoped follow-up | Owner Settings & Context: durable weight goal and revisioned context through the UI |
| #228 | Research accepted / parked | No cross-image semantic auto-merge until trustworthy event identity exists |
| #167 | Owner-deferred privacy/history operation | Requires explicit freeze/decision before any rewrite |
| #126 | Owner/admin decision | Recheck required-check/protection capability before settings changes |
| #105 | NOT_ELIGIBLE | No canonical sleep switch until the accepted device-pair evidence gate is met |

#189/#290/#291/#292/#293/#297/#302/#306/#307/#308/#309 are complete, not active queue items. #295 performance and #298 Stress diagnosis are closed as not planned after consolidated Owner UAT: no currently reported general-latency/Stress symptom justifies the old probes. This is neither measured optimization proof nor a diagnosed Stress fix. #153 and #210 remain closed as not planned.

The only open PRs before this documentation closeout are Dependabot #270/#271. They remain separate review proposals and must not be merged as documentation cleanup.

This is a status map, not an automatic Worker queue. Finish documentation reconciliation, then review the Owner's forthcoming Grok/Astra design answers before selecting the next UI direction. #305 remains the functional priority; #319 is an evidence prerequisite for new activity metrics, not an implied parallel assignment. The old #305 + #306 → #307 → #308 → #309 launch sequence is complete/superseded. Existing visual/IA and data contracts stay in force until explicitly changed.

### Operational disposition

The durable Owner runtime is `D:\HealthCheck\stable`; the clean control checkout is `D:\HealthCheck\main`; Owner Ops live in `D:\HealthCheck\ops`; new agent tasks use `D:\HealthCheck\workspaces\<client>\<issue-or-task>`. See [Owner Machine Layout](OWNER_MACHINE_LAYOUT.md).

Google high-frequency sample HR remains intentionally disabled under the accepted explicit collection policy; existing history is preserved and no broad backfill/re-enable is authorized merely to make freshness look green. Other accepted Garmin/Google/Training/wearables-sleep collection remains bounded by the existing operational contracts.

The tested off-site recovery path is a verified ordinary ZIP in the Owner's materialized Google Drive folder plus supported clean restore. Protected age-based publication remains optional rather than required for the Owner workflow.

Workspace cleanup runs daily at 12:00 with a seven-day minimum retention and fail-closed eligibility. Legacy roots such as `D:\Garmin` or old client roots are not in the janitor allowlist and require explicit/manual disposition. This session closeout does not delete local workspaces or change scheduled tasks.

Weight remains operational through screenshots; #229 provides explicit correction/replay semantics and #240 records metadata origins without rewriting legacy history. #153 is closed as not planned; #228 remains parked. The unconfigured browser extractor observed in #305 is not a failure of the separately accepted screenshot-skill path.

See [Current History](EXECUTION_HISTORY_CURRENT.md), [Owner UI](OWNER_UI_SHELL.md), [Owner Machine Layout](OWNER_MACHINE_LAYOUT.md), [Owner Refresh](OWNER_REFRESH.md) and [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md).

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

Deterministic bounded Weight/sleep/activity/data-quality packet, stable result hash, thin API/text/CLI renderers, direct R05 reuse, full bounded activity inventory and honest missing/unavailable/confirmed-empty distinctions. #203 fixes limited-encoding stdout; #227 provides coherent compound reads without changing packet mathematics; #248 adds explicit JSON/text output. #172 UX and #283 backend performance are complete. No new score or LLM/Telegram delivery.

## Post-R05 Stable Owner Runtime — completed foundation

One persistent private cross-domain profile, supported backup/restore into disposable UAT clones, reproducible exploratory agreement, bounded provider refresh, stabilized Google identity and stale SyncRun recovery are canonical. #214 added successful automatic selected-stream operation; #238 later completed explicit reversible collection-intent/freshness semantics.

## Post-R05 Garmin Training & Recovery — completed

Parent #160 closed after #175 bounded discovery, #180 typed persistence and live replay proof, #183 normal refresh composition and #187 read-only Owner view with semantic review/UAT.

No custom Health-Check training/readiness score, medical/coaching claim, VO2 guessing or invented producer attribution. #189 completed the Russian Owner-first Activity foundation and #309 completed Activity v2. Further presentation is #318; possible additional metric evidence is separately investigated under #319.

## Current owner-facing product work

### Source freshness / data quality

#147/#191/#193 delivered provider-call-free shared freshness from persisted facts. #238 completed explicit collection intent so intentionally disabled streams remain historically truthful/non-actionable without hiding enabled failures or rewriting history. #189 Stage 2 makes Данные the shared source/freshness/import entry point. #305 adds safe failure classification and import-history UX, but the real 15-second freshness timeout still requires diagnosis and a verified fix.

### Hardware/private Owner gates

#215 completed the first real private Context note/read-back. #148 off-site recovery is complete with a verified Google Drive ZIP and clean restore rehearsal. #153 is closed as not planned; screenshot import remains the accepted Weight workflow.

### Owner UI #189 — integrated; post-UAT follow-up active

Accepted IA and one frozen visual/language system govern all pages. Stages 1–6 are complete: shared shell, Данные, Обзор, Вес, Сон and Активность. Sleep is primary at `/sleep`; Agreement remains secondary at `/agreement`. No provider/analytics/schema semantics are changed by presentation redesign.

#189 stages 1–7 and the subsequent #306–#309 wave are integrated. Consolidated Owner UAT on the 2026-10-07 product checkpoint produced the current bounded follow-ups in the backlog above. Neither #317/#318 nor forthcoming design proposals silently reopen the shell or redefine data contracts. See [Owner UI](OWNER_UI_SHELL.md) and [Current History](EXECUTION_HISTORY_CURRENT.md).

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
