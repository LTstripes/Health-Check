# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in release-specific documents and GitHub issues.

## Current canonical state — 2026-10-03

- Canonical Git branch: `main`. Checkpoint before this docs closeout: `0339088c52dcefac93bb372a3a460c12cc4b6152`; exact-main CI `37137153269` SUCCESS. Owner `D:\HealthCheck\main` was also clean/read back at this SHA.
- Latest numbered major release remains R05. Post-R05 Runtime, Period Brief, Context v0, Garmin Training/Recovery, source freshness/collection policy, screenshot workflow and reliability/correction work are canonical.
- #214 automatic selected-stream collection proof and #238 collection-policy/freshness reconciliation are complete. Google high-frequency sample HR remains intentionally disabled under explicit reversible policy; historical age/evidence is preserved rather than called fresh.
- Stable private data: `D:\HealthCheck\stable`; Owner/control checkout: `D:\HealthCheck\main`; local Ops: `D:\HealthCheck\ops`; disposable Owner UAT: `D:\HealthCheck\uat`; agent tasks: `D:\HealthCheck\workspaces\<client>\<issue-or-task>`.
- #148 practical off-site recovery is complete: the accepted Owner workflow is an ordinary verified ZIP in the materialized Google Drive folder plus supported clean restore. Optional protected age publication is not required.
- #251 CI lane balancing and #256 filesystem/workspace maintenance are complete. The workspace janitor runs daily at 12:00 local with seven-day minimum retention and preserves ambiguous/active/young/wrong-origin tasks.
- Current active non-UI technical thread: #246 Stage A docs-only PR fast path. #243/#242/#244 are separate maintenance/security tasks; #247/#248/#240 are later bounded follow-ups. UI #172/#189 remains deferred.
- Repository visibility remains public at this checkpoint; #126 and #167 remain explicit Owner/capability/privacy decisions rather than implicit authorization for settings/history changes.

See the [current backlog](ROADMAP.md#current-backlog--2026-10-03), [Owner machine layout](OWNER_MACHINE_LAYOUT.md), [current history](EXECUTION_HISTORY_CURRENT.md) and [model journal](MODEL_BENCHMARK.md).

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

#123–#125 established provenance-bound evidence, three serial Linux lanes with exact nodeid/multiplicity reconciliation, and focused native Windows DPAPI/startup/HTTP/cleanup proof. Historical timing improvement is recorded in [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md), not promised for every run.

#181 is complete. Captured root/child identities are checked independently; post-termination reuse requires changed trustworthy CreationTime. Exit-255 reconciliation consumes the complete accepted transcript. The post-main transient-WMI failure was retained and repaired by bounded polling, not a retry-until-green waiver. See `docs/DEVELOPMENT_PROCESS.md` for the precise success/failure contract.

#126 is still an explicit Owner/capability decision. Before advancing canonical/shared refs the Integrator requires exact-tree/SHA final `checks: SUCCESS` under the accepted PR protocol. Green constituent lanes alone are insufficient. No history rewrite, forced ref update or protection change is part of ordinary work.

## Next work

#215 first real private Context note/read-back; #238 collection-intent contract and fix; then #148 protected off-site recovery. The Owner-only #215 action and read-only #238 design can proceed independently. Do not repeat #214's expensive refresh solely to close an already-proven automatic gate. UI remains deferred.

Before updating local code, verify idle relevant Owner processes and a clean accepted checkout. Do not switch/pull while refresh is running. Do not infer local deployment from `git fetch`.

## Core engineering rules

- `main` is the only canonical release source.
- Issue = contract; short Worker prompt = role, exact SHA, workspace and delivery.
- Workers do not self-accept or merge; independent review remains risk-based.
- Real health data, screenshots, tokens, payloads and runtime DBs never enter Git/CI/Worker workspaces.
- Missing/null/zero/unavailable/unknown remain distinct.
- Deterministic analytics own mathematics; UI/LLM explain rather than reimplement them.
- Owner-confirmed actual model labels count as evidence even when a client reports unknown; unreported versions stay unknown.

## Useful docs

- [README](../README.md)
- [Product Vision](PRODUCT_VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Decisions and Open Questions](DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](EXECUTION_HISTORY_CURRENT.md)
- [Model Evidence Journal](MODEL_BENCHMARK.md)
- [Owner Refresh](OWNER_REFRESH.md)
- [Owner Refresh Closeout](OWNER_REFRESH_CLOSEOUT_2026-10-01.md)
- [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md)
- [Stable Owner Runtime Closeout](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
