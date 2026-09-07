# R02 Garmin post-48 targeted architecture audit

## Checkpoint 1 — remote baseline and scope (2026-09-07)

Status: IN PROGRESS — NOT SAFE TO CLAIM READY.

- CONFIRMED: GitHub `integration/r02-garmin` = `aea777e418d8d16c275a860c31b11c72641a73e6`; isolated clone pinned to this SHA. Audit branch: `audit/r02-garmin-post48-astra`.
- CONFIRMED: remote `main` = `c6f48d26a9eefee73b52f68835d931cce7b18388` (read only; not audit baseline).
- CONFIRMED: #48 is closed; PR #50 merged candidate `7fc10358a1d1713a562a4c9d3096b4398ba2c313` as `a820f8c1335a3178a4d61a6750f0752b1d7a5446`.
- CONFIRMED: #49 is already closed/integrated via PR #51 (`c223d683ec65188a0b9c68866d2ad103a7435dd3`, accepted candidate `0a9c453f87efb10dde977c70c735347bff100ed4`). Current integration is nine commits ahead of post-48 and includes #53/#57/#59. Readiness here means preserving/evaluating the #49 contract on the requested current integration, not authorizing duplicate implementation.
- CONFIRMED: #52 release tracker is closed. #55 is open, #56 closed; their issue bodies explicitly identify analytic identity/time and collection/reprocessing follow-ups. Closure/report text is context, not proof of baseline implementation.

Read: AGENTS.md; docs/agents/codex.md; PRODUCT_VISION; relevant ARCHITECTURE sections 4-7; ROADMAP R02; DECISIONS_AND_OPEN_QUESTIONS Garmin; EXECUTION_HISTORY R02; R02 normalization/persistence contracts; GitHub #48/#49 bodies, #49 integrator comments, PR #50 and compare API; tracker #52 and scoped #55/#56 context. No standalone ADR files or R02_IMPLEMENTATION_SPEC exist in the pinned tree: architecture/decisions + roadmap + issues govern. R01 spec is historical, not silently reused.

Scope: incremental/trailing, bounded backfill/replay, partial/error coverage, id-less corrections, provenance/time/series and CLI/API/storage agreement; at most eight adversarial scenarios. Only this report is a deliverable change. No production changes, provider calls, private runtime access, PR or merge.

Understood invariants: missing/null/zero differ; unknown/empty/unavailable differ; incomplete fetch must not advance successful checkpoint; history retained; stable current projection on replay/correction; explicit device evidence only; production provider identity separate from synthetic; historical state isolated from incremental; explicit bounded range/budget and coverage-driven resume.

Initial inspection targets (not findings yet): sample identity and timestamp fallback; aggregate aliases vs field provenance; source identity change when device evidence appears; authoritative empty/removal vs existing current rows; coverage-skip versioning; watermark vs unresolved earlier dates. Historical contract markdown still describes synthetic-only/semantic-value identity and must not be mistaken for the full production orchestration contract.

NOT CHECKED yet: implementation invariants, tests, eight scenarios, final #49 minimum contract. Owner-live behavior remains UNVERIFIED in this session.
