# Final Target Architecture

This is the current canonical architecture after released R01–R04. Historical evidence and disputed findings remain in the R00 audit, release issues and release-specific closeouts.

## 1. System shape

```text
Windows laptop
┌──────────────────────────────────────────────────────────────────┐
│ Windows Task Scheduler / explicit owner CLI                     │
│             │ sync / backfill / refresh / reports               │
│             v                                                    │
│ Health-Check Python runtime                                      │
│   ├── explicit provider adapters (Garmin / Google / imports)     │
│   ├── immutable raw + typed source evidence                      │
│   ├── current/canonical versioned selection                      │
│   ├── deterministic analytics / coverage / agreement             │
│   ├── loopback UI + read/query APIs                              │
│   ├── optional isolated ingest-only listener                     │
│   └── SQLite WAL + local artifact store outside Git              │
└──────────────────────────────────────────────────────────────────┘
       ^                     ^                         |
       |                     |                         v
 Garmin Connect       Google Health API v4        bounded read-only AI

Android phone
┌──────────────────────────────────────────────────┐
│ Xiaomi S400 -> openScale -> openScale-sync      │
│                         -> Health-Check webhook  │
└──────────────────────────────────────────────────┘
```

One local codebase/database is enough. No broker, queue, container platform, multi-tenancy or SaaS authentication is added without a demonstrated need.

## 2. Runtime boundary

- Python 3.12+, FastAPI/Uvicorn, SQLAlchemy/Alembic, SQLite WAL.
- Runtime state under a user-scoped external data directory, never inside the checkout.
- Loopback UI/read/import listener is distinct from the optional ingest-only listener.
- Provider credentials/tokens/session files remain external and use Windows user-scoped protection where implemented.
- Content-addressed raw artifacts/provider evidence remain local; Git contains code, schemas, docs, tests and synthetic fixtures only.

## 3. Data pipeline

```text
immutable raw/provider evidence
            |
            v
typed source record + provider/device/algorithm provenance
            |
            v
current projection / versioned canonical selection
            |
            v
deterministic analytics + coverage + agreement
            |
            v
versioned evidence packet / saved report
            |
     dashboard / bounded AI
```

Raw, source-specific, current/canonical, derived and narrative layers are different contracts. Reprocessing creates new versioned interpretation while preserving original evidence.

## 4. Shared provenance rules

The system keeps separate identities for:

- physical device;
- provider/account/source;
- acquisition method / source family / query mode;
- measurement algorithm and version;
- raw artifact / provider observation;
- typed source/current projection;
- canonical rule and derived algorithm.

Acquisition context must never be silently promoted into physical-device identity.

Missing, null, explicit zero, confirmed-empty, unavailable, unknown and invalid remain distinct where the owning contract supports them.

## 5. Provider flows

### Xiaomi S400

Preferred live path:

```text
S400 -> openScale -> openScale-sync -> authenticated ingest-only endpoint
```

Historical/fallback path:

```text
Xiaomi screenshot/photo -> immutable image -> versioned extraction
 -> editable candidate -> explicit confirmation -> typed source evidence
```

Xiaomi-app and openScale body-composition algorithms are non-equivalent compatibility groups unless future paired evidence supports a versioned calibration.

### Garmin

Garmin uses `python-garminconnect` rather than a second private HTTP client.

Released R02/R03 behavior:

- owner-assisted protected session reuse;
- typed daily/sleep/activity/intraday persistence;
- bounded incremental sync + trailing reconciliation;
- bounded resumable historical backfill;
- explicit historical/incremental coverage/checkpoints;
- authoritative vs partial collection-reconciliation semantics;
- version-aware reprocessing;
- deterministic analytic metric/time/coverage identity;
- immutable evidence manifests;
- scalar baseline/trend analytics, activity comparison, lagged associations and read-only dashboard/query paths.

Client method existence never proves Vivoactive 5 capability. Provider/account/device evidence stays explicitly attributed.

### Google Health API v4

R04 is released and uses an explicit `google_*` path over shared runtime/evidence primitives. Garmin-specific tables/contracts are not reused as a generic provider framework.

#### OAuth/runtime

- Google Web Application / Web Server client.
- Fixed exactly registered loopback callback.
- System-browser authorization-code flow with one-use CSRF state.
- `access_type=offline`; consent prompting only when required by the accepted auth path.
- Exactly two R04 read scopes: sleep + health metrics/measurements.
- Client secret/token/session state stored only in the external runtime with Windows user-scoped DPAPI protection.
- Owner project proven `In production`, External.

#### Source identity

`list`, `reconcile`, `rollUp`, `dailyRollUp` and `dataSourceFamily` are acquisition/query context, not stable source/device identity.

`google-wearables` is family-level evidence and may include more than one wearable class. It is not automatically Fitbit-device proof. Physical Fitbit/device attribution requires explicit persisted provider/device metadata.

Raw list/source metadata remains distinct from family-reconciled/rollup evidence.

#### Sync contract

R04 supports:

- bounded incremental sync;
- bounded historical backfill;
- explicit bounded refresh/reconciliation;
- provider request budgets and bounded retries;
- pagination/resume;
- separate incremental/historical/refresh state;
- exact completed-window provider skipping when coverage proves no work remains;
- immutable prior evidence on refresh/correction;
- privacy-safe structural diagnostics;
- fail-closed handling for unknown provider shapes.

Time windows are inclusive lower / exclusive upper. Undocumented list ordering is not assumed.

#### Proven terminal empty-envelope variant

Owner-live R04 exposed a list response where the JSON object omitted both the repeated collection field and next-page token. Current ProtoJSON semantics permit omitted empty repeated fields.

Accepted narrow rule:

- LIST/RECONCILE + missing collection + no usable next token => complete empty terminal page;
- missing collection + usable token => continue pagination;
- normal array + token/no-token => continue/complete normally;
- null/non-array/malformed collection => invalid/fail-closed;
- rollup shapes are not broadened by this exception.

## 6. Logical data model

### Shared evidence/provenance

- providers / acquisition sources / physical devices;
- measurement algorithms;
- raw artifacts / immutable provider observations;
- ingest batches/events;
- sync runs / stream state / coverage.

### Typed source data

- scalar measurements;
- sleep sessions / stage intervals;
- activities;
- intraday series/chunks/points;
- Garmin-specific typed source/current records;
- Google-specific raw/source/typed current records;
- later context events and lab data.

This is intentionally not a generic EAV health store.

### Interpretation/output

- current projections and versioned canonical selections;
- versioned derived measurements;
- deterministic analytics/evidence manifests;
- agreement runs and optional canonical-source rules in R05;
- report/evidence packets and later delivery attempts.

## 7. Idempotency and synchronization

Each provider path defines:

- stable external identity when available;
- semantic fingerprint fallback;
- bounded window/request semantics;
- checkpoint/coverage namespace;
- retry/backoff/failure classes;
- immutable raw observation history;
- current-projection reconciliation rules;
- explicit version-aware reprocessing/refresh when accepted.

Receive order never defines event order. Partial/unknown/failed fetches do not retire accepted current evidence or advance successful checkpoints unless the owning contract explicitly proves completion.

## 8. Coverage

Coverage accompanies every non-trivial result and may include:

- requested vs covered interval;
- freshness / gaps;
- usable vs excluded counts;
- per-source / per-metric status;
- present / confirmed-empty / unknown / failed / unavailable states;
- rule/algorithm/version identity.

Operational provider `present` does not imply that every analytic metric is computable.

## 9. Time and lag semantics

- Persist real UTC when the source proves it.
- Preserve original local time/offset/zone evidence where available.
- Do not invent UTC for local-only timestamps.
- Preserve date-only precision.
- Sleep belongs to local wake date.
- Lag direction is explicit; e.g. X[d] with Y[d+k].

## 10. Deterministic analytics

The deterministic layer owns:

- baseline summaries and quantiles;
- robust trends/deviations;
- activity/session comparison;
- bounded lagged associations;
- coverage/freshness/exclusions;
- source agreement and later canonical-source rules;
- reproducible versioned evidence packets.

UI and LLM layers may format/explain these results but must not become separate analytics engines.

## 11. R05 agreement architecture

R05 uses:

```text
source evidence
 -> pairing / eligibility
 -> comparable metric projection
 -> immutable versioned agreement run
 -> optional versioned canonical-source rule
```

Two cohorts are intentionally different:

- `device_pair`: explicit persisted Fitbit/device attribution; eligible for the strong canonical gate;
- `family_pair`: broader Google wearable-family evidence; exploratory only.

Agreement is per metric. Provider scores are display-only, not treated as equivalent measurements.

Exploratory gate: 14 paired nights.

Provisional canonical-source gate: 42 valid device-pair nights across at least six weeks plus coverage/stability checks. Canonical default remains Garmin until a reviewed versioned per-metric rule changes it.

## 12. AI boundary

Default AI path:

```text
LLM -> typed bounded read tool -> deterministic application service
    -> compact versioned evidence packet
```

No provider credentials, unrestricted raw tables, private runtime paths or years of raw samples are sent merely to let the LLM do mathematics.

## 13. Release and migration safety

A release is not complete until:

- exact accepted candidate is known;
- exact-head CI is green;
- owner UAT covers private-runtime/provider behavior where relevant;
- populated owner DB migration/integrity is checked when schema changes matter;
- release PR merges the exact accepted candidate to `main`;
- exact post-main CI is green;
- sanitized closeout is recorded.

`main` is the only canonical release source. Integration/task branches are staging/history, not product truth.