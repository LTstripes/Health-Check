# Hermes — Worker / Delegation Adapter

Use [AGENTS.md](../../AGENTS.md). The receiving Hermes Worker remains accountable for the final candidate when it delegates or changes model.

## Delegation mechanics

Helpers are Delegates unless explicitly assigned another role. Read-only helpers may share context; concurrent writers need explicitly assigned isolated sub-workspaces/branches, otherwise run sequentially. The Worker assembles the bounded result before handoff; helpers do not create an implicit second candidate or start another roadmap task.

A helper that contributes implementation is not the independent Reviewer of that work. Apply the issue's review requirement independently of the delegation mechanism.

## Fallback evidence

Report material actual delegate/fallback use in surrounding completion context, preserving unknown identity when necessary. A fallback is not automatically a failure. Use the shared two-field [Model evidence](../../AGENTS.md#completion-reporting), not a mandatory expanded telemetry form.

## Client distinction

Hermes does not need the Codex-local `$delivery-loop` skill. Only explicit coordination/queue authorization loads [Agent orchestration](../AGENT_ORCHESTRATION.md). Ordinary Hermes execution follows [Development Process](../DEVELOPMENT_PROCESS.md).
