# Combined Sleep + Activity + Context evidence

## Optional saved observed Steps and Weight (#451)

Set `steps_garmin_source_id` (CLI `--steps-garmin-source-id`) to select one exact
Garmin source independently of Activity/Sleep. Set `include_weight=True` (CLI
`--include-weight`) to request the accepted Weight overlay and canonical evidence.
Neither option is enabled by default. These selections use explicit detailed /
compact v4; omitted options preserve the existing v1/v2/v3 versions and defaults.
Both sections remain identical in detailed and compact JSON/text/file/stdout,
with the existing 2 MiB caps, exact 7/30-day dates and one read-only transaction.
Context is still read once. The Weight/Context MCP and access setup are unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> --sleep-garmin-source-id <sleep-id> \
  --steps-garmin-source-id <observed-steps-id> --include-weight \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

Steps delegates to `read_observed_steps_window` and exports saved materialized
account-level daily observations, **not completed daily totals**. Values retain
exact integers (including zero), date precision, eligibility states, candidate /
observation / normalization provenance and unknown coverage, device, timezone and
finality. Unprojected, ambiguous, retired, null, missing and invalid evidence does
not become zero. Sources are never summed, and no period total or mean is added.
The existing 4096-candidate and independent 4096-provenance bounds remain. If the
reader reports incomplete search, the complete combined export fails with
`steps_search_incomplete`; even an earlier proven prefix is not published.
This path neither opens artifact bytes nor reparses provider bodies. Completed
Steps, Google Steps, provider refresh and new projection/ingestion remain outside
this slice.

Weight reuses the accepted v1 exporter projection of `WeightQueryService` in the
same caller-owned snapshot. It retains confirmed source overlay measurements,
`canonical_selected`, source/provenance, accepted daily medians, canonical status,
coverage, trend/rate algorithm identities and unavailable reasons. Overlay points
are not all canonical-selected; sources are not summed. Daily medians exist only
on dates with eligible selected measurements. A derived trend is not evidence of
a measurement on an unmeasured date. Source freshness is provider-scoped and uses
the explicit evaluation clocks. The existing export cadence is 7 days, independent
of runtime settings; this is a coverage policy, not imputation or acquisition proof.
No configured goal, import queue or raw artifact is exported.

The inherited 2000 scalar-input bound and 100 rows per exported Weight series are
unchanged. Any series exceeding 100 rows fails the complete combined export with
`weight_selected_points_exceed_max`, instead of returning a winning prefix. Missing
or unconfirmed measurements stay absent; no zero, interpolated daily weight,
source fallback, daily causal join or health diagnosis is introduced. Owner-local
availability/UAT and acquisition completeness remain unverified.


## Optional saved HRV and resting heart rate (#451, next bounded slice)

Set `hrv_garmin_source_id`, `hrv_google_source_id`, `rhr_garmin_source_id`
and/or `rhr_google_source_id` on `CombinedEvidenceRequest`, or the matching CLI
flags. Every exact ID is validated in the shared read-only snapshot before any
domain reader runs. Each metric has its own explicit sources; no Sleep/Activity
fallback or provider pooling occurs. `rhr_google_auto_select=True` (CLI
`--rhr-google-auto-select`) opts into the accepted metric-specific Google RHR
selection. An exact RHR override takes precedence, including an empty source.
HRV requires exact sources and does not infer a Google choice from Sleep or RHR.

With HRV/RHR selected, detailed/compact packets use
`health-chat-combined-evidence-v3` / `health-chat-combined-compact-evidence-v3`.
Existing omitted-metric v1 and Stress/Body Battery v2 remain unchanged. Sections
`hrv` and `rhr` contain only requested `providers`; compact retains these sections
identically to detailed. JSON, readable text, files and stdout share the frozen
packet and the unchanged 2 MiB caps, SQL/time guards and exact 7/30-day dates.
Context is read once. Steps and Weight are separately opt-in above. The existing
Weight/Context MCP, its schema/auth and connection setup are unchanged.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> --sleep-garmin-source-id <sleep-id> \
  --hrv-garmin-source-id <weekly-hrv-id> --hrv-google-source-id <daily-hrv-id> \
  --rhr-garmin-source-id <rhr-id> --rhr-google-auto-select \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

Garmin HRV is the persisted `hrv_weekly_average_ms` snapshot, labelled as a
provider weekly/trailing aggregate on its saved source-local date. It reuses
Overview snapshot matching, eligibility and latest-within-date ordering; equal
date-only candidates stay ambiguous. Eligible partial and zero values remain
values; wrong units, missing/null/invalid, excluded and retired records never
supply one. Per-point evidence retains source field, record/metric/raw IDs,
precision, saved clock and normalization identity. The adapter reads current
typed rows only; no raw-body parsing or import is added. At most 4096 candidate
metric rows and 256 rows/date are inspected (the existing RHR work ceilings);
overflow fails the entire packet without a prefix. Undated records cannot be
assigned to the requested window. Counts are **snapshot-date counts**, not
daily HRV coverage. `dates_without_eligible_snapshot` does not describe the
physiological coverage of any weekly aggregate. No HRV mean is computed.

Google HRV uses `read_google_daily_vitals` (#297), retaining its exact daily
metric/stream/unit, date-only eligibility, current-record ambiguity, per-point
states and exclusions. This reader gains optional exact source and cap arguments;
omitting them preserves its existing behavior. Combined selects one exact source
and caps candidates at 4096 before projection, rejecting overflow without a
prefix. The scalar allowlist excludes arbitrary bodies and unrelated source
inventory. Missing dates mean no eligible saved daily value; they never become
zero or prove collection failure. Google daily HRV and Garmin weekly HRV remain
different series even if their values coincide; neither is averaged with the other.

RHR delegates to `read_saved_rhr_period` (#393), including its #376 eligibility,
source-specific dates/precision, chronology exclusions, partial/zero values,
record provenance, refresh facts, exact rational mean and final-only rounded
display. The denominator is distinct eligible saved days; missing days are never
zero. The existing 32-source inventory, 4096-record/source and 256-record/date
bounds remain unchanged. Google automatic selection evaluates RHR eligibility in
this exact window: other metrics cannot choose a source, two eligible sources
conflict even on disjoint dates or equal values, ambiguous-only sources compete,
and any incomplete candidate blocks selection. Conflict, unknown and incomplete
states retain the reader's disclosure and have no selected value/mean; unresolved
missing-day counts stay null. SQL/storage failures reject the complete packet.

All acquisition coverage stays unknown. Saved dates do not establish common
timezones, daily causal alignment, clinical significance or provider availability.
No new ingestion, refresh, migration, UI, Stable operation or private-data test is
included. Owner-local availability/UAT remains separate and unverified.

## Optional saved Stress and Body Battery (#451)

Select `CombinedEvidenceRequest.stress_garmin_source_id` and/or
`body_battery_garmin_source_id` (CLI flags below) to add those exact Garmin
sources. Neither falls back to the Activity/Sleep source or automatic selection.
All IDs are validated before any domain reader runs. With both omitted, existing
detailed/compact v1 shapes and serializers are unchanged. With either selected,
the version is `health-chat-combined-evidence-v2` or
`health-chat-combined-compact-evidence-v2`; `request.sources` and `sections` add
only the requested metrics. Compact changes only Sleep: all selected Stress,
Body Battery and Context facts remain identical to detailed mode, with the same
2 MiB cap. Oversize results fail without a winning prefix.

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> --sleep-garmin-source-id <sleep-id> \
  --stress-garmin-source-id <stress-id> \
  --body-battery-garmin-source-id <battery-id> \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

Both new sections use the same existing read-only transaction and exact inclusive
request dates as Sleep/Activity. Context is still read once. Sources may coincide
or differ; the packet neither pools sources nor joins daily facts causally.
These are saved-source dates, not completed Moscow days inferred by the CLI.
This CLI addition does not extend the unchanged Weight/Context MCP or its schema,
authentication or connection availability. HRV, RHR, Steps and Weight are
separate opt-in sections described above.

`sections.stress` uses `analyze_garmin_metric_series` for
`stress_daily_average` with the accepted
`r03-01-stress-daily-mean-applicability-v1` selection and `r03-01-v2` rules.
It preserves provider daily averages in points, every selected point's state,
date/precision/clock, zero, partial, missing, null, ambiguity, exclusions and
allowlisted input manifests, normalization/provenance and applicability audit.
The existing 2000 candidate cap is unchanged: overflow rejects the entire request
with `stress_selected_points_exceed_max`, never a truncated series. Baseline/trend comparisons are
not exported or reinterpreted; `reader_result_hash` identifies the accepted full
reader result, while the combined hash binds the disclosed projection. No raw
payload, arbitrary diagnostic detail, source filename or artifact path is exposed.

`sections.body_battery` uses `read_body_battery_period` with the accepted
`r394-saved-body-battery-maxima-v1` eligibility: only proven current typed saved
samples, with legacy scalar/alias eligibility explicitly unknown. Each daily
value is the **maximum among saved eligible measurements**, not a guaranteed
full-day/provider-native maximum or morning value. Sample count, winning evidence
IDs/precision, exclusions, unknown acquisition coverage and search metadata are
retained. The accepted period mean weights eligible saved days equally;
`mean_exact` preserves its rational representation and `mean_value` is a lossless
decimal **string**, or null. The 100000 period/10000 per-day candidate caps stay
unchanged. Incomplete search emits no daily prefix or mean, and day counts and
missing dates remain null. A storage failure rejects the complete packet.

For both metrics, `missing_day_count`/`missing_dates` mean dates with no eligible
value, including excluded dates; they do not prove acquisition failure or absence
of a physiological observation. `excluded_day_count` counts dated exclusions
without an eligible value and is a subset of missing days, not an additional
disjoint count. Stress availability counts describe records separately. Explicit
zero remains zero; missing/unknown never becomes zero. Stored presence does not
establish full-day acquisition coverage (reported unknown). JSON and text print
the same selected facts, semantics, counts and warnings; stdout validates its
complete result before writing any byte. The historic `--st` stdout alias stays
accepted despite the new `--stress-...` option. Private Owner UAT remains separate
from synthetic tests and CI.

`healthcheck.combined_evidence.read_combined_evidence` returns a single bounded
`health-chat-combined-evidence-v1` packet by default. It composes the accepted
[Sleep](SLEEP_CHAT_EVIDENCE.md) and [Activity](ACTIVITY_CHAT_EVIDENCE.md) evidence
services in one existing WAL-aware read-only SQLite transaction. Context is read
once, with the existing current-revision overlap/precision/disclosure rules.
This additional reader and standalone CLI leave the original exporter and MCP
tools, domains, schema and authentication unchanged. No connection is installed.

```python
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.combined_evidence import CombinedEvidenceRequest, read_combined_evidence

packet = read_combined_evidence(
    profile=Path(selected_existing_profile),
    profile_kind="synthetic",  # trusted caller assertion, never inferred
    request=CombinedEvidenceRequest(
        end_date=date(2099, 1, 8), days=7,
        activity_garmin_source_id=selected_activity_garmin_id,
        sleep_garmin_source_id=selected_sleep_garmin_id,
        sleep_google_source_id=selected_sleep_google_id,
        include_context=True, context_limit=50,
    ),
    evaluated_at_utc=datetime.now(UTC),
    evaluation_local_date=date(2099, 1, 8),
)
```

## Request and output contract

Exactly 7 or 30 inclusive local calendar dates ending at the explicit date;
underflow, `date.max`, bool days and oversized/invalid limits fail. Requested and
effective bounds are equal, without clipping or fallback. Activity requires one
explicit Garmin source. Sleep requires at least one provider: an explicit Garmin
source and/or a Google exact source ID or `sleep_google_auto_select=True`.
An exact Google Sleep ID takes precedence over automatic selection. The Garmin
choices can coincide or differ; they are separate explicit selections and never
pooled. All explicitly requested IDs are validated for existence and provider in
the shared snapshot before either domain reader runs. Explicit-source requests
expose no unrelated inventory and never fall back to another source. Google opt-in
uses the bounded [Sleep selection contract](METRIC_SOURCE_SELECTION.md); competing
series or incomplete discovery remain labelled outcomes without a selected source.
Existing empty exact sources remain valid empty stored evidence; an unavailable
explicitly selected ID fails the request.

The top level contains version/provenance, generated/evaluation clocks, explicit
profile assertion/privacy, exact request and selected sources, snapshot/limits,
sections, interpretation boundaries and `envelope_hash`. The sections are:

- `sleep`: existing package/provenance/reader/metric versions and limits, with
  the unchanged public source sections under `providers.garmin` and/or
  `providers.google`;
- `activity`: existing package/provenance/reader versions and limits, with the
  unchanged public source section under `providers.garmin`, plus a versioned
  `temporal_evidence` object;
- optional `context`: the existing allowlisted current revisions/page metadata,
  once, with `relationship=local_date_window_cooccurrence_only`.

The composition deliberately uses the services' private session-based
`_assemble` hooks. Calling their public readers would open separate snapshots.
Equivalence tests bind this dependency to their public results; changes to the
hooks require checking this consumer. Per-domain generated clocks/hashes and
duplicated request/profile fields are omitted from the combined projection.
The combined SHA-256 covers canonical compact UTF-8 JSON excluding only its own
`envelope_hash`; nested versions and full evidence remain hash-bound.

`encode_combined_evidence` emits compact complete JSON. `render_combined_evidence`
renders a shorter readable view of the same frozen packet: exact request/source/
clock/limit identities, Sleep presence/gaps and resolved series plus saved-session
metric states/units/role exclusions, all five Activity cells including coverage
conflicts, and current Context revisions/page metadata. Full Sleep temporal and
metric audit provenance remains in the matching JSON, identified by the printed
hash. No values are recomputed. Literal Context text remains JSON-escaped untrusted
data, never instructions. The complete JSON retains provenance, exclusions,
per-night evidence, missing dates and coverage conflicts. Neither serializer
writes files. No automatic upload occurs.

## Activity temporal evidence

`sections.activity.temporal_evidence` is a versioned
`health-chat-activity-temporal-evidence-v1` object present only in combined
packets (detailed and compact are identical); the standalone Activity reader
stays aggregate-only. It is read in the same read-only snapshot through the
existing bounded loader and inherited 4096 candidate cap, against the exact
selected Garmin source and the persisted source-local-date window (no date
recomputation). A projected current-session cap of 200 is enforced; more than
200 projected current sessions fail the slice. Overflow returns an explicit
`incomplete` result with `sessions` and counts null — no timing prefix — while
the five Activity cells remain unaffected. A cooperative budget expiry anywhere
in the bounded timing assembly, including after the candidate rows load, returns
that same explicit `incomplete` state; unrelated storage/SQL failures still fail
the complete request.

Each projected current session exposes its persisted `source_local_date`
independently of the start state, plus a `start` endpoint in one of five states:
`absent`, `date_only`, `local`, `instant` or `ambiguous`, with `eligible` and a
deterministic `reason`. A timestamp is only called an activity start when the
persisted source field is a proven start leaf (`startTimeGMT`/`startTimeLocal`/
`startTimeUTC`/`startTime`); generic `timestamp`/`time` clocks are ambiguous.
Calendar/date-only evidence is retained with its saved date but is never a
start endpoint by itself. A record that is partial only because of unrelated
missing/invalid metrics, and an aware value that populates both paired columns
with the same path, keep a proven start. Actual start-clock ambiguity is read
from a closed allowlist of persisted temporal diagnostic codes
(`paired_time_mismatch`/`invalid_datetime`/`invalid_calendar_date`); a malformed
or unsupported diagnostic shape fails closed for timing. Invalid and conflicting
(paired local/UTC start) records, and duplicate current identities, never yield
usable timing. Retired records supply no current timing and are reported as
excluded reason counts. The `end` endpoint is always explicitly
`not_persisted_in_activity_contract` with null timing; raw payloads, unknown
fields and duration are never used to invent an end. Missing precision/zone/
offset stays null — never zero or a host/Moscow zone — and the persisted
source-local date is retained even when the UTC instant crosses a boundary, the
start clock is absent, or the start is ambiguous. Record/source/raw-payload/
normalization identity and source field paths are closed scalar allowlists; raw
bodies, artifact paths, unknown fields and diagnostic bodies are never exported
(the persisted diagnostic codes are inspected internally only). Readable text
prints the frozen `temporal_evidence` object without recomputing it. No universal
sleep ordering, join or causality is added; Garmin sleep can remain date-only.

## Semantics and limits

Sleep still uses source-local **wake dates** and Activity still uses persisted
source-local activity dates. Equal request bounds do not prove shared timezone,
daily alignment, temporal ordering or an effect of one domain on another. No
daily join, new formula, score, source pooling or causal analysis is performed.
Only local-date window co-occurrence is described. A missing Context note does
not establish absence of exposure.

All existing recursive disclosure rules, units and temporal precision apply.
Sleep zero/missing/null/partial/ambiguous/excluded states and unknown acquisition
coverage remain intact. Activity count/type/tennis duration/cycling distance
cells retain their accepted values, eligibility/exclusions, incomplete search,
coverage conflicts and normalization evidence. No summary of these states hides
an unavailable or conflicting domain. A domain's bounded incomplete result does
not truncate the other domain; storage/SQL errors reject the complete response.

The shared transaction retains `mode=ro`, `query_only`, deny-write authorizer,
current-schema validation, 20-million SQL-step and 20-second progress guards.
Sleep's 400/provider and 200/night record caps, Activity's bounded loaders and
2-second cooperative summary budget, and Context's 1–100 rows (default 50,
cap+1 read with explicit `has_more/truncated` and unknown total) remain as
documented in the individual service contracts. Each domain's limits are
present in its section. Combined JSON and text each have a 2 MiB UTF-8 cap,
including text reminders. Oversize JSON fails before a packet is returned;
oversize JSON or text fails before the CLI creates its output directory;
there is no winning prefix or all-history mode.

These are cooperative read guards, not a hard whole-response deadline. Python
processing, SQLite lock waiting, real-profile latency and Owner UAT remain
unverified. Profile classification (`synthetic`, `disposable_owner_clone`,
`durable_owner_runtime`) is a trusted caller assertion, not authentication.
Owner profiles are private. Snapshot metadata stays unknown; current Stable
identity is not inferred. SQLite WAL/SHM read coordination can occur; application
writes, migrations and journal changes are denied.

## Standalone CLI

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-08 --days 7 \
  --activity-garmin-source-id <activity-id> \
  --sleep-garmin-source-id <sleep-id> --sleep-google-source-id <google-id> \
  --evaluation-local-date 2099-01-08 \
  --output-dir <new-external-directory>
```

Either Sleep ID option may be omitted, but not both. `--context-limit` is
optional; `--no-include-context` skips Context entirely. The evaluation instant
is captured in UTC at invocation and the local evaluation date is explicit,
never inferred from the host zone. The command writes `evidence.json` and
`evidence.txt` from the same frozen packet only after both serializations pass.

`--output-dir PATH` and `--stdout json|text` are required and mutually exclusive.
`--stdout` emits only the selected existing serializer result for the one frozen
packet and no status line: `json` is `encode_combined_evidence`, `text` is
`render_combined_evidence`. The complete result is validated and constructed
before any byte reaches stdout, so a read, validation or serialization failure
leaves stdout empty with a bounded code on stderr and a nonzero exit. A malformed
stdout request — missing, invalid or conflicting options, including `--stdout`
combined with `--output-dir` in either order — likewise writes no payload and
prints one bounded code, never the arbitrary supplied values, and reads no data.
Stdout mode never creates the output directory and writes no `evidence.json`/`evidence.txt`.
Stdout receives the exact UTF-8 bytes of the serializer result even when the
active console encoding cannot represent some characters, so the packet is never
re-escaped into invalid JSON, substituted or truncated. The user redirects or
pipes stdout explicitly. This command runs in the local executor: it is not a
live assistant connection, no upload occurs, and captured/redirected stdout can
contain private owner context, so any resulting file is private Owner data.

The output directory must be new and outside the profile and any Git checkout
(including `.git` worktree files). Repeat `--agent-workspace-root` to also
exclude development roots without Git markers. These checks happen before
reading data. No files are overwritten. A filesystem failure during writing can
leave a partial new output directory; the command reports failure, never export
success. Read/validation/serialization failure creates no output directory.
Console errors contain bounded codes, without health text or profile paths.

No implicit/default profile, missing DB creation, runtime preparation, migration,
environment/config scan, raw provider-body read, provider call, OAuth/MCP setup,
Stable operation or database write is part of this command. Missing/unmigrated
databases fail without repair. Automated checks use external synthetic profiles
only. Independent data/privacy review and exact-candidate CI remain separate
from Owner export/UAT and connection verification.

Google Sleep may be requested without a technical ID with
`CombinedEvidenceRequest.sleep_google_auto_select=True` or CLI
`--sleep-google-auto-select`. The exact Sleep override still takes precedence.
This delegates to the same [Sleep selection contract](METRIC_SOURCE_SELECTION.md);
Activity selection and omitted-provider behavior are unchanged. A blocked Google
choice remains a labelled section with selection evidence and `source_range=null`,
and is preserved in both JSON and text.


## Opt-in compact projection

For a 30-day local query, add `--projection compact` to either destination mode:

```text
python -m healthcheck.export_combined_evidence \
  --profile <existing-explicit-profile> --profile-kind synthetic \
  --end-date 2099-01-31 --days 30 \
  --activity-garmin-source-id <activity-id> \
  --sleep-garmin-source-id <sleep-id> --sleep-google-source-id <google-id> \
  --evaluation-local-date 2099-01-31 --projection compact --stdout json
```

Python callers set `CombinedEvidenceRequest(..., projection="compact")`. The
omitted/default `projection="detailed"` preserves the existing v1 packet shape,
hash contract, validation and serializers. Compact uses the distinct version
`health-chat-combined-compact-evidence-v1` and hash-bound `projection` metadata;
it is a summary projection, not a detailed interval replay packet. Both modes
use the same accepted readers in the same read-only snapshot, before the
unchanged 2 MiB UTF-8 serialization guard. Compact does not call the capped
public detailed serializer first. No byte cap is raised and no winning prefix
is emitted. An oversized compact packet still fails the complete request.

Only Sleep representation changes:

- Daily ranges, series/values, units, metric states/reasons/eligibility, explicit
  zero, missing/null/partial/ambiguous states, candidate/excluded record IDs,
  roles, source identity/selection and acquisition-coverage limits stay intact.
  All saved sessions remain; `summary_record_id` replaces the duplicate night
  `summary` object, referencing its saved session or null when ambiguous/absent.
- Every metric retains its scalar fields. Exactly equal evidence fields across
  that session's metrics move once to `evidence_common`. Reconstruct a metric's
  summary evidence by overlaying its own `evidence` over `evidence_common`.
  Replace `field_paths_index` with the exact path list at that index in the
  session's `field_path_sets`; repeated lists are stored once without dropping
  paths. Indices are local to each session and bound by the envelope hash.
  Record/observation/normalization identities, source eligibility, field paths,
  immutable metadata and content hashes remain bound to the packet.
- Per-metric `interval_ids` and `interval_snapshots` become `interval_summary`:
  exact counts, groups by interval kind/state and endpoint precision, and SHA-256
  of canonical UTF-8 JSON `{interval_ids, interval_snapshots}` using the existing
  canonical encoder. This summarizes stage/out-of-bed detail without new sleep
  formulas. Counts/digests describe all contributing intervals; they do not
  silently retain only a prefix. The digest identifies omitted detail but cannot
  reconstruct it or establish independent source correctness.
- `interval_summary.session_intervals` retains original `sleep_session` endpoint
  snapshots, including offsets, wall time, timezone, precision and state. Session
  `temporal_evidence` and accepted start/end metric cells also stay intact.
  Date-only/null timing gains no invented instant or host offset. Stage segment
  endpoints/IDs are intentionally available only in detailed mode.

Activity cells (including coverage/conflict/incomplete-search flags), current
Context revisions/text/temporal precision and explicit page bounds/has-more,
profile/privacy assertions, unknown verified-snapshot/Stable identity, requested
and effective dates, cooperative limits and interpretation boundaries are
unchanged. Compact text includes the projection identity and the same selected
facts/comments as JSON; full summary provenance stays in its matching JSON.
No daily causal join or source pooling is added. Original comments remain
untrusted data, never tool instructions.

The persisted synthetic size regression includes 30 Garmin nights, 30 Google
nights with 60 seven-minute stage intervals each (within the existing parser
cap), daily Activity and 50 Unicode comments plus additional rows proving the
Context page bound. Detailed JSON exceeds 2 MiB while compact JSON stays below
1.5 MiB, with every daily point and selected comment preserved. This proves that
representative workload, not a universal size/latency guarantee or Owner UAT.
