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

Capture sources implemented by v0 are `cli` and `manual`. The schema reserves
`telegram` and `dashboard` for later adapters, but v0 cannot write them. Tags
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

## Planned portal adapter and chat evidence — Owner decision 2026-10-09

The v0 contract above remains the implemented baseline. The following are assigned
next capabilities, **not changes already available because this document was updated**.

- [#294 Stage A](https://github.com/LTstripes/Health-Check/issues/294) adds a compact
  portal form, recent list and revision history using this service. The original
  comment, visible editable event date and optional time/range are preserved;
  event time is not recorded-at. Date-only input must not become invented midnight.
  Dashboard capture-source activation is a narrow adapter change with provenance
  tests, not a second journal or unrestricted settings schema. Weight-goal settings
  stay Stage B and must not block comments.
- [#341 Stage A](https://github.com/LTstripes/Health-Check/issues/341) consumes current
  revisions through existing reads into a separate versioned, bounded health/context
  evidence envelope. It does not modify Context service/models in parallel with
  #294, alter original text, infer tags/exposure absence, or rewrite Period Brief
  hashes. A history view stays separately available when explicitly requested.
- P1 [#342](https://github.com/LTstripes/Health-Check/issues/342) diagnoses source
  availability concurrently as read-only research. Missing source records cannot
  be filled by a comment or silently inferred by the model.

The Owner requested documentation reconciliation before launching the three tasks.
Their existing short prompts remain valid; task/workspace/file ownership is in the
issues and [roadmap](ROADMAP.md#current-backlog). A future sharing button follows
accepted #294/#341 integration. Direct ChatGPT read access needs a verified
connection and explicit bounded consent; Telegram is not a prerequisite.

Routine comments must be saved to the explicitly selected **durable Owner profile**
after a safe rollout. A note entered in a disposable UAT clone is not automatically
part of Stable and must not be silently discarded or claimed as a production note.
Implementation uses synthetic data only. Private exported notes are evidence for
Owner-selected discussion, never instructions for model tool execution or content
for public GitHub/CI logs.
