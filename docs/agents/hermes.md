# Hermes — Worker / Delegation Adapter

Universal rules in `/AGENTS.md` are authoritative.

## Assigned root

`D:\Hermes Project\hermes-garmin`

Each task uses its own workspace:

`D:\Hermes Project\hermes-garmin\workspaces\<issue>-<slug>`

Do not use `D:\Garmin`, `D:\Garmin-UAT`, Codex/Grok roots, or another task workspace.

## Primary Hermes session

The Hermes session that receives the issue is the accountable primary worker even when it delegates to bots/subagents or falls back to another model.

It must:

- read `AGENTS.md`, the issue and active release spec;
- verify assigned baseline/branch/workspace;
- keep all delegates inside issue scope;
- ensure only the assigned candidate branch is delivered unless the issue explicitly defines benchmark branches;
- report the actual delegate/fallback chain.

## Delegation rules

- Read-only delegates may share task context.
- Two simultaneous writers must not share one working tree. Give each writer an explicitly assigned sub-workspace/branch or run them sequentially.
- Delegates do not merge or self-accept.
- A delegate may propose an alternative, but the primary session selects/assembles the final task candidate before returning it to the Integrator.
- Do not let a bot create unrelated sibling repos/workspaces or continue into the next task.

## Model fallback attribution

If a run changes model because of limits/errors, report it explicitly, for example:

`Step 3.7 Flash -> DeepSeek V4 Flash fallback`

A fallback is not automatically a failure. The point is reproducibility and later benchmark/retrospective value.

## Finish

Commit/push only the assigned task branch and return the `AGENTS.md` completion report with exact SHA/checks/deviation history and all material delegates/fallbacks.

Do not edit `docs/EXECUTION_HISTORY.md`; the Integrator writes the neutral reviewed record.
