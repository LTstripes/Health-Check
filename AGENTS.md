# AGENTS.md — Health-Check

Universal project constitution for coding/review agents. Read this before every task. Client-specific adapters live in `docs/agents/` and may add mechanics but must not weaken these rules.

## Sources of truth

When documents disagree, use this order:

1. `docs/PRODUCT_VISION.md` — product purpose and boundaries.
2. `docs/ARCHITECTURE.md` and accepted ADRs — architecture invariants and durable technical contracts.
3. The active release implementation spec named by the current release tracker / explicit Integrator note. A completed release spec remains historical evidence and is not automatically the next release's active spec.
4. The active GitHub issue and explicit Integrator notes — task-specific scope and acceptance criteria.
5. `docs/DEVELOPMENT_PROCESS.md` — branch/workspace/review protocol.
6. `docs/MODEL_ROUTING.md` — complexity/routing/escalation protocol.
7. `docs/DECISIONS_AND_OPEN_QUESTIONS.md` — current decisions and live verification items.
8. `docs/BACKLOG_IDEAS.md` and historical/audit material — context only unless promoted into an active spec.

If no new release implementation spec has been promoted yet, use architecture + roadmap + the active GitHub issue/Integrator note; do not silently treat the previous release spec as current.

A task issue may narrow an architecture/spec but may not silently override a higher-priority invariant. Escalate conflicts to the Integrator.

## Roles

- **Owner** — chooses product direction and may perform private/live UAT.
- **Integrator** — currently ChatGPT/Lera in the normal workflow. Creates task specs, chooses routing, manages GitHub, reviews candidates, accepts/rejects, merges, updates durable logs/docs.
- **Worker** — Codex, Grok Build, Hermes/its delegates, or another assigned coding agent. Implements only the assigned issue and does not self-accept.
- **Reviewer** — independently validates a candidate. Does not silently modify the candidate under review.

The default principle is: **workers provide the hands; the Integrator owns acceptance and repository integration.**

## Task prompt authority

The GitHub issue is the authoritative task specification. A launch prompt sent by the Integrator is intentionally short and normally contains only:

- issue number/link;
- assigned model/client and complexity;
- assigned physical workspace root/task directory;
- task branch and exact baseline/integration SHA;
- instruction to read this file, the active release spec (when one is designated) and the issue;
- instruction to run required checks, commit/push only the task branch and return the exact final SHA.

Do not duplicate the whole issue in chat prompts. If requirements change, the Integrator updates the issue or adds an explicit Integrator note in GitHub; chat-only requirement drift is not authoritative.

## Git ownership

- `main` is the only canonical accepted/stable history and the only release source. Workers never write to `main`.
- During a multi-task release, the Integrator may create one release integration branch such as `integration/r01-weight-core` or `integration/r02-garmin`.
- A release integration branch is a staging/coordination line, never a second source of truth.
- After a release is merged to `main`, its integration branch becomes historical/staging-only. The next release integration branch starts from the then-current canonical `main`, not from the old integration branch or an arbitrary stacked task branch.
- Worker branches are isolated, normally `task/<issue>-<slug>`, from an exact pinned integration SHA.
- A worker may commit and push only its assigned task branch.
- Workers do not merge, force-push, delete branches/tags, retarget PRs or alter repository settings unless explicitly delegated.
- By default workers do not create PRs; the Integrator handles PR creation/review/merge through GitHub.
- Reviewers do not mutate the candidate they are independently reviewing.

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

Current owner workstation assignments are documented in `docs/DEVELOPMENT_PROCESS.md`. Each local agent uses a task-specific clone/worktree under its own assigned root. The owner canonical and UAT workspaces are forbidden agent development workspaces.

Agents must not create, move, rename, inspect or delete sibling workspaces outside their assigned task directory unless the Integrator explicitly assigns that filesystem operation.

## Runtime/private-data isolation — hard invariant

Development-agent workspaces must not contain or access real personal health data or owner credentials, including:

- real Health-Check SQLite databases or sidecars;
- Xiaomi/Garmin/Fitbit payloads from the owner's account unless explicitly sanitized for a private owner-only probe;
- screenshots/photos containing real measurements;
- tokens, bind keys, MAC/key material, refresh tokens or secrets;
- private lab/medical documents;
- owner UAT runtime data;
- symlinks/junctions/hardlinks to any of the above.

Repository and normal agent tests use synthetic fixtures only. Private/live verification is owner/integrator controlled and is reported as `UNVERIFIED` until actually performed.

## Scope discipline

- Do only the assigned issue.
- Do not start the next roadmap item automatically.
- Do not perform unrelated cleanup "while here".
- Do not add unused infrastructure for future releases.
- Do not reinterpret product/health semantics without an issue/ADR decision.
- Missing/unknown/unavailable data is never silently converted to zero.
- Do not make diagnosis or causal claims from wearable/BIA associations.

## Verification

Every task must perform the checks specified by the issue/release spec and truthfully report what actually ran.

Minimum completion discipline:

- targeted tests/checks proportional to the change;
- final diff/scope/privacy review;
- exact baseline, branch and final candidate SHA;
- exact test commands/outcomes;
- limitations, failures and remaining `UNVERIFIED` items;
- final `git status --short` and remote/HEAD read-back when working locally.

Do not claim a full suite, browser smoke, live provider test or device verification unless it actually ran.

## Completion report from a worker

Return one concise report containing:

- task/issue ID;
- runtime-reported client/model (and delegates/fallbacks if applicable);
- baseline SHA and target integration branch;
- task branch and physical workspace;
- exact final candidate SHA;
- what changed and key files;
- exact checks and outcomes;
- deviations from the original plan and why;
- blockers/surprises/limitations;
- working-tree status;
- confirmation that `main` and unrelated branches/workspaces were not modified.

Do not edit `docs/EXECUTION_HISTORY.md` as a normal worker. The Integrator records accepted, rejected and abandoned attempts centrally after review to avoid parallel merge conflicts and preserve neutral history.

## Durable history and decisions

- `docs/EXECUTION_HISTORY.md` records who did what, model/client, baseline/candidate, problems, changes of plan, review verdict and integration result — including useful failed/rejected attempts.
- Important durable architecture/data/security changes require an ADR or an explicit update to canonical architecture/decision docs.
- Release/user-facing changes later belong in a changelog/release note; engineering history is not a substitute for release notes.
- Logs must never include private health values or secrets.

## Delivery

A worker delivers a pushed task branch and completion report. The Integrator then inspects GitHub diff/evidence, requests fixes or rejects/accepts, merges accepted work into the current integration branch, updates execution history and affected canonical docs, and eventually opens the release integration -> `main` PR.

After a release merge to `main`, canonical `main` must be read back, exact post-merge CI checked, release/UAT status recorded, and the next release must restart from the new canonical `main` rather than continuing from the old release integration branch.
