# Health-Check Roadmap

The roadmap follows usable vertical slices. Each release adds value on the Windows laptop without requiring enterprise infrastructure or discarding source evidence.

Future ideas that are intentionally not committed to a release yet live in [Backlog Ideas](BACKLOG_IDEAS.md).

**Current planning focus:** R01 is released to stable `main`. Complete the bounded post-R01 consolidation/R01.1 safety follow-ups, then create a fresh `integration/r02-garmin` from canonical `main` and reconstruct the already accepted Garmin contract/live-spike layers before production R02 ingestion work begins.

## R00 — Final architecture (complete)

Outputs:

- pinned donor/source and license review;
- final runtime, data, analytics, AI, and report boundaries;
- device/API uncertainty called out rather than guessed;
- exact R01 implementation and acceptance contract.

No product code or production data is part of R00.

## R01 — Weight & Body Composition vertical slice (released)

Delivered the first useful product and the reusable Health-Check core:

- Python/FastAPI local application, configuration, SQLite WAL, and migrations;
- provider/device/input/algorithm provenance model;
- raw artifact/import records, typed scalar measurements, canonical rule v1, and coverage v1;
- batch Xiaomi screenshot/photo extraction into editable candidates with explicit confirmation;
- openScale-sync-compatible authenticated webhook and idempotent ingestion;
- raw weight, time-aware trend, robust rate, compatible body-composition series, estimated fat/lean mass, and recomposition view;
- minimal local dashboard with provenance, coverage, import history, and algorithm-discontinuity warnings;
- synthetic offline tests.

The mandatory R01 owner gate passed on integrated candidate `058639919c4b5e13c420e7c016d292843afa10dc`. Final closeout evidence, including owner-assisted historical Xiaomi migration and explicit UNVERIFIED live-device/provider items, is recorded in [R01 Release Closeout](R01_RELEASE_CLOSEOUT.md).

R01 release PR #40 merged to stable `main`; R01 tracker #13 is closed. Garmin, Fitbit, Recovery Score, full Telegram/email delivery, and unrestricted AI/SQL remain outside R01.

### Post-R01 bounded follow-ups

Before the main R02 implementation wave:

- integrate the accepted safe local profile backup/restore tooling (#27) after revalidation on current `main`;
- change default local ports to owner-approved `8120/8121` (#32), preserving explicit overrides and route isolation;
- optionally integrate the accepted dashboard visual polish (#26) after current-main revalidation;
- complete the post-release documentation/lineage consolidation tracked by #41.

These are not reasons to reopen R01; they are post-release hardening/quality follow-ups.

## R02 — Garmin ingestion and backfill (next active release)

Production objective:

- Start from the R00-reviewed `python-garminconnect` `0.3.12`/SHA pin; change it only if concrete live evidence requires an explicit decision.
- User-assisted initial sign-in/MFA and durable protected token/session storage outside Git.
- Raw/source records, typed daily/sleep/activity/intraday entities, incremental sync, trailing-window resync, backfill, idempotency, and stream coverage.
- Preserve only metrics produced/evidenced by this device/account; an available client method is not evidence of device capability.

Accepted preparation already exists on held/diverged task branches:

- #28 — capability inventory + synthetic contract fixtures: accepted;
- #29 — normalization/idempotency/time/source contract: accepted;
- #30 — Garmin persistence/raw-observation contract: accepted;
- #31 — owner-assisted Windows auth/session and bounded live capability spike: owner live objective achieved;
- #36 — live response-shape/capability reconciliation: owner rerun PASS.

These branches must **not** be merged directly into current `main`. After post-R01 consolidation, create fresh `integration/r02-garmin` from the then-current canonical `main` and reconstruct accepted semantics in order `#28 -> #29 -> #30 -> #31 -> #36`, preserving the real accepted #28 lineage and rerunning exact-head CI/migration/privacy checks. Only after that foundation is canonical should production sync/backfill orchestration start.

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

## R09 — Laboratory, medication, supplement, and document data

- Original laboratory/medical document provenance outside Git.
- Candidate extraction, human confirmation, normalized analytes/units/reference ranges, and longitudinal views.
- Medication/vitamin/supplement exposure timeline with dose, unit, start/end/change events, provenance, and optional adherence observations without a mandatory daily diary.
- Lab-guided interpretation that can relate confirmed analytes to medication/supplement periods and relevant wearable/body-composition trends.
- Practical follow-up suggestions and questions to discuss with a clinician/pharmacist, without autonomous diagnosis or prescription changes.
- Combined lab, medication/supplement, wearable, context, and body-composition evidence without causal overclaiming.

If medication/supplement scope makes R09 too large, split it into a follow-up release while keeping the shared exposure/event model.

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
