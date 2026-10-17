# Combined Sleep + Activity + Context evidence

`healthcheck.combined_evidence.read_combined_evidence` returns a single bounded
`health-chat-combined-evidence-v1` packet. It composes the accepted
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
  unchanged public source section under `providers.garmin`;
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
