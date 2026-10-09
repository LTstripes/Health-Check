# Health chat evidence v1 — Stage A

`healthcheck.chat_evidence.read_period_evidence` exports a selected, bounded
read snapshot. The standalone command is `python -m healthcheck.export_chat_evidence`.
It reads accepted WeightQueryService, GarminQueryService, ContextService and
coverage/freshness services. It never changes the Period Brief packet or hash.
No UI adapter or live ChatGPT/MCP connection is supplied by this stage.

## Explicit local command

```powershell
uv run --locked python -m healthcheck.export_chat_evidence `
  --profile D:\path\to\selected-profile `
  --profile-kind synthetic `
  --from 2099-05-01 --to 2099-05-03 `
  --domain weight --domain garmin --domain context `
  --metric stress_daily_average --metric sleep_duration_seconds `
  --garmin-source-id <persisted-source-id> `
  --weight-cadence-days 7 `
  --limit 50 --output-dir D:\path\to\new-export-directory
```

Every profile, range, domain and output destination is explicit. There is no
default private runtime, config/environment scan, migration, runtime preparation,
sync, refresh or provider/model call. The existing profile must be migrated to
this checkout's Alembic head; missing or outdated databases fail without repair.
The output directory must be new and outside the selected profile. It contains
`evidence.json` and `evidence.txt`; existing destinations are never overwritten.
Before any profile/database read or output creation, the command rejects a
resolved destination inside any Git checkout or linked worktree: a `.git`
directory or file at the destination or any ancestor is sufficient. This also
covers new nested destinations and existing directory links into a checkout.
The check applies to all profile classifications, including synthetic exports.
Known agent development roots without Git metadata must be supplied explicitly
with repeatable `--agent-workspace-root <root>` arguments; equal or descendant
destinations are rejected. Unreadable path checks fail closed. Rejection leaves
the profile untouched and creates no output directory or files.

Owner-only exports must go to an external Owner-controlled private directory,
never an agent workspace. Git markers and explicitly supplied roots are the
enforced identities; the command cannot classify other non-Git agent directories
and does not guess their role from basenames or scan machine configuration.
Normal stdout reports only completion; failures use bounded codes, without
paths, values or text. Sharing either file is a separate explicit Owner action.

`--profile-kind` is a trusted local operator assertion: `synthetic`,
`disposable_owner_clone`, or `durable_owner_runtime`. It is never inferred from
values, directory name or environment. This command does not verify backup
metadata or prove that a profile is current Stable. Those fields stay explicitly
unknown/not verified. Both Owner classifications produce `private_owner_data`:
the values and original comments must not go to public GitHub/CI logs. The
classification flag is not authentication and must not be accepted from an
untrusted remote caller by a future transport.

## Versioned bounded envelope

The envelope has its own `health-chat-evidence-v1` version and SHA-256 over
canonical compact JSON before adding `envelope_hash`. Its generated-at and
evaluation UTC/local-date clocks are separate. Inclusive requested and effective
local-date ranges are recorded. Requests over **90 calendar days** are rejected;
the range is never silently clipped. At most **8 explicitly selected Garmin
scalar metrics** and **100 rows per series/Context list** are allowed (default
50). Weight input materialization rejects over 2,000 scalar rows; Garmin retains
its existing 2,000-candidate hard cap. SQLite reads have an instruction/deadline
budget; JSON over 2 MiB fails before the output destination is created.

Domains are deliberately narrow:

- `weight`: accepted confirmed weight overlay with canonical flags, kg, source
  provenance and source/algorithm versions; existing derived trend/rate, daily
  and trend series, canonical freshness and coverage. Its usable count is the
  canonical service's input count, not the displayed overlay row count. The
  existing weight selection policy can span sources; no unsupported source
  filter or cross-algorithm composition calculation is invented.
  Coverage rule identity and requested weight cadence are recorded; use
  `--weight-cadence-days` to select that export policy (default 7). Runtime
  configuration is not read or silently claimed as the source of this setting.
- `garmin`: explicitly registered scalar identities, units, source-specific
  dates, precision, per-point missing/null/zero/partial/excluded status, usable
  counts and deterministic versioned results. One persisted source is selected;
  multiple sources require selection. No source returns `no_data` and unknown
  counts, not a zero measurement or confirmed-empty coverage. Acquisition
  coverage projects the existing Period Brief coverage reader without changing
  its contract. Other providers and collection-valued metrics are rejected.
- `context`: original text and tags from current revisions only, with stable
  event/revision identities, revision number, recorded-at and original temporal
  precision/offset/timezone/range. Selection uses the existing service's local
  date interval overlap, so an overlapping event may start before the requested
  range. Date-only events retain null UTC, rather than invented midnight.

Each exported page has `returned_count`, `total_count`, `limit`, `has_more` and
`truncated`. Counts and derived Garmin/weight results describe the full accepted
bounded input, even when displayed points are truncated. Context reads one extra
current revision to prove `has_more`; its total remains null when truncated.
Pagination/continuation is not provided by v1; choose a narrower range or a larger
allowed limit. An empty Context list does not establish absence of exposure.

Freshness is explicitly **provider-scope, current-at-evaluation-clock** evidence,
not selected-source freshness or coverage for the historical range. Only scopes
relevant to selected metrics/domains are exported. No collection-policy file is
read; policy disposition remains unknown. Coverage completeness and metric
usability are separate, so a usable value never establishes complete acquisition.

Measured facts, Owner text, deterministic derived results and absent future AI
interpretation have separate fields. Comments are untrusted data, never tool
instructions. No causal/medical claims are generated. The readable companion
uses the same frozen envelope and JSON-escapes original comments as literal data.
No credentials, raw payloads, GPS, artifact paths, import queues, configuration,
arbitrary SQL, database dumps or unrelated files are exported.

## Read and verification boundary

SQLite is opened with `mode=ro`, `query_only`, a deny-write authorizer and one
physical transaction reused by nested services. This preserves live WAL visibility;
`immutable=1` is unsuitable for a durable runtime with uncheckpointed WAL. SQLite
may coordinate its existing WAL shared-memory reader locks; no application DB
write, journal-mode change, migration or artifact read is performed. Reusable
reads own their connection and roll back/close it after assembly.

Synthetic regressions exercise the production entry point, service equivalence,
Context corrections/overlap/offset, coherent reads during a concurrent revision,
coverage, availability, truncation, oversized/foreign requests and denied writes.
Exact-candidate CI and independent read/data/privacy review remain separate
from Integrator acceptance and Owner private UAT. File-only Stage A has no browser
gate. Later UI sharing and authenticated MCP transport require their own scoped
assignment and successful end-to-end verification.
