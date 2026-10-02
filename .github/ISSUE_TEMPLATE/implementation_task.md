---
name: Implementation task
about: Bounded Health-Check implementation/review task
---

# <Task ID> — <Title>

## Objective and scope

<Outcome, relevant sources/Integrator notes, in-scope boundaries and meaningful exclusions.>

## Assignment

- **Implementation complexity / risk:** <brief reason; independent review or Owner gate only when required>
- **Execution:** <one Worker by default; selected route, not actual Model evidence>
- **Target / exact baseline:**
- **Task branch / assigned workspace:**

## Acceptance criteria

- [ ] <Observable result and relevant failure cases.>

## Verification

<Focused checks and any specifically required final CI/review/UAT gate. Use DEVELOPMENT_PROCESS.md#verification-by-change; do not automatically add full local suites or a separate early review.>

## Boundaries and delivery

Synthetic fixtures only; private Owner data/runtime/provider calls stay outside development. Deliver the authorized task branch and AGENTS.md completion report; no implicit PR/merge/release authority. Keep established explicit gates unless the Integrator revises them.

<!-- Add only applicable details, not empty/N/A sections:
Dependencies/shared contracts: pinned readiness, single artifact owner and safe order.
Parallel execution: explicit Owner authorization and compatible task boundaries.
High-risk unresolved contract: source requirement -> production boundary -> negative acceptance check.
Orchestrated queue: explicitly listed tasks, per-task base/workspace, completion/review mode,
and whether unrelated eligible tasks may continue after an integration block.
A genuinely isolated task needs no launch-compatibility form.
-->
