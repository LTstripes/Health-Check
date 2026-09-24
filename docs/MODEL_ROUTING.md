# Model Routing — Health-Check

This file defines task complexity, routing and escalation. Exact provider/model availability changes over time; the Integrator chooses a concrete execution route per task.

Use the [Owner task proposal](#owner-task-proposal) format below. Model/effort recommendations are resolved from current availability per launch; repository policy specifies the capability and review bar.

Execution-mode semantics are defined in [`AGENT_ORCHESTRATION.md`](AGENT_ORCHESTRATION.md).

## Effort and coordination choice

Choose execution mode separately from model strength. One Worker can handle a complex bounded task with required independent review; an orchestrator is justified by explicit queue/review/remediation coordination needs, not by the client name. Record the [launch compatibility assessment](AGENT_ORCHESTRATION.md#launch-compatibility-assessment) before selecting parallel work.

Use the lowest reasoning setting that comfortably handles the bounded contract. Reserve a higher setting for identified unresolved architecture, provenance, replay/state-transition or statistical reasoning; explain that reason in routing. Do not raise every Worker and Reviewer to the maximum because a previous run was slow or blocked. First resolve missing requirements, ownership and runtime readiness. An early strong contract review can be more useful than upgrading a long implementation pass with an incomplete packet.

Concrete model IDs and effort assignments belong to the launch/local configuration. Attribute actual root/Worker/Reviewer settings from available runtime evidence; unknown settings or token costs remain unknown. Reassess after a specific failure, not from wall time alone.

## Roles

Role ownership and the prohibition on self-acceptance are defined in [`AGENTS.md`](../AGENTS.md#roles). This document owns capability, risk/review and escalation decisions; it does not redefine the roles.

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

Typical routing: a capable coding Worker for a bounded multi-file contract. Orchestration is a separate explicit opt-in decision, not a model tier.

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

## Capability-based selection

Select reliable fast execution for mechanical/bounded work, strong coding and reasoning for cross-layer contracts, and stronger reasoning for unresolved architecture or difficult review. A newer model does not remove project checks or independent review. Concrete provider/model IDs and effort belong to current local configuration or the task launch, not a permanent repository roster. Apply shared scope/evidence rules across models; evaluate model-specific prompting advice on the actual workload rather than assuming identical behavior.

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

## Owner task proposal

Use this format when proposing a task to the Owner, in plain Russian:

1. **Название.**
2. **Что изменится и зачем:** one or two concrete sentences.
3. **Сложность:** небольшая / средняя / сложная, with a short reason. Complexity describes implementation effort; state **Риск** separately using this project's risk/review policy.
4. **Исполнитель:** a concrete currently available model and supported reasoning effort, selected at launch for the required capability. Label this a recommendation; report the actually used model only from runtime evidence.
5. **Независимое ревью / действия владельца:** only the required review or private/manual gate, with its reason.
6. One copyable start prompt, normally 5–8 lines and about 100 words or less: repo/issue and applicable note, Worker role, target and exact baseline, assigned branch/workspace, intended result and authorized delivery. Requirements and acceptance criteria remain in the authoritative issue/contract.

Do not invent an available model, baseline, workspace or permission to make the card look complete. Resolve a missing safety-critical assignment or contract in the authoritative task before launch. A short prompt does not waive any required gate. An explicitly orchestrated launch additionally follows `AGENT_ORCHESTRATION.md`; this format does not activate it.
