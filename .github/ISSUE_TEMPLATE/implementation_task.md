---
name: Implementation task
about: Bounded Health-Check implementation/review task
---

# <Release/Task ID> — <Title>

## Routing

- **Complexity:** C0 / C1 / C2 / C3 / C4, with reason
- **Risk:** separate from complexity; required review/gates and reason
- **Recommended executor:** concrete currently available model and supported effort, selected at launch (not actual runtime attribution)
- **Alternative:**
- **Independent reviewer required:** yes / no; early contract / final candidate, with reason
- **Execution mode and reason:** one Worker (default) / explicitly orchestrated
- **Completion mode if orchestrated:** review-and-stop / remediate (default one cycle, at most two under project policy)

## Integration context

- **Target integration branch:**
- **Exact baseline SHA:**
- **Dependencies:** none / issue(s)
- **Assigned task branch:** `task/<issue>-<slug>`
- **Assigned workspace:**

## Launch compatibility

Use `docs/AGENT_ORCHESTRATION.md#launch-compatibility-assessment`. A short no-overlap statement is sufficient for one isolated task; expand for a task set.

- **Applicable Integrator comments:** IDs/URLs and checked-at time
- **Shared artifacts/contracts:** existing or new modules, exports, DTO fields, migrations/constraints, version constants; none if isolated
- **Single owner and boundary for each shared artifact:**
- **Execution order:** single / sequential / explicitly authorized parallel, with reason
- **Dependency readiness:** accepted baseline / pinned stable fixture and explicit integration strategy / blocked
- **Parallel authorization, if applicable:** Owner instruction and compatible task IDs
- **Integration-block continuation, if a queue:** disabled by default / explicitly enabled for listed unrelated eligible tasks

## Objective

<One concise outcome.>

## Required reading

- `AGENTS.md`
- active release spec only when explicitly designated and relevant; otherwise not applicable
- relevant architecture/ADR sections

## In scope

- 

## Explicitly out of scope

- 

## Acceptance criteria

- [ ] 

## Early contract checkpoint

For schema/replay/eligibility/statistics/cross-layer changes: map each relevant source requirement to its input/API boundary and an adversarial acceptance test before broad implementation. Exercise production DTOs/entry points where practical. For routine docs/mechanical work, mark not applicable with a reason.

## Verification required

- [ ] targeted tests/checks (exact commands and expected outcomes)
- **Final harness / CI / review schedule:** required commands/gates and whether frozen-candidate review may overlap; not applicable where justified by scope
- [ ] final diff/scope/privacy review
- [ ] exact HEAD/remote/clean-tree read-back

## Privacy / live-data boundary

Synthetic fixtures only unless an explicit owner-only live probe is listed here. No real health DB/screenshots/tokens/documents in worker workspace or Git.

## Completion report

Return the `AGENTS.md` worker completion report: task, actual client/model/delegates, baseline, integration target, workspace, branch, final SHA, changed areas, exact checks, deviations, blockers/limitations and confirmation that canonical/unrelated workspaces were untouched.
