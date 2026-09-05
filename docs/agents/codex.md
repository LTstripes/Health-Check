# Codex — Worker Adapter

Universal rules in `/AGENTS.md` are authoritative.

## Assigned root

`D:\Codex\Garmin`

Each task uses its own workspace:

`D:\Codex\Garmin\workspaces\<issue>-<slug>`

Do not use `D:\Garmin`, `D:\Garmin-UAT`, another client's root, or another task workspace.

## Start

- Read `AGENTS.md`, the active GitHub issue and the active release spec when one is explicitly designated.
- Fetch the repository into the assigned task workspace.
- Verify the exact baseline/integration SHA from the launch prompt before editing.
- Check out/create only the assigned task branch.
- Never infer that a completed prior release integration branch is the new baseline; use the exact current baseline supplied by the Integrator.

## Work

- Implement only the issue.
- Use synthetic fixtures; never request/copy owner private runtime data into the workspace.
- Do not begin later roadmap work as cleanup.
- Commit/push only the task branch.
- Do not merge or alter `main`/integration branches.

## Finish

Run issue-required checks and return the worker completion report specified by `AGENTS.md`, including exact baseline, workspace, branch, candidate SHA, changed areas, checks, deviations/limitations and final clean-tree status.

Do not edit `docs/EXECUTION_HISTORY.md`; the Integrator records the reviewed result.
