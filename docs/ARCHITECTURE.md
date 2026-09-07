# Final Target Architecture

This is the canonical implementation architecture after R00. Source verification and disputed findings are recorded in [the R00 audit](audits/R00_FINAL_ARCHITECTURE.md); the first vertical slice is specified in [R01](R01_IMPLEMENTATION_SPEC.md).

## 1. System shape

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

## 2. Runtime responsibilities

### Windows laptop

- Python 3.12+, FastAPI/Uvicorn, SQLAlchemy/Alembic, SQLite WAL.
- Runtime state under `%LOCALAPPDATA%\Health-Check` (configurable), never inside the checkout.
- Dashboard/read/import listener bound only to loopback.
- Optional separate private-LAN ingest-only listener/port exposing only webhook plus non-sensitive liveness; stable sender UUID and rotatable credential are independent.
- Prefer HTTPS or a trusted encrypted private overlay. Plain trusted-LAN HTTP requires explicit opt-in and a confidentiality warning; public exposure is unsupported.
- Provider tokens/secrets outside Git, ultimately in Windows Credential Manager/DPAPI or an equivalently user-scoped secret store.
- Source artifacts such as images, raw JSON, and FIT files in a content-addressed local artifact directory with database references.

### Android phone

- openScale performs S400 BLE collection.
- openScale-sync forwards data through its generic webhook.
- Both are external GPL applications; Health-Check communicates through their published data boundary and does not incorporate their code.
- Health Connect is a future/secondary bridge, not the preferred S400 path, because it cannot represent the complete openScale record.

No custom Health-Check Android application is required for R01–R05.

## 3. End-to-end data pipeline

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

## 4. Provider flows

### Xiaomi S400

Live path:

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

### Garmin

R02 uses the community `python-garminconnect` package as a pinned runtime dependency rather than building another private HTTP client. Initial sign-in/MFA is user-assisted; reusable auth state is stored outside Git. Each stream has explicit backfill and trailing-window reconciliation because unofficial endpoints and late provider updates do not provide a universal durable cursor.

Garmin payloads map into typed scalar, sleep, activity, and series entities. A library method only proves that a client endpoint exists; it does not prove that Vivoactive 5 produces the metric. Live account fixtures decide availability, and unknown/unsupported values remain unavailable. Current series identity prefers a stable provider timestamp/token over array position; an authoritative complete collection may retire absent members, and parser upgrades reprocess stored raw evidence only when explicitly requested. The incremental watermark is not contiguous history.

### Google Fitbit / Google Health

R04 targets Google Health API v4 (`health.googleapis.com`), not a legacy Google Fit pipeline. It requests only the currently implemented read scopes and treats partial consent as a stream-level capability state.

Google Health source identity is explicit. The adapter preserves raw `list` records with their `dataSource` platform/device/recording-method metadata and stores reconciled/rollup results separately with the exact query/family. `google-wearables`, `google-sources`, and `all-sources` are different source families: an aggregate from `google-sources` or `all-sources` may include Health Connect, manual, or third-party data and must never be labelled as Fitbit-device evidence. Even a `google-wearables` aggregate is family-level unless returned metadata identifies the physical device. Garmin/Fitbit agreement uses only records attributable to the intended Fitbit device/source; otherwise label the evidence `google_wearables_family` and exclude it from a device-specific decision.

OAuth for one personal account:

1. External Google Cloud project in **In production** status under the documented personal-use/unverified exception. Track the separate 100-user unverified-app audience cap; it is not the exception definition.
2. Desktop OAuth client; system browser; random loopback callback on `127.0.0.1`.
3. Authorization code flow with PKCE S256 and a unique one-use state that is persisted and validated.
4. Offline access; securely retained refresh token; refresh on demand for scheduled jobs.
5. `prompt=consent` only for initial refresh-token acquisition or deliberate reauthorization.
6. When scopes change, reauthorize with the complete required set; do not assume installed-app incremental authorization.
7. Surface token health and require manual reconnect on revocation/`invalid_grant`.

Testing status is unsuitable for automation because its offline refresh token is limited to seven days. A service account cannot replace the owner's consent. Verification/policy and live API access remain a release gate, not an excuse to switch to an unsafe token workflow.

Google Health sleep and physiological records are source data. A local `healthcheck_*` or adapted `fettle_*` score is a derived, versioned metric; it must not be named or displayed as an official Fitbit Sleep Score or Readiness value. The documented public interfaces reviewed by R00 did not expose those proprietary scores.

### Life context

The canonical object is an event/exposure interval:

- original text;
- start/end plus precision/timezone metadata;
- capture source;
- optional tags with `suggested`, `confirmed`, or `rejected` status;
- parser/model version where structured suggestions were used.

Dashboard/Telegram saves clear text immediately. It asks for clarification only when the date/range or intended event is materially ambiguous. Analytics may use confirmed tags and may use suggested tags only when the lower evidence quality is explicit.

## 5. Canonical logical data model

### Shared evidence/provenance

- `providers`
- `physical_devices`
- `acquisition_sources` (provider + input method + application/configuration)
- `measurement_algorithms` (producer, version, parameters, compatibility group)
- `raw_artifacts` (content hash, type, local reference)
- `ingest_batches` / `ingest_events`
- `sync_runs` / `sync_stream_state`

### Typed source data

- `measurement_sessions` and `scalar_measurements` for sparse scalar/vendor values;
- `sleep_sessions` and `sleep_stage_intervals`;
- `activities` plus FIT/raw-detail references;
- `series_streams` and bounded time-series chunks/points for intraday data;
- `context_events` and versioned tag interpretations;
- later, typed lab documents/results.

This is not one EAV table. A scalar metric registry is appropriate for scalar values; intervals, sessions, stages, activities, and high-frequency streams retain their own semantics and constraints.

### Interpretation and output

- `derived_measurements` with algorithm/version and input references;
- `canonical_rule_sets`, `canonical_selection_runs`, and `canonical_selections`;
- `coverage_intervals`/calculated coverage summaries;
- `report_runs`, evidence-packet snapshots, rendered artifacts, and `delivery_attempts`;
- later, `experiments` and exposure/evaluation records.

Canonical selections point to immutable source or derived entities. They do not overwrite values. Corrections are append-only superseding revisions. A rule run records its exact input set/rule hash so historical output can be reproduced.

## 6. Idempotency and synchronization

Each provider/stream defines:

- stable external ID when available;
- semantic fingerprint fallback;
- initial backfill interval;
- incremental watermark/cursor;
- explicit trailing reconciliation window, without treating that watermark as contiguous history;
- stable collection identity and authoritative retirement, with version-aware reprocessing of stored raw evidence;
- retry/backoff and failure classification;
- source coverage calculation.

The raw transport event is persisted before or atomically with normalization. Duplicate retries link to the existing semantic record and succeed without duplicating measurements. Receive order never defines event order. A parser failure keeps replayable raw evidence and a sanitized status.

Photo artifacts deduplicate by content hash; semantic measurement deduplication uses source/device/timestamp/metric/algorithm identity so separately transported copies of the same source event converge without conflating genuine equal-valued weigh-ins. For openScale-sync, a stable configured sender-instance UUID is independent of its rotatable bearer secret, so credential rotation cannot fork source identity.

## 7. Coverage contract

Coverage is returned with every non-trivial analytic/report result:

- requested and actually covered interval;
- observed versus expected days/nights/sessions when an expectation is meaningful;
- freshness and longest gaps;
- per-source/per-algorithm breakdown;
- failed, unavailable, confirmed-empty, and unknown intervals;
- rule version and exclusions.

Sparse voluntary streams such as weekly weight use a configured cadence. Continuous streams use expected time/day coverage. Missing and zero are never interchangeable. Analytics has explicit minimum-count/span gates; an overall `HIGH/MEDIUM/LOW` label, if rendered, is secondary to these facts.

## 8. Time and lag semantics

- Persist a UTC instant when one exists, the source local timestamp, numeric offset, and zone identifier when available.
- Preserve date-only precision rather than inventing a midnight instant.
- A sleep session is keyed analytically to the local **wake date**.
- `lag 0` means the same analytic date; `lag +1` means the next analytic date.
- An exposure on evening X can align with the sleep session waking X+1 and morning HRV on X+1.
- Travel/timezone policy remains a later feature, but retained offsets allow reprocessing.

Lag direction is named in APIs and evidence packets; ambiguous `correlation(metric_a, metric_b, lag=1)` contracts are forbidden.

## 9. Deterministic analytics

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

## 10. Cross-device agreement

Pair comparable metrics separately; do not compare proprietary vendor scores as if they were the same construct.

- Preliminary exploratory report: at least 14 paired nights across at least two weeks.
- Provisional canonical-source decision: at least 42 paired nights across at least six weeks, adequate coverage, and no known firmware/method break.

These are engineering gates, not statistical guarantees. For sleep duration, stages, RHR, and HRV, report paired difference/systematic bias, MAE, RMSE, and Bland–Altman limits (or robust quantiles when assumptions fail). Correlation is secondary; Lin's CCC may supplement the stronger gate. A rule change remains reversible/versioned.

## 11. AI and MCP boundary

The default AI path is:

```text
LLM -> typed bounded read tool -> application analytics service
    -> compact versioned evidence packet
```

Tools expose period summary, coverage, provenance, weight progress, period comparison, activity comparison, source agreement, and context-event analysis. They use bounded date ranges and return counts/coverage/algorithm/rule versions. The MCP credential authorizes only read DTO endpoints; ingest, context write, import confirmation, settings, and admin routes use separate capabilities.

The LLM does not receive provider credentials, database paths, unrestricted raw tables, or years of samples to calculate mathematics. It explains observations, alternatives, uncertainty, and practical suggestions without diagnosis.

Generic SQL is not part of the normal interface. A later expert-only mode would require a separate SQLite `mode=ro` connection, `query_only`, an authorizer/progress deadline, one AST-validated `SELECT`, allowlisted analytic views/columns, required date/row/byte limits, and audit. Raw/config/secret/identity/schema tables remain invisible.

## 12. Reports and delivery

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

## 13. Recovery Score

No Health-Check Recovery Score is currently justified. Preserve Garmin/Fitbit signals with provenance and accumulate cross-source evidence first. A future score is allowed only after a documented user problem, sufficient personal baseline, and validation plan; it must be transparent, component-attributed, versioned, and non-medical.

## 14. Security and license boundaries

- Real data, payloads, documents, databases, and secrets never enter Git or synthetic fixtures.
- Dashboard/read/import is loopback-only; the separate LAN ingest app has no product routes, uses a stable sender UUID plus independent high-entropy rotatable credential, and has an encrypted-overlay/HTTPS or explicitly warned trusted-private-LAN transport boundary.
- Log identifiers/counts/status, not authorization material or raw health values by default.
- Use typed access capabilities: read, ingest, context/import write, and admin are distinct.
- openScale/openScale-sync remain external GPL programs; do not claim this eliminates every legal obligation for every distribution arrangement.
- AGPL VitaSync and unlicensed `garmin_ai` are reference-only.
- Health-Check is licensed under MIT. Donor code is reused only selectively with the attribution, copyright notices, and other obligations required by its source license and exact reused commit.

## 15. Architecture invariants

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
