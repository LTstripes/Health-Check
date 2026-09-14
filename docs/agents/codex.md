# Codex adapter

Universal rules in `/AGENTS.md` are authoritative. Local Codex configuration supplies local models, agents, skills and runtime mechanics; repository policy supplies project constraints and acceptance.

See [`docs/AGENT_ORCHESTRATION.md`](../AGENT_ORCHESTRATION.md).

## Assigned root

`D:\Codex\Garmin`

Each task uses its own workspace:

`D:\Codex\Garmin\workspaces\<issue>-<slug>`

Do not use `D:\Garmin`, `D:\Garmin-UAT`, another client's root, or another task workspace.

## Mode A — manual Worker

Use for an ordinary single-task Codex launch, including `Codex без оркестрации`, unless orchestration is explicitly requested.

### Start

- Read `AGENTS.md`, the active GitHub issue and the active release spec when one is explicitly designated.
- Fetch the repository into the assigned task workspace.
- Verify the exact baseline/integration SHA and the issue/Integrator [launch compatibility decision](../AGENT_ORCHESTRATION.md#launch-compatibility-assessment) before editing; read applicable Integrator comments. If shared ownership is unresolved, return that conflict before writes.
- Check out/create only the assigned task branch.
- Never infer that a completed prior release integration branch is the new baseline.

### Work

- Implement only the issue.
- Use synthetic fixtures; never request/copy Owner private runtime data into the workspace.
- Do not begin later roadmap work as cleanup.
- Commit/push only the task branch.
- Do not merge or alter `main`/integration branches.
- Do not self-accept.

### Finish

Run issue-required checks and return the Worker completion report specified by `AGENTS.md`, including exact baseline, workspace, branch, candidate SHA, changed areas, checks, deviations/limitations and final clean-tree status.

## Mode B — `$delivery-loop` Execution Orchestrator

When the launch invokes `$delivery-loop` or explicitly requests orchestration, the root session acts as **Execution Orchestrator**.

The root must:

- read project policy/issue/spec before applying local orchestration mechanics;
- validate exact baseline, branch/workspace, compatibility/ownership, queue mode, completion mode and review requirement;
- delegate implementation to the locally configured Worker;
- not duplicate delegated write work after delegation;
- wait for the Worker and inspect the actual candidate/diff/check evidence;
- invoke the locally configured separate read-only Reviewer when project routing requires it, when Owner/Integrator explicitly requests it, or when justified execution risk raises the review requirement;
- STOP for Integrator re-scope if risk implies architecture, privacy, canonical-data or health-semantics expansion;
- honor review-and-stop; otherwise use the default one remediation cycle and the project conditions for a second, never more than two;
- return internal verdicts `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED`, or `BLOCKED_FOR_INTEGRATION`;
- never equate `INTERNAL_ACCEPT` with project `ACCEPT`;
- never acquire implicit merge authority.

A child reviewer that inherits writable rights from the parent does not prove enforced independent read-only review; use the Owner's local mechanism that actually provides the required isolation.

## Queue behavior

Only an explicitly authorized queue may advance automatically.

For a sequential independent queue (explicit parallel assignments instead follow the project compatibility contract):

- each task has its own branch/workspace/baseline;
- the previous task reaches `INTERNAL_ACCEPT` before the next eligible item starts;
- previous candidate history is not an implicit baseline for the next task.

If a task requires prior integration and no explicit dependency strategy was supplied, mark it `BLOCKED_FOR_INTEGRATION`. That blocks the affected dependency chain; unrelated explicitly listed eligible tasks may continue only when the launch explicitly enables integration-block continuation.

Return both per-task evidence and one final queue summary.

## Private-data and workspace boundary

Orchestrated mode does not weaken existing restrictions:

- never inspect/use `D:\Garmin\Garmin-Main` or `D:\Garmin\Garmin-UAT` as development workspaces;
- never access Owner private runtime/health payloads;
- one write candidate owns one physical workspace;
- do not reuse another active task workspace;
- synthetic fixtures remain the normal test basis.

## Skills

Generic orchestration belongs to local `$delivery-loop`. Do not create a Health-specific skill merely for symmetry. A Health-specific skill is justified only for a genuinely reusable project procedure that does not duplicate `AGENTS.md`, architecture, release specs or issue contracts.

Local skill paths, current model IDs and reasoning levels are not tracked in this repository.

## History

Do not edit `docs/EXECUTION_HISTORY.md` as a normal Worker or Execution Orchestrator. The Integrator records the reviewed result.
