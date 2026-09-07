# R03 Garmin analytic input contract (pre-R03 / #55)

This is the bounded read/semantic contract that sits between accepted R02 Garmin
projections and deterministic R03 analytics. It does not redesign ingestion, add
a scheduler, calculate LLM mathematics, ingest Fitbit/Google, parse FIT/GPS, or
introduce a generic multi-provider framework.

Implementation: `healthcheck.garmin.analytic_contract`.

## Goals

1. Keep statistically different provider fields as distinct analytic metrics.
2. Preserve series time semantics from the [normalization contract](R02_NORMALIZATION_CONTRACT.md).
3. Expose metric-level analytic availability that is stricter than operational
   surface `present`.
4. Freeze a reproducible input DTO / evidence manifest for each deterministic
   calculation.

## Aggregate vs sample identity

Do not collapse provider fields that mean different aggregates into one analytic
metric code.

| Metric code | Aggregate kind | Window | Reviewed source fields |
| --- | --- | --- | --- |
| `stress_daily_average` | `daily_average` | `calendar_day` | `avgStressLevel` |
| `stress_daily_maximum` | `daily_maximum` | `calendar_day` | `maxStressLevel` |
| `stress_sample` | `sample` | `point` | `stress`, `stressLevel`, series arrays |
| `spo2_daily_average` | `daily_average` | `calendar_day` | `averageSpO2` |
| `spo2_trailing_7d_average` | `trailing_aggregate` | `trailing_7d` | `lastSevenDaysAvgSpO2` |
| `spo2_sample` | `sample` | `point` | `spo2`, `spo2Percent`, series arrays |

Rules:

- Preserve the reviewed source field/path on the metric row.
- Do not substitute maximum for average, or a seven-day trailing average for a
  daily value, when the requested analytic metric is absent.
- Operational acquisition success for a stress/SpO2 surface is not permission to
  invent a missing aggregate.

## Series time semantics

`_sample_temporal` (incremental sync series expansion) follows the same rules as
normalization:

| Provider stamp | Analytic precision | UTC | Local evidence |
| --- | --- | --- | --- |
| aware ISO / offset datetime | `instant` | normalized UTC | wall time + offset/zone when present |
| explicit GMT/UTC field or epoch stamp | `instant` | UTC by field/epoch semantics | no invented local zone |
| local-only naive datetime/string | `local` | **none** | `local_wall_time` / source local timestamp |

Genuinely local-only naive timestamps must not receive an invented UTC timezone.
Date-only values remain local dates. Travel/timezone frameworks are out of scope;
DST/local-only regressions exist for intraday/lag analytics.

## Metric-level analytic coverage

Operational coverage `present` means the acquisition surface succeeded. It does
**not** prove every dependent analytic metric is complete.

`MetricAnalyticCoverage` reports, per metric code:

- availability: `available`, `missing`, `null`, `zero`, `invalid`,
  `not_computable`, or `partial`;
- parsed sample counts and usable/null/zero/invalid/missing counts;
- deterministic exclusions / shape-loss reasons;
- whether the operational surface was present.

Sleep family rule: `sleep_duration_seconds` presence must not imply
`sleep_score`, `sleep_stages`, or `nap_duration_seconds` availability. Missing,
null, and explicit zero remain distinct states.

## Evidence manifest / input DTO v1

Contract version: `r03-garmin-analytic-input-v1`.

Each deterministic calculation may freeze an `AnalyticInputDTO` containing:

- metric definition (code, unit, aggregate kind, window);
- selected value/state and field path;
- analytic date/time semantics;
- source / algorithm identity;
- metric-level coverage/availability;
- immutable evidence references:
  raw payload id + content hash, observation id/key, record id + idempotency key,
  metric row id, normalization/reconciliation contract versions;
- stable `manifest_hash` over the canonical JSON body (excluding the hash itself).

Same evidence + rule version => same DTO/manifest hash. A later current-record
correction updates the live projection but does not rewrite an already-recorded
manifest that points at immutable raw/observation evidence and the selected
values frozen at analysis time. This is not a second Garmin store and not generic
event sourcing.

Producer-side storage grounding: `build_analytic_input_from_storage()` takes a
persisted record/metric locator, joins the existing raw-payload + observation
provenance chain, constructs `AnalyticEvidenceRef` itself, and fails closed on
missing or mismatched provenance. Selected input freezes scalars and, for
collection-valued metrics such as `sleep_stages`, the canonical stage-interval
collection used by the calculation.

## Non-goals

- LLM mathematics or free-form SQL analytics;
- scheduler / Fitbit / Google / FIT / GPS / dashboard redesign;
- generic multi-provider analytic framework;
- inventing missing aggregates or UTC for local-only samples.
