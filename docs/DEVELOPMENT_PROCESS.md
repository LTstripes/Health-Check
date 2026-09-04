# Development Process

This document defines how Health-Check work is planned, implemented by external coding agents, reviewed, integrated and preserved for later retrospectives/articles.

The workflow intentionally reuses lessons from `LTstripes/hermes-finance`, while reducing unnecessary rebases and central-log merge conflicts.

## 1. Core operating model

Normal flow:

1. Owner discusses a need with the Integrator (ChatGPT/Lera).
2. Integrator classifies complexity/model routing and creates/updates the authoritative GitHub issue.
3. Integrator chooses the release integration baseline, task branch and assigned local workspace.
4. Integrator sends the owner a short copyable launch prompt.
5. Owner launches the selected worker in Codex, Grok Build or Hermes.
6. Worker reads `AGENTS.md`, the issue and active release spec; implements only the task; tests; commits/pushes its task branch; returns a completion report.
7. Owner forwards that report to the Integrator.
8. Integrator reads the actual GitHub branch/diff/check evidence, reviews it and decides ACCEPT / FIXES REQUIRED / REJECT.
9. Accepted work is merged by the Integrator into the current release integration branch (or `main` for a deliberately tiny standalone task).
10. Integrator updates engineering history and any canonical docs made stale.
11. At release gate, owner-only preview/UAT validates the integrated release.
12. Integrator reviews and merges the release integration PR into `main`, then reads back canonical state.

Workers implement. The Integrator owns acceptance, GitHub integration and durable engineering history.

## 2. Branch strategy

### `main`

Canonical stable/accepted project state. No coding agent writes directly to it.

### Release integration branch

For releases composed of multiple tasks, create one branch from current `main`, for example:

- `integration/r01-weight-core`
- later `integration/r02-garmin`

This branch is the moving integration target for that release. It solves the old Finance problem where every task had to chase a moving `main` while parallel development was active.

Task PRs target the release integration branch. Only after release integration/UAT passes do we open one integration -> `main` PR.

### Task branches

Pattern:

`task/<github-issue>-<short-slug>`

A task branch starts from an exact pinned SHA of the release integration branch. The issue and launch prompt record that SHA.

### Parallel work

Only genuinely independent scopes run in parallel. If task B depends on task A's schema/API, task B starts only after A is integrated unless the issue explicitly provides a stable contract fixture.

A task does not rebase continuously. If integration advances while a worker is coding, the worker stays on the pinned baseline. At review time the Integrator decides whether:

- candidate is independent and can merge cleanly as-is;
- one refresh/retest pass is needed;
- candidate conflicts semantically and must be revised.

Schema/migration/security/network/canonical-data tasks are treated conservatively and normally refresh/retest against latest integration before acceptance.

## 3. Local workspace layout

GitHub is canonical. Local paths are execution/preview locations, not sources of truth.

`D:\Garmin` is the owner-only parent root. It contains separate main and UAT checkouts; the parent directory itself is not a mutable Git checkout.

### Owner canonical checkout

`D:\Garmin\Garmin-Main`

Purpose:

- owner/integrator stable checkout of accepted `main`;
- convenient local read/run point after releases;
- never a development-agent workspace.

Other coding agents must not access, branch-switch, reset or use this checkout.

### Owner preview/UAT checkout

`D:\Garmin\Garmin-UAT`

Purpose:

- owner-only checkout of the current release integration candidate;
- browser/manual preview;
- live S400/Garmin/Fitbit probes when their release reaches that gate;
- private UAT data profiles.

Coding workers must not use this workspace.

Runtime/private data remains outside Git checkout, preferably through release/profile-specific `HEALTHCHECK_DATA_DIR`, for example `%LOCALAPPDATA%\Health-Check\uat` and later `%LOCALAPPDATA%\Health-Check\prod`. Do not reuse one private database across arbitrary branches.

### Codex root

`D:\Codex\Garmin`

Task workspace pattern:

`D:\Codex\Garmin\workspaces\<issue>-<slug>`

### Grok Build root

`D:\Grok\Garmin`

Task workspace pattern:

`D:\Grok\Garmin\workspaces\<issue>-<slug>`

### Hermes root

`D:\Hermes Project\hermes-garmin`

Task workspace pattern:

`D:\Hermes Project\hermes-garmin\workspaces\<issue>-<slug>`

The three paths above are parent roots. Do not keep one shared mutable clone at the root and switch branches between concurrent tasks. Each active task owns its own clone/worktree directory.

If these machine paths change, the issue/Integrator launch note may override them; repository branch and issue remain authoritative.

## 4. Workspace creation rules for workers

A worker may create only the task directory explicitly assigned below its client root. It may clone/fetch the repository there and check out the assigned branch/baseline.

Workers must not:

- inspect `D:\Garmin\Garmin-Main` or `D:\Garmin\Garmin-UAT`;
- reuse another task directory;
- create sibling roots elsewhere on disk;
- link private owner runtime/data into a dev clone;
- switch/reset a working tree currently used by another session.

Parallel Hermes bots/delegates follow the same invariant. Multiple simultaneous writers require separate sub-workspaces/branches; a supervising Hermes session remains accountable for the final candidate and reports all delegates used.

## 5. Task definition

The Integrator creates a GitHub issue before implementation. It should include:

- release/task ID and objective;
- complexity/risk class and recommended executor;
- target integration branch and exact baseline SHA;
- dependencies;
- required source documents;
- in-scope and explicit out-of-scope;
- acceptance criteria;
- privacy/live-data boundary;
- exact expected verification;
- expected completion report.

Task requirements live in GitHub, not only in chat. If scope changes, the issue body or an explicit `Integrator note` comment is updated before the worker implements the new requirement.

## 6. Launch prompt convention

The Integrator sends the owner a short prompt, normally like:

```text
Health-Check task #NN — <title>
Complexity: C2 / Normal
Recommended executor: Luna High (alternative: Grok High)

Repo: https://github.com/LTstripes/Health-Check
Issue: <URL>
Target integration: integration/r01-weight-core @ <SHA>
Branch: task/<issue>-<slug>
Workspace: D:\Codex\Garmin\workspaces\<issue>-<slug>

Read AGENTS.md, the issue and the active release spec. Implement only the issue. Run the required checks. Commit/push only the task branch. Do not merge or modify main/integration. Return the canonical completion report with exact final SHA.
```

The issue contains details; the launch prompt is a locator, not a second specification.

## 7. Worker completion -> Integrator review

The owner forwards the worker's completion report. The Integrator does not accept that summary as proof.

Integrator checks, as applicable:

- branch and exact baseline/candidate SHAs;
- actual GitHub diff and changed-file scope;
- whether task/architecture contracts were followed;
- tests/checks actually evidenced;
- privacy/secrets/runtime-data boundary;
- migrations/schema/data semantics;
- docs made stale;
- whether integration branch moved and whether refresh is needed.

Possible verdicts:

- **ACCEPT** — candidate is integrated.
- **FIXES REQUIRED** — same issue/candidate remains open with explicit findings.
- **REJECT** — approach/candidate is not integrated; reason is preserved in history.

A reviewer never silently repairs a candidate and then calls the original worker's result accepted. Trivial Integrator-owned documentation/metadata fixes may be explicit separate commits; behavioral fixes become a follow-up worker pass/task.

## 8. Engineering history — everything useful is retained

`docs/EXECUTION_HISTORY.md` is maintained by the Integrator, not by parallel workers.

Record both successful and useful failed/rejected attempts. Each entry should capture:

- date;
- release/task/issue;
- executor client/model and any Hermes delegates/fallbacks;
- complexity/routing decision;
- baseline/integration SHA;
- task branch and candidate SHA;
- original objective;
- what was actually implemented;
- important files/areas;
- tests/checks;
- unexpected problems;
- decisions changed during implementation and why;
- review findings/verdict;
- merge/integration SHA or rejection reason;
- retrospective note worth remembering for a future article/process improvement.

Do not store private health values, screenshots, credentials or raw personal payloads in engineering history.

### Durable decision split

- **Execution History**: what happened, by whom, problems/outcome.
- **Issue**: authoritative task scope.
- **Architecture/Decision docs or ADR**: durable rule changed for future work.
- **Roadmap**: current release sequence.
- **Backlog Ideas**: non-committed future ideas.

This avoids a giant diary becoming the product specification.

## 9. Model/agent attribution

Record the runtime-reported model when known. Do not infer model identity from a UI label if the runtime/report says something else.

If Hermes starts with one model and falls back/delegates to another, record the chain, for example:

`Step 3.7 Flash -> DeepSeek V4 Flash fallback`

That history is useful for later model benchmarks and the eventual story of how the project was built.

## 10. Release integration and UAT

For the R01 release gate use the concise owner checklist in `docs/R01_OWNER_UAT.md`.

When all planned tasks for a release are integrated:

1. Integrator reviews the complete integration diff against the release spec.
2. Automated full release checks pass.
3. Owner UAT/preview runs from `D:\Garmin\Garmin-UAT`, using a separate private runtime profile.
4. Live/provider/device probes required by that release are performed or explicitly remain `UNVERIFIED` if allowed by the spec.
5. Integrator resolves findings in dedicated task branches, not by ad-hoc edits in UAT checkout.
6. Integrator opens/reviews integration -> `main` PR.
7. Accepted release is merged to `main`.
8. `D:\Garmin\Garmin-Main` is fast-forwarded to canonical `main` by the owner when convenient; GitHub remains canonical.
9. Release documentation/history is synchronized.

## 11. Benchmark / A-B tasks

When intentionally comparing models on the same task:

- pin one exact baseline;
- give each candidate a separate branch/workspace;
- candidates do not read/copy one another before completion;
- compare actual diffs/tests/evidence, not prose confidence;
- log model, timing if known, candidate SHA, result and Integrator verdict in Execution History.

Benchmark candidates are not automatically merged; the Integrator selects or synthesizes the accepted approach.

## 12. Future Hermes automation

Later we may automate issue pickup, worker/reviewer bots and integration inside Hermes. The same contracts remain:

- issue is authority;
- isolated workspace/branch per writer;
- delegates cannot self-accept;
- final Integrator gate remains explicit;
- execution history records the delegation chain;
- private owner runtime remains outside bot workspaces.

Automation may remove manual message shuttling; it must not remove accountability or evidence.
