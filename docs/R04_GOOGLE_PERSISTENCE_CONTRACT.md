# R04 Google Health persistence contract

This is the offline persistence foundation for R04 (#86). It stores synthetic
Google Health identity, immutable raw response evidence, acquisition
observations, and a minimum typed-record shell. It does not authenticate, call
Google, run production sync/backfill, or perform typed health normalization
beyond that shell.

## Identity dimensions

These dimensions must not be collapsed:

1. **Stable provider/source/device identity** (`google_sources`) — only from
   explicit provider metadata. Query mode and `dataSourceFamily` are not part
   of this key. The same provider dataSource observed through
   `list` / `reconcile` / `rollUp` / `dailyRollUp` is one logical source.
2. **API acquisition mode** — stored on observations and current records.
3. **`dataSourceFamily` filter** — full resource URI such as
   `users/me/dataSourceFamilies/google-wearables`.
4. **Data type/stream** — sleep, heart-rate, HRV, daily vitals.
5. **Observation/fetch window/run** — immutable acquisition provenance.

Family-only aggregates use `source_kind=family_aggregate` and remain
unattributed. `google-wearables` without explicit device metadata never
creates a Fitbit physical device. Source-specific list evidence and family
aggregates stay separately addressable.

## Storage layers

| Layer | Tables | Contract |
| --- | --- | --- |
| Raw bytes | `raw_artifacts` plus `artifacts/google/payloads/<aa>/<sha256>.<ext>` | Content-addressed reuse. |
| Raw envelope | `google_raw_payloads` | One immutable source/stream/content-hash row. |
| Observation | `google_payload_observations` | Query mode, family, window, and sync run. Exact retries converge by `observation_key`. |
| Source identity | `google_sources` plus R01 provider/device/source rows | Textual dataSource or family URI lives here; R01 `source_instance_id` stays UUID-only. |
| Current typed shell | `google_source_records`, `google_sleep_records`, `google_record_metrics` | List vs rollup identities stay distinct. Numeric zero is `state=value`. String-encoded provider numerics stay in `value_text` without coercion. |

Generic spine reuse is unchanged: `providers`, `physical_devices`,
`acquisition_sources`, `raw_artifacts`, `ingest_batches` / `ingest_events`,
`sync_runs` / `sync_stream_state`, `coverage_intervals`. Google data is never
written into `garmin_*` tables.

## Migration

Revision `0009_google_persistence_contract` is additive only. It does not
recreate populated R01–R03 parents and does not migrate Garmin/Xiaomi rows.
`ondelete=RESTRICT` matches existing evidence semantics.
