# Health-Check Roadmap

The roadmap follows usable vertical slices. Each release adds value on the Windows laptop without requiring enterprise infrastructure or discarding source evidence.

Future ideas that are intentionally not committed to a release yet live in [Backlog Ideas](BACKLOG_IDEAS.md).

**Current planning focus:** R01 and R02 are released to stable `main`. Before R03 analytics begins, complete pre-R03 hardening in order: #56 collection reconciliation/version-aware reprocessing, then #55 metric/time/analytic-coverage and reproducible evidence-manifest contract. After those two foundations are accepted, start deterministic Garmin analytics and activity comparison in R03.

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

R01 release PR #40 merged to stable `main`; R01 tracker #13 is closed. Garmin, Fitbit, Recovery Score, full Telegram/email delivery, and unrestricted AI/SQL remained outside R01.

### Post-R01 bounded follow-ups

After R01 release, accepted bounded hardening/polish work was revalidated against the then-current stable line rather than merged blindly from stale branches. Those follow-ups are historical and do not reopen R01.

## R02 — Garmin ingestion and backfill (released)

R02 delivered the production Garmin acquisition layer:

- owner-assisted initial sign-in/MFA and durable protected token/session storage outside Git;
- capability contracts that distinguish available client methods from actual owner device/account evidence;
- raw/source payload observations with immutable acquisition and normalization provenance;
- typed daily/sleep/activity/intraday normalization and persistence;
- incremental sync with bounded trailing-window resync;
- bounded historical backfill with request caps, resumability and coverage-driven skipping;
- explicit `present`, `confirmed_empty`, `unknown` and failure/unavailable semantics;
- historical/incremental checkpoint isolation;
- exact completed-rerun idempotency and privacy-safe owner diagnostics.

Historical lineage was deliberately reconstructed onto a fresh `integration/r02-garmin` after R01 release rather than merging the earlier diverged preparation stack directly. The accepted preparation layers were #28, #29, #30, #31 and #36.

The owner release gate #52 found several real-provider convergence defects that green synthetic CI had not proven. Focused repair rounds #53, #57 and #59 were integrated into the R02 line and the same external owner runtime was resumed rather than reset.

Final release evidence proved:

- historical backfill `succeeded`;
- exact rerun of completed historical coverage made `0` provider requests and left persisted current/observation counts unchanged;
- normal incremental `garmin-sync` succeeded afterward;
- historical and incremental checkpoint namespaces remained isolated;
- privacy gate passed with no private Garmin evidence entering Git/CI/issues.

R02 release PR #61 merged accepted integration SHA `aea777e418d8d16c275a860c31b11c72641a73e6` to stable `main`. Released stable SHA: `d3b2fa316242ac11a7ba5851fdc99656cdf8e534`. Release PR CI `34049514818` and exact post-merge `main` CI `34049649157` both succeeded. #52 is closed completed.

Full sanitized release history, including the accepted residual duplicate-coverage semantics, is recorded in [R02 Release Closeout](R02_RELEASE_CLOSEOUT.md).

### Pre-R03 hardening

Before R03 deterministic analytics consumes Garmin current records:

1. **#56 — Garmin collection reconciliation and reprocessing policy.** Make current collections converge deterministically under provider corrections, reorder/insert/remove events, timestamp/value corrections, stale replay, and normalization-rule upgrades. Define authoritative collection replacement/tombstoning and explicit bounded version-aware reprocessing without weakening normal historical coverage skipping.
2. **#55 — Garmin metric, time, and analytic coverage contract.** Make analytic meaning explicit: daily average vs maximum vs trailing aggregate vs samples; local/UTC/offset time semantics; metric-level analytic availability rather than surface-level `present`; and a reproducible R03 input DTO/evidence manifest whose old calculations remain auditable after later source corrections.

These are post-release hardening tasks, not reasons to reopen R02.

## R03 — Garmin analytics and activity comparison

After #56 and #55:

- personal baselines, trends, percentiles, anomalies, and lag semantics;
- cycling/session comparison with genuinely comparable fields and explicit coverage;
- Garmin-specific score presentation with provenance and no medical overclaim;
- deterministic read/query service over versioned evidence manifests;
- dashboard expansion for Garmin trends/comparisons without making the LLM responsible for raw-series mathematics.

## R04 — Google Health / Fitbit ingestion

Frozen contract (#84; accepted #81 `5643609852` + #82 `5643533712`/`5643611744`): Google Health API v4 only, legacy Fitbit Web API turn-down September 2026. Web Application / Web Server OAuth with Client ID + Client Secret (outside Git) and a fixed registered localhost loopback callback — Desktop/random-port contract retired; exact port/path pinned in R04-02.

- Complete the live API-access and OAuth verification checklist first (Console setup, fixed-callback authorization, secret/refresh protection, Published/In-Production behavior).
- Request only `googlehealth.sleep.readonly` and `googlehealth.health_metrics_and_measurements.readonly` (all Health scopes Restricted; personal-use/unverified exception with warning + 100-user cap; Testing 7-day tokens rejected for automation).
- Incremental sync/backfill for data types actually exposed to the account (sleep; heart rate; HRV + daily HRV; daily resting HR; SpO2 + daily SpO2; respiratory-rate sleep summary + daily respiratory rate), preserving raw `list` source metadata separately from family reconcile/rollup results. Sample heart-rate supports `list/reconcile/rollUp/dailyRollUp`; other planned vitals/daily types use `list/reconcile`; sleep uses session operations.
- Keep `list`/`reconcile`/`rollUp`/`dailyRollUp` and `dataSourceFamily` as query context, not source identity; family aggregates are never Fitbit-device evidence without explicit provider metadata (`google-wearables` includes Pixel Watch). Explicit `google_*` layer reusing the generic spine; no `garmin_*` reuse, no generic provider framework.
- Raw/source preservation, typed sleep/HR/HRV/RHR/SpO2 data where available, coverage (`nextPageToken`, sleep cap 25, inclusive-lower/exclusive-upper bounds, no ordering reliance, string-encoded integers, missing-never-zero), quotas (300/min/user; 250 QPS / 100 users aggregate) plus tighter Health-Check budgets, and token-health diagnostics.
- R03 analytics stay Garmin-only; cross-source agreement/canonical sleep is R05.
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
