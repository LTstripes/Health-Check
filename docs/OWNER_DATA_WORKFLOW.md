# Owner data and efficient task execution

Owner decision: 2026-10-10. This is the standing workflow for Owner-requested analysis,
diagnosis and UAT; it clarifies earlier blanket restrictions on private-data visibility.

## Data access and presentation

An Owner request to analyze, diagnose or visually verify their data authorizes the
assigned assistant to read the relevant real records, reports, documents, screenshots
and UI in the assigned context. Use ordinary local viewers, browser tools and model
vision/text in the authorized assistant conversation. Do not ask again for each
record, image or query. Values, dates, names, identifiers and local paths are not
credentials merely because they are personal. Show the facts needed to answer the
Owner without compulsory masking or opaque surrogate labels.

Keep real datasets and working reports in the assigned Owner-data location outside
the tracked code checkout. A code task that needs Owner evidence can perform an
authorized read-only diagnostic there; it need not pretend that all useful evidence
is synthetic. Automated tests/CI and committed examples still use synthetic data.
Do not copy or link runtime databases into code fixtures. Read-only database work
uses an appropriate read-only connection and must not run migration-capable startup.

Access credentials, tokens, recovery keys and real `.env` contents are not report
material. Do not print them. Public GitHub/CI publication and sharing to another
recipient are separate from showing relevant data to the Owner in the authorized
AI conversation. Ordinary task authorization is not permission to publish a whole
dataset; follow a specific Owner publication request when one is given.

## Reads, runtime changes and data writes

Reading/analyzing assigned data does not authorize database writes, migrations,
reimports, semantic attestations, production changes or destructive operations.
Those require the applicable task authority. Once the Owner has authorized a bounded
operation, carry out its necessary reversible steps without repeated consent.
Normal code checks do not call account-backed providers. Live provider operations,
runtime preparation/start/stop and external connections use their assigned scope.
Stable remains durable; candidate runtime validation uses an isolated approved clone.

## One writer per physical checkout

Before editing or local verification, claim the canonical physical checkout with
the current chat/task identity using the available local ownership helper. Check
the claim before commit/push and release it at handoff or cancellation. Concurrent
claim acquisition must be atomic. Never steal a claim because a timer elapsed or
adopt another chat's identity. A paused task retains ownership until handed off.
If occupied, use a fresh authorized checkout; read-only remote review can continue.
The helper is cooperative coordination, not an OS lock against arbitrary editors.
If the helper is unavailable, use a freshly created uniquely named checkout and
record its owner once; do not turn missing tooling into repeated approval requests.

## Review and proportional verification

Read-only review preflight checks actual Git/source access, not just configured
permissions. Keep environment readiness, source identity and model findings distinct.
Receiving a final model message is not a review PASS. On setup/access failure, save
the diagnostic and repair the cause before one new preflight. Do not repeatedly
launch model reviews with the same broken environment or enlarge packets to disguise
missing source access. Required review remains required; retain useful prior findings.

Routine prose/UI work does not acquire a second reviewer, a full local suite or real
runtime UAT merely because an agent can imagine a risk. Apply the existing risk and
verification policies. Reuse applicable evidence with its original candidate/scope;
rerun only invalidated or missing checks, including explicitly required CI gates.

## Offline evidence and runtime continuation

Declare whether the task reads saved evidence or evaluates a running application.
An offline clone audit needs code/clone/checkpoint identity and the required database
checks; it does not need a listener or running UI. Runtime verification additionally
needs a current process identity (PID plus creation time/executable), endpoint and
evidence binding the loaded code and selected data/profile. `/healthz`, a Git SHA,
an old PID or a matching filename alone does not establish that binding.

Keep a small local receipt of observed identity and completed steps with evidence
references. On continuation, validate only dependencies of the next step. Changed
code/data/process or modified evidence invalidates affected results; a new chat or
lost polling session alone does not. File hashes do not prove database integrity,
and process metadata does not prove application/profile binding. Preserve those
limits rather than rerunning unrelated work or claiming fresh success.

## Concrete blockers

Every STOP/approval request identifies the actual missing authority, conflicting
contract or reproducible failure and the smallest next action. General discomfort
about personal values is not a blocker. Continue independent authorized work.
Do not add mandatory report fields or new gates beyond what the task needs.
