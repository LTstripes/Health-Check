# Health-Check

Health-Check is a single-user, local-first personal health observatory for a Windows laptop. It preserves source evidence from personal devices, turns it into reproducible deterministic analytics, and exposes the same evidence through local dashboards, deterministic period reviews, Garmin training/recovery views and later bounded AI tools.

It is not a SaaS product, medical diagnostic system, workout planner, or replacement for Garmin / Google Health / Xiaomi daily apps.

## What is released now

Canonical source: `main`.

- **R01 — Weight & Body Composition:** Xiaomi screenshot/photo import, openScale/openScale-sync contract, provenance, canonical selection, conservative body-composition analytics, local dashboard, backup/restore.
- **R02 — Garmin ingestion/backfill:** protected owner session reuse, typed Garmin persistence, bounded incremental sync, resumable historical backfill, coverage/checkpoints and exact-rerun idempotency.
- **R03 — Garmin analytics/dashboard:** deterministic personal baselines/trends, activity comparison, lagged associations, provider-native metric presentation, reproducible evidence manifests and owner-facing read-only Garmin UI.
- **R04 — Google Health ingestion:** Google Health API v4 OAuth, protected session storage, source-aware typed persistence, bounded incremental sync/backfill/refresh, coverage/checkpoints, privacy-safe diagnostics and live owner verification.
- **R05 — Garmin / Google wearable sleep agreement:** pairing, comparable projection, immutable agreement runs, statistics/gates, exploratory owner report; Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.
- **Post-R05 Owner Runtime & Period Brief:** one durable private Owner profile, verified backup/restore UAT clones, one-command Garmin/Google refresh, deterministic Period Brief correctness/UI closeout and Owner UAT.
- **Garmin Training & Recovery:** live-discovered Garmin-native Training Status/load/ACWR, Load Focus, Training Readiness/Recovery and activity Training Effect/load are persisted, included in normal owner refresh and shown read-only on the Garmin owner page.
- **Context capture v0:** revisioned owner-authored free-text context events with deterministic local storage and CLI capture/list/revise flow.

R04 release lineage:

- release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release PR: #114
- release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-merge `main` CI: `34768452960` — SUCCESS
- closeout: [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)

The final R04 owner gate also proved the populated private runtime remained healthy at Alembic `0010_google_typed_normalization`, with WAL/FK enabled, `quick_check=ok` and zero foreign-key violations.

## Current focus

Current canonical checkpoint: `main @ 9ac6cb03e3cef2b7b5b321bcf88194c704df3bb2`; exact-main CI `36447735415` SUCCESS. Re-read current `main` from GitHub before every launch or integration.

Recently completed owner-value work now also includes the full Xiaomi screenshot workflow:

- #217 — one-command Owner screenshot import over the existing R01 photo/Xiaomi pipeline;
- #219 — repo-scoped Codex skill `health-weight-screenshot-import`;
- #221 — Owner-assisted structured extraction, so Codex/Work can inspect an attached screenshot and feed the strict R01 contract without a second external vision API;
- Owner live gate PASS: one older and one newer Xiaomi Home/S400 screenshot imported, exact NEW replay returned `DUPLICATE`, historical Weight evidence remained intact and no duplicate semantic measurement was created;
- #223 — routine Model evidence simplified to only `model` and `provider/client`.

**Immediate non-UI sequencing is now:**

1. **#214 — data readiness:** audit Stable historical coverage first, then enable/prove recurring daily `owner-refresh` through Windows Task Scheduler, then perform only justified bounded backfill.
2. **#215 — Context Capture operationalization:** add/read back the first real private Owner context note in Stable and begin using the already-accepted #177 contract.
3. **#148 — off-site disaster recovery:** once routine collection is boring, establish a protected off-machine recovery point and rehearse clean restore/provider reauthorization.
4. **#167 — privacy/history remediation:** still deferred by Owner decision while the repository remains public; revisit before treating long-term public exposure as safe.

#153 openScale/openScale-sync remains **optional compatibility work**, not a blocker for Weight accumulation. The real device/network/auth path reached Health-Check, but installed openScale-sync sends numeric `userId` while the current receiver requires a string. The accepted routine Weight path is now Xiaomi screenshot -> Codex/Work skill -> R01 photo pipeline -> Stable.

Separate non-actionable/deferred items:

- #126 — repository protection remains an Owner/capability decision; manual exact-SHA `checks: SUCCESS` remains the integration gate;
- #105 — canonical sleep switch remains NOT_ELIGIBLE until its evidence gate exists;
- #172/#189 — Period Brief / whole-product UI work remains deferred until the data-readiness slice above is complete or Owner explicitly reprioritizes.

The provider stack already supports bounded Garmin, Garmin Training, Google normal and wearables-sleep refresh. The main operational gap is no longer ingestion correctness; it is making collection automatic and proving what historical evidence actually exists.
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

For normal Owner operation, the accepted durable private profile is `D:\Garmin\HealthCheck-Stable`. It is persistent owner data, not a release-UAT sandbox; candidate UAT uses a disposable verified backup/restore clone.

The bounded manual Owner refresh (normal Garmin, Garmin Training, Google Health and the accepted wearables-sleep reconciliation layer) and its optional Task Scheduler setup are documented in [Owner Refresh](docs/OWNER_REFRESH.md). The command requires an already-established external runtime and does not create a new profile.

No health data, credentials, payloads, images, logs, database files or generated reports belong in the repository.

## CI and integration gate

Normal development should use targeted checks while iterating, then one exact candidate gate, one exact integration gate after acceptance, and an exact `main` gate when publishing canonical history.

The accepted final GitHub Actions verdict is the job named **`checks`**. It fail-closes over the mandatory quality evidence, exact Linux test-partition reconciliation and focused Windows evidence. The repository is currently public; #126 remains an explicit repository-settings/Owner decision. Regardless of server enforcement, Integrator process must not advance `main` unless `checks` succeeded on the exact SHA being promoted.

Do not reopen the performance campaign merely to save seconds. #124 closed the measured large serial stall; further CI optimization requires a new material measured bottleneck.

## Canonical documentation

- [Project Wiki / current state](docs/PROJECT_WIKI.md)
- [Product Vision](docs/PRODUCT_VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md)
- [CI Maintenance Closeout](docs/CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [Owner Refresh](docs/OWNER_REFRESH.md)
- [Verbose historical execution log](docs/EXECUTION_HISTORY.md)
- [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](docs/R05_RELEASE_CLOSEOUT.md)
- [Stable Owner Runtime Closeout](docs/STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
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
