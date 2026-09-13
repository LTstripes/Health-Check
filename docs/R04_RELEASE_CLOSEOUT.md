# R04 Release Closeout — Google Health ingestion

R04 is released to canonical `main`.

## Release lineage

- R04 release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- Release PR: #114 (`integration/r04-google-health` → `main`)
- Release merge commit: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- PR-context CI: `34768197695` — SUCCESS
- Post-merge `main` CI: `34768452960` — SUCCESS
- Tracker: #80 — closed completed

## What R04 delivered

- Google Health API v4 ingestion only; no new legacy Fitbit Web API path.
- Web Application OAuth with a fixed registered loopback callback.
- Exactly two read scopes: sleep plus health metrics/measurements.
- Windows user-scoped DPAPI protection for Google client/token/session material in the external runtime directory.
- Explicit Google source identity and provenance; query mode and `dataSourceFamily` remain acquisition context rather than device identity.
- Additive immutable raw/source evidence and typed Google normalization/persistence.
- Bounded incremental sync, historical backfill, explicit refresh/reconciliation, coverage, checkpoints, request budgets and resumability.
- Completed-window idempotency: an exact rerun can skip the provider entirely when coverage proves no work is required.
- Fail-closed shape handling with privacy-safe structural diagnostics.

## Owner-live acceptance

Sanitized owner-live evidence proved:

- Google Auth Platform is `In production`, External.
- Fresh re-consent succeeded and the immediate normal authorization path reused protected state.
- `granted_scope_count=2`, `missing_scope_count=0`.
- Bounded capability probing succeeded for the planned R04 surfaces.
- Heart-rate pagination/resume was exercised against the live provider.
- A live terminal HTTP-200 envelope omitted both `dataPoints` and `nextPageToken`; focused repair #110 now treats only the proven missing-collection/no-token LIST/RECONCILE case as an empty terminal page while malformed/null/non-array shapes remain fail-closed.
- The repaired heart-rate window completed with confirmed-empty coverage and an exact rerun made 0 provider requests.
- A bounded historical `daily_hrv` backfill succeeded.
- A tiny explicit `daily_hrv` refresh succeeded and exercised reconciliation without discarding immutable prior evidence.

No owner health values, IDs, raw payloads, tokens or precise identifying timestamps were recorded in GitHub evidence.

## Populated owner DB disposition

The owner runtime was checked after R04 UAT:

- Alembic head: `0010_google_typed_normalization`
- readiness: true
- journal mode: WAL
- foreign keys: enabled
- `PRAGMA quick_check`: `ok`
- foreign-key violations: 0

No destructive R01–R03 migration was required.

## Source-attribution disposition for R05

R04 preserves provider/source/device metadata conservatively. `google-wearables` family evidence is not automatically Fitbit-device evidence because the family may include more than one Google wearable class. R05 may use `device_pair` only when persisted live metadata explicitly supports the intended Fitbit source/device identity. Broader family-only evidence remains exploratory and cannot drive a canonical-source switch.

## Accepted residual limitations

- Refresh-token durability over a long elapsed interval remains observationally `UNVERIFIED`; the project is In Production and immediate protected reuse/refresh is proven, so this is not an R04 release blocker.
- Provider late-correction behavior beyond the bounded refresh evidence remains observational rather than assumed.
- Proprietary Fitbit Sleep Score / Readiness is not claimed by R04.

## Next work

R05 starts from released canonical `main`, never from the retired R04 staging assumption. The frozen R05 design is tracked by #97 with implementation issues #100–#106. Post-R04 maintenance #98 and hardening investigation #99 remain separate and must not be mixed into R04 history.
