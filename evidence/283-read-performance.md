# Issue #283: measured Period Brief reads

Assignment: [#283](https://github.com/LTstripes/Health-Check/issues/283),
[Integrator comment 5981015027](https://github.com/LTstripes/Health-Check/issues/283#issuecomment-5981015027).
Pinned baseline: `9eb5b82221c99d96e7681f26c4f41e637186fe47`.
Delivery is the task branch; no PR, merge, release or acceptance is implied.

## Candidate boundaries

Only the three assigned backend hot paths change. There is no schema/index
change, cache, materialized report, provider access, UI change or analytics
contract change. Verification adds frozen query oracles, an opt-in synthetic
harness and focused tests registered in the existing complete CI partition.

Measured production Git blobs (canonical LF content):

| File | Git blob |
| --- | --- |
| `src/healthcheck/source_freshness_read.py` | `bc3f91c3bb39d9e84187f75f1b6001244bb149c1` |
| `src/healthcheck/analytics/sleep_agreement_report.py` | `121b366ace562be5a08558a27875b9bb3ff2d171` |
| `src/healthcheck/analytics/garmin_baselines.py` | `2fc8fb802fc6127b5cf3aca4afb0a2ec01e683c9` |

These blobs bind performance evidence to the retained implementation without
introducing a self-referential commit SHA into a tracked report. The final
delivery report binds the complete candidate commit and exact CI run.

## Same-harness protocol

`scripts/profile_period_brief_reads.py` creates a new, explicitly named external
synthetic runtime. It uses the real migration schema, normalization/persistence
for 28 nights and daily stress evidence, and a published account
sleep-agreement run. FK-valid bulk source-record/metric and coverage history
provide query volume. Bulk noise is a performance proxy, not an end-to-end
provider ingestion test or a claim about Owner profile contents or timings.

The full profile adds 2,000,000 Garmin source records and metric rows,
200,000 coverage intervals, and 5,000 sync runs. The control adds 10,000,
1,000 and 100 respectively. Neither arm adds indexes or runs ANALYZE.
Both arms use the same persisted database, period (2099-01-02 through 2099-01-29),
frozen evaluation clock, production services and downstream assemblers.
Fresh sessions retain the production read-snapshot behavior. Only the three
query bodies are replaced by the frozen baseline in the before arm.

One warmup per arm is excluded. Five measured pairs alternate before/after
order. Wall times include SQL fetch and ORM work; `sql_execute_seconds` is
DBAPI execute time only, not fetch/ORM time. Baseline phase time includes
unchanged downstream provenance/analytics work, while
`baseline_candidate_seconds` separately times candidate execute/fetch/ORM.
EXPLAIN runs after the measured call, using captured SQL and the actual bound
parameters; it is excluded from timings. Every measured packet, including its
hash, and every ordered stress-baseline candidate identity must be equal.

Reproduction from the candidate checkout and locked environment:

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'hc-283-uv-cache'
uv sync --locked
$env:HEALTHCHECK_DATA_DIR = Join-Path $env:TEMP 'hc-283-synthetic-full-reproduction'
uv run --no-sync python scripts/profile_period_brief_reads.py `
  --runtime $env:HEALTHCHECK_DATA_DIR --output evidence/283-full-reproduction.json `
  --repeats 5
# Use another new runtime and --records 10000 --intervals 1000 --runs 100
# for the control. --reuse accepts only a previously generated synthetic
# manifest from this exact harness; it never seeds an existing database.
```

Runtime files/artifacts are external and excluded from Git. Only synthetic
measurement JSON, SQL/parameters/plans and this explanation are delivered.
Environment: locked dependencies, Python 3.13.15, SQLite 3.53.1 on Windows.
CI separately validates the candidate under its configured Linux/Windows
toolchains. Local timing is not a benchmark of Owner Stable or CI hardware.

## Final measurements

The final full database is 2,441,105,408 bytes (about 2.27 GiB), with
2,000,056 source records, 2,000,364 metric rows, 200,000 coverage intervals and
5,000 sync runs. Its cardinalities match the assigned full-size proxy; its
physical size and distribution differ from #172, so absolute times are not
compared across those two harnesses.

Five measured samples per arm, with full packet/hash and ordered candidate
identity equality in every pair:

| Read/phase | Full before (s) | Full after (s) | Control before (s) | Control after (s) |
| --- | ---: | ---: | ---: | ---: |
| Period Brief build | 55.108098 | 6.520210 | 0.929431 | 0.776407 |
| Garmin series freshness | 16.768557 | 0.085401 | 0.096171 | 0.008789 |
| Sleep source data quality | 4.669489 | 0.291002 | 0.015952 | 0.004587 |
| Baseline queries + unchanged assembly | 27.617466 | 0.146433 | 0.191246 | 0.131406 |
| Stress baseline candidate execute/fetch/ORM alone | 6.835841 | 0.002062 | 0.016262 | 0.003258 |

Full total ranges: before 54.351161–57.488935 s; after 6.362687–8.204927 s.
For every retained hot path, the slowest after sample is faster than the
fastest before sample in both profiles. Improvement exceeds the measured
run-to-run spread. Full build median improves about 8.45 times / 88.2%.
Residual time is in unchanged reads/assembly outside the assigned three paths.

Coverage rows crossing into ORM fall from 200,000 to 580 in the full profile,
and from 1,000 to 29 in the control. Complete overlapping coverage facts are
preserved; this is SQL selection, not a report/history cap.

Raw samples, SQL execute/phase timing, bound SQL and EXPLAIN plans are in
`283-full.json` and `283-control.json`. `283-measurement-identity.json` records
schema/harness identities, profile counts, returned coverage row counts and
the packet hashes. Final full packet result hash:
`351d2bbe0df7b5799396a8d99c20b94654b515cf61bcf0d1fce6255c8699629d`.

## Why the outputs are equivalent

### Garmin series freshness

For each provider source, the first accepted row ordered by civil date descending
has the same date as that source's MAX(non-NULL civil date). A returned NULL row
still proves that undated evidence exists. Taking MAX across those source
probes in SQL is therefore identical to the original provider-wide MAX. Counting
the corresponding first non-NULL record IDs tests source observation, not
historical row count: zero means the original COUNT was zero. Decoding only the
global maximum also preserves the original handling of unselected older dates.
Nonempty/all-NULL input keeps the
original invalid-chronology result. The second aggregate reads every accepted
row on that exact global latest date across every provider source. All stream,
surface, current-projection and ok/partial filters, invalid chronology detection,
timestamp/date precedence and latest-slice source ambiguity remain identical.
LIMIT 1 applies only to finding each source's maximum date, never to the final
evidence slice or to history/coverage returned to a consumer.

EXPLAIN replaces full source-record scans with the existing
`ix_garmin_source_records_surface_date` for backward date probes and exact
source/surface/day aggregation. The source table is still read to identify the
provider's sources; there is no speculative new index.

### Sleep source data quality

Only the three state columns and five run columns actually consumed by this
read are fetched as typed SQL rows. They retain the existing datetime decoding
and the original Python MAX/sort logic verbatim, including NULL/empty input,
success eligibility, unfinished attempts and lexical ID tie-breaks. No run or
state history is truncated. The unused historical entity fields and ORM
materialization are removed, rather than adding another clock interpretation.

Coverage is filtered before ORM using the stored ISO civil-date prefixes and
the original inclusive date comparisons. This retains endpoints, alternate
space/T separators, fractional precision and offsets without shifting their
civil dates to UTC. SQL also retains rows it cannot decode or whose normalized
date differs from that prefix: unusual/basic ISO encodings and offset-day
shifts still go through the unchanged Python .date() filter, and malformed rows
outside the requested window still reach fail-closed datetime decoding rather
than disappearing. The SQL predicate is a conservative prefilter; the original
Python filter remains the final authority. If either bound is absent, no time
predicate is applied. All overlapping coverage facts, complete status counts,
ordering, diagnostics, explicit zero/NULL values, state precedence, provider
order, actual-evidence dates and window fields remain unchanged.

EXPLAIN still scans coverage to apply its time predicate, but only matching
rows (plus encoding/invalidity fallbacks) reach ORM. Sync clocks/status are
typed narrow projections rather than all historical ORM entities. Measurements
justify this read reduction; an
additional coverage/sync index is unnecessary for this candidate.

### Baseline candidates

The additional predicate `record.id IN (SELECT record_id WHERE metric_code = M)`
is logically redundant: every row from the existing join filtered to metric M
already proves that membership. It provides a planner access path through
`ix_garmin_record_metrics_metric_state`, followed by the existing unique
record/metric index and source-record primary key. The original source,
projection, metric and local-date-or-undated-UTC predicates remain in place.
State is not filtered. Ordering, cap+1 failure, provenance assembly, selected
inputs, statistics and result hashing remain unchanged. The necessary ORDER BY
temporary B-tree remains; there is no index or history truncation.

## Semantic regression evidence

The three oracle bodies in `scripts/period_brief_read_reference.py` were
extracted from the pinned baseline, not reimplemented from the candidate.
AST comparison to `git show <baseline>:<file>` passed for each complete body.
SHA-256 of the dedented baseline body text:

| Body | SHA-256 |
| --- | --- |
| `_garmin_series_evidence_query` | `89996658b57d0de900d11e35f784da9c51f6145b0d6edeef872861ceae22c2d0` |
| `_source_data_quality` | `a7fa6839c37df7d5bd632984020ba194f33602ca490f7ece5c56deba97c1bf3d` |
| `_candidate_statement` | `b386ca6df69e495416cb526f658c8636b1e6c0961291ac251fa6916af6acb37d` |

`tests/test_period_brief_read_equivalence.py` compares persisted reads and
production results against these oracles: all five series surfaces, missing/
undated/local/unknown chronology, mixed timestamp/date inputs, multiple and
foreign sources, excluded retired/invalid/empty/future sibling evidence,
deterministic randomized evidence, freshness states/reasons/actionability,
completed-versus-running clocks, successful/partial/failed/unknown state
precedence, lexical tie-breaks, empty providers, inclusive coverage endpoints,
unbounded/one-sided windows, maximum calendar date, alternate/basic ISO datetime
encodings, offset-day shifts and malformed out-of-window datetime rejection.
Baseline cases preserve
all four metric states, explicit zero, local-date precedence over UTC, NULL-date
UTC fallback, ordering, exact cap+1 failure before assembly and real production
assembly/results/hashes. Read tracing confirms the optimized reads execute
SELECT only.

Existing affected freshness, sleep report, baseline/trend and Period Brief
tests cover the unchanged consumers and negative contracts. Full packet/hash
and candidate identity equality is also enforced throughout both performance
profiles, not inferred from response sizes or similar timings.

## Rejected proposal

`283-rejected-metric-id.json` records the initial control experiment, which used
metric IDs instead of record IDs in the redundant baseline membership
predicate. Its plan still drove through source/date, and its baseline timing
did not improve beyond noise. That query form is not retained. Its data is
historical experiment evidence, not final-candidate validation.

`283-before-civil-date-fix.json` retains the first full-profile experiment.
Additional regressions showed that its naive datetime-range coverage filter
lost valid timestamps without fractional digits or with a T separator. That
filter and its SQL clock aggregation/window proposal are not retained. The
final implementation uses a conservative civil-date prefilter and narrow
typed clock projections with the unchanged clock rules. The final profile
remeasures the complete stabilized implementation on the same generated
database; no earlier timing is relabeled as final evidence.

## Tooling and remaining authority

Final local checks:

- Focused suites: `test_period_brief_read_equivalence.py`,
  `test_source_freshness.py`, `test_sleep_agreement_report.py`,
  `test_garmin_baselines_trends.py`, `test_period_brief.py`,
  `test_read_snapshot.py`: **182 passed**, 95.34 s. Raw local JUnit is retained
  in the external task temp directory, outside Git.
- `ruff check .`: passed.
- `scripts/ci_test_lanes.py validate-manifest`: 64 files in three lanes, passed.
- `python -m healthcheck.db.migration_guard`: passed; existing head
  `0015_candidate_metadata_origins`.
- `git diff --check`: passed. The exact-candidate complete CI gate is performed
  after publishing this complete task-branch candidate and reported separately.

No automatic local full-suite rerun was used; the focused tests and complete
exact-candidate CI have different purposes.

The configured local verification helper README was absent on this host.
Equivalent preparation used the locked task-local venv, isolated task cache,
explicit external synthetic runtime and external pytest basetemp.

CBM: used `D-Codex-index-sources-health-check-main` to locate the three query
functions; checked against current assigned source. Its recorded snapshot root
was unavailable locally, so graph readiness was not treated as freshness proof.

Worker measurements and green CI do not substitute for independent review or
Integrator acceptance. Those remain separate, and no Owner/live provider gate
is claimed by this synthetic task-branch delivery.
