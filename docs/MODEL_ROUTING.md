# Model Routing — Health-Check

This file defines task complexity, routing and escalation. Exact provider/model availability changes over time; the Integrator chooses a concrete executor per task.

Every task proposal to the owner should begin with a short routing header:

```text
Complexity: C2 / Normal
Recommended executor: Luna High
Alternative: Grok High
Independent reviewer: not required
```

For high-risk work, include the reviewer/escalation requirement.

## Roles

- **Integrator** — task decomposition, routing, final technical acceptance and GitHub integration.
- **Primary worker** — owns one implementation candidate.
- **Delegate** — bounded helper used by a primary worker (common in Hermes); does not self-accept.
- **Independent reviewer** — validates a candidate without silently modifying it.

## Complexity classes

### C0 — Trivial / Mechanical

Examples:

- typo/docs/link corrections;
- bounded formatting;
- mechanical fixture/update with exact contract;
- small test-only change with no semantic ambiguity.

Typical routing: any reliable weak/fast model. Current examples may include DeepSeek/GLM/Step flash-class models.

Review: Integrator self-review is normally enough.

### C1 — Routine

Examples:

- small isolated UI behavior;
- simple CRUD under an established schema;
- bounded parser mapping with fixtures;
- straightforward tests/documentation around existing behavior.

Typical routing: DeepSeek V4 Flash, GLM 5.x, Step 3.x Flash, or another strong fast model.

Review: Integrator; independent reviewer only if the diff becomes cross-cutting.

### C2 — Normal

Examples:

- multi-file feature under stable architecture;
- new dashboard section;
- provider-normalization work with an established contract;
- non-destructive backend/API behavior;
- moderate analytics implementation with known formulas/tests.

Typical routing: Luna High / strong Codex model, Grok High, or equivalent.

Review: Integrator plus targeted independent review when behavior spans several layers.

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

Typical routing: Luna Max / Sol High-class reasoning, Grok xHigh/very-high reasoning, or equivalent strong coding model.

Review: strong Integrator review; independent reviewer normally required. Live/private probes remain owner-controlled.

### C4 — Critical / Architecture

Examples:

- changing architecture invariants;
- reinterpretation/migration of stored health history;
- destructive operations;
- privacy/security architecture;
- cross-release canonical data-model redesign;
- ambiguous external API/licensing decision that affects long-term implementation.

Typical routing: strongest available model such as Sol Ultra / Luna Max at maximum reasoning, followed by an independent strong reviewer from a different model family when practical.

Review: mandatory independent review plus explicit Integrator decision/ADR before implementation or merge.

## Routing principles

1. Use the cheapest/fastest model that comfortably fits the task; do not burn premium reasoning on mechanical work.
2. Escalate when scope/risk grows during implementation.
3. High reasoning is not a substitute for tests or source evidence.
4. A model completion report is context, not proof; Integrator inspects the actual Git state.
5. For provider/API/device facts, current source/official documentation beats model memory.
6. For health analytics, complex statistics are not automatically better. Prefer explainable methods that fit available sample size/coverage.

## Model-family examples — non-normative

Current owner environments may include models such as:

- DeepSeek V4 Flash — useful for C0/C1 and bounded code archaeology;
- Step 3.7 Flash / GLM 5.3 — useful fast workers for bounded C1/C2 tasks when stable;
- Luna High — default strong coding worker for many C2 tasks;
- Luna Max / Sol High — C3 cross-cutting work;
- Grok High/xHigh — strong alternative for C2/C3, especially independent implementation/review;
- Sol Ultra — reserved for C4, difficult arbitration or unusually broad/high-risk tasks.

This list is guidance, not a permanent ranking. The Integrator states the concrete recommendation at the beginning of each task.

## Hermes delegation/fallback

If Hermes delegates or automatically falls back:

- the supervising worker remains responsible for issue scope and final branch;
- delegates inherit `AGENTS.md` and may not broaden scope;
- simultaneous writers require isolated branches/workspaces;
- completion report lists the actual model/delegate/fallback chain;
- a fallback does not invalidate the result, but attribution must be preserved for retrospectives/benchmarks.

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
- real owner health data or credentials would be needed in a worker workspace;
- security/network exposure changes;
- provider behavior differs from pinned/official contract;
- unexpected failures outside task scope suggest a moving integration contract;
- implementation would add an out-of-scope dependency/service or begin a later roadmap release.
