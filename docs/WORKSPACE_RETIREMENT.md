# Recoverable workspace relocation

The Integrator accepted this narrow contract on 2026-10-17 after the Owner chose a
separate recovery folder instead of Windows Recycle Bin. The existing Bin probes
and their counterexamples are historical research, not evidence for this consumer.
This candidate changes source only. Installation, real moves and scheduling need
separate project acceptance. Finance receives an unapplied delta independently.

## Object and safety boundary

Retirement relocates the same verified physical **root container with its actual
contents**. It is not an immutable tree snapshot, backup, free-space reclamation,
recursive deletion, or Windows Bin operation. No permanent delete, copy/delete
fallback, Shell, automatic restore or purge is provided. Recovery storage grows
until the Owner makes a separate decision; this task never removes its contents.

All existing eligibility guards remain: only newly enrolled, bound standalone
clones in fixed immediate-child roots; explicit completed state and at least seven
days since both completion and activity; current root/Git identities; clean,
published, private/runtime-free, inactive process state and recognized caches.
Active, paused, unknown, legacy, dirty, unpublished and shared worktrees preserve.
Stable/Main/Test/UAT/Owner/Ops/staging/backups/runtime/recovery are excluded.

Lifecycle, retirement, Recover and Restore hold the same project mutex throughout.
Resume-first invalidates eligibility. Retirement-first records durable intent and
v2 retiring state before releasing descendant handles. Root DELETE handle with
deny-delete sharing and real source/destination ancestor pins remain held through
the same-volume local fixed NTFS no-replace rename and post-inspection. No source
path is re-opened for the move. No destination is removed to make room.

Releasing descendants is deliberate: a root rename does not recursively act on
their handles or traverse a child junction. A noncooperative writer can still
change contents/membership, and Windows may refuse rename while other child
handles remain open. Refusal or uncertainty preserves and requires review, with
no fallback. This is cooperative coordination, not a new same-user security boundary.

## Observation and NEEDS_REVIEW

Before intent, retain a bounded metadata observation of the checked tree. After
rename confirm root identity and collect a bounded no-follow observation. Every
directory is inspected/pinned before enumerating its children; reparse, alias,
unsafe hardlink, inaccessible or over-limit material stops inspection without
traversing it. Known cache proof transfers only when the full metadata digest
matches the validated preflight; no new cache exception is inferred.

Observation files explicitly contain `NonSnapshot=true`. Relative paths,
identities, lengths, last-write timestamps and link counts form the digest; file
contents are not hashed. This does not prove unchanged bytes, a consistent point
in time, absence of a writer, or future immutability. Detected differences and
incomplete/unknown inspection are **NEEDS_REVIEW**. A matching observation is not
authority for any later deletion or purge. External modifications remain actual
container contents; relocation does not undo another process's writes.

Any observed change, unexpected original-path occupant, reparse/private marker,
inspection/observation bound, failure after intent or ambiguous result commits
`needs_review` in the journal and lifecycle. If a journal/state write itself fails,
the last prepared/retiring/restoring record still blocks all automatic consumers;
the caller reports error instead of claiming a new durable final state. Preserve
both objects when both locations exist. Never delete the new old-path occupant.
No automatic retry, restore, Resume or sweep of recovery occurs.

Every inspection, including explicit Recover and Restore preflight, retains a
verified root DELETE binding before its first descendant enumeration. A compatible
observation handle never substitutes for that binding. A closed journal is accepted
by ordinary consumers only after its fresh paused Claim/generation is committed
(or a later legitimate generation); closed journal plus old completed record stays
pending and cannot fetch, Resume or automatically retire again.

## Persistent states and recovery

Unchanged enrolled clients use lifecycle format 1. Retirement upgrades the target
record to format 2 with the same fields plus an ordered `Transaction` GUID.
Format 2 states are `retiring`, `retired`, `restoring`, `needs_review`; old v1
readers reject these records. The static enrollment marker remains format 1.
Deploy matching helper/janitor readers together; never deploy old automatic Apply.

The fixed Ops directory holds `workspace-retirement-<path-key>.state`, exact ordered
UTF-8/LF journal format 2: Format, Transaction, Path, Destination, RootId, GitId,
Enrollment, Owner, Claim, Generation, Head, Completed, BeforeDigest, AfterDigest,
BeforeObservation, AfterObservation, Phase, Issue, NextClaim, NextGeneration.
The destination is only `<fixed recovery root>\<transaction GUID>`. Phases are
prepared, retired, restore_prepared, restored, cancelled, needs_review. Claims are
local authority and must not be published. Closed previous journals are archived
before a new retirement cycle. Fresh observation names and pending files are not
lifecycle authority. Records use no-follow bounded reads and atomic flushed writes;
incomplete pending files are never promoted automatically.

`-Operation Recover -Workspace <original> -Owner <owner> -ClaimId <original claim>`
is explicit inspection/reconciliation, never a scheduled operation. It binds the
journal and record and inspects both fixed locations:

| Durable intent / observed object | Explicit Recover outcome |
| --- | --- |
| prepared, original only, expected identity/observation | cancelled; fresh paused claim, no move |
| prepared, recovery only, expected identity/observation | retired; no repeated rename |
| restore_prepared, original only, verified | restored; fresh paused claim |
| restore_prepared, recovery only | NEEDS_REVIEW; no restore retry |
| both/neither, changed identity/observation, existing NEEDS_REVIEW | preserve; NEEDS_REVIEW or reject |

An abandoned mutex permits this inspection, never a state reset. An API error does
not establish that nothing moved. Process-crash reconciliation is not a guarantee
against filesystem/media failure or a substitute for backup.

`-Operation Restore` is an explicit no-replace reverse rename from verified retired
root to the vacant original path. Intent and a fresh future Claim/generation are
durable first. The source root stays bound while descendants are released. Inspect
again after return; changes/uncertainty become NEEDS_REVIEW. A successful location
restore returns **paused**, not permission to write. The owner must Resume using
the new claim and CheckActive; changed enrollment/Git identities never acquire an
automatic new claim. NEEDS_REVIEW needs separate read-only assessment and a new
explicit recovery decision; this consumer has no override/adoption switch.

## CLI and bounds

Scan remains default; `-Apply` is refused. `-Retire` is the only move switch.
Scan retains its existing completed-candidate fetch behavior (local Git metadata
writes), so it must not be described as a strictly read-only filesystem scan.
At most 200 tasks, 25,000 entries per task, depth 128, 4 MiB per observation and
8 KiB per journal/claim. A bound is a preserve/review result, never truncation
presented as a complete manifest. No raw Git errors, process commands, real data,
file contents or credentials enter the structural latest report.

## Acceptance and activation plan

Validate synthetic eligibility, both mutex winners, root/path/reparse guards,
external content writes and new old-path occupants, destination/restore collisions,
double run, crash before/after both moves, explicit reconciliation and paused claim
issuance. Retain deliberate nonzero crash exits and actual abandoned-mutex evidence.
Review the frozen exact source/evidence independently; obtain exact CI. Old Shell
or historical immutable-tree results do not supply those passes.

After independent project acceptance, prepare the fixed same-volume recovery root
`D:\HealthCheck\recovery\workspaces`, install matching accepted source with rollback
copies while tasks remain absent/disabled, validate synthetic restore, and run a
fresh accepted-helper Scan. Do not label the historical 06:41Z scan as current.

Only after reviewing that scan may a separately accepted scheduler use:

- Name `Health-Check-workspace-retirement`; daily 12:00 machine local time.
- Current normal user, InteractiveToken/Limited, no password/credential grant,
  IgnoreNew and StartWhenAvailable; same existing project mutex.
- Windows PowerShell 5.1 hidden action:
  `powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File D:\HealthCheck\ops\workspace-cleanup\cleanup-workspaces.ps1 -Operation Scan -Retire -RetentionDays 7`.
- Structural log `D:\HealthCheck\ops\workspace-cleanup-latest.json`; durable claims,
  journals and bounded observations in the same Ops directory; moved containers in
  the recovery root. Recovery never appears among scan roots.
- Stop future invocations to roll back; preserve pending states and all containers.
  Never swap in an old janitor ignoring v2 claims or enable permanent Apply.

Finance requires its own accepted lifecycle consumer, fixed roots/recovery path,
project mutex, exact validation and Integrator acceptance. This Health plan is not
authority to install, merge, register a task or touch Finance runtime. Stable,
refresh and CBM are unchanged by this work.
