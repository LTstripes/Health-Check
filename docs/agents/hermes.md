# Hermes — Worker / Delegation Adapter

Universal rules in `/AGENTS.md` are authoritative.

## Assigned root

Use only the physical task workspace explicitly assigned in the launch/Owner-local configuration under the location-role protections in `docs/DEVELOPMENT_PROCESS.md`. Owner canonical, Stable/private-runtime and preview/UAT locations, another client's root and other active task workspaces are excluded. Missing or conflicting assignments must be resolved before writes.

## Accountable Hermes Worker

The Hermes session that receives the issue is the accountable **Worker** for the final candidate even when it delegates to bots/subagents or falls back to another model.

It must:

- read `AGENTS.md`, the issue and the active release spec when one is explicitly designated;
- verify assigned baseline/branch/workspace;
- never infer the next-release baseline from a completed prior integration line or old stacked branch;
- keep all helpers inside issue scope;
- ensure only the assigned candidate branch is delivered unless the issue explicitly defines benchmark branches;
- report the actual Delegate/fallback chain;
- never self-accept.

## Delegation rules

Hermes bots/subagents are **Delegates** by default unless the task launch explicitly assigns another role.

- Read-only Delegates may share task context.
- Two simultaneous writers must not share one working tree. Give each writer an explicitly assigned sub-workspace/branch or run them sequentially.
- Delegates do not merge or self-accept.
- A Delegate may propose an alternative, but the Worker selects/assembles the final task candidate before returning it to the Integrator.
- Do not let a Delegate create unrelated sibling repos/workspaces or continue into the next task.

## Model fallback attribution

If a run changes model because of limits/errors, report it explicitly, for example:

`Step 3.7 Flash -> DeepSeek V4 Flash fallback`

A fallback is not automatically a failure. The point is reproducibility and later benchmark/retrospective value.

## Relationship to Codex orchestration

Codex `$delivery-loop` is a Codex-local execution mechanism. Hermes remains a first-class manual Worker route and does not need to use that skill.

The same project review bar still applies: high-risk work may require a separate Reviewer, and final project acceptance remains with the Integrator.

## Finish

Commit/push only the assigned task branch and return the `AGENTS.md` Worker completion report with exact SHA/checks/deviation history and all material Delegates/fallbacks.

Do not edit `docs/EXECUTION_HISTORY.md`; the Integrator writes the neutral reviewed record.
