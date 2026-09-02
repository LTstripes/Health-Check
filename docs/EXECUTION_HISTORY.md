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
- **Workspace decision:** `D:\Garmin` is owner stable checkout; recommended owner preview/UAT checkout is `D:\Garmin-UAT`; Codex/Grok/Hermes receive separate task-workspace roots documented in `docs/DEVELOPMENT_PROCESS.md`.
- **Parallelism decision:** use a release integration branch (for example `integration/r01-weight-core`) so active tasks do not continuously chase moving `main`. Each task remains pinned to one integration SHA until review; refresh/retest is risk-based at integration time.
- **Logging decision:** normal workers do not edit this shared history file. They return structured completion reports; Integrator appends accepted/rejected/failed attempt history centrally, preventing parallel log merge conflicts and preserving neutral attribution.
- **Model routing:** every task presented to the owner starts with complexity, recommended executor, alternative and reviewer requirement; concrete model names are per-task guidance rather than permanent repository truth.
