# Product Vision

## Product definition

Health-Check is a **single-user, local-first personal health observatory** for one person using a Windows laptop. It combines long-term source evidence, deterministic/reproducible analytics, life context, and later laboratory data. A visual dashboard and a conversational AI interface are equal product surfaces over the same evidence layer.

Health-Check is not:

- a SaaS or multi-user platform;
- a workout generator or daily wearable dashboard replacement;
- a mandatory diary or nutrition tracker;
- a medical diagnosis or treatment system;
- a universal wearable-integration framework.

Local-first means the owner controls the runtime, provenance and history. It does not prohibit explicitly selected compact evidence packets from being sent to an external model later.

## Priority and current outcome

Product priorities remain:

1. **Weight and body composition.** Observe sustainable trend/recomposition while preserving provenance and algorithm boundaries.
2. **Sleep.** Understand long-term change and compare sources honestly.
3. **Physical activity and fitness.** Preserve activities and make cycling/session comparison useful.
4. **Recovery and general wellbeing.** Interpret source metrics without inventing a premature universal score.

The product has now moved beyond its first slices:

- R01 established the local runtime and weight/body-composition vertical slice;
- R02 added production Garmin ingestion/backfill;
- R03 added deterministic Garmin analytics and owner dashboard;
- R04 added production Google Health API v4 ingestion with owner-live OAuth/sync/backfill/refresh proof;
- R05 delivered exploratory Garmin/Google wearable sleep agreement with strict fail-closed legacy cohorts; Garmin remains canonical/default and #105 stayed deferred/NOT_ELIGIBLE.

The current bounded product focus is the **#119 deterministic period brief** over existing analytics, not another ingestion framework or a new health-score layer.

## Sources

- **Xiaomi Body Composition Scale S400:** historical screenshot/photo import and openScale/openScale-sync live path.
- **Garmin Vivoactive 5 / Garmin Connect:** released ingestion, historical backfill, deterministic analytics and owner dashboard.
- **Google Health API v4:** released ingestion for sleep and supported health metrics/measurements, with preserved source/device metadata and explicit source-family semantics.
- **Google wearable / Fitbit evidence:** eligible for R05 device-level agreement only when persisted metadata explicitly supports the intended Fitbit/device attribution. Broader `google-wearables` family evidence remains family-level, not automatically Fitbit-device evidence.
- **Free-text context:** later short events/exposure intervals through dashboard/Telegram.
- **Later:** laboratory results, medications/supplements and personal health documents.

Every source value remains available. A canonical rule may select one value for one metric/period, but selection never deletes competing evidence.

## Current product question: which sleep source should we trust for which metric?

R05 posed this empirically and per metric. Accepted closeout evidence was insufficient for a canonical switch; Garmin remains the default until a reviewed per-metric rule changes that.

The intended flow is:

1. pair eligible overnight sessions by local wake date;
2. project only genuinely comparable sleep metrics;
3. calculate versioned agreement statistics over immutable evidence;
4. show source overlays and disagreements;
5. consider a reversible per-metric canonical-source rule only after enough explicit device-attributed evidence exists.

The exploratory gate is 14 paired nights. A provisional canonical-source decision requires 42 valid device-pair nights across at least six weeks plus coverage/stability checks. Correlation alone is never enough.

## Core usage modes

### Automatic reviews

Planned recurring reviews remain:

- Sunday weekly review;
- month-end review;
- annual review.

Each review will be computed from deterministic evidence, then rendered to dashboard/Telegram/email. Missing coverage remains part of the result, not something hidden by prose.

### Ad-hoc investigation

The user should be able to ask questions such as:

- What happened over the last 10 days?
- How is weight changing?
- At similar weight, what happened to estimated fat and lean mass?
- Compare recent bicycle rides.
- How are sleep and activity related?
- What happened around travel, alcohol, illness, stress, or poor sleep?
- How far apart are Garmin and Google/Fitbit sleep estimates?
- Which source is currently more stable for a given metric?

Typed analytics services compute summaries, comparisons, agreement, trends, coverage and provenance. The LLM explains those results and uncertainty; it does not calculate years of raw samples or diagnose disease.

## Life context without diary friction

The primary context object is an event/exposure interval, not a mandatory daily questionnaire. The system stores the user's original wording, time/date range, capture source and optional tags. Unambiguous notes should be cheap to capture; ambiguity may trigger a small confirmation step.

Dashboard and Telegram are the intended primary capture paths. Obsidian is optional and not a canonical health store.

## Evidence and safety principles

- Preserve raw evidence where practical and always preserve source provenance.
- Keep physical device, provider/input method and measurement algorithm distinct.
- Do not silently compare or merge body-composition series produced by different algorithms.
- Do not label source-family aggregates as a specific device without explicit metadata.
- Prefer repeated observations and agreement over single measurements.
- Treat consumer BIA/wearables as observational instruments, not clinical truth.
- Treat association as exploratory evidence, not causation.
- Expose coverage, freshness, disagreement and computability alongside conclusions.
- Represent unavailable/missing evidence honestly; never convert it to zero.
- Keep proprietary provider scores separate from Health-Check-derived metrics.
- Permit historical reprocessing under new parser/canonical versions without destroying prior evidence.
- Keep owner secrets, raw payloads and private runtime data outside Git and worker environments.

## Product boundaries

Dashboard and AI are equal interfaces, but analytics truth lives below both. UI/LLM code must not become a second mathematics engine.

No custom Health-Check Recovery Score is scheduled until R05+ evidence demonstrates a concrete unmet need. Any future score must be transparent, versioned, component-attributed and explicitly non-medical.

## Future personal health record

Later releases may ingest bloodwork, vitamin/mineral panels, medications/supplements and medical/laboratory documents. Original documents remain linked to confirmed structured results. Extraction may use external vision/LLM tools, but uncertain fields require confirmation and unsupported diagnosis remains out of scope.

## Repository rule

Code, schemas, tests, synthetic fixtures and sanitized engineering evidence belong in Git. Real health data, screenshots, raw provider payloads, credentials/tokens, databases, generated reports and personal documents do not.