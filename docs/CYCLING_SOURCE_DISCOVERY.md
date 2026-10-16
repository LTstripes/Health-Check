# Cycling distance source discovery

The #347 backend exposes `CyclingSourceDiscoveryService(session).discover(...)`
with version `cycling-distance-source-discovery-v1`. It discovers saved exact
Garmin sources for **one metric**, `cycling_distance_meters`, without choosing
one. It does not change Statistics, Sleep selection, Activity evidence or CLI.
UI wiring, independent review, integration and Owner UAT are separate steps.

```python
from datetime import date
from healthcheck.analytics.cycling_source_discovery import CyclingSourceDiscoveryService

packet = CyclingSourceDiscoveryService(session).discover(
    end_date=date(2099, 1, 8), days=7,
)
```

The caller supplies an existing SQLAlchemy SQLite session and owns its lifetime
and transaction. Pending ORM changes are rejected before queries/autoflush. The
service establishes/reuses one physical read snapshot, expires stale ORM state
and performs SELECTs; it does not open profiles, migrate, commit, roll back, write
data or access providers/auth. It uses the ordinary summary budget, restores
the connection's busy timeout and removes its progress handler on exit. Like the existing
summary service, it is not an adapter for a caller that already owns a custom
SQLite progress handler; such a transport adapter requires separate integration.

## Explicit periods and meaning

The five accepted summary windows are reused without clipping or fallback:

- `end_date` plus integer `days=7` or `days=30`.
- `period_type="trailing365"` or `"year_to_date"` plus `end_date`.
- `period_type="calendar_year"` plus integer `calendar_year`, without end/days.

The result reports inclusive requested start/end and day count. A following
coverage boundary must exist (`date.max` is rejected). Annual windows contain
at most 366 days. No custom/all-history or last-known period is introduced.
Membership uses persisted `source_local_date`, not UTC/receipt/host dates.
Unlocatable/missing dates remain outside this bounded range; raw timestamp
reconstruction is not attempted.

The existing `PeriodSummaryService._activities` reducer and bounded input loader
own all calculations and eligibility. This deliberately reuses the private hook
also used by Activity evidence, avoiding public `build()`'s Sleep/provider reads.
Production-entry synthetic tests compare its returned cycling cells with public
summary output in every supported window. No summary code changes are required.

The frozen type set is exactly `cycling`. `road_biking`, other cycling subtypes
and other activities do not enter distance. Extending that set needs a separate
evidence-backed decision. Distance remains the sum of eligible saved per-session
`distance_meters` in meters, with explicit eligible-session denominator. No daily
distance, unit reinterpretation or source fusion is introduced.

## Result contract

The packet has `contract_version`, accepted `reader_contract`, `evaluated_at`,
`requested_window`, `metric`, `freshness`, `read_limits` and two `providers`.
`selection_policy` is `caller_owned_no_automatic_selection`. There is no selected
source ID, combined aggregate, ranking or cross-source delta.

For Garmin, `options` is ordered by persisted source ID solely for deterministic
enumeration. Each option contains the exact existing `source_identity`, an
`eligibility` result, and the accepted reducer's `summary` cell. The cell retains
value/numerator/denominator and eligible/excluded counts, all availability counts,
observed/eligible dates and bounds, exclusions, coverage and snapshot evidence.
It adds `search.complete=true` only after its bounded read succeeds.

`eligibility.has_eligible_values` is true if the accepted cell has at least one
usable distance, **including explicit zero**. `ambiguous_record_count` retains
`duplicate_current_identity` exclusions even when that source has other usable
sessions. `state` is `ambiguous_records`, `eligible`, or `no_eligible_values`.
`reason_codes` includes all accepted exclusion reasons and a no-values reason
when applicable. Retired snapshots remain disclosed, not counted as current.

Garmin provider counts are metadata `source_count`, `eligible_source_count` and
`ambiguous_source_count`. Provider `state` is, in precedence order:

1. `search_incomplete` if the bounded discovery cannot finish.
2. `ambiguous_records` if any exact source has duplicate-current ambiguity.
3. `multiple_eligible_sources` if more than one has usable distance.
4. `unique_eligible_source` if exactly one has usable distance.
5. `no_eligible_values` if metadata sources exist without usable distance.
6. `source_missing` if the metadata inventory is empty.

Those states describe discovery; even `unique_eligible_source` does not select
or persist a source. An ambiguous source with some usable data retains both
facts, and the provider remains ambiguous. Another metric's values, a brand
label, a newer record or longer coverage never establish distance eligibility.

Google is explicitly `not_collected`, reason
`typed_activity_stream_not_collected`, based on the persisted stream contract.
Its `search.scope` is `persisted_stream_contract`; it does not enumerate Google
metadata or pretend a metric search found zero sources. All three counts are
null, `options=[]`. No Google Activity ingestion or parity is implied.

## Missingness, coverage and bounded failure

Missing/null/invalid/negative/wrong-unit distances and invalid/current-duplicate
records retain the accepted exclusions. Missing activity types retain their
explicit reason. Partial valid records remain usable with partial counts.
An eligible saved zero is zero; absent distance stays null even with complete
or confirmed-empty acquisition coverage. No missing date becomes a zero.

`search.complete` means the bounded saved-input evaluation finished. It does not
mean complete collection or live freshness. Per-source `summary.coverage` retains
unestablished, failed and contradictory acquisition evidence. Shared acquisition
identities cannot prove exact-source coverage. `freshness` remains unknown.

Discovery uses the existing one-request `PeriodReadBudget` deadline and source,
record, metric, metadata and coverage caps reported in `read_limits`. The activity
hook loads all saved activity types and distance/duration inputs conservatively;
an overflow in those dependencies can make discovery incomplete too. This is a
bounded backend contract, not a proof about unbounded stored history.

Any incomplete source or inventory read suppresses the **entire Garmin result**:
`options=[]`, all three provider counts null, `search.complete=false`, exact
`search.reason` plus `reason_codes`. A successful earlier prefix is not returned
as a unique candidate. Google's independent unsupported-stream fact remains.
No official total or eligible count is fabricated from a truncated search.

The budget is cooperative and SQLite-specific, not a hard whole-response latency
guarantee. This slice has synthetic evidence only; real-profile latency,
provider freshness, UI selection behavior and Owner UAT remain unverified.
