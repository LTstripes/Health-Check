# Reference Projects and Reuse Strategy

This document tracks external projects that may reduce implementation work. License boundaries matter: do not copy code until the relevant license is understood and compatible with our intended repository license/distribution model.

## Summary

| Project | Primary value to Healh-Check | License / reuse stance | Current recommendation |
|---|---|---|---|
| [TolmachevKirill/garmin_ai](https://github.com/TolmachevKirill/garmin_ai) | Garmin collectors, raw/local cache, Windows packaging, reports, MCP/Telegram patterns | Repository describes itself as open source, but no root LICENSE was identified during the initial review | Study and potentially reuse ideas; **do not copy code until license is clarified** |
| [dandwhelan/garmin-stats-ai](https://github.com/dandwhelan/garmin-stats-ai) | Garmin ingestion plus personal baselines, trends, anomalies, correlations, deterministic analytics and dashboard patterns | MIT (bundled garmin-grafana module retains BSD-3-Clause) | High-priority code/architecture donor candidate |
| [Deekshith-Dade/fettle](https://github.com/Deekshith-Dade/fettle) | Current Google Health API / Fitbit sync, SQLite, readiness/insights, analytics, MCP, single-user local-first design | MIT | High-priority donor for Fitbit/Google Health integration and analytics patterns |
| [the-momentum/open-wearables](https://github.com/the-momentum/open-wearables) | Unified provider abstraction, normalized API, Health Connect SDK/sync design | MIT | Strong reference for provider/canonical models; likely too broad/heavy to adopt wholesale |
| [oliexdev/openScale](https://github.com/oliexdev/openScale) | Direct BLE ingestion from Xiaomi Body Composition Scale S400 and body metrics | GPL-3.0 | Use as a separate Android application/integration; avoid copying GPL code into core |
| [oliexdev/openScale-sync](https://github.com/oliexdev/openScale-sync) | Sync openScale data to Health Connect, generic webhooks, MQTT and other services | GPL-3.0 | Prefer external webhook/Health Connect boundary |
| [nikira-studio/healthquery](https://github.com/nikira-studio/healthquery) | Health Connect -> webhook -> SQLite -> dashboard/LLM/MCP, read/write token separation, SQL read guard | MIT | Useful reference/donor for Android/Health Connect bridge and local API/security patterns |
| [biosync-io/vitasync](https://github.com/biosync-io/vitasync) | Provider plugin architecture, correlation/anomaly/health-score systems, LLM-ready contexts, reports | AGPL-3.0 | Architecture/reference only unless AGPL implications are intentionally accepted; too infrastructure-heavy for our single-user scope |

## Detailed notes

### garmin_ai

Useful pieces to inspect:

- personal Garmin Connect access through `python-garminconnect`;
- raw payload caching;
- daily/activity collectors;
- local SQLite/report pipeline;
- MCP integration;
- Windows packaging and desktop application;
- Telegram/reporting UX patterns.

Main concerns:

- no root license identified in initial review despite the project describing itself as open source;
- contains workout creation/write functionality that is outside our core product goal;
- current analytics layer appears more report-oriented than our planned longitudinal/statistical engine.

**Decision:** keep monitoring releases and treat as an important reference, but do not base our repository on copied code until licensing is clarified.

### garmin-stats-ai

Particularly aligned with our intended architecture:

- local SQLite;
- personal baselines;
- rolling metrics;
- trends;
- z-score anomalies;
- correlations/statistical tests;
- LLM interprets precomputed evidence rather than doing the primary math;
- Garmin-specific health/recovery focus.

**Decision:** one of the first repositories for source-level technical audit.

### fettle

Particularly aligned with the Fitbit side:

- built for the current Google Health API rather than legacy Fitbit Web API;
- personal/single-user local design;
- OAuth and incremental synchronization;
- SQLite storage;
- sleep/readiness/training analytics;
- anomaly/correlation/insight patterns;
- MCP/AI integration;
- deterministic analysis before LLM narration.

**Decision:** likely primary donor/reference for the Google Health/Fitbit adapter.

### Open Wearables

Strengths:

- provider abstraction;
- normalized health data API;
- multiple wearable providers;
- Android Health Connect/Samsung Health sync SDK patterns;
- self-hosted model;
- active project and MIT license.

Caveats:

- designed for a broader platform than our single-user application;
- some AI assistant capabilities are still evolving;
- official-provider approaches may require access/approval that is unnecessary for our personal Garmin use case.

**Decision:** use as architecture/reference material; avoid inheriting platform complexity without a concrete need.

### openScale + openScale-sync

The openScale supported-scale documentation currently lists **Xiaomi Body Composition Scale S400** with `MiScaleS400Handler`, BLE Broadcast and body metrics support.

Potential integration:

```text
Xiaomi S400 -> openScale -> openScale-sync -> generic webhook or Health Connect -> Healh-Check
```

This is preferable to image-only ingestion if it proves stable on the user's phone.

Because both projects use GPLv3, keep them outside the Healh-Check codebase and integrate over external interfaces.

**Decision:** primary Xiaomi ingestion experiment; retain screenshot/photo import as fallback and historical-data path.

### HealthQuery

Useful patterns:

- Android Health Connect companion -> webhook;
- SQLite/WAL local storage;
- local dashboard;
- MCP;
- separate ingest and read tokens;
- read-only SQL guard;
- privacy-conscious self-hosted deployment.

**Decision:** strong reference for Health Connect ingestion/security, especially if we later use Health Connect as a generic Android bridge.

### VitaSync

Very close to the broad feature vision:

- provider plugins;
- unified metrics;
- correlation engine;
- anomaly detection;
- health scores;
- reports;
- LLM-ready context endpoints.

But it targets a production multi-tenant platform with PostgreSQL/Redis/workers/Kubernetes-style infrastructure and uses AGPL-3.0.

**Decision:** study concepts and schemas, but do not choose it as the base for a simple local single-user application.

## Technical audit required before implementation

For each high-priority donor, inspect actual source rather than relying on README claims.

Audit fields:

- repository SHA/tag reviewed;
- license and embedded third-party licenses;
- data model/schema;
- provider/auth implementation;
- sync/backfill behavior and idempotency;
- raw payload retention;
- metric coverage;
- timezone handling;
- source provenance;
- tests and fixtures;
- analytics algorithms;
- LLM boundary;
- local security model;
- packaging/deployment;
- reusable files/modules;
- changes required for Healh-Check.

Initial audit priority:

1. `garmin-stats-ai`
2. `fettle`
3. `garmin_ai`
4. `HealthQuery`
5. `openScale` / `openScale-sync` integration path
6. `open-wearables`
7. `VitaSync` (architecture comparison only)
