# Health-Check

Health-Check is a single-user, local-first personal health observatory for a Windows laptop. It preserves source evidence from personal devices, turns it into reproducible deterministic analytics, and exposes the same evidence through local dashboards, deterministic period reviews, Garmin training/recovery views and planned bounded AI tools.

It is not a SaaS product, medical diagnostic system, workout planner, or replacement for Garmin / Google Health / Xiaomi daily apps.

## What is available in canonical main

Canonical source: `main`. Repository integration, Owner-local deployment and human UAT are separate.

- **R01 — Weight & Body Composition:** Xiaomi screenshot/photo import, openScale/openScale-sync contract, provenance, canonical selection, conservative body-composition analytics, local dashboard, backup/restore. Screenshots are the accepted operational Weight path; optional openScale compatibility #153 is closed as not planned.
- **R02 — Garmin ingestion/backfill:** protected owner session reuse, typed Garmin persistence, bounded incremental sync, resumable historical backfill, coverage/checkpoints and exact-rerun idempotency.
- **R03 — Garmin analytics/dashboard:** deterministic personal baselines/trends, activity comparison, lagged associations, provider-native metric presentation, reproducible evidence manifests and owner-facing read-only Garmin UI.
- **R04 — Google Health ingestion:** Google Health API v4 OAuth, protected session storage, source-aware typed persistence, bounded incremental sync/backfill/refresh, coverage/checkpoints, privacy-safe diagnostics and historical live owner verification.
- **R05 — Garmin / Google wearable sleep agreement:** pairing, comparable projection, immutable agreement runs, statistics/gates, exploratory owner report; Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.
- **Post-R05 Owner Runtime & Period Brief:** one durable private Owner profile, verified backup/restore UAT clones, one-command Garmin/Google refresh, deterministic Period Brief correctness/UI closeout and historical Owner UAT.
- **Garmin Training & Recovery:** live-discovered Garmin-native Training Status/load/ACWR, Load Focus, Training Readiness/Recovery and activity Training Effect/load are persisted, included in normal owner refresh and shown read-only.
- **Context Capture v0:** revisioned owner-authored free-text context events with explicit dates/instants/intervals and CLI capture/list/revise. The secondary `/context` portal (#294 Stage A) and bounded standalone Weight/Garmin-scalars/current-Context export (#341 Stage A) are integrated. Durable Owner UAT, manual private export and ChatGPT transport are separate gates.
- **Owner screenshot workflow:** Xiaomi screenshot -> repo skill `health-weight-screenshot-import` -> Owner-assisted structured extraction -> existing R01 photo pipeline -> Stable; OLD/NEW/exact-replay Owner gate PASS (#217/#219/#221). #240 adds durable visible/Owner-attested/workflow-profile/unknown metadata origins and date-only attestation without rewriting legacy provenance.
- **Safety/reliability:** screenshot algorithm identity (#226), coherent compound reads (#227), privacy test oracle (#233), Windows cleanup/CI provenance (#181/#243), reviewable changed-sidecar corrections (#229), UI Host/Origin validation (#244) and non-Windows Google AEAD v2 with unchanged Windows DPAPI (#247).
- **Automatic selected-stream collection:** #214 accepted an Owner-reported automatic/logon run with a complete successful report and Task Scheduler result 0; #238 subsequently completed explicit collection-policy/freshness semantics. That historical proof is not a promise of current provider availability.
- **Owner UI A+ / desktop:** the approved warm shell and real Overview (#322/#326/#328), source-only Sleep v3 including unpaired account observations (#317), compact Activity A/B (#318), five-recent-session journal/history disclosure (#335), sparse Overview Weight-chart clarity (#334) and compact source attention (#333) are integrated. Desktop 1024px+ only (#321); all source/date/coverage and privacy boundaries remain. Real Owner feedback is partial, not blanket acceptance.
- **Period Brief output/performance:** explicit `period-brief --format json|text` preserves default behavior and packet identity (#248). Historical #283 synthetic optimization and #295 indexed Google freshness reads are integrated. Current real-clone Overview latency still needs work; engineering speed evidence is not a claim that the Owner page is fast.

R04 release lineage:

- release candidate: `406f4044ffb0d010c64a8635d402016ae916fc5a`
- release PR: #114
- release merge: `bb5776e98d259cb6256c95bd49d400dc1238af61`
- post-merge `main` CI: `34768452960` — SUCCESS
- closeout: [R04 Release Closeout](docs/R04_RELEASE_CLOSEOUT.md)

The final R04 owner gate proved the populated private runtime remained healthy at Alembic `0010_google_typed_normalization`, with WAL/FK enabled, `quick_check=ok` and zero foreign-key violations. This is historical R04 evidence, not the current migration-head claim.

## Current focus — 2026-10-11 Owner UAT and controlled Stable handoff

Latest accepted **product** (before a docs-only checkpoint):
[`main fa36dc5b6402fe6e6e166091002faf4af1ec0993`](https://github.com/LTstripes/Health-Check/commit/fa36dc5b6402fe6e6e166091002faf4af1ec0993).
[Separate post-main CI 38164560091](https://github.com/LTstripes/Health-Check/actions/runs/38164560091)
**SUCCESS attempt 1**, all mandatory Linux/Windows/quality/final checks.
GitHub merges and docs commits do not deploy into Stable.

Now engineered and merged: one full-history Weight+composition view #375,
normal Google sleep-source resolution #342/#343, dated RHR reader and first
Overview consumer #376, more readable Statistics source labels #347,
bounded trailing365/calendar-year/YTD Statistics #380, and **saved Garmin**
daily Steps projection/read-only window/Statistics display #377
(PRs #389–#391). Already delivered #344 Overview graph polish and #345
saved-session Activity detail must **not** be relaunched. #319 calories/BMR
remain meaning-blocked; Google Steps are not yet acquired.

The Owner ran the new UI against an **isolated 2026-10-08 saved-data clone**,
not current Stable: routes and tested process/profile identity PASS, fresh full
DB integrity UNVERIFIED. Observed `/brief` first/repeat 23.098/9.470 seconds
with uncontrolled cache; the responsiveness gate remains open. Human
[#330 UAT is PARTIAL](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6113161066).
Old copied Garmin reauth/Google failures do not establish current provider
health, and successful CI does not imply current data collection.

Owner requests recorded without duplicate implementation: #392 exact Google
Steps acquisition/storage contract; #395 attach the already accepted Garmin
offline daily Steps projector to routine successful persisted acquisition;
#393 source/day-correct period-mean RHR instead of verbose card; #394 truthful
Body Battery daily-max vs saved snapshot semantics; #379 human Weight table
precision/dates; #347 provider-first source selection; #294 primary Comments
navigation/one IANA zone chooser; #305 concise saved-value versus refresh state.
#380 all-history remains separate; #345 conceptual redesign deferred.

See the [2026-10-11 Owner UAT checkpoint](docs/OWNER_UAT_CHECKPOINT_2026-10-11.md),
[current backlog](docs/ROADMAP.md#current-backlog),
[Current Execution History](docs/EXECUTION_HISTORY_CURRENT.md),
[Owner UI](docs/OWNER_UI_SHELL.md) and
[Owner Machine Layout](docs/OWNER_MACHINE_LAYOUT.md).
A controlled Stable update is now worth planning, **not already executed**:
Owner-local backup+verify+restored-clone rehearsal, runtime/process locks,
rollback readiness and a separately assigned Codex deployment operation
must precede any durable-profile migration/start. No unauthorized provider
refresh, typed replay, private data write or scheduler change follows
from this documentation reconciliation.

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

Source identity remains conservative. Query mode and `dataSourceFamily` are acquisition context, not device identity. Broader wearable-family evidence must not be labelled Fitbit-device evidence without explicit metadata. Source-only account observations (#317) do not loosen legacy device-agreement or canonical-switch gates.

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
The startup script prepares/migrates its selected runtime; it is not a read-only
inspection command. Candidate UAT uses the explicitly verified disposable clone,
not Stable as a scratch target.

For normal Owner operation, the durable private profile is `D:\HealthCheck\stable`; the clean control checkout is `D:\HealthCheck\main`; disposable private UAT/recovery state belongs under `D:\HealthCheck\uat`; Owner-local wrappers live in `D:\HealthCheck\ops`. New agent work uses `D:\HealthCheck\workspaces\<client>\<issue-or-task>`. See [Owner machine layout](docs/OWNER_MACHINE_LAYOUT.md) for the canonical roles and cleanup lifecycle. GitHub merges still do not update the local checkout or restart its processes automatically.

[Owner Refresh](docs/OWNER_REFRESH.md) documents the local selected-stream runner, Scheduler controls and unchanged bounded CLI. The command requires an already-established external runtime and does not create a new profile. Never switch/pull code while the Owner refresh or dependent application processes are using that checkout.

No health data, credentials, payloads, images, logs, database files or generated reports belong in the repository. Routine comments added to a disposable clone will not automatically become durable Stable notes; #294's real rollout must make the target explicit.

## CI and integration gate

Normal development uses targeted checks while iterating, then required exact-candidate, PR integration and post-main gates. Documentation-only changes follow the existing classifier policy; a Markdown filename does not by itself authorize skipping checks.

The accepted final GitHub Actions verdict is **`checks`**. It fail-closes over mandatory quality evidence, exact Linux test-partition reconciliation and focused Windows evidence. #302 pins the Linux evidence-producing/consuming path (`quality`, the three Linux lanes and `checks`) to one exact CPython patch so hosted-runner patch rollout cannot create a false cross-job environment mismatch; the equality gate itself remains strict. #126 remains an explicit repository-settings/Owner decision. Regardless of server enforcement, Integrator process must not advance `main` unless `checks` succeeded on the exact tree/SHA being promoted under the accepted PR contract.

#181/#243 preserve fail-closed ownership, CreationTime identity and same-attempt completeness. Partial reruns are not complete acceptance evidence; historical failures remain failures. Dependency changes additionally require the separate dependency-audit gate. Dependabot #270/#271 are not documentation-housekeeping merges. See [Development Process](docs/DEVELOPMENT_PROCESS.md).

## Canonical documentation

- [Project Wiki / current state](docs/PROJECT_WIKI.md)
- [Owner UAT follow-up — 2026-10-06, historical](docs/OWNER_UAT_FOLLOWUP_2026-10-06.md)
- [Product Vision](docs/PRODUCT_VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap / current backlog](docs/ROADMAP.md)
- [Owner UI routes and visual contract](docs/OWNER_UI_SHELL.md)
- [Context Capture — delivered v0 and secondary portal adapter](docs/CONTEXT_CAPTURE.md)
- [Backlog Ideas / promoted work](docs/BACKLOG_IDEAS.md)
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
