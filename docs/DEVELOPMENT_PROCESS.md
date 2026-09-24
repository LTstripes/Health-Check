# Development Process

This document defines how Health-Check work is planned, implemented by external coding agents, reviewed, integrated and preserved for later retrospectives/articles.

The workflow intentionally reuses lessons from `LTstripes/hermes-finance`, while reducing unnecessary rebases and central-log merge conflicts.

Execution-mode semantics are additionally defined in `docs/AGENT_ORCHESTRATION.md`.

## 1. Core operating model

Normal manual/brokered flow:

1. Owner discusses a need with the Integrator (ChatGPT/Lera).
2. Integrator classifies complexity/model routing and creates/updates the authoritative GitHub issue.
3. Integrator chooses the release integration baseline, task branch and assigned local workspace.
4. Integrator sends the Owner a short copyable launch prompt.
5. Owner launches the selected Worker in Codex, Grok Build, Hermes or another selected client.
6. Worker reads `AGENTS.md`, the issue and the active release spec when one is designated; implements only the task; tests; commits/pushes its task branch; returns a completion report.
7. Owner forwards that report to the Integrator.
8. Integrator reads the actual GitHub branch/diff/check evidence, reviews it and decides ACCEPT / FIXES REQUIRED / REJECT.
9. Accepted work is merged by the Integrator into the current release integration branch (or `main` for a deliberately tiny standalone task).
10. Integrator updates engineering history and any canonical docs made stale.
11. At release gate, Owner-only preview/UAT validates the integrated release.
12. Integrator reviews and merges the release integration PR into `main`, then reads back canonical state and exact post-merge CI.
13. The completed release integration line becomes historical/staging-only; the next release starts from the new canonical `main`.

Workers implement. The Integrator owns project acceptance, GitHub integration and durable engineering history.

### 1.1 Owner execution intent

- `дай задачу для Grok` -> manual Grok Worker;
- `дай задачу для Hermes` -> manual Hermes Worker;
- `дай задачу для <model/client>` -> manual Worker unless orchestration is explicitly requested;
- `Codex без оркестрации` -> manual Codex Worker;
- `дай задачу для Codex` -> manual single-Worker route by default;
- `дай серию задач для Codex` -> assess the assigned set and propose compatible ordering; automated execution requires an explicit `$delivery-loop`/orchestration launch.

The Integrator honors the requested implementation route while continuing to perform GitHub-side issue/PR/review/merge mechanics directly when available.

### 1.2 Codex `$delivery-loop` route

The activation, packet, queue, remediation and internal-verdict protocol is defined once in [`AGENT_ORCHESTRATION.md`](AGENT_ORCHESTRATION.md). Ordinary tasks use one Worker; only an explicit orchestration launch uses that protocol. `INTERNAL_ACCEPT` never grants project acceptance or merge authority.

## 2. Branch strategy

### `main`

Canonical stable/accepted project state and the only release source. No coding agent writes directly to it.

### Release integration branch

For releases composed of multiple tasks, create one branch from current `main`, for example:

- `integration/r01-weight-core`
- `integration/r02-garmin`

This branch is the moving integration target for that release. It solves the old Finance problem where every task had to chase a moving `main` while parallel development was active.

Task PRs target the release integration branch. Only after release integration/UAT passes do we open one integration -> `main` PR.

A release integration branch is never a second source of truth and must not become the baseline for the next release after it has already been released. Once its release is merged to `main`, the next release integration branch is created from the then-current canonical `main`.

Accepted task branches that were intentionally held during a release freeze must be re-read against the new `main`; their old acceptance does not by itself make their historical branch merge-ready after the freeze lifts.

### Task branches

Pattern:

`task/<github-issue>-<short-slug>`

A task branch starts from an exact pinned SHA of the release integration branch. The issue and launch prompt record that SHA.

### Parallel work

Complete the [launch compatibility assessment](AGENT_ORCHESTRATION.md#launch-compatibility-assessment) and record shared artifact ownership before launch. Parallel execution requires explicit Owner opt-in. Only genuinely independent scopes run in parallel. If task B depends on task A's schema/API, task B starts only after A is integrated unless the issue explicitly provides a stable contract fixture or the Integrator explicitly supplies a safe dependency/baseline strategy.

A task does not rebase continuously. If integration advances while a Worker is coding, the Worker stays on the pinned baseline. At review time the Integrator decides whether:

- candidate is independent and can merge cleanly as-is;
- one refresh/retest pass is needed;
- candidate conflicts semantically and must be revised.

Schema/migration/security/network/canonical-data tasks are treated conservatively and normally refresh/retest against latest integration before acceptance.

For stacked accepted work created before the previous release completed, reconstruct the accepted semantic deltas onto the new canonical lineage instead of blindly merging a diverged stack. Preserve exact accepted behavior, migration order and review evidence; rerun exact-head checks on the reconstructed line.

## 3. Local workspace layout

GitHub is canonical. Concrete workstation paths belong to the Owner's local configuration and the explicit task assignment, not this repository. Record the assigned physical task directory and exact branch/baseline at launch; if the assignment is missing or conflicts with a protected location, resolve it before writing.

The following roles remain mandatory regardless of machine paths:

- **Owner canonical checkout:** accepted-main read/run location, never an agent development workspace; agents must not inspect, switch or reset it without a specific Owner-controlled assignment.
- **Owner preview/UAT checkout:** Owner-only candidate preview and gated private/device verification; never a development workspace.
- **Stable private data runtime:** durable Owner evidence and verified backup source, outside Git; never reset or repurpose it for candidate testing. Only an explicitly authorized Owner-controlled live gate may access it.
- **Per-client development root:** a container for separate explicitly assigned task clones/worktrees, never one shared mutable checkout switched between concurrent tasks.

Candidate UAT uses a disposable runtime restored from a verified Stable backup. No real health data, credentials, backups or links to private locations enter an agent workspace. A changed machine path cannot relax these exclusions or authorize inspection of siblings.

## 4. Workspace creation rules for workers

A Worker may create only the task directory explicitly assigned below its client root. It may clone/fetch the repository there and check out the assigned branch/baseline.

Workers, Delegates and Execution Orchestrators must not:

- inspect the Owner canonical, Stable/private-runtime or preview/UAT locations;
- reuse another task directory;
- create sibling roots elsewhere on disk;
- link private Owner runtime/data into a dev clone;
- switch/reset a working tree currently used by another session.

Parallel Hermes bots/Delegates follow the same invariant. Multiple simultaneous writers require separate sub-workspaces/branches; a supervising Hermes Worker remains accountable for the final candidate and reports all Delegates used.

## 5. Task definition

The Integrator creates a GitHub issue before implementation. It should include:

- release/task ID and objective;
- complexity/risk class, recommended executor/route and execution-mode rationale;
- launch compatibility decision: dependencies, shared artifact/contract ownership and safe order or explicitly authorized parallel boundaries;
- target integration branch and exact baseline SHA;
- dependencies;
- required source documents and applicable Integrator comment IDs/URLs;
- in-scope and explicit out-of-scope;
- acceptance criteria;
- privacy/live-data boundary;
- proportional early contract checkpoint (or why not applicable), exact expected verification and final harness/CI/review ordering;
- completion/remediation mode for orchestration;
- expected completion report.

Task requirements live in GitHub, not only in chat. If scope changes, the issue body or an explicit `Integrator note` comment is updated before the Worker implements the new requirement.

## 6. Launch prompt convention

Use the [Owner task proposal](MODEL_ROUTING.md#owner-task-proposal) format. Keep the explanation and complexity/risk/model recommendation outside the copyable 5–8-line locator prompt. Record the [launch compatibility decision](AGENT_ORCHESTRATION.md#launch-compatibility-assessment) in the authoritative issue/note; do not duplicate requirements in the prompt.

An explicitly requested orchestration/queue adds the fields required by `AGENT_ORCHESTRATION.md`; an ordinary Worker launch does not load that extra procedure. A missing safety-critical contract or assignment is resolved before launch.

## 7. Worker / Orchestrator completion -> Integrator review

The Owner forwards the Worker completion report or Codex queue report. The Integrator does not accept that summary as proof.

Integrator checks, as applicable:

- branch and exact baseline/candidate SHAs;
- actual GitHub diff and changed-file scope;
- whether task/architecture contracts were followed;
- tests/checks actually evidenced;
- privacy/secrets/runtime-data boundary;
- migrations/schema/data semantics;
- docs made stale;
- whether required independent review actually ran;
- whether integration branch moved and whether refresh is needed.

Possible verdicts:

- **ACCEPT** — candidate is integrated or explicitly accepted-and-held with a stated future gate.
- **FIXES REQUIRED** — same issue/candidate remains open with explicit findings.
- **REJECT** — approach/candidate is not integrated; reason is preserved in history.

`INTERNAL_ACCEPT` is only an internal Codex delivery-loop verdict and never substitutes for this Integrator decision.

A Reviewer never silently repairs a candidate and then calls the original Worker's result accepted. Trivial Integrator-owned documentation/metadata fixes may be explicit separate commits; behavioral fixes become a follow-up Worker pass/task.

## 8. Engineering history — everything useful is retained

`docs/EXECUTION_HISTORY.md` is maintained by the Integrator, not by parallel Workers/Execution Orchestrators.

Record both successful and useful failed/rejected attempts. Each entry should capture:

- date;
- release/task/issue;
- executor client/model and any Hermes Delegates/fallbacks or Codex root/Worker/Reviewer attribution when known;
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

If Codex orchestrates, preserve runtime-reported root/Worker/Reviewer attribution when known.

That history is useful for later model benchmarks and the eventual story of how the project was built.

## 10. Release integration and UAT

`docs/R01_OWNER_UAT.md` is the historical Owner checklist for R01. Future releases should use their own release-specific UAT checklist/issue rather than treating the R01 checklist as current by default.

When all planned tasks for a release are integrated:

1. Integrator reviews the complete integration diff against the release spec.
2. Automated full release checks pass.
3. Owner UAT/preview runs from its explicitly assigned Owner-only checkout, using a disposable private runtime restored/cloned from the accepted Stable recovery point when real owner evidence is required; Stable itself is not the candidate sandbox.
4. Live/provider/device probes required by that release are performed or explicitly remain `UNVERIFIED` if allowed by the spec.
5. Integrator resolves findings in dedicated task branches, not by ad-hoc edits in UAT checkout.
6. Integrator opens/reviews integration -> `main` PR.
7. Accepted release is merged to `main`.
8. Exact post-merge `main` CI is checked and canonical `main` is read back.
9. The Owner canonical checkout is fast-forwarded to canonical `main` by the Owner when convenient; GitHub remains canonical.
10. Release documentation/history is synchronized.
11. The completed integration branch is no longer used as the next release baseline; create the next release integration branch from current `main`.

## 11. Benchmark / A-B tasks

When intentionally comparing models on the same task:

- pin one exact baseline;
- give each candidate a separate branch/workspace;
- candidates do not read/copy one another before completion;
- compare actual diffs/tests/evidence, not prose confidence;
- log model, timing if known, candidate SHA, result and Integrator verdict in Execution History.

Benchmark candidates are not automatically merged; the Integrator selects or synthesizes the accepted approach.

## 12. Current Codex and future provider automation

Codex `$delivery-loop` is now a supported execution mode under `docs/AGENT_ORCHESTRATION.md`.

Later we may automate issue pickup, Worker/Reviewer bots and integration inside Hermes or another provider-neutral orchestration layer. The same contracts remain:

- issue is authority;
- isolated workspace/branch per writer;
- Delegates cannot self-accept;
- final Integrator gate remains explicit;
- execution history records the delegation chain;
- private Owner runtime remains outside bot workspaces.

Automation may remove manual message shuttling; it must not remove accountability or evidence.

## 13. CI evidence and complete-suite gates

The CI workflow keeps both `push` and `pull_request` coverage. Every qualifying
candidate gate runs the complete pytest collection and suite through the three
ordinary serial Linux lanes in `ci/test-lanes.json`. The same checked-in
manifest is the only file-assignment source for local and CI invocation. An
independent unrestricted collection must equal the exact disjoint multiset
union of lane nodeids, including parametrizations and duplicate multiplicity.
Unassigned, overlapping, stale or empty assignments fail closed. Selectors,
deselections, unreviewed skips/xfails and automatic failure retries are not a
way to reduce the gate.

Each lane retains its exact collection and outcome inventory plus the checked-
out commit/tree, event/ref, PR base/head identities when present, manifest and
selection digests, command, lockfile digest, Python/uv/runner metadata, pytest
output, JUnit XML, status, and built-in setup/call/teardown duration evidence.
Missing, malformed, contradictory, interrupted or wrong-provenance evidence is
incomplete, never successful evidence. The final stable `checks` job runs under
`if: always()` and requires explicit success plus complete matching evidence
from quality and all three lanes.

| Lane | Tested ref | Cancellation scope | Required evidence | Evidence invalidated by |
| --- | --- | --- | --- | --- |
| Task push | task branch SHA | Same task branch only | Exact checkout, complete lane union, timing/JUnit, metadata | Changed tree/config/lock/manifest/selection |
| PR event | PR merge ref plus PR head SHA | Same PR number only | Same evidence, with merge checkout distinct from head | Any changed candidate/configuration |
| Integration push | integration SHA | No task/PR cancellation | Exact integration checkout and complete gate | New integration commit |
| Main push | main SHA | No task/PR cancellation | Exact post-main checkout and complete gate | New main commit |

Concurrency is lane-scoped: PR runs share only their PR number, task-branch
pushes share only their task ref, and integration/main/other refs do not opt in
to cancellation. A PR merge ref's checked-out `HEAD` is recorded separately
from the PR head SHA. A canceled, timed-out or superseded run has no complete
evidence for its SHA.

Use one full remote candidate gate after frozen code stabilizes, then the exact
post-integration and post-main gates owned by the Integrator. Run a full local
suite when the issue or risk requires it; do not repeat an unchanged full suite
because polling or a log view was lost. Timing evidence is for finding material
fixture/setup/test costs and environment effects, not for asserting an
unproven root cause. Once only small, legitimate residual costs remain, stop
optimizing this maintenance track and report them for a separately scoped task.

Local contract checks use the same manifest:

```text
uv run python scripts/ci_test_lanes.py validate-manifest
uv run python scripts/ci_test_lanes.py collect --output-dir <evidence-dir>
uv run python scripts/ci_test_lanes.py run-lane --lane <lane> --output-dir <evidence-dir> --basetemp <external-temp-dir>
uv run python scripts/ci_test_lanes.py verify-lane --lane <lane> --output-dir <evidence-dir>
```

`uv run pytest` remains the unrestricted serial diagnostic/control command; it
is not a permanent fourth per-candidate CI suite.

### Stabilize before a full gate

For a shared DB/session, serialization, restore or other cross-cutting primitive, map its direct consumers and failure/lifecycle boundaries before the expensive gate. Cover those boundaries with focused regressions, including known failure clusters and the actual production entry points. Review an unresolved contract early when warranted; this is not an extra mandatory review for every small task or a replacement for final independent review.

Finish formatting/lint fixes and focused tests before starting the full suite. Freeze its source, relevant configuration and dependencies until it finishes; do not run a formatter or another writer against the candidate in parallel. If a full suite fails, preserve its failures, diagnose and rerun the failed nodes plus the affected contract tests first. Run the required complete gate after the fixes stabilize, not as the next diagnostic command after every change.

Before any repeat record the previous evidence, what changed and the concrete unresolved risk/gate. A changed commit SHA, lost polling session or desire for extra confidence alone is not a reason. A nonsemantic-only edit can reuse evidence only where policy permits and its exact diff is proven; a source-changed or interrupted record is never silently relabeled passed. Keep stricter issue/CI/independent-review/UAT requirements. There is no blanket numeric cap that waives a required full gate.

Readiness means an actual writable, short external temp/cache and resolved toolchain plus an appropriate small check, not only a path/dry-run check. Once an infrastructure fault is known, fix its conditions before another expensive suite; do not weaken the tested safety contract.
