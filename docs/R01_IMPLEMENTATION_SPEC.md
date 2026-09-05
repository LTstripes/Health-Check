# R01 Implementation Spec — Weight & Body Composition Vertical Slice

## 1. Decision and outcome

R01 builds the small provider-neutral Health-Check core and uses it for the user's highest-priority problem: Xiaomi S400 weight and body composition.

The released slice lets the user start one local Windows application, import a batch of historical Xiaomi screenshots into a review queue, explicitly confirm/edit measurements, receive an authenticated openScale-sync webhook payload, and view weight/body-composition trends with provenance, coverage, and algorithm-discontinuity warnings.

R01 is not a schema-only foundation release. It must be a useful working product.

### Current release status

R01 is released on `main`. The final owner gate passed on the integrated
candidate `058639919c4b5e13c420e7c016d292843afa10dc`; the current `main` at
the post-R01 documentation baseline is
`24c4e1f949cd04746ca40bde539a9f32b1b4b4b0`, with its CI check successful.
The owner-assisted historical Xiaomi import, packaged Windows `tzdata`
support, and production vision-extractor composition are part of the
released behavior. Live S400/openScale BLE and a real external vision
provider call remain **UNVERIFIED**.

## 2. In scope

### Core

- Python project, typed configuration, Windows launcher, structured logging.
- Loopback UI/read/import FastAPI/Uvicorn application bound only to `127.0.0.1`.
- Optional separate, route-isolated ingest-only FastAPI/Uvicorn application on a configurable private-LAN address/port; it exposes no UI, read, import, settings, or admin routes.
- SQLite database in WAL mode with foreign keys and versioned migrations.
- Provider, physical-device, acquisition/input, raw-artifact, measurement-algorithm, source-measurement, canonical-selection, sync, and coverage concepts.
- Runtime data directory outside the repository.

### Xiaomi historical path

- Multi-file screenshot/photo upload.
- Original image preservation outside Git with content hash.
- Pluggable vision-extraction contract.
- Per-field structured candidates, edit/reject/confirm workflow, and batch history.
- Explicit Xiaomi-app algorithm provenance even when its exact version is unknown.
- Idempotent re-upload and intentional reprocessing under a new extractor version.

### Xiaomi live path

- An authenticated FastAPI receiver compatible with the pinned openScale-sync generic-webhook contract documented by R00.
- Durable raw request evidence, validation, normalization, idempotency, and useful error status.
- A replayable synthetic contract fixture; live BLE pairing is a separate verification item if S400 bind-key setup blocks it.

### Analytics and dashboard

- Raw/canonical weight series and configurable goal line.
- Time-aware display trend for irregular observations.
- Robust trailing weight-change rate.
- Body-fat, source-provided muscle, estimated fat-mass, and estimated lean-mass series without cross-algorithm mixing.
- A conservative similar-weight/recomposition view.
- Coverage/freshness/gap summary.
- Provenance, import history, source overlay, and an obvious algorithm-boundary warning.

## 3. Explicitly out of scope

- Garmin or Fitbit authentication, ingestion, schemas specific to their payloads, or live backfill.
- Sleep, activity, intraday-series, Telegram, email, lab, or report implementation.
- A custom Recovery Score.
- Automatic Xiaomi calibration or mathematical conversion between Xiaomi-app and openScale composition values.
- Diagnosis, causal claims, or BIA accuracy claims.
- Generic LLM/SQL/MCP access.
- Docker, Postgres, Redis, workers, queues, multi-user authentication, or cloud deployment.
- Copying openScale/openScale-sync GPL code into Health-Check.

Small interfaces may be reserved for future typed records, report renderers, and notifiers; unused infrastructure must not be implemented.

## 4. Required stack and runtime

Use:

- Python 3.12 or newer;
- `uv` for environment/lock management;
- packaged Python `tzdata` so IANA zones such as `Europe/Moscow` resolve on
  clean Windows installations without relying on host timezone files;
- FastAPI and Uvicorn;
- SQLAlchemy 2.x and Alembic;
- Pydantic Settings;
- Jinja2 server-rendered pages plus small vanilla JavaScript/SVG for charts (no Node toolchain in R01);
- pytest and Ruff.

Canonical Windows entrypoint: `scripts/start.ps1`. It must create/check the runtime directories, apply safe forward migrations, start the loopback UI/API listener, and optionally start the separate ingest-only listener when configured. The underlying commands must remain callable directly for troubleshooting.

Default runtime layout:

```text
%LOCALAPPDATA%\Health-Check\
  config.toml
  healthcheck.db
  artifacts\
    photos\
    payloads\
  logs\
```

`HEALTHCHECK_DATA_DIR` may override this path. Tests must use a temporary directory. The repository must not contain a runtime database, uploaded image, payload, token, or report.

The UI/read/import application binds only to `127.0.0.1`. A second minimal ASGI application may bind a different port on the private LAN and exposes only the openScale ingest route plus a non-sensitive liveness route. It must not mount dashboard, analytics, import, settings, or admin routes. The two listeners share application services and SQLite WAL, not HTTP routes or credentials.

LAN ingest requires an explicit stable sender-instance UUID, a high-entropy rotatable ingest secret bound to that UUID, and a Windows firewall rule limited to the private network. HTTPS or a trusted encrypted private overlay is preferred. Plain HTTP is permitted only behind an explicit `trusted_private_lan_http` opt-in with a startup/UI warning that bearer credentials and health payloads lack transport confidentiality. Public internet exposure is unsupported.

## 5. Suggested project topology

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

## 6. R01 logical data model

Names may be adjusted to existing conventions created during implementation, but the following identities and constraints are normative.

### Reference identities

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

### Evidence and import lifecycle

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

### Confirmed measurements

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

### Canonical layer

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

### Sync and coverage

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

### Future typed entities

R02+ adds separate `sleep_sessions`, `sleep_stage_intervals`, `activities`, activity/FIT detail references, and intraday-series/chunk entities. Later releases add `context_events`, `report_runs`, and experiments. They must not be forced into `scalar_measurements` merely to avoid a migration. R01 need not create unused future tables.

## 7. Metric and provenance rules

- Canonical normalized units in R01 are kilograms and percentage points; the original unit/value remain reconstructable from raw evidence.
- `weight` is a direct physical measurement and may form a continuous canonical series across input methods only when device/unit identity is clear and no observed calibration break exists.
- `body_fat_pct`, source muscle mass, water, visceral-fat index, and similar BIA outputs are algorithm-dependent.
- A screenshot visibly sourced from Xiaomi Home but without an evidenced formula/build uses an identifier such as `xiaomi_home_s400_unknown_version`. If even the application is not evidenced, use a separate `xiaomi_s400_unknown_app_algorithm`; unknown does not mean equivalent.
- openScale values include the openScale app version and selected body-composition formula/configuration where the source exposes them. Unknown configuration remains its own non-equivalent group.
- `muscle_mass` is not renamed to `lean_mass`.
- Health-Check `estimated_fat_mass` and `estimated_lean_mass` are derived metrics, never provider-native values.

## 8. Historical photo workflow

The provider-neutral port is conceptually:

```python
class ImageMeasurementExtractor(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...
```

`ExtractionRequest` contains artifact ID/reference, declared locale/timezone hints, and target schema version; it never accepts an arbitrary filesystem path. `ExtractionResult` contains extractor/provider/model/prompt/schema versions and one or more measurement groups. Each candidate field contains metric code, source text when available, proposed value/unit/time, nullable model-reported confidence, and optional image-region evidence. Provider errors return a typed failure and leave the artifact replayable. Normal runtime composition selects the configured real extractor and fails closed with `extractor_not_configured` when endpoint/model configuration is absent; the deterministic fake is reserved for explicit tests and synthetic demo composition. Network calls occur only from explicit import/reprocess actions, and no live model call occurs in CI.

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

## 9. openScale-sync webhook workflow

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

## 10. R01 API and UI contract

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

## 11. Deterministic analytics v1

All calculations operate on confirmed canonical observations, use source time, and return input count, covered span, algorithm version, and unavailable reason.

### 11.1 Display weight trend

1. Reduce multiple canonical observations on one local date to the daily median while preserving drill-down.
2. Sort by observation time.
3. Apply time-aware exponential smoothing with a 21-day half-life:

```text
alpha_i = 1 - 2^(-delta_days / 21)
trend_i = alpha_i * value_i + (1 - alpha_i) * trend_(i-1)
```

The first observation initializes the series. This is `weight_trend_taewma_v1`. It is preferred to per-observation `alpha=0.1` because weekly/irregular gaps must affect smoothing. Raw points remain visible. Kalman, LOESS, and STL are not R01 defaults.

### 11.2 Rate of change

Use Theil–Sen median pairwise slope over daily medians in the trailing 90 calendar days, converted to kg/week. Require at least six observations spanning at least 42 days; otherwise return unavailable. Report count and span, and do not manufacture a confidence interval in R01. This is `weight_rate_theil_sen_90d_v1`.

### 11.3 Body composition

For a single confirmed session with compatible weight and body-fat inputs:

```text
estimated_fat_mass_kg = weight_kg * body_fat_pct / 100
estimated_lean_mass_kg = weight_kg - estimated_fat_mass_kg
```

Record both input IDs under `body_composition_decomposition_v1`. Do not combine a weight from one date with body fat from another. Smooth/display composition only within one algorithm compatibility group. Display sensible precision (normally one decimal) without discarding stored source precision.

### 11.4 Recomposition view

R01 provides evidence, not a classifier:

- time series and a weight-vs-body-fat/fat-mass scatter grouped by algorithm;
- an optional similar-weight comparison only for same-algorithm observations at least 28 days apart and within 1% body weight;
- exact dates, source algorithm, and deltas;
- no automatic claim that a small BIA change is real muscle gain or fat loss.

If there is no compatible pair, show why. Never bridge an algorithm boundary to create a comparison.

### 11.5 Coverage v1

For a requested period and configured weight cadence (default seven days), return:

- observed unique measurement dates;
- expected cadence bins and covered bins;
- oldest/latest observation and freshness;
- longest gap;
- algorithm/source breakdown;
- per-bin state plus counts/intervals for `present`, `confirmed_empty`, `unavailable`, `failed`, and `unknown`.

Coverage is evidence metadata, not a replacement value. Trend and slope availability gates remain separate from an overall label.

## 12. Canonical rule v1

The initial rule is intentionally small:

1. Eligible evidence is confirmed and not superseded.
2. Exact duplicate imports collapse to one semantic source record while retaining all linked raw artifacts/attempts.
3. Weight selects the latest confirmed revision for each semantic weigh-in.
4. Composition selection requires an explicit algorithm compatibility group; the default rule never crosses groups.
5. Derived measurements are eligible only when all inputs are eligible and their derivation version matches the requested analytics version.

The rule is serialized, hashed, and tested with reordered input. Identical input plus identical rule must yield byte-equivalent ordered selection output.

## 13. Security and privacy

- Use synthetic fixtures only in the repository and CI.
- Keep runtime data and logs under the external data directory; logs contain IDs/counts, not payload bodies or measurements by default.
- Do not log authorization headers, tokens, raw photos, or extracted personal values.
- Use a stable sender UUID plus a separate high-entropy rotatable webhook credential. An environment override is allowed; persisted secrets must live outside Git and be documented.
- Limit upload size and accepted media types; generate storage names rather than trusting filenames.
- Keep UI/read/import routes loopback-only. The optional LAN listener is ingest-only, uses a separate port/app, and follows the explicit encrypted-overlay/HTTPS or warned trusted-LAN transport mode; public exposure is unsupported.
- No analytics or import endpoint may accept an arbitrary filesystem path.
- The UI must warn that consumer BIA is non-clinical and method-sensitive.

## 14. Error and reprocessing behavior

- Every import/webhook event ends as received, parsed, pending-confirmation, committed, rejected, duplicate, or failed.
- Failures expose a stable reason code plus a sanitized message.
- A failed parser run leaves immutable raw evidence available for a later reprocessor.
- Candidate edits are audited; confirmed measurements are revised by supersession.
- Analytics never drops an invalid point silently: excluded points and reasons are returned in metadata.
- Confirmation is transactional. A structurally valid webhook batch stores its envelope transactionally and normalizes items with savepoints under the durable mixed-validity policy above.

## 15. Testing contract

All automated checks run offline and without provider credentials.

Canonical local checks are `uv run ruff check .` and `uv run pytest`. The implementation may add a type checker, but these two commands and the fresh-start PowerShell smoke are mandatory and documented in the README.

Required suites:

- migration from empty database; migration idempotency; WAL and foreign-key assertions;
- configuration/runtime-directory isolation on Windows-compatible paths;
- synthetic photo batch, extractor contract, per-field normalization, edit/reject/confirm, and reprocessing;
- exact-image and semantic-record idempotency;
- pinned openScale-sync webhook contract fixture, listener route isolation, auth/secret rotation with stable sender identity, unknown fields, malformed envelope, mixed valid/invalid batch, out-of-order replay, lost-response duplicate retry, and transaction failure;
- algorithm-provenance and incompatible-series rejection;
- canonical selection-run determinism/input-snapshot hash under input reordering, failed-run behavior, and rule/input version change;
- time-aware EWMA with irregular gaps and same-day medians;
- Theil–Sen slope with outlier, minimum count/span, and no-data cases;
- fat/lean derivation with explicit input IDs and no cross-session pairing;
- coverage state/precedence with present, confirmed-empty, unavailable, failed, unknown, and missing-not-zero cases;
- instant/minute/date temporal precision with a date-only case proving that no midnight UTC timestamp is invented;
- API/UI smoke tests and safe error rendering;
- repository hygiene check for database/image/payload/secret patterns.

Use generated/synthetic data only. A private owner UAT data directory may validate real screenshots and the live phone path, but its contents and output never enter Git or test artifacts.

## 16. Acceptance criteria and evidence

| ID | Verifiable acceptance criterion | Required evidence |
|---|---|---|
| AC-01 | A clean Windows checkout starts with the documented PowerShell entrypoint, stores runtime state outside the repository, keeps UI/read/import on loopback, and exposes only the separate ingest app on an enabled LAN port. | Fresh-start transcript, path assertions, and negative route-isolation probes against both ports. |
| AC-02 | Empty-database migration succeeds, WAL and foreign keys are active, and rerunning migration is safe. | Migration tests and pragma assertions. |
| AC-03 | A synthetic six-month/26-image batch reaches a review queue without creating a confirmed or canonical measurement. | Integration test with table counts. |
| AC-04 | Every confirmed photo value links to image hash, batch/event, extractor version, acquisition source, physical device, measurement algorithm, and explicit temporal precision; date-only evidence has no invented midnight instant. | Provenance query and temporal-precision tests. |
| AC-05 | Extractor confidence is nullable/per-field and never substitutes for human confirmation. | Schema and workflow tests; no fixed confidence default. |
| AC-06 | Re-uploading the same image and reconfirming the same candidate does not duplicate measurements; explicit reprocessing creates a versioned candidate set. | Idempotency/reprocessing tests. |
| AC-07 | The pinned openScale-sync fixture is accepted and retained; a mixed valid/invalid batch commits valid items, quarantines invalid items, and acknowledges only after all states are durable; invalid envelope/auth is rejected without secret logging. | Contract, mixed-batch, transaction, and log-capture tests. |
| AC-08 | Replaying after a lost response or out-of-order backfill does not duplicate sessions/values/failed items; rotating the credential while retaining the sender UUID does not change identity. | Duplicate/backfill/secret-rotation integration tests. |
| AC-09 | Xiaomi-app composition and openScale composition have different algorithm identities and cannot silently form one trend/canonical series. | Constraint/service tests and dashboard smoke assertion. |
| AC-10 | Canonical selection preserves all source values; the same scope/rule/input snapshot is idempotent under input reordering, failed runs never activate, and rule/input changes create a new versioned run. | Run/hash determinism tests and database assertions. |
| AC-11 | The dashboard shows raw weight, the 21-day time-aware trend, goal line when configured, and provenance drill-down. | API/UI smoke plus manual visual check with synthetic data. |
| AC-12 | Weight rate is Theil–Sen over trailing 90 days and works with irregular dates/outliers; insufficient evidence returns unavailable, not zero. | Unit tests with hand-checkable fixtures. |
| AC-13 | Estimated fat/lean values use same-session compatible inputs and retain input IDs/version; source muscle stays distinct. | Derivation tests. |
| AC-14 | Recomposition view never crosses an algorithm boundary and labels consumer-BIA uncertainty. | Service and UI tests. |
| AC-15 | Coverage shows count, cadence bins, freshness, longest gap, source/algorithm split, and present/confirmed-empty/unavailable/failed/unknown states without fabricating measurements. | Coverage precedence unit/API tests. |
| AC-16 | Correcting a confirmed value preserves the superseded value and causes a versioned canonical recomputation. | Revision integration test. |
| AC-17 | All tests and lint run offline with synthetic fixtures and no live credentials. | Canonical check transcript. |
| AC-18 | `git diff` contains no application runtime data, real health values, images, payloads, tokens, databases, or generated reports. | Final tracked/untracked and ignore audit. |

Optional live acceptance:

- Pair the owner's S400 in openScale using owner-held MAC/bind-key material.
- Capture the installed openScale-sync version's real generic-webhook request in the private runtime directory.
- Replay it successfully to the laptop over a private LAN and confirm one measurement.

If optional live acceptance is not possible, report it as `UNVERIFIED`; do not fake a successful BLE/webhook claim.

For the released R01, live S400/openScale BLE and the real external
vision-provider call are still **UNVERIFIED**. The final owner gate covered
the offline/synthetic contract, fail-closed unconfigured-provider behavior,
and the owner-assisted historical import, not those optional live paths.

## 17. Implementation sequence

1. Bootstrap project, configuration, external runtime path, launcher, and checks.
2. Add migrations/reference identities/raw/import/source-measurement tables and repositories.
3. Implement photo candidate workflow and batch dashboard.
4. Implement canonical rule v1 and provenance queries.
5. Implement pure weight/composition/coverage analytics with tests.
6. Build weight dashboard and algorithm warnings.
7. Implement/replay the pinned openScale-sync webhook contract and idempotency.
8. Run the full offline suite, visual smoke, privacy/ignore audit, and optional private live verification.

Each step must leave migrations and tests green. Do not start R02 Garmin work as cleanup or follow-up inside R01.

## 18. Definition of done

R01 is done only when all non-optional acceptance criteria pass, the dashboard is usable with a synthetic six-month history, the allowed live limitation is honestly reported, canonical documents reflect any implementation-discovered contract change, and no private/runtime artifact is present in Git.
