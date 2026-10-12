# Context Capture v0

Context Capture stores small owner-authored health and lifestyle notes as local,
append-only evidence. It is a persistence and retrieval boundary only: v0 does
not interpret text, infer dates, assign AI tags, correlate context with health
metrics, or add context to reports.

## Evidence contract

- A logical event has a stable UUID and exactly one current revision pointer.
- Revision rows and their tag assignments are append-only. Revising an event
  creates the next numbered revision and atomically advances the pointer; prior
  text, time, capture source, and tags remain queryable with `--history`.
  Omitted tags retain their status and original provenance on a revision;
  explicitly supplied tags become confirmed under the new capture source.
- Original text is required, is stored without trimming or paraphrasing, must
  not contain NUL, and is limited to **4,000 Unicode code points**.
- An optional caller-supplied `--operation-id` makes an identical add/revise
  retry converge, including a partial revise retried after the current head has
  advanced. Identity binds the operation kind and explicitly supplied,
  normalized request fields; reusing it for different input fails closed.
  Generated and supplied operation IDs are returned by the CLI.

Supported explicit time forms are:

- one calendar date (`--date YYYY-MM-DD`), with no invented time or UTC;
- one ISO 8601 timestamp with `Z` or a numeric offset (`--timestamp`);
- a start/end date range, or start/end ISO 8601 timestamps carrying offsets.

`--timezone` optionally records an IANA zone for timestamp forms and validates
that the supplied local clock and offset are valid for that zone. Date-only
forms reject a timezone. Mixed-precision or reversed interval bounds fail
closed. Production persistence does not parse words such as `today`,
`yesterday`, or `last night`.

Capture sources implemented by v0 are `cli`, `manual` and `dashboard`. The
portal adapter uses `dashboard`; `telegram` remains reserved and rejected. Tags
are Unicode-normalized, case-folded, separator-normalized, limited to **64
code points**, and deduplicated. CLI tags are persisted with `confirmed` status
and their capture-source provenance. The schema can later represent
`suggested` and `rejected` interpretations without rewriting old revisions.

## Commands

The profile must already be migrated to Alembic head
`0013_context_capture_v0`.

```powershell
uv run --locked healthcheck context-add `
  --data-dir D:\path\to\profile `
  --date 2026-09-22 `
  --text "Synthetic note" `
  --tag tennis `
  --tag fatigue

uv run --locked healthcheck context-list `
  --data-dir D:\path\to\profile `
  --from 2026-09-01 `
  --to 2026-09-30 `
  --limit 50

uv run --locked healthcheck context-revise `
  --data-dir D:\path\to\profile `
  --event-id <event-uuid> `
  --text "Synthetic corrected note" `
  --operation-id <caller-retry-key>
```

List filtering uses inclusive owner-local calendar dates and interval overlap.
Ordering is deterministic and most-recent-first. The default limit is 50 and
the hard maximum is **200**. Add/revise success output omits the note text;
`context-list` deliberately returns context notes but never reads or emits
unrelated provider or health evidence. Validation/storage errors do not echo
the submitted note.

## Portal adapter — #294 Stage A

The loopback portal exposes `/context` through the primary **Комментарии** tab
in the existing desktop shell. It adds, lists and revises through Context v0;
no new schema, weight-goal settings, providers or migrations are introduced.

- The form preserves original Unicode text and shows an editable event date.
  Optional local time accepts `HH:MM`, seconds or fractional seconds. One
  human-labelled city/IANA selector supplies the zone; the server resolves each
  event-date clock separately, then validates the exact offset-bearing timestamp
  with the unchanged `parse_timestamp` / `parse_interval` contracts. City labels
  always include the IANA key to distinguish ambiguous names.
- DST gaps fail closed with the draft and operation key retained. Repeated clocks
  show an explicit first/second occurrence choice with its actual offset, separately
  for each ambiguous interval endpoint. A changed endpoint/zone clears its previous
  choice. Intervals keep equal precision and strict UTC ordering under v0.
  Date-only input hides/disables the zone, submits no zone/occurrence, and never
  fabricates midnight or UTC. Without JavaScript, entering time first shows the
  selector on validation readback; no temporal guess is made.
- **Сейчас** explicitly populates browser-local date/minute and proposes the browser
  IANA zone for review; it performs no location lookup or proof of the user's city.
  The initial visible date uses the host calendar; it can be changed before saving.
  Event time/precision and automatic recorded-at UTC are displayed separately.
- An edit whose event fields match its authoritative expected revision omits the
  temporal argument to `revise`. This retains source spelling (`Z` / numeric zero,
  seconds and fractional trailing zeros), precision, UTC, offsets, IANA absence and
  tags exactly, including on old retries after the head advances. Offset-only legacy
  records show their original time and have no invented city/zone; changing their
  time requires an explicit IANA choice. Historical second-level offsets are never
  rounded: unchanged records are retained, while newly resolved clocks unsupported
  by v0 fail validation. The service/schema semantics remain unchanged.
- POST/303/GET reads the committed current revision from storage. A hidden operation
  key supports identical retries and a submitting guard prevents double clicks.
  An older operation retry shows the latest current version with a notice and history
  link. A hidden expected revision and a serialized write transaction reject stale
  editors; the escaped draft is retained for comparison, never silently overwrites.
- Current entries use inclusive explicit date/interval-overlap filters (initially the
  last 30 days), most recent first, with a 50-entry bound and an overflow notice.
  A per-event history link explicitly requests the latest 50 append-only revisions;
  their currentness, revision number and source are visible. No deletion or AI tags.
- Existing UI Host/Origin protections apply to all writes. The adapter accepts bounded
  URL-encoded forms only (64 KiB; text 4000 code points), rejects duplicate/foreign
  fields, escapes rendered text, sends `Cache-Control: no-store` and uses generic
  validation/conflict/storage messages. Submitted text is retained only in the form
  draft/readback, not included in error diagnostics or logs.

Synthetic HTTP/service checks cover persistence across app restart, source/precision,
retry, stale/concurrent edits, history, escaping and negative input/security cases.
The browser check uses desktop Chromium 1024/1440 with an explicit disposable
synthetic profile; Owner rollout and durable-profile write/readback remain separate.

## Chat evidence — standalone Stage A implemented, transport later

The #294 portal adapter above is implemented. [#341 Stage A](https://github.com/LTstripes/Health-Check/issues/341)
now supplies a separate bounded read-only standalone Weight/Garmin-scalars/
current-Context evidence envelope without changing Context history, original
text or Period Brief hashes. Its command, privacy/output-path restrictions and
coverage limits live in [Health Chat Evidence](HEALTH_CHAT_EVIDENCE.md).
The first actual Owner export and explicit manual sharing remain UNVERIFIED;
there is no share button or authenticated direct ChatGPT connection yet.

The [#342 offline clone diagnosis](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6087155625)
is accepted as historical source classification, not a fresh provider recovery.
Source absence cannot be inferred from comments or repaired by a model.

Routine comments must be saved to the explicitly selected **durable Owner profile**
after a safe rollout. A note entered in a disposable UAT clone is not automatically
part of Stable and must not be silently discarded or claimed as a production note.
Implementation uses synthetic data only. Private exported notes are evidence for
Owner-selected discussion, never instructions for model tool execution or content
for public GitHub/CI logs.
