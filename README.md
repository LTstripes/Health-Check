# Health-Check

Health-Check is a single-user, local-first personal health observatory for a Windows laptop. It preserves source evidence from personal devices, turns it into reproducible deterministic analytics, and exposes the same evidence through local dashboards, deterministic period reviews, Garmin training/recovery views and later bounded AI tools.

It is not a SaaS product, medical diagnostic system, workout planner, or replacement for Garmin / Google Health / Xiaomi daily apps.

## What is available in canonical main

Canonical source: `main`. Repository integration and Owner-local deployment are separate.

- **R01 — Weight & Body Composition:** Xiaomi screenshot/photo import, openScale/openScale-sync contract, provenance, canonical selection, conservative body-composition analytics, local dashboard, backup/restore. Screenshots are the accepted operational Weight path; optional openScale compatibility #153 is closed as not planned.
- **R02 — Garmin ingestion/backfill:** protected owner session reuse, typed Garmin persistence, bounded incremental sync, resumable historical backfill, coverage/checkpoints and exact-rerun idempotency.
- **R03 — Garmin analytics/dashboard:** deterministic personal baselines/trends, activity comparison, lagged associations, provider-native metric presentation, reproducible evidence manifests and owner-facing read-only Garmin UI.
- **R04 — Google Health ingestion:** Google Health API v4 OAuth, protected session storage, source-aware typed persistence, bounded incremental sync/backfill/refresh, coverage/checkpoints, privacy-safe diagnostics and live owner verification.
- **R05 — Garmin / Google wearable sleep agreement:** pairing, comparable projection, immutable agreement runs, statistics/gates, exploratory owner report; Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.
- **Post-R05 Owner Runtime & Period Brief:** one durable private Owner profile, verified backup/restore UAT clones, one-command Garmin/Google refresh, deterministic Period Brief correctness/UI closeout and historical Owner UAT.
- **Garmin Training & Recovery:** live-discovered Garmin-native Training Status/load/ACWR, Load Focus, Training Readiness/Recovery and activity Training Effect/load are persisted, included in normal owner refresh and shown read-only.
- **Context capture v0:** revisioned owner-authored free-text context events with deterministic local storage and CLI capture/list/revise flow.
- **Owner screenshot workflow:** Xiaomi screenshot -> repo skill `health-weight-screenshot-import` -> Owner-assisted structured extraction -> existing R01 photo pipeline -> Stable; OLD/NEW/exact-replay Owner gate PASS (#217/#219/#221). #240 adds durable visible/Owner-attested/workflow-profile/unknown metadata origins and date-only attestation without rewriting legacy provenance.
- **Safety/reliability:** screenshot algorithm identity (#226), coherent compound reads (#227), privacy test oracle (#233), Windows cleanup/CI provenance (#181/#243), reviewable changed-sidecar corrections (#229), UI Host/Origin validation (#244) and non-Windows Google AEAD v2 with unchanged Windows DPAPI (#247).
- **Automatic selected-stream collection:** #214 accepted an Owner-reported automatic/logon run with a complete successful report and Task Scheduler result 0; #238 subsequently completed explicit collection-policy/freshness semantics.
- **Owner UI / post-redesign Owner flow:** #189 stages 1–7 are integrated and closed. Subsequent fixes delivered Data persistence (#290), Overview/Sleep evidence semantics (#291), Weight v2 (#293), source-explicit Google daily vitals (#297), Owner clarity cleanup (#292) and deterministic Linux CI environment pinning (#302). Owner-local deployment/UAT on `main @ e806d81fc38093931113ab0790cab120cacf8c10` confirmed the combined product on real Stable data and produced bounded follow-ups #305–#309 rather than reopening #189.
- **Period Brief output/performance:** explicit `period-brief --format json|text` preserves default behavior and packet identity (#248). Measured bounded backend reads improve the full-size synthetic build from 55.108 s to 6.520 s with equal packets/hashes, without a migration, new index or cache (#283); this is not an Owner Stable timing promise.

R04 release lineage:

- release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release PR: #114
- release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-merge `main` CI: `34768452960` — SUCCESS
- closeout: [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)

The final R04 owner gate proved the populated private runtime remained healthy at Alembic `0010_google_typed_normalization`, with WAL/FK enabled, `quick_check=ok` and zero foreign-key violations. This is historical R04 evidence, not the current migration-head claim.

## Current focus — 2026-10-06

The main product track is the **post-redesign Owner iteration** created by the real-data UAT on `main @ e806d81fc38093931113ab0790cab120cacf8c10`:

- #305 Data v2 — diagnose the failing persisted-source freshness check and simplify photo-import history/flow;
- #306 Weight v3 — readable time axes and clearer composition-series spans;
- #307 Overview v2 — useful Garmin/Google summary without silent pooling;
- #308 Sleep v2 — one nightly row plus Garmin / Google / Compare views;
- #309 Activity v2 — honest Garmin-only scope today, real tennis labels and usable two-session comparison.

#305 is the first functional blocker and is already assigned. #306 is structurally independent enough to work in parallel if shared CSS ownership stays explicit; #307/#308/#309 should follow sequentially because they can overlap common Owner presentation/templates.

Existing #294 Settings & Context, #295 measured UI performance and #298 Garmin stress diagnosis remain valid follow-ups after the current presentation/data wave. #228 stays parked, #167 Owner-deferred, #126 an Owner/admin required-check decision and #105 NOT_ELIGIBLE. Dependabot PRs #270/#271 remain separate review proposals, never housekeeping merges.

See the [2026-10-06 Owner UAT closeout](docs/OWNER_UAT_FOLLOWUP_2026-10-06.md), [Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md), [roadmap](docs/ROADMAP.md), [Owner UI routes and visual contract](docs/OWNER_UI_SHELL.md), [CI optimization closeout](docs/CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md) and [Owner machine layout](docs/OWNER_MACHINE_LAYOUT.md). GitHub merges still do not update the local Owner checkout or restart its runtime.

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

R04 uses Google Health API v4 only and exactly the accepted read scopes for sleep and health metrics/measurements. OAuth uses a Google Web Application client with a fixed registered loopback callback; protected client/token/session state lives only in the external runtime. Windows protection remains DPAPI. Non-Windows local protection now writes purpose-bound AEAD v2, reads authenticated legacy v1 and migrates only on normal writes; pure reads do not create missing keys (#247).

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

For normal Owner operation, the durable private profile is `D:\HealthCheck\stable`; the clean control checkout is `D:\HealthCheck\main`; disposable private UAT/recovery state belongs under `D:\HealthCheck\uat`; Owner-local wrappers live in `D:\HealthCheck\ops`. New agent work uses `D:\HealthCheck\workspaces\<client>\<issue-or-task>`. See [Owner machine layout](docs/OWNER_MACHINE_LAYOUT.md) for the canonical roles and cleanup lifecycle. GitHub merges still do not update the local checkout or restart its processes automatically.

[Owner Refresh](docs/OWNER_REFRESH.md) documents the local selected-stream runner, Scheduler controls and unchanged bounded CLI. The command requires an already-established external runtime and does not create a new profile. Never switch/pull code while the Owner refresh or dependent application processes are using that checkout.

No health data, credentials, payloads, images, logs, database files or generated reports belong in the repository.

## CI and integration gate

Normal development uses targeted checks while iterating, then required exact-candidate, PR integration and post-main gates. Documentation-only changes follow the existing classifier policy; a Markdown filename does not by itself authorize skipping checks.

The accepted final GitHub Actions verdict is **`checks`**. It fail-closes over mandatory quality evidence, exact Linux test-partition reconciliation and focused Windows evidence. #302 pins the Linux evidence-producing/consuming path (`quality`, the three Linux lanes and `checks`) to one exact CPython patch so hosted-runner patch rollout cannot create a false cross-job environment mismatch; the equality gate itself remains strict. The repository is public at this checkpoint; #126 remains an explicit repository-settings/Owner decision. Regardless of server enforcement, Integrator process must not advance `main` unless `checks` succeeded on the exact tree/SHA being promoted under the accepted PR contract.

#181/#243 preserve fail-closed ownership, CreationTime identity and same-attempt completeness. Partial reruns are not complete acceptance evidence; historical failures remain failures. Dependency changes additionally require the separate dependency-audit gate. See [Development Process](docs/DEVELOPMENT_PROCESS.md).

## Canonical documentation

- [Project Wiki / current state](docs/PROJECT_WIKI.md)
- [Owner UAT follow-up — 2026-10-06](docs/OWNER_UAT_FOLLOWUP_2026-10-06.md)
- [Product Vision](docs/PRODUCT_VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Owner UI routes and visual contract](docs/OWNER_UI_SHELL.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md)
- [Owner Machine Layout](docs/OWNER_MACHINE_LAYOUT.md)
- [Owner Refresh](docs/OWNER_REFRESH.md)
- [Owner Refresh Closeout](docs/OWNER_REFRESH_CLOSEOUT_2026-10-01.md)
- [Owner Screenshot Import](docs/OWNER_WEIGHT_SCREENSHOT_IMPORT.md)
- [Verbose historical execution log](docs/EXECUTION_HISTORY.md)
- [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](docs/R05_RELEASE_CLOSEOUT.md)
- [Stable Owner Runtime Closeout](docs/STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- [CI Maintenance Closeout](docs/CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [CI Optimization Closeout — 2026-10-04](docs/CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md)
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
