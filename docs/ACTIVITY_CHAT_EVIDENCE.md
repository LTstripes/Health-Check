# Activity evidence service

The bounded #341 slice returns an in-memory Activity + optional current Context
packet for exactly 7/30 inclusive source-local calendar dates and one explicitly
selected persisted Garmin source. It reuses the accepted #346/#347 activity
summary cells: session count, type counts, tennis count, independently eligible
tennis duration in seconds, and cycling distance in meters. No new aggregation,
provider pooling, workout-type expansion, recovery inference or transport is part
of this contract. Context establishes only local-date window co-occurrence;
absence of a note does not establish absence of exposure or causality.

```python
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.activity_evidence import ActivityEvidenceRequest, read_activity_evidence

packet = read_activity_evidence(
    profile=Path(selected_existing_profile),
    profile_kind="synthetic",  # explicit trusted caller classification
    request=ActivityEvidenceRequest(
        end_date=date(2099, 1, 8), days=7,
        garmin_source_id=selected_garmin_id,
        include_context=True, context_limit=50,
    ),
    evaluated_at_utc=datetime.now(UTC),
    evaluation_local_date=date(2099, 1, 8),
)
```

`health-chat-activity-evidence-v1` has independent
`health-chat-activity-provenance-v1` provenance and a SHA-256 hash of canonical
compact UTF-8 JSON excluding `envelope_hash`. `encode_activity_evidence` and
`render_activity_evidence` are optional JSON/text consumers of that same frozen
packet; neither writes files. No export is necessary to consume the service.

## Exact window and source

`end_date` must be an exact date, `days` integer 7 or 30 (never bool). Start is
end minus `(days - 1)`; underflow and `date.max` are rejected. Requested and
effective ranges are identical: no clipping, previous-window fallback, all-history
mode or preceding-period delta. Activity membership uses the existing persisted
`GarminSourceRecord.source_local_date`; UTC dates, receipt dates and the host's
timezone do not replace it. Missing/unlocatable local dates are outside this
bounded reader; no new raw timestamp reconstruction is attempted.

One explicit nonblank source ID (existing 36-character identity cap) is required.
It is validated in `GarminSource` and against provider code `garmin_connect`
before summary/Context reads. Unknown, Google-only and wrong-provider IDs fail.
An existing source with no observations in the period is valid empty stored
evidence. No default source, unrelated inventory disclosure, Google activity
parity, cross-source total or source selection algorithm is introduced.

## Reused summary semantics

The adapter calls `PeriodSummaryService._activities` through its existing bounded
input-loading hook, reusing `_identity`, `_incomplete`, coverage, snapshot metadata
and all reducers unchanged. It avoids the public `build()`'s unrelated Sleep and
second-provider inventory reads. This private adapter dependency is deliberate
and covered by equivalence tests against public `build()` for 7/30 days.

The five cells retain the accepted `source-period-summary-v1` units, aggregation
value/numerator/denominator, eligible/excluded counts, observed calendar dates,
eligible/effective date bounds, availability counts, partial/retired evidence,
exclusion reasons, coverage and snapshot normalization versions. Request bounds
and each cell's observed/eligible bounds describe different facts. No new
per-workout detail, timing precision, raw metric provenance or conversion is
invented for an aggregate-only result.

- Session/type counts cover accepted saved activity sessions, including types
  other than tennis/cycling. Invalid and duplicate current identities remain
  excluded according to the existing reader.
- Tennis is exactly `tennis` or `tennis_v2`; its count is independent of duration
  eligibility. Duration uses accepted `duration_seconds` in seconds only.
- Cycling distance is exactly `cycling`, using accepted `distance_meters` in
  meters. `road_biking`, running and other types do not enter this cell; missing
  activity types retain the reader's explicit exclusions.
- Null/missing/invalid/unit-mismatched/negative scalars are excluded, preserving
  reason counts. A real eligible zero remains zero. Partial valid inputs retain
  partial counts; duplicate current identities never acquire a winning row.
- No saved observations without acquisition proof have null values. Existing
  source-specific complete coverage can establish proven-empty count/type cells
  (0 or `{}`), while absent distance/duration remains null. Stored rows alone
  never prove collection completeness. Observations on confirmed-empty dates
  retain `contradictory` coverage and those dates. Shared acquisition identities
  do not establish exact-source completeness.

No readiness/load/recovery reducers, calories, steps, raw-value recalculation,
new scores, medical interpretation or inferred energy effects are included.

## Context and disclosure

Optional Context uses unchanged `ContextService.list(history=False)` with local
date interval overlap. Current corrected revisions may start before the window;
superseded text and nonoverlapping notes are excluded. The exact Context
recursive whitelist from [Sleep evidence](SLEEP_CHAT_EVIDENCE.md) preserves event/
revision identity, literal original text, capture source, tags/provenance and
original date/timestamp/offset/zone precision. Date-only stays date-only.
Operation IDs are excluded. Literal Owner text is untrusted data, never tool
instructions; JSON/text consumers escape it identically.

The packet permits local-date window co-occurrence only. It does not join notes
to individual workouts, count exposure-free days, infer effects, establish
causality or create an automatic cross-domain analysis engine. A later authorized
caller can combine this packet with other bounded evidence while retaining each
domain's source/window/coverage limits.

Activity source/cells use recursive allowlists. Dynamic activity-type counts,
coverage status/date maps and retirement-reason counts permit only scalar typed
values; containers in scalar positions fail. Unknown future fields are dropped.
No provider bodies, raw payloads, artifact paths, GPS, credentials, configuration,
SQL, queue records, unrelated files or unrelated source inventory are exported.
This is a disclosure boundary, not a scrubber of authorized original Context.

## Snapshot and limits

The caller supplies an existing trusted profile and explicit classification:
`synthetic`, `disposable_owner_clone`, or `durable_owner_runtime`. Owner profiles
are private; classification is an operator assertion, not authentication.
Snapshot metadata remains unknown and current Stable identity unverified.

All source validation, summary and Context reads share the existing
`chat_evidence._read_session`: WAL-aware SQLite `mode=ro`, one read transaction,
`query_only`, deny-write authorizer, current-schema check, 20-million SQL-step
budget and 20-second SQL progress deadline. No `immutable=1`, normal engine/
runtime factory, migration, refresh, profile discovery, environment/config scan,
provider call or application write is used. SQLite's WAL/SHM read coordination
can occur. Missing or unmigrated profiles fail without repair or creation.

The existing summary limits apply per selected source/activity surface: 4096
candidate records, 16384 metric rows, 8192 metadata rows per table, 2048 coverage
intervals, 32 source identities for coverage attribution, and a 2-second
cooperative summary budget. The adapter retains the outer SQLite guards and
adds cap+1 loading and inherited budget checks; it never changes busy_timeout
or replaces the snapshot's progress callback. Overflow/budget failure returns
the existing `search_incomplete` cells with unknown values/counts and explicit
reasons, never a successful prefix. No aggregation is performed after truncating
inputs. SQLite failures surface bounded `EvidenceError` codes without data/paths.

These are cooperative query/read guards, not a hard whole-response latency
guarantee; SQLite lock waiting and Python processing remain limitations. Real
profile performance is unverified. Context is capped at 1–100 current rows,
default 50, reads one extra and reports `has_more/truncated` and unknown total
when truncated. Context truncation does not truncate activity aggregates.
The existing 2 MiB JSON guard runs before the structured packet returns; text
has the same byte limit including its header. Nothing uploads automatically.

## Compatibility and verification

Existing Sleep service/contract, summaries, exporter, MCP tools/schema/auth,
database schema, UI and shared roadmap/status documents are unchanged. This
service does not make data reachable from ChatGPT/dot; connection, OAuth,
transport setup, live provider access, Owner DB reads, Stable deployment and
runtime UAT are outside the slice.

Synthetic production-entry tests cover public-summary equivalence, 7/30 bounds,
source-local date membership, irrelevant workout exclusions, exact sources,
zero/missing/null/partial, duplicate/retired inputs, coverage conflicts, Context
revisions/overlap/precision/truncation, coherent concurrent reads, recursive
disclosure, caps, preserved SQL guards, output limits and denied writes. Required
independent data/privacy review and exact-candidate CI remain separate gates.
