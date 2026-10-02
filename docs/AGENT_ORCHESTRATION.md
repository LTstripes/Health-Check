# Agent orchestration — Health-Check

Optional execution-local coordination for explicitly authorized queues/delegation. Reading this file, naming a client or asking for an audit does not activate it. Ordinary single-Worker work uses [Development Process](DEVELOPMENT_PROCESS.md); roles/acceptance authority are defined in [AGENTS.md](../AGENTS.md#roles).

## Roles

Use the canonical roles; do not require a Builder/Breaker/Auditor pipeline. An Orchestrator coordinates delegated work rather than becoming a second writer. Independent review requires a separate Reviewer, not root/Worker self-review.

## Launch compatibility assessment

For a genuinely isolated single task, the issue assignment is sufficient: no compatibility table or N/A sections. For dependencies/shared contracts or proposed parallel work, record the compact decision required by [Parallel work](DEVELOPMENT_PROCESS.md#parallel-work): dependency readiness, pinned interface/base, shared artifact owner, boundaries and order. Add applicable comment IDs when they establish that decision.

Parallel execution requires explicit Owner opt-in and compatible scopes, not merely separate worktrees. Unresolved shared schema/API/module/export/migration/version ownership blocks the affected launch. Do not inspect other workspaces to discover ownership; use assignment records. Do not silently change an existing assignment.

## Early contract checkpoint and final gates

[Verification by change](DEVELOPMENT_PROCESS.md#verification-by-change) owns risk-proportional early checks; [CI evidence](DEVELOPMENT_PROCESS.md#13-ci-evidence-and-complete-suite-gates) owns final-gate identity/completeness. An orchestrated run adds no automatic extra full suite or mandatory early review. Required final checks/review may overlap on one frozen candidate when the issue permits.

## Mode A — manual / brokered execution

One Worker is the default for `дай задачу для <model/client>`, including Codex, and for `Codex без оркестрации`. A request for a task series asks the Integrator to propose compatible order; it does not authorize automatic execution. Follow the ordinary process without loading queue mechanics.

## Mode B — Codex `$delivery-loop`

An explicit orchestration launch identifies repo, authorized task list, per-task exact baseline/target, branch/workspace, queue/completion mode and required review. State the actual coordination benefit.

1. Root coordinates; a Worker owns each implementation candidate.
2. Worker returns exact candidate/check evidence; root inspects the actual result.
3. Use a separate Reviewer when [risk policy](MODEL_ROUTING.md#independent-review-triggers) requires it; a network-disabled reviewer receives accessible literal source/evidence, not just URLs.
4. `review-and-stop` returns findings without automatic fixes. Otherwise use one remediation cycle; a second requires explicit authorization or a demonstrably mechanical bounded fix. Never exceed two.
5. Internal states are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED` and `BLOCKED_FOR_INTEGRATION`. `INTERNAL_ACCEPT` is execution evidence, never project ACCEPT or merge permission.

## Queue policy

### Single

One authorized task, its checks/review and report; then stop.

### Independent queue

Only explicitly listed eligible tasks may advance. Each owns its assigned branch, physical write workspace and pinned baseline; the prior task's candidate is not an implicit base. A sequential queue advances after the previous task reaches INTERNAL_ACCEPT; explicitly authorized parallel work keeps separate per-task gates.

### Dependency / integration block

A task requiring an unintegrated dependency and lacking an explicit safe baseline/fixture strategy is BLOCKED_FOR_INTEGRATION. This blocks that dependency chain. Unrelated listed eligible items may continue only if the launch expressly enables integration-block continuation; otherwise stop. Do not invent stacked history, merge canonical branches or pick replacement backlog work.

## Independent review triggers

Use [MODEL_ROUTING.md](MODEL_ROUTING.md#independent-review-triggers); queue activation neither adds an automatic Reviewer to every task nor waives a required one.

## Reporting

### Per-task report

Use [Completion reporting](../AGENTS.md#completion-reporting), adding only material delegation/remediation facts and evidence references. A compact phase ledger is useful for actual coordinated work; unknown timings/costs remain unknown, not a mandatory form.

### Final queue report

List each authorized task's final internal state, candidate SHA when present, review path and unresolved Integrator action. This is not batch project acceptance.

## Local skills/config

Client skills, model routing and subagent definitions are local mechanics; do not hardcode machine paths/model IDs here. A new project skill is justified by a reusable distinct procedure, not symmetry or a copy of policy. Keep implicit delivery-loop activation disabled.

## Invariants automation cannot weaken

All [project boundaries](../AGENTS.md) still apply, including privacy, workspace isolation, health semantics, honest evidence and Integrator-controlled acceptance.
