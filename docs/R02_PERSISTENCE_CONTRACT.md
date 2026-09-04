# R02 Garmin persistence contract

This is the offline persistence continuation of the [capability contract](R02_CAPABILITY_CONTRACT.md)
and [normalization contract](R02_NORMALIZATION_CONTRACT.md). It accepts already-normalized Garmin
DTOs and synthetic payload bytes/mappings only. It does not authenticate, call Garmin Connect,
run a backfill, provide a UI, or calculate analytics.

## Storage layers

| Layer | Tables/files | Contract |
| --- | --- | --- |
| Raw bytes | `artifacts/payloads/<aa>/<sha256>.<ext>` and `raw_artifacts` | Exact bytes are content-addressed and retained outside the checkout. `raw_artifacts` keeps only safe relative path, hash, media type, size, and source filename metadata. |
| Raw Garmin envelope | `garmin_raw_payloads` | One immutable source/stream/content-hash row. It records parse status, normalization/source contract versions, sanitized diagnostics, record count, optional fetch window, and R01 ingest/sync references. |
| Source identity | `garmin_sources` plus R01 provider/device/source rows | A stable `GarminSourceIdentity` is explicit. Attributed device code/model creates a `physical_devices` row; an unattributed account value has no device row. A client method or field never creates attribution. |
| Current typed projection | `garmin_source_records`, `garmin_daily_records`, `garmin_sleep_records`, `garmin_activity_records`, `garmin_intraday_records`, `garmin_fit_records` | A source record is keyed by `(garmin_source_id, idempotency_key)` from #29. The shared parent carries temporal/provenance facts; each stream has a separate typed table. `original_fit` remains raw evidence with a small typed marker. |
| Scalar values | `garmin_record_metrics` | Scalar metric registry attached to the typed parent. It stores capability/metric identity, field path, unit, device evidence, and one of `missing`, `null`, `value`, or `invalid`. Numeric zero is stored as `state=value` and `value_number=0`. |
| Sleep intervals | `garmin_sleep_stage_intervals` | Stages are interval rows with ordinal, UTC instants when available, original local wall-time evidence, offsets/zones, and level. The full temporal DTO is retained in sanitized JSON columns for replay. |
| Coverage/freshness | R01 `coverage_intervals` and `sync_stream_state` | Garmin does not create a second coverage model. Coverage status/counts are recorded through the R01 repository; stream freshness is the monotonic `last_attempt_at`/`last_success_at`/watermark state. Missing, failed, unavailable, and confirmed-empty are never encoded as zero. |

## Replay and correction semantics

The raw file and raw payload row are immutable. Rewriting the same source/stream/content hash
returns the existing row. A normalized record is an idempotent current projection keyed by the
stable #29 key: exact retries do not create another parent, typed marker, metric row, or sleep
stage. A refreshed payload with the same stable source-record ID creates a new raw evidence row
and updates the current projection while retaining the earlier raw bytes. An id-less semantic
record follows the #29 semantic key and therefore creates a different projection only when its
present typed metric set or temporal identity changes.

The persistence facade can also create the ordinary R01 `provider_sync` batch/event atomically.
Invalid results still retain their raw evidence and sanitized failure state; no partial typed
record is invented. The caller owns the SQLAlchemy transaction and may roll the complete operation
back.

## Temporal and presence rules

- `calendarDate` is stored as a local `Date`; it is never converted to UTC midnight.
- UTC instants are stored in UTC. The original local timestamp string, wall time, numeric offset,
  zone, and source field names remain separate columns.
- A genuinely local-only naive time keeps `temporal_precision=local` and has no invented UTC value.
- The textual R02 `source_instance_id` stays in `garmin_sources`; the shared R01 acquisition row
  uses its natural provider/device/input identity because its legacy instance column is UUID-only.
- Metric `missing`, JSON `null`, explicit numeric zero, and `invalid` are distinct persisted states.
- Diagnostics and unknown-field records store codes/shapes/paths only; raw values remain in the
  content-addressed artifact.

## Offline API boundary

`healthcheck.garmin.persistence.GarminPersistenceRepository.persist_result` accepts a
`GarminNormalizationResult` and caller-supplied bytes (or a validated synthetic fixture/mapping)
plus a `ContentAddressedGarminPayloadStore`. It performs no provider discovery or network I/O.
`GarminCoverageRepository.record` is a persistence adapter for existing R01 coverage/sync tables;
it does not infer availability from the static capability matrix.
