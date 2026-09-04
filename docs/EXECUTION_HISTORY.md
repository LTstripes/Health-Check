# Execution History

Durable engineering history for Health-Check. Maintained by the Integrator after review/integration, including useful failed/rejected attempts. This is intended for retrospectives, model benchmarking and a future article/story of how the project was built.

Do not put real health values, screenshots, credentials, private payloads or medical documents here.

## Entry template

### YYYY-MM-DD — <release/task> — <short title>

- **Issue / PR:**
- **Complexity / routing:**
- **Executor:** client + runtime-reported model; delegate/fallback chain if any
- **Role:** worker / reviewer / architecture audit / integrator
- **Baseline:** exact SHA
- **Target integration:** branch + SHA
- **Task branch / workspace:**
- **Candidate:** exact SHA
- **Objective:**
- **Result:** what was actually done
- **Checks:** exact commands/results or repository-side evidence
- **Problems / surprises:**
- **Plan changes / decisions:** what changed and why
- **Integrator review:** ACCEPT / FIXES REQUIRED / REJECT + key findings
- **Integration result:** merge SHA/branch or reason not integrated
- **Retrospective note:** process/model/product lesson worth preserving

---

## 2026-08-31 to 2026-09-02 — R00 — Product discovery and multi-model architecture consolidation

- **Issue / PR:** PR #1 bootstrap docs; PR #2 owner decisions; PR #3 final R00 architecture/R01 specification.
- **Complexity / routing:** C4 / architecture and source-level forensic review.
- **Executors / reviewers used:** ChatGPT/Lera as integrator; independent/research passes included Gemini Flash, Grok 4.7 High, Step 3.7 Flash with DeepSeek V4 Flash fallback, GLM 5.3 with DeepSeek V4 Flash fallback, a large Nemotron model, and final Sol Ultra consolidation. Exact model availability/labels were owner runtime choices; model prose was never treated as proof.
- **Objective:** define what Health-Check should be, choose build-vs-fork strategy, audit donor projects, establish data/provenance/analytics architecture and produce an implementation-ready first release.
- **Research process:** several models received intentionally similar independent audit prompts. Their findings were compared rather than merged blindly. Contradictory SHA/license/API/device claims triggered direct source/official-document checks. Useful unique ideas were retained even when a model was unreliable on factual archaeology.
- **Notable failures / corrections:** Gemini produced a strong architectural direction but inconsistent repository SHA/license/stack claims in parts of its audit; Nemotron produced useful product ideas but several overconfident factual errors; Step/GLM runs were interrupted/fell back and were completed through DeepSeek V4 Flash, so those results are attributed as pipelines rather than pure single-model benchmarks.
- **Key decisions that survived consolidation:** clean Health-Check core rather than donor fork; Python/FastAPI/SQLite WAL; source/raw evidence retained; typed health entities rather than one generic EAV; deterministic analytics separated from LLM interpretation; coverage first-class; physical device/provider/acquisition/measurement algorithm separated; Xiaomi-app and openScale BIA series not silently merged; R01 Weight & Body Composition before Garmin; Recovery Score deferred; bounded typed AI tools later; openScale/openScale-sync external GPL components.
- **Donor strategy:** `python-garminconnect` pinned future Garmin dependency; selective reuse/patterns from `garmin-stats-ai`, `fettle`, `healthquery`, `open-wearables`; `garmin_ai` reference-only while unlicensed; VitaSync reference-only; exact pins recorded in R00 docs.
- **R01 outcome:** first working vertical slice will import/confirm historical Xiaomi screenshots, accept openScale-sync webhook, preserve provenance/algorithm boundaries, compute conservative weight/body-composition analytics and show a minimal local dashboard.
- **Integrator review:** PR #3 received semantic review with no merge blockers before subsequent owner-approved MIT/backlog/process additions. Live device/account details remain explicitly `UNVERIFIED` until their release acceptance probes.
- **Cost/process note:** final Sol consolidation consumed two full five-hour owner limit windows plus a short continuation. This reinforced the value of doing broad reconnaissance with cheaper/diverse models first and reserving strongest-model context for arbitration/consolidation.
- **Retrospective lesson:** model consensus is useful for discovering candidate architecture, not for proving facts. Exact source evidence, pinned commits and independent Integrator review prevented several plausible-but-wrong claims from becoming architecture contracts.

## 2026-09-02 — R00 process follow-up — Engineering workflow formalization

- **Objective:** port the mature parts of the `hermes-finance` engineering process into Health-Check before coding starts, while fixing known friction around moving `main`, shared workspaces and central history conflicts.
- **Owner workflow:** Integrator defines GitHub issues/tasks and model routing; owner launches assigned workers in Codex/Grok/Hermes; workers return candidate SHA/completion report; Integrator reviews actual GitHub state and controls acceptance/merge.
- **Workspace decision:** owner root is `D:\Garmin`, with stable checkout `D:\Garmin\Garmin-Main` and preview/UAT checkout `D:\Garmin\Garmin-UAT`. The first draft used flat `D:\Garmin` / `D:\Garmin-UAT` paths; this was corrected before R01 implementation started. Codex/Grok/Hermes receive separate task-workspace roots documented in `docs/DEVELOPMENT_PROCESS.md`.
- **Parallelism decision:** use a release integration branch (for example `integration/r01-weight-core`) so active tasks do not continuously chase moving `main`. Each task remains pinned to one integration SHA until review; refresh/retest is risk-based at integration time.
- **Logging decision:** normal workers do not edit this shared history file. They return structured completion reports; Integrator appends accepted/rejected/failed attempt history centrally, preventing parallel log merge conflicts and preserving neutral attribution.
- **Model routing:** every task presented to the owner starts with complexity, recommended executor, alternative and reviewer requirement; concrete model names are per-task guidance rather than permanent repository truth.

## 2026-09-02 — R01-01 — Bootstrap local runtime, project skeleton and offline checks

- **Issue / PR:** #4 / PR #14.
- **Complexity / routing:** C2 / Normal; launch recommendation was Luna High / strong Codex coding model; independent reviewer not required.
- **Executor:** Codex, runtime-reported model `GPT-5`; no delegates/fallbacks. Owner launched this as the Luna High task, but repository attribution follows the runtime-reported model per `AGENTS.md`.
- **Role:** worker; ChatGPT/Lera Integrator review and merge.
- **Baseline:** `cca6efb43d2cb56de7448f006b3f496b1ef6d770`.
- **Target integration:** `integration/r01-weight-core` at the same baseline SHA.
- **Task branch / workspace:** `task/4-bootstrap-runtime`; `D:\Codex\Garmin\workspaces\4-bootstrap-runtime`.
- **Candidate:** `54ecf2391037bca616e006e2c8b45a9a5e8f06c5` (`feat: bootstrap local runtime`).
- **Objective:** create the smallest production-shaped Python/Windows runtime foundation for later R01 tasks without implementing Xiaomi/domain behavior prematurely.
- **Result:** added Python 3.12+/uv project skeleton, typed Pydantic settings, external runtime directory guard/layout, SQLite bootstrap with WAL/foreign keys, narrow structured logging, separate loopback UI and ingest-only FastAPI apps, CLI, canonical `scripts/start.ps1`, GitHub Actions CI, repository hygiene rules, README bootstrap instructions and six offline bootstrap tests.
- **Checks:** worker reported `uv sync --locked` PASS; `uv run ruff check .` PASS; `uv run pytest` = 6 passed with one upstream Starlette/httpx warning; PowerShell fresh-start returned HTTP 200 from both `/healthz` endpoints and 404 for `/api/imports` on ingest listener; `git diff --check` PASS. Repository-side verification confirmed GitHub Actions run `33664348091` completed `success` on exact candidate SHA `54ecf239...`.
- **Problems / surprises:** issue body still contained the superseded pre-workspace-correction baseline `10e0e5e...`; the explicit Integrator launch prompt correctly pinned `cca6efb...`, which the worker used. No owner workspaces were inspected. No domain/Xiaomi/provider features were added.
- **Plan changes / decisions:** none to product architecture. Bootstrap intentionally includes only placeholder DB opening rather than R01 schema/migrations; those remain #5. UI and ingest are separate ASGI apps from day one, with ingest exposing only non-sensitive liveness in this task.
- **Integrator review:** **ACCEPT**. Actual branch/commit/diff and key files were inspected rather than trusting the completion report. Candidate is exactly one commit ahead of its assigned baseline; scope is disciplined; runtime isolation, route isolation, safe logging, SQLite pragmas, tests and CI match issue #4. No blocking findings.
- **Integration result:** PR #14 merged into `integration/r01-weight-core`; merge SHA `f5a71687cbf7f99f97ae3ee6a94e216183d7c3ae`.
- **Retrospective note:** the first end-to-end worker → report → Integrator evidence review → task PR → integration flow worked as intended. The stale issue baseline showed why the launch prompt must carry an exact pinned SHA and why the Integrator should synchronize issue metadata immediately when a baseline changes.

## 2026-09-02 — R01-02 — Core SQLite schema, migrations and provenance repositories

- **Issue / PR:** #5 / PR #15.
- **Complexity / routing:** C3 / Hard data semantics; executor Luna Max; independent reviewer required and assigned to Grok xHigh.
- **Executor:** Codex, runtime-reported model Luna Max; no delegates/fallbacks reported.
- **Reviewer:** Grok xHigh, reviewer-only; no repository writes.
- **Role:** Luna Max worker; Grok xHigh independent reviewer/re-reviewer; ChatGPT/Lera Integrator.
- **Baseline:** `7e84fc14a9909640f76263dd59b1c68a0c3b9a62`.
- **Target integration:** `integration/r01-weight-core` at the same baseline SHA.
- **Task branch / workspace:** `task/5-core-schema`; `D:\Codex\Garmin\workspaces\5-core-schema`.
- **Initial candidate:** `0e18b3e35811759f3eb2a39cc27eae2011025808`.
- **Final candidate:** `1376756559a31d400245062c7e1e24f9989963fe`.
- **Objective:** establish the durable R01 SQLite/Alembic provenance, revision, canonical, sync and coverage persistence contracts before photo/webhook services depend on them.
- **Initial result:** added the R01 migration/schema, 18 domain tables plus Alembic state, repository layer, WAL/FK readiness, provenance/dedup/revision/canonical/sync/coverage primitives and synthetic tests.
- **Initial checks:** worker reported Ruff PASS, pytest 10 passed with one upstream warning, fresh/repeat migration PASS, WAL/FK/readiness PASS, `alembic check` clean, downgrade/re-upgrade PASS and `git diff --check` PASS. GitHub Actions push and PR runs were green on the reviewed SHA.
- **Independent review round 1:** **BLOCKERS**. Grok xHigh found five durable-semantics defects invisible to the green tests: terminal candidate decisions could drift after measurement creation; exact replay vs reprocessing/source updates were conflated; ingest external-ID identity was nullable/stream-sensitive and could swallow real updates; supersession allowed multiple active heads; measurement-algorithm `(code, version)` reuse silently accepted contradictory immutable metadata.
- **Integrator additions:** two further hardening requirements were added: terminal canonical runs must be immutable/idempotent after completion, and `import_candidate_edits` must be protected from both UPDATE and DELETE.
- **Fix round:** Luna Max updated the same task branch rather than starting a new issue. The fix introduced terminal-decision guards/no-op replay, explicit revision requirements for new evidence, stream-independent ingest dedup keys while keeping genuine update evidence representable, single-successor indexes/checks, immutable algorithm metadata comparison, immutable terminal canonical completion, and full candidate-edit audit protection. Regression tests were added for all seven findings.
- **Final checks:** worker reported Ruff PASS, pytest 12 passed with one upstream Starlette/httpx warning, fresh/repeat migration PASS, WAL/FK/readiness PASS, `alembic check` clean, downgrade/re-upgrade PASS and diff check PASS. Repository-side verification confirmed final PR CI `33677353644` succeeded on `1376756559a31d400245062c7e1e24f9989963fe`.
- **Independent re-review:** **ACCEPT**. Grok xHigh re-reviewed only `0e18b3e...1376756`, reproduced the previous failure classes against throwaway SQLite databases, confirmed all seven invariants closed, and judged the resulting persistence contract suitable for later openScale ingestion when #10 always supplies `event_type` plus evidence identity/fingerprint for genuine successive updates.
- **Non-blocking follow-up:** #10 must pass `event_type` and evidence fingerprint/artifact identity; successive updates without new evidence intentionally collapse as exact retries. Additional SQLite timezone/candidate-level SQL precision/natural-identity hardening remains future work unless a concrete R01 path needs it.
- **Integrator review:** **FIXES REQUIRED → ACCEPT**. The initial implementation was structurally strong but not durable enough for downstream ingestion. The independent reviewer materially improved the design; the fixed candidate was inspected against the actual diff/CI before final acceptance.
- **Integration result:** PR #15 merged into `integration/r01-weight-core`; merge SHA `3f86d13aeec4823b8ea74c859dcb8f4df5aba5f0`. Issue #5 closed completed.
- **Retrospective note:** green tests plus a plausible schema are not sufficient for append-only health history. The highest-value review was adversarial scenario testing at repository/SQLite semantics: exact retry, real update, post-confirm edit, forked revision and algorithm identity. This validates the C3 rule that persistence/canonical semantics require an independent model reviewer before integration.

## 2026-09-03 — R01-04 — Canonical selection, revisions and coverage v1

- **Issue / PR:** #7 / PR #17.
- **Complexity / routing:** C3 / Hard canonical-data semantics; executor Luna Max; independent reviewer Grok xHigh.
- **Executor:** Codex worker assigned Luna Max; runtime identity was reported inconsistently across worker summaries (`not exposed` initially, later Codex / GPT-5). No delegates/fallbacks were reported, so attribution preserves both the assigned routing and runtime-report limitation rather than inventing a stronger identity.
- **Reviewer:** Grok xHigh, reviewer-only, with adversarial throwaway SQLite probes; no repository writes.
- **Role:** Luna worker/fix rounds; Grok independent reviewer/re-reviewer; ChatGPT/Lera Integrator.
- **Baseline:** `05fe900161b8aa2c806de8f4fdd847456f047967`, shared with parallel task #6.
- **Task branch / workspace:** `task/7-canonical-coverage`; `D:\Codex\Garmin\workspaces\7-canonical-coverage`.
- **Initial candidate:** `0f25f134c67a2bf90acc35775bd13858e5b219ff`.
- **Intermediate fix:** `7a058b8ca7e96e1c61710d2351472c8f3791881d`.
- **Final candidate:** `ef8f82473aa1fc19d0da573d336514765769f292`.
- **Objective:** implement deterministic canonical selection/revisions and first-class sparse weight coverage without losing competing evidence or crossing composition algorithm groups.
- **Initial result:** added pure deterministic canonical rules, canonical service/DTOs, current-head repository helpers, coverage-v1 precedence/cadence logic and synthetic tests. Initial CI was green, but the first Integrator pass identified three high-risk semantic areas for independent attack.
- **Independent review round 1:** **BLOCKERS**. Grok reproduced all three: (1) pure rules keyed `(metric_code, semantic_key)` but persisted selections keyed only `(run, semantic_key)`, so one weigh-in with weight + body-fat could not persist in one run; (2) source/provider-scoped coverage intervals were filtered but current observations leaked across sources/providers; (3) a failed canonical run marked `failed` then re-raised, causing the normal `session_scope()` rollback to erase the failed run/diagnostic.
- **Fix round 1:** Luna fixed source/provider observation isolation and related current-head filtering, plus additional determinism/current-head hardening. Integrator inspected the actual delta and rejected the worker's optimistic completion as incomplete because the multi-metric identity and durable failed-run problems were still present.
- **Fix round 2:** Luna added forward migration `0002_canonical_selection_metric_identity` without rewriting `0001`, changed selection identity to `(selection_run_id, metric_code, semantic_key)`, updated repository lookup/add semantics, and added a mixed-metric persisted regression. Canonical selection writes now occur inside a savepoint; a selection-write exception rolls back partial selections and returns a typed failed result so the outer `session_scope()` can durably commit the sanitized failed-run audit row.
- **Migration behavior:** upgrading an existing `0001` database to `0002` preserves prior selection rows and restores append-only triggers after SQLite table recreation. Lossless downgrade works when old identity can represent the data; downgrade fails explicitly if a run already contains multiple metrics for one semantic key, preventing destructive collapse.
- **Checks:** final worker reported Ruff PASS, full pytest `22 passed` with two known warnings, empty/repeat upgrade PASS, downgrade/re-upgrade PASS, `alembic check` clean and diff check clean. Repository-side CI run `33780197156` completed `success` on exact final SHA `ef8f824...`.
- **Independent final re-review:** **ACCEPT**. Grok verified the real `0001→0002` upgrade, append-only triggers after recreate, lossless and fail-closed downgrade paths, persisted mixed-metric run through fresh-session readback, and the `session_scope() → failed result → fresh session` durability path. Source/provider coverage isolation remained closed.
- **Non-blocking follow-up:** migration upgrade/downgrade adversarial probes are stronger than the current pytest suite and may be worth codifying later; repeated identical failures intentionally create multiple failed audit runs; repository-loaded period fields remain nullable and #8 should use source-session dates where needed.
- **Integrator review:** **FIXES REQUIRED → PROVISIONAL ACCEPT → ACCEPT**. The actual deltas were reviewed after each worker report. Crucially, an intermediate completion report was not accepted because two confirmed blockers were still visible in code despite green tests.
- **Integration result:** PR #17 merged into `integration/r01-weight-core`; merge SHA `d19ecb693c84715d25739502c8f74fd719a3d058`. Issue #7 closed completed.
- **Parallel-integration note:** sibling task #6 was developed from the same pre-#7 baseline and independently introduced a migration named `0002_photo_candidate_provenance` from `0001`. After #7 integration, #6 must not be merged unchanged: its migration chain must be refreshed/renumbered after canonical `0002` and reverified before integration, avoiding multiple Alembic heads.
- **Retrospective note:** this was the clearest proof yet that the workflow should distrust both green CI and worker completion claims. Integrator suspicion generated concrete attack cases; the independent reviewer reproduced them; and the second Integrator delta check caught an incomplete first fix round before merge. Parallel task branches worked as intended, but parallel schema changes require an explicit Integrator migration-order gate at convergence.

## 2026-09-03 — R01-05 — Deterministic weight and body-composition analytics v1

- **Issue / PR:** #8 / PR #18.
- **Complexity / routing:** C2 / Normal deterministic analytics; deliberate benchmark route to Hermes + Meta Muse Spark 1.3 Contributor; targeted independent review required from a different model family.
- **Executor:** Hermes Agent desktop on Windows 11, runtime-reported model `muse-spark-1.3-contributor-free` via `opencode-free`; no delegates/fallbacks reported.
- **Reviewer / Integrator:** ChatGPT/Lera independently inspected the actual branch/deltas, R01 spec and exact-head CI; implementation model was not used for review.
- **Baseline:** `19c04b0f4db69868f4a1c9a10c3320cc61fcba3d`.
- **Task branch / workspace:** `task/8-weight-analytics`; `D:\Hermes Project\hermes-garmin\workspaces\8-weight-analytics`.
- **Initial candidate:** `5304debbb4b5f2e09ce6d5c238585746f38e227a`.
- **Final candidate:** `011cfbbd810812a5c56aac9b29fdbb5fb684840f`.
- **Objective:** implement pure deterministic R01 weight/body-composition analytics with hand-checkable formulas, explicit evidence gates, provenance, coverage pass-through and unavailable-not-zero semantics.
- **Initial result:** Muse Spark implemented daily median reduction, 21-day time-aware EWMA, trailing 90-calendar-day Theil–Sen in kg/week with >=6 observation/>=42-day gates, same-session fat/lean derivation, composition/recomposition DTOs, coverage pass-through and 22 synthetic analytics tests. Worker reported Ruff PASS and full pytest `44 passed`; exact candidate CI run `33785840892` succeeded.
- **Integrator first review:** **FIXES REQUIRED** despite green tests. Three domain-contract errors were found: fat/lean derivation incorrectly required raw weight and body-fat to share one algorithm compatibility group; similar-weight recomposition could report available with only weight and no composition evidence and lacked exact source algorithm provenance; `WeightSeries` computed raw canonical observations but dropped them from its DTO even though R01 requires raw points to remain visible.
- **Fix round:** the same Muse Spark model, with no delegate/fallback, corrected all three on the same pinned branch: same-session derivation now allows separate per-metric algorithms and follows the BIA/body-fat compatibility lineage while checking dates/units; recomposition requires actual composition evidence and carries exact algorithm code/version; `WeightSeries.raw_points` preserves deterministic canonical observations with provenance. Six additional focused tests raised the analytics suite to 28 tests.
- **Final checks:** worker reported Ruff PASS, focused analytics `28 passed`, full pytest `50 passed`, diff/privacy/scope checks clean. Repository-side CI run `33786564522` completed `success` on exact final SHA `011cfbb...`.
- **Integrator final review:** **ACCEPT**. Actual `5304debb..011cfbb` delta and final implementation were inspected; no new blocker found. The accepted Theil–Sen window is `(latest-90d, latest]`, a consistent 90-calendar-date interpretation.
- **Integration result:** PR #18 merged into `integration/r01-weight-core`; merge SHA `297d5838c5c9f24a42b51bcf6feffa9af627c984`.
- **Benchmark retrospective:** **PARTIAL first shot → ACCEPT after one targeted fix round**. Muse Spark was strong on formula implementation, determinism, scope discipline, synthetic tests and responding precisely to review. Its main weakness was cross-layer domain semantics: locally plausible algorithm-boundary rules were applied at the wrong metric/session layer, and an API DTO omitted evidence the spec required to remain visible. For a free Contributor-tier coding model, this was a useful and credible result rather than a clean first-pass success.

## 2026-09-03 — R01-07a — openScale-sync contract fixture and pure normalization

- **Issue / PR:** #19 / PR #20.
- **Complexity / routing:** C2 / Normal bounded contract/normalization; deliberate second benchmark for Hermes + Meta Muse Spark 1.3 Contributor.
- **Executor:** Hermes Agent desktop on Windows 11, runtime-reported model `muse-spark-1.3-contributor-free` via `opencode-free`; no delegates/fallbacks reported.
- **Baseline:** `1b8afb5fc1be9594ba6b0d7b64d43619a85f93f0`.
- **Task branch / workspace:** `task/19-openscale-contract`; `D:\Hermes Project\hermes-garmin\workspaces\19-openscale-contract`.
- **Initial candidate:** `f76936076075808222eb37ba351aa905bff9ff06`.
- **Final candidate:** `609ee8cbc29f4772f6c1ff495392edd52baea11d`.
- **Objective:** implement a pure, framework-free openScale-sync generic-webhook contract and normalization layer for later #10, with deterministic identity/fingerprints, authoritative `values[]`, missing-not-zero semantics, source-time precision and typed sanitized failures, while excluding HTTP/auth/DB state machinery.
- **Initial result:** added typed contract DTOs, normalization, synthetic fixtures and 21 adversarial tests. The first pass was structurally strong and stayed inside scope.
- **Integrator first review:** **FIXES REQUIRED** on three edge contracts: id-less insert/update incorrectly used delete-style `(source,user,time)` identity instead of semantic fingerprint; present `values: null` incorrectly enabled convenience fallback; unknown numeric values retained metadata but lost the numeric evidence.
- **Fix round:** the same Muse Spark model corrected all three in one focused pass: event-specific identity now reserves time fallback for delete and uses semantic fingerprints for id-less insert/update; any present non-list `values` fails closed; unknown numeric evidence preserves numeric value and explicit-value state without becoming canonical or influencing the canonical semantic fingerprint.
- **Checks:** worker reported Ruff PASS, focused contract tests `24 passed`, full pytest `74 passed`, diff/privacy/scope audits clean. Repository-side CI run `33789789944` completed `success` on exact final SHA `609ee8c...`.
- **Integrator review:** **PARTIAL/FIXES REQUIRED → ACCEPT** after independent actual-delta inspection.
- **Integration result:** PR #20 merged into `integration/r01-weight-core`; merge SHA `102c6dfe75410eb12a7381661d57dc96ec0484c3`. Issue #19 closed completed.
- **Benchmark retrospective:** Muse Spark again showed a consistent profile: strong deterministic implementation, tests and scope discipline, but it benefits materially from Integrator review on edge-domain identity/evidence semantics. It closed all findings cleanly in one short fix round, supporting use as a cost-effective C2 worker with review rather than autonomous merge authority.

## 2026-09-03 — R01-03 — Historical Xiaomi photo import and confirmation workflow

- **Issue / PR:** #6 / PR #16.
- **Complexity / routing:** C3 / Hard ingestion, provenance, idempotency and migration convergence; implementation/fix rounds Grok xHigh, independent Sol-family adversarial review, final ChatGPT/Lera Integrator convergence review.
- **Executor:** Grok runtime reported Grok 4.6; assigned Grok xHigh; no delegates reported.
- **Original baseline:** `05fe900161b8aa2c806de8f4fdd847456f047967`.
- **Task branch / workspace:** `task/6-photo-import`; `D:\Grok\Garmin\workspaces\6-photo-import`.
- **Initial reviewed candidate:** `d343757096d9a70187c1983b44c8dfd2075e218c`.
- **Semantic-accepted candidate:** `64adf33a4a745b998c794d34d11b47dd308c0df7`.
- **Grok convergence candidate:** `4ca8c7a1e2e1d64df25f400c3a4ce6aeae797bb6` after merging accepted #7/#8 integration `1b8afb5fc1be9594ba6b0d7b64d43619a85f93f0`.
- **Final PR head:** `8a51c7b4dbe878033bc160abbc4666eabb18f5f8`, an Integrator-only mechanical merge of current integration `102c6dfe75410eb12a7381661d57dc96ec0484c3` after #19 landed in parallel.
- **Objective/result:** implemented immutable external photo artifacts, provider-neutral versioned extraction, pending candidates, explicit edit/reject/confirm, idempotent confirmation/reprocessing, complete temporal/provider/device/algorithm provenance, linked acquisition-source lineages, source-head supersession, sanitized failures/logging, durable duplicate and failed-attempt audit, and loopback photo import/review APIs using only synthetic test data.
- **Independent review:** the first Sol review reproduced 10 blockers spanning temporal consistency, SQLite timestamp reload, old replay/reprocess revision behavior, multiple metric heads, extraction identity, provider/algorithm provenance, atomic extraction, failed-reprocess durability, privacy logging and duplicate occurrence history. Grok fix round 1 closed most but left four; fix round 2 closed the remaining internal date/timestamp consistency, exact terminal replay, full extraction/acquisition fingerprint and reprocess acquisition-source lineage findings. Integrator independently inspected the fixed code and accepted `64adf33...` semantically when owner limits made another external Sol pass undesirable.
- **Migration convergence:** the parallel photo migration was linearized without rewriting accepted history: `0001_r01_core_schema -> 0002_canonical_selection_metric_identity -> 0003_photo_candidate_provenance`. Accepted canonical `0002` remained blob-identical to integration; obsolete parallel photo `0002` was removed. Grok reported fresh/repeat/existing-0002/downgrade-reupgrade probes PASS and exactly one Alembic head.
- **Cross-task convergence:** #19 merged after Grok's pinned convergence. Integrator resolved the remaining mechanical overlap by merging current integration as a second parent and overlaying accepted #19 files unchanged; compare against current integration then contained only #6 changes.
- **Checks:** Grok convergence reported Ruff PASS, full pytest `97 passed`, focused #6 `45 passed`, #7 `10 passed`, #8 `28 passed`, compile/diff/privacy/hygiene PASS and Alembic head/current/check PASS. Exact final PR head `8a51c7b...` received GitHub Actions run `33791846735` **SUCCESS**; `uv sync --locked`, Ruff and full pytest all succeeded on the real combined #6+#19 tree.
- **Integrator review:** **FIXES REQUIRED → semantic ACCEPT → convergence ACCEPT → FINAL ACCEPT**. Worker/reviewer prose was repeatedly cross-checked against actual remote code, migration graph and CI.
- **Integration result:** PR #16 merged into `integration/r01-weight-core`; merge SHA `ca28af2f71909ce24ac0660756d0c19387dc52c9`. Issue #6 closed completed.
- **Retrospective note:** #6 validated the full multi-agent workflow under real complexity: independent adversarial review found bugs green tests missed; repeated narrow fix rounds worked better than rewrites; preserving the semantic candidate in ancestry made later migration convergence auditable; and parallel accepted work can be reconciled mechanically by the Integrator when its surface is truly non-semantic. This is the strongest evidence so far for keeping C3/C4 workers separate from acceptance authority.

## 2026-09-03 — R01-06 — Local dashboard and photo-review UX

- **Issue / PR:** #9 / PR #21.
- **Complexity / routing:** C2 / Normal multi-layer UI; executor Grok High; targeted contract/UI review by ChatGPT/Lera Integrator.
- **Executor:** Grok runtime-reported Grok 4.6 / launch Grok High; no delegates/fallbacks.
- **Role:** Grok worker/fix rounds; ChatGPT/Lera Integrator reviewer and merge authority.
- **Baseline:** `afa4d84ef6bf5a7ca23414bca93e97e5a4dcb507`.
- **Target integration:** `integration/r01-weight-core` at the same baseline SHA.
- **Task branch / workspace:** `task/9-dashboard-ui`; `D:\Grok\Garmin\workspaces\9-dashboard-ui`.
- **Initial candidate:** `eec7f08f96db6aae714d4aafd1bc1bc3afb9e65e`.
- **Fix-round-1 candidate:** `0547c3d08a4ef5caf6a88d39d474465b85b55a7d`.
- **Final candidate:** `12b163d20a5f963db94f768bace9330dfa831103`.
- **Objective:** turn accepted photo-import/canonical/analytics contracts into a usable loopback dashboard and browser review flow without hiding provenance, coverage or algorithm boundaries.
- **Initial result:** added Jinja2 + vanilla JS/SVG dashboard/review pages, loopback weight series/summary/artifact routes, goal/cadence configuration, import queue and browser edit/reject/confirm flow, provenance drill-down, raw/trend/goal/composition/recomposition/coverage presentation, algorithm-boundary/BIA warnings and synthetic UI tests. No Node toolchain or #10 webhook implementation was introduced.
- **Integrator review round 1:** **FIXES REQUIRED** despite green tests. Dashboard GET paths called `CanonicalSelectionService.select()` under a committing session. Filtered reads could therefore create/supersede durable partial or empty `r01-weight` runs, making canonical history depend on browser filters.
- **Fix round 1:** Grok removed canonical writes from GET paths and added regression snapshots proving repeated/filtered `/`, `/api/weight/series` and `/api/weight/summary` reads do not mutate runs/selections. Integrator accepted that blocker as closed but found a second cross-layer defect: analytics still read all current source heads directly, so the canonical layer had effectively fallen out of the vertical slice and normal photo confirmation created no durable dashboard canonical run.
- **Fix round 2:** Grok moved canonical recomputation to the explicit photo-confirm write path, added durable `r01-weight` plus per-composition-compatibility-group scopes, and changed trend/rate/composition inputs to canonical-selected evidence. Raw current source heads remain independently inspectable with provenance and a `canonical_selected` marker. A competing-source regression proves both raw values remain visible while daily/trend/current analytics use only the canonical winner.
- **Checks:** final worker reported Ruff PASS; full pytest `132 passed` with one upstream Starlette/httpx warning; `git diff --check` PASS; live synthetic 26-image API/UI smoke PASS; GET non-mutation PASS; negative ingest probes PASS; DOM-rendered visual smoke PASS; safe-error PASS. Repository-side exact-head CI `33799919165` completed **SUCCESS** on `12b163d...`; post-merge integration CI `33800201969` completed **SUCCESS** on merge head `a6a002d...`.
- **Limitations:** owner UAT with real Xiaomi screenshots remains `UNVERIFIED`; live S400/openScale remains #10/owner-only. Bitmap screenshot capture was not available in the worker environment; visual verification used rendered DOM plus synthetic assertions.
- **Non-blocking hardening follow-up:** #11 should explicitly audit the UX/diagnostic behavior when a source write succeeds but canonical recomputation produces a failed run, so a prior successful canonical snapshot cannot be mistaken for fresh state.
- **Integrator review:** **FIXES REQUIRED → FIXES REQUIRED → ACCEPT** after actual remote diff, source-contract and CI inspection on every round.
- **Integration result:** PR #21 merged into `integration/r01-weight-core`; merge SHA `a6a002d224165f718cf6334fea28fb648f96895a`. Issue #9 closed completed.
- **Retrospective note:** #9 reinforced the same lesson seen in the Muse C2 benchmarks: cross-layer code can look polished, have comprehensive tests and still place a domain mutation or semantic source-of-truth at the wrong layer. Two narrow Integrator rounds converted a strong UI implementation into a correct write-canonical/read-canonical vertical slice without a rewrite.

## 2026-09-04 — R01-07 — openScale-sync webhook ingestion and isolated LAN receiver

- **Issue / PR:** #10 / PR #22.
- **Complexity / routing:** C3 / Hard network + ingestion + auth + idempotency + persistence; experimental Grok Bot three-role team plus independent ChatGPT/Lera Sol-family Integrator review.
- **Executor:** Grok Bots on Android/group workflow. Builder runtime/model `UNVERIFIED`; Breaker runtime/model `UNVERIFIED`; Auditor runtime label reported as `Ревьюейер (Grok Bot)`.
- **Role:** Builder was sole code writer; Breaker adversarial QA; Auditor read-only same-family gate; ChatGPT/Lera independent Integrator/merge authority.
- **Baseline:** `ef8a5117b5d2e158d87eadde394a7ad555e73533`.
- **Target integration:** `integration/r01-weight-core` at the same baseline SHA.
- **Task branch:** `task/10-openscale-webhook`.
- **Initial team candidate:** `53e5b32703af32b740e6e658aadf9aa59be07424`.
- **Final candidate:** `94aca9ae491e62ccc927ee69538edb65acaedeba`.
- **Objective:** implement the pinned openScale-sync generic-webhook contract as a secure, route-isolated live ingestion path with durable raw evidence, mixed-validity handling, replay/idempotency, tombstones, canonical reconsideration and algorithm provenance.
- **Initial result:** added authenticated `/api/ingest/openscale` on the separate ingest-only ASGI app, stable sender UUID plus rotatable bearer secret, fail-closed private-LAN binding, durable raw payload storage, savepoint-based mixed batches, insert/update/delete/clear/test state handling, openScale provenance/compatibility groups, replay handling, privacy-safe diagnostics and extensive synthetic tests. The internal Breaker found and the Builder fixed a lost `item_warnings` diagnostic path before the first team report.
- **Integrator review round 1:** **FIXES REQUIRED** despite Builder/Breaker/Auditor ACCEPT. Four findings were identified from the actual remote diff: (1) naive sender wall time was converted into invented UTC, violating accepted #19 temporal semantics; (2) deleting/clearing the last composition compatibility group could leave the prior successful composition canonical run active; (3) invalid-item quarantine identity depended on whole-envelope artifact hash/batch position, so reordered retries could duplicate failed items; (4) an automatic formatter commit rewrote accepted #7/#8 files and historical migration `0002` without semantic need.
- **Fix round:** the Grok Bot team closed all four on the same branch. Naive minute evidence now persists local wall time with `source_timestamp_utc = NULL`, supported by forward-only migration `0004_naive_minute_wall_clock`; canonical recomputation now reconsiders previously successful composition scopes and writes a newer empty successful run when final evidence disappears; invalid-item evidence keys are structural/order-independent; formatter churn was removed and accepted `0002_canonical_selection_metric_identity.py` restored blob-identical to baseline (`ff361b0c5b59e86d79abac7244c3e9a2b2daed70`).
- **Checks:** Breaker independently reported full pytest `158 passed` on the final candidate; exact-head GitHub Actions CI `33859388728` completed **SUCCESS** on `94aca9ae...`; regressions explicitly assert naive-minute no-invented-UTC durability, final composition-group empty superseding canonical run, and invalid-item retry convergence across batch reorder/JSON formatting. Post-merge integration CI `33860481127` completed **SUCCESS** on merge head `8bb43c896f4b8fbed6bd1ea937f9cad46e01c2d4`.
- **Limitations:** live owner S400/openScale phone-to-laptop flow remains `UNVERIFIED` and is explicitly non-blocking for code acceptance; worker-side GitHub issue/check APIs were partially unavailable (403), but Integrator remote read-back supplied the missing CI evidence.
- **Integrator review:** **FIXES REQUIRED → ACCEPT** after independent source/spec/diff/CI inspection. The same-family Bot Auditor's ACCEPT was treated as useful peer review, not final independent authority.
- **Integration result:** PR #22 merged into `integration/r01-weight-core`; merge SHA `8bb43c896f4b8fbed6bd1ea937f9cad46e01c2d4`. Issue #10 closed completed by Integrator after merge.
- **Benchmark retrospective:** the three-Bot shape was worthwhile: Breaker caught a real implementation defect before handoff and the team fixed narrow findings effectively. At the same time, Builder/Breaker/Auditor shared cross-layer blind spots around accepted temporal/canonical contracts, validating the need for a different-model Integrator review on C3 tasks even when an internal multi-agent team unanimously ACCEPTs.