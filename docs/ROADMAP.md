# Provisional Roadmap

This roadmap is intentionally **pre-implementation**. R00 may change the technical base and therefore later sequencing.

## R00 — Source-level technical audit

Goal: determine what should be reused, adapted, integrated externally, or written ourselves.

Inspect at least:

- `garmin-stats-ai`;
- `fettle`;
- `garmin_ai`;
- `HealthQuery`;
- `openScale` / `openScale-sync`;
- `open-wearables`;
- VitaSync architecture selectively.

Output:

- exact reviewed SHAs/tags;
- per-module reuse matrix;
- license compatibility notes;
- recommended base repository strategy;
- proposed canonical schema;
- implementation plan updated from evidence.

**No production health data should be placed in any agent/development repository during this phase.**

## R01 — Local core and canonical schema

Goal: establish the smallest reliable single-user local platform.

Likely scope:

- SQLite database and migrations;
- source measurement/provenance model;
- canonical metric layer;
- context events;
- sync state/watermarks;
- data-quality/coverage model;
- local configuration and secret-storage conventions;
- backup/export baseline.

## R02 — Garmin ingestion + historical backfill

Goal: make Garmin the first complete automated source.

Scope:

- Garmin Vivoactive 5 / Garmin Connect authentication and token handling;
- incremental sync;
- maximum reliable historical backfill;
- daily health metrics;
- activities;
- Garmin-specific scores;
- raw/source payload retention where useful;
- idempotency and retry behavior;
- source coverage diagnostics.

## R03 — Xiaomi S400 ingestion

Goal: automate weight/body composition.

Primary experiment:

```text
S400 -> openScale -> openScale-sync -> webhook/Health Connect -> Health-Check
```

Also implement:

- screenshot/photo historical import;
- vision extraction with human confirmation;
- import provenance;
- duplicate detection;
- historical six-month backfill from available screenshots/data.

## R04 — Fitbit / Google Health ingestion

Goal: automated second wearable source.

Scope:

- current Google Health API OAuth;
- incremental sync and backfill;
- sleep, HR/HRV, RHR, SpO2 and other useful metrics;
- source/provenance retention;
- data coverage diagnostics.

## R05 — Cross-device reconciliation

Goal: retain both source truths while choosing useful canonical metrics.

Scope:

- configurable source preference per metric;
- Garmin vs Fitbit sleep comparison;
- bias/agreement statistics;
- source overlays in query results;
- canonical selection rule versioning;
- periodic device-comparison report.

Do not choose Fitbit or Garmin as the canonical sleep source before this phase has real data.

## R06 — Weight/body-composition analytics

Goal: solve the current primary user problem first.

Scope:

- 7/30/90-day trends;
- target progress;
- fat-mass vs lean/muscle change;
- recomposition detection at similar body weight;
- measurement-noise handling;
- relationship with sleep/activity/context;
- confidence and coverage indicators.

## R07 — General longitudinal analytics

Scope:

- personal baselines;
- percentiles;
- period comparison;
- anomaly detection;
- lagged associations/correlations;
- activity/session comparison (e.g. cycling rides);
- longer-term sleep/recovery/fitness trends;
- data-quality-aware conclusions.

## R08 — Dashboard, reports and proactive delivery

Scope:

- visual dashboard;
- selectable periods and overlays;
- weight/body-composition view;
- sleep/recovery/activity views;
- context-event overlays;
- weekly automatic report (Sunday);
- month-end automatic report;
- annual review;
- report history in the local dashboard;
- proactive email delivery;
- proactive Telegram delivery.

## R09 — AI / LLM analytics interface

Goal: arbitrary natural-language research over deterministic analytics.

Scope:

- read-only query/analytics API or MCP layer;
- tool-oriented questions over arbitrary periods;
- explanation and practical suggestions;
- citations/provenance back to calculated metrics/source coverage where practical;
- explicit confidence/caveat handling;
- external LLM use allowed when useful;
- no unrestricted mutation of health data.

## R10 — Context capture workflow

Goal: make life context useful without becoming a chore.

Scope:

- quick free-text event entry via **Telegram and dashboard**;
- date/range extraction;
- human-correctable tags;
- analytics around repeated context patterns;
- no mandatory daily mood/energy questionnaire.

Obsidian is not a dependency or canonical event store. Optional selected-note/folder import may be evaluated later if it adds useful context without turning the system into a general vault parser.

## R11+ — Broader personal health record

Future, after wearable/body composition product is stable:

- blood/lab result ingestion;
- PDF/image extraction with confirmation;
- normalized analytes, units and lab-provided reference ranges;
- vitamin/mineral tracking;
- longitudinal lab trends;
- combined lab + wearable + body-composition research;
- optional doctor-visit summaries/export;
- use of external LLMs for selected or full source documents when explicitly useful.

## Later / maybe

- native mobile app;
- additional wearable providers;
- optional Obsidian import for selected health-context notes;
- optional periodic summary import from the existing ChatGPT food diary if it proves analytically useful;
- remote secure read-only access for ChatGPT/other assistants;
- richer timezone/travel-day semantics;
- additional notification/query channels beyond dashboard/email/Telegram.

## Explicitly not an MVP priority

- workout generation/scheduling;
- replacing Garmin/Fitbit daily views;
- multi-user accounts/workspaces;
- SaaS/cloud platform architecture;
- Kubernetes/Redis/Postgres without demonstrated need;
- mandatory subjective daily journaling;
- detailed nutrition/calorie/macronutrient tracking;
- sophisticated timezone handling.
