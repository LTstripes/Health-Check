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

## Checkpoint 2 — static sync/normalization audit

### C1 — CONFIRMED / PASS: bounded shared orchestration and state isolation
`garmin/backfill.py:292 GarminHistoricalBackfill.__init__` uses GarminIncrementalSync with `garmin_historical` namespace and coverage skip. `sync.py:1253 _ingest_window`, `1480 _fetch`, `369 _disable_provider_retries` bound application requests/retries; auth abort is explicit. `sync.py:1737 _write_checkpoint` changes success cursor/watermark only for present/confirmed_empty; failures preserve prior success state. Per-day surfaces are actually requested per day, not inferred from a sparse multi-day list. Watermark is latest successful date, not a contiguous-history proof; normal sync computes a fixed trailing interval and does not backfill gaps outside it.

### C2 — BLOCKER candidate pending reproduction: truncated activities can become complete
`sync.py:1506 _fetch_activities` breaks at exhausted budget after a nonempty full page, or exits MAX_ACTIVITY_PAGES, then returns `collected, None, used` without incomplete marker. `881 _coverage_status_for` accepts any expected duration metric; `1550 _persist_payload` writes successful coverage. `1317 _completed_coverage_status` then lets historical resume skip that exact interval. Static path is unambiguous; synthetic end-to-end probe will establish classification. This is directly within #49 bounded/resumable correctness, unlike analytic follow-ups.

### C3 — CONFIRMED semantic gaps; RISK for future consumers
- `sync.py:729 _reconcile_record` rekeys every sample with mutable `record_index`, discarding the sample_token supplied by `743 _series_records`; normalization.py:920 key also includes sample_index. Reorder/insertion can fork unchanged timestamp records. Persistence upserts received members only (`persistence.py:484`, `persist_result`) and does not retire absent collection members. Empty/removal/timestamp correction therefore is not a complete current-collection reconciliation policy. #56 explicitly tracks this scope, but its CLOSED state does not establish its presence in this pinned integration.
- `sync.py:809 _sample_temporal` attaches UTC to naive strings/datetimes, loses aware source-offset/local evidence, and assigns date-only request-day fallback to unstamped samples. This violates local-only no-invented-UTC intent; exact real provider exposure is UNKNOWN without live input (not needed/authorized here).
- `sync.py:488 _adapt_known_provider_shape` maps avg/max stress and daily/seven-day SpO2 into the same alias; `528 _summary_scalar` takes the last array element rather than a defined statistic/time ordering. Typed scalar field provenance reports the alias, while original field survives in raw evidence. Do not consume this as an analytic daily average. #55 is the existing bounded follow-up.
- `_source_identity_for` changes source identity on later target-device evidence. Identity partitions are honest, but same event can have both unattributed and attributed current rows without a supersession relation. No automatic cross-source dedup is justified without an explicit contract.

### C4 — CONFIRMED / PASS with limits: immutable evidence and replay
`persistence.py:805 persist_result`, `301 GarminPayloadObservationRepository`, `1068 _replay_current_records`: raw content and logical observations retained; exact existing observation replay returns current projection without replacing it. New observations can update existing stable keys. This does not prove receive-order independence for old payload reacquired under a new sync-run observation; retain that distinction in tests/report. Production `source_kind=provider` is explicitly passed by sync; raw fixture defaults remain synthetic.

### C5 — CONFIRMED operational/analytic distinction
`sync.py:857 _has_expected_metric` is existential (sleep duration or any expected value); `585 _parse_series` filters non-numeric samples. Thus present is acquisition-level, not complete series/score/stage/metric coverage. Unknown drift with no expected value remains refetchable, but mixed valid/invalid members can still be present. This needs explicit worker/consumer limits; no invented zero occurs in the inspected scalar-state path.

Checkpoint 2 is static evidence, not a claim that tests passed. Next: eight bounded scenarios, focused existing tests and a compact reproduction script. No production edits.
