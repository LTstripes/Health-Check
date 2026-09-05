# R01 Release Closeout — Weight & Body Composition

This document is the release-closeout supplement to `docs/EXECUTION_HISTORY.md` for the work performed after the history sync through R01-07 / issue #10. It intentionally contains no real health values, screenshots, credentials, private payloads, or machine-specific raw-artifact paths.

## Release candidate

- Integration branch: `integration/r01-weight-core`
- Final owner-UAT release candidate: `058639919c4b5e13c420e7c016d292843afa10dc`
- Exact integrated CI: GitHub Actions run `33986964805` — SUCCESS
- Stable pre-R01 `main` before release merge: `cca6efb43d2cb56de7448f006b3f496b1ef6d770`

## R01-08 hardening and owner UAT

Issue #11 completed the integrated release-hardening gate after several fail-fast UAT findings were fixed rather than waived.

Notable release-gate findings and fixes:

- stale canonical state was made visibly diagnosable instead of silently presenting an old successful snapshot as fresh;
- failed-only composition scopes were included in canonical freshness state;
- a dedicated owner Windows UAT checklist was added;
- owner Windows fresh-start and route-isolation checks passed;
- the photo-review UI was fixed to expose provenance visibly before confirmation;
- the initial real-image attempt exposed that the runtime was still wired to a synthetic-only extractor; this led to issue #34 rather than being treated as an OCR edge case;
- Windows `ZoneInfo` availability exposed a missing runtime timezone dependency; this led to issue #37.

Final owner UAT on exact SHA `058639919c4b5e13c420e7c016d292843afa10dc`:

- Ruff: PASS;
- pytest: `182 passed`;
- Windows fresh start: PASS;
- separate loopback UI and ingest-route isolation: PASS;
- packaged `tzdata` / `Europe/Moscow` resolution: PASS;
- synthetic historical photo E2E: 26 images, 59 pending candidates, explicit edit/reject/confirm flow, no auto-confirm;
- confirmation result: 58 confirmed, 1 rejected, repeated confirmation idempotent;
- dashboard/analytics/provenance/BIA warnings: PASS;
- GET/read-only no-mutation checks: PASS;
- openScale synthetic contract/replay verification: PASS;
- privacy/repository hygiene: PASS.

Optional live device verification remains explicit rather than implied:

- live S400/openScale BLE: **UNVERIFIED**;
- real external vision-provider call: **UNVERIFIED BY OWNER**.

Those two items are not counted as passed and are not required to claim a live device/provider integration that was not actually exercised.

## Issue #34 — production real-photo extractor

The first private owner real-photo UAT failed structurally because normal runtime used `FakeImageMeasurementExtractor`, which only accepted synthetic payload-bearing images. Issue #34 added a production-capable provider-neutral real-photo adapter behind the existing extractor contract.

Accepted candidate: `a8699ac840710130b26c54e29fe5dc68ac132c10`.

Independent reviewer: Muse Spark 1.2 — ACCEPT.

Key accepted properties:

- normal production composition no longer hardwires the synthetic fake;
- unconfigured runtime fails closed with a truthful typed configuration error;
- provider/network failures are sanitized and replayable from preserved raw evidence;
- structured output validation is strict about units, dates, timestamps, nullable confidence, provenance and temporal precision;
- fake extraction remains explicit test/demo composition only;
- external network activity occurs only from an explicit owner import/reprocess action.

The owner subsequently chose not to configure an external vision API solely for a one-time historical backfill. Historical screenshots were instead imported through an owner-assisted, manually confirmed path while preserving the normal Health-Check service/confirmation/provenance model. Therefore provider-specific live-photo verification is deliberately deferred rather than falsely marked PASS.

## Historical Xiaomi migration

The owner-assisted historical migration ran against the accepted integrated code with a runtime outside Git.

Sanitized result:

- 20 source screenshots examined;
- 19 unique weigh-ins retained; one duplicate screenshot skipped;
- 341 candidates confirmed through the normal service/confirmation path;
- 19 measurement sessions;
- 341 scalar measurements;
- canonical recompute completed with 2 runs / 114 selections;
- all represented metric codes were importable; none were skipped;
- repeat/idempotency validation: PASS;
- dashboard sanity: PASS;
- provenance recorded as owner-assisted historical photo extraction with Xiaomi S400 and Moscow timezone semantics;
- no model/confidence/algorithm version was falsely claimed;
- no product-code change, commit, push, PR or merge was performed by the migration operation.

A final read-only compatibility pass on a disposable copy of the owner runtime confirmed the same session/measurement/canonical counts and did not mutate the source owner data.

## Issue #37 — Windows timezone runtime hardening

Owner migration exposed that clean Windows environments may lack an IANA timezone database even though Linux CI provides one through the host OS.

Accepted candidate: `1205c3c6f1086f74084bb1addd7ff96bdafc50a6`.

Integration merge: `058639919c4b5e13c420e7c016d292843afa10dc`.

The fix adds packaged Python `tzdata` as a runtime dependency and a regression test that clears the host `TZPATH` before resolving `ZoneInfo("Europe/Moscow")`. Final Windows owner UAT confirmed normal zone resolution with `+03:00` and no process-local shim.

## Release decision

**R01 mandatory owner gate: PASS; R01 is released on `main`.**

The release merge completed as PR #40. The current `main` at this
post-R01 documentation baseline is
`24c4e1f949cd04746ca40bde539a9f32b1b4b4b0`; its post-merge CI run
`33990424240` completed **SUCCESS**. No mandatory R01 blockers remain. Live
S400/openScale BLE and the real external vision-provider call remain
**UNVERIFIED** and are not part of the release PASS claim.
