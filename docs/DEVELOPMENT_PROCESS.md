# Development Process

This document defines how Health-Check work is planned, implemented by coding agents, reviewed, integrated and preserved for retrospectives/articles.

The workflow intentionally reuses lessons from `LTstripes/hermes-finance`, while keeping GitHub authoritative, reducing unnecessary rebases and avoiding central-log merge conflicts.

Execution-mode details are also summarized in `docs/AGENT_ORCHESTRATION.md`.

## 1. Core operating model

### Project ownership

1. Owner discusses a need with the Integrator (ChatGPT/Lera).
2. Integrator classifies complexity/risk, chooses routing and creates/updates the authoritative GitHub issue.
3. Integrator selects the release integration baseline, task branch and assigned local workspace.
4. Implementation runs either through a manual Worker route or an explicitly orchestrated Codex route.
5. Integrator reviews the actual GitHub candidate/evidence and decides project `ACCEPT / FIXES REQUIRED / REJECT`.
6. Accepted work is integrated by the Integrator.
7. Integrator updates engineering history and affected canonical docs.
8. Release integration/UAT/main merge proceeds under the normal release gates below.

Workers implement. An Execution Orchestrator may coordinate local work, but the Integrator still owns project acceptance, GitHub integration and durable engineering history.

## 2. Execution mode A — manual Worker

Normal manual flow:

1. Integrator creates/updates the authoritative issue.
2. Integrator selects the Worker/client and exact baseline/branch/workspace.
3. Integrator sends the Owner a short copyable launch prompt.
4. Owner launches the selected Worker in Grok Build, Hermes, manual Codex or another selected client.
5. Worker reads `AGENTS.md`, the issue and active release spec when designated; implements only the task; tests; commits/pushes its task branch; returns a completion report.
6. Owner returns that report to the Integrator.
7. Integrator reads actual GitHub branch/diff/check evidence and decides `ACCEPT / FIXES REQUIRED / REJECT`.
8. Integrator performs repository integration and history/docs updates.

Typical Owner intent:

- `дай задачу для Grok` -> Grok Worker;
- `дай задачу для Hermes` -> Hermes Worker;
- `дай задачу для <model/client>` -> that client as Worker;
- `Codex без оркестрации` -> Codex as one Worker.

## 3. Execution mode B — Codex `$delivery-loop`

Typical Owner intent:

- `дай задачу для Codex` -> orchestrated `single` task by default;
- `дай серию задач для Codex` -> explicitly bounded queue.

Before launching a queue, the Integrator inspects current GitHub state and selects only tasks that are eligible for the intended dependency strategy.

The launch packet includes for each task:

- issue/task ID;
- active release/integration context;
- exact baseline;
- task branch;
- physical workspace;
- dependency status;
- independent-review requirement.

Inside Codex:

1. strong root acts as **Execution Orchestrator**;
2. root validates project policy and task packet;
3. implementation is delegated to the locally configured **Worker**;
4. root does not duplicate delegated write work;
5. Worker tests and returns exact candidate evidence;
6. root reviews actual diff/check evidence;
7. a separate Reviewer is used when project routing, explicit Owner/Integrator request, or justified execution risk requires independent review;
8. remediation is bounded to two automatic cycles;
9. internal result is `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`;
10. project `ACCEPT` still belongs to the Integrator.

### Queue progression

For independent queue items:

- each task has its own task branch/workspace/baseline;
- previous candidate history is not an implicit baseline;
- previous task reaches `INTERNAL_ACCEPT` before the next eligible task starts.

If task B requires task A to be integrated first and no explicit safe dependency strategy was supplied, B becomes `BLOCKED_FOR_INTEGRATION`.

That blocks only the affected dependency chain. Unrelated explicitly listed eligible tasks may continue.

The Orchestrator must not invent stacked history, merge the release integration branch, or discover replacement tasks from roadmap/backlog.

### Reporting

Codex returns:

- the normal per-task evidence for every attempted task;
- one final queue report listing every authorized task, final internal state, candidate SHA where applicable, review path and unresolved Integrator action.

The final queue report is not project acceptance.

## 4. Branch strategy

### `main`

Canonical stable/accepted project state and the only release source. No coding Worker writes directly to it.

### Release integration branch

For releases composed of multiple tasks, create one branch from current `main`, for example:

- `integration/r01-weight-core`
- `integration/r02-garmin`

This branch is the moving integration target for that release, not a second source of truth.

Task PRs target the release integration branch. Only after release integration/UAT passes do we open integration -> `main` PR.

After a release is merged to `main`, its integration branch becomes historical/staging-only. The next release integration branch starts from then-current canonical `main`.

Accepted-but-held work from a previous freeze must be re-read against new canonical lineage; historical acceptance alone does not make it merge-ready.

### Task branches

Pattern:

`task/<github-issue>-<short-slug>`

A task branch starts from an exact pinned SHA of the assigned target/integration branch. The issue/launch packet records that SHA.

### Parallel work

Only genuinely independent scopes run in parallel.

If task B depends on task A's schema/API, B starts only after A is integrated unless the issue/Integrator explicitly provides a stable contract/baseline strategy.

Workers do not continuously rebase because integration moved. Integrator decides at review time whether candidate is independent, needs one refresh/retest pass, or must be revised.

Schema/migration/security/network/canonical-data work is treated conservatively and normally refreshed/retested against latest relevant integration state before acceptance.

## 5. Local workspace layout

GitHub is canonical. Local paths are execution/preview locations, not sources of truth.

`D:\Garmin` is the Owner-only parent root.

### Owner canonical checkout

`D:\Garmin\Garmin-Main`

Stable accepted `main` checkout. Never a development-agent workspace.

### Owner preview/UAT checkout

`D:\Garmin\Garmin-UAT`

Owner-only release preview/live UAT workspace. Coding agents must not use or inspect it.

Runtime/private data remains outside Git checkout through release/profile-specific data directories. Do not reuse one private database across arbitrary branches.

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

These are parent roots. Do not keep one shared mutable clone at the root and switch branches between concurrent tasks. Each active write task owns its own workspace.

If machine paths change, explicit issue/Integrator launch instructions may override them; repository branch/issue remain authoritative.

## 6. Workspace creation rules

A Worker may create only the task directory explicitly assigned below its client root.

Workers/Delegates/Execution Orchestrators must not:

- inspect `D:\Garmin\Garmin-Main` or `D:\Garmin\Garmin-UAT`;
- reuse another active task directory;
- create unrelated sibling roots elsewhere;
- link private Owner runtime/data into a development workspace;
- switch/reset a working tree used by another active task.

Multiple simultaneous writers require separate explicit branches/workspaces. A supervising Hermes Worker remains accountable for its final candidate and delegate chain.

## 7. Task definition

The Integrator creates a GitHub issue before implementation. It should contain:

- release/task ID and objective;
- complexity/risk class and recommended execution route;
- target integration branch and exact baseline SHA;
- dependencies;
- required source documents;
- in-scope / out-of-scope;
- acceptance criteria;
- privacy/live-data boundary;
- required verification;
- expected completion report.

Task requirements live in GitHub, not only in chat. If scope changes, update the issue or add an explicit `Integrator note` before implementing the changed requirement.

## 8. Launch prompt conventions

### Manual Worker prompt

```text
Health-Check task #NN — <title>
Complexity: C2 / Normal
Recommended executor: <client/model>

Repo: https://github.com/LTstripes/Health-Check
Issue: <URL>
Target integration: integration/<active-release> @ <SHA>
Branch: task/<issue>-<slug>
Workspace: <assigned task workspace>

Read AGENTS.md, the issue and active release spec if designated. Implement only the issue. Run required checks. Commit/push only the task branch. Do not merge main/integration. Return the Worker completion report with exact final SHA.
```

### Codex `$delivery-loop` single prompt

Adds:

- explicit `$delivery-loop`;
- `queue_mode=single`;
- root = Execution Orchestrator;
- implementation delegated locally;
- independent-review requirement;
- max two remediation cycles;
- `INTERNAL_ACCEPT != project ACCEPT`;
- no canonical/integration merge authority.

### Codex `$delivery-loop` queue prompt

Lists every authorized task with exact baseline/branch/workspace/dependency/review data and states:

- progress only through listed eligible tasks;
- one task reaches `INTERNAL_ACCEPT` before next eligible item;
- dependency integration gaps become `BLOCKED_FOR_INTEGRATION`;
- unaffected listed tasks may continue;
- return per-task evidence + final queue report.

The issue contains requirements; prompts are execution locators/contracts, not duplicate specifications.

## 9. Completion -> Integrator review

The Integrator does not accept Worker/Orchestrator summaries as proof.

Check, as applicable:

- branch and exact baseline/candidate SHAs;
- actual GitHub diff and scope;
- issue/architecture/release-contract compliance;
- tests/checks actually evidenced;
- privacy/secrets/runtime boundary;
- migrations/schema/canonical-data semantics;
- whether required independent review actually ran;
- whether target integration moved and refresh is needed.

Verdicts:

- **ACCEPT** — project candidate accepted/integrated or explicitly accepted-and-held with a stated gate.
- **FIXES REQUIRED** — candidate remains open with explicit findings.
- **REJECT** — approach/candidate not integrated; reason is retained.

`INTERNAL_ACCEPT` from Codex means only that its local delivery loop passed its internal gate.

A reviewer never silently repairs a candidate and then calls the original result independently accepted. Behavioral fixes normally return to a Worker.

## 10. Engineering history

`docs/EXECUTION_HISTORY.md` is maintained by the Integrator, not by parallel Workers/Orchestrators.

Record useful successful and failed/rejected attempts, including executor/client/model/delegates/fallbacks, complexity/routing, baseline/candidate, checks, important problems, review verdict and integration/rejection outcome.

Do not store private health values, screenshots, credentials or raw personal payloads.

Durable split:

- **Execution History** — what happened.
- **Issue** — authoritative task scope.
- **Architecture/ADR/decision docs** — durable rule.
- **Roadmap** — release sequence.
- **Backlog Ideas** — non-committed future ideas.

## 11. Model/agent attribution

Record runtime-reported model when known. Do not infer identity solely from UI labels when stronger runtime evidence exists.

If Hermes falls back/delegates, record the actual chain. If Codex orchestrates, preserve root/Worker/Reviewer attribution when available.

## 12. Release integration and UAT

When all planned tasks for a release are integrated:

1. Integrator reviews the complete integration diff against the release spec.
2. Automated full release checks pass.
3. Owner UAT/preview runs from `D:\Garmin\Garmin-UAT` with a separate private runtime profile.
4. Required live/provider/device probes run or explicitly remain `UNVERIFIED` when allowed.
5. Findings are resolved in dedicated task branches, not ad-hoc UAT edits.
6. Integrator opens/reviews integration -> `main` PR.
7. Accepted release is merged to `main`.
8. Exact post-merge `main` CI is checked and canonical `main` read back.
9. Owner canonical checkout may be fast-forwarded when convenient; GitHub remains canonical.
10. Release documentation/history is synchronized.
11. Next release integration branch starts from current canonical `main`.

## 13. Benchmark / A-B tasks

When intentionally comparing models:

- same exact baseline;
- separate branches/workspaces;
- candidates do not inspect each other before completion;
- compare actual diffs/tests/evidence;
- record timing/cost when known;
- Integrator selects/synthesizes the accepted result.

## 14. Automation beyond current Codex orchestration

Codex `$delivery-loop` is a currently supported execution mode.

Future Hermes/provider-neutral automation may later remove more manual message shuttling, but the same contracts remain: issue authority, isolated writers, no self-accept, explicit Integrator final gate, attribution/history, and strict private-runtime isolation.
