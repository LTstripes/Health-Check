# Garmin activity pagination resume fix

## Checkpoint 1 — red regression

Remote main verified: c6f48d26a9eefee73b52f68835d931cce7b18388.
Branch: fix/garmin-activity-pagination-resume. Scope: F1 only.
Read current AGENTS, collection/persistence contracts, #56 and remote post56 audit c97c86f.
Root cause: fetch_complete governs retirement, but successful coverage/checkpoint/attempt ignore it.
New parameterized end-to-end regression covers budget and page-cap stops in historical and incremental paths, saved first-page observation, no false success/checkpoint, actual second-page fetch, stable current IDs and replay.
Before fix: 4 FAILED (11.79s), all on expected PARTIAL vs actual SUCCEEDED after first full page. Command: python -m pytest tests/test_garmin_activity_pagination_resume.py -q --basetemp=D:\Codex\Garmin\pagination-red-20260907.
No production edits at this checkpoint.
