# R02 post-56 targeted revalidation

## Checkpoint A — baseline and probe plan

IN PROGRESS. Review only F1–F4, not a general #56 audit.

- Remote main verified by git ls-remote: `c6f48d26a9eefee73b52f68835d931cce7b18388`; audit worktree pinned to that exact commit.
- Previous remote audit verified: `83cc2ac4e515bdb5a83e23192853148e931def3f`; report read from that object. Its reviewed integration was `aea777e418d8d16c275a860c31b11c72641a73e6`.
- New branch: `audit/r02-garmin-post56-revalidation-astra`.
- Read current AGENTS.md, #56 GitHub body (CLOSED), current R02_COLLECTION_RECONCILIATION_CONTRACT.md, scoped sync code and ROADMAP pre-R03 prerequisites.

| Finding | #56 change mapped in current code | Verification plan |
| --- | --- | --- |
| F1 pagination | sync.py `_fetch_activities` now returns `complete=False` for truncation; `_collection_scope` uses it for retirement. `_persist_payload` still computes checkpoint/status from coverage. | Repeat old full-first-page budget=1 backfill twice; inspect stored checkpoint, skipped requests, missing second-page record; retry also with larger budget. |
| F2 reorder identity | `_reconcile_record` retains sample_token and omits index when token exists; collection persistence maintains current/retired members. | Reorder/insert synthetic samples; compare keys and persisted current row IDs/counts; run exact existing regression. |
| F3 timezone | `_sample_temporal` still attaches UTC to naive stamps in static inspection. | Probe shared five surface adapters; inspect preserved date/offset and contract, no fix. |
| F4 completeness | collection completeness controls retirement; roadmap explicitly requires #55 metric analytic availability/manifest after #56. | Probe mixed invalid series and aggregate-only payload; distinguish collection scope from analytic sufficiency. |

Only this document will be committed. No provider calls or private runtime; synthetic temp runtime outside checkout. Tests/probe results remain NOT CHECKED at checkpoint A.
