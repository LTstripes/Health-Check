# Workspace recycle: production contract decision packet

Historical Windows Bin research. The Integrator subsequently accepted recoverable
root-container relocation under [the narrower retirement contract](WORKSPACE_RETIREMENT.md).
The Bin NO_GO and immutable-tree investigation below do not reject that new contract.

Status: **NO_GO for production implementation/rollout under the current constraints**.
This is the reviewable result of investigating a drop-in safe transition, including
deterministic counterexamples. It is not an accepted architecture or a schedulable
recycler. The Owner requested concrete alternatives if equivalent protection needs
a substantial architecture change. No guard is weakened and no existing Owner/task
workspace is recycled.

## Required boundary

Daily recoverable cleanup must use Windows Recycle Bin, never permanent deletion
or an empty/purge operation. Preserve fixed immediate-child roots, no-follow pinned
physical identity, clean/private/process/publication guards, explicit completion
and seven days since both completion and relevant activity. Preserve active,
paused, unknown, legacy, dirty, unpublished and shared worktree material. Stable,
Main, Test, UAT, Owner, Ops, staging, runtime, backups and recovery remain excluded.

Resume and cleanup use the same existing project mutex for the whole transaction.
No timer, missing PID, released marker, PR state or backdated adoption completes an
existing folder. No new ACLs, elevated token, credentials, broker/service/driver or
third-party dependency is authorized. Finance acceptance remains independent.

## Documented API investigation

| Mechanism | Documented guarantee | Missing production guarantee |
| --- | --- | --- |
| Existing native directory pins, share=3 | Other opens cannot request DELETE; current handle identifies the inspected object | Shell cannot rename/recycle while that pin remains |
| IFileOperation DeleteItem + FOFX_RECYCLEONDELETE | Queues a Shell-item operation with recycle intent | No existing filesystem-handle or expected-FileId compare-and-recycle argument |
| PreDeleteItem | May veto before the operation | Identity can change after callback approval and before Shell acts |
| PostDeleteItem | Non-null new item identifies a recycled item; item HRESULT is distinct from queue success | Post-action verification cannot prevent acting on the wrong replacement |
| IFileSystemBindData2.SetFileID | Supplies cached filesystem information to ParseDisplayName | No documented conditional-delete/identity-enforcement guarantee; this is not an object lock |
| OpenFileById | Opens a filesystem handle matching the specified identifier | That handle cannot be passed to IFileOperation as its source |
| FILE_RENAME_INFO with SetFileInformationByHandle | Renames through an existing source handle; can refuse destination replacement | A filesystem rename is not registration in Windows Recycle Bin or normal Bin restore |

No documented equivalent drop-in was found. This is a conclusion about these APIs
and the tested route, not a claim that every conceivable Windows design is impossible.

## Reproduced evidence, not just a theoretical window

The existing probe is extended with hooks available only inside newly generated,
small synthetic fixtures. The identity check and real Shell call are unchanged;
the test deliberately swaps the checked object after the check returns success.
It never receives an existing arbitrary deletion target.

| Case | Observed result on D: NTFS / ordinary Windows PowerShell 5.1 STA |
| --- | --- |
| Existing share=3 pin retained | Shell recycle is refused; fixture survives |
| Replacement before identity check | Veto; original and replacement survive |
| Replacement after identity check | **Shell recycled the replacement, not the inspected object**; receipt FileId differs; moved synthetic item restored |
| Junction substituted after identity check | **Shell recycled the substituted junction**; receipt identity differs; decoy contents survive; moved synthetic item restored |
| Cancellation injected in PostDeleteItem | Operation reports failure although item already moved; non-null recycled receipt permits explicit restore; no retry |
| Restore destination occupied | Refused without overwrite/merge; collision contents survive; receipt restored to a separate vacant owned path |

Aggregate `GetAnyOperationsAborted` was false even for the injected post-move
failure; item HRESULT/COM failure and receipt must also be retained. An error is
not evidence that nothing moved. No timed or automatic permanent fallback exists.
Source audit checks that the probe has no permanent-delete or Bin-empty primitive;
this audit is not a proof about every Shell policy/quota failure.

The mutex harness uses the production lifecycle helper on fresh bound synthetic
clones and actual Shell round-trips on separate owned GUID fixtures under the same
test mutex. Resume-first excludes entry to the Shell boundary. Recycle-first
excludes Resume. A child exit after a durable `deleting` record leaves retirement
intact after abandoned-mutex acquisition; Resume is refused. Every successful
child has explicit native exit 0. The parent retains an observer handle through
child exit, explicitly catches AbandonedMutexException on that same kernel object,
releases it, and then verifies that the production Resume refuses retirement.
These prove the coordination primitives only:
they do not pretend that the unsupported eligible-workspace recycle transaction
or a new restore/Claim protocol has been implemented.

The first mutex attempt failed on native exit evidence. Its logs and failure are
retained. A small exit-code diagnostic produced 0 both with and without an early
handle, so it did not explain/reproduce that failure. Later focused runs capture
the child handle before releasing its wait and pass; no old failure is relabeled.

The later successful Go review of the older probe is separately
[triaged against source and primary enum facts](WORKSPACE_RECYCLE_REVIEW_TRIAGE.md).
Its useful harness/receipt observations are applied; its incorrect numeric mask
and file-reparse assertions are not applied. Current tests use fresh marked temp
roots outside Git metadata, with measured PreMove flags and explicit source
attestations. A late after-callback restore collision remains unproved.

## Concrete alternatives and constraints

| Alternative | Preserves current guarantees? | Windows Bin outcome | Decision needed |
| --- | --- | --- | --- |
| A. Retain strict guards and refuse unsupported recycle | Yes; current safe state | No automatic removal | Available now; no implementation/schedule pretending the request is complete |
| B. Handle-bound same-volume recoverable retirement to a journaled recovery area | Potentially; needs implementation and proof of source/destination pins, crashes and restore | **Not** Windows Bin; normal Explorer Restore is unavailable | A different architecture and changed user requirement; previously declined quarantine is not silently reintroduced |
| C. Handle-bound handoff, then Shell in an exclusively enforced staging namespace | Original retirement can bind to the checked object; Shell-stage identity and exclusive access still need proof | Bin restore initially returns to staging, requiring a custom original-path recovery protocol | Substantial new state/journal/security architecture; cannot assume a random GUID provides isolation or add ACLs/broker under this task |

Direct Shell + mutex + another last identity check is **rejected**, not an accepted
fourth option: the deterministic replacement cases disprove equivalence. A FileId
cache, a successful round-trip, or checking the recycled identity afterward does
not repair that result. Manually writing undocumented `$Recycle.Bin` metadata or
using an unverified deletion utility is also outside the permitted solution.

B and C are proposals only. No handoff/quarantine directory, security change,
retirement move or new production state is implemented. C cannot be considered
safe merely by moving the race into Ops; actual equivalent enforcement is required.

## Contract gates before any future B/C implementation

1. Choose and accept the architecture, including whether ordinary Windows Bin
   Restore must return directly to the original workspace. Keep the no-permanent-
   fallback invariant; no background purge/empty operation.
2. Define bounded total bytes, entries, tasks and per-run work, fixed same-volume
   local NTFS context, normal logged-in user and unavailable-Bin/quota handling.
   The present probe covers tiny owned files only, not arbitrary tree capacity.
3. Define a versioned durable transaction record before the first retirement:
   original path, root/Git identities, enrollment/Claim/generation, completion HEAD,
   transaction ID, expected volume/context and known outcome/receipt. Hold the
   same mutex continuously; a pending/uncertain outcome is PRESERVE, never retry.
4. Define recycling/recycled/uncertain states and migration behavior. Old readers
   must fail closed; deploy matching helper/janitor pairs. Do not repurpose existing
   `deleting/deleted` tombstones or clear them to resume a path.
5. Define explicit recover-to-vacant-original-path semantics, no overwrite/merge,
   original identities/content proof and a new Claim/generation before work. An
   Explorer restore does not itself authorize Resume. Copy-restored changed IDs
   require a distinct fresh-workspace workflow, never forged enrollment.
6. Add end-to-end tests of the **chosen** implementation for both mutex winners,
   post-check path/junction replacement, cancellation before/after movement,
   process crash, partial/uncertain outcomes, restore collision, unavailable Bin,
   size/context limits and absence of permanent fallback. Current primitive
   evidence must not be relabeled as those unreached production checks.
7. Obtain complete independent review and project Integrator acceptance. Only
   then consider accepted-pair installation and a 12:00 local Interactive/Limited,
   IgnoreNew/StartWhenAvailable recoverable task with no permanent Apply argument.

## Delivery/rollout separation

Production helper/native source remains byte-identical to accepted #442. No
production recycle switch or scheduler action is added. Real workspaces moved: 0.
The complete research/contract/test candidate is reviewable; production code and
rollout are not ready. Publication is separately prohibited pending a useful
accepted candidate and explicit authority; no denied push/PR action is retried.
Finance receives an unapplied separate delta, not deployment or a PR. Its lifecycle
consumer and eventual architecture/implementation require its own Integrator.

## Primary sources

- [CreateFile sharing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [IFileOperation](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ifileoperation)
- [Operation flags](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags)
- [PreDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-predeleteitem)
- [PostDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-postdeleteitem)
- [IFileSystemBindData2](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ifilesystembinddata2)
- [OpenFileById](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-openfilebyid)
- [FILE_RENAME_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)
