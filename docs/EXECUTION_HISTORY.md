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
