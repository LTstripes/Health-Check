# Sleep evidence service

`healthcheck.sleep_evidence.read_sleep_evidence` returns one structured
`health-chat-sleep-evidence-v1` package for an explicitly selected **7 or 30
inclusive calendar days**, plus optional existing current Context revisions.
The package is independent of transport and has its own version/hash. No file
is required. `encode_sleep_evidence` and `render_sleep_evidence` are optional
JSON/plain-text consumers of the same frozen package; neither writes files.

```python
from datetime import UTC, date, datetime
from pathlib import Path

from healthcheck.sleep_evidence import SleepEvidenceRequest, read_sleep_evidence

packet = read_sleep_evidence(
    profile=Path(selected_existing_profile),
    profile_kind="synthetic",  # trusted caller classification, not inferred
    request=SleepEvidenceRequest(
        end_date=date(2099, 1, 2), days=7,
        garmin_source_id=selected_garmin_id,
        google_source_id=selected_google_id,
        include_context=True, context_limit=50,
    ),
    evaluated_at_utc=datetime.now(UTC),
    evaluation_local_date=date(2099, 1, 2),
)
```

The caller supplies a trusted existing profile and explicit classification.
There is no profile discovery, environment/config scan, default private profile,
startup, migration, connection setup, refresh, provider call, schema change or
application database write. Missing/unmigrated profiles fail safely. This module
does not install a connector or make data reachable from ChatGPT/dot. An eventual
transport needs separate authorization and actual end-to-end verification.

## Request and exact sources

`end_date` is an exact `date`, and `days` is exactly integer 7 or 30 (not bool).
Start is end minus `(days - 1)`. Underflow and `date.max` are rejected. The
requested and effective inclusive local-date ranges are identical; no clipping,
earlier-period fallback or all-history mode exists. Evaluation clock is aware
and UTC-normalized separately from the explicit local evaluation date.

At least one provider must be selected. Each requested Garmin/Google provider
has **one explicit exact persisted source ID**; there is no auto-selection or
list of sources. IDs are nonempty strings within the existing 36-character
database identity cap. ALL selected IDs are checked in the same snapshot before
the first `read_source_sleep_range` invocation: existence in `GarminSource` or
`GoogleSource`, then provider code `garmin_connect` or `google_health`. Unknown,
cross-provider and incorrect-provider selections fail without a partial package.
An existing source without rows in the selected period remains valid empty
stored evidence. No unrelated source inventory is returned. No Garmin/Google
pooling, canonical selection, pairing, agreement or new metric formula occurs.

## Preserved reader semantics

Each provider section contains `selected_source_id`, provider identity, unknown
acquisition coverage and an allowlisted `source_range`. This calls the accepted
`source-sleep-range-v1` reader unchanged, including its exact date window,
source-local wake dates, gaps, ordering and hard caps. Explicit zero, missing,
null, invalid, partial, ambiguous and role-uncertain states are retained; excluded
sessions and per-point exclusions stay visible. Collisions never choose a
longest/latest winner. Google main/nap/CLASSIC/STAGES rules remain reader-owned.
Existing native Garmin sleep score and calendar-day nap identity stay separate.

The metric projection's accepted units and eligibility remain unchanged. Metric
cells preserve state/value/unit/field path, reason, zero, variant, comparison and
exclusion basis; timing evidence retains original precision, source-local dates,
timestamps, wall time, offsets and timezone. Date-only/null evidence gains no
invented midnight or current host offset. Accepted normalized seconds do not
become a new provider-native measurement.

Observed/missing dates and missing-wake-date counts mean **stored row presence**,
not complete acquisition or sleep absence. Null wake dates are located only by
the parent's persisted local date inside the window; unlocatable rows are outside
this bounded read. Acquisition completeness is explicitly unknown even when
every date has rows. Context absence does not prove absence of exposure.

## Explicit recursive whitelist and versioned provenance

The public projection is a recursive allowlist in `sleep_evidence.py`:

- `SOURCE`, `RANGE`, `NIGHT_SOURCE`, `SLEEP_SESSION`, `POINT`: exact source
  identity, typed nights, metric cells, role decisions, exclusions and counts;
- `TEMPORAL`, `INTERVAL`: source timing and typed interval evidence, including
  endpoint temporal precision and offsets;
- `EVIDENCE`, `NORMALIZATION`, `ELIGIBILITY`, `BASIS`: immutable record/metric/
  interval/observation IDs, metadata content hashes, source class/cohort and
  eligibility, normalization/reconciliation/source contract versions, attempt
  identity/fingerprints, source-evidence state/path/hash, and the prior device
  eligibility independently of the account-observation decision;
- `CONTEXT`: event/revision identities, revision number/currentness, original
  text, capture source, created-at, exact start/end temporal metadata and tags
  with their status/provenance. Operation IDs are excluded.

Unknown fields at every depth are dropped. Scalar leaves reject containers,
preventing arbitrary nested payloads from passing under a formerly scalar key.
`wake_date_missing_by_source` allows only the requested source's key. Provider
source-evidence bodies (`record_source_evidence`) are excluded; state/path/hash
and eligibility decisions retain the relevant audit identity. No credentials,
provider bodies, GPS, storage paths, configuration, arbitrary SQL, queue records,
debug dumps or unrelated files are included. These allowlists are disclosure
rules, not a scrubber for Owner-authored Context text: authorized original text
is preserved literally as untrusted data.

The package records `health-chat-sleep-provenance-v1`, the accepted reader and
metric contract/rule versions. SHA-256 uses canonical compact UTF-8 JSON,
excluding `envelope_hash`. JSON/text serialize the same frozen package; text
JSON-escapes literal Context text. Context is never tool instructions or evidence
of causality. AI interpretation is absent and causality is not established.

## Snapshot, limits and privacy

The existing `chat_evidence._read_session` owns one WAL-aware SQLite `mode=ro`
transaction, `query_only`, deny-write authorizer, current-schema check, 20-million
SQL instruction budget and 20-second deadline. All provider validation, nested
Sleep reads and Context reads share it. No `immutable=1` or normal write-capable
engine/runtime factory is used. Existing WAL/SHM read coordination is possible;
application writes and journal/migration changes are denied.

The existing reader caps remain **400 records per selected provider** and **200
per night**. Overflow preserves `read_limit_exceeded`, empty days/series and
unknown counts; no successful winning prefix or false completeness is returned.
The adapter does not slice Sleep nights/metrics after resolution. Context allows
1–100 current rows, default 50; reads one extra to disclose `has_more/truncated`,
with unknown total on truncation. Current revision selection uses existing local
date interval overlap, so an event can start before the requested window.

Existing 2 MiB JSON output guard runs before the structured package returns.
Text has the same byte maximum, including its explanatory header. Storage/query
failures surface bounded `EvidenceError` codes without logging data or paths.
Profile classification is a trusted operator assertion (`synthetic`,
`disposable_owner_clone`, `durable_owner_runtime`); Owner profiles are private.
Snapshot metadata remains unknown and current Stable identity is unverified.
The classification is not authentication. No automatic upload occurs.

## Compatibility and checks

Existing `health-chat-evidence-v1` responses, exporter, MCP tools/domains/schema/
auth, Sleep readers, Period Brief, UI and database schema are unchanged. This is
an additional service, not an extension of the currently deployed MCP surface.

Synthetic tests cover exact 7/30 equivalence, source/provider validation before
read, zero/missing/null/partial, main/nap exclusions and ambiguity, date/offset/
precision, null wake-date bounds, corrections and coherent concurrent reads,
reader/Context/byte/SQL/time limits, recursive privacy projection, no files,
no provider calls and denied writes. Exact-candidate CI and independent data/
privacy review are distinct gates. Real Owner export, live connector access,
runtime UAT and causal/medical interpretation are outside this implementation.
