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
- **Owner screenshot workflow:** Xiaomi screenshot -> repo skill `health-weight-screenshot-import` -> Owner-assisted structured extraction -> existing R01 photo pipeline -> Stable; OLD/NEW/exact-replay Owner gate PASS (#217/#219/#221).
- **Latest safety/reliability work:** Windows limited-encoding Period Brief stdout (#203), Xiaomi screenshot algorithm identity (#226), coherent compound reads (#227), Garmin Training privacy-oracle repair (#233), Windows cleanup/CI provenance hardening (#181), and reviewable changed-sidecar corrections with duplicate-safe replay (#229).

R04 release lineage:

- release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release PR: #114
- release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-merge `main` CI: `34768452960` — SUCCESS
- closeout: [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)

The final R04 owner gate also proved the populated private runtime remained healthy at Alembic `0010_google_typed_normalization`, with WAL/FK enabled, `quick_check=ok` and zero foreign-key violations.


## Current focus — 2026-10-01

Canonical product checkpoint: `main @ ac1df6dd5bdcfdc57c56a9b531e89a108a658d2b`; exact-main CI `36818997839` SUCCESS, including Windows smoke and final `checks`. Re-read live GitHub state before later launch/integration; this is dated evidence, not a permanent branch pointer.

**Completed in the current reliability/correction slice:**
- #233 / PR #234: collision-safe Garmin Training privacy test oracle, test-only;
- #181 / PR #236 + follow-up PR #237: fail-closed Windows process-tree cleanup, CreationTime-proven post-termination PID reuse, exact exit-255 transcript handling and full-rerun-only CI provenance; the first post-merge escape was preserved and repaired before final green main;
- #229 / PR #235: changed Owner-assisted screenshot sidecars now stage reviewable correction evidence, reject without semantic mutation, confirm through existing revision/supersession history, and replay idempotently; SQLite signed-zero fingerprint stability was independently found and repaired before merge.

Earlier #203/#226/#227, source freshness #147/#191/#193 and Google HR performance/reliability #199/#206/#207/#212 remain complete.

**Immediate non-UI work:**
1. **#214 — automatic collection proof:** one untouched genuine scheduled/logon Owner refresh still needs final JSON/task-result/freshness proof.
2. **#215 — first real Context note:** persist/read back one private Owner-authored note in Stable; no fabricated diary content.
3. **#148 — protected off-site recovery:** next large durability/security track once daily collection is proven boring.

#228 cross-image semantic identity remains research-accepted/implementation-parked; #153 openScale numeric-`userId` compatibility is optional rather than a Weight prerequisite. #172/#189 UI remains deferred by Owner choice. Google high-frequency `heart_rate` remains OFF by default only in the local Ops runner; existing history is retained and no broad HR backfill is implied.

There are **11 open issues** at this checkpoint, including ongoing model journal #210, Owner/capability gate #126, Owner-deferred #167 and NOT_ELIGIBLE #105. See the [roadmap](docs/ROADMAP.md#current-backlog--2026-10-01), [current execution history](docs/EXECUTION_HISTORY_CURRENT.md) and [model journal](docs/MODEL_BENCHMARK.md).

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

For normal Owner operation, the accepted durable private profile is `D:\Garmin\HealthCheck-Stable`. It is persistent owner data, not a release-UAT sandbox; candidate UAT uses a disposable verified backup/restore clone. The Owner operation checkout is `D:\Garmin\HealthCheck-Owner-Main`; GitHub merges do not automatically update that local checkout or restart its processes.

[Owner Refresh](docs/OWNER_REFRESH.md) documents the local selected-stream runner, Scheduler controls and the unchanged bounded CLI. The command requires an already-established external runtime and does not create a new profile.

No health data, credentials, payloads, images, logs, database files or generated reports belong in the repository.

## CI and integration gate

Normal development should use targeted checks while iterating, then one exact candidate gate, one exact integration gate after acceptance, and an exact `main` gate when publishing canonical history.

The accepted final GitHub Actions verdict is the job named **`checks`**. It fail-closes over the mandatory quality evidence, exact Linux test-partition reconciliation and focused Windows evidence. The repository is currently public; #126 remains an explicit repository-settings/Owner decision. Regardless of server enforcement, Integrator process must not advance `main` unless `checks` succeeded on the exact SHA being promoted.

#181 is complete: Windows cleanup remains fail-closed, post-termination PID reuse requires CreationTime evidence, and partial reruns cannot silently mix attempts. Separate performance optimization still requires a material measured bottleneck.

## Canonical documentation

- [Project Wiki / current state](docs/PROJECT_WIKI.md)
- [Product Vision](docs/PRODUCT_VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md)
- [Model Evidence Journal](docs/MODEL_BENCHMARK.md)
- [CI Maintenance Closeout](docs/CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [Owner Refresh](docs/OWNER_REFRESH.md)
- [Owner Screenshot Import](docs/OWNER_WEIGHT_SCREENSHOT_IMPORT.md)
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
