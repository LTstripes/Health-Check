# Reference-project refresh — 2026-09-13 (post-R04 mechanical closeout)

## Purpose

Mechanical docs closeout for issue #90 against the accepted post-R04 baseline.
Research was already performed and accepted by the Integrator; this snapshot
records the accepted verdict durably without expanding scope.

This audit does **not** repin any approved donor, approve new copied code,
change a runtime dependency/schema/canonical rule, or make a third-party
repository authoritative for provider/API facts. Reviewed source SHAs and
reuse classifications in `docs/REFERENCE_PROJECTS.md` are unchanged.

## Baselines

- Health-Check baseline reviewed: `integration/r04-google-health @ 767a06a4bd192dc1027ecba82b0a589d7ee12272`
- Exact post-merge integration CI cited by the Integrator: `34719742157` — SUCCESS.
- Prior full refresh: [`REFERENCE_PROJECT_REFRESH_2026-09-12.md`](REFERENCE_PROJECT_REFRESH_2026-09-12.md)
  against `main @ 43abef5454e1778c9449a61635aca7c45c84a5b7`, which added Haelan
  as AGPL-3.0 reference-only and was integrated via PR #83.

## Evidence rule (unchanged)

1. **Provider truth** — current first-party Google documentation and explicit
   owner-live evidence remain authoritative for Google Health behavior.
   Donor behavior only creates a question to verify.
2. **Implementation pattern** — data-flow, failure, coverage, replay and
   query-boundary patterns may inform Health-Check when they fit our architecture.
3. **Adversarial regression** — a bug another project found can become a
   synthetic Health-Check regression even when none of that project's code is reused.

## Accepted verdict (Integrator-reviewed)

- **No R04 reopen blocker was found.** Accepted R04 work (#84–#88) is not
  reopened by this refresh.
- The four deferred watch items from the 2026-09-12 refresh remain
  **WATCH / DEFER** (see below). None of them justified an automatic upgrade,
  repin, or canonical-rule change in this closeout.
- Haelan remains **AGPL-3.0 / REFERENCE ONLY / NO CODE COPYING**.
- **#94 / owner-live source attribution is unresolved.** Fitbit-specific
  attribution that has not been proven live is not inferred here.
- **No follow-up issues were created in this closeout.** The Integrator owns
  creation of any implementation issues after reviewing this report.

## Refresh matrix (mechanical carry-forward)

No new upstream verification pass was performed in this mechanical closeout.
Observed heads below are carried forward from the 2026-09-12 verified
snapshot; any newer upstream head is observation only until an explicit
future task re-audits it. Reviewed pins and reuse classifications do not change.

| Project | Reviewed pin (unchanged) | Observed head carried forward from 2026-09-12 | Disposition 2026-09-13 |
|---|---|---|---|
| `python-garminconnect` | `981d150caeda7d632224a75f3895c08df27a2a34` (`0.3.12`), MIT, DIRECT runtime dependency | `6569a424c9d44cc93fdd1b0444cc878d1a630866` (`0.3.13`) | **WATCH / DEFER** — keep R02 pin; any bump stays a separate bounded upgrade task with auth/activity regression + owner verification. |
| `garmin-stats-ai` | `936974ac8c78781e7d0075040f459ea7676b3819`, MIT/BSD-3, selective donor | `b648f015e5bd914d27f82c19021e187473639068` | **WATCH / DEFER** — overnight-series/DST/sparse-upsert/fixture-drift ideas stay reference/regression candidates for later analytics work; no medical-threshold adoption. |
| `fettle` | `82929df268124f0a3470b180adbbbeb0802d03cd`, MIT, selective donor | same (no delta 2026-09-12) | **ALREADY COVERED / WATCH** — existing R04 registry/sync/sleep/test-pattern audit remains current. |
| `healthquery` | `f175148f67cb954fc4db2e026e497984dfccac29`, MIT, selective pattern donor | same (no delta 2026-09-12) | **ALREADY COVERED / WATCH** — raw replay/migration/typed-MCP patterns remain current; generic-SQL boundary stays rejected. |
| `garmin_ai` | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee`, UNVERIFIED license | same (no delta 2026-09-12) | **REFERENCE ONLY** — no code copying; unchanged. |
| `openScale` | `6613db5838e4674a19652441073f82b3ee3d7009`, GPL-3.0, external component | `573beb1d3588bd73597fb8a2da7474bf465157d2` (API-v3 identity model) | **WATCH / DEFER** — keep R01 path; re-audit exact installed pair + v3 payload before any future Xiaomi ingest change. |
| `openScale-sync` | `32e38651cf78bbf230e33d17abb00b147130f305`, GPL-3.0, external component | `afff7625c6a1cfc946caf76da87d7bc418a29270` (`0.6.3` line) | **WATCH / DEFER** — same re-audit gate as openScale; pre-v3 key assumptions stay stale. |
| `open-wearables` | `72351e24de045e87da4fe4fd86142494e304e17b`, MIT, architecture/selective pattern | `53de57cade876df104720c0c5be07bbf462a55b1` (`0.8`) | **WATCH / DEFER** — SyncRun/status/attribution/migration-guard patterns stay reference material; provider claims stay non-authoritative. |
| `haelan` | `89d512115acc9b1529a6380399a0d451556da0b1` (`1.6.0`), AGPL-3.0 | same (added 2026-09-12) | **REFERENCE ONLY / NO CODE COPYING** — adversarial Google-v4, freshness, rebuild, correction/rederive and bounded-query ideas stay design/test inputs, not provider truth. |
| `VitaSync` | `f299cd134edea8effca9ac52436fc83d439792b6`, AGPL-3.0 | same (no delta 2026-09-12) | **REFERENCE ONLY** — unchanged; product/infrastructure mismatch. |

## Deferred watch items — 2026-09-13 disposition

1. **`python-garminconnect` upgrade (0.3.12 → 0.3.13).**
   Still deferred. A bounded dependency-upgrade task may be proposed later by
   the Integrator with exact regression/live-owner gates. Not bumped here.
2. **openScale / openScale-sync API-v3 contract.**
   Still deferred. Any future Xiaomi/openScale work must re-audit the exact
   installed pair and current v3 webhook payload first. R01 is not reopened.
3. **Source freshness / staleness model.**
   Still deferred. Any future model must be metric/source-aware against actual
   R01–R04 source behavior, not one universal age threshold. Placement
   (R05 / R06 / monitoring / backlog) is an Integrator planning decision,
   not made here.
4. **Cross-project adversarial regression catalogue (10 classes).**
   Watch list carried forward unchanged from 2026-09-12 (UTC-offset dating,
   sibling-upsert nulling, shape-drift-as-empty, omitted-zero vs missing,
   string numerics, fixture drift, late-evidence invalidation, aggregate
   mislabeling, dead-source-as-thin-chart, convenience-zero override).
   Classes are encoded only by an owning implementation task where the data
   shape makes the regression meaningful. No missing-class promotion is
   claimed in this mechanical closeout.

## Delta against the 2026-09-12 audit

- Baseline moved from `main @ 43abef5` (pre-R04) to
  `integration/r04-google-health @ 767a06a` (post-R04 #84–#88).
- No donor reclassification; no reviewed-pin change; no license change recorded.
- No already-promoted R04 finding is rediscovered as new.
- Unresolved state carried forward: #94 and remaining owner-live
  source-attribution evidence (including whether real
  `dataSource`/`platform`/device metadata suffices for Fitbit attribution).

## Proposed follow-ups

None proposed here (normally 0–5; this closeout proposes **0**).
The Integrator owns creation of any implementation issues, including R05
planning inputs, after reviewing this report.

## Hard boundaries observed

- Research/audit/docs only; no runtime code, dependency, schema,
  canonical-rule, roadmap or migration change.
- No AGPL/GPL/unverified-license donor code copied.
- No donor claim treated as medical/provider fact.
- No owner health data, secrets, or provider tokens in scope.
- No generic provider framework; no invented roadmap work.
