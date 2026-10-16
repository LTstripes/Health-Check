# Managed workspace lifecycle and cleanup

This is the v1 cooperative protocol used by `scripts/cleanup-workspaces.ps1`
and its matching native `.fs.cs` file. It adds no service, credentials, ACL or
execution-policy change. Installation and scheduling require separate acceptance;
a source change is not proof of the currently installed version or task state.

## Scope and state contract

Only **new standalone task clones** in the existing four immediate-child roots
can enroll. `Create` atomically creates a fresh empty child (fail if it exists)
and commits an active record under the existing project cleanup mutex. It cannot
adopt legacy folders. Clone into that empty directory, then `Bind` validates Git
topology, expected origin and physical root/GitDir identities. Clones with dependent
worktrees and all linked worktrees are preserved **before fetch**: v1 does not
coordinate ownership of the entire shared Git Common cohort.

All writers must `CheckActive` their bound active claim before work, `Pause` when paused,
`Resume` before any further writes or verification, and `Complete` only after
delivery when no more work is intended. A paused task retains ownership. Complete
requires the same owner and current ClaimId, a bound clone and a clean, private-free
snapshot. It is an explicit lifecycle transition, not a timer, PID test, `released`
string, PR state or a loose completed marker. Publication is proved afresh by the
janitor; completing a locally committed unpublished branch cannot permit deletion.

`Resume` accepts paused/completed for the same owner and current ClaimId, atomically
changes generation and ClaimId and clears completion. Save its returned ClaimId.
Active `Check` itself does not grant ownership to a second task; never share a token
or adopt another task's owner identity. `Check` reports the recorded state; writing
is permitted only when it is **active**, with the current token. `CheckActive`
rejects unbound, paused and completed records. The worker consumer below deliberately
does not expose diagnostic `Check`. There is no v1
ownership-transfer/adoption operation; use a fresh unique task clone for a new owner.

The lifecycle and janitor use one project mutex through their entire transaction.
Resume-first invalidates eligibility. Janitor-first commits `deleting` before the
first unlink, holds the mutex through removal, then commits `deleted`. Resume and
Create refuse both retired states, including after an interrupted/partial deletion.
An abandoned mutex permits inspection; it never resets ownership or tombstones.
A busy mutex rejects immediately; callers may retry later without stealing a claim.

This is cooperative coordination under the existing Owner workflow, not protection
against an arbitrary editor or a same-user attacker bypassing the protocol. The
matching accepted janitor/helper pair and participating clients must be deployed
together; do not run an old janitor against managed roots. A client without the
helper may only create a fresh unique **unmanaged** clone and record its owner once;
it must never resume/reuse an enrolled path. Such fallback clones remain ineligible
for automatic cleanup. Existing fallback markers are not migrated automatically.

## Worker checkout workflow

The existing Codex, Hermes and Grok adapters use this one workflow when the task
explicitly selects **managed lifecycle v1**. OpenCode or other executors reading
the shared Owner workflow use the same entrypoint. The task assignment supplies
the accepted installed `$janitor`, configured client root/new `$task` child,
unique `$taskOwner`, official origin, pinned `$baseline`, `$branch` and delivery scope.
Owner identifiers use ASCII letters/digits, dot, underscore, hyphen (maximum 80).
These are task inputs, not new machine configuration or an executable launcher.
Do not use Stable, Test, staging, recovery or backups.

Dot-source the accepted installed script with its matching native helper, under
the existing PowerShell authorization policy. `Invoke-WorkerLifecycle` is the
worker consumer in that script: each operation acquires the existing project
mutex and either returns one claim object or throws. This avoids treating a stale
native `$LASTEXITCODE`, a JSON string or diagnostic Check as authorization to write.
If loading is denied by AuthorizationManager, stop and report that exact failure;
do not use ExecutionPolicy Bypass, Unblock-File, alternate hosts or evaluation of
the script text to evade it. Do not load a disposable checkout as the production helper.

```powershell
$ErrorActionPreference = 'Stop'
. $janitor
$claim = Invoke-WorkerLifecycle -Action Create -Workspace $task -Owner $taskOwner
# Retain owner/path/Claim/generation in the existing task checkpoint now.
git clone -- $officialOrigin $task
if ($LASTEXITCODE -ne 0) { throw 'clone failed; retain active claim for recovery' }
$claim = Invoke-WorkerLifecycle -Action Bind -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
$claim = Invoke-WorkerLifecycle -Action CheckActive -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
git -C $task switch -c $branch $baseline
if ($LASTEXITCODE -ne 0) { throw 'task branch/baseline setup failed' }
# CheckActive again before each bounded edit/test/commit/publication phase.
# Perform only the assigned work and its separately authorized delivery.
$claim = Invoke-WorkerLifecycle -Action Pause -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
# On continuation, use the same owner and the current checkpoint Claim:
$claim = Invoke-WorkerLifecycle -Action Resume -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
# Persist the NEW Claim/generation before continuing. The old Claim must fail.
$claim = Invoke-WorkerLifecycle -Action CheckActive -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
# Commit/publish only as authorized, retain the delivered SHA/resource receipt.
# Complete AFTER delivery exists and no further writes are intended:
$claim = Invoke-WorkerLifecycle -Action Complete -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
```

This is a sequence of explicit phase boundaries, not a script to run unattended
from start to finish. Do not Complete in a `finally` block, on failure, or merely
because a chat turn ended. If the client disappears before Pause, active remains
durable and preserves the checkout. Review fixes after Complete require Resume,
the new Claim, then CheckActive before edits. Missing/stale task checkpoint or
unknown ownership means preserve, never borrow another task's token or identity.
The checkpoint is a resume receipt, not cleanup authority; the external registry
remains authoritative. A local-only delivery can Complete but remains protected
by the janitor's independent unpublished-history guard.

A short task prompt can select this workflow without a new launcher:

```text
Worker: <repo / issue / accepted note>, baseline <SHA>, target <branch>.
Use a NEW task clone under <configured client root>, branch <task branch>.
Lifecycle: managed v1, accepted helper <Ops script>, owner <unique task identity>.
Follow WORKSPACE_LIFECYCLE.md#worker-checkout-workflow through Invoke-WorkerLifecycle.
Keep current Claim/generation in the task checkpoint; require CheckActive before work.
Delivery: <local-only or explicitly allowed branch/PR>. Complete after delivery.
Do not enroll an existing platform checkout or operate on runtime/Owner folders.
```

There is no platform task-created/paused/resumed/completed hook in this API. The
executor must execute the boundary calls in its task/checkout workflow; a prompt
cannot intercept a platform event. A platform-created checkout already exists,
so Create refuses it. Keep it unmanaged, or use a separate fresh authorized clone
for managed work; never claim automatic enrollment or move an active checkout.
Existing worktrees stay outside managed v1. Client root/helper-path selection and
adoption of these prompts remain explicit setup/rollout steps; this change does
not edit app configuration, install Ops, register tasks or activate scheduling.

The standalone CLI retains diagnostic `Check` and also accepts `CheckActive`.
Diagnostic success alone is never a write guard. Scan is the default; real scan
or Apply is a separate authorized operation, not a worker completion hook. Finance
derives roots from the accepted installation directory, so source execution inside
a disposable checkout is not an Ops install.

## Persistent format and failure handling

The fixed Ops directory holds `workspace-claim-<sha256-canonical-path>.state`.
Each v1 record is UTF-8 without BOM, LF-terminated, with exactly these ordered
`Name=Value` lines: Format, Path, RootId, GitId, Enrollment, Owner, Claim,
Generation, State, Head, Completed. Path is UTF-8 base64 of the canonical lexical
Windows path in invariant uppercase (one representation for case variants); identities
include volume/file index and creation timestamp. GitId is `-` until binding.
Enrollment/Claim are fresh lowercase 32-hex GUIDs; Generation is 1..999999999;
State is active, paused, completed, deleting or deleted. Completed is UTC ticks
and Head is a commit hash for completed/retired states, otherwise both are `-`.

The static `.git/workspace-enrollment.state` has exactly the first five fields.
It proves pairing to the external record, not completion. Unknown versions/fields,
duplicates, malformed records, missing registry/marker, copied markers, identity
changes and legacy `.git/codex-owner.json` (file or directory) all fail closed before fetch/delete.
Worktree pointers, aliases/reparse points and non-cache hardlinks remain protected.

No-follow bounded reads, pinned physical ancestors, fresh exclusive temporary files,
flush-to-disk and same-directory atomic write-through rename replace whole records.
State is never truncated in place. A process crash sees the old or new full record;
incomplete `.pending-*` files are not authority. Do not rename one into authority.
Create or Bind failing midway leaves an unmanaged/unbound/active folder preserved.
Leave uncertain/deleting records intact for manual read-only recovery assessment;
never clear a record, forge completion or re-enroll that path to make cleanup pass.
Tombstones remain outside deleted folders; use a new unique path for new work.

## Cleanup guards and operation

Eligibility needs a matched **completed** record, unchanged completion HEAD and
physical root/GitDir identities, and at least seven days since **both** completion
and the newest relevant file/commit activity. Resume creates a new completion cycle.
All existing clean/untracked/ignored/cache, private/runtime, process, origin,
publication/local-ref and handle-bound deletion guards still apply. No broader
cache exception or root is introduced. Unknown, active, paused, dirty, unpublished,
private/runtime, backup/recovery and reparse material is preserved. Stable/Test,
staging, backups, Ops and unapproved workspaces are outside the allowlist.

The bounded `workspace-cleanup-latest.json` remains the structural run report. A
deletion error stops the sweep; its durable deleting record prevents automatic
Resume/retry. Dry-run does not change lifecycle state, but eligible completed clones
still fetch local origin tracking refs. No server/DB/process lifecycle is managed.

Rollback before deployment is simply to retain the currently installed version and
leave all schedules disabled/unregistered. After a separately approved deployment,
stop future scheduler invocations and preserve records for inspection; never roll
back to a janitor that ignores managed claims while retaining automatic Apply.
There is no undelete or automatic retirement reset. This candidate does not authorize
registration, installation, real Apply, runtime start/stop, DB writes or security changes.

Windows synthetic regressions cover both mutex winners, stale claims, paused tasks,
malformed/unknown/copied metadata, identity replacement, pending writes, durable
deleting/deleted states, abandoned mutex, shared worktrees, existing guards and an
actual eligible synthetic deletion. Fixtures are under an exact harness-owned temp
root; no Owner/runtime data is used.
