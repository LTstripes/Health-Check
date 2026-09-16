# Current Execution History

This is the compact current release history for fast handoff. The older verbose engineering log remains in [EXECUTION_HISTORY.md](EXECUTION_HISTORY.md) and Git/GitHub history. This file is maintained as the current release-to-release narrative.

No raw owner health values, identifiers, payloads, screenshots, credentials or private runtime artifacts belong here.

## R00 — architecture and process foundation

R00 established the product and engineering rules:

- single-user Windows-first local system;
- Python/FastAPI/SQLite WAL;
- immutable/source evidence separated from canonical selection and derived analytics;
- device/provider/input/algorithm provenance separated;
- deterministic analytics below UI/LLM;
- explicit coverage and missing/null/zero semantics;
- release integration branches with Integrator-controlled acceptance/merge;
- worker prompts pinned to exact SHAs and issues as the real contracts.

## R01 — Weight & Body Composition — released

Main outcomes:

- runtime + migrations + provenance core;
- Xiaomi screenshot/photo import with confirmation;
- openScale/openScale-sync contract;
- canonical selection and coverage;
- deterministic weight/body-composition analytics;
- owner dashboard and backup/restore.

Owner UAT exposed real defects that synthetic CI missed: visible provenance, production image-extractor wiring and Windows timezone data. All were repaired before release.

## R02 — Garmin ingestion/backfill — released

Main outcomes:

- protected Garmin auth/session reuse;
- typed normalization and persistence;
- incremental sync + trailing reconciliation;
- bounded resumable historical backfill;
- historical/incremental checkpoint isolation;
- exact completed rerun with zero provider calls.

The full historical owner backfill exposed live convergence defects in activities, heart-rate and Body Battery that short-window tests did not reproduce. Focused repair rounds preserved the same owner runtime and converged without resetting private state.

Released stable main recorded in the R02 closeout: `d3b2fa316242ac11a7ba5851fdc99656cdf8e534`.

## Pre-R03 hardening

Before analytics, the project made two contracts explicit:

- collection reconciliation/version-aware reprocessing;
- analytic metric/time/coverage identity + immutable evidence manifests.

This prevented R03 from building statistics on ambiguous provider fields or mutable current rows without reproducible inputs.

## R03 — deterministic Garmin analytics/dashboard — released

Delivered:

- scalar personal baselines, quantiles, robust trend/deviation;
- deterministic activity/cycling comparison;
- bounded lagged Spearman association primitives with explicit lag direction and coverage gates;
- read-only owner Garmin dashboard/query service;
- provider-native score wording without inventing a custom readiness/recovery score.

Owner UAT found a populated SQLite migration failure in the accepted pre-R03 chain. A focused FK-safe migration repair was required before the owner dashboard gate could proceed. R03 was released only after populated runtime migration and owner read-only UAT passed.

## R04 — Google Health ingestion — released 2026-09-13

### Contract / architecture phase

R04 first re-audited current provider truth instead of trusting earlier assumptions. Final accepted direction:

- Google Health API v4 only;
- Web Application/Web Server OAuth, not Desktop random-port OAuth;
- fixed registered loopback callback;
- exactly two read scopes for sleep and health metrics/measurements;
- explicit `google_*` ingestion/persistence layer over shared runtime/evidence primitives;
- query mode and `dataSourceFamily` are acquisition context, not source identity;
- `google-wearables` family is not automatic Fitbit-device proof;
- R05 owns cross-source agreement/canonical sleep.

### OAuth / capability

#85 implemented and proved the auth/capability boundary. Owner-live evidence showed:

- Web Application authorization works on the local Windows runtime;
- protected session reuse works;
- planned Google Health surfaces are callable;
- source/device/platform metadata exists on some populated responses;
- heart-rate pagination exists live;
- paired-device settings endpoint is intentionally unavailable under the narrow R04 scope set.

The Google Auth Platform project initially remained in Testing. Follow-up #94 proved final `In production` / External state and fresh protected re-consent/session reuse. Long-horizon refresh-token durability remains observationally `UNVERIFIED` until enough time elapses.

### Persistence / normalization / migration safety

R04 added additive Google persistence and typed normalization through Alembic `0010_google_typed_normalization`.

A separate migration-ancestry guard (#96) was added after review identified that the normal fresh-database path was not enough proof for a moving multi-release SQLite chain.

Final owner DB closeout proved:

- revision `0010_google_typed_normalization`;
- readiness true;
- WAL + FK enabled;
- `PRAGMA quick_check = ok`;
- 0 FK violations.

### Sync / live blocker #110

#88 implemented bounded incremental sync, historical backfill, coverage/checkpoints, exact completed-rerun skipping and explicit bounded refresh.

The owner heart-rate run exposed a real provider shape not covered by fixtures:

1. heart-rate pagination repeatedly hit the request/page ceiling and resumed correctly;
2. a later resumed request returned HTTP 200 but failed generic `shape_drift`;
3. diagnostic stage 1 split page-envelope drift from normalization drift;
4. live rerun proved the failure was the page-envelope path;
5. privacy-safe diagnostic stage 2 inspected only structure of already-persisted invalid evidence;
6. exact live shape proved: top-level object, `dataPoints` missing, `nextPageToken` absent;
7. current ProtoJSON semantics justified treating the proven omitted empty repeated field as an empty terminal list page;
8. focused repair accepted only that missing-collection/no-token LIST/RECONCILE case; null/non-array/unknown shapes remain fail-closed.

Accepted repair candidate: `52b0751890f9688cbf7399b3ddf0ff364146d714`.

Merged to R04 integration through PR #113; integration head became `406f4044ffb0d010c64a8635d402016ae916fc5a`.

Owner-live proof after repair:

- same heart-rate window completed as `confirmed_empty` with one provider call;
- exact rerun made **0 provider calls** and skipped completed coverage;
- one-day `daily_hrv` historical backfill succeeded;
- one-day explicit `daily_hrv` refresh succeeded and exercised reconciliation.

#110 and #88 were then closed completed.

### R04 release closeout

Release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`.

- PR #114: `integration/r04-google-health` → `main`
- exact PR-context CI `34768197695`: SUCCESS
- release merge commit: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- exact post-merge `main` CI `34768452960`: SUCCESS
- tracker #80: closed completed

R04 release truth is recorded in [R04_RELEASE_CLOSEOUT.md](R04_RELEASE_CLOSEOUT.md).

## Lessons carried forward

- Owner UAT is not ceremony: it repeatedly found defects green synthetic CI could not prove.
- Provider shape diagnostics should distinguish structural failure classes early and remain privacy-safe.
- Exact completed-window rerun with zero provider calls is a powerful convergence proof.
- Family/query context must never be promoted into physical-device identity without explicit metadata.
- Populated-database migration checks belong in release gates, not only fresh-DB tests.
- `main` is the only release source; staging branches are temporary coordination tools.

## R05 — Garmin / Google wearable sleep agreement — released

Main outcomes:

- #100–#104 pairing/projection/persistence/statistics/report contracts;
- #122 exploratory uncertain account observations cohort, labeled exploratory-only;
- owner UAT/closeout #106 completed on canonical `main @ 46e59327e394ae6dbc5a4ecdf42913200124b9e9`;
- exact-main CI `35130647037` SUCCESS;
- strict legacy `device_pair` / `family_pair` fail-closed;
- provider-attribution evidence insufficient for canonical switch;
- #105 deferred / NOT_ELIGIBLE; Garmin remains canonical/default.

Sanitized closeout: [R05_RELEASE_CLOSEOUT.md](R05_RELEASE_CLOSEOUT.md).

## Next phase

Current bounded product focus:

- #119 — deterministic period brief v1 over existing weight/sleep/activity/coverage analytics.

Residual maintenance where still justified:

- #98 — evaluate Garmin dependency upgrade 0.3.12 → 0.3.15;
- #99 — reproduce/minimize the known order-sensitive OAuth test/global-state leak.
