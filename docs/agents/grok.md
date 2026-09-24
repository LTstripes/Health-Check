# Grok Build — Worker Adapter

Universal rules in `/AGENTS.md` are authoritative.

## Assigned root

Use only the physical task workspace explicitly assigned in the launch/Owner-local configuration under the location-role protections in `docs/DEVELOPMENT_PROCESS.md`. Owner canonical, Stable/private-runtime and preview/UAT locations, another client's root and other active task workspaces are excluded. Missing or conflicting assignments must be resolved before writes.

## Start

- Read `AGENTS.md`, the active GitHub issue and the active release spec when one is explicitly designated.
- Verify the exact assigned baseline/integration SHA before editing.
- Work only on the assigned task branch.
- Do not treat a completed prior release integration branch or an old stacked task branch as the next release baseline unless the Integrator explicitly assigns it.

## Work

- Keep the implementation bounded to the issue; do not turn Build exploration into unrequested redesign.
- Browser/UI inspection is useful when explicitly in scope, but private owner health data remains outside worker workspaces.
- Use synthetic/local test data unless an owner-only live probe is explicitly separated from development.
- Commit/push only the task branch; do not merge, force-push or mutate canonical/integration branches.

## Finish

Return the completion report from `AGENTS.md`: runtime-reported model/reasoning where available, baseline, workspace, branch, final SHA, changed areas, exact checks, deviations, surprises/limitations and clean working-tree state.

Do not edit `docs/EXECUTION_HISTORY.md`; the Integrator records the reviewed result.
