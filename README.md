# Health-Check

Health-Check is a single-user, local-first personal health observatory for a Windows laptop. It preserves source evidence from personal devices, turns it into reproducible deterministic analytics, and exposes the same evidence through local dashboards and later bounded AI tools.

It is not a SaaS product, medical diagnostic system, workout planner, or replacement for Garmin / Google Health / Xiaomi daily apps.

## What is released now

Canonical source: `main`.

- **R01 — Weight & Body Composition:** Xiaomi screenshot/photo import, openScale/openScale-sync contract, provenance, canonical selection, conservative body-composition analytics, local dashboard, backup/restore.
- **R02 — Garmin ingestion/backfill:** protected owner session reuse, typed Garmin persistence, bounded incremental sync, resumable historical backfill, coverage/checkpoints and exact-rerun idempotency.
- **R03 — Garmin analytics/dashboard:** deterministic personal baselines/trends, activity comparison, lagged associations, provider-native metric presentation, reproducible evidence manifests and owner-facing read-only Garmin UI.
- **R04 — Google Health ingestion:** Google Health API v4 OAuth, protected session storage, source-aware typed persistence, bounded incremental sync/backfill/refresh, coverage/checkpoints, privacy-safe diagnostics and live owner verification.
- **R05 — Garmin / Google wearable sleep agreement:** pairing, comparable projection, immutable agreement runs, statistics/gates, exploratory owner report; Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.

R04 release lineage:

- release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release PR: #114
- release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-merge `main` CI: `34768452960` — SUCCESS
- closeout: [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)

The final R04 owner gate also proved the populated private runtime remained healthy at Alembic `0010_google_typed_normalization`, with WAL/FK enabled, `quick_check=ok` and zero foreign-key violations.

## Current focus

R05 is released (exploratory closeout; Garmin canonical/default; #105 deferred/NOT_ELIGIBLE). Closeout: [R05 Release Closeout](docs/R05_RELEASE_CLOSEOUT.md).

Post-R05 product closeout: **#119 deterministic period brief v1** is **completed** on canonical `main @ 2c19ca968f84efb5e69c1a859ce6016939e617ca` (exact-main CI `35139999279` SUCCESS). Delivered: deterministic weight/sleep/activity/data-quality period brief packet, stable result hash, thin API/text/CLI rendering, accepted direct R05 sleep-report reuse, and full activity inventory repairs. No new health scores; no LLM delivery.

Current bounded product focus: **#127 Period Brief local UI v1** (presentation over the accepted #119 contract). Parallel CI/reliability work #123–#126 is a separate maintenance track, not the next health-product release.

Attribution remains conservative: `google-wearables` family evidence is not automatically Fitbit-device evidence; `account_wearables_sleep_observations_v1` stays exploratory/uncertain-only; Garmin remains canonical/default; #105 remains deferred/NOT_ELIGIBLE (not an actionable next implementation unless future live evidence meets its gate).

## Architecture in one minute

```text
provider payloads / photos / context
                |
                v
immutable raw evidence
                |
                v
typed source records + source/device/provenance
                |
                v
versioned current/canonical selection
                |
                v
deterministic analytics + coverage + agreement
                |
                v
versioned evidence packets
          /                     \
   local dashboard          bounded read-only AI
```

Core rules:

- runtime: Python 3.12+, FastAPI, SQLite WAL, Windows-first local operation;
- real runtime data, provider credentials, raw payloads, screenshots, databases and generated reports stay outside Git;
- physical device, provider/input method and measurement algorithm are separate identities;
- source-specific evidence survives canonical selection and later reprocessing;
- missing / null / zero / unavailable / unknown stay distinct;
- analytics, coverage and agreement are deterministic and versioned; the LLM explains compact evidence rather than doing raw-series mathematics;
- provider-specific ingestion remains explicit (`garmin_*`, `google_*`) over shared runtime/evidence primitives rather than a generic EAV/provider framework.

## Google Health / R04 notes

R04 uses Google Health API v4 only and exactly the accepted read scopes for sleep and health metrics/measurements. OAuth uses a Google Web Application client with a fixed registered loopback callback; protected client/token/session state lives only in the external Windows runtime.

Live owner acceptance proved bounded capability, incremental sync, resumable pagination, exact completed-window zero-call rerun, historical backfill and explicit bounded refresh. A real terminal HTTP-200 envelope with omitted empty repeated fields was repaired narrowly under #110; malformed/null/non-array variants remain fail-closed.

Source identity remains conservative. Query mode and `dataSourceFamily` are acquisition context, not device identity. Broader wearable-family evidence must not be labelled Fitbit-device evidence without explicit metadata.

## Local bootstrap

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked
uv run ruff check .
uv run pytest
```

Start the canonical Windows runtime:

```powershell
.\scripts\start.ps1
```

Runtime defaults to `%LOCALAPPDATA%\Health-Check` and may be overridden with `HEALTHCHECK_DATA_DIR`.

No health data, credentials, payloads, images, logs, database files or generated reports belong in the repository.

## Canonical documentation

- [Project Wiki / current state](docs/PROJECT_WIKI.md)
- [Product Vision](docs/PRODUCT_VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md)
- [Verbose historical execution log](docs/EXECUTION_HISTORY.md)
- [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)
- [R04 Google persistence contract](docs/R04_GOOGLE_PERSISTENCE_CONTRACT.md)
- [R03 analytic input contract](docs/R03_ANALYTIC_INPUT_CONTRACT.md)
- [Reference Projects and Reuse Strategy](docs/REFERENCE_PROJECTS.md)
- [Development Process](docs/DEVELOPMENT_PROCESS.md)
- [Model Routing](docs/MODEL_ROUTING.md)
- [Agent Orchestration](docs/AGENT_ORCHESTRATION.md)

## Safety

Health-Check is an observational personal system. Consumer wearables and BIA scales are not clinical instruments. The product exposes uncertainty, coverage and source disagreement and must not present association as diagnosis or causation.

## License

Health-Check is licensed under the [MIT License](LICENSE). External donor/library license obligations still apply at the exact reused source version.