# Windows Recycle Bin feasibility — not a production cleanup implementation

Owner direction: automatically recycle eligible completed task folders daily,
without permanent deletion, ACL/credential/security changes or repeated approval
of every old task. Existing lifecycle, retention, private/runtime, Git publication,
identity and cross-process Resume/cleanup guards remain mandatory. No real folder
may be recycled before independent review and project acceptance. Finance needs
its own Integrator acceptance; Health acceptance does not grant it.

## Minimal implementation boundary

Keep the accepted production helper/janitor unchanged until identity binding is
resolved. Add separate Windows-only synthetic probes, not imported by the helper
or scheduled by Ops. Public probe operations create new random fixtures with
one constant synthetic file, limits it to 4 KiB, runs veto/locked-pin checks, then
performs an explicitly unpinned Shell recycle/restore round-trip. It never accepts
an existing deletion target, enumerates/empties the Bin, uses external software,
elevates or calls permanent deletion as a fallback. Restored fixtures remain for
read-back. Run with normal interactive Windows PowerShell 5.1 STA on a local fixed
NTFS volume. Fail closed on unavailable context, COM failure, absent recycled item,
collision, unexpected content or changed root/file identity. A post-action error
does not imply that an earlier action was undone; retain the fixture/evidence.

The probe uses IFileOperation with FOFX_RECYCLEONDELETE, FOF_SILENT,
FOF_NOCONFIRMATION, FOF_NOERRORUI, FOFX_EARLYFAILURE and FOFX_NOCOPYHOOKS on
recycle. Restore omits recycle/no-confirmation flags. PreDelete rejects missing
TSF_DELETE_RECYCLE_IF_POSSIBLE or changed identity; PostDelete must return an actual
recycled IShellItem and successful item HRESULT. Verify aggregate cancellation too.
Restore only that returned item to its vacant original parent/name via Shell,
with no rename/overwrite/copy-delete/elevation permission. This is feasibility
evidence for the deliberately tiny synthetic fixture, not an arbitrary-tree size,
quota, no-fallback guarantee or production API safety proof.

The PowerShell harnesses require Windows PowerShell 5.1; C# independently checks
STA/interactive/normal-user/local-fixed-NTFS context. FixtureParent is a temp base,
not a deletion target: the harness creates a fresh marked temp root outside Git,
and the native probe refuses Git metadata ancestors and unmarked parent roots.
The marker is test hygiene, never production enrollment or cleanup authority.
Success/FAIL receipts flush file contents and label source attestations separately
from measured flags/results. They are not a crash-safe recovery journal.

The tested restore-collision case rejects an occupied destination before Shell.
A collision introduced after the last callback check may still cause Shell
confirmation UI; the probe does not prove immediate fail-closed behavior for that
window. Do not add FOF_NOCONFIRMATION to restore to auto-answer that collision.

## Blocking contract issue

The existing native Tree holds directory pins with share=3, without
FILE_SHARE_DELETE, and binds permanent disposition to those handles.
IFileOperation accepts IShellItem, not the validated filesystem handle or an
expected FileId. Retaining the current pins blocks Shell rename/recycle. Closing
them or adding FILE_SHARE_DELETE admits a path/identity race. PreDelete checks and
PostDelete receipts do not create atomic check-and-recycle semantics. The current
project mutex serializes cooperating lifecycle participants but not unrelated
filesystem mutation. Do not silently weaken those guarantees to obtain a green
round-trip. Early independent design review is NO_GO for a direct replacement.

No temporary handoff/quarantine architecture is implemented or assumed accepted.
No new production CLI switch or schedulable recycle action is delivered by this
probe. The existing permanent Apply must never appear in the future daily task.

The subsequent [production contract decision packet](WORKSPACE_RECYCLE_CONTRACT.md)
records deterministic counterexamples, concurrency/failure evidence and the
architectural alternatives. It supersedes feasibility-only readiness assumptions.

## Production acceptance still required

1. Resolve and independently accept object-bound Windows recycle semantics without
   weakening no-follow/identity protection or adding security changes.
2. Prove supported volume/user/Bin policy and bounded bytes/entries/quota behavior;
   no permanent fallback, no timed purge and no retry after an uncertain outcome.
3. Define durable recycling/recycled receipts and crash states under the same mutex
   used by Resume. Never reset deleting/deleted tombstones or manufacture completed
   legacy workspaces. Preserve all current eligibility and seven-day guards.
4. Define accepted restore/Resume semantics for a vacant destination, preserved
   physical identity and a new Claim; no overwrite/merge or ad hoc registry edits.
5. Implement and independently review the final helper/janitor pair, run appropriate
   negative/concurrency/round-trip checks and obtain separate project acceptance.
6. Only then install accepted pairs and register daily 12:00 local InteractiveToken,
   Limited, IgnoreNew, StartWhenAvailable actions containing recoverable recycle
   only. Health and Finance rollout readiness remain separate.

Finance delta is this source-neutral probe and contract issue only; its current
canonical helper also lacks the accepted lifecycle/worker consumer. Do not bypass
that prerequisite, deploy the local candidate, publish a Finance PR or merge it as
part of the Health probe. Its Integrator must accept the lifecycle foundation and
the final recycle implementation independently.

## Sources

- [IFileOperation flags](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags)
- [PreDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-predeleteitem)
- [PostDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-postdeleteitem)
- [Transfer source flags](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_transfer_source_flags)
- [IFileOperation and STA](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ifileoperation)
- [CreateFile sharing modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
