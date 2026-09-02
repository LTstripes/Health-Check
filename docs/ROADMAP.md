# Health-Check Roadmap

The roadmap follows usable vertical slices. Each release adds value on the Windows laptop without requiring enterprise infrastructure or discarding source evidence.

## R00 — Final architecture (complete in this branch)

Outputs:

- pinned donor/source and license review;
- final runtime, data, analytics, AI, and report boundaries;
- device/API uncertainty called out rather than guessed;
- exact R01 implementation and acceptance contract.

No product code or production data is part of R00.

## R01 — Weight & Body Composition vertical slice

Deliver the first useful product and the reusable Health-Check core:

- Python/FastAPI local application, configuration, SQLite WAL, and migrations;
- provider/device/input/algorithm provenance model;
- raw artifact/import records, typed scalar measurements, canonical rule v1, and coverage v1;
- batch Xiaomi screenshot/photo extraction into editable candidates with explicit confirmation;
- openScale-sync-compatible authenticated webhook and idempotent ingestion;
- raw weight, time-aware trend, robust rate, compatible body-composition series, estimated fat/lean mass, and recomposition view;
- minimal local dashboard with provenance, coverage, import history, and algorithm-discontinuity warnings;
- synthetic offline tests.

Garmin, Fitbit, Recovery Score, full Telegram/email delivery, and unrestricted AI/SQL are excluded.

## R02 — Garmin ingestion and backfill

- Start from the R00-reviewed `python-garminconnect` `0.3.12`/SHA pin; change it only if the live account spike supplies contrary evidence recorded in the R02 decision/ADR.
- User-assisted initial sign-in/MFA and durable token storage outside Git.
- Raw/source records, typed daily/sleep/activity/intraday entities, incremental sync, trailing-window resync, backfill, idempotency, and stream coverage.
- Preserve only metrics produced by this device/account; an available client method is not evidence of device capability.

## R03 — Garmin analytics and activity comparison

- Personal baselines, trends, percentiles, anomalies, and lag semantics.
- Cycling/session comparison with comparable fields and coverage.
- Garmin-specific score presentation with provenance and no medical overclaim.
- Expand dashboard and deterministic query service.

## R04 — Google Health / Fitbit ingestion

- Complete the live API-access and OAuth verification checklist first.
- Incremental sync/backfill for data types actually exposed to the account, preserving raw `list` source metadata separately from family reconcile/rollup results.
- Raw/source preservation, typed sleep/HR/HRV/RHR/SpO2 data where available, coverage, and token-health diagnostics.
- Record that proprietary Fitbit Sleep Score/Readiness is unavailable through the reviewed public API; if a future documented API exposes a provider-native score, keep it distinct from Health-Check/fettle-derived scores.

## R05 — Garmin/Fitbit agreement and canonical sleep

- Pair nights by wake date and compare each comparable metric separately.
- Bias, limits of agreement, MAE/RMSE, and secondary association statistics.
- First exploratory report after the documented minimum; a canonical-source change only after the stronger gate and stability checks.
- Versioned canonical sleep rule and visible per-source overlays.

## R06 — Context, Telegram, and read-only AI tools

- Low-friction free-text event/exposure capture through dashboard and Telegram.
- Suggested vs confirmed dates/tags while preserving raw wording.
- Typed, read-only analytic/MCP tools that return compact evidence packets.
- Natural-language investigation over deterministic results; no direct database mutation or raw-series mathematics by the LLM.

## R07 — Saved reports and delivery

- One deterministic report/evidence model for Sunday, month-end, and annual reviews.
- Dashboard archive and renderers.
- Telegram and email notifier adapters with independent delivery retry/audit.
- Coverage-aware conclusions and reproducible report revisions.

## R08 — Deeper personal analytics and experiments

- Event-aligned and matched-control context analysis.
- Lagged comparisons and effect sizes with explicit sample/coverage gates.
- Structured n-of-1 experiments.
- Consider, but do not presume, a transparent Recovery Score only if accumulated data demonstrates an unmet need.

## R09 — Laboratory and document data

- Original document provenance outside Git.
- Candidate extraction, human confirmation, normalized analytes/units/reference ranges, and longitudinal views.
- Combined lab, wearable, context, and body-composition evidence without diagnosis.

## R10 — Optional advanced work

- Richer timezone/travel semantics if real data requires it.
- Additional providers or a mobile application only when they solve a demonstrated need.
- Advanced AI workflows, secure remote access, or additional notification channels.
- Optional Obsidian or food-diary summary import.

## Release gates that apply throughout

- No real personal data, screenshots, tokens, or databases in Git or CI fixtures.
- Every ingestion path is idempotent and reports coverage/failures.
- Source values survive canonical selection and reprocessing.
- Derived values name their algorithm/version and input provenance.
- Missing values remain missing, not zero.
- New donor code requires license review and attribution at the exact reused commit.
- A release must work locally on Windows and its automated tests must run without live credentials.
