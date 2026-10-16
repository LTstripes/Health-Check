# Garmin HRV calendar recovery: future copy-only verification

This runbook is preparation, not authorization to run recovery. Code/synthetic
acceptance, independent review, private copy verification and Stable rollout are
separate outcomes. Do not call Garmin, change Stable, or start/stop the Owner's
application to exercise it. No real profile was reprocessed for this candidate.

## Candidate contract

`r02-garmin-hrv-calendar-normalization-v3` uses the explicit
`hrvSummary.calendarDate` as a source-local date without an instant or invented
zone. Present supported calendar fields must all be strict valid dates and agree.
A sleep/start clock, requested day or receipt cannot replace an absent date.
Other normalization output retains v2, including existing stress/activity gates.

Production id-less HRV identities retain the existing reconciliation algorithm:
source + stream + surface + temporal coordinate. Distinct days cannot collide;
value corrections within one day retain the identity. No new schema or generic
cross-source/metric resolution is introduced. Google HRV remains separate.

Offline reprocess verifies HRV original bytes, size and SHA-256, with a 1 MiB
per-artifact bound and duplicate-JSON-key rejection. The existing 140-observation
and date-range limits remain. It selects the latest observation per existing
source/surface/acquisition window and preserves original receipt chronology.
Out-of-range returned dates and unproven dates never authorize retirement.

An old v1/v2 undated singleton is excluded from ordinary absence retirement.
Only offline reprocess may retire its exact old reconciliation identity after
proving its own immutable payload resolves to the same in-range day as the
committed dated replacement. Source/surface, versions, integrity and non-stale
chronology must match. Replacement and retirement share one transaction. A
legacy row belonging to another day stays untouched. Missing/invalid/unknown
coverage cannot supersede it; unresolved evidence stays excluded, not guessed.
An older overlapping acquisition whose own verified bytes prove that same day
cannot expose a stale dated value ahead of the newer legacy observation or
consume every bounded-resume slot. Acquisition-window equality alone is not
evidence that two HRV summaries describe the same day.
Eligibility and resume use each original's verified returned day. A restored
different day in the same acquisition window cannot consume another resume slot
or hide a missing day. Originals outside the requested range remain eligible
when a later request expands to include their returned day; a previous clipped
attempt or another day's current projection is not proof of completion.

## Separately authorized operator procedure

1. Obtain explicit authorization for an exact disposable profile, candidate SHA,
   date range and `hrv_status` only. Use supported consistent backup/restore;
   copying only a live DB without its WAL is insufficient. Never use Stable as
   the target. Verify clone provenance, ordinary non-reparse paths, schema and
   absence of another writer. Retain a pre-operation copy for rollback.
   The existing command has no source-ID selector: authorization must cover all
   saved HRV sources in this range, with their identities inventoried in advance.
   Otherwise STOP; do not remove other sources or silently expand authorization.
2. Record a private baseline manifest of original raw/artifact hashes and bytes,
   original acquisition observations, checkpoints and current projection. For
   every expected day, identify its own payload date, newest observation and
   weeklyAvg state/value. Include unchanged controls outside the range and in
   another surface/source. Do not publish personal values/IDs/dates on GitHub.
3. Begin with two adjacent dates and the existing `garmin-reprocess` command,
   explicit clone `--data-dir`, `--start`, `--end`, `--stream hrv_status`,
   `--max-observations` no greater than 140, and `--dry-run`. Check exact target,
   eligible/version-skipped/superseded counts and remaining budget. Dry-run
   enters runtime preparation/migration machinery: verify schema eligibility
   first; do not claim it is a general read-only command.
4. Only under the separate apply authorization, run that bounded operation on
   the same copy without `--dry-run`. Verify every dated current HRV value/state
   against its own original, not a window/receipt date. Check legacy retirement
   references and reasons. Any unexplained extra/missing day, source mix,
   rollback, stale overwrite or damaged provenance is STOP on the copy.
5. Repeat the identical operation: no new current duplicates, value drift or
   additional observations after convergence. Exercise bounded resume and compare
   its final per-day mapping with the expected mapping. Do not increase limits
   to bypass an unproven original. Inspect unresolved undated/malformed cases
   explicitly; a successful command is not proof all days were recovered.
6. Original bytes/raw rows/acquisition observations remain intact. Derivative
   observations and dated rows may be added, and a proven legacy current row may
   retire. Projection row-count growth is expected, not evidence of duplication.
   Outside-range/surface and unassigned-source controls, plus incremental/historical checkpoints,
   must match the baseline. Record integrity checks and their actual limits;
   a timeout is not a pass. Restore only the disposable copy if verification fails.

Expansion beyond the pilot, real recovery, provider reacquisition, Stable rollout
and Owner UAT each require their own assigned scope. This runbook grants none.
