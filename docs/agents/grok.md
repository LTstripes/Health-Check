# Grok Build — Worker Adapter

Grok Build is an ordinary Worker under [AGENTS.md](../../AGENTS.md), not a mandatory multi-bot pipeline. Use the assigned issue and relevant [development/check procedure](../DEVELOPMENT_PROCESS.md#verification-by-change).

## Build-specific use

Exploration and browser/UI inspection are useful inside the assigned scope; they do not authorize redesign or access to private Owner data. Use synthetic browser fixtures and distinguish observed browser checks from code inspection.

Return the shared [completion report](../../AGENTS.md#completion-reporting). Only explicit authorization changes delivery permissions or enables coordinated bots.

## Managed Owner-local task checkout

When the task explicitly selects managed lifecycle v1, use the executable
`Invoke-WorkerLifecycle` consumer in the accepted installed helper and follow
[worker checkout workflow](../WORKSPACE_LIFECYCLE.md#worker-checkout-workflow).
The assignment supplies the helper path, client root, new child and unique owner;
retain the current Claim/generation in the existing task checkpoint. Require
CheckActive before work, Pause/Resume explicitly, and Complete after delivery.
This does not hook platform task events or enroll an already-created checkout.
Without configured/accepted support, use only the shared fresh-unmanaged fallback.
