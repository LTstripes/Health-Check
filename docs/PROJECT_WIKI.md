# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in release-specific documents and GitHub issues.

## Current canonical state — 2026-10-07

- Audited product checkpoint before this documentation closeout: `main @ 29cc9fcf53c508fa5f4994e3170e697726c0514c`. Exact post-main CI `37658045395`, attempt 1, is SUCCESS with quality, all three Linux lanes, Windows smoke and final `checks`. Documentation publication has its own PR/CI record; always read live main before work.
- #189 stages 1–7 remain integrated/closed. The subsequent wave completed Weight v3 (#306), Overview v2 (#307), Sleep v2 (#308) and Activity v2 (#309, including the evidence-backed `tennis_v2` alias). #305 diagnostics/import presentation is integrated, but its real Stable freshness request still times out after 15 seconds.
- Consolidated Owner UAT on this product checkpoint is recorded in GitHub. It generated #317–#319 and confirmed the remaining #305 symptom; #295 performance and #298 Stress diagnosis were closed as not planned. This is prior Owner-reported evidence, not a new local test performed by this documentation session.
- Latest numbered major release remains R05. Post-R05 Runtime, Period Brief, Context v0, Garmin Training/Recovery, source freshness/collection policy, screenshot workflow and reliability/correction work remain canonical.
- Stable private data: `D:\HealthCheck\stable`; Owner/control checkout: `D:\HealthCheck\main`; local Ops: `D:\HealthCheck\ops`; disposable Owner UAT: `D:\HealthCheck\uat`; agent tasks: `D:\HealthCheck\workspaces\<client>\<issue-or-task>`.
- #148 practical off-site recovery and #256 filesystem/workspace maintenance are complete; the fail-closed workspace janitor remains the accepted daily cleanup mechanism.
- The CI/test-maintenance wave is complete: #251 lane balancing, #246 docs-only/exact-tree event dedup, #243 Windows transcript reliability and #242 dependency/security audit. #244 Host/Origin hardening and #302 deterministic Linux environment pinning are also complete. #274 retained a measured NO-GO profiling record, not optimization code.
- Former follow-ups #240 metadata origins, #247 non-Windows AEAD and #248 Period Brief CLI formats are complete. #172 UX/performance is closed after #189 Stage 3 and #283 backend optimization.
- Nine open issues: five product follow-ups (#305/#317/#318/#319/#294) and four parked/deferred/admin-gated items (#228/#167/#126/#105). Dependabot PRs #270/#271 remain separate review proposals, not accepted changes.
- Repository visibility remains public at this checkpoint. No settings/history rewrite, local deployment or private UAT is implied by engineering acceptance or this documentation closeout.

See the [current backlog](ROADMAP.md#current-backlog), [current integration and UAT history](EXECUTION_HISTORY_CURRENT.md), [historical 2026-10-06 UAT handoff](OWNER_UAT_FOLLOWUP_2026-10-06.md), [Owner UI](OWNER_UI_SHELL.md), [Owner machine layout](OWNER_MACHINE_LAYOUT.md) and [CI optimization closeout](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md).

## What the product can do today

### Owner interface

The primary sections are **Обзор / Вес / Сон / Активность / Данные** on one frozen Russian visual/state/disclosure system. Overview is `/brief`; Weight remains `/`; Sleep is `/sleep` with secondary `/agreement`; Activity is `/garmin` with Сессии and Тренировки и восстановление modes; Data is `/imports` with source freshness/actions and the existing import review workflow.

Interpretation-changing limitations remain visible; detailed provenance/statistics/internal codes stay accessible behind disclosure. Sleep v2 has explicit Garmin / Google / Compare views; fuller per-source nightly evidence is the separate #317 follow-up. Activity v2 is honestly Garmin-backed with explicit Session A / Session B selection and evidence-backed tennis labels; #318 owns further presentation refinement. Data history prioritizes pending/action-required imports and folds completed history. Its browser extractor is correctly reported unconfigured on the Owner profile, and the freshness timeout remains an open functional issue, not a successful status check.

### Weight / body composition

- Import Xiaomi Home/S400 screenshots through the repo skill and strict Owner-assisted extraction, reusing R01.
- Auto-confirm only the accepted unambiguous path; reject incompatible algorithm identity before semantic writes (#226).
- Preserve original evidence, source/device/algorithm provenance and confirmed history.
- #240 records a complete per-candidate metadata-origin map for new imports, while legacy NULL stays historical and unchanged. Date supplied by Owner is explicitly date-only; authorized fixed Xiaomi workflow identity is not falsely labelled visual evidence.
- Exact attachment replay is duplicate-safe; cross-image event dedup is not implemented (#228).
- Stage changed-sidecar/provenance corrections for explicit review (#229/#240); reject is non-mutating and confirm preserves revision/supersession history.
- The openScale/openScale-sync contract remains historical delivered functionality; optional real-device compatibility #153 is closed as not planned. Screenshots are the accepted operational Weight path.
- Calculate deterministic trends and show the Russian Owner-first Weight page without changing its analytics/canonical policy. #306 adds responsive human-readable time axes and explicit observed spans for separate composition compatibility groups.

### Garmin

- Protected Owner-assisted session reuse.
- Incremental sync and historical backfill with coverage/checkpoints/reconciliation.
- Deterministic scalar baselines/trends, activity/cycling comparison and bounded lagged associations.
- Russian Owner-first Activity modes over unchanged service/API results, with explicit A/B selection, stale-response protection and no redundant selector when only one source is usable. `tennis_v2` renders as `Теннис`; persisted codes and analytics equality remain unchanged.
- Persist Garmin-native Training Status/load/ACWR, Load Focus and Readiness/Recovery with truthful chronology/provenance.
- Keep Training current through normal Owner refresh and show recent activity Training Effect/load without inventing thresholds or recovery-time units. Calories, max HR and separate aerobic/anaerobic effects require the #319 evidence inventory before any new metric contract or display claim.

### Google Health

- Web Application OAuth with fixed registered loopback callback and external-runtime protected state.
- Windows DPAPI remains unchanged. #247 replaces non-Windows custom-cipher writes with purpose-bound AES-256-GCM/HKDF v2; authenticated v1 reads remain compatible, migration happens only on normal writes, and reads do not create missing keys.
- Accepted read-only sleep and health-metrics scopes.
- Source/raw/current typed evidence with bounded incremental sync, historical backfill, refresh/reconciliation and coverage/checkpoint/idempotency contracts.
- Privacy-safe structural diagnostics.
- Selectable normal streams; fixed wearables-sleep reconciliation remains a separate required layer.

The bare CLI default still includes sample HR. The local Scheduler/Ops wrapper applies the Owner's HR-OFF choice, and #238 supplies explicit reversible collection-policy semantics used by shared freshness consumers. Disabled HR remains historically truthful/non-actionable rather than fabricated fresh. See [Owner Refresh](OWNER_REFRESH.md).

### Cross-domain reporting

- Deterministic Period Brief over Weight, sleep, activity and data quality, with stable result hash.
- Overview v2 shows Garmin/Google values with explicit source identity, dates and missing states, without pooling or changing the packet. For custom periods over 400 days, only the Google daily-vitals display read is bounded to the trailing 400 inclusive days with visible exact scope; the Period Brief and Garmin retain the full selected period (#307).
- Thin API/text/CLI rendering, limited-encoding stdout (#203) and explicit `period-brief --format json|text` (#248).
- Coherent Weight/Period Brief compound SQLite reads and clean ORM cache alignment (#227).
- Shared source-freshness projection from #147/#191/#193/#238, not duplicated UI thresholds.
- #283 bounds three measured backend hot paths using existing indexes/narrow reads. Full-size synthetic median improved from 55.108 s to 6.520 s; packets/hashes and ordered baseline inputs matched, with no added index, migration or cache. Exact Owner Stable timing remains unverified. [Measurement evidence](../evidence/283-read-performance.md).

### Live-accepted Stable Owner Runtime

The completed foundation provides one private persistent profile, supported large-profile backup/verify/restore, one-command provider refresh, bounded dense-HR continuation, path-free Google instant/interval identity, shared external-runtime locking and supported stale-run recovery.

Historical closeout proved no current instant duplicate groups or stale running SyncRun rows at that checkpoint. Those are dated observations, not a perpetual guarantee. #214 adds one successful automatic selected-stream run; it does not prove continuous multi-day operation, graceful cancellation or once-per-day deduplication.

Stable is data, not Git state, and is never reset for release UAT. The new UI's repository integration is not a new private-runtime deployment/acceptance claim.

## R04 live proof

Released Owner gates proved In-production Google OAuth, the two accepted scopes, protected consent/session reuse, bounded capability, pagination/resume, narrow terminal-empty repair #110, zero-call completed-window replay, bounded HRV backfill/refresh and populated DB integrity. See [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md).

## Source-attribution rule that matters for R05

`dataSourceFamily`, query mode and broad `google-wearables` family membership are acquisition context, not proof of one physical Fitbit device.

- `fitbit_device` / `device_pair`: requires explicit persisted source/device metadata.
- `google_wearables_family` / `family_pair`: exploratory only, insufficient for canonical switching.
- `account_wearables_sleep_observations_v1`: exploratory/uncertain-only.

Garmin remains canonical/default. #105 is NOT_ELIGIBLE until its existing evidence gate is satisfied. Current equipment or a configured report label must not retroactively rewrite historical producer identity.

## Engineering reliability / CI

#123–#125 established provenance-bound evidence, three serial Linux lanes with exact nodeid/multiplicity reconciliation, and focused native Windows proof. #181 and #243 retain fail-closed process/cleanup semantics, including complete transcript/PID/CreationTime evidence and the narrow accepted exit-255 separator grammar.

The later optimization wave changed execution cost without deleting test coverage:
- #251 rebalanced the same complete Linux test union; controlled candidate wall time moved from 5:13 to 4:21 (52 seconds / 16.6%).
- #246 Stage A live-proved a fail-closed docs-only route for five existing prose files; its terminal verdict explicitly states that pytest and Windows were not run.
- #246 Stage B live-proved exact-tree task-push delegation to an already-complete PR gate; the delegated push is explicitly not a candidate gate. The first push before a matching PR exists remains full.
- #242 separated dependency advisories, patched urllib3/pytest, pinned action SHAs and added bounded Dependabot visibility. Unrelated ordinary CI does not depend on OSV/network availability.

Detailed rollout evidence and limitations are in [CI Optimization Closeout — 2026-10-04](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md). A partial rerun cannot supply complete current-attempt acceptance evidence. Classify failures before repeating, preserve failed runs and follow the existing full-rerun/recovery contract.

#126 remains an explicit Owner/capability decision. The Integrator still requires exact-tree/SHA successful gates before advancing canonical history even without server-side protection.

## Next work

#305 needs root-cause diagnosis of the observed 15-second freshness timeout, not another unqualified request to repeat the already-performed UAT. Keep the freshness policy unchanged; use a disposable verified clone or sanitized timing/query-count evidence. Do not increase the timeout blindly or call providers to mask a persisted-read problem.

Before launching #317 Sleep v3 or #318 Activity v3, review the Owner's forthcoming Grok/Astra design feedback and settle the smallest compatible scope. The existing visual/IA contract remains in force until an explicit decision changes it. #319 is evidence-first research, not authorization to add fields, guess units or extend ingestion; #294 Settings & Context remains separately scoped.

#306–#309 are complete. #295 and #298 are closed as not planned after consolidated Owner UAT, not unfinished measurement/diagnostic gates. The [roadmap](ROADMAP.md#current-backlog) keeps parked/admin work and the two Dependabot proposals separate. This status map does not start any Worker automatically.

Before updating local code, verify idle relevant Owner processes and a clean accepted checkout. Do not switch/pull while refresh or dependent runtime processes use that checkout. GitHub publication and local deployment remain separate.

## Core engineering rules

- `main` is the only canonical release source.
- Issue = contract; short Worker prompt = role, exact SHA, workspace and delivery.
- Workers do not self-accept or merge; independent review remains risk-based. Integrator performs review where appropriate, without waiving required independence.
- Real health data, screenshots, tokens, payloads and runtime DBs never enter Git/CI/Worker workspaces.
- Missing/null/zero/unavailable/unknown remain distinct.
- Deterministic analytics own mathematics; UI/LLM explain rather than reimplement them.
- #210 model benchmarking/attribution intake is retired. Complexity and execution-route recommendations support task assignment; they are not a new results journal.

## Useful docs

- [README](../README.md)
- [Product Vision](PRODUCT_VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Owner UI routes and visual contract](OWNER_UI_SHELL.md)
- [Decisions and Open Questions](DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](EXECUTION_HISTORY_CURRENT.md)
- [Owner Refresh](OWNER_REFRESH.md)
- [Owner Refresh Closeout](OWNER_REFRESH_CLOSEOUT_2026-10-01.md)
- [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md)
- [Stable Owner Runtime Closeout](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
