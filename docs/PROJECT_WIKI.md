# Health-Check Project Wiki

This is the compact current-state entry point. Historical contracts and release evidence remain in their release-specific documents and GitHub issues.


## Current canonical state — 2026-10-01

- Canonical Git branch: `main`.
- Current accepted product checkpoint: `ac1df6dd5bdcfdc57c56a9b531e89a108a658d2b`.
- Exact-main CI: `36818997839` — SUCCESS, including Windows smoke and final `checks`.
- Re-read live GitHub main/CI before launch/integration; documentation SHAs are dated evidence, not permanent branch pointers.
- Latest numbered major release remains R05. Post-R05 Runtime, Period Brief, Context v0, Garmin Training/Recovery, source freshness, screenshot workflow, #203/#226/#227, #233, #181 and #229 are canonical.
- Stable Owner data profile: `D:\Garmin\HealthCheck-Stable`. Candidate UAT uses disposable verified backup/restore clones, never Stable itself.
- Owner operational checkout: `D:\Garmin\HealthCheck-Owner-Main`; local Ops scripts: `D:\Garmin\HealthCheck-Ops`. GitHub merges do not automatically deploy to these local paths.
- #214: historical inventory/manual PASS; daily 10:30 plus logon Scheduler configured; one untouched automatic-run acceptance remains.
- Google high-frequency `heart_rate` is OFF by Owner decision in the local runner only. Other streams remain enabled; no historical HR backfill while disabled.
- #229 correction workflow is released: changed sidecars stage pending evidence, reject leaves prior state intact, confirm reuses revision/supersession history, terminal replay is duplicate-safe.
- #181 CI reliability is complete: fail-closed process identity/CreationTime handling plus full-rerun-only evidence provenance are canonical; the post-merge WMI transient was repaired in PR #237 and exact-main is green.
- #228 research is accepted/parked; #153 optional compatibility; #172/#189 UI deferred; #167 Owner-deferred; #126 decision/capability gate; #105 NOT_ELIGIBLE; #210 ongoing journal.
- Repository visibility is public; private-data restrictions remain unchanged. This state does not authorize a visibility/protection/history rewrite.

Full [backlog status table](ROADMAP.md#current-backlog--2026-10-01), [current history](EXECUTION_HISTORY_CURRENT.md), and [model evidence table](MODEL_BENCHMARK.md).

## What the product can do today

### Weight / body composition

- import Xiaomi Home/S400 screenshots through the repo skill and strict Owner-assisted extraction, reusing R01;
- auto-confirm only the accepted unambiguous path; reject incompatible algorithm identity before semantic writes (#226);
- preserve original evidence, source/device/algorithm provenance and confirmed history;
- exact attachment replay is duplicate-safe; no claim of automatic cross-image event dedup (#228);
- accept the openScale/openScale-sync contract, with real numeric-userId compatibility still optional/open (#153);
- calculate deterministic trends and show the local Weight dashboard.

Changed-sidecar correction staging is released under #229: changed evidence stays pending until explicit decision, reject is non-mutating, confirm preserves revision/supersession history, and exact terminal replay is duplicate-safe.

### Garmin

- protected owner-assisted session reuse;
- incremental sync and historical backfill;
- coverage/checkpoints/reconciliation;
- deterministic scalar baselines/trends;
- activity/cycling comparison and bounded lagged associations;
- read-only owner Garmin dashboard;
- persist Garmin-native Training Status/load/ACWR, Load Focus and Readiness/Recovery with truthful chronology/provenance;
- keep Training current through one-command Owner refresh;
- show Training & recovery plus recent activity Training Effect/load.

### Google Health

- Web Application OAuth with fixed registered loopback callback;
- external-runtime DPAPI-protected auth/session state;
- accepted read-only sleep and health-metrics scopes;
- source/raw/current typed evidence;
- bounded incremental sync, historical backfill and explicit refresh/reconciliation;
- coverage/checkpoint/idempotency semantics;
- privacy-safe structural diagnostics;
- selectable normal streams; fixed wearables-sleep reconciliation remains separate.

The bare CLI default still includes sample HR. Use the local Scheduler/runner for the Owner's chosen HR-OFF profile; see [Owner Refresh](OWNER_REFRESH.md).

### Cross-domain reporting

- deterministic Period Brief over Weight, sleep, activity and data quality;
- reproducible evidence packet and stable result hash;
- thin API/text/CLI rendering, including limited-encoding Windows stdout (#203);
- coherent Weight/Period Brief multi-query SQLite snapshots with clean ORM cache alignment (#227);
- shared source-freshness projection from #147/#191/#193, not duplicated UI thresholds.

### Live-accepted Stable Owner Runtime

The completed foundation provides one private persistent profile, supported large-profile backup/verify/restore, one-command provider refresh, bounded dense-HR continuation, path-free Google instant/interval identity, shared external-runtime locking and supported stale-run recovery.

Historical closeout proved zero current instant duplicate groups and no stale running SyncRun rows at that checkpoint. Those are dated observations, not a perpetual health guarantee after later runs. The 2026-09-29 operational report proved a successful manual selected-stream refresh; uninterrupted automatic proof remains open in #214.

Stable is data, not Git state, and is never reset for release UAT.

## R04 live proof

The released Owner gate proved In-production Google OAuth, the two accepted scopes, protected consent/session reuse, bounded capability, pagination/resume, narrow terminal-empty repair #110, zero-call completed-window replay, bounded HRV backfill/refresh and populated DB integrity at the R04 revision. Release specifics remain in [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md).

## Source-attribution rule that matters for R05

`dataSourceFamily`, query mode and broad `google-wearables` family membership are acquisition context, not proof of one physical Fitbit device.

- `fitbit_device` / `device_pair`: requires explicit persisted source/device metadata;
- `google_wearables_family` / `family_pair`: exploratory only, insufficient for canonical switching;
- `account_wearables_sleep_observations_v1`: exploratory/uncertain-only.

Garmin remains canonical/default. #105 is NOT_ELIGIBLE until its existing evidence gate is satisfied.

## Engineering reliability / CI

#123–#125 established provenance-bound evidence, three serial Linux lanes with exact nodeid/multiplicity reconciliation, and focused native Windows DPAPI/startup/HTTP/cleanup proof. Their historical remote timing improvement is recorded in [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md), not used as a promise for every current run.

#181 is complete. Windows cleanup now captures root/descendant creation identity, treats post-termination PID reuse as proven only by changed trustworthy CreationTime, consumes the accepted exit-255 transcript fail-closed, and requires one coherent full-rerun evidence set rather than cross-attempt mixing. The first post-merge WMI transient was preserved as an escape and repaired before final exact-main green.

#126 is still an explicit Owner/capability decision. Before advancing canonical/shared refs, Integrator requires exact-SHA final `checks: SUCCESS`; green constituent lanes alone are insufficient. No history rewrite, forced ref update or protection change is part of ordinary product work.


## Next work

Prove one untouched automatic #214 run, then record the Owner's first real #215 Context note. After those operational gates, prioritize #148 protection/publication/retention design and a clean recovery rehearsal. #228/#153 stay parked/optional; #172/#189 UI remains deferred unless the Owner reprioritizes.

The [roadmap table](ROADMAP.md#current-backlog--2026-10-01) records all 11 open issues, including the non-coding tracker and parked gates. It is not an automatic queue.

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
- [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md)
- [Stable Owner Runtime Closeout](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
