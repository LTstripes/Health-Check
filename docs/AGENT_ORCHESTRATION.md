# Agent orchestration — Health-Check

> **Status:** project-facing execution contract. Local client orchestration implements this contract but does not override repository policy.

Health-Check supports a manual Worker route and an optional Codex `$delivery-loop` route. The active GitHub issue, release/architecture contracts and explicit Integrator notes remain authoritative under `AGENTS.md` precedence.

## Roles

- **Owner** — product direction and owner-only/private/live UAT.
- **Integrator** — normally ChatGPT/Lera. Owns project task decomposition/routing, authoritative issue/notes, final `ACCEPT / FIXES REQUIRED / REJECT`, GitHub integration/merge and durable history/docs.
- **Execution Orchestrator** — optional execution-local coordinator. In Codex `$delivery-loop` mode this is the strong root session. It may plan, delegate, internally review/remediate and coordinate an explicitly authorized queue, but it does not own project acceptance.
- **Worker** — one accountable implementation writer for one candidate. Does not self-accept.
- **Delegate** — bounded helper below a Worker/Orchestrator. Does not self-accept.
- **Reviewer** — independent validator when routing, an explicit request or justified execution risk requires one. Does not silently modify the candidate.

Root/Orchestrator self-review is not independent review.

## Mode A — manual / brokered execution

Normal flow:

`Owner -> Integrator -> authoritative issue -> short launch prompt -> selected Worker -> completion report -> Integrator GitHub review -> FIXES REQUIRED / ACCEPT / REJECT -> Integrator integration`

Examples:

- `дай задачу для Grok` -> manual Grok Worker;
- `дай задачу для Hermes` -> manual Hermes Worker;
- `дай задачу для <model/client>` -> manual Worker unless orchestration is explicitly requested;
- `Codex без оркестрации` -> manual Codex Worker.

## Mode B — Codex `$delivery-loop`

Owner intent:

- `дай задачу для Codex` -> orchestrated single-task route by default;
- `дай серию задач для Codex` -> explicitly bounded queue;
- `Codex без оркестрации` -> Mode A.

The launch packet must identify the repo, issue/task list, active release/integration context, exact baseline for every task, task branch, physical workspace, queue mode and review requirement.

In orchestrated mode:

1. root = **Execution Orchestrator**;
2. implementation is delegated to the locally configured Worker;
3. root does not duplicate delegated write work;
4. Worker verifies and returns exact candidate evidence;
5. root reviews actual diff/check evidence;
6. a separate independent Reviewer is used when `MODEL_ROUTING.md`, an explicit Owner/Integrator request, or justified execution risk requires one;
7. justified risk may raise the review bar inside the current task, but architecture/scope/health-semantics changes still require STOP + Integrator re-scope;
8. automatic remediation is bounded to two cycles;
9. internal verdicts are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`;
10. `INTERNAL_ACCEPT` is evidence only and never equals project `ACCEPT`.

The Execution Orchestrator has no implicit authority to merge an integration branch or `main`.

## Queue policy

### Single

One task is implemented, internally reviewed and reported, then the run stops.

### Independent queue

Only tasks explicitly listed by the Integrator may advance automatically. Every task has its own task branch, physical writer workspace and exact assigned baseline. A previous candidate is not an implicit baseline for the next task.

The previous task must reach `INTERNAL_ACCEPT` before the next eligible task starts.

### Dependency / integration block

If task B requires task A to be integrated first and no explicit safe dependency strategy was supplied, task B becomes `BLOCKED_FOR_INTEGRATION`.

That status blocks the affected dependency chain, **not the whole queue**. Unrelated explicitly listed eligible tasks may continue.

Do not invent stacked history, merge the release integration line, or pick replacement work from roadmap/backlog.

## Independent review triggers

Use a separate Reviewer when:

1. project complexity/routing requires it;
2. Owner/Integrator explicitly requests it;
3. justified risk discovered during execution raises the review requirement under project policy.

The third case is not permission to broaden scope. Reinterpretation of health semantics, architecture, privacy boundaries or canonical data contracts requires STOP + Integrator decision.

## Reporting

### Per-task report

Return task/issue ID, runtime-reported client/model/delegates when available, exact baseline/target, task branch/workspace, candidate SHA, changed areas, exact checks/outcomes, deviations, blockers/limitations and final local state.

### Final queue report

An orchestrated queue additionally returns every listed task and its final internal status, candidate SHA where applicable, review path used and unresolved Integrator action.

The final queue report is not batch project acceptance.

## Local skills/config

`$delivery-loop`, local model routing and subagent definitions are machine-local Codex mechanics. Repository docs do not hardcode their filesystem paths or current model IDs.

Do not create a Health-specific skill merely for symmetry. A project-specific skill is justified only for a genuinely reusable Health-specific procedure that should be loaded progressively and does not duplicate architecture/spec/policy.

## Invariants automation cannot weaken

Private owner health/runtime data remains outside development-agent workspaces. Synthetic fixtures remain the normal test basis. One writer owns one write workspace. Missing/unknown/unavailable is not silently zero. Agents do not invent diagnosis or causality. Canonical integration remains Integrator-controlled.
