# Saved Garmin observed daily Steps v1 (#377)

Contract: `garmin-observed-daily-steps-v1`, following the
[accepted bounded Steps decision](https://chatgpt.com/c/6ac9ecb7-a734-83ea-9040-8ad886eee940?messageId=858171b8-66dd-464c-b4f1-47a2a12e74c9).

`SavedDailyStepsRepository.project_day` is an explicit offline service over
already saved Garmin `daily_health` JSON observations whose source filename is
exactly `daily_summary.json`. It has no provider, sync, CLI, UI or analytics
entry point. The caller selects one existing source and one calendar date,
supplies the saved artifact store, and owns the database transaction. This slice
does not run a historical replay or alter collection policy.
The session must have no pending ORM changes; flushed writes may be used. A
physical SQLite transaction pins the compound read and remains caller-owned,
including rollback of newly derived records.

Only a top-level `calendarDate` with strict, valid `YYYY-MM-DD` spelling and a
top-level nonnegative JSON integer `totalSteps` are accepted. `observed_daily_steps`
has unit `steps` and account attribution. Coverage, device, timezone and finality
remain `unknown`; the date has no invented midnight, UTC offset or window.
Acquisition windows and received times cannot supply or reinterpret the day.
Booleans, floats (including integral floats), strings and negative counts are
invalid. Explicit zero is a value; null, absent and invalid are separate states.
An absent leaf means only `field_absent_in_payload`, never no steps in history.
Other fields, activity data, distance and nested envelopes cannot supply Steps.

The service verifies immutable raw/artifact/observation links, byte size and
SHA-256 before writing a typed record. It scans all eligible saved artifacts for
that source, because acquisition-window filtering could hide a conflicting
returned date. A configurable artifact bound (default 1,000) or per-artifact
byte bound (default 1 MiB), unreadable bytes or inconsistent provenance fails
closed before inserting any Steps records. Unsupported dates, malformed JSON,
duplicate JSON keys and unsupported shapes are returned as explicit exclusions
with saved observation references. They do not acquire a guessed date.

One derived daily record is identified by contract version, saved source, returned
day and immutable artifact hash. Identical acquisitions share that record while
retaining every acquisition observation. Different artifacts remain separate.
Their metric state and provenance persist in the existing Garmin daily-record
tables, on a distinct `observed_daily_steps` surface so ordinary daily-summary
reconciliation cannot replace or retire the evidence. Existing records are not
updated on replay. Original raw payloads and acquisition observations remain
unchanged. No schema change is needed. To avoid floating-point rounding, valid
counts use the existing metric `value_text` slot as a canonical decimal integer;
the service returns a typed Python integer.

One distinct valid count yields that observed value, even if repeated in different
artifacts. Two or more distinct valid counts yield `ambiguous` and no selected
value. Neither the latest, largest nor sum wins. Null/missing/invalid observations
remain visible alongside valid ones; they do not retract a valid observation or
prove correction authority. With no valid count, a homogeneous non-value state
is retained; mixed non-value states or no supported saved day yield `unavailable`,
with individual evidence preserved. This is a saved-observation snapshot, not a
full-day total, collection-status diagnosis, wear claim or promise about unsaved
history. No `not_collected` claim is inferred. Sources are never fused.

Synthetic acceptance cases cover zero/null/absence/invalid types, exact integers
above floating-point precision, repeated acquisitions, divergent values in either
arrival order, same-count artifacts, mixed presence states, source/day/surface
separation, date-only precision, unsupported dates and shapes, fail-closed bounds
and artifact integrity, and ordinary reconciliation retaining Steps evidence.
Google Steps, device fusion, correction selection, timezone conversion, statistics
cards and Calories/Energy are outside this contract.

## Read-only materialized window

`read_observed_steps_window` in `garmin/observed_steps_read.py` returns one cell
per exact civil date in an explicitly selected Garmin source/window. It never
calls `project_day`, opens saved bytes, materializes records, commits, selects an
automatic source, seeks a latest value, or aggregates days. The caller owns the
read snapshot. This reader is not yet connected to Statistics or another UI.

Windows contain 1–366 inclusive calendar days; larger/reversed windows and
missing source selection are rejected. The independent reader contract is
`garmin-observed-daily-steps-window-v1`. Each request reads at most 4,097
candidate/history records on the `observed_daily_steps` surface, including
retired/unsupported records, using the 4,097th only to detect the 4,096-row cap.
The singleton metric/raw/artifact metadata joins cannot multiply candidates.
A second independent cap+1 query reads up to 4,097 eligible saved acquisition
observations for these raw identities; repeated raw references do not multiply
provenance rows. This cap is reader-local, not an analytics/annual-read budget.

Ascending date order establishes complete earlier groups. A truncated candidate
day and subsequent unexamined dates yield `search_incomplete` with no value.
A truncated provenance day and later candidate groups also yield
`search_incomplete`; independently complete cells remain usable. Unsupported
materialized contracts, absent metric/acquisition links and inconsistent
provenance fail that day closed. Returned evidence on incomplete cells may be
partial and does not establish group completeness. Counts describe examined
rows, including the detection row, rather than total history size.

Complete cells preserve the projection's distinct valid-count resolution and
missing/null/invalid evidence, including exact integer text storage and zero.
Without materialized day evidence the cell is `projection_unavailable` with
reason `not_evidenced`, never a claim that projection was not run, the leaf was
missing, collection never occurred, or Steps were zero. An unknown exact source
uses `source_not_found`. Coverage, device, timezone and finality remain unknown.
Persisted provenance references and contract versions are retained; the reader
does not re-verify artifact bytes or attest completeness of unsaved/unprojected
history. No schema, replay, collection, ledger or migration contract changes.
