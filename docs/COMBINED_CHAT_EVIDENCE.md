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
explicit Garmin source. Sleep requires at least one provider, with one explicit
Garmin and/or Google source. The Garmin choices can coincide or differ; they
are separate explicit selections and never pooled. All IDs are validated for
existence and provider in the shared snapshot before either domain reader runs.
No inventory or automatic source selection is exposed. Existing empty sources
remain valid empty stored evidence; an unavailable selected ID fails the request.

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
