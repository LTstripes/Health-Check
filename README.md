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
- **Latest safety fixes:** Windows limited-encoding Period Brief stdout (#203), Xiaomi screenshot auto-confirm algorithm identity (#226), coherent SQLite/ORM snapshots for compound Weight and Period Brief reads (#227).

R04 release lineage:

- release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release PR: #114
- release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-merge `main` CI: `34768452960` — SUCCESS
- closeout: [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)

The final R04 owner gate also proved the populated private runtime remained healthy at Alembic `0010_google_typed_normalization`, with WAL/FK enabled, `quick_check=ok` and zero foreign-key violations.

## Current focus — 2026-09-30

Accepted product checkpoint before this documentation refresh: `main @ f6939f531d4384e28fa9bd65fce59b498a0e6032`; exact-main CI `36634392128` SUCCESS, including Windows smoke and final `checks`. Re-read current GitHub main/CI before launch or integration; this is a dated product checkpoint, not a permanent branch pointer.

**Completed:** #203 via PR #225; #226 via PR #230; #227 via PR #231 after one independent-review remediation round; #233 via PR #234 repaired the collision-prone Garmin Training privacy test oracle without production changes. Source freshness #147/#191/#193 and Google HR performance/reliability #199/#206/#207/#212 are also complete.

**Current non-UI work:**

1. **#229 — candidate awaiting an isolated independent semantic review:** candidate `532a069c2b1253b4a3ce88c56f8d3b843f6b2f05` has green exact-head CI. The first Sol 6.1 High review attempt stopped at preflight because its review runtime inventory was not isolated; that is `BLOCKED / INCONCLUSIVE`, not a semantic defect or ACCEPT.
2. **#214 — automatic collection proof:** historical inventory and manual refresh passed; Task Scheduler is configured for 10:30 plus Owner logon, including battery operation. One untouched automatic run with final report/result remains unproven.
3. **#215 — first real Context note:** add/read back one private Owner-authored note using the existing contract. No invented diary entry and no daily-note requirement.
4. **#181 — Windows smoke / partial-rerun reliability:** recent cleanup exit-255 failures are retained evidence; green later runs do not close the defect. Diagnose without weakening cleanup or the final gate.
5. **#148 — protected off-site recovery:** design the protection/publication/retention contract, then implementation/security review and a separate clean restore rehearsal. Local backup alone does not satisfy it.

The Owner chose **Google high-frequency `heart_rate` OFF by default in the local Ops runner**, with a reversible flag. Garmin HR, other Google streams and fixed wearables-sleep reconciliation remain enabled. Existing Google HR history is retained; its historical gap is intentionally not a backfill target while disabled. The repository's bare CLI default is unchanged and includes HR. See [Owner Refresh](docs/OWNER_REFRESH.md).

Weight accumulation does not depend on #153: openScale is optional compatibility work after the screenshot route was live-proven. #228 Phase 1 research is accepted, but cross-image event dedup implementation is parked until trustworthy source-event identity exists; date/value similarity must not auto-merge measurements.

There are **13 open issues** at this checkpoint, including #210's ongoing model journal, deferred #172/#189 UI, Owner-deferred #167 privacy rewrite, #126 protection/capability decision and #105 NOT_ELIGIBLE. The [roadmap](docs/ROADMAP.md#current-backlog--2026-09-30) distinguishes actionable work from parked items. No new UI/AI/Recovery Score track is launched by this handoff.

[Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md) and the [model table](docs/MODEL_BENCHMARK.md) record actual outcomes and Owner-confirmed model labels without inventing missing runtime versions.

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

#181 is reliability work for demonstrated Windows cleanup and partial-rerun evidence failures, not an invitation to retry until green. Separate performance optimization still requires a material measured bottleneck.

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
