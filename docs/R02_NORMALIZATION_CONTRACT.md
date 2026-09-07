# R02 Garmin normalization contract

This is the offline continuation of [the R02 capability contract](R02_CAPABILITY_CONTRACT.md).
It parses synthetic Garmin fixtures only. It does not authenticate, call Garmin Connect, read
tokens, backfill, write a database, or define a schema.

## Input and output

`healthcheck.garmin.normalization.normalize_garmin_payload` accepts either a validated
`GarminCapabilityFixture` or its synthetic JSON envelope. A raw mapping is accepted for a
deterministic unit probe only when its stream is supplied; missing source metadata is treated as
an unattributed synthetic account value.

The immutable output is `GarminNormalizationResult` containing a source identity, zero or more
`GarminRecordDTO` records, typed `GarminMetricDTO` values, temporal DTOs, unknown-field shape
evidence, and sanitized diagnostics. Raw payload values are not copied into diagnostics or
unknown-field evidence.

The parser recognizes the reviewed `sleep`, `daily_health`, `activity`, `intraday`, and
`original_fit` streams. Activity arrays are parsed item by item, so a valid item survives a
malformed sibling. Unknown fields are retained as path/shape metadata and never become invented
canonical metrics.

## Temporal semantics

| Source value | DTO precision | UTC field | Local field |
| --- | --- | --- | --- |
| `YYYY-MM-DD` / `calendarDate` | `date` | `None` | `local_date` |
| aware ISO local datetime | `instant` | normalized aware UTC | `local_wall_time`, original `source_local_timestamp`, and `source_utc_offset_minutes`/`source_timezone` when available |
| aware or naive explicit `...GMT`/`...UTC` field | `instant` | normalized aware UTC; naive values are attached to UTC by field semantics | no local wall time is invented |
| paired `startTimeLocal` + `startTimeGMT` | `instant` when either side supplies an instant | GMT/UTC side is retained as `source_utc_field` | Local side is retained as `source_local_field` plus its wall-time/zone evidence |
| naive ISO datetime / local wall time with no paired UTC field | `local` | `None` | `local_wall_time` and its date |

Date-only input never becomes midnight UTC. A genuinely local-only naive datetime never receives
an invented timezone. An invalid timestamp yields an `unknown` temporal DTO plus a stable
diagnostic. When both paired fields are valid but disagree on the UTC instant, the local field
is still retained and the record receives a deterministic `paired_time_mismatch` diagnostic.

## Presence semantics

Every recognized field carries one of `missing`, `null`, `value`, or `invalid`:

- absent path → `missing`;
- present JSON `null` → `null`;
- present finite number/string, including numeric `0` → `value`;
- wrong shape, non-finite number, or numeric string → `invalid`.

Only `value` is usable. `GarminMetricDTO.is_zero` identifies an explicit numeric zero without
using truthiness. Missing and null values are never substituted with zero and do not activate a
convenience fallback.

## Source and device identity

`GarminSourceIdentity` requires `source_kind=synthetic` and `provider_code=garmin_connect`.
Device code/model are accepted only when the envelope explicitly says `device.attributed=true`.
The derived `source_instance_id` is stable for the source kind, provider, attribution bit, and
device identity; fixture id, payload order, and payload values are excluded. An unattributed
account-level value remains unattributed. A client method or an inventory row never becomes device
evidence. A metric is device evidence only when both the source is explicitly attributed and the
R02 capability status is `verified` or `verified_conditional`.

## Idempotency

`stable_garmin_idempotency_key` emits a `garmin:v1:record:<sha256>` key when a stable source
record id exists. The key covers only source instance, stream, and record id, so retries with
changed formatting or a refreshed payload target the same record.

When no record id exists it emits `garmin:v1:semantic:<sha256>`, covering source instance,
stream, temporal key, and the sorted set of present non-null typed metrics. Unknown fields,
fixture id, JSON key order, and receive time are excluded. Explicit zero is included; missing
and null are not. A semantic fallback cannot disambiguate two genuinely identical id-less source
records, so callers must retain the diagnostic/source context rather than inventing an ordinal
identity.

Production current-projection identity for id-less series uses
`stable_garmin_reconciliation_key`. A provider timestamp/token is preferred over array
position. Index is last-resort only when no record id and no sample token exist. See the
[collection reconciliation contract](R02_COLLECTION_RECONCILIATION_CONTRACT.md).

## Result states

- `ok`: all parsed records are structurally usable;
- `partial`: at least one record is retained with missing fields, warnings, or recoverable shape
  drift;
- `empty`: the payload or an explicit activity collection has no records;
- `invalid`: no usable record can be produced from a fatal envelope/collection shape failure.

The result is deterministic: DTO collections, metrics, unknown paths, diagnostics, and activity
records are sorted by stable semantic keys. No database, network, authentication, live Garmin, or
backfill code is part of this contract.
