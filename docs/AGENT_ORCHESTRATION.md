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

## Launch compatibility assessment

Before issuing an implementation launch, the Integrator records a compact execution decision in the issue or explicit Integrator note. The Worker/Orchestrator checks it before writes. For one isolated task, a few lines are enough; for a task set, use a table:

| Task | Dependency / pinned contract | Shared files, interfaces, migrations, versions | Single owner / write boundary | Mode, order and reason |
| --- | --- | --- | --- | --- |
| Issue ID | Accepted baseline or explicit fixture/strategy | Include planned new modules and exports | Accountable task for each shared artifact | One Worker / sequential / explicitly parallel |

Read the current issue and applicable Integrator comments, dependency acceptance state and relevant baseline interfaces. Use authoritative assignment records to check active ownership; this does not authorize inspection of another task's workspace. Record source comment IDs/URLs and when checked. An unresolved conflict blocks the affected launch until the Integrator supplies a bounded decision.

- **One Worker is the default** for one bounded task, including focused remediation. An independent reviewer can still be required without a full orchestration loop.
- **Orchestration is useful** for an explicitly authorized queue or a task that benefits from managed review/remediation and evidence coordination. State that benefit; complexity alone does not require delegation.
- **Sequence dependent work:** establish and integrate a shared schema/API/DTO/version contract first, then launch its consumer. Starting earlier requires an explicit stable fixture/contract and safe baseline/integration strategy.
- **Parallel implementation requires explicit Owner opt-in and proven compatible boundaries.** Separate worktrees alone are insufficient. Check newly created modules, package exports, migration heads/constraints, version constants and propagated evidence fields. If two tasks design the same contract, assign one owner and resolve the boundary before release; otherwise run sequentially.
- **Do not rewrite active assignments silently.** Apply this assessment to new launches; changes to ongoing work need an explicit Integrator instruction.

Use the implementation issue template to preserve the decision. A short launch prompt points to it rather than copying the entire issue.

## Early contract checkpoint and final gates

For schema, replay, eligibility, statistics or other cross-layer risk, require a small requirement map before broad implementation: `source requirement -> input/API boundary -> adversarial acceptance test`. Cover relevant negative cases from the contract, such as failed/running successors, incomplete or cross-run rows, explicit replay versions, propagated exclusion flags, authoritative epoch identity and boundary gaps. Do not invent requirements or thresholds absent from the issue/spec.

The Worker writes/runs focused acceptance checks using actual production DTOs/entry points where practical. An unresolved architecture/health-semantics decision returns to the Integrator. Use an early independent contract review for such high-risk reasoning when warranted; final candidate review remains separate. Routine docs/mechanical work can mark this checkpoint not applicable.

Run targeted checks during implementation. Schedule issue-required full pytest/harness and CI after the relevant implementation stabilizes; preserve exact candidate/command/outcome evidence. Do not repeat a passing suite on an unchanged candidate merely because a polling session disappeared. A semantic change invalidates affected evidence and requires the applicable gates again. Independent review and final checks may overlap on one frozen candidate unless the issue/spec requires a particular order; all required gates must pass before internal acceptance.

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

- `дай задачу для Codex` -> Mode A, one Worker by default;
- `дай серию задач для Codex` -> assess the explicitly assigned set and propose an order; automatic queue execution requires an explicit orchestration launch;
- explicit `$delivery-loop` / orchestration request -> Mode B after launch compatibility assessment;
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
8. `completion_mode=review-and-stop` returns findings without automatic fixes; otherwise default to one remediation cycle, with a second only explicitly authorized or demonstrably mechanical and bounded; never exceed two;
9. internal verdicts are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`;
10. `INTERNAL_ACCEPT` is evidence only and never equals project `ACCEPT`.

The Execution Orchestrator has no implicit authority to merge an integration branch or `main`.

## Queue policy

### Single

One task is implemented, internally reviewed and reported, then the run stops.

### Independent queue

Only tasks explicitly listed by the Integrator may advance automatically. Every task has its own task branch, physical writer workspace and exact assigned baseline. A previous candidate is not an implicit baseline for the next task.

This queue mode is sequential: the previous task must reach `INTERNAL_ACCEPT` before the next eligible task starts. Explicit parallel assignments follow the launch compatibility assessment instead and retain separate per-task acceptance gates.

### Dependency / integration block

If task B requires task A to be integrated first and no explicit safe dependency strategy was supplied, task B becomes `BLOCKED_FOR_INTEGRATION`.

That status blocks the affected dependency chain. Unrelated explicitly listed eligible tasks may continue only when the queue launch explicitly permits integration-block continuation; otherwise stop the queue.

Do not invent stacked history, merge the release integration line, or pick replacement work from roadmap/backlog.

## Independent review triggers

Use a separate Reviewer when:

1. project complexity/routing requires it;
2. Owner/Integrator explicitly requests it;
3. justified risk discovered during execution raises the review requirement under project policy.

The third case is not permission to broaden scope. Reinterpretation of health semantics, architecture, privacy boundaries or canonical data contracts requires STOP + Integrator decision.

## Reporting

### Per-task report

Return task/issue ID, runtime-reported client/model/delegates when available, exact baseline/target, task branch/workspace, candidate SHA, changed areas, exact checks/outcomes, deviations, blockers/limitations and final local state. Orchestrated runs also record execution-mode rationale, completion/remediation mode and a compact phase ledger with evidence references. Separate wall time from overlapping job durations; report usage/cost only when measured, otherwise unknown.

### Final queue report

An orchestrated queue additionally returns every listed task and its final internal status, candidate SHA where applicable, review path used and unresolved Integrator action.

The final queue report is not batch project acceptance.

## Local skills/config

`$delivery-loop`, local model routing and subagent definitions are machine-local Codex mechanics. Repository docs do not hardcode their filesystem paths or current model IDs.

Do not create a Health-specific skill merely for symmetry. A project-specific skill is justified only for a genuinely reusable Health-specific procedure that should be loaded progressively and does not duplicate architecture/spec/policy.

## Invariants automation cannot weaken

Private owner health/runtime data remains outside development-agent workspaces. Synthetic fixtures remain the normal test basis. One writer owns one write workspace. Missing/unknown/unavailable is not silently zero. Agents do not invent diagnosis or causality. Canonical integration remains Integrator-controlled.
