# Garmin activity pagination resume fix

## Checkpoint 1 — red regression

Remote main verified: c6f48d26a9eefee73b52f68835d931cce7b18388.
Branch: fix/garmin-activity-pagination-resume. Scope: F1 only.
Read current AGENTS, collection/persistence contracts, #56 and remote post56 audit c97c86f.
Root cause: fetch_complete governs retirement, but successful coverage/checkpoint/attempt ignore it.
New parameterized end-to-end regression covers budget and page-cap stops in historical and incremental paths, saved first-page observation, no false success/checkpoint, actual second-page fetch, stable current IDs and replay.
Before fix: 4 FAILED (11.79s), all on expected PARTIAL vs actual SUCCEEDED after first full page. Command: python -m pytest tests/test_garmin_activity_pagination_resume.py -q --basetemp=D:\Codex\Garmin\pagination-red-20260907.
No production edits at this checkpoint.

## Checkpoint 2 — minimal fix

Shared `_persist_payload` demotes otherwise successful activity coverage to unknown when fetch_complete=False. Existing status mapping gives PARTIAL, successful checkpoint stays unchanged, and normal historical skip cannot hide the incomplete range. Immutable partial observations and #56 absence-retirement guard stay intact. No new enum/cursor/schema.
Exact new regression: 4 PASSED in 7.97s (budget/page-cap x historical/incremental). First 20 rows retained without successful checkpoint; second invocation refetches page 1 and retrieves page 2; 21 stable current rows; completed historical replay uses zero requests. Incremental replay refetches bounded trailing window without duplicate rows.

## Checkpoint 3 — final local validation

82 PASSED in 100.34s: new pagination regression + existing incremental, historical, collection reconciliation tests. Command: `.venv\Scripts\python.exe -m pytest tests/test_garmin_activity_pagination_resume.py tests/test_garmin_incremental_sync.py tests/test_garmin_historical_backfill.py tests/test_garmin_collection_reconciliation.py -q --basetemp=D:\Codex\Garmin\pagination-targeted-final-20260907`.
Repository-wide Ruff and git diff --check passed. Locked dependencies unchanged. Full pytest runs in push CI; final exact-SHA CI outcome is reported at handoff, not assumed here. No schema changes, no additional local full suite.
Proof (historical activity requests): run1=1/PARTIAL/unknown/no success checkpoint/20 rows; run2=2/SUCCEEDED/present/success checkpoint/21 rows; run3=0/SUCCEEDED/unchanged 21 row IDs and observations. Incremental total requests=10,11,11 (nine daily calls + bounded activities); same PARTIAL->SUCCEEDED->SUCCEEDED and stable 21 activity rows. Page-cap variant also verified; tests raise synthetic cap from 1 to 2 for completion.
Existing #56 retirement/stable-identity and historical/incremental isolation regressions pass. Only five production lines changed, plus regression and contract/delivery documentation. #55/timezone/aggregates/R03/dependencies untouched. No PR/merge/private provider access.
Limit: hard page cap remains; split oversized historical windows. Remaining counts retain existing attempted-work meaning and must be read with PARTIAL status.
Follow-up: previously persisted false-present coverage from an old build is not automatically repaired; any affected historical windows need separately scoped reacquisition. No migration or private-data repair is performed here.
