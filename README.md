# Health-Check

Health-Check is a single-user, local-first personal health observatory. It keeps source evidence from several devices, computes reproducible analytics on a Windows laptop, and exposes the same evidence through a local dashboard and an AI/LLM interface.

It is not a SaaS product, workout planner, medical diagnostic system, or replacement for Garmin/Fitbit/Xiaomi daily apps.

## Product priorities

1. Weight and body composition.
2. Sleep.
3. Physical activity and fitness, especially cycling.
4. Recovery and general wellbeing.

Planned sources are Garmin Vivoactive 5, Google Fitbit Air through the applicable Google health-data interface, Xiaomi Body Composition Scale S400, and free-text life-context events. Laboratory results and other personal health documents are later work.

## Architecture in one minute

```text
provider payloads / photos / context
                |
                v
raw evidence -> typed source records -> versioned canonical selection
                                      |
                                      v
                         deterministic analytics
                                      |
                                      v
                  evidence packets and saved reports
                         /                    \
                  dashboard              read-only AI
```

- Runtime: Python 3.12+, FastAPI, SQLite in WAL mode, and a small Windows-first local service.
- Android: openScale and openScale-sync remain external GPL applications for the S400 path.
- Source-specific values are retained even when another source becomes canonical.
- Physical device, provider/input method, and measurement algorithm are separate identities.
- Xiaomi-app and openScale body-composition values are not silently joined into one curve.
- Analytics, coverage, and source agreement are calculated deterministically; every confidence value states whether it is rule-derived, model-reported, or human-confirmed and is never invented. The LLM explains compact structured evidence.
- Weekly, month-end, and annual reports share one report model and are rendered for dashboard, Telegram, and email.

## Current status

The R01 bootstrap runtime is in place. Domain features are intentionally added in later task branches. The approved vertical slice is **R01 — Weight & Body Composition**, which will build the reusable core, import historical Xiaomi screenshots with confirmation, accept the openScale-sync webhook contract, compute conservative weight/body-composition analytics, and provide a minimal dashboard.

R01 deliberately excludes Garmin ingestion, Fitbit ingestion, a custom Recovery Score, and full Telegram/email delivery.

## Local bootstrap

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

From a clean checkout, run:

```powershell
uv sync
uv run ruff check .
uv run pytest
```

The canonical Windows launcher prepares the external runtime, applies the checked-in Alembic migrations to SQLite with WAL/foreign-key pragmas, and starts the loopback listener on `127.0.0.1:8120`:

```powershell
.\scripts\start.ps1
```

Use `-DataDir C:\Temp\Health-Check` for a temporary runtime directory. Set `-EnableIngest` to start the separate liveness-only ingest listener on `-IngestHost`/`-IngestPort`; it has no UI, import, settings, or product routes. The same operations are directly callable with `uv run python -m healthcheck.cli prepare-runtime`, `migrate`, or `serve --app ui|ingest`.

Runtime state defaults to `%LOCALAPPDATA%\Health-Check` and can be overridden with `HEALTHCHECK_DATA_DIR`. No health data, provider credentials, payloads, images, logs, database, or generated reports belong in the repository.

### Real Xiaomi photo extraction

The normal UI uses the configured real-image extractor. Configure the endpoint
and model through environment variables before an explicit photo upload or
reprocess action:

```powershell
$env:HEALTHCHECK_PHOTO_VISION_BASE_URL = "https://vision.example.invalid/v1"
$env:HEALTHCHECK_PHOTO_VISION_MODEL = "your-vision-model"
$env:HEALTHCHECK_PHOTO_VISION_API_KEY = $env:VISION_PROVIDER_SECRET
```

The endpoint is OpenAI-compatible and receives one image plus a strict R01
photo schema request. The API key is never written to the repository,
runtime config, logs, or review UI. If the endpoint/model is not configured,
the import remains replayable and returns a sanitized
`extractor_not_configured` diagnostic; the synthetic fake is used only by
explicit tests and the synthetic demo helper. No provider call is made by
health checks or read-only pages.

## Canonical product documentation

- [Product Vision](docs/PRODUCT_VISION.md)
- [Final Architecture](docs/ARCHITECTURE.md)
- [R00 Final Architecture Audit](docs/audits/R00_FINAL_ARCHITECTURE.md)
- [R01 Implementation Spec](docs/R01_IMPLEMENTATION_SPEC.md)
- [Local profile backup and restore](docs/PROFILE_BACKUP.md)
- [Reference Projects and Reuse Strategy](docs/REFERENCE_PROJECTS.md)
- [Roadmap](docs/ROADMAP.md)
- [Decisions and Open Questions](docs/DECISIONS_AND_OPEN_QUESTIONS.md)
- [Backlog Ideas](docs/BACKLOG_IDEAS.md)

## Engineering workflow

All coding/review agents must start with [AGENTS.md](AGENTS.md).

- [Development Process](docs/DEVELOPMENT_PROCESS.md) — owner/integrator/worker flow, integration branches, local workspace roots, review/UAT and logging.
- [Model Routing](docs/MODEL_ROUTING.md) — task complexity and executor/reviewer recommendations.
- [Execution History](docs/EXECUTION_HISTORY.md) — durable history of implementations, failures, decisions and model attribution for retrospectives.
- Client-specific worker adapters live under `docs/agents/`.

## Safety and repository hygiene

Real health data, screenshots, databases, provider responses, tokens, credentials, reports, and laboratory documents must never be committed. Consumer wearables and BIA scales are observational tools, not clinical instruments; Health-Check must expose uncertainty and must not present associations as diagnoses or causation.

## License

Health-Check is licensed under the [MIT License](LICENSE). Reused donor code must still retain any attribution/notices required by its own license and be reviewed at the exact reused source commit.
