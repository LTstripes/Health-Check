# AGENTS.md — Health-Check

Universal project constitution for coding/review agents. Read this before every task. Client-specific adapters live in `docs/agents/` and may add mechanics but must not weaken these rules.

## Read by task type

Read this constitution and the current issue/applicable Integrator notes once at task start; refresh them when the assignment or authoritative facts change. Read detailed sources by need, not as a mandatory whole-repository tour:

- Docs/process-only: affected documents and their referenced policy sections; no product-wide architecture/test inventory.
- Implementation/bugfix: the relevant contract/architecture and affected source/tests, plus the verification policy below.
- Financial/data semantics, restore, migration, privacy or runtime boundaries: the governing spec/ADRs and applicable review/UAT gates before changing that boundary.
- Task routing/proposal: `docs/MODEL_ROUTING.md`; client mechanics: only the relevant `docs/agents/` adapter.
- Health launch compatibility, or an explicitly requested orchestration/queue: the relevant `docs/AGENT_ORCHESTRATION.md` section; reading it does not activate the loop.

Use already-read unchanged context. Historical task catalogs are not standing orders. Within the authorized task, perform routine reversible investigation, edits, synthetic checks and permitted delivery without repeated approval; scope/product/security/data decisions and canonical integration retain their existing owners.

## Sources of truth

When documents disagree, use this order:

1. `docs/PRODUCT_VISION.md` — product purpose and boundaries.
2. `docs/ARCHITECTURE.md` and accepted ADRs — architecture invariants and durable technical contracts.
3. The active release implementation spec named by the current release tracker / explicit Integrator note. A completed release spec remains historical evidence and is not automatically the next release's active spec.
4. The active GitHub issue and explicit Integrator notes — task-specific scope and acceptance criteria.
5. `docs/DEVELOPMENT_PROCESS.md` — branch/workspace/review protocol.
6. `docs/MODEL_ROUTING.md` — complexity/routing/escalation protocol.
7. `docs/AGENT_ORCHESTRATION.md` — execution modes and project-facing orchestration contract.
8. `docs/DECISIONS_AND_OPEN_QUESTIONS.md` — current decisions and live verification items.
9. `docs/BACKLOG_IDEAS.md` and historical/audit material — context only unless promoted into an active spec.

If no new release implementation spec has been promoted yet, use architecture + roadmap + the active GitHub issue/Integrator note; do not silently treat the previous release spec as current.

A task issue may narrow an architecture/spec but may not silently override a higher-priority invariant. Escalate conflicts to the Integrator.

## Roles

- **Owner** — chooses product direction and may perform private/live UAT.
- **Integrator** — currently ChatGPT/Lera in the normal workflow. Creates task specs, chooses routing, manages GitHub, reviews candidates, accepts/rejects, merges and updates durable logs/docs.
- **Execution Orchestrator** — optional execution-local coordinator. May plan, delegate, internally review/remediate and coordinate only an explicitly authorized queue. Does not own project acceptance or canonical integration.
- **Worker** — one accountable implementation writer for one candidate. Does not self-accept.
- **Delegate** — bounded helper below an Orchestrator/Worker. Does not self-accept.
- **Reviewer** — independently validates a candidate without silently modifying it.

The default principle remains: **Workers provide the hands; the Integrator owns project acceptance and repository integration.** Root/Orchestrator self-review is not called independent review.

## Task prompt authority

The current GitHub issue, accepted contract and applicable Integrator notes define the task under the source precedence above. A launch prompt is a locator and execution assignment, not a second specification. Update the authoritative issue/note when requirements change.

Use the [Owner task proposal](docs/MODEL_ROUTING.md#owner-task-proposal) format when handing a task to the Owner. The launch identifies the issue/note, assigned branch and actual workspace, exact baseline/target, intended result and authorized delivery. Missing safety-critical information must be resolved before writes.

One bounded task defaults to one Worker; independent review follows risk policy and does not activate orchestration. Only an explicit orchestration/queue request uses `docs/AGENT_ORCHESTRATION.md` and its listed eligible tasks.

For Health implementation launches, record and verify the [launch compatibility decision](docs/AGENT_ORCHESTRATION.md#launch-compatibility-assessment), including applicable comments, dependency state and shared artifact ownership. Do not silently rewrite existing assignments.

## Git ownership

- `main` is the only canonical accepted/stable history and the only release source. Workers never write to `main`.
- During a multi-task release, the Integrator may create one release integration branch such as `integration/r01-weight-core` or `integration/r02-garmin`.
- A release integration branch is a staging/coordination line, never a second source of truth.
- After a release is merged to `main`, its integration branch becomes historical/staging-only. The next release integration branch starts from the then-current canonical `main`, not from the old integration branch or an arbitrary stacked task branch.
- Worker branches are isolated, normally `task/<issue>-<slug>`, from an exact pinned integration SHA.
- A Worker may commit and push only its assigned task branch.
- Workers/Execution Orchestrators do not merge, force-push, delete branches/tags, retarget PRs or alter repository settings unless explicitly delegated.
- By default Workers do not create PRs; the Integrator handles PR creation/review/merge through GitHub.
- Reviewers do not mutate the candidate they independently review.
- An Execution Orchestrator does not become a second writer after delegation.

## Stale-base and parallel-work policy

A task stays pinned to its assigned baseline while it is being implemented. Do not repeatedly rebase just because the integration branch moved.

- Independent parallel tasks may finish against the same pinned integration SHA.
- The Integrator decides at review time whether a stale candidate can merge cleanly or needs one refresh/retest pass.
- A refresh is normally required for overlapping files, migrations/schema, security/network boundaries, canonical data semantics or other high-risk shared contracts.
- Accepted-but-held work from a previous release freeze is not automatically merge-ready after the freeze lifts; re-read the new canonical baseline, reconcile lineage as needed, and rerun the required exact-head checks.
- Low-risk independent work does not require churn merely to match the newest SHA.
- Never rebase/reset another agent's branch or workspace.

## Physical workspace isolation

One active write/verification task owns one physical working tree. Branch isolation alone is not sufficient for parallel sessions.

Concrete workstation assignments come from Owner-local configuration and the explicit launch. `docs/DEVELOPMENT_PROCESS.md` defines the protected location roles. Each agent uses only its assigned task clone/worktree; Owner canonical, Stable/private-runtime and UAT locations are forbidden development workspaces regardless of their paths.

Agents must not create, move, rename, inspect or delete sibling workspaces outside their assigned task directory unless the Integrator explicitly assigns that filesystem operation.

## Runtime/private-data isolation — hard invariant

Development-agent workspaces must not contain or access real personal health data or Owner credentials, including:

- real Health-Check SQLite databases or sidecars;
- Xiaomi/Garmin/Fitbit payloads from the Owner's account unless explicitly sanitized for a private Owner-only probe;
- screenshots/photos containing real measurements;
- tokens, bind keys, MAC/key material, refresh tokens or secrets;
- private lab/medical documents;
- Owner UAT runtime data;
- symlinks/junctions/hardlinks to any of the above.

Repository and normal agent tests use synthetic fixtures only. Private/live verification is Owner/Integrator controlled and is reported as `UNVERIFIED` until actually performed.

The durable Stable Owner data profile is identified by the Owner-local assignment. Development Workers/Reviewers must not inspect or mutate it unless an issue explicitly authorizes an Owner-controlled live gate. Release/product UAT must use a disposable verified backup/restore clone; Stable is never reset or repurposed as a candidate sandbox.

## Scope discipline

- Do only the assigned issue.
- A normal Worker does not start the next roadmap item automatically.
- In a sequential `$delivery-loop` queue, an Execution Orchestrator advances only to the next **explicitly listed eligible task** after the prior task reached `INTERNAL_ACCEPT`, subject to the integration-block exception below. Explicit parallel assignments require the launch compatibility assessment and separate acceptance gates.
- The Orchestrator must not discover/invent extra roadmap/backlog work.
- `BLOCKED_FOR_INTEGRATION` blocks the affected dependency chain. Continue to unrelated explicitly listed eligible queue items only when the launch explicitly enables integration-block continuation; otherwise stop.
- Do not perform unrelated cleanup "while here".
- Do not add unused infrastructure for future releases.
- Do not reinterpret product/health semantics without an issue/ADR decision.
- Missing/unknown/unavailable data is never silently converted to zero.
- Do not make diagnosis or causal claims from wearable/BIA associations.
- If justified risk discovered during execution implies architecture, privacy, canonical-data or health-semantics expansion, STOP and return to the Integrator for re-scope.

## Verification

Every task must perform the checks specified by the issue/release spec and truthfully report what actually ran. Apply the proportional early contract checkpoint and final-gate scheduling in [`docs/AGENT_ORCHESTRATION.md`](docs/AGENT_ORCHESTRATION.md#early-contract-checkpoint-and-final-gates); this does not waive any required gate.

Minimum completion discipline:

- targeted tests/checks proportional to the change;
- final diff/scope/privacy review;
- exact baseline, branch and final candidate SHA;
- exact test commands/outcomes;
- limitations, failures and remaining `UNVERIFIED` items;
- final `git status --short` and remote/HEAD read-back when working locally.

Do not claim a full suite, browser smoke, live provider test or device verification unless it actually ran.

Independent review is required when `docs/MODEL_ROUTING.md` says so, when Owner/Integrator explicitly requests it, or when justified execution risk raises the review bar under project policy. Evidence counts as independent review only when a separate Reviewer actually ran.

## Completion reporting

A normal Worker returns one concise per-task report containing:

- task/issue ID;
- runtime-reported client/model (and Delegates/fallbacks if applicable);
- baseline SHA and target integration branch;
- task branch and physical workspace;
- exact final candidate SHA;
- what changed and key files;
- exact checks and outcomes;
- deviations from the original plan and why;
- blockers/surprises/limitations;
- working-tree status;
- confirmation that `main` and unrelated branches/workspaces were not modified.

An orchestrated queue additionally returns one final queue report listing every authorized task, its final internal state, candidate SHA where applicable, review path and unresolved Integrator action. That queue report is not batch project acceptance.

Do not edit `docs/EXECUTION_HISTORY.md` as a normal Worker/Execution Orchestrator. The Integrator records accepted, rejected and abandoned attempts centrally after review.

## Durable history and decisions

- `docs/EXECUTION_HISTORY.md` records who did what, model/client, baseline/candidate, problems, changes of plan, review verdict and integration result — including useful failed/rejected attempts.
- Important durable architecture/data/security changes require an ADR or an explicit update to canonical architecture/decision docs.
- Release/user-facing changes later belong in a changelog/release note; engineering history is not a substitute for release notes.
- Logs must never include private health values or secrets.

## Delivery

A Worker delivers a pushed task branch and completion report. The Integrator then inspects GitHub diff/evidence, requests fixes or rejects/accepts, merges accepted work into the current integration branch, updates execution history and affected canonical docs, and eventually opens the release integration -> `main` PR.

`INTERNAL_ACCEPT` from an Execution Orchestrator is evidence only and does not authorize integration.

After a release merge to `main`, canonical `main` must be read back, exact post-merge CI checked, release/UAT status recorded, and the next release must restart from the new canonical `main` rather than continuing from the old release integration branch.
