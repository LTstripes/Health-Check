# Model Routing — Health-Check

This file defines task complexity, routing and escalation. Exact provider/model availability changes over time; the Integrator chooses a concrete execution route per task.

Every task proposal to the Owner should begin with a short routing header, for example:

```text
Complexity: C2 / Normal
Recommended executor: Luna High
Alternative: Grok High
Independent reviewer: not required
```

For high-risk work, include the reviewer/escalation requirement.

Execution-mode semantics are defined in [`AGENT_ORCHESTRATION.md`](AGENT_ORCHESTRATION.md).

## Roles

- **Integrator** — task decomposition, routing, final project acceptance and GitHub integration.
- **Execution Orchestrator** — optional execution-local coordinator for planning/delegation/internal review/remediation/explicit queue coordination. Does not own project acceptance.
- **Worker** — owns one implementation candidate. Does not self-accept.
- **Delegate** — bounded helper below an Orchestrator/Worker. Does not self-accept.
- **Reviewer** — independently validates a candidate without silently modifying it.

Root/Orchestrator self-review is not independent review.

## Complexity classes

### C0 — Trivial / Mechanical

Examples:

- typo/docs/link corrections;
- bounded formatting;
- mechanical fixture/update with exact contract;
- small test-only change with no semantic ambiguity.

Typical routing: any reliable weak/fast model.

Review: Integrator review is normally enough. Independent review is optional unless explicitly requested or justified risk appears.

### C1 — Routine

Examples:

- small isolated UI behavior;
- simple CRUD under an established schema;
- bounded parser mapping with fixtures;
- straightforward tests/documentation around existing behavior.

Typical routing: a reliable fast coding model.

Review: Integrator; independent review only if the diff becomes materially cross-cutting, is explicitly requested, or execution reveals justified risk.

### C2 — Normal

Examples:

- multi-file feature under stable architecture;
- new dashboard section;
- provider-normalization work with an established contract;
- non-destructive backend/API behavior;
- moderate analytics implementation with known formulas/tests.

Typical routing: Luna High, Grok High, another strong coding Worker, or a Codex orchestrated route with a strong root and scoped Worker.

Review: Integrator plus targeted independent review when behavior spans several layers or risk warrants it.

### C3 — Hard / High risk

Examples:

- new ingestion pipeline;
- SQLite schema/migrations with existing data;
- idempotency/reprocessing;
- network/security boundary;
- OAuth/provider auth;
- canonical-selection mechanics;
- complex cross-source analytics;
- significant refactor touching several architecture layers.

Typical routing: a strong coding model / strong orchestrated route with high reasoning.

Review: strong Integrator review; independent Reviewer normally required. Live/private probes remain Owner-controlled.

### C4 — Critical / Architecture

Examples:

- changing architecture invariants;
- reinterpretation/migration of stored health history;
- destructive operations;
- privacy/security architecture;
- cross-release canonical data-model redesign;
- ambiguous external API/licensing decision that affects long-term implementation.

Typical routing: strongest appropriate available reasoning model(s), with explicit architecture decision before implementation when needed.

Review: mandatory independent review plus explicit Integrator decision/ADR before implementation or merge.

## Routing principles

1. Use the cheapest/fastest model that comfortably fits the task; do not burn premium reasoning on mechanical work.
2. Escalate when scope/risk grows during implementation.
3. High reasoning is not a substitute for tests or source evidence.
4. A completion report is context, not proof; Integrator inspects actual Git state/evidence.
5. For provider/API/device facts, current source/official documentation beats model memory.
6. For health analytics, complex statistics are not automatically better. Prefer explainable methods that fit sample size/coverage.
7. A strong Execution Orchestrator may use a cheaper scoped Worker; role separation matters more than permanent model names.
8. `INTERNAL_ACCEPT` from local orchestration is execution evidence only, not project `ACCEPT`.

## Independent review triggers

Use a separate Reviewer when any of these applies:

1. this complexity/risk policy requires one;
2. Owner/Integrator explicitly requests one;
3. justified execution risk appears that raises the review bar under project policy.

The third case does not authorize requirement invention or scope expansion. If the risk implies architecture, privacy, canonical data or health-semantics changes, STOP and ask the Integrator.

## Model-family examples — non-normative

Current Owner environments may include models such as:

- fast DeepSeek/GLM/Step-class models for bounded C0/C1 work;
- Luna High for many C2 implementation tasks;
- Grok High/xHigh as a strong alternative implementation/review route;
- Sol/Astra-class strong reasoning for orchestration, difficult review/arbitration or higher-risk work when available.

These are examples only. Local Codex configuration controls internal Codex model assignment; repository policy controls the required capability/review bar.

## Manual and orchestrated clients

Manual Grok, Hermes, manual Codex and other clients may act as Workers under the same project roles.

Codex `$delivery-loop` is an explicit orchestration route: root acts as Execution Orchestrator, implementation is delegated locally, and final project acceptance remains with the Integrator.

## Hermes delegation/fallback

If Hermes delegates or automatically falls back:

- the supervising Worker remains responsible for issue scope and final branch;
- helpers are Delegates unless explicitly assigned another role;
- simultaneous writers require isolated branches/workspaces;
- completion report lists the actual model/delegate/fallback chain;
- fallback does not invalidate the result, but attribution must be preserved.

## Independent benchmark mode

Only when explicitly requested:

- identical pinned baseline and issue contract;
- separate branches/workspaces;
- candidates do not inspect one another before completion;
- compare actual code/tests/evidence;
- record timing/cost when known and useful;
- Integrator chooses or synthesizes the accepted result.

## Escalation triggers

Stop and ask the Integrator instead of guessing when:

- issue/spec/architecture conflict;
- a migration may reinterpret or lose existing data;
- source/device/algorithm identity is ambiguous in a way that affects history;
- real Owner health data or credentials would be needed in a Worker workspace;
- security/network exposure changes;
- provider behavior differs from pinned/official contract;
- unexpected failures outside task scope suggest a moving integration contract;
- implementation would add an out-of-scope dependency/service or begin a later roadmap release;
- a bounded task now requires architecture/health-semantics expansion.
