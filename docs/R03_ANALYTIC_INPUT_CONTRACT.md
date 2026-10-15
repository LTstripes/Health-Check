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

## Versioned activity session extension (#319 B1)

Analytic rules `r03-garmin-analytic-rules-v2` add:

| Metric code | Aggregate kind | Window | Unit | Reviewed source fields |
| --- | --- | --- | --- | --- |
| `max_heart_rate_bpm` | `session_maximum` | `activity_session` | `bpm` | `maxHR` |
| `training_effect` (existing aerobic alias) | `provider_session_score` | `activity_session` | `points` | `aerobicTrainingEffect`, alternate `trainingEffect` |
| `anaerobic_training_effect` | `provider_session_score` | `activity_session` | `points` | `anaerobicTrainingEffect` |

Maximum and average HR are independent identities. Both effects remain separate
provider-native scores with unverified producer attribution; raw camelCase rows
and labels are not additional analytic metrics. There is no combined effect,
cross-effect substitution or energy metric in this extension.

Comparison algorithm `r03-02-garmin-activity-comparison-v1` is unchanged; its
output rule changes from `r03-02-v1` to `r03-02-v2`. Frozen v1 outputs retain the
original ordered eight codes: `duration_seconds`, `distance_meters`, `speed_mps`,
`heart_rate_bpm`, `power_watts`, `cadence_rpm`, `training_effect`,
`acute_training_load`. V2 defaults append `max_heart_rate_bpm`, then
`anaerobic_training_effect`. Serialized query codes, definitions, rule versions,
input manifests and result hashes identify each output without reinterpreting
old results under a new default. A legacy projection without either new row
reports `not_computable` / `metric_absent_from_projection`; it does not invent
coverage or run replay. The input DTO shape remains v1, and normalization version
is retained in each immutable evidence reference.

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

## Selected-day stress adapter (#357, backend only)

R03 daily stress selection uses rule `r03-01-v2` and explicit
`r03-01-stress-daily-mean-applicability-v1` selection semantics. Before daily
ambiguity resolution, only a proven normalizer-created **missing** daily-mean
placeholder on `heart_rate`, `body_battery`, `spo2` or `respiration` may be a
non-candidate. Proof requires agreement of persisted intraday surface and
source/day collection key, exact missing scalar path/state/unit/attribution,
reviewed normalization/reconciliation versions, and the selected raw/observation
and committed normalization event/batch chain. The observation identity is
recomputed, including its matching `<surface>.json` filename; filename or missing
state alone is insufficient. No additional raw originals are scanned for this
classification. Missing or conflicting provenance remains a candidate (or fails
input assembly), so it cannot resolve ambiguity in favor of another value.

Genuine stress missing/null/invalid, unexpected nonmissing foreign rows and all
genuine duplicates, including equal values, retain the existing fail-closed
per-date semantics. No first-usable or value-based selection is performed.
Non-candidates are absent from points, availability counts and statistics; the
separate `applicability` audit retains their frozen input/evidence references,
surface/collection/observation/event identities and counts. Both this audit and
all frozen inputs are bound into the result hash. The fetched-row cap applies
**before** applicability; non-candidates do not make an over-cap query admissible.

Explicit `selection_version="r03-01-v1"` requests the legacy strict selection,
with its original serialization and hash semantics. Other scalar metrics retain
v1. Existing frozen results are never reinterpreted. The compatible stress
adapter contract is `garmin-daily-stress-personal-baseline-v2`; it requires the
new R03 rule/selection version in both current and history, and copies the
applicability audit. It never filters R03 participants or recomputes a narrower
baseline. Its date, timezone and ordinary acquisition proof remains unchanged:
no Owner timezone policy or implicit Moscow fallback is introduced.

`GarminQueryService.stress_baseline` requires an explicit source, selected date D
and aware evaluation instant. In one physical read snapshot it calls R03 for
`[D,D]` and `[D-28,D-1]`. At least 21 distinct eligible historical dates are
required; this product gate is not a clinical threshold. It copies R03's frozen
median and Type-7 P25/P75, and computes only current minus historical median in
points. No percentile/trend/robust-z interpretation is added.

All participating daily means must retain exact source, `avgStressLevel`, stored
unit/attribution and compatible method evidence. The stress-specific equivalence
of normalization v1/v2 is pinned to #319 commit
`4a7bc96d7940c2e5161a210de2c179641bfa2aa6`: daily stress parsing, calendar meaning
and metric coverage did not change. Unknown versions are not assumed compatible.
Record-wide partial parse status can concern unrelated sibling fields and does
not downgrade stress. Participating metric-specific partial or incompatible
evidence withholds the entire comparison, without subset percentile recomputation.

Completion requires the referenced ordinary `garmin_incremental` or
`garmin_historical` successful acquisition of `stress.json`, its exact committed
observation/event/batch provenance, and receipt at/after the source-day end.
Only the referenced original JSON is read, bounded to 1 MiB per participant
(at most 29); its genuine `calendarDate`, daily mean and unambiguous IANA timezone
must agree with the selected evidence. Source-clock checks reconcile normalized
clock evidence and supplied offsets with the named timezone, respecting DST.
They do not require every optional raw clock field to survive normalization:
malformed optional `startTimeLocal` may normalize away without invalidating an
independently valid `calendarDate`, unambiguous timezone and post-boundary
acquisition. Malformed observation identity fails
closed. Host timezone, requested window, mutable coverage, raw deduplication receipt,
and later reprocess timestamps are not proof.
Absent date/timezone/acquisition proof retains the saved current value with a
specific unavailable comparison reason. A skipped midnight is unproven; an
ambiguous midnight uses the later valid boundary. No acquisition/intraday
completeness, hardware continuity, health grade or causal claim is made.

This slice does not expose a route or choose a UI surface. Source selection, actual
Owner coverage and future UI acceptance remain separate.

## Non-goals

- LLM mathematics or free-form SQL analytics;
- scheduler / Fitbit / Google / FIT / GPS / dashboard redesign;
- generic multi-provider analytic framework;
- inventing missing aggregates or UTC for local-only samples.
