# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in release-specific documents and GitHub issues.

## Current canonical state — 2026-10-04

- Canonical Git branch: `main`. Closeout checkpoint: `9f41985c47f758f38186efade974bb7ba1d9bf4d`; exact-main ordinary CI `37184776672` SUCCESS and Dependency audit `37184776636` SUCCESS.
- Latest numbered major release remains R05. Post-R05 Runtime, Period Brief, Context v0, Garmin Training/Recovery, source freshness/collection policy, screenshot workflow and the reliability/correction slice remain canonical.
- Stable private data: `D:\HealthCheck\stable`; Owner/control checkout: `D:\HealthCheck\main`; local Ops: `D:\HealthCheck\ops`; disposable Owner UAT: `D:\HealthCheck\uat`; agent tasks: `D:\HealthCheck\workspaces\<client>\<issue-or-task>`.
- #148 practical off-site recovery and #256 canonical filesystem/workspace maintenance are complete; the fail-closed workspace janitor remains the accepted daily cleanup mechanism.
- The 2026-10-03/04 CI/test-maintenance wave is complete: #251 lane balancing, #246 docs-only + exact-tree event dedup, #243 Windows transcript reliability and #242 dependency/security audit all closed with live integration evidence.
- #244 loopback Host/Origin hardening is also complete and reconciled into the current lane manifest.
- There is no open test-suite/pytest/lane/workflow optimization implementation task. #126 is still an explicit Owner/admin decision about required-check enforcement, not unfinished test engineering.
- Current bounded non-UI technical work is #247 / #248 / #240. #228 is parked; #172/#189 UI and #167 privacy/history remain deferred; #105 remains NOT_ELIGIBLE.
- Repository visibility remains public at this checkpoint. No settings/history rewrite is implied by engineering acceptance.

See the [CI optimization closeout](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md), [current backlog](ROADMAP.md#current-backlog--2026-10-04), [Owner machine layout](OWNER_MACHINE_LAYOUT.md) and [current history](EXECUTION_HISTORY_CURRENT.md).

## What the product can do today

### Weight / body composition

- Import Xiaomi Home/S400 screenshots through the repo skill and strict Owner-assisted extraction, reusing R01.
- Auto-confirm only the accepted unambiguous path; reject incompatible algorithm identity before semantic writes (#226).
- Preserve original evidence, source/device/algorithm provenance and confirmed history.
- Exact attachment replay is duplicate-safe; cross-image event dedup is not implemented (#228).
- Stage changed-sidecar corrections for explicit review (#229); reject is non-mutating; confirm preserves revision/supersession history; SQLite signed-zero normalization does not destabilize replay.
- Accept the openScale/openScale-sync contract; real numeric-userId compatibility remains optional/open (#153).
- Calculate deterministic trends and show the local Weight dashboard.

### Garmin

- Protected Owner-assisted session reuse.
- Incremental sync and historical backfill with coverage/checkpoints/reconciliation.
- Deterministic scalar baselines/trends, activity/cycling comparison and bounded lagged associations.
- Read-only Owner Garmin dashboard.
- Persist Garmin-native Training Status/load/ACWR, Load Focus and Readiness/Recovery with truthful chronology/provenance.
- Keep Training current through normal Owner refresh and show recent activity Training Effect/load.

### Google Health

- Web Application OAuth with fixed registered loopback callback and external-runtime DPAPI-protected state.
- Accepted read-only sleep and health-metrics scopes.
- Source/raw/current typed evidence with bounded incremental sync, historical backfill, refresh/reconciliation and coverage/checkpoint/idempotency contracts.
- Privacy-safe structural diagnostics.
- Selectable normal streams; fixed wearables-sleep reconciliation remains a separate required layer.

The bare CLI default still includes sample HR. The local Scheduler/Ops wrapper applies the Owner's HR-OFF choice, and #238 now supplies the accepted explicit reversible collection-policy semantics used by shared freshness consumers. Disabled HR remains historically truthful/non-actionable rather than fabricated fresh. See [Owner Refresh](OWNER_REFRESH.md).

### Cross-domain reporting

- Deterministic Period Brief over Weight, sleep, activity and data quality.
- Reproducible evidence packet and stable result hash.
- Thin API/text/CLI rendering, including limited-encoding stdout (#203).
- Coherent Weight/Period Brief compound SQLite reads and clean ORM cache alignment (#227).
- Shared source-freshness projection from #147/#191/#193, not duplicated UI thresholds.

### Live-accepted Stable Owner Runtime

The completed foundation provides one private persistent profile, supported large-profile backup/verify/restore, one-command provider refresh, bounded dense-HR continuation, path-free Google instant/interval identity, shared external-runtime locking and supported stale-run recovery.

Historical closeout proved no current instant duplicate groups or stale running SyncRun rows at that checkpoint. Those are dated observations, not a perpetual guarantee. #214 now adds one successful automatic selected-stream run; it does not prove continuous multi-day operation, graceful cancellation or once-per-day deduplication.

Stable is data, not Git state, and is never reset for release UAT.

## R04 live proof

Released Owner gates proved In-production Google OAuth, the two accepted scopes, protected consent/session reuse, bounded capability, pagination/resume, narrow terminal-empty repair #110, zero-call completed-window replay, bounded HRV backfill/refresh and populated DB integrity. See [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md).

## Source-attribution rule that matters for R05

`dataSourceFamily`, query mode and broad `google-wearables` family membership are acquisition context, not proof of one physical Fitbit device.

- `fitbit_device` / `device_pair`: requires explicit persisted source/device metadata.
- `google_wearables_family` / `family_pair`: exploratory only, insufficient for canonical switching.
- `account_wearables_sleep_observations_v1`: exploratory/uncertain-only.

Garmin remains canonical/default. #105 is NOT_ELIGIBLE until its existing evidence gate is satisfied. Current equipment or a configured report label must not retroactively rewrite historical producer identity.

## Engineering reliability / CI

#123–#125 established provenance-bound evidence, three serial Linux lanes with exact nodeid/multiplicity reconciliation, and focused native Windows proof. #181 and #243 retain fail-closed Windows process/cleanup semantics, including complete transcript/PID/CreationTime evidence and the narrow accepted exit-255 separator grammar.

The later optimization wave changed execution cost without deleting test coverage:
- #251 rebalanced the same complete Linux test union across the three lanes; the controlled candidate wall time moved from 5:13 to 4:21 (52 seconds / 16.6%).
- #246 Stage A live-proved a fail-closed docs-only route for five existing prose files; its terminal verdict explicitly states that pytest and Windows were not run.
- #246 Stage B live-proved exact-tree task-push delegation to an already-complete PR gate; the delegated push skips its own quality/Linux/Windows/checks and is explicitly not a candidate gate. The first push before a matching PR exists remains full.
- #242 moved dependency advisories into a separate path-scoped workflow, patched urllib3/pytest, pinned actions to immutable SHAs and added bounded Dependabot visibility. Ordinary CI therefore stays deterministic and does not depend on OSV/network availability for unrelated changes.

Detailed rollout evidence and limitations are in [CI Optimization Closeout — 2026-10-04](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md).

#126 remains an explicit Owner/capability decision. The Integrator process still requires exact-tree/SHA successful gates before advancing canonical history even without server-side protection.

## Next work

There is no automatic next CI/test optimization task. Reopen performance work only for a new measured bottleneck, regression or security need.

Current bounded non-UI backlog:
- #247 — replace the non-Windows Google custom cipher with standard AEAD without changing the accepted Windows DPAPI boundary.
- #248 — explicit Period Brief JSON/text stdout without changing deterministic packet semantics.
- #240 — explicit Owner-attested screenshot date/source metadata under the existing provenance boundary.

#228 remains parked, #172/#189 UI and #167 privacy/history remain deferred, and #105 remains NOT_ELIGIBLE. #126 is a repository-settings/Owner decision rather than implementation work.

Before updating local code, verify idle relevant Owner processes and a clean accepted checkout. Do not switch/pull while refresh or dependent runtime processes use that checkout. GitHub publication and local deployment remain separate.

## Core engineering rules

- `main` is the only canonical release source.
- Issue = contract; short Worker prompt = role, exact SHA, workspace and delivery.
- Workers do not self-accept or merge; independent review remains risk-based.
- Real health data, screenshots, tokens, payloads and runtime DBs never enter Git/CI/Worker workspaces.
- Missing/null/zero/unavailable/unknown remain distinct.
- Deterministic analytics own mathematics; UI/LLM explain rather than reimplement them.

## Useful docs

- [README](../README.md)
- [Product Vision](PRODUCT_VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
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
