# Development Process

This document defines how Health-Check work is planned, implemented by external coding agents, reviewed, integrated and preserved for later retrospectives/articles.

The workflow intentionally reuses lessons from `LTstripes/hermes-finance`, while reducing unnecessary rebases and central-log merge conflicts.

Execution-mode semantics are additionally defined in `docs/AGENT_ORCHESTRATION.md`.

## 1. Core operating model

Normal manual/brokered flow:

1. Owner discusses a need with the Integrator (ChatGPT/Lera).
2. Integrator classifies complexity/model routing and creates/updates the authoritative GitHub issue.
3. Integrator chooses the release integration baseline, task branch and assigned local workspace.
4. Integrator sends the Owner a short copyable launch prompt.
5. Owner launches the selected Worker in Codex, Grok Build, Hermes or another selected client.
6. Worker reads `AGENTS.md`, the issue and the active release spec when one is designated; implements only the task; tests; commits/pushes its task branch; returns a completion report.
7. Owner forwards that report to the Integrator.
8. Integrator reads the actual GitHub branch/diff/check evidence, reviews it and decides ACCEPT / FIXES REQUIRED / REJECT.
9. Accepted work is merged by the Integrator into the current release integration branch (or `main` for a deliberately tiny standalone task).
10. Integrator updates engineering history and any canonical docs made stale.
11. At release gate, Owner-only preview/UAT validates the integrated release.
12. Integrator reviews and merges the release integration PR into `main`, then reads back canonical state and exact post-merge CI.
13. The completed release integration line becomes historical/staging-only; the next release starts from the new canonical `main`.

Workers implement. The Integrator owns project acceptance, GitHub integration and durable engineering history.

### 1.1 Owner execution intent

- `дай задачу для Grok` -> manual Grok Worker;
- `дай задачу для Hermes` -> manual Hermes Worker;
- `дай задачу для <model/client>` -> manual Worker unless orchestration is explicitly requested;
- `Codex без оркестрации` -> manual Codex Worker;
- `дай задачу для Codex` -> Codex `$delivery-loop` single-task route by default;
- `дай серию задач для Codex` -> explicitly bounded Codex `$delivery-loop` queue.

The Integrator honors the requested implementation route while continuing to perform GitHub-side issue/PR/review/merge mechanics directly when available.

### 1.2 Codex `$delivery-loop` route

For an orchestrated Codex task, the strong root acts as **Execution Orchestrator** and delegates implementation to the locally configured **Worker**. The root does not duplicate delegated write work.

For every task the launch packet specifies:

- issue/task ID;
- active release/integration context;
- exact baseline;
- task branch;
- physical workspace;
- queue mode;
- dependency status;
- independent-review requirement.

The root reviews actual candidate/check evidence after the Worker returns. A separate Reviewer is used when project routing requires independent review, when the Owner/Integrator explicitly requests it, or when justified execution risk raises the review bar. Such risk does not authorize scope expansion: architecture/privacy/canonical-data/health-semantics expansion remains STOP + Integrator re-scope.

Automatic remediation is bounded to two cycles. Internal results are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`. `INTERNAL_ACCEPT` never equals project `ACCEPT`.

For an explicitly authorized independent queue:

- every task keeps its own branch/workspace/exact baseline;
- a previous candidate is not an implicit baseline for the next task;
- one task reaches `INTERNAL_ACCEPT` before the next eligible task starts;
- if a task requires prior integration and no safe dependency strategy was supplied, it becomes `BLOCKED_FOR_INTEGRATION`;
- that blocks the affected dependency chain, not unrelated explicitly listed eligible tasks;
- the Orchestrator must not invent stacked history, merge the integration branch or select replacement backlog work.

Codex returns per-task evidence plus one final queue report covering every authorized task. That queue report is not batch project acceptance.

## 2. Branch strategy

### `main`

Canonical stable/accepted project state and the only release source. No coding agent writes directly to it.

### Release integration branch

For releases composed of multiple tasks, create one branch from current `main`, for example:

- `integration/r01-weight-core`
- `integration/r02-garmin`

This branch is the moving integration target for that release. It solves the old Finance problem where every task had to chase a moving `main` while parallel development was active.

Task PRs target the release integration branch. Only after release integration/UAT passes do we open one integration -> `main` PR.

A release integration branch is never a second source of truth and must not become the baseline for the next release after it has already been released. Once its release is merged to `main`, the next release integration branch is created from the then-current canonical `main`.

Accepted task branches that were intentionally held during a release freeze must be re-read against the new `main`; their old acceptance does not by itself make their historical branch merge-ready after the freeze lifts.

### Task branches

Pattern:

`task/<github-issue>-<short-slug>`

A task branch starts from an exact pinned SHA of the release integration branch. The issue and launch prompt record that SHA.

### Parallel work

Only genuinely independent scopes run in parallel. If task B depends on task A's schema/API, task B starts only after A is integrated unless the issue explicitly provides a stable contract fixture or the Integrator explicitly supplies a safe dependency/baseline strategy.

A task does not rebase continuously. If integration advances while a Worker is coding, the Worker stays on the pinned baseline. At review time the Integrator decides whether:

- candidate is independent and can merge cleanly as-is;
- one refresh/retest pass is needed;
- candidate conflicts semantically and must be revised.

Schema/migration/security/network/canonical-data tasks are treated conservatively and normally refresh/retest against latest integration before acceptance.

For stacked accepted work created before the previous release completed, reconstruct the accepted semantic deltas onto the new canonical lineage instead of blindly merging a diverged stack. Preserve exact accepted behavior, migration order and review evidence; rerun exact-head checks on the reconstructed line.

## 3. Local workspace layout

GitHub is canonical. Local paths are execution/preview locations, not sources of truth.

`D:\Garmin` is the Owner-only parent root. It contains separate main and UAT checkouts; the parent directory itself is not a mutable Git checkout.

### Owner canonical checkout

`D:\Garmin\Garmin-Main`

Purpose:

- Owner/Integrator stable checkout of accepted `main`;
- convenient local read/run point after releases;
- never a development-agent workspace.

Other coding agents must not access, branch-switch, reset or use this checkout.

### Owner preview/UAT checkout

`D:\Garmin\Garmin-UAT`

Purpose:

- Owner-only checkout of the current release integration candidate;
- browser/manual preview;
- live S400/Garmin/Fitbit probes when their release reaches that gate;
- private UAT data profiles.

Coding Workers/Execution Orchestrators must not use this workspace.

Runtime/private data remains outside Git checkout, preferably through release/profile-specific `HEALTHCHECK_DATA_DIR`, for example `%LOCALAPPDATA%\Health-Check\uat` and later `%LOCALAPPDATA%\Health-Check\prod`. Do not reuse one private database across arbitrary branches.

### Codex root

`D:\Codex\Garmin`

Task workspace pattern:

`D:\Codex\Garmin\workspaces\<issue>-<slug>`

### Grok Build root

`D:\Grok\Garmin`

Task workspace pattern:

`D:\Grok\Garmin\workspaces\<issue>-<slug>`

### Hermes root

`D:\Hermes Project\hermes-garmin`

Task workspace pattern:

`D:\Hermes Project\hermes-garmin\workspaces\<issue>-<slug>`

The three paths above are parent roots. Do not keep one shared mutable clone at the root and switch branches between concurrent tasks. Each active task owns its own clone/worktree directory.

If these machine paths change, the issue/Integrator launch note may override them; repository branch and issue remain authoritative.

## 4. Workspace creation rules for workers

A Worker may create only the task directory explicitly assigned below its client root. It may clone/fetch the repository there and check out the assigned branch/baseline.

Workers, Delegates and Execution Orchestrators must not:

- inspect `D:\Garmin\Garmin-Main` or `D:\Garmin\Garmin-UAT`;
- reuse another task directory;
- create sibling roots elsewhere on disk;
- link private Owner runtime/data into a dev clone;
- switch/reset a working tree currently used by another session.

Parallel Hermes bots/Delegates follow the same invariant. Multiple simultaneous writers require separate sub-workspaces/branches; a supervising Hermes Worker remains accountable for the final candidate and reports all Delegates used.

## 5. Task definition

The Integrator creates a GitHub issue before implementation. It should include:

- release/task ID and objective;
- complexity/risk class and recommended executor/route;
- target integration branch and exact baseline SHA;
- dependencies;
- required source documents;
- in-scope and explicit out-of-scope;
- acceptance criteria;
- privacy/live-data boundary;
- exact expected verification;
- expected completion report.

Task requirements live in GitHub, not only in chat. If scope changes, the issue body or an explicit `Integrator note` comment is updated before the Worker implements the new requirement.

## 6. Launch prompt convention

### Manual Worker

The Integrator sends the Owner a short prompt, normally like:

```text
Health-Check task #NN — <title>
Complexity: C2 / Normal
Recommended executor: <client/model>

Repo: https://github.com/LTstripes/Health-Check
Issue: <URL>
Target integration: integration/<active-release> @ <SHA>
Branch: task/<issue>-<slug>
Workspace: <assigned workspace>

Read AGENTS.md, the issue and the active release spec if one is designated. Implement only the issue. Run the required checks. Commit/push only the task branch. Do not merge or modify main/integration. Return the Worker completion report with exact final SHA.
```

### Codex `$delivery-loop` single task

The prompt additionally states:

- explicit `$delivery-loop`;
- `queue_mode=single`;
- root = Execution Orchestrator;
- implementation belongs to the local configured Worker;
- independent-review requirement;
- max two remediation cycles;
- `INTERNAL_ACCEPT != project ACCEPT`;
- no implicit integration/main merge authority.

### Codex `$delivery-loop` queue

One queue launch packet may list several explicitly authorized tasks. It must state exact baseline/branch/workspace/dependency/review data for every task and require:

- progression only through listed eligible items;
- `INTERNAL_ACCEPT` before advancing;
- `BLOCKED_FOR_INTEGRATION` for unresolved dependency integration gaps;
- unrelated explicitly listed eligible tasks may continue;
- no invented tasks/stacking/merge;
- per-task evidence plus one final queue report.

The issue contains details; launch prompts are locators/execution contracts, not second specifications.

## 7. Worker / Orchestrator completion -> Integrator review

The Owner forwards the Worker completion report or Codex queue report. The Integrator does not accept that summary as proof.

Integrator checks, as applicable:

- branch and exact baseline/candidate SHAs;
- actual GitHub diff and changed-file scope;
- whether task/architecture contracts were followed;
- tests/checks actually evidenced;
- privacy/secrets/runtime-data boundary;
- migrations/schema/data semantics;
- docs made stale;
- whether required independent review actually ran;
- whether integration branch moved and whether refresh is needed.

Possible verdicts:

- **ACCEPT** — candidate is integrated or explicitly accepted-and-held with a stated future gate.
- **FIXES REQUIRED** — same issue/candidate remains open with explicit findings.
- **REJECT** — approach/candidate is not integrated; reason is preserved in history.

`INTERNAL_ACCEPT` is only an internal Codex delivery-loop verdict and never substitutes for this Integrator decision.

A Reviewer never silently repairs a candidate and then calls the original Worker's result accepted. Trivial Integrator-owned documentation/metadata fixes may be explicit separate commits; behavioral fixes become a follow-up Worker pass/task.

## 8. Engineering history — everything useful is retained

`docs/EXECUTION_HISTORY.md` is maintained by the Integrator, not by parallel Workers/Execution Orchestrators.

Record both successful and useful failed/rejected attempts. Each entry should capture:

- date;
- release/task/issue;
- executor client/model and any Hermes Delegates/fallbacks or Codex root/Worker/Reviewer attribution when known;
- complexity/routing decision;
- baseline/integration SHA;
- task branch and candidate SHA;
- original objective;
- what was actually implemented;
- important files/areas;
- tests/checks;
- unexpected problems;
- decisions changed during implementation and why;
- review findings/verdict;
- merge/integration SHA or rejection reason;
- retrospective note worth remembering for a future article/process improvement.

Do not store private health values, screenshots, credentials or raw personal payloads in engineering history.

### Durable decision split

- **Execution History**: what happened, by whom, problems/outcome.
- **Issue**: authoritative task scope.
- **Architecture/Decision docs or ADR**: durable rule changed for future work.
- **Roadmap**: current release sequence.
- **Backlog Ideas**: non-committed future ideas.

This avoids a giant diary becoming the product specification.

## 9. Model/agent attribution

Record the runtime-reported model when known. Do not infer model identity from a UI label if the runtime/report says something else.

If Hermes starts with one model and falls back/delegates to another, record the chain, for example:

`Step 3.7 Flash -> DeepSeek V4 Flash fallback`

If Codex orchestrates, preserve runtime-reported root/Worker/Reviewer attribution when known.

That history is useful for later model benchmarks and the eventual story of how the project was built.

## 10. Release integration and UAT

`docs/R01_OWNER_UAT.md` is the historical Owner checklist for R01. Future releases should use their own release-specific UAT checklist/issue rather than treating the R01 checklist as current by default.

When all planned tasks for a release are integrated:

1. Integrator reviews the complete integration diff against the release spec.
2. Automated full release checks pass.
3. Owner UAT/preview runs from `D:\Garmin\Garmin-UAT`, using a separate private runtime profile.
4. Live/provider/device probes required by that release are performed or explicitly remain `UNVERIFIED` if allowed by the spec.
5. Integrator resolves findings in dedicated task branches, not by ad-hoc edits in UAT checkout.
6. Integrator opens/reviews integration -> `main` PR.
7. Accepted release is merged to `main`.
8. Exact post-merge `main` CI is checked and canonical `main` is read back.
9. `D:\Garmin\Garmin-Main` is fast-forwarded to canonical `main` by the Owner when convenient; GitHub remains canonical.
10. Release documentation/history is synchronized.
11. The completed integration branch is no longer used as the next release baseline; create the next release integration branch from current `main`.

## 11. Benchmark / A-B tasks

When intentionally comparing models on the same task:

- pin one exact baseline;
- give each candidate a separate branch/workspace;
- candidates do not read/copy one another before completion;
- compare actual diffs/tests/evidence, not prose confidence;
- log model, timing if known, candidate SHA, result and Integrator verdict in Execution History.

Benchmark candidates are not automatically merged; the Integrator selects or synthesizes the accepted approach.

## 12. Current Codex and future provider automation

Codex `$delivery-loop` is now a supported execution mode under `docs/AGENT_ORCHESTRATION.md`.

Later we may automate issue pickup, Worker/Reviewer bots and integration inside Hermes or another provider-neutral orchestration layer. The same contracts remain:

- issue is authority;
- isolated workspace/branch per writer;
- Delegates cannot self-accept;
- final Integrator gate remains explicit;
- execution history records the delegation chain;
- private Owner runtime remains outside bot workspaces.

Automation may remove manual message shuttling; it must not remove accountability or evidence.
