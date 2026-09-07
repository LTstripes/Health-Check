# R02 Garmin collection reconciliation contract

This is the pre-R03 hardening continuation of the
[normalization contract](R02_NORMALIZATION_CONTRACT.md) and
[persistence contract](R02_PERSISTENCE_CONTRACT.md). It defines how current Garmin
collections converge under provider corrections and how completed coverage can be
reprocessed after adapter/normalization upgrades. It does not add a scheduler,
analytics, FIT/GPS ingestion, Fitbit/Google adapters, or live Garmin access.

## Stable sample identity

Current-projection identity is independent of mutable array position when a stable
provider token exists.

1. A stable provider record id (`activityId` or equivalent) still wins and uses the
   existing `garmin:v1:record:` key.
2. Otherwise an id-less sample uses `garmin:v1:reconcile:` over source, stream,
   surface, temporal identity, and **sample token**.
3. The sample token is the provider timestamp or numeric series stamp when present.
4. Array index is a last-resort identity only when no record id and no sample token
   exist. Reorder/insert is then inherently ambiguous and is not invented into a
   stable identity.

`record_index` remains a non-identity attribute. Reorder or insertion of unchanged
samples must not create another current row.

## Timestamp correction

A corrected provider timestamp/token is a new sample identity. The old identity is
absent from the new collection. When that collection is authoritative and complete,
the old current row is retired rather than updated in place. The new identity is
inserted or updated. Value-only corrections keep the same identity and update the
current projection.

## Collection authority and removal

A fetch may retire current members **only** when it is authoritative and complete
for that collection window. Partial, unknown, failed, truncated, or budget-stopped
fetches never delete or retire prior valid current members.

| Collection | Window | Complete when |
| --- | --- | --- |
| Intraday series (HR, stress, Body Battery, SpO2, respiration) | one local calendar date | the day payload was fully retrieved and coverage is `present` or `confirmed_empty` |
| Day-scoped singleton (sleep, daily summary, RHR, HRV) | one local calendar date | same as above |
| Activities | the requested local-date range | every activity page was retrieved, the last page was short or empty, and coverage is `present` or `confirmed_empty` |

Truncated activity pagination (`limit` items on the last allowed page, or a mid-window
request-budget stop) is incomplete. An explicit empty collection can retire every
current member of that window. Present members in a complete collection un-retire a
previously retired identity. Present members in an incomplete fetch may update or
un-retire themselves but must not retire absences.

Retired rows stay in the current-projection table with `projection_status=retired`.
Raw payloads and observation rows are never deleted.

## Replay and recency

Raw bytes, raw payload rows, and observation rows remain immutable. A newer
observation (later `received_at` than the collection's latest
`projection_observed_at`) may update current members and, if complete, retire
absences. An older observation is still stored as provenance and **must not**
change current projection: no value rollback, no insert of vanished members, and
no un-retire.

Exact observation-key retries remain idempotent and do not create another
observation row.

## Version-aware reprocessing

Normal historical backfill continues to skip `present` / `confirmed_empty` coverage.
That skip is unchanged unless reprocessing is explicitly requested.

- `garmin-backfill --reprocess` re-fetches `present` coverage whose current rows are
  not yet on the current reconciliation contract version. `confirmed_empty` coverage
  still skips. Historical and incremental checkpoint namespaces stay isolated.
- `garmin-reprocess` is an offline, bounded command. It re-normalizes stored raw
  artifacts for an explicit date range and does not call Garmin, write incremental
  checkpoints, or write historical checkpoints.

Reprocess is bounded by the requested local-date span and a max observation cap.
Days in the requested range with no `present` / `confirmed_empty` coverage that
also sit outside the incremental trailing window are reported as history gaps.
An incremental watermark is not contiguous history.

## Out of scope

Scheduler/background service, Garmin analytics, FIT/GPS download, Fitbit/Google,
a generic provider framework, owner live payloads, and destructive provenance
rewrite.
