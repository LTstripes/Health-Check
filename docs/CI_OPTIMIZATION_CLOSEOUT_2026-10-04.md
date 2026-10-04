# CI Optimization Closeout — 2026-10-04

This document closes the 2026-10-03/04 Health-Check test/CI optimization and dependency-security wave. It is a dated engineering record, not an instruction to keep optimizing tests without a new measured need.

## Canonical closeout

Final canonical checkpoint: `main @ 9f41985c47f758f38186efade974bb7ba1d9bf4d`.

Required exact-main gates:
- ordinary CI `37184776672`, attempt 1 — SUCCESS;
- Dependency audit `37184776636`, attempt 1 — SUCCESS.

The complete test/provenance contract remains fail-closed. No test file was deleted to achieve this closeout.

## #251 — balance the three Linux lanes

Goal: reduce the slowest-lane critical path without changing the complete Linux pytest union.

Accepted change:
- `tests/test_google_sync_backfill.py`: app-ingest -> garmin;
- `tests/test_owner_weight_screenshot_import.py`: app-ingest -> core-sleep;
- `tests/test_read_snapshot.py`: app-ingest -> core-sleep.

Evidence:
- exact candidate run `37128803050`;
- complete collection preserved;
- controlled wall-time comparison: 5:13 -> 4:21, an observed reduction of 52 seconds / 16.6%.

This is a wall-clock critical-path result. The sum of individual runner/job time did not establish runner-minute or billing savings, so none is claimed.

## #246 Stage A — safe docs-only PR path

Goal: avoid full pytest + Windows work for an explicitly bounded class of prose-only pull requests.

Accepted behavior:
- only modifications of five existing allowlisted prose files may qualify;
- new/unlisted Markdown, README/build metadata, config, fixtures, mixed changes, renames/deletes/mode changes and classifier/workflow changes fail closed to full CI;
- base/head/merge identities and trees are proven before skipping;
- the terminal result explicitly states when pytest and Windows were not run.

Live proof:
- implementation PR #262;
- canonical merge `d4529df9b5c0f3df28d637a259fbe82d0b4fde43`;
- validation PR #263, run `37141354429`;
- classify/docs/checks succeeded; quality/Linux/Windows were skipped.

Effect: qualifying routine documentation changes no longer pay the ~full-suite cost.

## #246 Stage B — exact-tree task-push / PR dedup

Goal: avoid repeating the same heavy suite on a task push when an already-complete PR run proves the exact same candidate tree.

Accepted behavior:
- delegation is limited to the same repository, one open PR targeting main and the exact task head;
- PR base/head/merge identities remain distinct;
- merge tree must equal task-head tree;
- only the newest complete successful PR run/attempt may authorize delegation;
- any stale, missing, failed, cancelled, superseded, foreign, ambiguous or lookup-error state falls back to full CI;
- a delegated push is explicitly not a candidate gate and skips its own quality/Linux/Windows/checks.

Live proof:
- implementation PR #265;
- canonical merge `37f73c29c33e2b40cf68e27a48b3e73a8822fdb0`;
- validation PR #266;
- authoritative full PR run `37149653148`;
- delegated task push `37149649729` completed after classifier work with quality/Linux/Windows/checks skipped.

Accepted limitation: the first task push before a matching PR exists still runs full CI. Stage B primarily saves subsequent pushes/remediations while that PR is open.

## #243 — Windows exit-255 transcript reliability

The optimization work repeatedly exposed a real Windows CI recurrence: taskkill exit 255 with the captured process tree already absent, closed ports/runtime, and one exact empty transcript item in a narrowly observed position.

The final #243 fix:
- accepts only the exact evidence-justified separator grammar;
- rejects whitespace and Unicode lookalikes;
- keeps raw transcript evidence;
- preserves exact PID-set, ownership/identity/CreationTime, independent child checks, port/runtime cleanup and same-attempt semantics;
- does not convert arbitrary exit 255 into success.

#243 closed through PR #267; accepted main checkpoint `754f19068cede943ddfb5c5f4ce0cfe72fa9689e`.

Effect: a known false-negative CI path was removed without weakening the security/cleanup contract.

## #242 — dependency security and bounded audit

Dependency delta:
- urllib3 `2.7.0 -> 2.8.0`;
- pytest `8.4.2 -> 9.0.3`;
- pytest constraint `>=9.0.3,<10`;
- uv transitive constraint `urllib3>=2.8.0,<3`;
- Garmin VCS pin unchanged;
- no unrelated resolved-version changes.

Audit/maintenance:
- reproducible `pip-audit==2.10.1` entrypoint using OSV;
- findings and scanner/network/tool/inventory failures are distinct nonzero outcomes;
- 45 registry packages are in coverage; Garmin VCS and first-party editable source are explicit unaudited limits;
- separate path-scoped Dependency audit workflow keeps OSV/network availability out of unrelated ordinary CI;
- audit evidence uploads even on failure;
- bounded weekly Dependabot groups for uv and GitHub Actions;
- Garmin excluded from automated dependency movement;
- touched actions pinned to immutable commit SHAs;
- least-privilege workflow permissions.

Final integration:
- PR #269;
- merge `9f41985c47f758f38186efade974bb7ba1d9bf4d`;
- refreshed current-main PR ordinary CI `37184547670` SUCCESS;
- refreshed PR Dependency audit `37184547667` SUCCESS;
- exact-main ordinary CI `37184776672` SUCCESS;
- exact-main Dependency audit `37184776636` SUCCESS.

## What this wave changed

The project now has:
1. a shorter observed Linux critical path without reducing coverage;
2. a live-proven fast path for narrowly safe documentation PRs;
3. live-proven avoidance of duplicate heavy execution on exact-tree subsequent task pushes;
4. a repaired Windows recurrence that no longer needs retry-until-green behavior;
5. patched known urllib3/pytest advisories and a bounded dependency-security gate;
6. explicit least-privilege/pinned-action CI hygiene.

## What it did not change

- The complete pytest union remains authoritative for full gates.
- Windows evidence remains mandatory for full gates.
- Main/integration/non-qualifying events remain full.
- A delegated task push never becomes an authoritative candidate gate.
- The first task push before an open matching PR remains full.
- Only the explicit Stage A prose allowlist may use docs-only routing.
- Dependency audit coverage does not include the Garmin VCS source or first-party editable source.
- No runner-minute, billing or monthly quota reduction is claimed without measured evidence.
- #126 required-check enforcement remains an Owner/admin repository-settings decision.

## Future disposition

There is no remaining planned test-suite/pytest/lane/workflow optimization task. Do not create another optimization issue merely because tests exist or CI takes several minutes. Reopen CI performance work only when a new measured bottleneck, reproducible regression, reliability defect or security requirement justifies it.
