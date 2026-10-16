# Hermes — Worker / Delegation Adapter

Use [AGENTS.md](../../AGENTS.md). The receiving Hermes Worker remains accountable for the final candidate when it delegates or changes execution route.

## Delegation mechanics

Helpers are Delegates unless explicitly assigned another role. Read-only helpers may share context; concurrent writers need explicitly assigned isolated sub-workspaces/branches, otherwise run sequentially. The Worker assembles the bounded result before handoff; helpers do not create an implicit second candidate or start another roadmap task.

A helper that contributes implementation is not the independent Reviewer of that work. Apply the issue's review requirement independently of the delegation mechanism.

## Completion

Report material effects of delegation/fallback on scope, verification or review independence through the shared [completion report](../../AGENTS.md#completion-reporting).

## Client distinction

Hermes does not need the Codex-local `$delivery-loop` skill. Only explicit coordination/queue authorization loads [Agent orchestration](../AGENT_ORCHESTRATION.md). Ordinary Hermes execution follows [Development Process](../DEVELOPMENT_PROCESS.md).

## Managed Owner-local task checkout

When the task explicitly selects managed lifecycle v1, use the executable
`Invoke-WorkerLifecycle` consumer in the accepted installed helper and follow
[worker checkout workflow](../WORKSPACE_LIFECYCLE.md#worker-checkout-workflow).
The assignment supplies the helper path, client root, new child and unique owner;
retain the current Claim/generation in the existing task checkpoint. Require
CheckActive before work, Pause/Resume explicitly, and Complete after delivery.
This does not hook platform task events or enroll an already-created checkout.
Without configured/accepted support, use only the shared fresh-unmanaged fallback.
