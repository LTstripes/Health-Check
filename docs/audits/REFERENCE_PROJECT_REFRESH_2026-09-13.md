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
- Reviewed pins and reuse classifications are unchanged. The accepted
  research recorded new observed upstream heads for `python-garminconnect`
  (`0.3.15`) and `haelan` (`1.14.0`); these are observations, not repins.
- The four deferred watch items from the 2026-09-12 refresh remain
  **WATCH / DEFER** (see below), except that the `python-garminconnect`
  maintenance disposition is now the bounded upgrade promoted as #98.
- Haelan remains **AGPL-3.0 / REFERENCE ONLY / NO CODE COPYING**.
- **#94 / owner-live source attribution is unresolved.** Fitbit-specific
  attribution that has not been proven live is not inferred here.
- This docs worker created **no** issues. The Integrator promoted the accepted
  #90 follow-up dispositions into **#96**, **#97** and **#98**.

## Refresh matrix

No additional upstream verification pass was performed for this docs closeout.
Observed heads below are those recorded by the accepted 2026-09-13 research
(for the projects it re-checked) and are carried forward from the verified
2026-09-12 snapshot elsewhere; any newer upstream head is observation only
until an explicit future task re-audits it. Reviewed pins and reuse
classifications do not change.

| Project | Reviewed pin (unchanged) | Observed head recorded by accepted 2026-09-13 research | Disposition 2026-09-13 |
|---|---|---|---|
| `python-garminconnect` | `981d150caeda7d632224a75f3895c08df27a2a34` (`0.3.12`), MIT, DIRECT runtime dependency | `54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5` (`0.3.15`) — supersedes the 0.3.13 head recorded 2026-09-12; material **sleep-respiration DTO alias fix** | **ADOPT NOW (bounded)** — keep the released R02 runtime pin at `0.3.12`; the accepted upgrade disposition is bounded **`0.3.12 → 0.3.15`**, promoted by the Integrator as **#98**, with auth/activity regression + owner-live gates. Observation only until #98 runs. |
| `garmin-stats-ai` | `936974ac8c78781e7d0075040f459ea7676b3819`, MIT/BSD-3, selective donor | `b648f015e5bd914d27f82c19021e187473639068` | **WATCH / DEFER** — overnight-series/DST/sparse-upsert/fixture-drift ideas stay reference/regression candidates for later analytics work; no medical-threshold adoption. |
| `fettle` | `82929df268124f0a3470b180adbbbeb0802d03cd`, MIT, selective donor | same (no delta 2026-09-12) | **ALREADY COVERED / WATCH** — existing R04 registry/sync/sleep/test-pattern audit remains current. |
| `healthquery` | `f175148f67cb954fc4db2e026e497984dfccac29`, MIT, selective pattern donor | same (no delta 2026-09-12) | **ALREADY COVERED / WATCH** — raw replay/migration/typed-MCP patterns remain current; generic-SQL boundary stays rejected. |
| `garmin_ai` | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee`, UNVERIFIED license | same (no delta 2026-09-12) | **REFERENCE ONLY** — no code copying; unchanged. |
| `openScale` | `6613db5838e4674a19652441073f82b3ee3d7009`, GPL-3.0, external component | `573beb1d3588bd73597fb8a2da7474bf465157d2` (API-v3 identity model) | **WATCH / DEFER** — keep R01 path; re-audit exact installed pair + v3 payload before any future Xiaomi ingest change. Clarification: `identity` is internal between openScale/openScale-sync; the webhook sends the transformed backend `key` (e.g. `builtin.weight → weight`), so the full namespace must not be assumed to cross the HTTP boundary. |
| `openScale-sync` | `32e38651cf78bbf230e33d17abb00b147130f305`, GPL-3.0, external component | `afff7625c6a1cfc946caf76da87d7bc418a29270` (`0.6.3` line) | **WATCH / DEFER** — same re-audit gate as openScale; pre-v3 key assumptions stay stale. |
| `open-wearables` | `72351e24de045e87da4fe4fd86142494e304e17b`, MIT, architecture/selective pattern | `53de57cade876df104720c0c5be07bbf462a55b1` (`0.8`) | **WATCH / DEFER** — SyncRun/status/attribution/migration-guard patterns stay reference material; provider claims stay non-authoritative. |
| `haelan` | `89d512115acc9b1529a6380399a0d451556da0b1` (`1.6.0`), AGPL-3.0 | `4fc2bab4136ed46f950c0d2dc3ef1e03c5c50324` (`1.14.0`) | **REFERENCE ONLY / NO CODE COPYING** — accepted material deltas: typed MCP/HTTP/read-boundary failure-class ideas, untrusted-text/tool-doc/runtime-budget ideas, night-detail evidence. Source **freshness is still not implemented upstream**; it stays a Health-Check design/test idea, not a donor capability. |
| `VitaSync` | `f299cd134edea8effca9ac52436fc83d439792b6`, AGPL-3.0 | same (no delta 2026-09-12) | **REFERENCE ONLY** — unchanged; product/infrastructure mismatch. |

## Deferred watch items — 2026-09-13 disposition

1. **`python-garminconnect` upgrade (0.3.12 → 0.3.15).**
   The accepted 2026-09-13 research moved this from "watch" to a bounded
   maintenance disposition: observed `0.3.15 @ 54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5`
   with a material sleep-respiration DTO alias fix, superseding the earlier
   0.3.13 observation. The Integrator promoted it as **#98** with
   regression/owner-live gates. The dependency is **not** bumped in this
   docs closeout; the reviewed runtime pin remains `0.3.12`.
2. **openScale / openScale-sync API-v3 contract.**
   Still deferred. Any future Xiaomi/openScale work must re-audit the exact
   installed pair and current v3 webhook payload first. R01 is not reopened.
   Preserved accepted clarification: the namespaced `identity` vocabulary is
   **internal** between openScale and openScale-sync; what crosses the HTTP
   boundary is the transformed backend `key` (e.g. `builtin.weight → weight`),
   so no downstream consumer should assume it receives the full namespace.
3. **Source freshness / staleness model.**
   Still deferred, and still not implemented upstream in Haelan 1.14.0 — it
   remains a Health-Check design/test idea rather than a donor capability.
   Any future model must be metric/source-aware against actual R01–R04 source
   behavior, not one universal age threshold. Placement
   (R05 / R06 / monitoring / backlog) is an Integrator planning decision,
   not made here.
4. **Cross-project adversarial regression catalogue (10 classes).**
   Watch list carried forward unchanged from 2026-09-12 (UTC-offset dating,
   sibling-upsert nulling, shape-drift-as-empty, omitted-zero vs missing,
   string numerics, fixture drift, late-evidence invalidation, aggregate
   mislabeling, dead-source-as-thin-chart, convenience-zero override).
   Classes are encoded only by an owning implementation task where the data
   shape makes the regression meaningful. No missing-class promotion is
   claimed in this docs closeout.

## Delta against the 2026-09-12 audit

- Baseline moved from `main @ 43abef5` (pre-R04) to
  `integration/r04-google-health @ 767a06a` (post-R04 #84–#88).
- Observed-head updates only: `python-garminconnect` `0.3.13 → 0.3.15`
  (material sleep-respiration DTO alias fix) and `haelan` `1.6.0 → 1.14.0`.
- No donor reclassification; no reviewed-pin change; no license change recorded.
- No already-promoted R04 finding is rediscovered as new.
- The `python-garminconnect` item moved from pure watch to a bounded upgrade
  disposition (#98); the other three deferred items stay watch/defer.
- Unresolved state carried forward: #94 and remaining owner-live
  source-attribution evidence (including whether real
  `dataSource`/`platform`/device metadata suffices for Fitbit attribution).

## Follow-up dispositions

The accepted #90 report proposed the follow-ups; the **Integrator** reviewed
and promoted them, and this docs worker created no issues:

- **#96** — guard Alembic migration ancestry before new schema work
  (from the migration-chain/re-parenting observation).
- **#97** — R05-00 Garmin/Google sleep agreement and canonical-source contract
  (the R05 agreement input).
- **#98** — bounded `python-garminconnect` `0.3.12 → 0.3.15` upgrade with
  regression and owner-live gates.
- An **R06 typed-tool packet** remains a future candidate for a later
  planning decision; it was not created as an issue for this closeout.

## Hard boundaries observed

- Research/audit/docs only; no runtime code, dependency, schema,
  canonical-rule, roadmap or migration change.
- No AGPL/GPL/unverified-license donor code copied.
- No donor claim treated as medical/provider fact.
- No owner health data, secrets, or provider tokens in scope.
- No generic provider framework; no invented roadmap work.
