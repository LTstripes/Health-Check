<a id="book--architecture-and-data-contracts"></a>
# Architecture and Data Contracts

This is the complete governing architecture, data, identity, selection and
versioned evidence/API contract book. Release-numbered contracts below remain
normative where explicitly retained; a released slice is not automatically
obsolete. Historical release plans and execution evidence are in the
[Wiki history map](PROJECT_WIKI.md#history-map), not additional active contracts.
Product meaning/UI is in [Product](PRODUCT_VISION.md); operator actions are in
[Owner Operations](OWNER_OPERATIONS.md). Examples describe contracts and grant
no provider, migration, deployment or data-write authority.

<a id="book--contents"></a>
## Contents

- [Common invariants and vocabulary](#common-invariants)
- [Source/domain contract matrix](#source-domain-matrix)
- [System, runtime and data flow](#system-and-runtime)
- [Logical model, synchronization, coverage and time](#logical-model)
- [Weight and optional openScale contract](#weight-contract), [photo provenance](#photo-provenance)
- Garmin: [capabilities](#garmin-capabilities), [normalization](#garmin-normalization),
  [persistence](#garmin-persistence), [reconciliation](#garmin-reconciliation),
  [Steps versions](#garmin-steps), [HRV recovery](#hrv-calendar-recovery)
- [Google persistence and auth boundary](#google-persistence)
- [Sleep agreement](#sleep-agreement), [saved sleep](#saved-sleep),
  [metric source selection](#metric-source-selection), [cycling](#cycling-source-discovery)
- [Analytic input and Stress versions](#analytics-and-stress)
- [Context](#context-capture), [UI evidence states](#ui-evidence-states)
- [Laboratory intake v1](LAB_INTAKE_V1.md): local PDF + transcription staging,
  explicit confirmation and full-snapshot revisions (#348)
- Evidence: [period](#evidence-period), [sleep](#evidence-sleep),
  [activity](#evidence-activity), [combined versions](#evidence-combined)
- [MCP boundary](#mcp-boundary), [technical decisions](#technical-decisions)


<a id="common-invariants"></a>

<a id="common-invariants--common-invariants-and-vocabulary"></a>
## Common invariants and vocabulary


<a id="common-invariants--must"></a>
### MUST

- Retain source provenance and practical raw evidence.
- Preserve competing source values and historical revisions.
- Separate physical device, provider/input method, and measurement algorithm.
- Version parsers, derived algorithms, and canonical rules.
- Distinguish Xiaomi-app S400 composition from openScale S400 composition.
- Use typed entities for sessions/intervals/activities/series.
- Calculate analytics deterministically and return coverage/exclusions.
- Require explicit confirmation for uncertain image extraction.
- Permit idempotent replay and historical reprocessing.
- Keep provider-native and Health-Check-derived scores distinctly named.
- Gate conclusions on actual device/account data rather than client method availability.

<a id="common-invariants--must-not"></a>
### MUST NOT

- Silently merge incompatible body-composition algorithms.
- Delete losing source values after canonical selection.
- Treat missing, unknown, or unsupported measurements as zero.
- Let an LLM calculate long raw time series or mutate the health store through a read credential.
- Present a derived score as official Fitbit/Garmin output.
- Treat endpoint existence as Vivoactive 5 feature support.
- Copy unlicensed, GPL, or AGPL code into the core contrary to the chosen reuse boundary.
- Require enterprise infrastructure for this personal application.
- Present consumer BIA, wearable associations, or LLM interpretation as diagnosis or causation.

<a id="common-invariants--vocabulary-and-absence-states"></a>
### Vocabulary and absence states

| Term | Exact meaning |
| --- | --- |
| Raw artifact | Immutable original bytes with content hash and safe local reference; not a selected metric. |
| Acquisition/normalization observation | Immutable receipt of one source/window/run/interpretation, retaining its own chronology even when raw bytes repeat. |
| Current projection | Typed derivative selected under that provider's recency/reconciliation rules; it is not the immutable history or automatically canonical. |
| Canonical selection | Versioned, reproducible references to eligible source/derived entities; losing values and revisions remain. |
| Source identity | Provider/input/application/account/device/algorithm identities are distinct. A friendly label or query family is not physical-device proof. |
| Eligibility | A metric/window/version-specific proof predicate. Method availability, non-empty containers and collection success do not establish it. |
| Coverage | Acquisition completeness, observed usable dates, wear coverage and a bounded local search's completeness are separate facts. A watermark is not contiguous history. |
| Snapshot | A physical SQLite read transaction. A restored data copy's provenance/age and a persisted report snapshot are separate meanings and require separate evidence. |
| Completed day | A stated civil-day policy and evaluation clock; Moscow display policy never proves Garmin's timezone or finality. |

Presence is `missing` (absent leaf), `null` (explicit JSON null), `value`
(including genuine numeric zero) or `invalid` (unsupported type/shape/unit under
the owning contract). Availability/coverage states such as `unavailable`,
`unknown`, `confirmed_empty`, `failed`, `partial` and `not_requested` do not
silently substitute for those leaves or for zero. `confirmed_empty` needs a
successful semantically complete fetch. UI request loading/error/no-change are
another layer. Each domain below retains its own resolution and fail-closed rules.


<a id="source-domain-matrix"></a>

<a id="source-domain-matrix--sourcedomain-contract-matrix"></a>
## Source/domain contract matrix


| Boundary | Authoritative identity/time | Selection and meaning | Detailed chapter |
| --- | --- | --- | --- |
| Weight/photo | Source session + metric algorithm; date-only/minute/instant precision | Confirmed non-superseded inputs; no composition-group bridge | [Weight](#weight-contract), [photo](#photo-provenance) |
| Garmin raw/current | Source + immutable original + observation; provider source time distinct from acquisition | Stable record/reconciliation identity; only complete authoritative collections retire absences | [Normalization](#garmin-normalization), [persistence](#garmin-persistence), [reconciliation](#garmin-reconciliation) |
| Google raw/current | Explicit Google source/context and path-free instant/interval identity | Raw LIST separate from aggregate/reconcile context; no family-to-device inference | [Google](#google-persistence) |
| Sleep agreement | Exact source and local wake date; device/account/family roles remain distinct | Legacy device gate and account-observation eligibility are not canonical switching | [Agreement](#sleep-agreement), [saved sleep](#saved-sleep) |
| Steps observed v1 | Returned strict calendarDate + original hash | Distinct-count ambiguity; no correction authority, collection/finality claim or GET projection | [Steps](#garmin-steps) |
| Steps completed v2 | Latest proved observation after Moscow day boundary | Receipt amendment permits only proven terminal partial acquisitions; current/future excluded | [Steps](#garmin-steps) |
| Steps all-time v1 | One exact source, one read snapshot, one aware evaluation | Global 4096/4096/4096 metadata/provenance/original bounds, 1 MiB/original, 16 MiB total, cooperative 5 seconds; incomplete means no statistics | [Steps](#garmin-steps) |
| Analytic input/Stress | Versioned input manifest and source-local/date or explicit Moscow policy | v2/v3/v4 adapter, baseline method and frozen legacy shape/hash remain distinct | [Analytics](#analytics-and-stress) |
| Context | Stable logical event + append-only revision + explicit temporal precision | Original text is evidence, never model tool authority | [Context](#context-capture) |
| Evidence/MCP | Explicit caller profile/source/window/clock + versioned whitelist/hash | Bounded saved reads, no implicit deployment/connection, no raw/SQL/write capability | [Evidence](#evidence-period), [combined](#evidence-combined), [MCP](#mcp-boundary) |

The matrix is a navigation aid, not a replacement for the full contracts below.
Different budgets are deliberately not unified: a v1 materialized Steps window
may retain independently complete cells, while incomplete completed/all-time or
combined-export searches suppress the affected aggregate or entire packet as
specified. A cooperative guard is not a hard end-to-end latency guarantee.


<a id="system-and-runtime"></a>

<a id="system-and-runtime--system-shape-runtime-and-data-flow"></a>
## System shape, runtime and data flow

The Android/openScale leg in the topology is an optional compatibility path, not the routine Owner Weight workflow. Screenshot import is the accepted operational path; #153 is not planned. Source availability is never inferred from the topology.

<a id="system-and-runtime--1-system-shape"></a>
### 1. System shape

```text
Windows laptop
┌────────────────────────────────────────────────────────────────────┐
│ Windows Task Scheduler                                             │
│          │ sync/report commands                                    │
│          v                                                         │
│ Health-Check Python runtime (shared deterministic services)        │
│   ├── provider adapters / explicit import services                 │
│   ├── typed analytics and canonical rules                          │
│   ├── loopback dashboard/read/import listener                      │
│   ├── optional separate private-LAN ingest-only listener           │
│   ├── report builder -> renderer -> notifier interfaces            │
│   └── SQLite WAL + local artifact store outside Git                │
└────────────────────────────────────────────────────────────────────┘
             ^                       ^                    |
             |                       |                    v
       Garmin Connect          Google Health API      external LLM
                                                        via bounded
Android phone                                           read tools
┌──────────────────────────────────────────────┐
│ Xiaomi S400 -> BLE -> openScale              │
│                         -> openScale-sync     │
│                         -> authenticated HTTP│
└──────────────────────────────────────────────┘
```

One local codebase and database are enough. The loopback UI/read/import ASGI app and optional LAN ingest-only ASGI app run as separate listeners/processes so LAN binding cannot expose dashboard or write/admin routes; both reuse the same application services and SQLite WAL. Do not add Redis, Celery, Kafka, Postgres, containers, Kubernetes, multi-tenancy, or SaaS authentication without a measured need. Long sync/report jobs run as idempotent CLI/application-service commands invoked by Windows Task Scheduler.

<a id="system-and-runtime--2-runtime-responsibilities"></a>
### 2. Runtime responsibilities

<a id="system-and-runtime--windows-laptop"></a>
#### Windows laptop

- Python 3.12+, FastAPI/Uvicorn, SQLAlchemy/Alembic, SQLite WAL.
- Runtime state is configurable and always outside the checkout. The selected durable Owner profile and code/control roles are defined in [Owner Operations](OWNER_OPERATIONS.md#machine-layout); `%LOCALAPPDATA%\Health-Check` remains the product default for generic/bootstrap use.
- Dashboard/read/import listener bound only to loopback.
- Optional separate private-LAN ingest-only listener/port exposing only webhook plus non-sensitive liveness; stable sender UUID and rotatable credential are independent.
- Prefer HTTPS or a trusted encrypted private overlay. Plain trusted-LAN HTTP requires explicit opt-in and a confidentiality warning; public exposure is unsupported.
- Provider tokens/secrets outside Git, ultimately in Windows Credential Manager/DPAPI or an equivalently user-scoped secret store.
- Source artifacts such as images, raw JSON, and FIT files in a content-addressed local artifact directory with database references.
- Stable is persistent owner data. Release/UAT profiles are disposable verified backup/restore clones; candidate validation never resets or repurposes Stable.

<a id="system-and-runtime--android-phone"></a>
#### Android phone

- openScale performs S400 BLE collection.
- openScale-sync forwards data through its generic webhook.
- Both are external GPL applications; Health-Check communicates through their published data boundary and does not incorporate their code.
- Health Connect is a future/secondary bridge, not the preferred S400 path, because it cannot represent the complete openScale record.

No custom Health-Check Android application is required for R01–R05.

<a id="system-and-runtime--3-end-to-end-data-pipeline"></a>
### 3. End-to-end data pipeline

```text
immutable raw artifact / provider response
                    |
                    v
typed source record with device/provider/algorithm provenance
                    |
                    v
versioned canonical selection (references, never replaces, source data)
                    |
                    v
deterministic analytics + coverage + disagreement
                    |
                    v
versioned evidence packet / saved report
                    |
           dashboard and bounded AI tools
```

Raw, source-specific, canonical, derived, and narrative layers are different contracts. Reprocessing creates a new parser/algorithm/rule version while retaining the earlier evidence.

Runtime preparation/startup can create or migrate its selected profile. Do not use a migration-capable startup as a read-only diagnostic. Updating code does not refresh a restored copy or recover providers.


<a id="logical-model"></a>

<a id="logical-model--logical-model-synchronization-coverage-and-time"></a>
## Logical model, synchronization, coverage and time

<a id="logical-model--5-canonical-logical-data-model"></a>
### 5. Canonical logical data model

<a id="logical-model--shared-evidenceprovenance"></a>
#### Shared evidence/provenance

- `providers`
- `physical_devices`
- `acquisition_sources` (provider + input method + application/configuration)
- `measurement_algorithms` (producer, version, parameters, compatibility group)
- `raw_artifacts` (content hash, type, local reference)
- `ingest_batches` / `ingest_events`
- `sync_runs` / `sync_stream_state`

<a id="logical-model--typed-source-data"></a>
#### Typed source data

- `measurement_sessions` and `scalar_measurements` for sparse scalar/vendor values;
- `sleep_sessions` and `sleep_stage_intervals`;
- `activities` plus FIT/raw-detail references;
- `series_streams` and bounded time-series chunks/points for intraday data;
- `context_events` and versioned tag interpretations;
- later, typed lab documents/results.

This is not one EAV table. A scalar metric registry is appropriate for scalar values; intervals, sessions, stages, activities, and high-frequency streams retain their own semantics and constraints.

<a id="logical-model--interpretation-and-output"></a>
#### Interpretation and output

- `derived_measurements` with algorithm/version and input references;
- `canonical_rule_sets`, `canonical_selection_runs`, and `canonical_selections`;
- `coverage_intervals`/calculated coverage summaries;
- `report_runs`, evidence-packet snapshots, rendered artifacts, and `delivery_attempts`;
- later, `experiments` and exposure/evaluation records.

Canonical selections point to immutable source or derived entities. They do not overwrite values. Corrections are append-only superseding revisions. A rule run records its exact input set/rule hash so historical output can be reproduced.

<a id="logical-model--6-idempotency-and-synchronization"></a>
### 6. Idempotency and synchronization

Each provider/stream defines:

- stable external ID when available;
- semantic fingerprint fallback;
- initial backfill interval;
- incremental watermark/cursor;
- explicit trailing reconciliation window, without treating that watermark as contiguous history;
- stable collection identity and authoritative retirement, with version-aware reprocessing of stored raw evidence;
- retry/backoff and failure classification;
- source coverage calculation.

Accepted post-R05 owner-operation rules add one profile-scoped external-runtime operation lock across supported Garmin/Google sync/backfill/refresh/reprocess paths and explicit stale-SyncRun maintenance. The maintenance path is non-reentrant, cutoff-bounded and terminalizes only provably orphaned `running` lifecycle rows as `failed`; it does not reset checkpoints, delete evidence or infer success from partial persistence.

For Google instant sample streams (heart rate, HRV, SpO2, respiratory-rate sleep summary), logical identity must not depend on response position/source-field path/record index. Canonical instant identity uses source + stream + acquisition context + canonical UTC instant; HR rollup/daily-rollup use a separate path-free interval identity. Provider corrections across orderable later epochs update the current projection; same-epoch/unorderable divergent revisions fail closed.

The raw transport event is persisted before or atomically with normalization. Duplicate retries link to the existing semantic record and succeed without duplicating measurements. Receive order never defines event order. A parser failure keeps replayable raw evidence and a sanitized status.

Photo artifacts deduplicate by content hash. Semantic convergence of separately transported copies requires trustworthy same-source-event identity; source/device/timestamp/metric/algorithm context must not conflate genuine equal-valued weigh-ins. Equal date/value alone is not that proof: #228 cross-image event deduplication is research, not an implemented fuzzy merge. The accepted artifact/replay/correction behavior remains unchanged. For openScale-sync, a stable configured sender-instance UUID is independent of its rotatable bearer secret, so credential rotation cannot fork source identity.

<a id="logical-model--7-coverage-contract"></a>
### 7. Coverage contract

Coverage is returned with every non-trivial analytic/report result:

- requested and actually covered interval;
- observed versus expected days/nights/sessions when an expectation is meaningful;
- freshness and longest gaps;
- per-source/per-algorithm breakdown;
- failed, unavailable, confirmed-empty, and unknown intervals;
- rule version and exclusions.

Sparse voluntary streams such as weekly weight use a configured cadence. Continuous streams use expected time/day coverage. Missing and zero are never interchangeable. Analytics has explicit minimum-count/span gates; an overall `HIGH/MEDIUM/LOW` label, if rendered, is secondary to these facts.

<a id="logical-model--8-time-and-lag-semantics"></a>
### 8. Time and lag semantics

- Persist a UTC instant when one exists, the source local timestamp, numeric offset, and zone identifier when available.
- Preserve date-only precision rather than inventing a midnight instant.
- A sleep session is keyed analytically to the local **wake date**.
- `lag 0` means the same analytic date; `lag +1` means the next analytic date.
- An exposure on evening X can align with the sleep session waking X+1 and morning HRV on X+1.
- Travel/timezone policy remains a later feature, but retained offsets allow reprocessing.

<a id="logical-model--completed-day-overview-presentation"></a>
#### Completed-day Overview presentation

Only the Overview Sleep, Stress and Body Battery cards use the completed Moscow
window described above. Their source dates are not relabelled or recalculated.
Sleep averages eligible Garmin durations once per existing local wake date;
Stress averages the eligible daily `avgStressLevel` values once per source day.
They reuse the existing scalar-series eligibility, partial/zero and ambiguity
rules, retain source selection, and never average repeated observations within a
day. Both reads retain the existing 400-day / 2,000-point bounds; an incomplete
read exposes no partial-prefix mean and a long window is not silently clipped.
One eligible day is sufficient, with compact n/N coverage; missing days never
become zero. Partial observations remain labelled. Sleep's final mean is rounded
half-up to a whole second only for human duration display; Stress retains the
existing up-to-two-decimal format. The selected-day 28-day Stress baseline reader
remains available separately and its interpretation is unchanged.

Lag direction is named in APIs and evidence packets; ambiguous `correlation(metric_a, metric_b, lag=1)` contracts are forbidden.


<a id="read-snapshots"></a>

<a id="read-snapshots--compound-physical-read-snapshots"></a>
## Compound physical read snapshots

<a id="read-snapshots--compound-read-consistency--227-accepted"></a>
##### Compound read consistency — #227 accepted

Weight/Period Brief compound reads establish one physical SQLite snapshot including
assembled queue/freshness. Clean pre-BEGIN or prior-transaction ORM objects must
align; expire_on_commit=False alone is insufficient. The local helper preserves
caller-owned transaction/close, rejects pending new/dirty/deleted state before cache
actions, retains flushed writes and expires clean caches on new/reused physical
transactions. It does not globally change engine/writer/provider semantics. The
initial missed pre-BEGIN cache case required independent review/remediation.


<a id="weight-contract"></a>

<a id="weight-contract--weight-composition-and-optional-openscale-contracts"></a>
## Weight, composition and optional openScale contracts

<a id="weight-contract--xiaomi-s400"></a>
#### Xiaomi S400

Optional compatible live path (not routine Owner import):

```text
S400 encrypted BLE broadcast
  -> openScale on Android (MAC + bind key; openScale S400 calculation)
  -> openScale-sync generic webhook
  -> authenticated Health-Check ingest endpoint
  -> raw request + typed measurement session
```

Historical/fallback path:

```text
Xiaomi-app screenshot/photo
  -> immutable local image
  -> versioned vision extraction
  -> editable candidate fields
  -> explicit human confirmation
  -> typed source measurement
```

The physical scale, input provider/application, and body-composition algorithm are separate. Xiaomi-app body composition and openScale S400 composition are different, non-equivalent algorithm groups unless a future same-weigh-in overlap study proves and versions a calibration. Weight may remain one series when physical-device/unit identity is clear; algorithm-derived composition may not.

The following R01 logical identities, algorithms, API families and error behavior remain governing. The original release scope/sequence/checklist are historical, not a new launch plan. Suggested topology names are descriptive; ownership boundaries are required. Future entities in the original model are explicitly not a claim that every table exists.

<a id="weight-contract--5-suggested-project-topology"></a>
### 5. Suggested project topology

The implementation may vary names, but ownership boundaries are required:

```text
src/healthcheck/
  app.py                 # application composition only
  cli.py                 # serve/migrate/reprocess commands
  config.py
  db/                    # engine, sessions, migrations
  domain/                # provenance and typed domain records
  ingestion/
    photo/               # extractor port, normalization, confirmation
    openscale/           # webhook contract and normalization
  canonical/             # versioned selection rules
  analytics/             # pure weight/composition/coverage functions
  web/
    ui_app.py            # loopback dashboard/read/import application
    ingest_app.py        # LAN ingest-only application; no UI/read/admin routes
    templates/           # local templates/static assets
tests/
  fixtures/              # synthetic/non-personal payloads and images only
scripts/start.ps1
```

Framework objects must not enter pure analytics functions. Routes call application services; services transact through repositories; deterministic analytics consumes typed records.

<a id="weight-contract--6-r01-logical-data-model"></a>
### 6. R01 logical data model

Names may be adjusted to existing conventions created during implementation, but the following identities and constraints are normative.

<a id="weight-contract--reference-identities"></a>
#### Reference identities

`providers`

- stable evidence-based code such as `xiaomi_home`, `xiaomi_app_unknown`, or `openscale`;
- display name;
- provider kind.

`physical_devices`

- manufacturer/model code (`xiaomi_s400`);
- optional owner-assigned instance identifier;
- no provider or algorithm meaning embedded in the device code.

`acquisition_sources`

- provider reference;
- physical-device reference when known;
- input method (`photo_import`, `webhook`, later `provider_api`);
- stable sender-instance UUID for automated sources, independent of any rotatable credential;
- source application and version when known;
- source configuration snapshot/fingerprint needed to interpret the data.

`measurement_algorithms`

- stable algorithm code and version;
- metric family;
- producer/owner (`xiaomi`, `openscale`, `healthcheck`, or unknown);
- parameter/configuration snapshot where relevant;
- explicit compatibility/equivalence group;
- verification state.

Algorithm identity belongs on each measurement value, not only on the physical session: scale weight and app-derived body fat from the same weigh-in may have different algorithms.

<a id="weight-contract--evidence-and-import-lifecycle"></a>
#### Evidence and import lifecycle

`raw_artifacts`

- immutable content hash, kind, media type, byte size, relative storage path;
- source/original filename as metadata only;
- received time and source time when known;
- never stores an absolute machine-specific path in exported logical evidence.

`ingest_batches`

- acquisition source, parser/extractor name and version;
- start/end/status/counts;
- supports photo batches, webhook replay, and future provider runs.

`ingest_events`

- batch and raw-artifact references;
- provider stream and external record ID when available;
- semantic fingerprint fallback;
- received/source timestamps;
- parse/normalization status and non-secret diagnostic reason.

`import_candidates`

- ingest event and measurement-group key;
- proposed metric/value/unit/source time;
- extractor/model/prompt/schema versions;
- extractor-reported per-field confidence, nullable;
- edited value and user decision (`pending`, `confirmed`, `rejected`);
- confirmation timestamp.

Extractor confidence and human confirmation are separate fields. A constant invented confidence such as `0.9` is forbidden.

<a id="weight-contract--confirmed-measurements"></a>
#### Confirmed measurements

`measurement_sessions`

- acquisition source and raw/ingest provenance;
- temporal precision (`instant`, `minute`, or `date`) and an explicit source local date;
- source timestamp as UTC only when an instant/minute is actually known; it remains null for date-only evidence rather than inventing midnight;
- source local timestamp, UTC offset, and zone identifier when available;
- source record ID/fingerprint;
- confirmation/import status;
- optional superseded-session link.

`scalar_measurements`

- session reference;
- metric code, normalized numeric value, normalized unit;
- original value/unit retained in source evidence;
- measurement-algorithm reference;
- quality/reliability status from the source, not an invented score;
- optional superseded-measurement link.

Confirmed source measurements are append-only. A correction creates a revision that supersedes an earlier value; it does not erase the earlier evidence.

`derived_measurements`

- metric/value/unit;
- Health-Check algorithm code/version and parameters;
- explicit input measurement IDs or an input-set hash;
- computed time.

<a id="weight-contract--canonical-layer"></a>
#### Canonical layer

`canonical_rule_sets`

- rule-set name, integer version, effective period;
- serialized deterministic rule and its hash;
- creation reason.

`canonical_selection_runs`

- stable run ID and requested semantic scope/period;
- rule-set ID/version/hash;
- deterministic input-snapshot hash over sorted eligible source/derived IDs plus their revision/content hashes;
- software/build version, started/completed times, status (`running`, `succeeded`, `failed`), selection count, and sanitized failure reason;
- optional superseded-run link.

`canonical_selections`

- semantic metric/key/period;
- selected source or derived entity reference;
- mandatory selection-run reference;
- computed time and selection reason;

Canonical selection references immutable evidence; it does not copy over or delete losing values. A successful `(scope, rule_hash, input_snapshot_hash)` is idempotent: replay returns the existing successful run or a byte-equivalent ordered result, never a second competing success. A different rule or input hash creates a new run and may supersede an earlier run. Failed runs keep diagnostics but never become the active canonical set.

<a id="weight-contract--sync-and-coverage"></a>
#### Sync and coverage

`sync_runs`

- provider/stream, requested interval, actual interval, status, item counts, error category, start/end times.

`sync_stream_state`

- provider/stream, cursor/watermark where one exists, last success, last attempt, trailing-window policy, and current diagnostic status.

`coverage_intervals`

- provider/stream/metric and source identity;
- interval/resolution;
- status: `present`, `confirmed_empty`, `unavailable`, `failed`, or `unknown`;
- observed count, expected count when a cadence is defined, and calculation-rule version.

For an atomic coverage bin: `present` wins when evidence exists; otherwise an explicit capability block yields `unavailable`; otherwise a successful semantically complete fetch with no record yields `confirmed_empty`; otherwise a required failed fetch/ingest attempt without a later success yields `failed`; no conclusive attempt/evidence yields `unknown`. Do not encode any of these as zero. Sparse weight coverage is evaluated against an explicit expected cadence, not against an assumed daily stream.

<a id="weight-contract--future-typed-entities"></a>
#### Future typed entities

R02+ adds separate `sleep_sessions`, `sleep_stage_intervals`, `activities`, activity/FIT detail references, and intraday-series/chunk entities. Later releases add `context_events`, `report_runs`, and experiments. They must not be forced into `scalar_measurements` merely to avoid a migration. R01 need not create unused future tables.

<a id="weight-contract--7-metric-and-provenance-rules"></a>
### 7. Metric and provenance rules

- Canonical normalized units in R01 are kilograms and percentage points; the original unit/value remain reconstructable from raw evidence.
- `weight` is a direct physical measurement and may form a continuous canonical series across input methods only when device/unit identity is clear and no observed calibration break exists.
- `body_fat_pct`, source muscle mass, water, visceral-fat index, and similar BIA outputs are algorithm-dependent.
- A screenshot visibly sourced from Xiaomi Home but without an evidenced formula/build uses an identifier such as `xiaomi_home_s400_unknown_version`. If even the application is not evidenced, use a separate `xiaomi_s400_unknown_app_algorithm`; unknown does not mean equivalent.
- openScale values include the openScale app version and selected body-composition formula/configuration where the source exposes them. Unknown configuration remains its own non-equivalent group.
- `muscle_mass` is not renamed to `lean_mass`.
- Health-Check `estimated_fat_mass` and `estimated_lean_mass` are derived metrics, never provider-native values.

<a id="weight-contract--8-historical-photo-workflow"></a>
### 8. Historical photo workflow

The provider-neutral port is conceptually:

```python
class ImageMeasurementExtractor(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...
```

`ExtractionRequest` contains artifact ID/reference, declared locale/timezone hints, and target schema version; it never accepts an arbitrary filesystem path. `ExtractionResult` contains extractor/provider/model/prompt/schema versions and one or more measurement groups. Each candidate field contains metric code, source text when available, proposed value/unit/time, nullable model-reported confidence, and optional image-region evidence. Provider errors return a typed failure and leave the artifact replayable. Tests use a deterministic fake implementation; no live model call occurs in CI.

1. Upload one or many images.
2. Hash and durably store each image outside Git before extraction.
3. Exact duplicate content links to the existing artifact; the UI reports the duplicate.
4. Run a versioned extractor through a provider-neutral `ImageMeasurementExtractor` interface.
5. Normalize its output into per-field candidates. Structural validation may warn about impossible units or malformed timestamps but must not silently "repair" a health value.
6. Present candidate values, source timestamp, physical device, provider/input method, and algorithm identity for editing.
7. Explicit confirmation creates one source session and its scalar measurements in a transaction. Repeating confirmation is idempotent.
8. Rejection keeps the import audit row but creates no measurement.
9. Reprocessing uses the same immutable image with a new extractor version and creates a new candidate set; it does not mutate the earlier result.

For an unambiguous batch, the user may confirm selected rows together. The UI must still show exactly what will be committed. No extracted candidate becomes canonical merely because a model returned it.

<a id="weight-contract--9-openscale-sync-webhook-workflow"></a>
### 9. openScale-sync webhook workflow

- Implement the generic-webhook contract at openScale-sync `32e38651cf78bbf230e33d17abb00b147130f305`. The top-level `event` is `insert`, `update`, `delete`, `clear`, or `test`. A single insert/update carries `id`, `userId`, `username`, `date`, convenience measurements, and optional `values[]`; a batch carries `measurements[]`. Each `values[]` item carries `key`, `name`, `unit`, `isDerived`, and optional numeric `value` or `text`.
- openScale-sync copies its configured authorization text verbatim to the HTTP `Authorization` header. Configure a narrow random `Bearer <token>` value; Health-Check validates that ingest-only secret independently from dashboard/read/admin access and never logs it.
- Preserve the original request bytes and media type before normalization when practical.
- `source_instance_id` is a stable configured UUID for one openScale-sync installation and is independent of its credential. The credential-to-instance binding is configuration; rotating the secret does not change data identity. For insert/update, the primary idempotency identity is `(source_instance_id, userId, id)`. Delete lacks `id`, so its fallback identity is `(source_instance_id, userId, measured_at)`. If a future sender omits stable identity, compute a semantic fingerprint from source instance, user, timestamp, normalized metric set, and algorithm/configuration identity. A payload hash alone is insufficient when transport metadata changes.
- A duplicate retry returns success and the existing event/session IDs without creating measurements again.
- Malformed JSON, invalid authentication, or an invalid top-level envelope returns non-2xx and commits no acknowledged batch. For a structurally valid batch, persist the raw envelope once, then process each measurement in a savepoint: valid items commit idempotently; invalid items become durable quarantined/failed ingest events with sanitized reasons. Return 2xx only after both valid and failed item states are durable. Because openScale-sync ignores response semantics, failed items surface in Health-Check diagnostics and are reprocessable from raw evidence rather than blocking every valid item.
- `values[]` presence is authoritative. The sender's missing convenience fields may be serialized as numeric zero; absence must never become a real zero measurement. Unknown fields are retained in raw evidence and ignored safely; required-field absence is explicit.
- `delete` and `clear` create recoverable source tombstones and canonical recomputation; they never physically delete immutable raw history.
- A trailing/backfill/manual-full-sync replay may send old records in any order and can duplicate a request after a lost response. Valid items deduplicate; the same invalid item links to its existing failed event. Analytics sorts by source time, not receive time. Any HTTP 2xx means only receiver acknowledgement, so Health-Check commits durably before responding.

Live phone-to-laptop proof is desirable but is not a code acceptance blocker if owner-specific bind-key/MAC or Android setup is unavailable. The blocker and exact manual verification steps must then remain documented as `UNVERIFIED`.

<a id="weight-contract--10-r01-api-and-ui-contract"></a>
### 10. R01 API and UI contract

Required routes are split by listener (path spelling may vary only if documented consistently).

Loopback UI/read/import listener only:

- `GET /healthz` — process/database/migration health without secrets or personal values.
- `POST /api/imports/photos` — create a batch and pending candidates; never confirm implicitly.
- `GET /api/imports` and `GET /api/imports/{id}` — batch/candidate status.
- `POST /api/import-candidates/confirm` — explicit selected-row confirmation, idempotent.
- `POST /api/import-candidates/reject` — retain audit, create no measurement.
- `GET /api/weight/series` — canonical/raw/algorithm-filtered points plus provenance.
- `GET /api/weight/summary` — trend, slope, composition, coverage, and explicit unavailable reasons.
- `GET /` — local weight dashboard.

LAN ingest-only listener:

- `GET /healthz` — separate non-sensitive liveness response;
- `POST /api/ingest/openscale` — authenticated sender contract and no other mounted product routes.

No generic SQL route and no LLM route exist in R01.

Dashboard minimum:

- raw weight points, time-aware trend, optional configured goal, current value/date;
- trailing slope with observation count/span or an unavailable reason;
- separate body-composition series by algorithm compatibility group;
- estimated fat/lean and source-provided muscle clearly labelled;
- similar-weight comparison without a causal or precision claim;
- observed/expected coverage, freshness, and longest gap;
- point-level provenance drill-down;
- import queue/history;
- persistent, obvious warning at every algorithm boundary.

<a id="weight-contract--11-deterministic-analytics-v1"></a>
### 11. Deterministic analytics v1

All calculations operate on confirmed canonical observations, use source time, and return input count, covered span, algorithm version, and unavailable reason.

<a id="weight-contract--111-display-weight-trend"></a>
#### 11.1 Display weight trend

1. Reduce multiple canonical observations on one local date to the daily median while preserving drill-down.
2. Sort by observation time.
3. Apply time-aware exponential smoothing with a 21-day half-life:

```text
alpha_i = 1 - 2^(-delta_days / 21)
trend_i = alpha_i * value_i + (1 - alpha_i) * trend_(i-1)
```

The first observation initializes the series. This is `weight_trend_taewma_v1`. It is preferred to per-observation `alpha=0.1` because weekly/irregular gaps must affect smoothing. Raw points remain visible. Kalman, LOESS, and STL are not R01 defaults.

<a id="weight-contract--112-rate-of-change"></a>
#### 11.2 Rate of change

Use Theil–Sen median pairwise slope over daily medians in the trailing 90 calendar days, converted to kg/week. Require at least six observations spanning at least 42 days; otherwise return unavailable. Report count and span, and do not manufacture a confidence interval in R01. This is `weight_rate_theil_sen_90d_v1`.

<a id="weight-contract--113-body-composition"></a>
#### 11.3 Body composition

For a single confirmed session with compatible weight and body-fat inputs:

```text
estimated_fat_mass_kg = weight_kg * body_fat_pct / 100
estimated_lean_mass_kg = weight_kg - estimated_fat_mass_kg
```

Record both input IDs under `body_composition_decomposition_v1`. Do not combine a weight from one date with body fat from another. Smooth/display composition only within one algorithm compatibility group. Display sensible precision (normally one decimal) without discarding stored source precision.

<a id="weight-contract--114-recomposition-view"></a>
#### 11.4 Recomposition view

R01 provides evidence, not a classifier:

- time series and a weight-vs-body-fat/fat-mass scatter grouped by algorithm;
- an optional similar-weight comparison only for same-algorithm observations at least 28 days apart and within 1% body weight;
- exact dates, source algorithm, and deltas;
- no automatic claim that a small BIA change is real muscle gain or fat loss.

If there is no compatible pair, show why. Never bridge an algorithm boundary to create a comparison.

<a id="weight-contract--115-coverage-v1"></a>
#### 11.5 Coverage v1

For a requested period and configured weight cadence (default seven days), return:

- observed unique measurement dates;
- expected cadence bins and covered bins;
- oldest/latest observation and freshness;
- longest gap;
- algorithm/source breakdown;
- per-bin state plus counts/intervals for `present`, `confirmed_empty`, `unavailable`, `failed`, and `unknown`.

Coverage is evidence metadata, not a replacement value. Trend and slope availability gates remain separate from an overall label.

<a id="weight-contract--12-canonical-rule-v1"></a>
### 12. Canonical rule v1

The initial rule is intentionally small:

1. Eligible evidence is confirmed and not superseded.
2. Exact duplicate imports collapse to one semantic source record while retaining all linked raw artifacts/attempts.
3. Weight selects the latest confirmed revision for each semantic weigh-in.
4. Composition selection requires an explicit algorithm compatibility group; the default rule never crosses groups.
5. Derived measurements are eligible only when all inputs are eligible and their derivation version matches the requested analytics version.

The rule is serialized, hashed, and tested with reordered input. Identical input plus identical rule must yield byte-equivalent ordered selection output.

<a id="weight-contract--13-security-and-privacy"></a>
### 13. Security and privacy

- Use synthetic fixtures only in the repository and CI.
- Keep runtime data and logs under the external data directory; logs contain IDs/counts, not payload bodies or measurements by default.
- Do not log authorization headers, tokens, raw photos, or extracted personal values.
- Use a stable sender UUID plus a separate high-entropy rotatable webhook credential. An environment override is allowed; persisted secrets must live outside Git and be documented.
- Limit upload size and accepted media types; generate storage names rather than trusting filenames.
- Keep UI/read/import routes loopback-only. The optional LAN listener is ingest-only, uses a separate port/app, and follows the explicit encrypted-overlay/HTTPS or warned trusted-LAN transport mode; public exposure is unsupported.
- No analytics or import endpoint may accept an arbitrary filesystem path.
- The UI must warn that consumer BIA is non-clinical and method-sensitive.

<a id="weight-contract--14-error-and-reprocessing-behavior"></a>
### 14. Error and reprocessing behavior

- Every import/webhook event ends as received, parsed, pending-confirmation, committed, rejected, duplicate, or failed.
- Failures expose a stable reason code plus a sanitized message.
- A failed parser run leaves immutable raw evidence available for a later reprocessor.
- Candidate edits are audited; confirmed measurements are revised by supersession.
- Analytics never drops an invalid point silently: excluded points and reasons are returned in metadata.
- Confirmation is transactional. A structurally valid webhook batch stores its envelope transactionally and normalizes items with savepoints under the durable mixed-validity policy above.


<a id="photo-provenance"></a>

<a id="photo-provenance--screenshot-provenance-and-correction-semantics"></a>
## Screenshot provenance and correction semantics

<a id="photo-provenance--auto-confirm-boundary"></a>
### Auto-confirm boundary

The command commits the R01 photo evidence and extracted candidates before deciding whether to confirm. It calls the existing `PhotoImportService.confirm()` only when all of these hold:

- exactly one image, one extraction set and one plausible measurement group;
- exactly one evidenced `weight` and no repeated or unsupported metric;
- every candidate has a finite value, supported unit, source date and consistent temporal precision, with no normalization warnings;
- all candidates are pending and have Xiaomi Home / Xiaomi S400 / `photo_import` provenance.

The existing R01 normalizer and confirmation service remain responsible for kg/percentage normalization, date-only precision, session identity, photo content-hash idempotency, Xiaomi weight/composition algorithm identity, measurement writes and canonical recomputation. The Owner adapter supplies Xiaomi Home/S400 acquisition context; it does not relabel composition values or invent a timestamp, confidence, formula or missing value. A date-only source remains date-only.

Any conflicting group, candidate set, duplicate metric, missing value/date/unit, unsupported metric/unit, warning, unrecognized source/device or confirmation validation failure returns `NEEDS_REVIEW`. The image and candidate audit stay in the existing photo workflow, but no semantic measurement is confirmed. A replay of already handled bytes returns `DUPLICATE`; a replay with unresolved candidates returns `NEEDS_REVIEW`. If the same bytes yield a new extraction set, the new interpretation is preserved for review and is never auto-confirmed.

A changed Owner-assisted sidecar for already-imported bytes follows the same rule even when it reuses the stored extraction identity: the changed interpretation is appended as its own pending correction candidate set in the existing review queue, linked to the original photo event. The original artifact, original candidate set and confirmed semantic history are never overwritten, and nothing is confirmed before the Owner's explicit decision. Replaying the same changed sidecar resolves to that same pending set (`NEEDS_REVIEW`, no duplicate evidence rows); after the correction has been confirmed, an exact replay is a no-op `DUPLICATE`. Confirming the staged correction uses the existing session/measurement revision mechanics, so the prior value is superseded but never erased; rejecting it leaves the current semantic and canonical state unchanged.

<a id="photo-provenance--metadata-origins-240"></a>
### Metadata origins (#240)

Every post-0015 `ImportCandidate` persists one complete canonical `metadata_origins_json`
map with exactly `provider_code`, `physical_device_code`, `source_application`,
`source_local_date` in `visible | owner_attested | workflow_profile | unknown`.
Database NULL is reserved exclusively for pre-0015 legacy rows and reads as
"origin not recorded"; there is no backfill, default, or history rewrite.

- The fixed `xiaomi_home / xiaomi_s400 / Xiaomi Home` workflow default, when the
  sidecar omits it, is `workflow_profile`, never visible/attested.
- `source_local_date` is never `workflow_profile`. It is `visible` when the
  sidecar carries it, `owner_attested` only for an explicit current-request
  `--owner-attested-date`, otherwise `unknown`. No clock/EXIF/filename/memory/
  prior-chat/default inference is permitted.
- Provider vision routes never accept attestation and never emit
  `workflow_profile` (`visible | unknown` only).
- Terminal-candidate immutability covers the new column; confirmed/rejected
  history stays immutable.

Replay/correction preserves #229:

- exact replay with equal core evidence plus equal origin map stays `DUPLICATE`;
- a fully legacy NULL set with unchanged core evidence uses the D1 read-time
  wildcard and stays `DUPLICATE` with zero provenance rewrite;
- changed core evidence follows normal #229 correction;
- a post-0015 provenance-only change is identity-bearing and stages a reviewable
  correction with its own `correction:` identity; distinct provenance claims get
  distinct identities.

<a id="photo-provenance--xiaomi-s400--r01"></a>
#### Xiaomi S400 / R01

- Routine Weight: Xiaomi Home/S400 screenshot → repo `health-weight-screenshot-import` skill → Owner-assisted strict extraction → R01 pipeline → Stable.
- openScale/openScale-sync remain external GPL applications and optional alternative contract. #153 is not planned; its historical numeric-userId issue is not a screenshot gate.
- Xiaomi-app and openScale composition remain distinct compatibility groups without an accepted paired-evidence calibration.
- #226 validates accepted screenshot algorithm identities before auto-confirm. Foreign explicit code, incompatible group or conflicting producer/metric-family metadata requires review before semantic writes; omitted permitted versions stay unknown.
- Model confidence is not confirmation policy. #229 reviewable changed-sidecar corrections and #240 metadata origins preserve history; date-only Owner attestation does not become visual evidence or invented time.
- #228 artifact vs source-event identity research is accepted, not cross-image dedup implementation. No fuzzy/date/value auto-merge, midnight inference or historical rewrite without trustworthy event proof.


<a id="garmin-provider-flow"></a>

<a id="garmin-provider-flow--garmin-provider-and-native-trainingbody-battery-flow"></a>
## Garmin provider and native Training/Body Battery flow

R02 uses the community `python-garminconnect` package as a pinned runtime dependency rather than building another private HTTP client. Initial sign-in/MFA is user-assisted; reusable auth state is stored outside Git. Each stream has explicit backfill and trailing-window reconciliation because unofficial endpoints and late provider updates do not provide a universal durable cursor.

Garmin payloads map into typed scalar, sleep, activity, and series entities. A library method only proves that a client endpoint exists; it does not prove that Vivoactive 5 produces the metric. Live account fixtures decide availability, and unknown/unsupported values remain unavailable. Current series identity prefers a stable provider timestamp/token over array position; an authoritative complete collection may retire absent members, and parser upgrades reprocess stored raw evidence only when explicitly requested. The incremental watermark is not contiguous history.

Training Phase B stores native status, load-balance, readiness and activity-list training fields through the immutable Garmin payload/observation and typed-record spine. `garmin-training-sync --start YYYY-MM-DD --end YYYY-MM-DD` is an explicit bounded acquisition of at most 14 readiness days and one Training Status response requested at the end date. Training Status `mostRecent` is **not** historical backfill: typed records use only provider source dates, and undated load-balance structures remain undated. The requested date lives in a separate acquisition row linked to the immutable observation. Multiple Readiness timestamps remain separate records. Device keys/IDs express association and activity listing `deviceId` expresses recorder association; neither proves metric producer identity. Ordinary `garmin-sync` retains its previous provider request set; activity Training Load and Training Effect are acquired only through its existing activity listing path. Missing, null, zero and invalid values remain separate field states. Training read access is a private deterministic service contract; owner presentation and live verification are separate gates.

Overview Body Battery (#394) reads the selected Garmin source's current typed
`intraday` / `body_battery` samples whose record path is
`payload.bodyBatteryValuesArray[index]` and metric path is
`payload.bodyBatteryValuesArray`. `garmin/sync.py` also synthesizes a scalar
`bodyBattery` alias from the last series member; that alias is not an additional
measurement. Existing `bodyBattery` / `bodyBatteryLevel` scalar rows cannot prove
direct versus adapted origin from their saved field path, so their eligibility
remains explicitly unknown. This reader neither reprocesses raw data nor changes
ingestion. Values require the Body Battery capability, `value` state, `points`,
a usable record and a finite numeric value, preserving the existing R02 finite
contract without introducing a product range; explicit zero remains a value.
Future UTC timestamps and unknown temporal precision are excluded. Source civil
dates are never compared with the host's calendar date or converted to UTC dates.
Date-only observations stay civil dates with unknown UTC chronology; no midnight
instant or host timezone is invented. Conflicting or
indistinguishable current sample coordinates exclude the day, including equal
numbers; date-only samples cannot resolve a multiple-sample collision. Replay and
correction selection remain the existing persistence/currentness contract.

Each eligible saved `source_local_date` contributes its maximum among eligible
measurements once. The Body Battery reader uses its entire supplied window unchanged.
The Overview UI alone selects completed Moscow days for Sleep, Stress and Body
Battery: rolling presets end yesterday in `Europe/Moscow`, retaining their day
count; a custom window retains its start and ends at the earlier of its selected
end and yesterday. An empty intersection shows no number. The actual card range
is visible, and no change applies to other screens, exports, Period Brief packets
or persisted source dates. Means
weight eligible days equally and retain exact rational arithmetic. Presentation
uses the existing format of up to two decimals, without #393 integer rounding or
its 400-day limit. Missing days are counted, never zero-filled. The read is bounded
to 100,000 candidate records per window and 10,000 per day; exceeding either cap
or a read failure returns no mean, maxima or denominator from a partial search.
These are maxima of saved measurements, not provider-final full-day peaks or
morning values. Acquisition completeness, wear coverage and legacy eligibility
remain unknown; saved values do not establish refresh success or medical meaning.


<a id="garmin-capabilities"></a>

<a id="garmin-capabilities--garmin-capability-and-bounded-probe-contract"></a>
## Garmin capability and bounded probe contract


This document freezes the pre-ingestion capability inventory for a Garmin
Vivoactive 5 and the reviewed `python-garminconnect` `0.3.12` source surface.
The bounded #98 maintenance upgrade to `0.3.15` changes the dependency pin
and provenance version only; this capability inventory and its read allowlist
remain unchanged. The `0.3.12` references below are the frozen review
baseline, not a new device-capability claim.
The matrix itself remains an offline/static contract. Issue #31 adds a
separate owner-assisted authentication and capability-probe harness; it does
not mutate this matrix or add ingestion, backfill, database/schema work, or a
UI.

The matrix has four deliberately separate questions:

1. What the R00 static review says about the physical watch.
2. What Garmin Connect may expose.
3. Which `python-garminconnect` method/field can be used later to retrieve a
   source payload.
4. What remains safe to claim before a payload from the target
   device/account is observed.

The third column never answers the first or fourth. A method or typed field is
not evidence that a Vivoactive 5 produces that metric.

<a id="garmin-capabilities--issue-31-owner-assisted-boundary"></a>
### Issue #31 owner-assisted boundary

The #31 commands run only when the owner invokes them from a checkout. They
use the pinned `python-garminconnect` source revision recorded in
`docs/REFERENCE_PROJECTS.md`, prompt for credentials and MFA through hidden
input, and keep the reusable tokenstore below the external
`HEALTHCHECK_DATA_DIR` runtime tree. The runtime path is rejected if it
resolves inside the checkout. The canonical `garmin_tokens.json` is a
Windows-current-user DPAPI envelope with an explicit owner SID; if that
protection API is unavailable the auth command fails closed. The provider sees
an inline decrypted snapshot only, never a plaintext temporary token file. A
malformed envelope is reported as recoverable `reauth_required`, while a
provider outage remains a failure. The implementation and CI tests use only
fake clients and synthetic payloads; no agent or CI process runs these commands
against an owner account.

The live probe accepts one or two adjacent owner-selected dates and at most
one activity selected from that small window. Activity discovery uses the
pinned provider's fixed activity-search endpoint directly with `start=0` and
`limit=1`; it does not call the provider's paginating
`get_activities_by_date` helper. The hard logical/provider request cap is 27,
and pinned-provider retries are disabled for the probe. One selected activity
may receive a summary call and `get_activity_details(maxchart=1, maxpoly=0)`;
no GPS/polyline route request and no ORIGINAL FIT download is made. Recovery
Time FIT evidence therefore remains explicitly `not_evaluated` until a
bounded correct FIT parser is added. Once a call reports reauthentication,
the probe stops and marks all remaining rows `not_run` with
`not_run_reason=reauth_required`. It does not call `prepare-runtime`, migrate
a database, write R02 persistence tables, ingest, backfill, or render a UI.
The probe retains raw responses only transiently in memory so it can return a
structural summary.

The sanitized report has this shape:

```text
contract_version: r02-garmin-capability-spike-v1
source: provider_code, target_device_code, target_device_model
library: name, version
application: name, version (unknown when no owner-safe app version is exposed)
auth: status, session_reused, mfa, storage, fixed-vocabulary error
probe: window_day_count, activity_requested, activity_selected, request_count,
       max_provider_requests, abort_reason, raw_payloads_retained=false,
       database_writes=false
privacy: raw_values_emitted=false, private_identifiers_emitted=false,
         tokens_emitted=false, health_timestamps_emitted=false
capabilities[]: code, static_audit_status, static_device_support, methods,
                method_callable, request_succeeded, status, value_state,
                payload_shapes, safe field_paths, shape_counts,
                field_state_counts, device_attribution,
                target_device_evidence, method_calls, fixed-vocabulary errors,
                optional not_run_reason/recovery_time_visibility
```

`status` distinguishes `succeeded`, `empty`, `null`, `unsupported`,
`shape_drift`, `method_unavailable`, `reauth_required`, `failed`, and
`not_run`/`partial`. `method_callable=true` never upgrades static device
support. `target_device_evidence=true` requires a present expected metric
leaf/value from the explicit #28/#29 field contract and exact target-device
attribution; an object container without its expected leaf does not qualify.
A payload containing both target and other-device markers is `mixed` and never
target evidence. Method presence or a non-empty root object alone is not
evidence.

The report contains no health values, activity/profile/device IDs, routes,
coordinates, precise health timestamps, credentials, cookies, tokens, or raw
payload dumps. If a raw owner response is deliberately saved for later shape
work, it must stay outside the checkout and be passed through the separate
`garmin-redact` command before anything is shared. The redaction output keeps
only statically allowlisted field names/paths, bounded counts, presence states,
and coarse attribution status. Unknown or provider-added keys are aggregated
as redacted counts; bounded traversal never materializes a whole provider
sequence.

<a id="garmin-capabilities--matrix"></a>
### Matrix

`VERIFIED` and `VERIFIED_CONDITIONAL` below mean the R00 static source/device
review result. `owner_account_verification` is `not_run` for every row in this
issue because no live Garmin account is accessed.

| Code | Stream | Watch/device review | Garmin Connect surface | Client surface (`0.3.12`) | Static status |
| --- | --- | --- | --- | --- | --- |
| `sleep` | sleep | Supported | Detailed sleep | `get_sleep_data` | `VERIFIED` |
| `sleep_score` | sleep | Supported | Sleep payload overall score | `get_sleep_data`, `dailySleepDTO.sleepScores.overall.value` | `VERIFIED` |
| `sleep_stages` | sleep | Supported | Nested stage totals plus raw levels | `get_sleep_data`, `dailySleepDTO.*SleepSeconds`, `levels` | `VERIFIED` |
| `naps` | sleep | Conditional: totals/events reviewed, exact intervals unknown | Watch/app/web totals and events | `get_sleep_data`, `get_body_battery_events`, `dailySleepDTO.napTimeSeconds`, `napEvents` | `VERIFIED_CONDITIONAL` |
| `heart_rate` | intraday | Supported | Daily/activity/FIT records | `get_heart_rates` | `VERIFIED` |
| `resting_heart_rate` | daily health | Supported | Daily history | `get_rhr_day` | `VERIFIED` |
| `hrv_status` | daily health | Supported after overnight baseline | Status/trends | `get_hrv_data` | `VERIFIED` |
| `stress` | intraday | Supported | Daily timeline | `get_stress_data` | `VERIFIED` |
| `body_battery` | intraday | Supported | Trends/events | `get_body_battery`, `charged`, `drained`, `bodyBatteryValuesArray` | `VERIFIED` |
| `spo2` | intraday | Conditional: setting/region/sleep dependent | Trends | `get_spo2_data` | `VERIFIED_CONDITIONAL` |
| `respiration` | intraday | Conditional: activity-type limits | Daily/sleep records | `get_respiration_data` | `VERIFIED_CONDITIONAL` |
| `vo2_max` | daily health | Watch/endpoint reviewed; owner payload unknown | Max metrics | `get_max_metrics` | `UNVERIFIED` |
| `recovery_time` | original FIT | Watch-only, up to four days | Not promised in Connect for sole VA5 | Possible `recoveryTimeSeconds`; no dedicated method | `WATCH_ONLY` |
| `training_readiness` | daily health | Not supported for VA5 | No VA5-produced value | `get_training_readiness` exists | `UNAVAILABLE` |
| `training_status` | daily health | Not VA5-produced | May be another compatible device's account value | `get_training_status` exists | `NOT_DEVICE_PRODUCED` |
| `unified_training_status` | daily health | Participant only | Account-level with another compatible device | No separate method | `PARTICIPANT_ONLY` |
| `training_effect` | activity | Unverified for sole VA5 | Sole-VA5 behavior unknown | Typed activity field | `UNVERIFIED` |
| `acute_training_load` | activity | Unverified for sole VA5 | Sole-VA5 behavior unknown | Typed activity field | `UNVERIFIED` |
| `activities` | activity | Supported | List/details/download | `get_activities_by_date`, `download_activity` | `VERIFIED` |
| `cycling_metrics` | activity | Basic metrics reviewed; advanced fields unknown | Recorded fields/FIT | activity details/download, speed/distance/HR/cadence/power/dynamics fields | `VERIFIED_CONDITIONAL` |

The machine-readable source of truth is
`healthcheck.garmin.capabilities.GARMIN_CAPABILITY_INVENTORY`; the checked-in
fixtures under `tests/fixtures/garmin/` exercise the offline envelope in
`healthcheck.garmin.contracts`. The typed normalization, temporal, source
identity, and idempotency continuation is documented in
`docs/ARCHITECTURE.md#garmin-normalization` and implemented by
`healthcheck.garmin.normalization`.

The inventory's `client_methods` is the static reviewed surface. The probe
report's `methods` and `method_calls` describe only the bounded execution graph
used by this spike; therefore naps currently executes `get_sleep_data` for its
typed `dailySleepDTO.napTimeSeconds` evidence, while the separately reviewed
`get_body_battery_events` surface remains documented in the inventory.

<a id="garmin-capabilities--synthetic-fixture-contract"></a>
### Synthetic fixture contract

Fixtures are provider-shaped but invented. They must:

- use `fixture_contract_version: r02-garmin-capability-fixture-v1`;
- identify `source_kind: synthetic` and a `synthetic-` fixture id;
- use the synthetic Vivoactive 5 identity only when the payload is explicitly
  device-attributed;
- keep raw field presence separate from non-null value presence;
- allow client methods/fields to be listed without promoting them to device
  capability;
- contain no credentials, tokens, MFA/OTP data, private identifiers, or owner
  payloads.

`method_surface_only.json` is the negative fixture: it lists methods for
Training Readiness, Training Status, and VO2 Max but has no device attribution
or payload evidence. `unattributed_account_value.json` has an account-level
Training Status value but no producer attribution. `daily_health.json` also
keeps null Training Readiness and Training Status fields explicit. None of
these fixtures changes the inventory status.

<a id="garmin-capabilities--owner-live-step-and-remaining-questions"></a>
### Owner live step and remaining questions

The exact owner procedure is in [Owner Operations](OWNER_OPERATIONS.md#garmin-auth). In short, the owner runs auth first
and then the separate capability probe:


See [Owner Operations — Garmin auth and probe](OWNER_OPERATIONS.md#garmin-auth) for the complete operator invocation.


Only the sanitized JSON summary may be copied back. Until the owner performs
this step and an Integrator reviews the summary, every owner-account result
below remains `UNVERIFIED`:

- Prove owner-region login/MFA, token refresh/reconnect, and Windows at-rest
  storage.
- Probe backfill depth, rate limits, and a safe trailing reconciliation window
  for each stream.
- Record actual payload availability and device attribution for every matrix
  row with Vivoactive 5 as the only source device.
- Verify exact nap intervals and timezone behavior.
- Recovery Time ORIGINAL FIT is intentionally not evaluated by this spike:
  retain `UNKNOWN`/`not_evaluated` until a correct bounded parser is reviewed.
- Verify Training Effect and Acute/Training Load provenance when those fields
  appear in activity payloads.
- Verify cycling power, advanced dynamics, cycling VO2, accessory attribution,
  and eBike fields for the owner's setup.
- Confirm conditional SpO2/respiration settings, region, sampling, and sleep
  semantics.

<a id="garmin-normalization"></a>

<a id="garmin-normalization--garmin-normalization-and-versioned-fields"></a>
## Garmin normalization and versioned fields


This is the offline continuation of [the R02 capability contract](#garmin-capabilities).
It parses synthetic Garmin fixtures only. It does not authenticate, call Garmin Connect, read
tokens, backfill, write a database, or define a schema.

<a id="garmin-normalization--input-and-output"></a>
### Input and output

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

<a id="garmin-normalization--temporal-semantics"></a>
### Temporal semantics

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

<a id="garmin-normalization--presence-semantics"></a>
### Presence semantics

Every recognized field carries one of `missing`, `null`, `value`, or `invalid`:

- absent path → `missing`;
- present JSON `null` → `null`;
- present finite number/string, including numeric `0` → `value`;
- wrong shape, non-finite number, or numeric string → `invalid`.

Only `value` is usable. `GarminMetricDTO.is_zero` identifies an explicit numeric zero without
using truthiness. Missing and null values are never substituted with zero and do not activate a
convenience fallback.

<a id="garmin-normalization--source-and-device-identity"></a>
### Source and device identity

`GarminSourceIdentity` requires `source_kind=synthetic` and `provider_code=garmin_connect`.
Device code/model are accepted only when the envelope explicitly says `device.attributed=true`.
The derived `source_instance_id` is stable for the source kind, provider, attribution bit, and
device identity; fixture id, payload order, and payload values are excluded. An unattributed
account-level value remains unattributed. A client method or an inventory row never becomes device
evidence. A metric is device evidence only when both the source is explicitly attributed and the
R02 capability status is `verified` or `verified_conditional`.

<a id="garmin-normalization--version-2-session-fields-319-b1"></a>
### Version 2 session fields (#319 B1)

`r02-garmin-normalization-contract-v2` adds `max_heart_rate_bpm` from `maxHR`
(bpm) and `anaerobic_training_effect` from `anaerobicTrainingEffect` (points).
Both retain the presence rules above and exact source field paths. Average HR
and maximum HR never substitute for one another.

`training_effect` remains the aerobic/general provider score: its alternatives
are `aerobicTrainingEffect`, then `trainingEffect`, selected by first **present**
path. A present null/invalid/zero does not fall through. Anaerobic effect has no
aerobic fallback. Raw camelCase rows and labels remain provenance only; the
analytic registry exposes exactly one identity per effect, with no score sum.

Both effects remain producer-unverified and non-device evidence. Maximum HR
uses the existing `cycling_metrics` family but its capability status stays
unknown and its device attribution stays false unless `maxHR` itself is included
in that family's reviewed client fields. This change does not add that reviewed
capability claim or upgrade the capability matrix. Numeric source evidence can
be compared without claiming a verified device producer.

The reconciliation contract and SQLite schema are unchanged. This version bump
does not reprocess historical projections. Replay requires separate explicit
Owner authorization. `calories` and `bmrCalories` remain outside normalization
and the analytic registry pending reviewed unit/composition evidence.

Absent new optional fields do not downgrade an otherwise complete activity
record; their own metric-level availability remains `missing`.

<a id="garmin-normalization--idempotency"></a>
### Idempotency

The HRV summary shape has a separate
`r02-garmin-hrv-calendar-normalization-v3` output version. Its explicit
`hrvSummary.calendarDate` is date-only, with the exact field path retained.
All present supported calendar fields must be valid and agree; null, malformed
or conflicting dates do not fall through to another date or sleep/start clock.
The production `hrv_status` adapter does not project unknown-time identities.
Other shapes retain v2 so existing stress/activity version gates are unchanged.
See [copy-only recovery](#hrv-calendar-recovery) for the separately authorized
legacy transition. This code change does not replay real historical data.

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
[collection reconciliation contract](#garmin-reconciliation).

<a id="garmin-normalization--result-states"></a>
### Result states

- `ok`: all parsed records are structurally usable;
- `partial`: at least one record is retained with missing fields, warnings, or recoverable shape
  drift;
- `empty`: the payload or an explicit activity collection has no records;
- `invalid`: no usable record can be produced from a fatal envelope/collection shape failure.

The result is deterministic: DTO collections, metrics, unknown paths, diagnostics, and activity
records are sorted by stable semantic keys. No database, network, authentication, live Garmin, or
backfill code is part of this contract.

<a id="garmin-persistence"></a>

<a id="garmin-persistence--garmin-immutable-persistence-and-current-projections"></a>
## Garmin immutable persistence and current projections


This is the offline persistence continuation of the [capability contract](#garmin-capabilities)
and [normalization contract](#garmin-normalization). It accepts already-normalized Garmin
DTOs and synthetic payload bytes/mappings only. It does not authenticate, call Garmin Connect,
run a backfill, provide a UI, or calculate analytics.

<a id="garmin-persistence--storage-layers"></a>
### Storage layers

| Layer | Tables/files | Contract |
| --- | --- | --- |
| Raw bytes | `artifacts/payloads/<aa>/<sha256>.<ext>` and `raw_artifacts` | Exact bytes are content-addressed and retained outside the checkout. `raw_artifacts` keeps only safe relative path, hash, media type, size, and source filename metadata. |
| Raw Garmin envelope | `garmin_raw_payloads` | One immutable source/stream/content-hash row. It records the canonical raw artifact link and first-seen metadata; repeated acquisition/normalization observations do not overwrite it. |
| Acquisition/normalization observations | `garmin_payload_observations` | One immutable row per logical source-window/sync/normalization observation. It retains ingest event, sync run, window, received time, source filename, parse interpretation, diagnostics, and the shared raw/artifact links. Exact retries converge by `observation_key`. |
| Source identity | `garmin_sources` plus R01 provider/device/source rows | A stable `GarminSourceIdentity` is explicit. Attributed device code/model creates a `physical_devices` row; an unattributed account value has no device row. A client method or field never creates attribution. |
| Current typed projection | `garmin_source_records`, `garmin_daily_records`, `garmin_sleep_records`, `garmin_activity_records`, `garmin_intraday_records`, `garmin_fit_records` | A source record is keyed by `(garmin_source_id, idempotency_key)` from #29. The shared parent carries temporal/provenance facts; each stream has a separate typed table. `original_fit` remains raw evidence with a small typed marker. |
| Scalar values | `garmin_record_metrics` | Scalar metric registry attached to the typed parent. It stores capability/metric identity, field path, unit, device evidence, and one of `missing`, `null`, `value`, or `invalid`. Numeric zero is stored as `state=value` and `value_number=0`. |
| Sleep intervals | `garmin_sleep_stage_intervals` | Stages are interval rows with ordinal, UTC instants when available, original local wall-time evidence, offsets/zones, and level. The full temporal DTO is retained in sanitized JSON columns for replay. |
| Coverage/freshness | R01 `coverage_intervals` and `sync_stream_state` | Garmin does not create a second coverage model. Coverage status/counts are recorded through the R01 repository; stream freshness is the monotonic `last_attempt_at`/`last_success_at`/watermark state. Missing, failed, unavailable, and confirmed-empty are never encoded as zero. |

<a id="garmin-persistence--replay-and-correction-semantics"></a>
### Replay and correction semantics

The raw file, raw payload row, and observation rows are immutable. The same source/stream/content
hash reuses one canonical raw row and one content-addressed artifact, while a different fetch
window, sync run, source filename, or normalization interpretation creates another observation
row. Exact retries converge on the observation key and do not create another row.

A normalized record is an idempotent current projection keyed by the stable #29 key, or by the
collection reconciliation key for id-less production series: exact observation retries do not
create another parent, typed marker, metric row, or sleep stage. A newer observation with the
same stable source-record ID may update that current projection, including its current
ingest-event, normalization-version, and reconciliation-version pointers. Replaying an older
observation never replays its payload into the current projection, so it cannot roll a newer
projection backward, un-retire a superseded member, or insert a member a newer complete
collection already retired. An id-less semantic record follows the #29 semantic key and therefore
creates a different projection only when its present typed metric set or temporal identity
changes.

An authoritative complete collection may retire current members that are absent from the new
response. Partial, unknown, failed, or truncated fetches never retire prior valid members.
Retirement is a current-projection status; raw payloads and observations stay immutable. See the
[collection reconciliation contract](#garmin-reconciliation).

The persistence facade can also create the ordinary R01 `provider_sync` batch/event atomically.
Invalid results still retain their raw evidence and sanitized failure state; no partial typed
record is invented. The caller owns the SQLAlchemy transaction and may roll the complete operation
back.

<a id="garmin-persistence--temporal-and-presence-rules"></a>
### Temporal and presence rules

- `calendarDate` is stored as a local `Date`; it is never converted to UTC midnight.
- UTC instants are stored in UTC. The original local timestamp string, wall time, numeric offset,
  zone, and source field names remain separate columns. Garmin persisted source/stage offsets
  accept the full #29 range of -23:59 through +23:59 (inclusive, -1439..1439 minutes).
- A genuinely local-only naive time keeps `temporal_precision=local` and has no invented UTC value.
- The textual R02 `source_instance_id` stays in `garmin_sources`; the shared R01 acquisition row
  uses its natural provider/device/input identity because its legacy instance column is UUID-only.
- Metric `missing`, JSON `null`, explicit numeric zero, and `invalid` are distinct persisted states.
- Diagnostics and unknown-field records store codes/shapes/paths only; raw values remain in the
  content-addressed artifact.

<a id="garmin-persistence--offline-api-boundary"></a>
### Offline API boundary

`healthcheck.garmin.persistence.GarminPersistenceRepository.persist_result` accepts a
`GarminNormalizationResult` and caller-supplied bytes (or a validated synthetic fixture/mapping)
plus a `ContentAddressedGarminPayloadStore`. It performs no provider discovery or network I/O.
`GarminCoverageRepository.record` is a persistence adapter for existing R01 coverage/sync tables;
it does not infer availability from the static capability matrix.

<a id="garmin-reconciliation"></a>

<a id="garmin-reconciliation--garmin-collection-authority-recency-and-reprocessing"></a>
## Garmin collection authority, recency and reprocessing


This is the pre-R03 hardening continuation of the
[normalization contract](#garmin-normalization) and
[persistence contract](#garmin-persistence). It defines how current Garmin
collections converge under provider corrections and how completed coverage can be
reprocessed after adapter/normalization upgrades. It does not add a scheduler,
analytics, FIT/GPS ingestion, Fitbit/Google adapters, or live Garmin access.

<a id="garmin-reconciliation--stable-sample-identity"></a>
### Stable sample identity

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

<a id="garmin-reconciliation--timestamp-correction"></a>
### Timestamp correction

A corrected provider timestamp/token is a new sample identity. The old identity is
absent from the new collection. When that collection is authoritative and complete,
the old current row is retired rather than updated in place. The new identity is
inserted or updated. Value-only corrections keep the same identity and update the
current projection.

<a id="garmin-reconciliation--collection-authority-and-removal"></a>
### Collection authority and removal

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

An incomplete activity fetch cannot produce successful acquisition coverage: an
otherwise usable prefix is recorded as `unknown`, with `partial` attempt/run status
and no advancement of the successful checkpoint. Historical resume re-fetches the
window from page zero with a bounded budget; complete-page replay remains idempotent.
A terminal short/empty page is required before coverage can become complete.
The page cap stays bounded; a window exceeding it must be split into smaller ranges.

Retired rows stay in the current-projection table with `projection_status=retired`.
Raw payloads and observation rows are never deleted.

<a id="garmin-reconciliation--replay-and-recency"></a>
### Replay and recency

Raw bytes, raw payload rows, and observation rows remain immutable. A newer
observation (later `received_at` than the collection's latest
`projection_observed_at`) may update current members and, if complete, retire
absences. An older observation is still stored as provenance and **must not**
change current projection: no value rollback, no insert of vanished members, and
no un-retire.

Exact observation-key retries remain idempotent and do not create another
observation row.

<a id="garmin-reconciliation--version-aware-reprocessing"></a>
### Version-aware reprocessing

Normal historical backfill continues to skip `present` / `confirmed_empty` coverage.
That skip changes only for an explicit reprocessing or bounded acquisition-repair request.

- `garmin-backfill --reprocess` re-fetches `present` coverage whose current rows are
  not yet on the current reconciliation contract version. `confirmed_empty` coverage
  still skips. Historical and incremental checkpoint namespaces stay isolated.
- `garmin-reprocess` is an offline, bounded command. It re-normalizes stored raw
  artifacts for an explicit date range and does not call Garmin, write incremental
  checkpoints, or write historical checkpoints.
- Offline reprocess applies only the newest observation in each
  source/surface/window. Older observations remain immutable provenance and are
  not replayed into current state.
- Eligibility is computed from the pre-run state. Overlapping activity windows
  with different bounds are applied and bounded-resumed in original `received_at`
  order so a newer provider observation wins every shared current identity.
  A write from an older eligible window cannot skip a newer eligible one, in the
  same run or a later bounded invocation. An observation remains eligible when
  any in-window current row is still on an older version or an older
  `projection_observed_at`.
- Ordinary sync/backfill persistence keeps a **whole-collection** stale guard:
  when the incoming collection is older than current projections in scope, it is
  fail-closed and must not insert unseen extra members. Per-row stale
  reconciliation (skip only newer shared identities while still applying other
  eligible rows) is reserved for the offline `garmin-reprocess` path that needs
  it for bounded overlapping resume.
- `garmin-reprocess --start/--end` is a hard current-projection boundary.
  A multi-day stored activity observation is clipped to the requested local
  dates; clipped collections are fail-closed for absence retirement.
- Collection completeness is reconstructed fail-closed: a stored activity list
  whose last page is full is not treated as authoritative, so truncated or
  budget-stopped fetches cannot retire absent members during reprocess.
- Version-aware skip is represented for empty collections by the newest
  observation's reconciliation and normalization versions. It does not invent
  current rows.

Reprocess is bounded by the requested local-date span and a max observation cap.
Days in the requested range with no `present` / `confirmed_empty` coverage that
also sit outside the incremental trailing window are reported as history gaps.
An incremental watermark is not contiguous history.

<a id="garmin-reconciliation--out-of-scope"></a>
### Out of scope

The [HRV calendar recovery amendment](#hrv-calendar-recovery) adds a narrow
offline identity transition, not a general retirement exception. Ordinary
absence retirement cannot assign an undated HRV row to a collection day.
Offline reprocess may supersede the exact old undated identity only after its
own verified original proves the same in-range day as a non-stale dated
replacement, atomically. Other days, partial/unproven collections and original
raw/observation evidence remain untouched. HRV uses its separate normalization
version for reprocess eligibility; reconciliation keys and other versions stay.

Scheduler/background service, Garmin analytics, FIT/GPS download, Fitbit/Google,
a generic provider framework, owner live payloads, and destructive provenance
rewrite.

<a id="garmin-steps"></a>

<a id="garmin-steps--garmin-observed-completed-and-all-time-steps"></a>
## Garmin observed, completed and all-time Steps


Contract: `garmin-observed-daily-steps-v1`, following the
[accepted bounded Steps decision](https://chatgpt.com/c/6ac9ecb7-a734-83ea-9040-8ad886eee940?messageId=858171b8-66dd-464c-b4f1-47a2a12e74c9).

`SavedDailyStepsRepository.project_day` is an explicit offline service over
already saved Garmin `daily_health` JSON observations whose source filename is
exactly `daily_summary.json`. #395/[PR #398](https://github.com/LTstripes/Health-Check/pull/398)
now wires this service after successful persisted routine Garmin acquisition;
the service itself makes no provider call and GET never projects/writes.
The caller selects one existing source and one calendar date,
supplies the saved artifact store, and owns the database transaction. This slice
does not run a historical replay or alter collection policy.
The session must have no pending ORM changes; flushed writes may be used. A
physical SQLite transaction pins the compound read and remains caller-owned,
including rollback of newly derived records.

Only a top-level `calendarDate` with strict, valid `YYYY-MM-DD` spelling and a
top-level nonnegative JSON integer `totalSteps` are accepted. `observed_daily_steps`
has unit `steps` and account attribution. Coverage, device, timezone and finality
remain `unknown`; the date has no invented midnight, UTC offset or window.
Acquisition windows and received times cannot supply or reinterpret the day.
Booleans, floats (including integral floats), strings and negative counts are
invalid. Explicit zero is a value; null, absent and invalid are separate states.
An absent leaf means only `field_absent_in_payload`, never no steps in history.
Other fields, activity data, distance and nested envelopes cannot supply Steps.

The service verifies immutable raw/artifact/observation links, byte size and
SHA-256 before writing a typed record. It scans all eligible saved artifacts for
that source, because acquisition-window filtering could hide a conflicting
returned date. A configurable artifact bound (default 1,000) or per-artifact
byte bound (default 1 MiB), unreadable bytes or inconsistent provenance fails
closed before inserting any Steps records. Unsupported dates, malformed JSON,
duplicate JSON keys and unsupported shapes are returned as explicit exclusions
with saved observation references. They do not acquire a guessed date.

One derived daily record is identified by contract version, saved source, returned
day and immutable artifact hash. Identical acquisitions share that record while
retaining every acquisition observation. Different artifacts remain separate.
Their metric state and provenance persist in the existing Garmin daily-record
tables, on a distinct `observed_daily_steps` surface so ordinary daily-summary
reconciliation cannot replace or retire the evidence. Existing records are not
updated on replay. Original raw payloads and acquisition observations remain
unchanged. No schema change is needed. To avoid floating-point rounding, valid
counts use the existing metric `value_text` slot as a canonical decimal integer;
the service returns a typed Python integer.

One distinct valid count yields that observed value, even if repeated in different
artifacts. Two or more distinct valid counts yield `ambiguous` and no selected
value. Neither the latest, largest nor sum wins. Null/missing/invalid observations
remain visible alongside valid ones; they do not retract a valid observation or
prove correction authority. With no valid count, a homogeneous non-value state
is retained; mixed non-value states or no supported saved day yield `unavailable`,
with individual evidence preserved. This is a saved-observation snapshot, not a
full-day total, collection-status diagnosis, wear claim or promise about unsaved
history. No `not_collected` claim is inferred. Sources are never fused.

Synthetic acceptance cases cover zero/null/absence/invalid types, exact integers
above floating-point precision, repeated acquisitions, divergent values in either
arrival order, same-count artifacts, mixed presence states, source/day/surface
separation, date-only precision, unsupported dates and shapes, fail-closed bounds
and artifact integrity, and ordinary reconciliation retaining Steps evidence.
Google Steps, device fusion, correction selection, timezone conversion, statistics
cards and Calories/Energy are outside this contract.

<a id="garmin-steps--read-only-materialized-window"></a>
### Read-only materialized window

`read_observed_steps_window` in `garmin/observed_steps_read.py` returns one cell
per exact civil date in an explicitly selected Garmin source/window. It never
calls `project_day`, opens saved bytes, materializes records, commits, selects an
automatic source, seeks a latest value, or aggregates days. The caller owns the
read snapshot. This v1 window remains available; Statistics now uses the separate completed-day
view below, without rewriting this reader or its history.

Windows contain 1–366 inclusive calendar days; larger/reversed windows and
missing source selection are rejected. The independent reader contract is
`garmin-observed-daily-steps-window-v1`. Each request reads at most 4,097
candidate/history records on the `observed_daily_steps` surface, including
retired/unsupported records, using the 4,097th only to detect the 4,096-row cap.
The singleton metric/raw/artifact metadata joins cannot multiply candidates.
A second independent cap+1 query reads up to 4,097 eligible saved acquisition
observations for these raw identities; repeated raw references do not multiply
provenance rows. This cap is reader-local, not an analytics/annual-read budget.

Ascending date order establishes complete earlier groups. A truncated candidate
day and subsequent unexamined dates yield `search_incomplete` with no value.
A truncated provenance day and later candidate groups also yield
`search_incomplete`; independently complete cells remain usable. Unsupported
materialized contracts, absent metric/acquisition links and inconsistent
provenance fail that day closed. Returned evidence on incomplete cells may be
partial and does not establish group completeness. Counts describe examined
rows, including the detection row, rather than total history size.

Complete cells preserve the projection's distinct valid-count resolution and
missing/null/invalid evidence, including exact integer text storage and zero.
Without materialized day evidence the cell is `projection_unavailable` with
reason `not_evidenced`, never a claim that projection was not run, the leaf was
missing, collection never occurred, or Steps were zero. An unknown exact source
uses `source_not_found`. Coverage, device, timezone and finality remain unknown.
Persisted provenance references and contract versions are retained; the reader
does not re-verify artifact bytes or attest completeness of unsaved/unprojected
history. No schema, replay, collection, ledger or migration contract changes.

<a id="garmin-steps--completed-day-read-only-view-377--pr-410"></a>
### Completed-day read-only view (#377 / PR #410)

[Integrated amendment receipt](https://github.com/LTstripes/Health-Check/issues/377#issuecomment-6133714095)
governs the separate Statistics view. It selects one exact Garmin source/account
and the latest proved acquisition by `GarminPayloadObservation.received_at`,
at or after the returned calendar day's end boundary under explicit
`Europe/Moscow` display policy. The first-original `received_at` is not used for
selection. Current/future
days are excluded; the default rolling Steps window ends yesterday, preserving
explicit historical bounds and other Statistics summaries.

Verified original bytes/hash and exact source/run/artifact/event/batch links are
required; successful acquisition only, with reprocess excluded and
failed/running/missing evidence unproven. A terminal partial is unproven unless the exact immutable receipt amendment below validates it. Identical original bytes
reacquired later can count; a later lower correction wins. Equal-time divergent
values remain ambiguous; latest missing/null/invalid/unproven never falls back
to an older count. Sole-source automatic selection requires complete bounded
range evidence; otherwise show honest choice/unavailable. No pooling or totals.

This is a new read-only projection, not a rewrite of v1 distinct-count ambiguity,
originals, materialized history, ingestion or schema. Candidate/provenance/byte
bounds and complete tie-group search fail closed as `search_incomplete`, never
absence/zero. The 5-second elapsed guard is **cooperative**, not a hard SQL,
lock or I/O deadline: source discovery may scan/sort before SQL returns and then
fail closed on elapsed excess. Real-database availability/latency requires its own dated Owner-runtime evidence; synthetic proof alone does not establish it. See Wiki for observed installation/UAT scope.
Moscow is a display policy, not proof of Garmin timezone, coverage, wear or final
day total; later corrections remain possible. Owner UAT and installed rollout are separate dated evidence in [Project Wiki](PROJECT_WIKI.md#current-canonical-state); this contract authorizes no historical replay.


<a id="garmin-steps--all-time-completed-steps-statistics-380--377"></a>
### All-time completed Steps statistics (#380 / #377)

The explicit Steps-only `steps_period=all_time` Statistics mode uses
`garmin-completed-day-steps-moscow-all-time-v1` and the separate
`garmin-completed-steps-all-time-budget-v1`. It requires one exact Garmin source;
an omitted source asks for selection, without pooling or source guessing. The
existing source-wide Statistics chooser remains available. Google Steps is
separately `not_collected` pending #392; Garmin is never substituted for Google.

The existing completed window entry point retains v2, 1–366 days and its
1000-original cap. Combined export v1–v5 and other Statistics metrics/periods
are unchanged. All-time is not implemented by looping through years/windows.

One read snapshot and one aware evaluation instant cover the all-time scan and
statistics. Metadata/provenance are bounded source-wide at 4096 candidates and
4096 observations, with cap+1. At most 4096 unique originals may be verified in
the entire request, each once; original identity is the immutable exact source,
stream and content hash (represented by raw payload ID). Reacquisitions still
retain their own timestamps/proofs and consume provenance capacity. Caps remain
1 MiB per original, 16 MiB combined bytes and one cooperative 5-second elapsed
guard shared by metadata, original reads, selection and aggregation. They never
reset by year/day. This is not a hard SQL/lock/I/O deadline or a real-data latency
claim. Any exhausted bound, unreadable/integrity-unknown original or unproved
daily grain fails closed as `search_incomplete`: no aggregate or winning prefix.

Metadata is not filtered by a materialized earliest date. Every relevant saved
acquisition for the exact source up to evaluation is considered within those
bounds. The v2 acquisition spine, immutable receipt proof, source/run/event/batch
links, returned `calendarDate`, strict nonnegative integer parsing and hash/byte
verification are reused. Reprocess remains excluded; terminal partial requires
valid receipt proof. Old partials, checkpoints and projections are never repaired
or written by this reader. Latest missing/null/invalid/unproven never exposes an
older value; later lower corrections replace earlier counts; equal latest
timestamps with distinct values/states stay ambiguous. Identical bytes acquired
again after the completion boundary may become eligible without a second read.

Effective end is the selected explicit `end_date`, capped at yesterday under
Europe/Moscow display policy; without an explicit end it is yesterday. The other
Statistics metrics retain their exact existing selected window, including the
calendar-year rule. The all-time start is the earliest verified returned completed
calendar day within that bound; no earlier account/provider coverage is inferred.
Returned days with no post-boundary acquisition remain unavailable. Sparse cells
and arithmetic calendar-span counts avoid expanding an arbitrary date gap into
an unbounded dense calendar. Empty/no-source/no-completed states are distinct.

Statistics use one selected latest proved value for each unique eligible civil
day. Integer zero is eligible and contributes to the mean's denominator. Sum is
exact integer addition; mean is sum divided by eligible-day count (Decimal;
rendered to one decimal, with exact numerator/denominator available). Counts
strictly above 10000/20000 exclude exactly 10000/20000 respectively. Record dates
include every equal maximum day. A qualifying streak uses values **>= 10000** on
adjacent calendar dates: omitted dates, null/missing/invalid/ambiguous/unavailable
days and values below 10000 break it. Longest length and all equally longest
ranges are retained. Acquisitions are never summed as extra days.

With no eligible values, numeric aggregates are unavailable, not fabricated zero;
when eligible values exist but none cross a threshold, that threshold count is
genuine zero. An incomplete search exposes no numeric statistics. The UI shows
the effective period, eligible denominator, sparse-state counts, dates without
verified evidence, exact source, evaluation, contracts and budget counters. Record
ties and streak ranges are scrollable details; per-day acquisition evidence stays
in the existing window/year table on the same Statistics page. Full bounded saved
search does not establish provider history, collection coverage, wear, provider
timezone or irrevocable finality. Later Garmin corrections remain possible.

No provider calls, Google import, replay/backfill, schema/migration, DB/artifact
writes, schedule or installed Stable changes are part of this code slice.
Development/desktop checks use synthetic profiles. Real Owner UAT and rollout are
separate and are not implied by CI or synthetic capacity checks.

<a id="garmin-steps--immutable-acquisition-receipt-amendment-and-trusted-index"></a>
### Immutable acquisition receipt amendment and trusted index

This accepted amendment is part of completed v2 and reused by all-time; it
supersedes the earlier blanket partial-run exclusion only for an exact valid
receipt. It does not certify historic partial runs or change observed v1.

Completed-day Steps contract `garmin-completed-day-steps-moscow-v2` retains the
latest proved acquisition after the Europe/Moscow day boundary. A terminal
partial run needs an immutable `garmin-daily-summary-acquisition-v1` receipt for
that exact observation; succeeded legacy runs without a receipt retain their
existing predicate. Present invalid or unsupported receipts fail closed. Original
hash, source, run, event and batch links remain required; coverage, device,
source timezone and finality stay unknown. Receipt eligibility does not suppress
latest missing/null/invalid values, competitors or any bounded-search failure.

The receipt is a one-to-one append-only FK to the immutable payload observation,
which already binds run/source/original/hash/received time. Only a complete new
`daily_summary` / `get_user_summary` acquisition can mint it, after the existing
optional Steps callback and before checkpoint/commit in the same transaction.
Receipt v1 requires strict original calendarDate equal to the requested date,
the exact UTC request-day observation window, and enclosing run request bounds;
these transport bounds do not establish Garmin timezone or finality. Same-key
replay can validate an existing receipt but cannot add missing proof or advance
received time. A genuinely new acquisition may reuse identical raw bytes. The
shared historical fetch path retains its existing lack of a Steps callback.

Migration 0016 creates an empty receipt table and does not certify old partials.
Attempt rollback preserves earlier commits; the existing separate failure
checkpoint may still be written, and orphan content-addressed files may remain.
The bounded reader joins receipts by PK and performs no writes. Provenance and
candidate caps still count the entire bounded source/time metadata scan. Before
applying the unchanged original-count, byte and time caps, it excludes a raw
original only when all its acquisition observations have fully validated receipts
with one agreeing returned day outside the requested completed days. Legacy,
missing/invalid receipt and conflicting-index groups retain all observations and
require original-byte verification; selected receipts are checked again against
the decoded calendarDate. This index relies on the existing trusted writer and
append-only spine: it does not authenticate arbitrary internally consistent forged
database inserts or inspect unrelated excluded files for later corruption.
Observed Steps v1/history remain unchanged. New proof applies only to
future acquisitions after a separately accepted rollout; it does not reconstruct
past provider success or authorize recovery/provider fetches.


<a id="garmin-steps--bounded-daily-summary-reacquisition"></a>
### Bounded daily-summary reacquisition

`garmin-backfill --reacquire-unproven-daily-summary` is a separate explicit
acquisition policy, requiring an existing profile, exact stored Garmin source,
only `daily_summary`, explicit completed dates and a span no larger than the
existing maximum backfill chunk (14 days). It cannot combine with `--reprocess`.
Ordinary coverage skip, projection-version reprocessing and other surfaces retain
their behavior. This mode holds the same operation lock and historical namespace.

Before authentication, one unchanged completed-day reader request evaluates the
whole invocation in one bounded snapshot. Coverage and projection freshness do
not establish acquisition proof. Incomplete or corrupt proof search, incompatible
source binding, ambiguous latest evidence and non-completed dates fail closed.
Budgets are neither raised nor reset per chunk. Latest proven acquisitions skip
even when Steps is zero, null, missing or invalid; acquisition proof is distinct
from numeric availability. Legacy succeeded proof and valid terminal-partial
receipts use the existing reader predicates. Unproven acquisitions must be unreceipted for this repair: any existing receipt
on an acquisition the native reader cannot prove blocks for separate diagnosis,
including a receipt on a failed, running or nonterminal run. This conservative
boundary avoids adjudicating disputed receipts or adding another metadata scan.
Source selection binds the existing provider/device identity; it does not
establish an external Garmin account ID.

Unproven selected dates use the existing complete `get_user_summary` persistence
transaction with strict returned-day and source binding. A later acquisition can
reuse identical content-addressed bytes while receiving a new observation and
receipt. Old observations, partial-run statuses and missing receipts are never
rewritten. Any per-day error stops the invocation; committed earlier receipts
remain usable for bounded resume. An all-proven resume performs no authentication,
provider calls or new acquisition writes. Offline replay cannot mint missing
historic proof. Reader eligibility, schema, caps and v1-v5 output contracts stay
unchanged; the operational report adds mode/proven-skip fields only for opt-in.


<a id="garmin-steps--separate-steps-window-budgets"></a>
### Separate Steps window budgets

| Entry point | Dates | Candidates / provenance | Original/byte/elapsed policy |
| --- | --- | --- | --- |
| observed materialized window v1 | 1–366 inclusive civil dates | independent 4096-row caps with cap+1 detection | No original-byte read; independently complete earlier cells remain usable |
| completed window v2 | 1–366 inclusive civil dates | source-wide bounded 4096 candidates and 4096 observations | 1000 originals, 1 MiB/original, 16 MiB combined, cooperative five seconds; complete search required |
| completed all-time v1 | sparse verified returned days through explicit end/yesterday | one global 4096 candidates and 4096 observations | One global 4096-original budget, 1 MiB/original, 16 MiB total and cooperative five seconds, never reset per year/day |

No all-time numeric prefix, partial mean or fabricated zero is allowed when search
is incomplete. This never claims complete provider history or a full-account
personal record. A fixed ≥10000 Steps streak is not a provider goal streak whose
goal definition and dates have not been established.


<a id="hrv-calendar-recovery"></a>

<a id="hrv-calendar-recovery--hrv-calendar-recovery-applicability"></a>
## HRV calendar recovery applicability


This runbook is preparation, not authorization to run recovery. Code/synthetic
acceptance, independent review, private copy verification and Stable rollout are
separate outcomes. Do not call Garmin, change Stable, or start/stop the Owner's
application to exercise it. No real profile was reprocessed for this candidate.

<a id="hrv-calendar-recovery--candidate-contract"></a>
### Candidate contract

`r02-garmin-hrv-calendar-normalization-v3` uses the explicit
`hrvSummary.calendarDate` as a source-local date without an instant or invented
zone. Present supported calendar fields must all be strict valid dates and agree.
A sleep/start clock, requested day or receipt cannot replace an absent date.
Other normalization output retains its accepted version, including stress/activity v2
and the separate [Sleep v3 interpretation](#saved-sleep-production-shape-interpretation-462--464).

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
An identical clipped replay converges after its in-range dated projection is
current, even when the undated legacy row must remain. Only a later complete
containing request with present coverage may force that pending transition.
Unknown coverage likewise cannot force an impossible transition on every
resume or starve another source. Clipping and coverage retirement guards remain
unchanged; convergence does not assert complete recovery or resolve legacy data.
A pending transition also respects a newer dated projection: its older original
cannot occupy the cap ahead of the newer same-day observation that can finish it.


<a id="google-persistence"></a>

<a id="google-persistence--google-persistence-identity-and-auth-boundaries"></a>
## Google persistence, identity and auth boundaries

<a id="google-persistence--google-fitbit--google-health"></a>
### Google Fitbit / Google Health

R04 targets Google Health API v4 (`health.googleapis.com`) only. The legacy Fitbit Web API has a September 2026 turn-down milestone; no legacy Fitbit Web API implementation. Accepted external contract: #81 adjudication (`5643609852`); repository-side correction: #82 (`5643533712`, `5643611744`).

R04 requests only the implemented read scopes `googlehealth.sleep.readonly` and `googlehealth.health_metrics_and_measurements.readonly`. Current first-party Google Health docs classify all Google Health API scopes as Restricted. Partial consent is a stream-level capability state.

Google Health source identity is explicit. `list` / `reconcile` / `rollUp` / `dailyRollUp` and `dataSourceFamily` are acquisition/query/collection context, not stable source identity. The adapter preserves raw `list` records with their `dataSource` platform/device/recording-method metadata and stores reconciled/rollup results separately with the exact query/family. `google-wearables`, `google-sources`, and `all-sources` are different source families: an aggregate from `google-sources` or `all-sources` may include Health Connect, manual, or third-party data and must never be labelled as Fitbit-device evidence. `google-wearables` includes Fitbit trackers and Pixel Watch; even a `google-wearables` aggregate is family-level (`google_wearables_family`) unless returned metadata identifies the physical device. Garmin/Fitbit agreement uses only records attributable to the intended Fitbit device/source.

Exact operation matrix: sample heart-rate supports `list/reconcile/rollUp/dailyRollUp`; the other planned vitals/daily types (HRV + daily HRV, daily resting HR, SpO2 + daily SpO2, respiratory-rate sleep summary + daily respiratory rate) use documented `list/reconcile` surfaces; sleep follows its own documented session operations. Never generalize rollup support. Initial R04 types: sleep; heart rate; HRV + daily HRV; daily resting HR; SpO2 + daily SpO2; respiratory-rate sleep summary + daily respiratory rate.

Sync mechanics: pagination follows `nextPageToken`; sleep page cap is 25; time bounds are inclusive lower / exclusive upper; do not rely on undocumented `list` ordering. Historical querying reaches as far back as recorded, subject to quotas; no invented retention ceiling. Current quotas include 300 requests/minute/user and an unverified-app aggregate cap of 250 QPS / 100 users; Health-Check still imposes its own tighter bounded request budgets/retry ceilings. Parsers must expect documented JSON string-encoded integer fields where applicable. R04 missing sleep/vital data remains missing, never zero; do not generalize true-zero semantics from unrelated data types.

R04 reuses the generic evidence/runtime/sync/coverage spine but implements an explicit `google_*` layer. Do not reuse `garmin_*` persistence and do not build a generic provider/EAV framework. R03 analytics stay Garmin-only in R04; cross-source agreement/canonical sleep remains R05.

OAuth for one personal account (Web Application / Web Server client per current Google Health product setup; the former Desktop-client assumption is retired):

1. External Google Cloud project in **Published / In production** status under the documented personal-use/unverified exception (unverified app: warning + 100-user cap). Testing status is unsuitable for routine automation because its offline refresh token is limited to seven days. Track the separate 100-user unverified-app audience cap; it is not the exception definition.
2. Web Application client with Client ID + Client Secret; secret/session/refresh-token material stays outside Git under the user runtime secret boundary (Windows Credential Manager/DPAPI-equivalent) and never enters worker workspaces/logs/issues. A service account cannot replace the owner's consent.
3. Local Windows app uses a fixed registered loopback redirect URI (`localhost` / localhost IP), which Google permits for Web Application redirect URIs as an exception to HTTPS. Random-port Desktop callbacks are retired: the exact default port/path is pinned as a fixed, exactly-registered implementation constant (R04-02), not an ephemeral port.
4. Authorization-code flow in the system browser with a unique one-use CSRF `state` that is persisted and validated; `access_type=offline` with a securely retained refresh token, refreshed on demand for scheduled jobs.
5. `prompt=consent` only for initial refresh-token acquisition or deliberate scope-set changes.
6. When scopes change, reauthorize with the complete required set; do not assume installed-app incremental authorization and do not promise Desktop incremental authorization.
7. Do not make PKCE a universal R04 requirement for this Web Application route unless later current provider evidence requires it.
8. Surface token health and require manual reconnect on revocation/`invalid_grant`.

The bounded GET-401 exception approved in [#406](https://github.com/LTstripes/Health-Check/issues/406)
keeps cached access explicitly unverified and retains the safe startup-refresh failure
class/code/status; cached data success does not prove token refresh or expiry. One
logical sync (including historical chunks, normal HR days and continuations) may
perform at most one startup refresh
and one recovery refresh. Only an actual successful protected refresh, with fallback
disabled, permits replay of the identical data GET. Refreshed access and the existing
scope ceiling carry to later pages/streams. Repeated 401 or `invalid_grant` aborts
the run and leaves later streams `not_run`; unavailable, failed, malformed or
storage/protection-failed recovery also stops. 403, POST rollups and other errors
retain their existing terminal/bounded-transport behavior.
Token persistence exceptions (including ENOSPC/EIO) are classified at the protected
write boundary as storage failures and prohibit startup cached fallback; transport
errors retain their provider classification.

The original GET and its replay each consume the existing data-request budget and
per-page attempt ceiling; OAuth attempts have separate sanitized counters. No
refresh is started when replay cannot fit. Safe diagnostics retain the first data
401 and startup/recovery reasons, without provider text. OAuth responses and auth
error bodies never enter data raw ingestion. Unauthorized attempts do not complete
pages, promote staged data or advance completed checkpoints. Accepted evidence and
resume cursor/idempotency rules remain unchanged. This synthetic code contract does
not prove the cause of the observed refresh failure or authorize owner-live runs.

Non-Windows Google credential writes use `healthcheck-google-local-key-v2`:
canonical UTF-8 JSON (ASCII escapes, sorted compact keys) with exactly `format`,
`purpose`, `nonce`, `ciphertext`. AES-256-GCM uses a fresh random 12-byte nonce
per write and a 16-byte tag attached to ciphertext. The existing 32-byte raw
key file derives a distinct AES key through HKDF-SHA256 (length 32, salt
`healthcheck-google-local-key-v2`, info `aes-256-gcm`). AAD is the ASCII version
constant, a NUL separator, and the trusted expected purpose supplied by code:
`google-client-credentials` or `google-tokens`. Envelope purpose must match;
relabeling it cannot bypass authentication. Repeated writes require fresh nonces;
operational usage remains far below the GCM nonce/counter bounds.

Plaintext is non-empty UTF-8 capped at 64 KiB; local envelopes are capped at
96 KiB. Purposes match ASCII `[a-z0-9-]{1,64}`. Exact fields, strict base64,
decoded sizes, UTF-8, format and authentication fail closed. Legacy v1 remains
authenticated read-only HMAC/XOR (16-byte nonce, 32-byte MAC, 1..65536-byte
ciphertext) with its original lack of role binding. Pure reads load the required
key only, never create a missing key or rewrite keys/envelopes. Existing v1 files
migrate individually on their next supported normal credential/token write.
Windows user-scoped DPAPI bytes, entropy and SID checks remain unchanged; the
uniform purpose argument is ignored by DPAPI and cryptography is loaded only
by the local implementation.

Local v2 protects a stolen envelope without its key and detects offline tampering
and role transplant. It does not protect theft of the whole runtime profile or
decrypted profile backup where the key and envelopes are together. This does not
change backup membership/format, add a keyring, or redesign Owner recovery.

Verification/policy and live API access remain a release gate with explicit owner-live acceptance probes (Console setup, fixed-callback authorization, secret/refresh behavior, `dataSource`/device attribution, envelope/pagination shapes, late-arrival behavior), not an excuse to switch to an unsafe token workflow.

Google Health sleep and physiological records are source data. A local `healthcheck_*` or adapted `fettle_*` score is a derived, versioned metric; it must not be named or displayed as an official Fitbit Sleep Score or Readiness value. No documented provider-native Fitbit Sleep Score / Daily Readiness identity exists in the current Health API; no such claim in R04.


This is the offline persistence foundation for R04 (#86). It stores synthetic
Google Health identity, immutable raw response evidence, acquisition
observations, and a minimum typed-record shell. It does not authenticate, call
Google, run production sync/backfill, or perform typed health normalization
beyond that shell.

<a id="google-persistence--identity-dimensions"></a>
### Identity dimensions

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

<a id="google-persistence--storage-layers"></a>
### Storage layers

#### Offline Steps countSum v1 (#392)

The later [explicit Steps acquisition v1](GOOGLE_STEPS_ACQUISITION.md) adds only
an opt-in readonly scope and manually requested one-day `google-wearables`
observation path. Its coverage/pagination remain unknown; it does not enable
Steps in production sync. The offline contract below remains the typed-value
foundation. Acquired observations use a distinct source contract and revalidate
their immutable request context during replay.

This bounded synthetic-only slice accepts already supplied `dailyRollUp`
`rollupDataPoints[*].steps.countSum`; it enables no acquisition surface, scope,
provider request, replay command, UI or production sync. Acquisition, account
access, observed-day eligibility, coverage and source selection retain their
separate future gates from [#392](https://github.com/LTstripes/Health-Check/issues/392#issuecomment-6115372615).

The reserved metric `steps_count_sum` has unit `count`. VALUE is an exact
nonnegative signed-int64 count (0 through 9223372036854775807), stored as canonical
ASCII decimal in the existing `value_text` slot, with `value_number` and
`collection_json` NULL. A dedicated typed decoder validates code, unit, state,
decimal grammar/range and empty alternate slots before returning a Python int.
Generic text is not an accepted numeric count. Missing leaf, explicit null,
invalid input and explicit string `"0"` remain distinct; no float conversion,
rounding, implicit zero, local summation or claim of zero activity is permitted.
Only canonical string integers are accepted; signs, whitespace, leading zeros,
fractions, exponents, booleans and JSON numeric tokens are invalid.

Only an explicit known family-aggregate identity matching the query family is
accepted. The exact returned `civilStartTime`/`civilEndTime` objects are retained in
endpoint JSON and immutable raw/attempt evidence. Their validated civil values
must be strictly ordered; no UTC, timezone, 24-hour or completed-day inference
is made. Identity includes the family, daily mode and exact raw endpoint objects,
excluding response order, record name and count. Equivalent-looking but differently
encoded endpoints conservatively remain separate. Invalid endpoints retain audit
evidence without creating a current projection.

Existing immutable payload/observation/normalization-attempt provenance is reused.
Exact replay cannot advance chronology. Divergent same-epoch or unorderable
observations invalidate the projection; strictly later orderable observations may
correct it, including lower counts, zero, null, missing and invalid, without
erasing history. For an invalid Steps projection, `projection_observed_at` retains
the maximum conflict receipt time as a barrier while the original observation
reference remains unchanged. Recovery must be strictly later than that barrier.
Older replay cannot replace it. A count with non-VALUE state or
an invalid/conflicted record is unavailable to a typed consumer. This is interval
evidence only and does not establish daily completeness or coverage.

The schema delta only admits `steps` in the four existing Google stream CHECKs;
no numeric column or general EAV extension is needed. Migration must preserve
populated rows, indexes, foreign keys and append-only triggers. Existing consumers
select stream/metric codes explicitly; the reserved count never enters their
float paths. Production stream registries and credentials remain unchanged.

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

<a id="google-persistence--migration"></a>
### Migration

Revision `0009_google_persistence_contract` is additive only. It does not
recreate populated R01–R03 parents and does not migrate Garmin/Xiaomi rows.
`ondelete=RESTRICT` matches existing evidence semantics.
<a id="google-persistence--live-terminal-envelope-decision-from-110"></a>
##### Live terminal-envelope decision from #110

Owner evidence proved terminal HTTP-200 LIST omitted both dataPoints and nextPageToken.
Only LIST/RECONCILE missing collection with no usable token becomes complete empty
terminal page. A usable token continues; arrays follow normal rules; null/object/
string/number/boolean/malformed shapes stay invalid. Rollup is not broadened. The
repaired completed-window replay made zero calls.


<a id="sleep-agreement"></a>

<a id="sleep-agreement--sleep-deviceaccount-agreement-and-canonical-gates"></a>
## Sleep device/account agreement and canonical gates

<a id="sleep-agreement--10-cross-device-agreement"></a>
### 10. Cross-device agreement

Pair comparable metrics separately; do not compare proprietary vendor scores as if they were the same construct.

- Preliminary exploratory report: exactly 14 paired nights.
- Provisional canonical-source decision: at least 42 paired nights across at least six weeks, adequate coverage, and no known firmware/method break.

These are engineering evidence gates, not claims that one device is objectively more accurate. For sleep duration, stages, RHR, and HRV, report paired difference/systematic bias, MAE, RMSE, and Bland–Altman limits (or robust quantiles when assumptions fail). Correlation is secondary; Lin's CCC may supplement the stronger gate. A rule change remains reversible/versioned.

<a id="sleep-agreement--r05-agreement--canonical-sleep"></a>
#### R05 agreement / canonical sleep

Frozen design from #97:

- Legacy sleep pairing uses local wake date and one eligible main overnight session per source/date; naps and ambiguous mains are excluded.
- device_pair needs explicit device metadata; family_pair is exploratory. Manual Google-edited evidence is excluded from the strong 42-night gate.
- Comparable session metrics are projected separately; native scores are display-only, not equivalent measurements.
- Difference is google minus garmin; N, bias, MAE, RMSE, Bland–Altman limits and robust summaries retain coverage, association secondary.
- Exploratory gate: 14 paired nights. Canonical gate: 42 valid device-pair nights across at least six weeks plus coverage/stability. Garmin remains default until a reviewed versioned per-metric rule; no switch from N/correlation alone.
- R05 may close without a canonical change when evidence is insufficient.

The separately accepted [account-observation contract](#sleep-agreement)
permits eligible identified account/family evidence and uncertain singleton roles
without device-equivalence/canonical claims. #317 source-only views reuse those
rules, exclude explicit naps, preserve multiple sessions without pooling/winner and
apply source/record/provenance gates to Garmin score/naps and the primary table.
The original DEVICE_PAIR/role/native-gate findings were corrected and independently
re-reviewed before integration; legacy Compare/Agreement is unchanged.


`account_wearables_sleep_observations_v1` is a separately selected exploratory
cohort under issue #122 and Integrator note `5701378562`. It is not
Garmin-vs-Fitbit/device agreement, device accuracy or interchangeability evidence.
It can never qualify for canonical selection, #105 or the 42-night gate.

Select it explicitly with
`SleepPairingQuery(cohort=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS)` and pass the
result through the existing metric projection, agreement persistence and report
services. The legacy pairing query `all` still selects `device_pair` and
`family_pair`; their rules, serialized pairs and version identity are unchanged.
The report's `all` filter includes published runs for the new cohort as well.

<a id="sleep-agreement--pairing-rule"></a>
### Pairing rule

`r05-account-wearables-sleep-pairing-v1` reads current persisted projections,
using the same stored local wake-date join and metric eligibility machinery.

- Garmin evidence must belong to a valid Garmin provider/account source. Device
  attribution is preserved exactly; the reader never assigns Vivoactive 5.
- Google must have an explicitly identified source or eligible
  `google-wearables` family. Unattributed identities, excluded/broad families,
  conflicting source eligibility, invalid records and missing wake dates remain
  excluded. Explicit source filters bound the query before pairing.
- Exclude every explicit `nap=true`. Do not rewrite missing, null, invalid or
  false main/nap/manual-edit values.
- Competing Google sources on the same wake date are excluded before role
  selection. Multiple Garmin records are also ambiguous.
- Within one Google source, use its explicit `main=true, nap=false` rule.
  Multiple explicit mains are excluded; other candidates retain an explicit
  `google_explicit_main_preferred` exclusion.
- Otherwise exactly one remaining Google session may supply an observation.
  More than one is excluded without longest/latest selection. This fallback
  does not assert that a session is an overnight main: even explicit
  `main=false` remains false and the observation's session role is flagged
  uncertain.

The pair freezes the role states/values, manual-edit state, source eligibility,
candidate IDs, chosen rule/selection and uncertainty flags. The query, pairing
result and agreement run all carry the new pairing version. An explicit attempt
to persist this cohort under another pairing version is rejected. Existing
frozen runs remain intact and replay uses their original snapshots. No migration
or provider normalization change is required.

<a id="sleep-agreement--report-and-gates"></a>
### Report and gates

The existing per-metric statistics become available at 14 valid nights, without
an additional span gate. Metric missing/null/zero and partial-evidence rules are
unchanged. The strong-gate eligible count is always zero and canonical proposal
eligibility is always false, including at 42+ nights. The report and frozen
night drill-down show the cohort label, uncertainty notice and inclusion or
exclusion basis. Independent Reviewer and Integrator acceptance, followed by
the bounded Owner-only live re-check, remain separate delivery gates.

<a id="saved-sleep"></a>

<a id="saved-sleep--latest-eligible-saved-sleep"></a>
## Latest eligible saved sleep


This default-only card shows `sleep_duration_asleep_seconds` separately for one
exact Garmin source and one exact Google source. It reuses the accepted
`read_source_sleep_night` / `resolve_source_sleep_point` rules: current typed
sessions, source eligibility, Google main/nap preference and uncertain singleton,
metric eligibility, explicit zero, partial records and same-night ambiguity.
It does not change those readers, canonical selection or explicit-date views.

Observation date is the typed persisted local **wake date**, never parent-record,
UTC, receipt, refresh or snapshot date. Age is evaluation local date minus wake
date in civil days. Search excludes dates after evaluation; there is no age
threshold. Refresh and unknown snapshot age cannot invalidate saved history.

An explicit exact source remains authoritative. For Google, the shared
[metric source selector](#metric-source-selection) evaluates each source through
this same bounded latest reader; one eligible source is selected only after
complete discovery. Multiple eligible/ambiguous candidates or an incomplete
search remain blocked. Garmin source selection is unchanged. Search walks observed wake-date
groups newest first, skipping ineligible groups while disclosing newer exclusions.
An older eligible night is explicitly historical; no empty search proves that
sleep was never collected. Missing/invalid/conflicting nights never become zero.

Use one read-only physical snapshot for both providers. Bound source inventory to
32, examined date groups to 32 and candidate records to 256, preserving complete
same-date groups and the existing 200-record night cap. SQLite work/time guards
also bound the wake-date sort (there is no wake-date index in the accepted schema).
Overflow/read failure yields no selected value from an incomplete group/search.
No schema/index migration, provider request, raw-body read or persisted change.

UI shows duration, source, wake date, civil-day age, partial/uncertain-role cues and
concise newer-conflict/missing notices. It uses OwnerDate and existing Data layout;
no technical JSON is added to an information badge. RHR/provider status remain
their existing independent blocks. This is synthetic engineering validation,
not Owner UAT or full completion of either issue.


### Saved sleep production-shape interpretation (#462 / #464)

Garmin Sleep normalization `r02-garmin-sleep-normalization-v3` accepts paired
`dailySleepDTO.sleepStartTimestampGMT/Local` and `sleepEndTimestampGMT/Local`
as integral epoch milliseconds. GMT establishes the instant; Local is a nominal
wall-clock encoding. Their exact whole-minute difference establishes each
endpoint's fixed offset, never an IANA zone or host timezone. Preserve field
paths and original Local value; `calendarDate` remains the explicit wake date.
Invalid/conflicting evidence cannot become an eligible instant. Local-only
evidence retains its local clock and original value without UTC; absent timing
retains the previous date-only/unknown outcome.

Production `sleepLevels[].startGMT/endGMT` are explicit GMT interval boundaries;
integral numeric `activityLevel` maps `0=DEEP`, `1=LIGHT`, `2=REM`, `3=AWAKE`.
The mapping is corroborated by [upstream SleepState](https://github.com/abrander/garmin-connect/blob/cb0fca0da6bf3f645de01c092df0f324dfd51220/SleepState.go#L6-L28);
this is implementation evidence, not a Garmin schema guarantee.
Unknown codes, malformed/order/gap/overlap/boundary conflicts and competing stage
aliases make the collection incomplete. Summary end validates the final stage;
it never replaces `complete_stage_boundary` or supplies missing stages. Endpoint
offsets are retained independently; intermediate offsets are not inferred across
DST/travel. Fixed-offset changes remain excluded by v6. Prior ISO/`levels`
shapes retain their semantics. Other Garmin streams retain their existing versions.

Production reconciliation deliberately retains the exact legacy v2 temporal
identity inputs, record-ID/sample-token precedence and source partition while
persisting enriched measurement evidence. This prevents an id-less date-only
original from becoming a second instant-keyed current night. It does not adopt
an arbitrary same-date row. Corrections and stale-observation authority retain
the existing collection rules; sleep version-current checks include empty windows.
For a row-free window, a current, non-invalid interpretation of the exact latest
original and receive epoch proves normalization currentness despite v2/v3 UUID
ordering; it does not prove acquisition completeness or confirmed-empty sleep.

Google Sleep normalization uses `r04-google-normalization-contract-v3`; other
streams retain v2; explicitly requested historical v1/v2 keeps its previous
metadata/unknown-field shape for immutable retries. The fixed-seed v2 demo
explicitly retains its v2 Google interpretation and strict reset certificate;
the reset allowlist is not broadened. V3 preserves `metadata.mainSleep` separately as
`sleep_metadata_main_sleep`, with its actual field path and presence state,
while retaining legacy `metadata.main`. The saved-source-night-only policy
`saved-google-main-sleep-v2` accepts explicit `mainSleep=true` with nap missing,
null or false, without processing/stage-status role gates. This follows the
[Google SleepMetadata schema](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints#Sleep.SleepMetadata),
including its main-night fallback without stages. Never synthesize `nap=false`.
Explicit nap=true excludes, invalid role fields and contradictory boolean aliases
exclude, false/null remain unconfirmed and multiple mains remain ambiguous.
Absent `mainSleep` keeps the legacy main-only policy. Source/immutability,
variant and endpoint gates remain independent. Frozen account-pairing v1 helpers
are unchanged. Existing originals require explicit replay before this new typed
metric exists; missing/invalid provider `updateTime` retains the accepted
fail-closed revision guard and can block replacement even for the same original.

`garmin.sleep_preview.preview_saved_garmin_sleep` accepts an existing read-only
snapshot, exact source, explicit observation IDs (maximum 30), a 1–30-day range
and one-MiB verified originals. It runs production preparation and reports
hypothetical identities, timing availability and currentness/replacement blockers.
It never prepares/migrates runtime, persists, contacts providers or asserts that
stored v6 eligibility changed. The existing reprocess `--dry-run` is not this
read-only operation. This preview grants no recovery or Stable write authority.

<a id="metric-source-selection"></a>

<a id="metric-source-selection--metric-specific-source-discovery-and-selection"></a>
## Metric-specific source discovery and selection


Google is one logical provider in the normal view. The backend selects an exact
saved source only when metric-specific eligibility proves one usable candidate
inside the requested scope and every candidate search completes. Selection does
not pool records, rewrite identities or establish lineage. Equal durations or
RHR values, UUID order, latest dates and history length never choose a source.

`metric_source_selection.select_metric_source` reuses the accepted Statistics
Sleep discovery decision. Readers retain eligibility, units, dates, work limits,
correction/retirement and provenance. An ambiguous-only candidate competes even
without a scalar. Two usable candidates conflict even on disjoint dates. Any
incomplete candidate blocks automatic selection; a prefix cannot supply a mean.
Exact overrides bypass unrelated identities and do not fall back if empty.

Consumers:

- Overview RHR evaluates all Google identities with the existing bounded period
  reader (at most 32 sources, 400 days, 4096 records/source and 256 records/day).
  The selected packet is reused without changing values, dates, n/N, exclusions,
  rational mean or last-observation provenance. Other metrics and out-of-window
  observations do not establish RHR eligibility.
- Data latest RHR explicitly opts into `read_saved_rhr(google_auto_select=True)`
  for Google default-latest only. Each exact reader checks at most 32 observed
  date groups and 256 candidate records across an inventory of at most 32 sources,
  in the same read-only snapshot under the Data SQL/time budget. A complete reader
  proves its newest eligible observation, not an exhaustive scan of older history.
  Ambiguous-only sources compete; any incomplete search blocks automatic choice.
  The chosen exact packet retains date, age, exclusions and provenance. The caller's
  query stays source-unspecified, with the chosen ID in `source_identity` and an
  additive `source_selection` disclosure. A successful automatic choice shows the
  value immediately, with an optional exact override in closed details. Empty,
  conflict and incomplete states remain explicit. The shared reader's default,
  Garmin, exact overrides, explicit periods and export/evidence behavior are
  unchanged; no Sleep preference or period mean is reused as latest RHR.
- Data Sleep evaluates each Google source with the existing latest reader:
  32 sources, 32 observed date groups, 256 records and 200 records/night. This is
  a bounded latest search ending on the evaluation date, not a period aggregate.
  A complete no-value single-source result retains its original exclusions.
- Statistics Sleep keeps its existing five windows, loader, caps and deadline.
  The extracted source-cell function is also used by Sleep evidence for its
  explicit 7/30-day window. Existing family/record/role gates exclude broad
  family list copies before source choice; identical values are not the proof.
- Sleep evidence opts into Google provider discovery with `google_auto_select`.
  Combined forwards `sleep_google_auto_select`, also exposed in its CLI. These
  flags default to false, preserving explicit and omitted-provider contracts.
  Once selected, the accepted exact range reader produces unchanged points and
  provenance. Its own 400-record range cap still applies: unique selection is
  not a promise that every richer detail read fits its limits.

Sleep evidence returns the same `sleep-window-selection-v1` decision as
Statistics, projected through an explicit recursive allowlist. Conflict,
incomplete and no-eligible outcomes have no selected source and `source_range`
is null. These are complete labelled outcomes, not missing Google sections.
A successful automatic request records `request.sources.google=null` (no exact
ID requested), with the resolved ID only in the provider section and selection.
The shared loader borrows the evidence caller's SQL guard; it never replaces or
removes that guard, changes pragmas, weakens write denial or opens another snapshot.

Acquisition coverage, refresh and snapshot age stay separate and may be unknown.
No provider calls, raw-file reads/deletion, new scopes, schemas, permissions,
canonical selection, live connector setup or Stable operations are involved.
Tests use real persistence/readers and synthetic profiles. Owner UAT is separate.

<a id="cycling-source-discovery"></a>

<a id="cycling-source-discovery--cycling-source-discovery-and-eligibility"></a>
## Cycling source discovery and eligibility


The #347 backend exposes `CyclingSourceDiscoveryService(session).discover(...)`
with version `cycling-distance-source-discovery-v1`. It discovers saved exact
Garmin sources for **one metric**, `cycling_distance_meters`, without choosing
one. It does not change Statistics, Sleep selection, Activity evidence or CLI.
UI consumption is described below; independent integration acceptance and Owner
UAT remain separate steps.

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

<a id="cycling-source-discovery--explicit-periods-and-meaning"></a>
### Explicit periods and meaning

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

<a id="cycling-source-discovery--result-contract"></a>
### Result contract

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

<a id="cycling-source-discovery--missingness-coverage-and-bounded-failure"></a>
### Missingness, coverage and bounded failure

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

<a id="cycling-source-discovery--statistics-ui-consumer"></a>
### Statistics UI consumer

`web.statistics.statistics_cycling_cell` projects discovery into the Garmin
cycling-distance card only. With no explicit `garmin_source_id`, all five
Statistics periods use the same explicit window and read snapshot as the page.
Automatic selection requires a completed discovery, `unique_eligible_source`,
exactly one usable option and no ambiguous source. Explicit zero is usable.
Multiple usable sources or duplicate-current ambiguity show a visible selection
request. An incomplete search suppresses the entire automatic value and its
official counts; a successful prefix is never a default. No eligible distance
stays unavailable, including confirmed-empty collection coverage.

The selected exact source is labelled on the card. Candidate counts/exclusions
and search completeness are disclosed separately from acquisition coverage.
Completed cycling discovery identities also supply labels and provider selector
options when the independently budgeted shared summary inventory is incomplete;
this presentation union does not rewrite its cells or claim that its search completed.
Google remains labelled `not_collected`; no cross-provider delta is introduced.
This does not change eligibility, reducers, source records or discovery policy.

The existing explicit provider override retains its current summary read and
does not fall back to another source, even when it has no distance. Automatic
selection does not alter the shared summary packet, Steps, Sleep, tennis or
activity-count selection. The native form retains only human overrides, so
period changes reevaluate automatic eligibility. A cycling session link uses
the metric's exact source and carries an empty `origin_garmin_source_id` in
automatic mode; its return link preserves that mode instead of creating a
provider-wide override. Existing links without that parameter retain their
previous explicit return behavior.

Synthetic route/browser checks cover this consumer. Live Owner/provider/device
acceptance and real-profile latency are separate, unverified gates.

<a id="analytics-and-stress"></a>

<a id="analytics-and-stress--analytic-input-deterministic-services-and-stress-adapter-versions"></a>
## Analytic input, deterministic services and Stress adapter versions

<a id="analytics-and-stress--9-deterministic-analytics"></a>
### 9. Deterministic analytics

Pure Python/SQL services calculate:

- summaries, percentiles, baselines, and period comparisons;
- coverage/freshness and exclusions;
- trends and robust slopes;
- anomalies with baseline/sample context;
- activity/session comparisons;
- lagged associations and effect sizes;
- source disagreement/agreement;
- versioned derived measurements.

R01 weight defaults are fixed in its spec: 21-day-half-life time-aware EWMA for display and trailing-90-day Theil–Sen slope for rate, with minimum evidence gates. Composition derives same-session estimated fat and lean mass and never crosses algorithm groups. Kalman/LOESS/STL are not R01 defaults.

Context analytics uses event-aligned windows and matched controls rather than a year-long boolean Pearson shortcut. Quantitative output includes event count, matching rules, coverage, effect size, and caveats. Structured n-of-1 experiments are a later extension of the same event model.


This is the bounded read/semantic contract that sits between accepted R02 Garmin
projections and deterministic R03 analytics. It does not redesign ingestion, add
a scheduler, calculate LLM mathematics, ingest Fitbit/Google, parse FIT/GPS, or
introduce a generic multi-provider framework.

Implementation: `healthcheck.garmin.analytic_contract`.

<a id="analytics-and-stress--goals"></a>
### Goals

1. Keep statistically different provider fields as distinct analytic metrics.
2. Preserve series time semantics from the [normalization contract](#garmin-normalization).
3. Expose metric-level analytic availability that is stricter than operational
   surface `present`.
4. Freeze a reproducible input DTO / evidence manifest for each deterministic
   calculation.

<a id="analytics-and-stress--aggregate-vs-sample-identity"></a>
### Aggregate vs sample identity

Do not collapse provider fields that mean different aggregates into one analytic
metric code.

| Metric code | Aggregate kind | Window | Reviewed source fields |
| --- | --- | --- | --- |
| `stress_daily_average` | `daily_average` | `calendar_day` | `avgStressLevel` |
| `stress_daily_maximum` | `daily_maximum` | `calendar_day` | `maxStressLevel` |
| `stress_sample` | `sample` | `point` | `stress`, `stressLevel`, series arrays |
| `spo2_daily_average` | `daily_average` | `calendar_day` | `averageSpO2` |
| `spo2_trailing_7d_average` | `trailing_aggregate` | `trailing_7d` | `lastSevenDaysAvgSpO2` |
| `spo2_sample` | `sample` | `point` | `spo2`, `spo2Percent`, series arrays |

Rules:

- Preserve the reviewed source field/path on the metric row.
- Do not substitute maximum for average, or a seven-day trailing average for a
  daily value, when the requested analytic metric is absent.
- Operational acquisition success for a stress/SpO2 surface is not permission to
  invent a missing aggregate.

<a id="analytics-and-stress--versioned-activity-session-extension-319-b1"></a>
### Versioned activity session extension (#319 B1)

Analytic rules `r03-garmin-analytic-rules-v2` add:

| Metric code | Aggregate kind | Window | Unit | Reviewed source fields |
| --- | --- | --- | --- | --- |
| `max_heart_rate_bpm` | `session_maximum` | `activity_session` | `bpm` | `maxHR` |
| `training_effect` (existing aerobic alias) | `provider_session_score` | `activity_session` | `points` | `aerobicTrainingEffect`, alternate `trainingEffect` |
| `anaerobic_training_effect` | `provider_session_score` | `activity_session` | `points` | `anaerobicTrainingEffect` |

Maximum and average HR are independent identities. Both effects remain separate
provider-native scores with unverified producer attribution; raw camelCase rows
and labels are not additional analytic metrics. There is no combined effect,
cross-effect substitution or energy metric in this extension.

Comparison algorithm `r03-02-garmin-activity-comparison-v1` is unchanged; its
output rule changes from `r03-02-v1` to `r03-02-v2`. Frozen v1 outputs retain the
original ordered eight codes: `duration_seconds`, `distance_meters`, `speed_mps`,
`heart_rate_bpm`, `power_watts`, `cadence_rpm`, `training_effect`,
`acute_training_load`. V2 defaults append `max_heart_rate_bpm`, then
`anaerobic_training_effect`. Serialized query codes, definitions, rule versions,
input manifests and result hashes identify each output without reinterpreting
old results under a new default. A legacy projection without either new row
reports `not_computable` / `metric_absent_from_projection`; it does not invent
coverage or run replay. The input DTO shape remains v1, and normalization version
is retained in each immutable evidence reference.

<a id="analytics-and-stress--series-time-semantics"></a>
### Series time semantics

`_sample_temporal` (incremental sync series expansion) follows the same rules as
normalization:

| Provider stamp | Analytic precision | UTC | Local evidence |
| --- | --- | --- | --- |
| aware ISO / offset datetime | `instant` | normalized UTC | wall time + offset/zone when present |
| explicit GMT/UTC field or epoch stamp | `instant` | UTC by field/epoch semantics | no invented local zone |
| local-only naive datetime/string | `local` | **none** | `local_wall_time` / source local timestamp |

Genuinely local-only naive timestamps must not receive an invented UTC timezone.
Date-only values remain local dates. Travel/timezone frameworks are out of scope;
DST/local-only regressions exist for intraday/lag analytics.

<a id="analytics-and-stress--metric-level-analytic-coverage"></a>
### Metric-level analytic coverage

Operational coverage `present` means the acquisition surface succeeded. It does
**not** prove every dependent analytic metric is complete.

`MetricAnalyticCoverage` reports, per metric code:

- availability: `available`, `missing`, `null`, `zero`, `invalid`,
  `not_computable`, or `partial`;
- parsed sample counts and usable/null/zero/invalid/missing counts;
- deterministic exclusions / shape-loss reasons;
- whether the operational surface was present.

Sleep family rule: `sleep_duration_seconds` presence must not imply
`sleep_score`, `sleep_stages`, or `nap_duration_seconds` availability. Missing,
null, and explicit zero remain distinct states.

<a id="analytics-and-stress--evidence-manifest--input-dto-v1"></a>
### Evidence manifest / input DTO v1

Contract version: `r03-garmin-analytic-input-v1`.

Each deterministic calculation may freeze an `AnalyticInputDTO` containing:

- metric definition (code, unit, aggregate kind, window);
- selected value/state and field path;
- analytic date/time semantics;
- source / algorithm identity;
- metric-level coverage/availability;
- immutable evidence references:
  raw payload id + content hash, observation id/key, record id + idempotency key,
  metric row id, normalization/reconciliation contract versions;
- stable `manifest_hash` over the canonical JSON body (excluding the hash itself).

Same evidence + rule version => same DTO/manifest hash. A later current-record
correction updates the live projection but does not rewrite an already-recorded
manifest that points at immutable raw/observation evidence and the selected
values frozen at analysis time. This is not a second Garmin store and not generic
event sourcing.

Producer-side storage grounding: `build_analytic_input_from_storage()` takes a
persisted record/metric locator, joins the existing raw-payload + observation
provenance chain, constructs `AnalyticEvidenceRef` itself, and fails closed on
missing or mismatched provenance. Selected input freezes scalars and, for
collection-valued metrics such as `sleep_stages`, the canonical stage-interval
collection used by the calculation.

<a id="analytics-and-stress--selected-day-stress-adapter-357-backend-only"></a>
### Selected-day stress adapter (#357, backend only)

R03 daily stress selection uses rule `r03-01-v2` and explicit
`r03-01-stress-daily-mean-applicability-v1` selection semantics. Before daily
ambiguity resolution, only a proven normalizer-created **missing** daily-mean
placeholder on `heart_rate`, `body_battery`, `spo2` or `respiration` may be a
non-candidate. Proof requires agreement of persisted intraday surface and
source/day collection key, exact missing scalar path/state/unit/attribution,
reviewed normalization/reconciliation versions, and the selected raw/observation
and committed normalization event/batch chain. The observation identity is
recomputed, including its matching `<surface>.json` filename; filename or missing
state alone is insufficient. No additional raw originals are scanned for this
classification. Missing or conflicting provenance remains a candidate (or fails
input assembly), so it cannot resolve ambiguity in favor of another value.

Genuine stress missing/null/invalid, unexpected nonmissing foreign rows and all
genuine duplicates, including equal values, retain the existing fail-closed
per-date semantics. No first-usable or value-based selection is performed.
Non-candidates are absent from points, availability counts and statistics; the
separate `applicability` audit retains their frozen input/evidence references,
surface/collection/observation/event identities and counts. Both this audit and
all frozen inputs are bound into the result hash. The fetched-row cap applies
**before** applicability; non-candidates do not make an over-cap query admissible.

Explicit `selection_version="r03-01-v1"` requests the legacy strict selection,
with its original serialization and hash semantics. Other scalar metrics retain
v1. Existing frozen results are never reinterpreted. The compatible stress
adapter contract is `garmin-daily-stress-personal-baseline-v2`; it requires the
new R03 rule/selection version in both current and history, and copies the
applicability audit. It never filters R03 participants or recomputes a narrower
baseline. Its date, timezone and ordinary acquisition proof remains unchanged:
no Owner timezone policy or implicit Moscow fallback is introduced.

`GarminQueryService.stress_baseline` requires an explicit source, selected date D
and aware evaluation instant. In one physical read snapshot it calls R03 for
`[D,D]` and `[D-28,D-1]`. At least 21 distinct eligible historical dates are
required; this product gate is not a clinical threshold. It copies R03's frozen
median and Type-7 P25/P75, and computes only current minus historical median in
points. No percentile/trend/robust-z interpretation is added.

All participating daily means must retain exact source, `avgStressLevel`, stored
unit/attribution and compatible method evidence. The stress-specific equivalence
of normalization v1/v2 is pinned to #319 commit
`4a7bc96d7940c2e5161a210de2c179641bfa2aa6`: daily stress parsing, calendar meaning
and metric coverage did not change. Unknown versions are not assumed compatible.
Record-wide partial parse status can concern unrelated sibling fields and does
not downgrade stress. Participating metric-specific partial or incompatible
evidence withholds the entire comparison, without subset percentile recomputation.

Completion requires the referenced ordinary `garmin_incremental` or
`garmin_historical` successful acquisition of `stress.json`, its exact committed
observation/event/batch provenance, and receipt at/after the source-day end.
Only the referenced original JSON is read, bounded to 1 MiB per participant
(at most 29); its genuine `calendarDate`, daily mean and unambiguous IANA timezone
must agree with the selected evidence. Source-clock checks reconcile normalized
clock evidence and supplied offsets with the named timezone, respecting DST.
They do not require every optional raw clock field to survive normalization:
malformed optional `startTimeLocal` may normalize away without invalidating an
independently valid `calendarDate`, unambiguous timezone and post-boundary
acquisition. Malformed observation identity fails
closed. Host timezone, requested window, mutable coverage, raw deduplication receipt,
and later reprocess timestamps are not proof.
Absent date/timezone/acquisition proof retains the saved current value with a
specific unavailable comparison reason. A skipped midnight is unproven; an
ambiguous midnight uses the later valid boundary. No acquisition/intraday
completeness, hardware continuity, health grade or causal claim is made.

This slice does not expose a route or choose a UI surface. Source selection, actual
Owner coverage and future UI acceptance remain separate.

<a id="analytics-and-stress--explicit-owner-selected-moscow-analysis-day-policy-357"></a>
#### Explicit Owner-selected Moscow analysis-day policy (#357)

Owner decision 2026-10-15: Moscow time is acceptable, including rare travel.
`GarminQueryService.stress_baseline(..., analysis_day_policy=
"owner-selected-europe-moscow-analysis-day-v1")` explicitly opts into adapter
`garmin-daily-stress-personal-baseline-v3`. Omitting the argument or supplying
`None` retains strict adapter v2, including its body/hash semantics and required
source-zone proof. Other policy values are rejected; host/browser timezone,
settings and source selection never implicitly enable this policy. R03
`r03-01-v2` and its applicability selection remain unchanged.

The policy selects **Europe/Moscow as the analysis completion zone**, separately
from the source zone. Garmin `calendarDate`, original timestamps and daily means
remain unchanged: these are Garmin's saved daily values with their original
dates, **not means recalculated over Moscow civil days**. D and `[D-28,D-1]`
continue to refer to those original dates. Policy version, analysis zone and date
meaning are bound into the adapter result hash; participant proofs also bind
the policy version and analysis zone. The embedded R03 evidence/hashes remain
source evidence, without rewritten temporal fields.

This first policy supports an absent source zone (`source_timezone: null`,
`source_timezone_status: unproven`) and an original confirmed `Europe/Moscow`
zone. Unknown and confirmed Moscow participants may coexist. The policy never
turns an analysis-zone selection into source-zone or completion proof. Present
null/empty/non-string/invalid zones, conflicting zone fields or persisted zone
evidence, and any confirmed other IANA zone withhold the **whole** comparison.
No incompatible participant is dropped and no subset baseline is recomputed.
All supplied recognized clock fields, offsets and alternate `date` evidence
must be valid and compatible with the original date and Moscow zone, including
fields normalizer selection did not retain. Unlike strict v2, malformed optional
raw clock evidence cannot be ignored by the opt-in policy. An absent clock is
allowed; an incompatible or malformed clock/date is not.
Every supplied naive wall clock must round-trip through the selected ZoneInfo
zone, even if normalization selected another date-only field and retained no
wall/instant. A DST gap fails; a repeated wall time requires a unique valid
instant supported by supplied UTC/offset evidence. No first-fold default is
used. Temporal conversion overflow also withholds the comparison rather than
escaping the reader as an exception. These checks do not persist an inferred
timestamp or source zone.

For each participating date, `ZoneInfo("Europe/Moscow")` determines the next
Moscow midnight boundary. The ordinary successful acquisition and exact
observation/event/batch/artifact chain described above remain mandatory, with
`started <= received <= completed <= evaluated` and **received >= boundary**.
Equality at midnight is admissible; one second before is not. Late evaluation,
reprocess/replay, projection time and raw deduplication time cannot rescue a
pre-boundary observation receipt. This establishes completion under the selected
policy only; it does not attest the source zone or complete intraday acquisition.

Every existing source/method/unit/zero/null/partial/21-of-28/cap/snapshot guard
continues to apply. This is a backend-only, synthetic-tested policy extension;
it adds no ingestion/schema/provider/UI/runtime operation or default policy.

<a id="analytics-and-stress--explicit-arithmetic-mean-comparison-357"></a>
#### Explicit arithmetic-mean comparison (#357)

Owner decision 2026-10-15: compare with the arithmetic mean. Both
`read_stress_baseline` and `GarminQueryService.stress_baseline` accept explicit
`comparison_method="arithmetic-mean-v1"`, selecting adapter
`garmin-daily-stress-personal-baseline-v4`. Omitted/`None` retains the original
v2 strict or explicitly selected v3 Moscow median-mode body and result hash.
Unknown comparison methods are rejected before any snapshot/read.

After **all** existing participant, applicability, method, unit, provenance,
acquisition, completion, partial, coverage and frozen sample-count gates pass,
v4 copies R03's frozen `baseline.mean` (computed by `statistics.fmean`) into
`comparison.mean`. Each eligible historical daily value has equal weight,
regardless of intraday sample count; missing dates/values never become zero.
The original dates `[D-28,D-1]` exclude D and still require at least 21 eligible
distinct dates out of 28. No participants are filtered and no subset is recomputed.

`delta_points` is the unrounded signed current daily value minus that frozen
mean; `direction` is `above`, `below` or `equal` relative to the mean. Reference
and delta must be finite, otherwise the whole comparison is `method_dependent`
with `frozen_baseline_mean_nonfinite` or `comparison_delta_nonfinite`, preserving
current value and evidence. An R03 statistics overflow before a frozen result is
returned withholds v4 comparison as `r03_statistics_nonfinite`, retaining any
already-read current evidence; no replacement mean or smaller sample is computed.
The legacy exception path is unchanged. `median`, P25 and P75 remain R03's
original statistics; the median is never relabeled as a mean.

The v4 body/hash binds `comparison_method` and the day policy explicitly:
`confirmed-source-timezone-day-v1` for the unchanged strict default, or the
existing `owner-selected-europe-moscow-analysis-day-v1` metadata only when
explicitly selected. Mean selection never enables Moscow implicitly. Embedded
R03 evidence and hashes remain unchanged, as do original source/date/time and
acquisition proofs, bounded two-query/single-snapshot reads and caps. This adds
no R03 algorithm, schema, provider, runtime, UI or date-selection changes.
The earlier real-copy applicability audit covered median mode only. The later
[bounded mean-mode receipt](https://github.com/LTstripes/Health-Check/issues/357#issuecomment-6194781870)
proves one completed-day control available and a different fixed D blocked by
early acquisition on the same isolated snapshot. It does not establish universal
coverage; missing days were not present in those inspected windows. Owner UAT
remains separate from synthetic evidence.

<a id="analytics-and-stress--overview-selected-day-presentation-357"></a>
#### Overview selected-day presentation (#357)

The existing **Стресс Garmin · среднее за день** card explicitly requests v4
arithmetic mean and the Owner-selected Moscow policy. D is the end date of the
existing Overview period controls, displayed as **Выбранная дата**; the page does
not search for a more convenient day. Its comparison history is always
`[D-28,D-1]`, independently of the Overview start date or 7/30/90-day length.
The saved current daily value, frozen historical mean and signed difference are
presented without a clinical good/bad interpretation. Formatting happens after
the reader's finite, unrounded comparison; a nonzero difference below 0.01 is
described as less than 0.01 rather than equal.

Unavailable comparisons show a short reason and retain any usable current value.
Missing, null, invalid or ambiguous D never falls back to the latest older value,
including the second stress cell in the existing collapsed source disclosure.
The adapter still owns all source, method, unit, partial, provenance, clock,
completion, 21/28 and bounded-read gates. The card adds neither a new technical
disclosure nor raw R03 proof output; existing technical evidence is unchanged.
This candidate UI slice requires independent review and Owner UAT before rollout;
it changes no provider, stored data, date-selection controls or Stable runtime.

<a id="analytics-and-stress--non-goals"></a>
### Non-goals

- LLM mathematics or free-form SQL analytics;
- scheduler / Fitbit / Google / FIT / GPS / dashboard redesign;
- generic multi-provider analytic framework;
- inventing missing aggregates or UTC for local-only samples.

<a id="context-capture"></a>

<a id="context-capture--context-revision-temporal-and-portal-contract"></a>
## Context revision, temporal and portal contract

<a id="context-capture--life-context"></a>
#### Life context

The canonical object is an event/exposure interval:

- original text;
- start/end plus precision/timezone metadata;
- capture source;
- optional tags with `suggested`, `confirmed`, or `rejected` status;
- parser/model version where structured suggestions were used.

The target event model preserves clear original text and permits later explicit interpretation. Implemented v0 capture sources are cli/manual/dashboard; Telegram remains reserved and rejected. Persistence never infers a date or parses relative words. Material ambiguity is resolved before the call. Suggested/rejected tag interpretation and event-aligned health analytics are future capabilities, not implemented v0 behavior; any later use of suggestions must disclose their lower evidence quality.


Context Capture stores small owner-authored health and lifestyle notes as local,
append-only evidence. It is a persistence and retrieval boundary only: v0 does
not interpret text, infer dates, assign AI tags, correlate context with health
metrics, or add context to reports.

<a id="context-capture--evidence-contract"></a>
### Evidence contract

- A logical event has a stable UUID and exactly one current revision pointer.
- Revision rows and their tag assignments are append-only. Revising an event
  creates the next numbered revision and atomically advances the pointer; prior
  text, time, capture source, and tags remain queryable with `--history`.
  Omitted tags retain their status and original provenance on a revision;
  explicitly supplied tags become confirmed under the new capture source.
- Original text is required, is stored without trimming or paraphrasing, must
  not contain NUL, and is limited to **4,000 Unicode code points**.
- An optional caller-supplied `--operation-id` makes an identical add/revise
  retry converge, including a partial revise retried after the current head has
  advanced. Identity binds the operation kind and explicitly supplied,
  normalized request fields; reusing it for different input fails closed.
  Generated and supplied operation IDs are returned by the CLI.

Supported explicit time forms are:

- one calendar date (`--date YYYY-MM-DD`), with no invented time or UTC;
- one ISO 8601 timestamp with `Z` or a numeric offset (`--timestamp`);
- a start/end date range, or start/end ISO 8601 timestamps carrying offsets.

`--timezone` optionally records an IANA zone for timestamp forms and validates
that the supplied local clock and offset are valid for that zone. Date-only
forms reject a timezone. Mixed-precision or reversed interval bounds fail
closed. Production persistence does not parse words such as `today`,
`yesterday`, or `last night`.

Capture sources implemented by v0 are `cli`, `manual` and `dashboard`. The
portal adapter uses `dashboard`; `telegram` remains reserved and rejected. Tags
are Unicode-normalized, case-folded, separator-normalized, limited to **64
code points**, and deduplicated. CLI tags are persisted with `confirmed` status
and their capture-source provenance. The schema can later represent
`suggested` and `rejected` interpretations without rewriting old revisions.

<a id="context-capture--portal-adapter--294-stage-a"></a>
### Portal adapter — #294 Stage A

The loopback portal exposes `/context` through the primary **Комментарии** tab
in the existing desktop shell. It adds, lists and revises through Context v0;
no new schema, weight-goal settings, providers or migrations are introduced.

- The form preserves original Unicode text and shows an editable event date.
  Optional local time accepts `HH:MM`, seconds or fractional seconds. One
  human-labelled city/IANA selector supplies the zone; the server resolves each
  event-date clock separately, then validates the exact offset-bearing timestamp
  with the unchanged `parse_timestamp` / `parse_interval` contracts. City labels
  always include the IANA key to distinguish ambiguous names.
- DST gaps fail closed with the draft and operation key retained. Repeated clocks
  show an explicit first/second occurrence choice with its actual offset, separately
  for each ambiguous interval endpoint. A changed endpoint/zone clears its previous
  choice. Intervals keep equal precision and strict UTC ordering under v0.
  Date-only input hides/disables the zone, submits no zone/occurrence, and never
  fabricates midnight or UTC. Without JavaScript, entering time first shows the
  selector on validation readback; no temporal guess is made.
- **Сейчас** explicitly populates browser-local date/minute and proposes the browser
  IANA zone for review; it performs no location lookup or proof of the user's city.
  The initial visible date uses the host calendar; it can be changed before saving.
  Event time/precision and automatic recorded-at UTC are displayed separately.
- An edit whose event fields match its authoritative expected revision omits the
  temporal argument to `revise`. This retains source spelling (`Z` / numeric zero,
  seconds and fractional trailing zeros), precision, UTC, offsets, IANA absence and
  tags exactly, including on old retries after the head advances. Offset-only legacy
  records show their original time and have no invented city/zone; changing their
  time requires an explicit IANA choice. Historical second-level offsets are never
  rounded: unchanged records are retained, while newly resolved clocks unsupported
  by v0 fail validation. The service/schema semantics remain unchanged.
- POST/303/GET reads the committed current revision from storage. A hidden operation
  key supports identical retries and a submitting guard prevents double clicks.
  An older operation retry shows the latest current version with a notice and history
  link. A hidden expected revision and a serialized write transaction reject stale
  editors; the escaped draft is retained for comparison, never silently overwrites.
- Current entries use inclusive explicit date/interval-overlap filters (initially the
  last 30 days), most recent first, with a 50-entry bound and an overflow notice.
  A per-event history link explicitly requests the latest 50 append-only revisions;
  their currentness, revision number and source are visible. No deletion or AI tags.
- Existing UI Host/Origin protections apply to all writes. The adapter accepts bounded
  URL-encoded forms only (64 KiB; text 4000 code points), rejects duplicate/foreign
  fields, escapes rendered text, sends `Cache-Control: no-store` and uses generic
  validation/conflict/storage messages. Submitted text is retained only in the form
  draft/readback, not included in error diagnostics or logs.

Synthetic HTTP/service checks cover persistence across app restart, source/precision,
retry, stale/concurrent edits, history, escaping and negative input/security cases.
The browser check uses desktop Chromium 1024/1440 with an explicit disposable
synthetic profile; Owner rollout and durable-profile write/readback remain separate.

Context command/list limits and durable-profile workflow are in [Owner Operations](OWNER_OPERATIONS.md#context-operations). Context v0 is introduced by migration 0013; that historical introduction is not a current global migration-head assertion. Current Context can be exported only through the separately versioned bounded evidence boundary below.


<a id="ui-evidence-states"></a>

<a id="ui-evidence-states--ui-evidence-state-technical-contract"></a>
## UI evidence-state technical contract

<a id="ui-evidence-states--state-and-evidence-contract"></a>
### State and evidence contract

`templates/owner_ui.html` supplies `state_chip(state)` and the native, initially
closed `technical_details()` caller block. The ten shared keys are `present`,
`partial`, `confirmed_empty`, `unknown`, `unavailable`, `insufficient`,
`not_requested`, `loading`, `error` and `no_change`. Unrecognized states display as
unknown. Loading/error describe requests; no-change requires an explicit comparison,
never missing evidence. Missing values are not zero; explicit source zero is real.

Interpretation-changing limitations stay visible. Detailed provenance, hashes,
exclusions, algorithm names and diagnostic statistics remain accessible behind
disclosure. Disclosure is a presentation pattern, not a privacy/access boundary.
It stays keyboard accessible without JavaScript. Informational algorithm/canonical
banners are `status`, not request errors. A failed refresh does not erase stored
history; an HTTP-successful check does not imply healthy collection.

Overview presentation does not pool sleep groups or change packet/hash semantics.
Weight retains canonical/algorithm boundaries. Sleep never substitutes a previous
night for the selected wake date or silently combines ambiguous same-date/source
evidence. Agreement remains exploratory and cannot choose a canonical source.
Activity does not add thresholds, recovery-time units, causal claims or best-lag
ranking. Source-specific aggregates are not automatically interchangeable.

Integrated boundaries include:
- #307 bounds only the Google daily-vitals display read to the trailing 400 inclusive days for longer custom periods and visibly discloses that scope; full Period Brief/Garmin period unchanged.
- #317 source-only account observations reuse accepted R05 eligibility, uncertain roles, exact wake dates and evidence. They do not loosen legacy device/family Compare or canonical rules. Google daily vitals are not within-sleep measurements; Google vendor-score availability is not promised.
- #318 preserves B−A and percent-to-A, blocks self-comparison, clears stale evidence and retains exact seconds in technical output. Power/cadence are hidden only when both sides lack eligible values. #335 folds history, not data.
- Only evidenced `tennis_v2` maps to Теннис; no generic `_v2` normalization or persistence change follows.


<a id="evidence-period"></a>

<a id="evidence-period--bounded-period-health-evidence"></a>
## Bounded period health evidence


`healthcheck.chat_evidence.read_period_evidence` exports a selected, bounded
read snapshot. The standalone command is `python -m healthcheck.export_chat_evidence`.
It reads accepted WeightQueryService, GarminQueryService, ContextService and
coverage/freshness services. It never changes the Period Brief packet or hash.
No UI adapter or live ChatGPT/MCP connection is supplied by this stage.

<a id="evidence-period--explicit-local-command"></a>
### Explicit local command


See [Owner Operations — analysis export](OWNER_OPERATIONS.md#analysis-export) for the complete operator invocation.


Every profile, range, domain and output destination is explicit. There is no
default private runtime, config/environment scan, migration, runtime preparation,
sync, refresh or provider/model call. The existing profile must be migrated to
this checkout's Alembic head; missing or outdated databases fail without repair.
The output directory must be new and outside the selected profile. It contains
`evidence.json` and `evidence.txt`; existing destinations are never overwritten.
Before any profile/database read or output creation, the command rejects a
resolved destination inside any Git checkout or linked worktree: a `.git`
directory or file at the destination or any ancestor is sufficient. This also
covers new nested destinations and existing directory links into a checkout.
The check applies to all profile classifications, including synthetic exports.
Known agent development roots without Git metadata must be supplied explicitly
with repeatable `--agent-workspace-root <root>` arguments; equal or descendant
destinations are rejected. Unreadable path checks fail closed. Rejection leaves
the profile untouched and creates no output directory or files.

Owner-only exports must go to an external Owner-controlled private directory,
never an agent workspace. Git markers and explicitly supplied roots are the
enforced identities; the command cannot classify other non-Git agent directories
and does not guess their role from basenames or scan machine configuration.
Normal stdout reports only completion; failures use bounded codes, without
paths, values or text. Sharing either file is a separate explicit Owner action.

`--profile-kind` is a trusted local operator assertion: `synthetic`,
`disposable_owner_clone`, or `durable_owner_runtime`. It is never inferred from
values, directory name or environment. This command does not verify backup
metadata or prove that a profile is current Stable. Those fields stay explicitly
unknown/not verified. Both Owner classifications produce `private_owner_data`:
the values and original comments must not go to public GitHub/CI logs. The
classification flag is not authentication and must not be accepted from an
untrusted remote caller by a future transport.

<a id="evidence-period--versioned-bounded-envelope"></a>
### Versioned bounded envelope

The envelope has its own `health-chat-evidence-v1` version and SHA-256 over
canonical compact JSON before adding `envelope_hash`. Its generated-at and
evaluation UTC/local-date clocks are separate. Inclusive requested and effective
local-date ranges are recorded. Requests over **90 calendar days** are rejected;
the range is never silently clipped. At most **8 explicitly selected Garmin
scalar metrics** and **100 rows per series/Context list** are allowed (default
50). Weight input materialization rejects over 2,000 scalar rows; Garmin retains
its existing 2,000-candidate hard cap. SQLite reads have an instruction/deadline
budget; JSON over 2 MiB fails before the output destination is created.

Domains are deliberately narrow:

- `weight`: accepted confirmed weight overlay with canonical flags, kg, source
  provenance and source/algorithm versions; existing derived trend/rate, daily
  and trend series, canonical freshness and coverage. Its usable count is the
  canonical service's input count, not the displayed overlay row count. The
  existing weight selection policy can span sources; no unsupported source
  filter or cross-algorithm composition calculation is invented.
  Coverage rule identity and requested weight cadence are recorded; use
  `--weight-cadence-days` to select that export policy (default 7). Runtime
  configuration is not read or silently claimed as the source of this setting.
- `garmin`: explicitly registered scalar identities, units, source-specific
  dates, precision, per-point missing/null/zero/partial/excluded status, usable
  counts and deterministic versioned results. One persisted source is selected;
  multiple sources require selection. No source returns `no_data` and unknown
  counts, not a zero measurement or confirmed-empty coverage. Acquisition
  coverage projects the existing Period Brief coverage reader without changing
  its contract. Other providers and collection-valued metrics are rejected.
- `context`: original text and tags from current revisions only, with stable
  event/revision identities, revision number, recorded-at and original temporal
  precision/offset/timezone/range. Selection uses the existing service's local
  date interval overlap, so an overlapping event may start before the requested
  range. Date-only events retain null UTC, rather than invented midnight.

Each exported page has `returned_count`, `total_count`, `limit`, `has_more` and
`truncated`. Counts and derived Garmin/weight results describe the full accepted
bounded input, even when displayed points are truncated. Context reads one extra
current revision to prove `has_more`; its total remains null when truncated.
Pagination/continuation is not provided by v1; choose a narrower range or a larger
allowed limit. An empty Context list does not establish absence of exposure.

Freshness is explicitly **provider-scope, current-at-evaluation-clock** evidence,
not selected-source freshness or coverage for the historical range. Only scopes
relevant to selected metrics/domains are exported. No collection-policy file is
read; policy disposition remains unknown. Coverage completeness and metric
usability are separate, so a usable value never establishes complete acquisition.

Measured facts, Owner text, deterministic derived results and absent future AI
interpretation have separate fields. Comments are untrusted data, never tool
instructions. No causal/medical claims are generated. The readable companion
uses the same frozen envelope and JSON-escapes original comments as literal data.
No credentials, raw payloads, GPS, artifact paths, import queues, configuration,
arbitrary SQL, database dumps or unrelated files are exported.

<a id="evidence-period--read-and-verification-boundary"></a>
### Read and verification boundary

SQLite is opened with `mode=ro`, `query_only`, a deny-write authorizer and one
physical transaction reused by nested services. This preserves live WAL visibility;
`immutable=1` is unsuitable for a durable runtime with uncheckpointed WAL. SQLite
may coordinate its existing WAL shared-memory reader locks; no application DB
write, journal-mode change, migration or artifact read is performed. Reusable
reads own their connection and roll back/close it after assembly.

Synthetic regressions exercise the production entry point, service equivalence,
Context corrections/overlap/offset, coherent reads during a concurrent revision,
coverage, availability, truncation, oversized/foreign requests and denied writes.
Exact-candidate CI and independent read/data/privacy review remain separate
from Integrator acceptance and Owner private UAT. File-only Stage A has no browser
gate. Later UI sharing and authenticated MCP transport require their own scoped
assignment and successful end-to-end verification.

<a id="evidence-sleep"></a>

<a id="evidence-sleep--exact-source-sleep-evidence"></a>
## Exact-source Sleep evidence


`healthcheck.sleep_evidence.read_sleep_evidence` returns one structured
`health-chat-sleep-evidence-v1` package for an explicitly selected **7 or 30
inclusive calendar days**, plus optional existing current Context revisions.
The package is independent of transport and has its own version/hash. No file
is required. `encode_sleep_evidence` and `render_sleep_evidence` are optional
JSON/plain-text consumers of the same frozen package; neither writes files.

```python
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.sleep_evidence import SleepEvidenceRequest, read_sleep_evidence

packet = read_sleep_evidence(
    profile=Path(selected_existing_profile),
    profile_kind="synthetic",  # trusted caller classification, not inferred
    request=SleepEvidenceRequest(
        end_date=date(2099, 1, 2), days=7,
        garmin_source_id=selected_garmin_id,
        google_source_id=selected_google_id,
        include_context=True, context_limit=50,
    ),
    evaluated_at_utc=datetime.now(UTC),
    evaluation_local_date=date(2099, 1, 2),
)
```

The caller supplies a trusted existing profile and explicit classification.
There is no profile discovery, environment/config scan, default private profile,
startup, migration, connection setup, refresh, provider call, schema change or
application database write. Missing/unmigrated profiles fail safely. This module
does not install a connector or make data reachable from ChatGPT/dot. An eventual
transport needs separate authorization and actual end-to-end verification.

<a id="evidence-sleep--request-and-exact-sources"></a>
### Request and exact sources

`end_date` is an exact `date`, and `days` is exactly integer 7 or 30 (not bool).
Start is end minus `(days - 1)`. Underflow and `date.max` are rejected. The
requested and effective inclusive local-date ranges are identical; no clipping,
earlier-period fallback or all-history mode exists. Evaluation clock is aware
and UTC-normalized separately from the explicit local evaluation date.

At least one provider must be selected. Garmin requires one explicit exact
persisted source ID. Google accepts either an exact ID or the opt-in
`google_auto_select=True`, using the same bounded metric/window discovery as
Statistics; an exact ID takes precedence. Omitted providers remain omitted.
See [metric source selection](#metric-source-selection) for conflict, incomplete
and no-eligible results. Existing explicit-source packets are unchanged. IDs are nonempty strings within the existing 36-character
database identity cap. ALL selected IDs are checked in the same snapshot before
the first `read_source_sleep_range` invocation: existence in `GarminSource` or
`GoogleSource`, then provider code `garmin_connect` or `google_health`. Unknown,
cross-provider and incorrect-provider selections fail without a partial package.
An existing source without rows in the selected period remains valid empty
stored evidence. Explicit reads return no unrelated inventory. Automatic Google reads disclose
only the bounded selection options, counts, dates and exclusion reasons through
a recursive allowlist. No Garmin/Google
pooling, canonical selection, pairing, agreement or new metric formula occurs.

<a id="evidence-sleep--preserved-reader-semantics"></a>
### Preserved reader semantics

Each provider section contains `selected_source_id`, provider identity, unknown
acquisition coverage and an allowlisted `source_range`. This calls the accepted
`source-sleep-range-v1` reader unchanged, including its exact date window,
source-local wake dates, gaps, ordering and hard caps. Explicit zero, missing,
null, invalid, partial, ambiguous and role-uncertain states are retained; excluded
sessions and per-point exclusions stay visible. Collisions never choose a
longest/latest winner. Google main/nap/CLASSIC/STAGES rules remain reader-owned.
Existing native Garmin sleep score and calendar-day nap identity stay separate.

The metric projection's accepted units and eligibility remain unchanged. Metric
cells preserve state/value/unit/field path, reason, zero, variant, comparison and
exclusion basis; timing evidence retains original precision, source-local dates,
timestamps, wall time, offsets and timezone. Date-only/null evidence gains no
invented midnight or current host offset. Accepted normalized seconds do not
become a new provider-native measurement.

Observed/missing dates and missing-wake-date counts mean **stored row presence**,
not complete acquisition or sleep absence. Null wake dates are located only by
the parent's persisted local date inside the window; unlocatable rows are outside
this bounded read. Acquisition completeness is explicitly unknown even when
every date has rows. Context absence does not prove absence of exposure.

<a id="evidence-sleep--explicit-recursive-whitelist-and-versioned-provenance"></a>
### Explicit recursive whitelist and versioned provenance

The public projection is a recursive allowlist in `sleep_evidence.py`:

- `SOURCE`, `RANGE`, `NIGHT_SOURCE`, `SLEEP_SESSION`, `POINT`: exact source
  identity, typed nights, metric cells, role decisions, exclusions and counts;
- `TEMPORAL`, `INTERVAL`: source timing and typed interval evidence, including
  endpoint temporal precision and offsets;
- `EVIDENCE`, `NORMALIZATION`, `ELIGIBILITY`, `BASIS`: immutable record/metric/
  interval/observation IDs, metadata content hashes, source class/cohort and
  eligibility, normalization/reconciliation/source contract versions, attempt
  identity/fingerprints, source-evidence state/path/hash, and the prior device
  eligibility independently of the account-observation decision;
- `CONTEXT`: event/revision identities, revision number/currentness, original
  text, capture source, created-at, exact start/end temporal metadata and tags
  with their status/provenance. Operation IDs are excluded.

Unknown fields at every depth are dropped. Scalar leaves reject containers,
preventing arbitrary nested payloads from passing under a formerly scalar key.
`wake_date_missing_by_source` allows only the requested source's key. Provider
source-evidence bodies (`record_source_evidence`) are excluded; state/path/hash
and eligibility decisions retain the relevant audit identity. No credentials,
provider bodies, GPS, storage paths, configuration, arbitrary SQL, queue records,
debug dumps or unrelated files are included. These allowlists are disclosure
rules, not a scrubber for Owner-authored Context text: authorized original text
is preserved literally as untrusted data.

The package records `health-chat-sleep-provenance-v1`, the accepted reader and
metric contract/rule versions. SHA-256 uses canonical compact UTF-8 JSON,
excluding `envelope_hash`. JSON/text serialize the same frozen package; text
JSON-escapes literal Context text. Context is never tool instructions or evidence
of causality. AI interpretation is absent and causality is not established.

<a id="evidence-sleep--snapshot-limits-and-privacy"></a>
### Snapshot, limits and privacy

The existing `chat_evidence._read_session` owns one WAL-aware SQLite `mode=ro`
transaction, `query_only`, deny-write authorizer, current-schema check, 20-million
SQL instruction budget and 20-second deadline. All provider validation, nested
Sleep reads and Context reads share it. No `immutable=1` or normal write-capable
engine/runtime factory is used. Existing WAL/SHM read coordination is possible;
application writes and journal/migration changes are denied.

The existing reader caps remain **400 records per selected provider** and **200
per night**. Overflow preserves `read_limit_exceeded`, empty days/series and
unknown counts; no successful winning prefix or false completeness is returned.
The adapter does not slice Sleep nights/metrics after resolution. Context allows
1–100 current rows, default 50; reads one extra to disclose `has_more/truncated`,
with unknown total on truncation. Current revision selection uses existing local
date interval overlap, so an event can start before the requested window.

Existing 2 MiB JSON output guard runs before the structured package returns.
Text has the same byte maximum, including its explanatory header. Storage/query
failures surface bounded `EvidenceError` codes without logging data or paths.
Profile classification is a trusted operator assertion (`synthetic`,
`disposable_owner_clone`, `durable_owner_runtime`); Owner profiles are private.
Snapshot metadata remains unknown and current Stable identity is unverified.
The classification is not authentication. No automatic upload occurs.

<a id="evidence-sleep--compatibility-and-checks"></a>
### Compatibility and checks

Existing `health-chat-evidence-v1` responses, exporter, MCP tools/domains/schema/
auth, Sleep readers, Period Brief, UI and database schema are unchanged. This is
an additional service, not an extension of the currently deployed MCP surface.

Synthetic tests cover exact 7/30 equivalence, source/provider validation before
read, zero/missing/null/partial, main/nap exclusions and ambiguity, date/offset/
precision, null wake-date bounds, corrections and coherent concurrent reads,
reader/Context/byte/SQL/time limits, recursive privacy projection, no files,
no provider calls and denied writes. Exact-candidate CI and independent data/
privacy review are distinct gates. Real Owner export, live connector access,
runtime UAT and causal/medical interpretation are outside this implementation.

<a id="evidence-activity"></a>

<a id="evidence-activity--exact-source-activity-evidence"></a>
## Exact-source Activity evidence


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

<a id="evidence-activity--exact-window-and-source"></a>
### Exact window and source

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

<a id="evidence-activity--reused-summary-semantics"></a>
### Reused summary semantics

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

<a id="evidence-activity--context-and-disclosure"></a>
### Context and disclosure

Optional Context uses unchanged `ContextService.list(history=False)` with local
date interval overlap. Current corrected revisions may start before the window;
superseded text and nonoverlapping notes are excluded. The exact Context
recursive whitelist from [Sleep evidence](#evidence-sleep) preserves event/
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

<a id="evidence-activity--snapshot-and-limits"></a>
### Snapshot and limits

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

<a id="evidence-activity--compatibility-and-verification"></a>
### Compatibility and verification

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

<a id="evidence-combined"></a>

<a id="evidence-combined--combined-evidence-and-v1v5-compatibility"></a>
## Combined evidence and v1–v5 compatibility


| Selected optional boundary | Detailed / compact identity | Compatibility |
| --- | --- | --- |
| none beyond Sleep/Activity/current Context | `health-chat-combined-evidence-v1` / `health-chat-combined-compact-evidence-v1` | default detailed; compact changes only the stated Sleep representation |
| Stress and/or Body Battery | detailed / compact `v2` | omitted optional metrics preserve v1 |
| HRV and/or RHR | detailed / compact `v3` | omitted vitals preserve v1/v2 |
| observed Steps and/or Weight | detailed / compact `v4` | omitted movement options preserve earlier shapes/defaults |
| explicit completed Steps | detailed / compact `v5` | exact Steps source required; omitted steps_view stays observed; UI form default is separately completed |

Later selected boundaries use their named version even when earlier optional
metrics are also selected. Every complete identity, field projection, guard and
legacy shape/hash rule follows below; no table shorthand changes an envelope.


<a id="evidence-combined--optional-completed-day-steps-v5"></a>
### Optional completed-day Steps (v5)

`CombinedEvidenceRequest.steps_view="completed"` explicitly selects the existing
`garmin-completed-day-steps-moscow-v2` reader for `steps_garmin_source_id`.
The default `steps_view="observed"` preserves the saved-observation reader and
all existing v1-v4 shapes/defaults. Completed mode requires an exact Steps source
and uses `health-chat-combined-evidence-v5` or
`health-chat-combined-compact-evidence-v5`, even when Weight/other metrics are selected.
The CLI opt-in is `--completed-day-steps` together with `--steps-garmin-source-id`;
omitting it retains the existing flags and observed semantics. For example:


See [Owner Operations — Explicit completed Steps v5](OWNER_OPERATIONS.md#export-completed-steps-v5) for the complete operator invocation.


Completed Steps uses the same physical read snapshot and aware UTC evaluation
instant as the other sections. Europe/Moscow is an explicit day-completion
display policy, not a supplied Garmin timezone or irrevocable finality. Current
and future Moscow days are excluded without shifting the requested 7/30-day
range or other sections. `requested_day_count`, `completed_day_count`,
`excluded_uncompleted_day_count` and `effective_completed_range` disclose that
distinction; completed-day count is a calendar count, not value/acquisition coverage.
The CLI's `--evaluation-local-date` does not override this Moscow completion clock.

Step values explicitly use `unit=count`.
The allowlist retains daily states/integers, latest acquisition and completion
timestamps, exact source/hash/run/event/observation links, proof/receipt identity,
and unknown coverage/device/timezone/finality. Newer null/missing/invalid evidence
does not reveal an older count; ties and legacy unproven partials keep v2 behavior.
The reader internally verifies bounded original bytes; no original body or path
is exported, and no projection, ingestion, replay, provider call or migration occurs.
Its unchanged source-wide 4096 candidate/provenance, 1000 original, 1 MiB/original,
16 MiB total-original and 5-second cooperative guards are disclosed in the section.
Any incomplete search rejects the entire packet as `steps_search_incomplete`.
There is no Steps aggregate or all-time mode in this slice.

`POST /api/analysis-export` accepts optional `steps_view` (default `observed`).
The updated form visibly defaults to completed Moscow days and can select saved
observations; old API requests remain observed/v4. It shows actual completed
dates, calendar counts and state counts without exposing daily values in the
disclosure summary. Detailed/compact preserve identical Steps facts. Existing
independent 2 MiB JSON/text limits, atomic download availability, no-store,
private classification, source selection and Context-once behavior remain.

<a id="evidence-combined--optional-saved-observed-steps-and-weight-451"></a>
### Optional saved observed Steps and Weight (#451)

Set `steps_garmin_source_id` (CLI `--steps-garmin-source-id`) to select one exact
Garmin source independently of Activity/Sleep. Set `include_weight=True` (CLI
`--include-weight`) to request the accepted Weight overlay and canonical evidence.
Neither option is enabled by default. These selections use explicit detailed /
compact v4; omitted options preserve the existing v1/v2/v3 versions and defaults.
Both sections remain identical in detailed and compact JSON/text/file/stdout,
with the existing 2 MiB caps, exact 7/30-day dates and one read-only transaction.
Context is still read once. The Weight/Context MCP and access setup are unchanged.


See [Owner Operations — Observed Steps and Weight v4](OWNER_OPERATIONS.md#export-observed-steps-weight-v4) for the complete operator invocation.


Steps delegates to `read_observed_steps_window` and exports saved materialized
account-level daily observations, **not completed daily totals**. Values retain
exact integers (including zero), date precision, eligibility states, candidate /
observation / normalization provenance and unknown coverage, device, timezone and
finality. Unprojected, ambiguous, retired, null, missing and invalid evidence does
not become zero. Sources are never summed, and no period total or mean is added.
The existing 4096-candidate and independent 4096-provenance bounds remain. If the
reader reports incomplete search, the complete combined export fails with
`steps_search_incomplete`; even an earlier proven prefix is not published.
This path neither opens artifact bytes nor reparses provider bodies. Completed
Steps, Google Steps, provider refresh and new projection/ingestion remain outside
this slice.

Weight reuses the accepted v1 exporter projection of `WeightQueryService` in the
same caller-owned snapshot. It retains confirmed source overlay measurements,
`canonical_selected`, source/provenance, accepted daily medians, canonical status,
coverage, trend/rate algorithm identities and unavailable reasons. Overlay points
are not all canonical-selected; sources are not summed. Daily medians exist only
on dates with eligible selected measurements. A derived trend is not evidence of
a measurement on an unmeasured date. Source freshness is provider-scoped and uses
the explicit evaluation clocks. The existing export cadence is 7 days, independent
of runtime settings; this is a coverage policy, not imputation or acquisition proof.
No configured goal, import queue or raw artifact is exported.

The inherited 2000 scalar-input bound and 100 rows per exported Weight series are
unchanged. Any series exceeding 100 rows fails the complete combined export with
`weight_selected_points_exceed_max`, instead of returning a winning prefix. Missing
or unconfirmed measurements stay absent; no zero, interpolated daily weight,
source fallback, daily causal join or health diagnosis is introduced. Owner-local
availability/UAT and acquisition completeness remain unverified.


<a id="evidence-combined--optional-saved-hrv-and-resting-heart-rate-451-v3"></a>
### Optional saved HRV and resting heart rate (#451, v3)

Set `hrv_garmin_source_id`, `hrv_google_source_id`, `rhr_garmin_source_id`
and/or `rhr_google_source_id` on `CombinedEvidenceRequest`, or the matching CLI
flags. Every exact ID is validated in the shared read-only snapshot before any
domain reader runs. Each metric has its own explicit sources; no Sleep/Activity
fallback or provider pooling occurs. `rhr_google_auto_select=True` (CLI
`--rhr-google-auto-select`) opts into the accepted metric-specific Google RHR
selection. An exact RHR override takes precedence, including an empty source.
HRV requires exact sources and does not infer a Google choice from Sleep or RHR.

With HRV/RHR selected, detailed/compact packets use
`health-chat-combined-evidence-v3` / `health-chat-combined-compact-evidence-v3`.
Existing omitted-metric v1 and Stress/Body Battery v2 remain unchanged. Sections
`hrv` and `rhr` contain only requested `providers`; compact retains these sections
identically to detailed. JSON, readable text, files and stdout share the frozen
packet and the unchanged 2 MiB caps, SQL/time guards and exact 7/30-day dates.
Context is read once. Steps and Weight are separately opt-in above. The existing
Weight/Context MCP, its schema/auth and connection setup are unchanged.


See [Owner Operations — HRV and resting heart rate v3](OWNER_OPERATIONS.md#export-vitals-v3) for the complete operator invocation.


Garmin HRV is the persisted `hrv_weekly_average_ms` snapshot, labelled as a
provider weekly/trailing aggregate on its saved source-local date. It reuses
Overview snapshot matching, eligibility and latest-within-date ordering; equal
date-only candidates stay ambiguous. Eligible partial and zero values remain
values; wrong units, missing/null/invalid, excluded and retired records never
supply one. Per-point evidence retains source field, record/metric/raw IDs,
precision, saved clock and normalization identity. The adapter reads current
typed rows only; no raw-body parsing or import is added. At most 4096 candidate
metric rows and 256 rows/date are inspected (the existing RHR work ceilings);
overflow fails the entire packet without a prefix. Undated records cannot be
assigned to the requested window. Counts are **snapshot-date counts**, not
daily HRV coverage. `dates_without_eligible_snapshot` does not describe the
physiological coverage of any weekly aggregate. No HRV mean is computed.

Google HRV uses `read_google_daily_vitals` (#297), retaining its exact daily
metric/stream/unit, date-only eligibility, current-record ambiguity, per-point
states and exclusions. This reader gains optional exact source and cap arguments;
omitting them preserves its existing behavior. Combined selects one exact source
and caps candidates at 4096 before projection, rejecting overflow without a
prefix. The scalar allowlist excludes arbitrary bodies and unrelated source
inventory. Missing dates mean no eligible saved daily value; they never become
zero or prove collection failure. Google daily HRV and Garmin weekly HRV remain
different series even if their values coincide; neither is averaged with the other.

RHR delegates to `read_saved_rhr_period` (#393), including its #376 eligibility,
source-specific dates/precision, chronology exclusions, partial/zero values,
record provenance, refresh facts, exact rational mean and final-only rounded
display. The denominator is distinct eligible saved days; missing days are never
zero. The existing 32-source inventory, 4096-record/source and 256-record/date
bounds remain unchanged. Google automatic selection evaluates RHR eligibility in
this exact window: other metrics cannot choose a source, two eligible sources
conflict even on disjoint dates or equal values, ambiguous-only sources compete,
and any incomplete candidate blocks selection. Conflict, unknown and incomplete
states retain the reader's disclosure and have no selected value/mean; unresolved
missing-day counts stay null. SQL/storage failures reject the complete packet.

All acquisition coverage stays unknown. Saved dates do not establish common
timezones, daily causal alignment, clinical significance or provider availability.
No new ingestion, refresh, migration, UI, Stable operation or private-data test is
included. Owner-local availability/UAT remains separate and unverified.

<a id="evidence-combined--optional-saved-stress-and-body-battery-451"></a>
### Optional saved Stress and Body Battery (#451)

Select `CombinedEvidenceRequest.stress_garmin_source_id` and/or
`body_battery_garmin_source_id` (CLI flags below) to add those exact Garmin
sources. Neither falls back to the Activity/Sleep source or automatic selection.
All IDs are validated before any domain reader runs. With both omitted, existing
detailed/compact v1 shapes and serializers are unchanged. With either selected,
the version is `health-chat-combined-evidence-v2` or
`health-chat-combined-compact-evidence-v2`; `request.sources` and `sections` add
only the requested metrics. Compact changes only Sleep: all selected Stress,
Body Battery and Context facts remain identical to detailed mode, with the same
2 MiB cap. Oversize results fail without a winning prefix.


See [Owner Operations — Stress and Body Battery v2](OWNER_OPERATIONS.md#export-stress-body-battery-v2) for the complete operator invocation.


Both new sections use the same existing read-only transaction and exact inclusive
request dates as Sleep/Activity. Context is still read once. Sources may coincide
or differ; the packet neither pools sources nor joins daily facts causally.
These are saved-source dates, not completed Moscow days inferred by the CLI.
This CLI addition does not extend the unchanged Weight/Context MCP or its schema,
authentication or connection availability. HRV, RHR, Steps and Weight are
separate opt-in sections described above.

`sections.stress` uses `analyze_garmin_metric_series` for
`stress_daily_average` with the accepted
`r03-01-stress-daily-mean-applicability-v1` selection and `r03-01-v2` rules.
It preserves provider daily averages in points, every selected point's state,
date/precision/clock, zero, partial, missing, null, ambiguity, exclusions and
allowlisted input manifests, normalization/provenance and applicability audit.
The existing 2000 candidate cap is unchanged: overflow rejects the entire request
with `stress_selected_points_exceed_max`, never a truncated series. Baseline/trend comparisons are
not exported or reinterpreted; `reader_result_hash` identifies the accepted full
reader result, while the combined hash binds the disclosed projection. No raw
payload, arbitrary diagnostic detail, source filename or artifact path is exposed.

`sections.body_battery` uses `read_body_battery_period` with the accepted
`r394-saved-body-battery-maxima-v1` eligibility: only proven current typed saved
samples, with legacy scalar/alias eligibility explicitly unknown. Each daily
value is the **maximum among saved eligible measurements**, not a guaranteed
full-day/provider-native maximum or morning value. Sample count, winning evidence
IDs/precision, exclusions, unknown acquisition coverage and search metadata are
retained. The accepted period mean weights eligible saved days equally;
`mean_exact` preserves its rational representation and `mean_value` is a lossless
decimal **string**, or null. The 100000 period/10000 per-day candidate caps stay
unchanged. Incomplete search emits no daily prefix or mean, and day counts and
missing dates remain null. A storage failure rejects the complete packet.

For both metrics, `missing_day_count`/`missing_dates` mean dates with no eligible
value, including excluded dates; they do not prove acquisition failure or absence
of a physiological observation. `excluded_day_count` counts dated exclusions
without an eligible value and is a subset of missing days, not an additional
disjoint count. Stress availability counts describe records separately. Explicit
zero remains zero; missing/unknown never becomes zero. Stored presence does not
establish full-day acquisition coverage (reported unknown). JSON and text print
the same selected facts, semantics, counts and warnings; stdout validates its
complete result before writing any byte. The historic `--st` stdout alias stays
accepted despite the new `--stress-...` option. Private Owner UAT remains separate
from synthetic tests and CI.

`healthcheck.combined_evidence.read_combined_evidence` returns a single bounded
`health-chat-combined-evidence-v1` packet by default. It composes the accepted
[Sleep](#evidence-sleep) and [Activity](#evidence-activity) evidence
services in one existing WAL-aware read-only SQLite transaction. Context is read
once, with the existing current-revision overlap/precision/disclosure rules.
This additional reader and standalone CLI leave the original exporter and MCP
tools, domains, schema and authentication unchanged. No connection is installed.

```python
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.combined_evidence import CombinedEvidenceRequest, read_combined_evidence

packet = read_combined_evidence(
    profile=Path(selected_existing_profile),
    profile_kind="synthetic",  # trusted caller assertion, never inferred
    request=CombinedEvidenceRequest(
        end_date=date(2099, 1, 8), days=7,
        activity_garmin_source_id=selected_activity_garmin_id,
        sleep_garmin_source_id=selected_sleep_garmin_id,
        sleep_google_source_id=selected_sleep_google_id,
        include_context=True, context_limit=50,
    ),
    evaluated_at_utc=datetime.now(UTC),
    evaluation_local_date=date(2099, 1, 8),
)
```

<a id="evidence-combined--request-and-output-contract"></a>
### Request and output contract

Exactly 7 or 30 inclusive local calendar dates ending at the explicit date;
underflow, `date.max`, bool days and oversized/invalid limits fail. Requested and
effective bounds are equal, without clipping or fallback. Activity requires one
explicit Garmin source. Sleep requires at least one provider: an explicit Garmin
source and/or a Google exact source ID or `sleep_google_auto_select=True`.
An exact Google Sleep ID takes precedence over automatic selection. The Garmin
choices can coincide or differ; they are separate explicit selections and never
pooled. All explicitly requested IDs are validated for existence and provider in
the shared snapshot before either domain reader runs. Explicit-source requests
expose no unrelated inventory and never fall back to another source. Google opt-in
uses the bounded [Sleep selection contract](#metric-source-selection); competing
series or incomplete discovery remain labelled outcomes without a selected source.
Existing empty exact sources remain valid empty stored evidence; an unavailable
explicitly selected ID fails the request.

The top level contains version/provenance, generated/evaluation clocks, explicit
profile assertion/privacy, exact request and selected sources, snapshot/limits,
sections, interpretation boundaries and `envelope_hash`. The sections are:

- `sleep`: existing package/provenance/reader/metric versions and limits, with
  the unchanged public source sections under `providers.garmin` and/or
  `providers.google`;
- `activity`: existing package/provenance/reader versions and limits, with the
  unchanged public source section under `providers.garmin`, plus a versioned
  `temporal_evidence` object;
- optional `context`: the existing allowlisted current revisions/page metadata,
  once, with `relationship=local_date_window_cooccurrence_only`.

The composition deliberately uses the services' private session-based
`_assemble` hooks. Calling their public readers would open separate snapshots.
Equivalence tests bind this dependency to their public results; changes to the
hooks require checking this consumer. Per-domain generated clocks/hashes and
duplicated request/profile fields are omitted from the combined projection.
The combined SHA-256 covers canonical compact UTF-8 JSON excluding only its own
`envelope_hash`; nested versions and full evidence remain hash-bound.

`encode_combined_evidence` emits compact complete JSON. `render_combined_evidence`
renders a shorter readable view of the same frozen packet: exact request/source/
clock/limit identities, Sleep presence/gaps and resolved series plus saved-session
metric states/units/role exclusions, all five Activity cells including coverage
conflicts, and current Context revisions/page metadata. Full Sleep temporal and
metric audit provenance remains in the matching JSON, identified by the printed
hash. No values are recomputed. Literal Context text remains JSON-escaped untrusted
data, never instructions. The complete JSON retains provenance, exclusions,
per-night evidence, missing dates and coverage conflicts. Neither serializer
writes files. No automatic upload occurs.

<a id="evidence-combined--activity-temporal-evidence"></a>
### Activity temporal evidence

`sections.activity.temporal_evidence` is a versioned
`health-chat-activity-temporal-evidence-v1` object present only in combined
packets (detailed and compact are identical); the standalone Activity reader
stays aggregate-only. It is read in the same read-only snapshot through the
existing bounded loader and inherited 4096 candidate cap, against the exact
selected Garmin source and the persisted source-local-date window (no date
recomputation). A projected current-session cap of 200 is enforced; more than
200 projected current sessions fail the slice. Overflow returns an explicit
`incomplete` result with `sessions` and counts null — no timing prefix — while
the five Activity cells remain unaffected. A cooperative budget expiry anywhere
in the bounded timing assembly, including after the candidate rows load, returns
that same explicit `incomplete` state; unrelated storage/SQL failures still fail
the complete request.

Each projected current session exposes its persisted `source_local_date`
independently of the start state, plus a `start` endpoint in one of five states:
`absent`, `date_only`, `local`, `instant` or `ambiguous`, with `eligible` and a
deterministic `reason`. A timestamp is only called an activity start when the
persisted source field is a proven start leaf (`startTimeGMT`/`startTimeLocal`/
`startTimeUTC`/`startTime`); generic `timestamp`/`time` clocks are ambiguous.
Calendar/date-only evidence is retained with its saved date but is never a
start endpoint by itself. A record that is partial only because of unrelated
missing/invalid metrics, and an aware value that populates both paired columns
with the same path, keep a proven start. Actual start-clock ambiguity is read
from a closed allowlist of persisted temporal diagnostic codes
(`paired_time_mismatch`/`invalid_datetime`/`invalid_calendar_date`); a malformed
or unsupported diagnostic shape fails closed for timing. Invalid and conflicting
(paired local/UTC start) records, and duplicate current identities, never yield
usable timing. Retired records supply no current timing and are reported as
excluded reason counts. The `end` endpoint is always explicitly
`not_persisted_in_activity_contract` with null timing; raw payloads, unknown
fields and duration are never used to invent an end. Missing precision/zone/
offset stays null — never zero or a host/Moscow zone — and the persisted
source-local date is retained even when the UTC instant crosses a boundary, the
start clock is absent, or the start is ambiguous. Record/source/raw-payload/
normalization identity and source field paths are closed scalar allowlists; raw
bodies, artifact paths, unknown fields and diagnostic bodies are never exported
(the persisted diagnostic codes are inspected internally only). Readable text
prints the frozen `temporal_evidence` object without recomputing it. No universal
sleep ordering, join or causality is added; Garmin sleep can remain date-only.

<a id="evidence-combined--semantics-and-limits"></a>
### Semantics and limits

Sleep still uses source-local **wake dates** and Activity still uses persisted
source-local activity dates. Equal request bounds do not prove shared timezone,
daily alignment, temporal ordering or an effect of one domain on another. No
daily join, new formula, score, source pooling or causal analysis is performed.
Only local-date window co-occurrence is described. A missing Context note does
not establish absence of exposure.

All existing recursive disclosure rules, units and temporal precision apply.
Sleep zero/missing/null/partial/ambiguous/excluded states and unknown acquisition
coverage remain intact. Activity count/type/tennis duration/cycling distance
cells retain their accepted values, eligibility/exclusions, incomplete search,
coverage conflicts and normalization evidence. No summary of these states hides
an unavailable or conflicting domain. A domain's bounded incomplete result does
not truncate the other domain; storage/SQL errors reject the complete response.

The shared transaction retains `mode=ro`, `query_only`, deny-write authorizer,
current-schema validation, 20-million SQL-step and 20-second progress guards.
Sleep's 400/provider and 200/night record caps, Activity's bounded loaders and
2-second cooperative summary budget, and Context's 1–100 rows (default 50,
cap+1 read with explicit `has_more/truncated` and unknown total) remain as
documented in the individual service contracts. Each domain's limits are
present in its section. Combined JSON and text each have a 2 MiB UTF-8 cap,
including text reminders. Oversize JSON fails before a packet is returned;
oversize JSON or text fails before the CLI creates its output directory;
there is no winning prefix or all-history mode.

These are cooperative read guards, not a hard whole-response deadline. Python
processing, SQLite lock waiting, real-profile latency and Owner UAT remain
unverified. Profile classification (`synthetic`, `disposable_owner_clone`,
`durable_owner_runtime`) is a trusted caller assertion, not authentication.
Owner profiles are private. Snapshot metadata stays unknown; current Stable
identity is not inferred. SQLite WAL/SHM read coordination can occur; application
writes, migrations and journal changes are denied.

<a id="saved-sleep-analyses"></a>
### Optional saved Context and sleep analyses (#462 / #464)

Combined export request/CLI opts `include_context_recovery` /
`--include-context-recovery` and `include_sleep_regularity` /
`--include-sleep-regularity` add envelope v6 (compact v6) and versioned analysis
sections. Defaults retain their existing versions/shape. Analyses consume only
the existing allowlisted Sleep and current Context projections from the same
read-only transaction, before compact projection. JSON, text and compact carry
identical analysis facts, exclusions and coverage; the existing 7/30-day, Sleep
400/provider and 200/night, Context 1–100 and output-byte limits do not grow.
Overflow remains fail-closed; Context truncation and date-window edges are
disclosed, never complete event history or negative exposure evidence.

Eligible input is one accepted source night per exact source/wake date, with
eligible ordered instant endpoints and explicit endpoint local zone/offset.
Use the existing source-night resolver, excluding ambiguous sessions/naps and
Google uncertain singleton roles. Garmin role may be null; retain its accepted
start `explicit_record_boundary` and end `complete_stage_boundary` methods,
without inventing a primary-sleep label. Missing endpoints/zones, conflicts and
within-night zone changes are excluded with reasons. No end is made from duration.
Retain source, record, role, temporal provenance and original metric references.
Partition by provider, exact source, variant, endpoint methods, normalization
contract and IANA zone or explicit fixed offset. DST within one IANA zone uses
its actual offsets; fixed-offset changes and travel use separate groups.

Context instant anchors retain minute/second/microsecond precision; interval
anchors use their explicit end. Date-only anchors are excluded without midnight
or `created_at` fallback. For each exact source pair the first eligible
sleep start in inclusive `[anchor, anchor + hours]`, default 24, explicitly bounded
by `context_pairing_hours` / `--context-pairing-hours` to 1–48. Keep event/revision
IDs and full temporal provenance; partition only the comparisons. Many events can reference one night, but every
night contributes once to pooled descriptive comparisons. Compare accepted sleep
duration, time in bed, WASO and saved sleep score only, by each cell's unit/method/
variant. Reference nights are the other compatible snapshot nights with exposure
unknown, never event-free controls. Report per-metric counts, missing/incompatible
values and means/difference only with at least three unique nights per group.
This first package pools timed Context events; it does not infer tags, cause,
diagnosis, HRV/Body Battery recovery or post-workout pairs. Activity end is not
persisted and is never synthesized.

Regularity explicitly means **circular local-clock population variability** for
start/end and elapsed-UTC midpoint converted into the evidenced source local zone.
For clock minutes `t`, `theta=2*pi*t/1440`, `R=abs(mean(exp(i*theta)))`, circular
SD is `sqrt(-2*ln(R))*1440/(2*pi)` minutes. Each partition requires at least three
unique nights; fewer gives `insufficient`/null, and `R<1e-12` gives undefined
direction/null. No linear clock average or clinical threshold is introduced.
Social jetlag is uncorrected circular free-minus-work shortest signed minutes
in `[-720,720)` plus its absolute value, requiring three nights in each group.
Only explicit optional wake-date `sleep_day_types` / repeatable
`--sleep-day-type YYYY-MM-DD=work|free|unknown` classify dates; duplicates,
out-of-window dates and invalid labels are rejected. Unlisted dates are unknown.
No classification is persisted or guessed from weekdays; its absence does not
block ordinary regularity. Shift-work/sleep-debt corrections are not performed.

<a id="evidence-combined--opt-in-compact-projection"></a>
### Opt-in compact projection

For a 30-day local query, add `--projection compact` to either destination mode:


See [Owner Operations — Compact projection with earlier defaults](OWNER_OPERATIONS.md#export-compact-v1) for the complete operator invocation.


Python callers set `CombinedEvidenceRequest(..., projection="compact")`. The
omitted/default `projection="detailed"` preserves the existing v1 packet shape,
hash contract, validation and serializers. Compact uses the distinct version
`health-chat-combined-compact-evidence-v1` and hash-bound `projection` metadata;
it is a summary projection, not a detailed interval replay packet. Both modes
use the same accepted readers in the same read-only snapshot, before the
unchanged 2 MiB UTF-8 serialization guard. Compact does not call the capped
public detailed serializer first. No byte cap is raised and no winning prefix
is emitted. An oversized compact packet still fails the complete request.

Only Sleep representation changes:

- Daily ranges, series/values, units, metric states/reasons/eligibility, explicit
  zero, missing/null/partial/ambiguous states, candidate/excluded record IDs,
  roles, source identity/selection and acquisition-coverage limits stay intact.
  All saved sessions remain; `summary_record_id` replaces the duplicate night
  `summary` object, referencing its saved session or null when ambiguous/absent.
- Every metric retains its scalar fields. Exactly equal evidence fields across
  that session's metrics move once to `evidence_common`. Reconstruct a metric's
  summary evidence by overlaying its own `evidence` over `evidence_common`.
  Replace `field_paths_index` with the exact path list at that index in the
  session's `field_path_sets`; repeated lists are stored once without dropping
  paths. Indices are local to each session and bound by the envelope hash.
  Record/observation/normalization identities, source eligibility, field paths,
  immutable metadata and content hashes remain bound to the packet.
- Per-metric `interval_ids` and `interval_snapshots` become `interval_summary`:
  exact counts, groups by interval kind/state and endpoint precision, and SHA-256
  of canonical UTF-8 JSON `{interval_ids, interval_snapshots}` using the existing
  canonical encoder. This summarizes stage/out-of-bed detail without new sleep
  formulas. Counts/digests describe all contributing intervals; they do not
  silently retain only a prefix. The digest identifies omitted detail but cannot
  reconstruct it or establish independent source correctness.
- `interval_summary.session_intervals` retains original `sleep_session` endpoint
  snapshots, including offsets, wall time, timezone, precision and state. Session
  `temporal_evidence` and accepted start/end metric cells also stay intact.
  Date-only/null timing gains no invented instant or host offset. Stage segment
  endpoints/IDs are intentionally available only in detailed mode.

Activity cells (including coverage/conflict/incomplete-search flags), current
Context revisions/text/temporal precision and explicit page bounds/has-more,
profile/privacy assertions, unknown verified-snapshot/Stable identity, requested
and effective dates, cooperative limits and interpretation boundaries are
unchanged. Compact text includes the projection identity and the same selected
facts/comments as JSON; full summary provenance stays in its matching JSON.
No daily causal join or source pooling is added. Original comments remain
untrusted data, never tool instructions.

The persisted synthetic size regression includes 30 Garmin nights, 30 Google
nights with 60 seven-minute stage intervals each (within the existing parser
cap), daily Activity and 50 Unicode comments plus additional rows proving the
Context page bound. Detailed JSON exceeds 2 MiB while compact JSON stays below
1.5 MiB, with every daily point and selected comment preserved. This proves that
representative workload, not a universal size/latency guarantee or Owner UAT.

<a id="mcp-boundary"></a>

<a id="mcp-boundary--mcp-read-capability-and-exposure-boundary"></a>
## MCP read capability and exposure boundary


This separate loopback server exposes **one** read-only tool,
`get_period_evidence(start, end, domains)`, over the accepted
[health-chat-evidence-v1 reader](#evidence-period). It has no portal,
UI resources, plugin manifest, provider calls, runtime preparation, migrations,
profile discovery or write tools. The existing standalone exporter is unchanged.
Implementation readiness and a successful connected ChatGPT read are separate.

<a id="mcp-boundary--local-configuration-and-contract"></a>
### Local configuration and contract

Run `python -m healthcheck.chat_evidence_mcp` with an explicit `--profile`,
`--profile-kind` and IANA `--timezone`. The profile must already exist with this
candidate's schema. Missing/unmigrated profiles produce bounded tool errors;
the server never prepares or repairs them. Profiles inside Git checkouts or
linked worktrees are rejected. Development uses external synthetic data only;
Owner/private profiles require a separately authorized Owner-only runner.

The profile path, classification, evaluation timezone, row limit (default 50,
maximum 100) and weight cadence (default 7 days) are trusted startup settings,
never tool arguments. Classification is still an operator assertion, not verified
snapshot or current Stable identity. The initial domains are `weight` and
`context`, selected explicitly on each call. They use accepted source provenance
and current Context revisions. Garmin, Google, arbitrary source/path/SQL,
additional fields and duplicate domains are rejected. Inclusive `YYYY-MM-DD`
periods must span 1–90 days. The evaluation clock uses the configured timezone.

The result contains the same envelope as both JSON text and `structuredContent`.
The envelope's canonical hash is unchanged. The **entire serialized HTTP result**,
including both representations and escaping, is capped at 2 MiB; an over-budget
read returns `output_exceeds_byte_limit`, never a partial malformed envelope.
Choose a narrower period or a smaller local row limit. Each page retains its
`has_more`, `truncated`, usable counts and unknown/zero/missing distinctions.
Stale source evidence remains explicitly stale; a successful HTTP read does not
claim fresh collection or complete historical coverage. Original Context notes
are untrusted data, never instructions. No medical/causal interpretation is added.

`/mcp` implements stateless Streamable HTTP, JSON responses, initialize, ping,
notifications and tools/list/call (2025-06-18 only). The initial initialize POST
can omit the version header; subsequent POSTs require
`MCP-Protocol-Version: 2025-06-18`. March headers/unversioned subsequent POSTs and
JSON-RPC batches are rejected; older clients must support June to continue.
GET and DELETE return
405; no SSE stream/session store is needed for this read-only prototype. POST
bodies are capped at 8 KiB. Only one evidence read runs at a time; overlapping
reads receive 429 `evidence_busy`. The underlying reader retains its SQLite
transaction, deny-write authorizer and SQL/time budgets. The manual foreground
launcher binds only `127.0.0.1`, caps concurrent connections, disables access logs
and forwarded-header trust. No request, argument, result or Context content is
logged by the facade; responses are `Cache-Control: no-store`.

Host must be localhost/127.0.0.1. Origin is checked on every method; absent Origin
is allowed for server clients, and present Origin requires an exact startup
`--origin` allowlist entry. Do not add wildcard origins or proxy to the portal.

**Owner data must not use the anonymous synthetic route.** Both Owner profile
classifications fail startup unless `HEALTHCHECK_MCP_GATEWAY_TOKEN` is supplied
from an existing Owner-controlled secret outside Git. This is an internal
proxy-to-loopback bearer credential (at least 32 non-whitespace ASCII characters),
not an API key for ChatGPT. No credential/key generator is included. The server
checks it before protocol handling or any database read, for discovery as well as
calls. Do not place this secret in tool arguments, URLs, command lines or logs.

For Owner-data HTTPS, an **existing MCP-compatible OAuth gateway** must:

1. Terminate HTTPS and expose OAuth protected-resource and authorization-server
   metadata with the exact public MCP resource identifier; support ChatGPT's
   authorization-code/PKCE client flow and registration/discovery requirements.
2. Authenticate the Owner and allow only that Owner. Validate token signature,
   issuer, resource/audience, expiry and `health.evidence:read` scope on **every**
   request, including initialization/discovery; respond with standard OAuth
   challenges at the public boundary. Client mTLS alone does not authorize the user.
3. Strip the external Authorization header after validation and replace it with
   the separately supplied internal gateway bearer credential. Set upstream Host
   to loopback. Reject unvalidated requests; never give callers that credential.
4. Forward only the MCP endpoint and necessary gateway-owned OAuth metadata,
   disable content/credential logging and caches, and offer user/token revocation.

The facade advertises OAuth scope in tool metadata for Owner profiles; the gateway
implements public OAuth discovery/challenges. The facade does **not** implement an
OAuth issuer or validate ChatGPT tokens. ChatGPT cannot send arbitrary custom API
keys, so entering the internal secret into ChatGPT is not a supported shortcut.
If no suitable existing gateway is available, Owner-data HTTPS is **BLOCKED on
access setup**; keep the manual export fallback or separately evaluate Secure MCP
Tunnel. Do not expose a private profile by relabelling it synthetic. Gateway
construction, identity-provider calls/configuration, keys and public exposure are
outside this implementation assignment.


<a id="reports-and-delivery"></a>

<a id="reports-and-delivery--reports-and-delivery-contracts"></a>
## Reports and delivery contracts

<a id="reports-and-delivery--12-reports-and-delivery"></a>
### 12. Reports and delivery

```text
deterministic report builder
  -> persisted evidence packet + report revision
  -> renderer interface
       -> dashboard/archive
       -> Telegram
       -> email
  -> independent delivery attempts/retries
```

Weekly, monthly, and annual reports use the same analytics contract. A report is computed once and rendered many ways. Delivery failure does not recompute the report; late-data reprocessing creates a new explicit revision. Every report carries coverage, source/algorithm/rule versions, and non-medical caveats.

<a id="reports-and-delivery--13-recovery-score"></a>
### 13. Recovery Score

No Health-Check Recovery Score is currently justified. Preserve Garmin/Fitbit signals with provenance and accumulate cross-source evidence first. A future score is allowed only after a documented user problem, sufficient personal baseline, and validation plan; it must be transparent, component-attributed, versioned, and non-medical.


<a id="security-boundary"></a>

<a id="security-boundary--data-listener-and-readwrite-capability-boundary"></a>
## Data, listener and read/write capability boundary

<a id="security-boundary--14-security-and-license-boundaries"></a>
### 14. Security and license boundaries

- Real data, payloads, documents, databases, and secrets never enter Git or synthetic fixtures. Assigned Owner read-only analysis and presentation in the authorized AI conversation follow [Owner data workflow](OWNER_OPERATIONS.md#owner-data-boundary); this does not authorize data/runtime mutations.
- The durable Owner Stable profile is never a development-agent workspace. Owner UAT uses a separate disposable restore/clone.
- Dashboard/read/import is loopback-only; the separate LAN ingest app has no product routes, uses a stable sender UUID plus independent high-entropy rotatable credential, and has an encrypted-overlay/HTTPS or explicitly warned trusted-private-LAN transport boundary.
- Log identifiers/counts/status, not authorization material or raw health values by default.
- Use typed access capabilities: read, ingest, context/import write, and admin are distinct.
- openScale/openScale-sync remain external GPL programs; do not claim this eliminates every legal obligation for every distribution arrangement.
- AGPL VitaSync and unlicensed `garmin_ai` are reference-only.
- Health-Check is licensed under MIT. Donor code is reused only selectively with the attribution, copyright notices, and other obligations required by its source license and exact reused commit.

<a id="security-boundary--11-ai-and-mcp-boundary"></a>
### 11. AI and MCP boundary

The default AI path is:

```text
LLM -> typed bounded read tool -> application analytics service
    -> compact versioned evidence packet
```

Tools expose period summary, coverage, provenance, weight progress, period comparison, activity comparison, source agreement, and context-event analysis. They use bounded date ranges and return counts/coverage/algorithm/rule versions. The MCP credential authorizes only read DTO endpoints; ingest, context write, import confirmation, settings, and admin routes use separate capabilities.

The LLM does not receive provider credentials, database paths, unrestricted raw tables, or years of samples to calculate mathematics. It explains observations, alternatives, uncertainty, and practical suggestions without diagnosis.

Generic SQL is not part of the normal interface. A later expert-only mode would require a separate SQLite `mode=ro` connection, `query_only`, an authorizer/progress deadline, one AST-validated `SELECT`, allowlisted analytic views/columns, required date/row/byte limits, and audit. Raw/config/secret/identity/schema tables remain invisible.


<a id="technical-decisions"></a>

<a id="technical-decisions--accepted-technical-decisions-and-source-lineage"></a>
## Accepted technical decisions and source lineage


The common evidence/provenance, source-comparison and time invariants above are the
canonical home of the equivalent accepted decisions. The original decision record
is retained by [exact baseline permalink](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/DECISIONS_AND_OPEN_QUESTIONS.md).
Product priorities are in Product, CI/risk/process in Development, operator
authority in Owner Operations and unresolved decisions in Wiki. A source report,
method name, donor README or plausible model answer cannot change an invariant.
Changes cite primary evidence, affected release/migration and the owning contract
or accepted decision; a layout decision grants neither health semantics nor
runtime access. The old R00/R01 plans do not automatically become current tasks.


<a id="source-comparison-decisions"></a>

<a id="source-comparison-decisions--source-comparison-and-canonical-switching"></a>
## Source comparison and canonical switching

<a id="source-comparison-decisions--owner-source-comparison-is-not-canonical-source-switching"></a>
#### Owner source comparison is not canonical-source switching

The A+ design, accepted source-specific reader and 7/30 Sleep/Statistics
implementation remain intact. Ordinary product language presents two providers
(Garmin and Google) while retaining exact saved source identities and eligibility
for the chosen metric/window. A Fitbit source and a Google family-aggregate
may overlap; they must not be treated as independently additive without proof.

Independent per-source values may be shown side by side without Agreement pairs.
A numerical delta requires compatible metric meaning, actual observation/period
windows, eligible denominators and units. Missing sources stay visible and
dated, not copied from another source or silently zeroed. The existing canonical
Garmin/R05 decision remains unchanged until the separate evidence gate is met.

Longitudinal "latest eligible" display is a *presentation of saved evidence*,
not a new canonical/current-day value or blanket completeness certification.
Stored time and BIA source provenance must be preserved under the accepted
precise time/date-only, correction and method rules.


<a id="runtime-provenance-decisions"></a>

<a id="runtime-provenance-decisions--runtime-and-provenance-decisions"></a>
## Runtime and provenance decisions

<a id="runtime-provenance-decisions--runtime"></a>
#### Runtime

- Python 3.12+, FastAPI, SQLite WAL, SQLAlchemy/Alembic, Windows-first local operation.
- One local codebase/database; loopback dashboard/read/import listener plus optional separate ingest-only process.
- Long sync/report jobs are explicit idempotent CLI/application-service operations suitable for Task Scheduler.
- Runtime data/artifacts/secrets live outside Git under an Owner-scoped data directory.
- No Redis/Celery/Kafka/Postgres/Kubernetes/multi-tenancy without demonstrated need.
- A disposable copy of real data is not synthetic and not automatically current Stable. Updating application code does not refresh the copy or recover providers. Startup may prepare/migrate its selected runtime; do not use it as a read-only probe.

<a id="runtime-provenance-decisions--data-and-provenance"></a>
#### Data and provenance

- Raw evidence, typed source data, current/canonical selection, derived analytics and LLM narrative are separate layers.
- Preserve competing source values and historical revisions; canonical rules/algorithms are versioned and reproducible.
- Physical device, provider/input method and measurement algorithm are separate identities. Provider/query family is not physical-device proof.
- Missing/null/zero/unavailable/unknown never collapse silently. Exact coverage/eligibility matter even when both sources are visually adjacent.
- Original comments/documents are evidence, not instructions to model tools or permission for autonomous writes.


<a id="garmin-decisions"></a>

<a id="garmin-decisions--garmin-source-and-analytical-decisions"></a>
## Garmin source and analytical decisions

<a id="garmin-decisions--garmin--r02r03"></a>
#### Garmin / R02–R03

- Use pinned `python-garminconnect`, not a second HTTP client. Protected Owner auth/session state stays external.
- Only reviewed read/download semantics are permitted; method existence is not device capability proof.
- Preserve raw/observation/current provenance, coverage, incremental/historical checkpoints and authoritative/partial reconciliation. Parser changes are version-aware.
- R03 metrics/time definitions and immutable manifests own analytics; UI does not reimplement statistics.
- Native scores remain native. Accepted Training includes Status, daily/chronic load, ACWR, Load Focus, Readiness/Recovery and activity Effect/load. Acquisition date is not necessarily provider source date.
- Associated device/activity recorder is not metric-producer proof. Recovery Time units and VO2/max metrics stay unavailable without accepted evidence.
- Normal Owner refresh includes bounded Training sync with the same auth/client.
- Only evidenced `tennis_v2` renders as Теннис; codes/formulas stay unchanged. #319 max-HR/anaerobic B1 is complete; calories still require authoritative meaning/coverage evidence, not requested cards.
- Maintenance #98 updated python-garminconnect 0.3.12 → 0.3.15; #99 hardened Google auth/sync tests. Both are complete, not new semantic dependencies.


<a id="time-freshness-decisions"></a>

<a id="time-freshness-decisions--time-freshness-and-coverage-decisions"></a>
## Time, freshness and coverage decisions

<a id="time-freshness-decisions--source-freshness--data-quality"></a>
#### Source freshness / data quality

- #147/#191/#193 are complete provider-call-free shared projections; vocabulary fresh | quiet | stale | unavailable | unknown | not_requested.
- Attempt/success, evidence time, coverage/checkpoints and configuration/request state remain distinct.
- Daily due/grace is versioned; activities use proven inventory; voluntary Weight is non-alert by default. Unknown chronology does not become healthy; optional metrics do not fail a healthy provider.
- Successful freshness reads do not prove provider recovery, complete account history or full Data acceptance. Metric date, evidence age and clone age remain distinct facts; current delivery and outstanding acceptance belong in the [dated project status](PROJECT_WIKI.md#current-backlog).
- Per-source indexed Google freshness reads preserve source facts. The earlier clone observation of 12–18 seconds on `/brief` is historical, not a current latency measurement; subsequent optimization is recorded in [#421](https://github.com/LTstripes/Health-Check/pull/421). Any performance conclusion requires a new measurement bound to its code/profile/window; no arbitrary cache or deadline increase follows from an old observation.
- The stored RHR exclusion was fixed and independently checked ([#340 acceptance](https://github.com/LTstripes/Health-Check/issues/340#issuecomment-6089244192)); its remaining Owner acceptance is distinct from implementation. The bounded offline sleep diagnosis was accepted ([#342 receipt](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6087155625)). Earlier missing HRV observations are window-specific; the later [calendar recovery amendment](#hrv-calendar-recovery) does not prove recovery of all history. Google daily HRV never substitutes Garmin weekly HRV.

<a id="time-freshness-decisions--time-coverage-and-agreement"></a>
#### Time, coverage and agreement

- Store valid UTC plus original local time/offset/zone when present; preserve date-only/local-only precision.
- Sleep is aligned by local wake date; lag direction is explicit.
- Nontrivial results carry coverage; missing days are not zero.
- Associations are exploratory, never causal/medical claims.
- Independent side-by-side values may have different coverage. A numerical comparison additionally requires compatible definitions, windows and denominators.


<a id="ai-context-decisions"></a>

<a id="ai-context-decisions--typed-analytical-access-and-context-decisions"></a>
## Typed analytical access and Context decisions

<a id="ai-context-decisions--ai--reports--context"></a>
#### AI / reports / context

- Typed bounded read-only analytical access, not unrestricted SQL or inherited sync/import/restore powers.
- Deterministic/versioned reports precede narrative and delivery.
- Context v0 stores revisioned original text, explicit time and optional confirmed tags; #215 proved first private Stable adoption. No mandatory diary, inferred date/tag or assumed negative exposure.
- #294 portal/navigation/city-IANA input and #341 selected evidence export are integrated. Preserve one Context system and packet/revision/source identity; original content is untrusted data. Durable Owner UAT and direct chat transport remain separate.
- Direct authenticated ChatGPT connection is planned and must be verified end-to-end with account/host capability and consent; no current direct localhost access claimed. Telegram is optional.
- R09 first document intake is #348; extraction candidates are not confirmed lab values. Preserve original document/report-specific units/ranges/qualifiers and event dates before interpretation.


<a id="google-decisions"></a>

## Google acquisition and collection decisions

##### Google Health / R04

R04 is released; accepted contract remains:

- Google Health API v4 only, no new legacy Fitbit Web API implementation.
- Web Application/Web Server OAuth with fixed exactly registered loopback callback.
- Client secret/token/session stays external with Windows user-scoped DPAPI; non-Windows #247 writes purpose-bound AEAD v2, reads authenticated v1 and migrates on normal writes only. Reads do not create missing keys.
- The default read scopes remain sleep and health metrics/measurements. Explicit `google-auth --include-steps` may additionally request only activity_and_fitness.readonly under the [bounded Steps contract](GOOGLE_STEPS_ACQUISITION.md). Historical two-scope Owner consent/session reuse does not prove the optional grant or perpetual token durability.
- `list`, `reconcile`, `rollUp`, `dailyRollUp` and `dataSourceFamily` are acquisition context, not stable device identity. Raw/list evidence is separate from aggregates/reconciled output.
- Accepted types include sleep, HR/HRV/daily HRV, daily resting HR, SpO2/daily SpO2, sleep-summary and daily respiration. A Google proprietary sleep score is not automatically available or equivalent to sleep efficiency; #342 verifies actual support.
- Pagination follows nextPageToken; bounded sleep pages and inclusive-lower/exclusive-upper windows. No assumed undocumented ordering.
- Historical/incremental/refresh namespaces are distinct; completed windows can skip calls only when coverage proves completion. Explicit bounded refresh may fetch corrections.
- Missing/null/zero/confirmed-empty are distinct; unknown shapes fail closed.

###### Owner collection selection — 2026-09-29

High-frequency Google heart_rate remains OFF in the Owner Ops runner; Garmin is the
primary high-frequency HR source. This does not delete history, change bare CLI
defaults or disable Google HRV/daily resting HR/fixed wearables-sleep reconciliation.
The gap is intentionally uncollected, not provider-empty or complete. Re-enable
and historical catch-up require separate bounded decisions; no automatic backfill.


<a id="period-brief-decisions"></a>

## Period Brief compatibility and display scope

##### Period Brief / post-R05

- #119 is the deterministic bounded cross-domain packet; Weight/sleep/activity/data-quality facts retain coverage and stable identity.
- UI/text/CLI are renderers; display changes cannot rewrite formula/count/hash. Direct R05 report reuse avoids copied agreement semantics.
- #146/#133/#129/#127 correctness/UAT, #172 UX, #189 and later A+ page work are integrated. New #341 is a separate versioned evidence envelope, not a silent rewrite of #119.
- #203 changes limited-encoding stdout only; #248 explicit JSON/text preserves default packets.
- #307 retains full custom Period Brief/Garmin range; only Google daily-vitals display is bounded to the trailing 400 inclusive days with exact visible scope.
