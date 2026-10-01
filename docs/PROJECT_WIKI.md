# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in release-specific documents and GitHub issues.

## Current canonical state — 2026-10-01

- Canonical Git branch: `main`. Repository checkpoint before this operational closeout: `4029fd8c70e5bde0120bdf7902f2016faec118ed`; exact-main CI `36820492189` SUCCESS. Re-read live GitHub state before launch/integration.
- Latest numbered major release remains R05. Post-R05 Runtime, Period Brief, Context v0, Garmin Training/Recovery, source freshness, screenshot workflow, #203/#226/#227/#233/#181/#229 are canonical.
- **#214 CLOSED / operational PASS:** Owner-reported automatic post-reboot/logon run completed with Scheduler result 0, complete successful seven-day report and all four acquisition layers succeeded. Measured duration 19m03.819s; Google sample HR OFF.
- **Freshness caveat:** Owner/Google aggregates remain stale solely from disabled `google:heart_rate / refresh_overdue`; Garmin aggregate is fresh. Optional Garmin HRV-status/resting-HR chronology remains unknown. #238 tracks explicit collection-intent/freshness alignment, not a request to enable HR or fabricate freshness.
- Stable private data: `D:\Garmin\HealthCheck-Stable`. Candidate UAT uses disposable verified backup/restore clones, never Stable as a development workspace.
- Owner operation checkout: `D:\Garmin\HealthCheck-Owner-Main`; local Ops: `D:\Garmin\HealthCheck-Ops`. Last observed Owner HEAD was `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`; updating it to newer main has not been evidenced. GitHub merges do not deploy locally.
- #229 correction workflow is released: changed sidecars stage pending evidence; reject preserves prior state; confirm reuses revision/supersession history; terminal replay is duplicate-safe.
- #181 is complete through PR #236 and post-main WMI follow-up PR #237. Fail-closed ownership/CreationTime evidence, exact exit-255 transcript parsing and full-rerun-only CI remain mandatory.
- #215 first real Context note/read-back remains open; #148 off-site protection/recovery remains open. #228 research accepted/parked; #153 optional; #172/#189 UI deferred; #167 Owner-deferred; #126 capability gate; #105 NOT_ELIGIBLE; #210 ongoing journal.
- PR #232 merged; obsolete PR #224 closed as superseded without merge. Repository visibility remains public; this closeout does not authorize visibility, protection or historical metadata rewrite.

See the [11-issue backlog](ROADMAP.md#current-backlog--2026-10-01), [automatic-run closeout](OWNER_REFRESH_CLOSEOUT_2026-10-01.md), [current history](EXECUTION_HISTORY_CURRENT.md) and [model journal](MODEL_BENCHMARK.md).

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

The bare CLI default still includes sample HR. The local Scheduler/Ops wrapper applies the Owner's HR-OFF choice. That choice is not yet represented consistently in the shared freshness policy; #238 remains open. See [Owner Refresh](OWNER_REFRESH.md).

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
