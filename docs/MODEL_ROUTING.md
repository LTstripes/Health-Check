# Model Routing — Health-Check

Integrator guidance for task proposals, capability selection and risk-based review. An already-assigned Worker needs its issue/contract, not this whole document. Roles are defined in [AGENTS.md](../AGENTS.md#roles); ordinary delivery/checks in [Development Process](DEVELOPMENT_PROCESS.md).

## Effort and coordination choice

Choose a model that comfortably handles the bounded contract and the lowest suitable reasoning setting. Higher effort is useful for unresolved architecture, provenance, replay/state transitions or statistics, not automatically for every task. Resolve missing requirements, ownership and runtime readiness before upgrading the model.

One Worker is the default regardless of client. Coordination is separate from model strength: use [orchestration](AGENT_ORCHESTRATION.md) only for an explicitly authorized queue or a concrete delegation/review/remediation benefit. Dependency or parallel work follows [Parallel work](DEVELOPMENT_PROCESS.md#parallel-work); an isolated task requires no compatibility form.

## Roles

Use [project role ownership](../AGENTS.md#roles). This document owns capability/review decisions, not a second set of acceptance permissions.

## Complexity classes

Implementation effort and risk are separate. A small privacy/migration change can still be high risk.

| Class | Typical scope / capability | Review |
| --- | --- | --- |
| <a id="c0--trivial--mechanical"></a>C0 — Trivial / Mechanical | Typo, link, formatting or unambiguous small fixture/test change; reliable fast model | Integrator; separate review optional unless requested/risk appears |
| <a id="c1--routine"></a>C1 — Routine | Isolated UI, established CRUD/parser mapping, bounded docs/tests; reliable coding model | Integrator; separate review for material cross-cutting risk or explicit request |
| <a id="c2--normal"></a>C2 — Normal | Multi-file feature under stable architecture, non-destructive API or established analytics; capable coding model | Integrator plus targeted independent review when multiple layers/risk warrant it |
| <a id="c3--hard--high-risk"></a>C3 — Hard / High risk | Ingestion, migrations, replay/idempotency, auth/network, canonical selection, cross-source analytics; strong coding/reasoning | Strong Integrator review; independent Reviewer normally required; live gates Owner-controlled |
| <a id="c4--critical--architecture"></a>C4 — Critical / Architecture | Destructive/history reinterpretation, privacy/security architecture or canonical-model redesign; strongest appropriate reasoning | Mandatory independent review plus explicit Integrator decision/ADR before implementation or merge as applicable |

## Routing principles

Use current capability and availability, not permanent model names. High reasoning is not a substitute for tests; stronger models do not turn self-review into independent review. For provider/device/API facts use pinned contracts/current official sources; for analytics prefer explainable methods appropriate to coverage/sample size.

## Independent review triggers

A separate Reviewer is required by the risk class above, explicit Owner/Integrator request, or justified execution risk. Required independent review can run alongside CI on the same frozen candidate unless the issue says otherwise. The Reviewer inspects existing exact-candidate evidence and runs focused checks for identified gaps; a second full suite is not required solely because a different role is reviewing.

Risk escalation does not authorize new requirements or scope expansion. If it changes architecture, privacy, canonical data or health semantics, return to the Integrator for a bounded decision. Existing explicit task gates stay in force unless the Integrator explicitly revises that assignment.

## Capability-based selection

Choose fast execution for mechanical work, strong coding for established cross-layer contracts and strong reasoning for unresolved decisions. Concrete model IDs/effort are local execution choices, not required task or completion metadata. Selection never waives required semantic/privacy review.

## Manual and orchestrated clients

Codex, Grok, Hermes and other clients may all be ordinary Workers. A client name or a request for a task series does not activate a queue. Execution-mode rules live only in [Agent orchestration](AGENT_ORCHESTRATION.md).

## Hermes delegation/fallback

The accountable Worker reports material changes to scope, verification or review independence caused by delegation/fallback, not model identities. Client-specific coordination belongs in [the Hermes adapter](agents/hermes.md).

## Escalation triggers

Return to the Integrator for conflicting authority; possible history loss/reinterpretation; identity ambiguity affecting history; access to real Owner data/credentials; changed security exposure/provider contracts; out-of-scope services/dependencies; or newly required architecture/health semantics. Ordinary reversible implementation choices within a resolved contract need no repeated approval.

## Owner task proposal

In plain Russian: task title; intended change/value; implementation complexity and separate risk; a suitable execution client and necessary review/Owner action. Honor an already selected route. A model/effort recommendation may help choose execution, but no model confirmation or attribution intake is needed before starting or accepting work.

Add one short copyable locator prompt, normally 5–8 lines: repo/issue/applicable note, role, target/exact baseline, assigned branch/workspace, outcome and authorized delivery. The issue is the specification; do not duplicate it in the prompt. Resolve missing safety-critical assignments first. Add queue/parallel fields only when that mode is actually authorized.
