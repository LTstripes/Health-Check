# Codex adapter

Use [AGENTS.md](../../AGENTS.md) and the assigned issue. A session is one Worker unless explicitly assigned otherwise. Local configuration selects models/effort/workspaces; no model roster or duplicate delivery policy lives here.

## Independent review mechanics

Give a separate Reviewer the pinned base/candidate, relevant contract/comment text, prior findings and check evidence. A network-disabled reviewer needs literal accessible sources, not only URLs. Resolve packet/runtime readiness before starting review inference.

Enforced read-only review requires a separate context/runtime with the intended permissions. A child inheriting writable rights is not proof of isolation. Independent review does not require an orchestration loop or another automatic full suite.

## Explicit orchestration only

Only an explicit request activates [Agent orchestration](../AGENT_ORCHESTRATION.md). A mention, audit or ordinary task/review does not invoke `$delivery-loop`.

## Local helpers

Load only a relevant procedure skill; keep implicit delivery-loop invocation disabled and avoid duplicate active skills. Skills may add mechanics, not weaken policy. Concrete model IDs/effort/local paths stay in local configuration; return the technical [completion report](../../AGENTS.md#completion-reporting).

## Managed Owner-local task checkout

When the task explicitly selects managed lifecycle v1, use the executable
`Invoke-WorkerLifecycle` consumer in the accepted installed helper and follow
[worker checkout workflow](../WORKSPACE_LIFECYCLE.md#worker-checkout-workflow).
The assignment supplies the helper path, client root, new child and unique owner;
retain the current Claim/generation in the existing task checkpoint. Require
CheckActive before work, Pause/Resume explicitly, and Complete after delivery.
This does not hook platform task events or enroll an already-created checkout.
Without configured/accepted support, use only the shared fresh-unmanaged fallback.
