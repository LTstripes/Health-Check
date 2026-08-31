# Target Architecture

## High-level shape

```text
Garmin Connect ---------> Garmin adapter -----------\
                                                    \
Google Health / Fitbit -> Google Health adapter -----> Canonical Health Store
                                                     /
Xiaomi S400 ------------> openScale / import ------/
                                                    \
Life context (Telegram/dashboard) -----------------> Context Store

Canonical Health Store + Context Store
            |
            v
Deterministic Analytics Engine
            |
            +--> baselines / rolling windows
            +--> trends / period comparisons
            +--> anomalies / confidence
            +--> correlations / associations
            +--> cross-device reconciliation
            +--> body-composition decomposition
            +--> data quality / coverage
            |
            v
Reports + Query API + Dashboard + read-only AI/MCP layer
            |
            +--> local dashboard
            +--> email delivery
            +--> Telegram delivery/context capture
```

## Data ingestion

### Garmin

Preferred initial route: direct personal Garmin Connect integration through the community `garminconnect` ecosystem.

Reasons:

- preserves Garmin-specific metrics that may not appear in Health Connect;
- supports historical backfill;
- already proven by multiple reference projects;
- avoids depending on approval for Garmin's official partner/developer APIs.

Primary known device: **Garmin Vivoactive 5**.

Store both normalized measurements and source/raw payloads when practical.

Important Garmin-specific signals to retain include, where available:

- Body Battery;
- Stress;
- Training Readiness;
- Training Status;
- Recovery Time;
- HRV;
- resting heart rate;
- sleep metrics/stages;
- VO2 max;
- activities and detailed activity metrics.

These scores are useful signals, but the product should not treat proprietary Garmin scores as the sole truth.

### Fitbit / Google Health

Use the current Google Health API rather than legacy Fitbit Web API integrations.

Goals:

- automatic OAuth-based sync;
- incremental backfill/sync;
- retain source timestamps and quality/provenance;
- make Fitbit sleep a candidate canonical sleep source only after a real comparison against Garmin.

### Xiaomi Body Composition Scale S400

Primary target path:

```text
Xiaomi S400 -> BLE -> openScale -> openScale-sync -> webhook and/or Health Connect -> Health-Check
```

The S400 is currently listed by openScale as supported with body metrics through `MiScaleS400Handler`.

Important: openScale/openScale-sync are GPLv3. Prefer to run them as separate applications and integrate through documented boundaries (webhook/Health Connect) rather than copying GPL code into Health-Check.

#### Photo/screenshot fallback

Keep manual image import as a supported fallback and for historical measurements.

Workflow:

1. User uploads a photo/screenshot from the Xiaomi app.
2. Vision extraction returns all relevant visible measurements.
3. Parsed values are shown for human confirmation.
4. Only confirmed values are written to the health store.
5. Record `source=xiaomi_scale`, input method (for example `photo_import`) and image provenance/reference.

Do not silently write vision/OCR results directly into the canonical store.

### Life context

Support free-text dated notes rather than mandatory daily ratings.

Primary MVP capture paths:

- Telegram bot/message flow;
- dashboard quick-entry flow.

A context event should minimally contain:

- event time/date or date range;
- free-text note;
- optional tags inferred or confirmed later;
- provenance (`telegram`, `dashboard`, `manual_import`, etc.).

Raw user wording should be preserved. Structured tags may be derived separately.

#### Obsidian

Obsidian is **not** the canonical event store in MVP. It may later be integrated as an optional import/reference source for selected folders or structured notes, but the core system should not depend on nightly parsing of a general-purpose vault.

### Nutrition

No dedicated calorie/macronutrient ingestion in the first releases. Food/alcohol remain contextual events when analytically relevant. A future optional summary import from the user's existing ChatGPT food diary may be evaluated separately.

## Canonical health store

Initial storage preference: **SQLite**.

The schema should separate source truth from canonical interpretation.

Conceptually:

```text
source_measurements
- id
- metric
- value
- unit
- timestamp/start/end
- source_provider
- source_device
- source_record_id
- payload/provenance reference
- quality metadata
- imported_at

canonical_measurements
- metric
- value
- unit
- timestamp/period
- selected_source
- selection_rule/version
- confidence

context_events
- id
- start/end
- text
- tags
- provenance

sync_state
- provider
- cursor/watermark
- last_success
- coverage metadata
```

Exact schema is still open and should be designed after the source-code audit.

## Source reconciliation

Rules:

1. Never destroy or overwrite source-specific measurements when selecting a canonical value.
2. Preferred source may differ by metric.
3. Source-selection rules must be versioned/configurable.
4. The dashboard should be able to show both the canonical metric and per-device/source variants.
5. The analytics engine should periodically quantify systematic differences between devices.

Initial working assumptions:

- Garmin: primary for most wearable/training metrics.
- Sleep: Garmin vs Fitbit comparison required before choosing a preferred source.
- Xiaomi S400: primary for weight/body composition.

## Weight and body-composition analytics

Focus on trend rather than single-day noise.

Priority metrics:

- weight;
- body-fat percentage and derived fat mass;
- lean mass;
- muscle mass where available;
- visceral-fat metric;
- body water;
- BMI;
- BMR.

Vendor "body age", opaque overall body ratings, or other low-value proprietary scores are not core analytics inputs.

Expected analyses include:

- 7/30/90-day trend;
- rate of weight change;
- fat-mass vs lean-mass change;
- progress toward target weight;
- recomposition at stable body weight;
- relationship with sleep, activity and relevant context events.

## Analytics engine

Core calculations must be deterministic and reproducible.

Candidate capabilities:

- rolling baselines and percentiles;
- trend detection;
- period-over-period comparison;
- outlier/anomaly detection;
- data coverage/quality scoring;
- Pearson/Spearman correlations where appropriate;
- lagged associations (for example sleep today vs HRV tomorrow);
- activity/session comparison;
- cross-device bias/agreement analysis;
- body-composition decomposition;
- configurable confidence/strength labels.

The LLM should request or interpret these results, not calculate them from thousands of raw rows.

## Reports and automation

Target automated cadence:

- weekly report every Sunday;
- monthly report on the last calendar day of the month;
- annual report at year end.

Routine sync and analytics recalculation should happen automatically without user intervention.

Every periodic report should:

1. be persisted/viewable in the local dashboard;
2. be proactively delivered through email;
3. be proactively delivered through Telegram.

Do not prioritize a daily morning report in MVP.

## Interfaces

### Dashboard

The dashboard should support:

- long-term graphs;
- selectable periods;
- source overlay (Garmin vs Fitbit, etc.);
- body composition and target progress;
- activity/session comparisons;
- anomaly/event overlays;
- data coverage indicators;
- drill-down from report findings;
- quick free-text context entry;
- report history.

### Telegram

Telegram should support at least:

- delivery of weekly/monthly/yearly report summaries;
- links or pointers to deeper local dashboard views where practical;
- quick free-text context/event capture;
- optional future lightweight commands/queries.

### Email

Email is a proactive report-delivery channel, not a primary data-entry channel. Exact provider/SMTP implementation should be chosen during implementation based on simplicity and reliability.

### AI / LLM

The AI interface must support arbitrary natural-language research questions and invoke read-only analytics/query tools.

Examples:

- compare arbitrary date ranges;
- explain a detected change;
- find recurring patterns around context events;
- compare similar activities;
- investigate relationships among multiple metrics.

The AI surface should be read-only with respect to imported health data except for explicit user-authored context entries or confirmed manual imports.

## Privacy and security

Local-first is primarily a product/engineering choice for simplicity, ownership and reproducibility, not a strict requirement that all health data remain offline.

Principles:

- local-first runtime and canonical database;
- no personal DB, raw health payloads, lab results, tokens or screenshots in Git;
- provider credentials/tokens stored outside the repository;
- external LLM use is allowed when useful;
- prefer sending query-sized/derived datasets instead of huge raw exports when possible;
- read-only machine/AI access where possible;
- backups and schema migrations from early versions;
- provenance and auditability for manual/AI-assisted imports.

## Timezone/travel handling

Preserve source timestamps and timezone metadata where practical. Sophisticated rules for travel, cross-timezone sleeps and report-day boundaries are deliberately deferred to a later backlog unless real data exposes a concrete issue sooner.

## Future lab/medical-data layer

Future ingestion may accept PDFs/images or structured exports from laboratory/medical sources.

Preferred workflow:

1. preserve the original document outside Git;
2. extract analytes/results/reference ranges/units;
3. show uncertain or ambiguous extraction for human confirmation;
4. store normalized values plus source-document provenance;
5. keep reference ranges supplied by that laboratory where available;
6. allow longitudinal comparisons and links to wearable/body-composition timelines.

Selected or full source documents may be sent to an external LLM when the user explicitly wants analysis; a local-only document-processing mode is not required for MVP.

LLM interpretation can add context and questions to investigate, but should not convert laboratory data into unsupported diagnoses.
