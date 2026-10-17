# Old-head Go review: verified disposition

Input: substantive OpenCode Go opencode-go/glm-5.3 review of **9d5f780** only.
The retry completed successfully without auth/config changes. Its verdict was
FIXES_REQUIRED for that old prototype and NO_GO for production. It is not review
of the later contract-decision or this changed candidate. No old request is rerun.

Each proposed change was checked against the old immutable source, current source
and Microsoft documentation; the numeric changes below are not applied blindly.

| Finding | Disposition in the current candidate |
| --- | --- |
| 1. Alleged wrong recycle-intent bit | **Rejected numeric assertion.** Microsoft defines DeleteRecycleIfPossible as 0x80 and UseFullAccess as 0x40. Old code already checked 0x80. Named enum values now make this explicit. A recycle-intent bit still does not prove no permanent fallback under every policy/quota failure. |
| 2. Alleged wrong restore mask | **Rejected numeric assertion; accepted observability.** RenameExist=0x1, OverwriteExist=0x2, MoveAsCopyDelete=0x400, so the existing 0x403 mask was correct. 0x4 means AllowDecryption. Named flags retain the same mask; raw PreMove flags and callback observation are recorded. |
| 3. Fixtures inside task Git metadata | **Accepted hygiene improvement.** Fresh harness-owned roots are now created beneath an existing temp base; Git ancestors are rejected. Past retained fixtures/receipts are preserved, not moved/deleted or relabeled. The marker is not production lifecycle authority. |
| 4. Incomplete operation flag list | **Accepted.** Proposal discloses Silent and NoConfirmation on recycle, and their distinction from restore. |
| 5. Late restore collision can prompt | **Accepted limitation.** Tested occupied-destination refusal is before queueing. The after-callback race/possible confirmation UI is not proved safe; no auto-confirm flag is added. Production remains blocked. |
| 6. Missing FAIL receipt in the old round-trip wrapper | **Accepted.** Catch writes a flushed FAIL receipt with source/harness/support hashes and retained fixture location. Actual MTA rejection and non-temp/Git parent rejection verify this path. This is file-content durability, not a transactional crash journal. |
| 7. Static attestations resemble measurements | **Accepted.** Receipt schema 2 groups source/launcher attestations under source_attestations and labels their basis; observed identities, flags and results remain measurements. |
| 8. Latent COM declaration hazards | **Partly already resolved, partly fixed.** Current ItemPath already frees GetDisplayName CoTaskMem in finally. The unused HWND argument is corrected from uint to IntPtr. No owner window is set. |
| 9. Alleged file-symlink following | **Rejected source assertion.** Old and current CreateFileW always include 0x00200000 OPEN_REPARSE_POINT, before the directory-only BACKUP_SEMANTICS ternary. Normal Identity rejects reparse attributes. The test-only raw-identity helper deliberately observes an owned junction after the counterexample. |
| 10. PowerShell version labeled process identity | **Accepted clarification.** Field is powershell_version; harness requires Windows PowerShell 5.1. Native C# checks its own Windows/user/STA boundary and does not claim to identify a PowerShell host. |

Current measured flags on this one host/build: PreDelete 642 (0x282), PreMove 560
(0x230). The first includes 0x80 recycle intent; the second contains none of
0x403. Those observations do not establish behavior on every Windows configuration.

The important production findings remain valid: direct Shell operation lacks
atomic binding to the checked filesystem object; post-action receipt cannot
prevent a wrong-object action; cooperative mutex alone is insufficient; durable
production recovery/Claim semantics and size/quota/policy proofs remain absent.
Current deterministic counterexamples strengthen that NO_GO.

## Primary facts used for disputed items

- [TRANSFER_SOURCE_FLAGS](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_transfer_source_flags)
- [CreateFileW / OPEN_REPARSE_POINT](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [SetOwnerWindow / HWND](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setownerwindow)
