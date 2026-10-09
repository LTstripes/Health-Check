# AGENTS.md — Health-Check

Essential boundaries for every agent. Read this and the active issue/applicable Integrator notes once; reuse unchanged context. Procedures are loaded by need, not as a repository-wide reading tour.

## Read by task type

- Docs/process: affected documents and relevant policy sections only.
- Implementation/review: the governing contract, affected source/tests and [verification](docs/DEVELOPMENT_PROCESS.md#verification-by-change).
- Data/health semantics, migration, restore, privacy or runtime boundaries: relevant architecture/ADRs and required review/UAT gates before changing the boundary.
- Routing is Integrator work: [MODEL_ROUTING.md](docs/MODEL_ROUTING.md). Load only your relevant `docs/agents/` adapter; [orchestration](docs/AGENT_ORCHESTRATION.md) is opt-in, not ordinary Worker setup.

## Sources of truth

Resolve conflicts in this order; this is precedence, not a mandatory reading list:
1. `docs/PRODUCT_VISION.md` — purpose and product boundaries.
2. `docs/ARCHITECTURE.md` and accepted ADRs — durable technical contracts.
3. The active release spec explicitly designated by its tracker/Integrator.
4. The active issue and applicable Integrator notes — task scope and acceptance.
5. `docs/DEVELOPMENT_PROCESS.md`, then `docs/MODEL_ROUTING.md`, then `docs/AGENT_ORCHESTRATION.md` — their respective procedures.
6. `docs/DECISIONS_AND_OPEN_QUESTIONS.md`, then backlog/history — context unless promoted into the governing contract.

Without a designated new release spec, use architecture + roadmap + the active issue/notes. A completed release spec is historical, not automatically current. An issue may narrow a higher-priority contract, not silently override it; return conflicts to the Integrator.

## Roles

- **Owner** chooses product direction and performs private/live UAT when needed.
- **Integrator** owns task/routing decisions, GitHub acceptance, integration and durable records.
- **Worker** is the accountable implementation writer for one candidate; never self-accepts.
- **Reviewer** independently validates a candidate without modifying it; self-review is not independent review.
- **Execution Orchestrator** coordinates only explicitly authorized work; after delegation it is not a second implementation writer. Internal verdicts do not grant project acceptance or merge authority.
- **Delegate** is a bounded helper, not an independent acceptance authority.

## Task prompt authority

The issue/accepted contract is the specification; a short launch prompt locates it and assigns execution. Within that scope, perform reversible investigation, edits, synthetic checks and permitted delivery without repeated approval. Resolve missing safety-critical scope/branch/workspace/baseline information before writes. Existing explicit assignments and gates are not waived retroactively by a new general default.

## Git ownership

`main` is the only canonical accepted history/release source. Integration branches are staging, not another source of truth. Workers never write to main and commit/push only their assigned task branch; they do not create PRs by default. Merge, force-push, branch/tag deletion, PR retargeting or repository settings require explicit delegation; Integrator acceptance remains separate.

<a id="stale-base-and-parallel-work-policy"></a>
Stay on the assigned pinned baseline; the Integrator decides refresh/retest at integration. Never rebase/reset another agent's branch or workspace. Release-lineage details belong to [Branch strategy](docs/DEVELOPMENT_PROCESS.md#2-branch-strategy).

## Physical workspace isolation

One active write/verification task owns one physical working tree. Use only the assigned task directory; do not inspect/create/move/rename/delete sibling workspaces without an explicit filesystem assignment. Owner canonical, Stable/private-runtime and preview/UAT locations are not development workspaces, regardless of paths. Current Owner-machine roles and Windows roots are maintained in [Owner machine layout](docs/OWNER_MACHINE_LAYOUT.md); do not duplicate that path table here.

## Owner data and runtime isolation

Follow [Owner data and efficient task execution](docs/OWNER_DATA_WORKFLOW.md).
Owner-requested analysis, diagnosis and UAT permit relevant real-data reads and
ordinary presentation in the authorized assistant conversation, without masking
personal values or asking again for each query/image. Keep credentials out of
outputs, real datasets out of tracked code/CI, and synthetic data in automated tests.
Reading data is distinct from permission to change data, runtime or publication.
Preserve Stable and the applicable migration/recovery/financial/health contracts.

## Scope discipline

Do only the assigned issue/listed eligible work: no automatic next roadmap item, unrelated cleanup or unused future infrastructure. Do not reinterpret product/health semantics without an issue/ADR decision. Missing/unknown/unavailable is never silently zero; do not invent diagnosis or causality from wearable/BIA associations. Return architecture/privacy/canonical-data/health-semantics expansion to the Integrator for re-scope.

## Verification

Claim the physical checkout before writing/testing and check ownership before delivery, as described in the Owner-data workflow. Every STOP cites a concrete boundary or failure; do not invent privacy gates for authorized Owner reads.

Use [proportional checks](docs/DEVELOPMENT_PROCESS.md#verification-by-change), then required exact-candidate/integration gates. A separate participant does not automatically rerun the full suite; inspect valid evidence and add focused checks for concrete gaps. Required independent review is set by [risk policy](docs/MODEL_ROUTING.md#independent-review-triggers), not by enabling a queue.

Never claim tests, browser/device/provider checks, independent review or success that were not performed. Report exact commands/results, candidate identity, failures and remaining `UNVERIFIED` work. Missing/interrupted/mismatched evidence is not a pass; changed code must not inherit an old pass. CI provenance/completeness rules are unchanged.

## Completion reporting

Return one concise report: issue/status; baseline/target; branch/workspace/final SHA; change summary (diff stat when available); actual checks/results; material deviations/blockers/limitations. For local Git work include clean/dirty status and HEAD/remote read-back; state any departure from assigned branch/workspace boundaries. Omit irrelevant optional fields rather than filling N/A sections.

Model benchmarking and attribution bookkeeping were retired by the Owner in [#210](https://github.com/LTstripes/Health-Check/issues/210). Do not request or wait for model/provider labels, require a Model evidence block, or append model scores/journal entries. Older model-reporting instructions are explicitly superseded; ordinary technical evidence and review gates remain required. Never include hidden reasoning or credentials. Owner-visible health evidence follows the linked Owner-data workflow; public engineering reports do not publish private datasets.

## Durable history and decisions

Detailed evidence lives in issue/PR; Integrator-maintained engineering history keeps short linked outcomes, including useful failures. Workers/Orchestrators do not edit shared history. Durable contract changes belong in architecture/decision docs or ADRs; product releases need release notes, not copied engineering reports.

## Delivery

Worker delivers the pushed task branch and report. Integrator checks the actual diff/evidence, accepts or returns findings, and alone performs canonical integration under [Development Process](docs/DEVELOPMENT_PROCESS.md). Orchestrated queues add only their [queue report](docs/AGENT_ORCHESTRATION.md#final-queue-report), not batch project acceptance.
