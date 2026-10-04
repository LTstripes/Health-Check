# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in release-specific documents and GitHub issues.

## Current canonical state — 2026-10-04

- Canonical Git branch: `main`. Owner UI #189 stages 1–6 are integrated through Activity PR #287; Stage 7 final whole-product acceptance remains open. Exact SHA/CI and the next-session handoff live in [Current History](EXECUTION_HISTORY_CURRENT.md).
- Latest numbered major release remains R05. Post-R05 Runtime, Period Brief, Context v0, Garmin Training/Recovery, source freshness/collection policy, screenshot workflow and reliability/correction work remain canonical.
- Stable private data: `D:\HealthCheck\stable`; Owner/control checkout: `D:\HealthCheck\main`; local Ops: `D:\HealthCheck\ops`; disposable Owner UAT: `D:\HealthCheck\uat`; agent tasks: `D:\HealthCheck\workspaces\<client>\<issue-or-task>`.
- #148 practical off-site recovery and #256 filesystem/workspace maintenance are complete; the fail-closed workspace janitor remains the accepted daily cleanup mechanism.
- The CI/test-maintenance wave is complete: #251 lane balancing, #246 docs-only/exact-tree event dedup, #243 Windows transcript reliability and #242 dependency/security audit. #244 Host/Origin hardening is also complete. #274 retained a measured NO-GO profiling record, not optimization code.
- Former follow-ups #240 metadata origins, #247 non-Windows AEAD and #248 Period Brief CLI formats are complete. #172 UX/performance is closed after #189 Stage 3 and #283 backend optimization.
- Five open issues at closeout: #189 Stage 7, parked #228, Owner-deferred #167, Owner/admin decision #126 and NOT_ELIGIBLE #105. Dependabot PRs #270/#271 are separate unreviewed proposals.
- Repository visibility remains public at this checkpoint. No settings/history rewrite, local deployment or private UAT is implied by engineering acceptance or this documentation closeout.

See the [current backlog](ROADMAP.md#current-backlog--2026-10-04), [Owner UI](OWNER_UI_SHELL.md), [Owner machine layout](OWNER_MACHINE_LAYOUT.md) and [CI optimization closeout](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md).

## What the product can do today

### Owner interface

The primary sections are **Обзор / Вес / Сон / Активность / Данные** on one frozen Russian visual/state/disclosure system. Overview is `/brief`; Weight remains `/`; Sleep is `/sleep` with secondary `/agreement`; Activity is `/garmin` with Сессии and Тренировки и восстановление modes; Data is `/imports` with source freshness/actions and the existing import review workflow.

Interpretation-changing limitations remain visible; detailed provenance/statistics/internal codes stay accessible behind disclosure. Narrow per-page Chromium checks are accepted. Stage 7 cross-browser/mobile/loading/error acceptance is still outstanding, and the Owner has already dispatched its task. Do not launch a duplicate Worker.

### Weight / body composition

- Import Xiaomi Home/S400 screenshots through the repo skill and strict Owner-assisted extraction, reusing R01.
- Auto-confirm only the accepted unambiguous path; reject incompatible algorithm identity before semantic writes (#226).
- Preserve original evidence, source/device/algorithm provenance and confirmed history.
- #240 records a complete per-candidate metadata-origin map for new imports, while legacy NULL stays historical and unchanged. Date supplied by Owner is explicitly date-only; authorized fixed Xiaomi workflow identity is not falsely labelled visual evidence.
- Exact attachment replay is duplicate-safe; cross-image event dedup is not implemented (#228).
- Stage changed-sidecar/provenance corrections for explicit review (#229/#240); reject is non-mutating and confirm preserves revision/supersession history.
- The openScale/openScale-sync contract remains historical delivered functionality; optional real-device compatibility #153 is closed as not planned. Screenshots are the accepted operational Weight path.
- Calculate deterministic trends and show the Russian Owner-first Weight page without changing its analytics/canonical policy.

### Garmin

- Protected Owner-assisted session reuse.
- Incremental sync and historical backfill with coverage/checkpoints/reconciliation.
- Deterministic scalar baselines/trends, activity/cycling comparison and bounded lagged associations.
- Russian Owner-first Activity modes over unchanged service/API results, with explicit source/reference selections.
- Persist Garmin-native Training Status/load/ACWR, Load Focus and Readiness/Recovery with truthful chronology/provenance.
- Keep Training current through normal Owner refresh and show recent activity Training Effect/load without inventing thresholds or recovery-time units.

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
- Russian Owner-first Overview with meaningful sleep labels/units/counts and action grouping, without pooling comparison statistics or changing the packet.
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

Receive and review the already-dispatched **#189 Stage 7** result in the next session. Read live main/issue/PR/candidate evidence first; do not restart completed stages 1–6 or infer an unpublished branch/SHA. Resolve concrete browser/loading/error/responsive findings, then reconcile required Owner-local deployment/UAT before claiming whole-product acceptance.

#228 remains parked, #167 Owner-deferred, #105 NOT_ELIGIBLE and #126 a repository-settings/Owner decision. Broad dependency/action updates #270/#271 require separate review and are not housekeeping merges. No automatic next CI/test optimization or new product-release track is authorized.

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
