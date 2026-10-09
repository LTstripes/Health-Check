# Development Process

Ordinary development, verification, integration and release procedure. [AGENTS.md](../AGENTS.md) owns universal boundaries/roles; [Model Routing](MODEL_ROUTING.md) owns risk-based review and proposals. Read the sections relevant to the task. The detailed CI reference at the end is for gate/CI work, not a mandatory preflight for every edit.

## 1. Core operating model

1. Integrator records the outcome, boundaries, assignment and necessary acceptance checks in an issue.
2. One Worker uses its assigned isolated branch/workspace and pinned base; investigates and implements within scope without repeated approval.
3. Worker runs proportional checks, stabilizes the candidate, pushes the authorized branch and returns the [completion report](../AGENTS.md#completion-reporting).
4. Required Reviewer and Integrator inspect actual diff/contract/evidence; add focused checks for gaps, not duplicate full suites by role.
5. Integrator accepts, requests fixes or rejects; integrates only after required gates, then records a concise linked outcome.
6. Release integration and genuinely private/device UAT use the separate [release gate](#10-release-integration-and-uat).

Explicit requirements of ongoing tasks remain in force. A new default does not silently amend an accepted contract/assignment.

### 1.1 Owner execution intent

A named implementation client means a single Worker by default. Honor the Owner's choice. A task series is an ordering proposal, not automatic queue authorization. Client/queue activation examples are maintained only in [Agent orchestration](AGENT_ORCHESTRATION.md#mode-a--manual--brokered-execution).

### 1.2 Codex `$delivery-loop` route

Only explicit orchestration uses [Agent orchestration](AGENT_ORCHESTRATION.md) for queue/delegation/remediation mechanics. Ordinary tasks and independent reviews do not load that protocol.

## 2. Branch strategy

### `main`

Only canonical accepted/stable history and release source. Workers never write to it; Integrator-controlled integration is explicit.

### Release integration branch

For a multi-task release, Integrator creates one `integration/<release>` from then-current main. It is staging, not a second source of truth. Task PRs target it; the completed release is promoted through an integration-to-main PR. A deliberately small standalone task may target main through its own PR.

After release, the old integration branch is historical/staging-only; start the next release from the new canonical main. Accepted-but-held work is not automatically merge-ready after a freeze. Reconcile its semantic delta/lineage and required gates against the current target, preserving migration order and accepted behavior rather than blindly merging old stacks.

### Task branches

Use the assigned `task/<issue>-<slug>` at the exact specified baseline. A Worker commits/pushes only that branch; Integrator creates PRs by default. Push CI does not require a Worker-created PR. Other Git permissions remain in [AGENTS.md](../AGENTS.md#git-ownership).

### Parallel work

One isolated task needs no launch-compatibility form. When actual dependencies/shared contracts or parallel proposals exist, Integrator records a short decision in the issue: ready dependency/pinned interface, common artifact owner, separate boundaries and safe order. Use a table only when useful for a task set.

Parallel implementation requires explicit Owner opt-in and compatible scopes. Check shared/new modules, exports, schema/migrations, DTOs and version/evidence fields; separate worktrees alone do not establish independence. Dependent consumers start after integration unless an explicit stable fixture/contract and safe baseline strategy are assigned. Unresolved ownership/dependency conflicts block the affected launch; queue continuation follows its explicit contract.

Workers stay pinned while implementing. Integrator decides whether a candidate merges cleanly or needs one refresh/retest pass; overlapping files, schema/security/network/canonical-data changes normally require refresh. Low-risk independent work need not chase each new target SHA. Never reset/rebase another task's workspace/branch.

## 3. Local workspace layout

The current Owner Windows paths are maintained in [Owner machine layout](OWNER_MACHINE_LAYOUT.md). Use those roots for new Health-Check assignments unless the Integrator explicitly assigns a temporary exception. Record the exact task workspace and resolve missing/conflicting protected-location assignments before writing; portable process policy remains role-based rather than duplicating the absolute path table here.

Protected location roles are unchanged:
- Owner canonical checkout: accepted-main read/run location, not agent development; do not inspect/switch/reset without an explicit Owner-controlled assignment.
- Owner preview/UAT checkout: Owner-only candidate/live gates, not development.
- Stable private runtime: durable evidence and verified backup source outside Git; never reset/repurpose for testing.
- Per-client development root: separate assigned task clones/worktrees, not a shared mutable checkout switched between sessions.

Real datasets, credentials and backups stay outside code workspaces and synthetic fixtures.
Assigned Owner analysis may read relevant real data and show it in the authorized AI
conversation under [Owner data workflow](OWNER_DATA_WORKFLOW.md), without per-read
approval or mandatory value masking. Candidate UAT uses an isolated approved clone.

## 4. Workspace creation rules for workers

A Worker may create/fetch/checkout only its explicitly assigned task directory below the authorized client root. Do not inspect protected locations or unrelated siblings, reuse another task directory, create other roots, link private data or switch/reset another session's tree. Concurrent writers use separate assigned trees; details of client delegation belong only in the relevant adapter.

## 5. Task definition

Before implementation, the issue contains the outcome and scope, relevant contract/notes, assigned branch/workspace/exact base/target, observable acceptance criteria and necessary checks. The Integrator records separate complexity/risk and the selected route. The [implementation template](../.github/ISSUE_TEMPLATE/implementation_task.md) is a compact aid, not a requirement to fill irrelevant fields.

Add dependency/parallel/early-contract/queue details only when applicable. For an isolated task, do not write compatibility tables or N/A sections. Scope changes are recorded in the issue or explicit Integrator note before implementation; a launch prompt is not another specification.

## 6. Launch prompt convention

Use the [Owner task proposal](MODEL_ROUTING.md#owner-task-proposal): short Russian explanation/model recommendation outside a copyable locator prompt. The prompt gives the issue/note, role, base/target, branch/workspace and authorized delivery. Resolve safety-critical omissions; omit unused process fields rather than expanding every launch into a checklist.

## 7. Worker / Orchestrator completion -> Integrator review

The handoff is context, not proof. Inspect exact base/candidate/ref, actual diff and scope, contract compliance, check evidence and limitations, protected-data boundaries and any affected migrations/security/semantics/docs. Determine whether the target moved materially and whether required independent review actually ran.

Verdicts: **ACCEPT** (integrated or explicitly accepted-and-held with remaining gate), **FIXES REQUIRED** (concrete findings on this task), or **REJECT** (not integrated, reason retained). Local queue verdicts do not replace this decision.

Reviewers do not silently repair the candidate. Small explicit Integrator-owned documentation/metadata commits are permitted; behavioral fixes normally return to a Worker. Independent review is not claimed for self-authored work.

### Verification by change

| Change / stage | Necessary work |
| --- | --- |
| Docs/process-only | Relevant content/contract consistency, links/anchors and diff/scope/privacy check; no manual product-wide pytest, browser or device gate solely for prose |
| Routine code/tests | Focused regressions for the change and affected consumers while iterating; required final CI on the stabilized exact candidate |
| Schema/replay/eligibility/statistics or cross-layer risk | Before broad work, map the material contract to actual input/API boundaries and negative acceptance cases; test production entry points where practical; early contract review only for identified unresolved risk |
| Independent Reviewer | Inspect pinned candidate, actual contract and existing evidence; add tests for concrete gaps, not an automatic second complete run |
| Integration/release | Validate the actual integrated result and required exact integration/main CI; perform genuinely necessary Owner UAT separately |

A full local suite is conditional on the issue or concrete risk, not an automatic addition to every remote CI run. No repeated full suite just because a different participant is reviewing, polling was lost or extra reassurance is desired. Existing exact-candidate/PR/integration/main gates remain governed by [section 13](#13-ci-evidence-and-complete-suite-gates); no cross-attempt mixing or relabeling old evidence as new.

Classify a failed run before repeating: code, tests, environment or unknown. Unchanged source plus red CI does not prove a product defect; a later green result does not explain the failure. Preserve it, fix identified conditions and use focused diagnosis before the required complete gate. Do not inflate timeouts, exclude failures or weaken assertions to obtain a pass.

On the shared Owner development machine, use one primary Worker and one heavyweight local verification process at a time across projects. At most two independent writers may run when explicitly authorized, with compatible scope, separate trees and available resources; do not kill sibling/Owner processes. CI gates are unaffected by this local resource limit.

### Quick local checks

In the assigned isolated workspace, establish the locked toolchain and use focused checks. Before commands that can access runtime, set `HEALTHCHECK_DATA_DIR` to an assigned external **synthetic** directory and use an external pytest temp path; never fall back to Owner/private defaults.

```text
uv sync --locked
uv run ruff check .
uv run pytest <affected-test-paths> --basetemp <external-synthetic-temp-dir>
```

For migration work, also use `uv run python -m healthcheck.db.migration_guard`. Exact CI lane commands are in section 13. These are command examples, not instructions to run every check for a documentation edit.

## 8. Engineering history — everything useful is retained

Detailed task scope, attempts, exact candidates/checks/review/integration and meaningful failures live in the issue/PR. Integrator-maintained `EXECUTION_HISTORY_CURRENT.md`/`EXECUTION_HISTORY.md` keep concise dated outcomes and links, not duplicate full reports. Keep useful rejected/abandoned attempts; do not rewrite historical evidence when a later attempt succeeds.

### Durable decision split

Issue: task authority/evidence. Architecture/decision docs or ADR: a durable contract change. Roadmap: release sequence. Backlog: uncommitted ideas. README: product overview, stable usage and links, not a running task-status ledger. Release notes describe product changes. Update a second document only when its own meaning became stale; do not synchronize the same report across all of them. Git retains old policy versions; do not add archival copies merely to preserve replaced prose.

## 10. Release integration and UAT

At release, review the integrated diff against the active spec; pass full automated release checks; run the required Owner-only preview/device/provider gates from a disposable verified Stable backup/restore clone. Do not use old release checklists as current by default; use that release's issue/checklist. Unperformed permitted live gates stay UNVERIFIED, never implicitly passed.

Resolve findings in dedicated task branches, not ad-hoc UAT edits. After accepted integration-to-main PR merge, read back canonical main and exact post-merge CI, record release/UAT outcome and start subsequent release work from this new main. GitHub publication does not update/restart Owner-local code. Owner fast-forwards the clean operation checkout only when relevant processes are idle and the update is appropriate.

### Resuming Owner analysis and UAT

Use the [offline/runtime distinction and evidence receipt](OWNER_DATA_WORKFLOW.md#offline-evidence-and-runtime-continuation).
Do not require a running UI for an offline clone audit. For runtime checks, verify
current process/code/profile binding; retain completed steps and resume only after
checking the dependencies of the next step. Missing human UAT is not a reason to
rerun successful synthetic tests. Use atomic physical-checkout ownership before
local writing/verification, not just different branch names in a shared tree.

## 12. Current Codex and future provider automation

Automation may remove manual message shuttling, not issue authority, workspace/data boundaries, evidence or Integrator acceptance. Optional queue/delegation protocol lives only in [Agent orchestration](AGENT_ORCHESTRATION.md).

## 13. CI evidence and complete-suite gates

The CI workflow keeps both `push` and `pull_request` coverage. Non-delegated pushes and
code-mode PR candidate gates run the complete pytest collection and suite through
the three ordinary serial Linux lanes in `ci/test-lanes.json`. The same checked-in
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

Dependency advisories are outside ordinary `quality` and `checks`.
`.github/workflows/dependency-audit.yml` runs `scripts/dependency_audit.py`
for pull requests and pushes to `main` that change dependency or audit policy
files, and for manual dispatch. Advisory findings and scanner, network, or
tool failures both fail that workflow, and it uploads evidence either way.
Docs-only PRs and unrelated code PRs do not run that network audit. Ordinary
CI stays the test and provenance gate; a dependency change is accepted only
when both gates pass. The Garmin git pin remains an explicit unaudited
coverage limit, not an audited package. The baseline reproduction and local
entrypoint are recorded in `docs/DEPENDENCY_SECURITY.md`.

Stage A permits a narrow **docs-only PR** outcome. `scripts/ci_docs_gate.py`
contains the explicit individual-path allowlist; README/build metadata, new files,
fixtures, runtime inputs and unlisted Markdown require full CI. Only modifications
of existing `100644` prose qualify. The classifier consumes the complete raw Git
diff, verifies event base/head/merge commits, trees and exact merge parents, and
requires the merge tree to equal the PR head tree. This deliberately sends base
movement or merge-resolution ambiguity to full CI. Mixed, unknown, rename/delete,
mode, symlink/submodule, classifier/workflow and config/dependency changes also
require full CI. No labels, PR descriptions or path-ignore triggers authorize skips.

The classifier retains `docs-decision-<run>-<attempt>/decision.json`, binding
event/ref/base/head/checkout, all trees, both diff digests and classifier/workflow
digests. The docs job checks UTF-8 prose, repository-local link existence and
credential patterns without executing Markdown or fetching URLs, and retains
`docs-outcome-<run>-<attempt>/outcome.json`. Credential pattern detection is a
bounded automated privacy guard, not proof that arbitrary prose contains no
private information; the normal documentation/privacy review still applies.
Final `checks` independently recomputes the decision and document checks and
requires exactly these two matching artifacts, successful classifier/docs jobs,
and explicit skips of quality, Linux lanes and Windows. Missing, stale, foreign,
mixed or contradictory evidence and unexpected failure/cancellation/skip fail.
Its terminal success explicitly says **docs-only; pytest and Windows were not run**.
Classifier errors fall back to full CI; they never authorize missing full evidence.
Full-mode evidence/verifiers, push events and same-attempt completeness remain
unchanged for every non-delegated event.

Stage B permits a task push to delegate only to a current same-repository open
PR targeting main, with the exact task head and an exact merge checkout tree
equal to the task-head tree. `scripts/ci_event_route.py` records head/base/merge
commits and trees separately. The PR classifier records its actual checkout in
`event-decision-<run>-<attempt>/decision.json`; API head SHA alone is insufficient.
The push selects the newest corresponding PR run and may wait up to seven minutes
for that exact run/attempt, without rerunning jobs. Delegation requires successful
classifier, quality, all three Linux lanes, Windows (including janitor), and final
`checks`, with docs skipped, plus matching checkout routing identity from that
attempt. The successful PR `checks` remains the authority for the complete
same-attempt evidence set; the push neither combines nor republishes those results.
Head/base/merge/PR/run identities are checked again after reading the evidence.

No PR/run at lookup, ambiguity, stale/foreign/closed PR, changed merge/base/head,
different tree, lookup error, missing/expired identity, docs-only PR, failed,
cancelled or superseded run/attempt, or bounded-wait expiry keeps the push full.
A delegated push skips its own quality/lanes/Windows and `checks`; its routing
summary explicitly says it is **not a complete candidate gate** and identifies
the PR run/attempt. Main/integration/other pushes and Stage A docs-only PR routing
remain unchanged. A later changed candidate must obtain its own complete gate;
delegation never makes a failed PR successful or erases earlier failures (#243).

Measured rollout results, live proofs and accepted limitations for #251/#246/#243/#242 are recorded in [CI Optimization Closeout — 2026-10-04](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md). No further CI optimization stage is implied by that closeout.

| Lane | Tested ref | Cancellation scope | Required evidence | Evidence invalidated by |
| --- | --- | --- | --- | --- |
| Task push | task branch SHA | Same task branch only | Full gate, or explicit non-gate delegation to a complete exact-tree PR run/attempt | Changed tree/config/lock/manifest/selection or PR identity |
| PR event | PR merge ref plus PR head SHA | Same PR number only | Full code-mode set or verified docs-only decision/outcome; merge checkout distinct from head | Any changed candidate/configuration |
| Integration push | integration SHA | No task/PR cancellation | Exact integration checkout and complete gate | New integration commit |
| Main push | main SHA | No task/PR cancellation | Exact post-main checkout and complete gate | New main commit |

Concurrency is lane-scoped: PR runs share only their PR number, task-branch
pushes share only their task ref, and integration/main/other refs do not opt in
to cancellation. A PR merge ref's checked-out `HEAD` is recorded separately
from the PR head SHA. A canceled, timed-out or superseded run has no complete
evidence for its SHA.

The supported recovery is **Re-run all jobs**, after diagnosing the failure.
Partial reruns may diagnose an individual job, but do not qualify as a candidate
gate. `checks` downloads only its current run/attempt and explicitly requires
exactly quality, three Linux lanes and Windows smoke from that attempt before
validating their contents. It never falls back to prior-attempt artifacts, even
when their SHA matches. Missing, expired or mixed-attempt evidence fails with a
`Re-run all jobs` instruction. A complete later attempt still must satisfy every
job result and SHA/tree/event/config/lock/manifest/selection check. This is a
fail-closed full-rerun-only contract, not cross-attempt aggregation or permission
to retry repeatedly until green.

Retaining earlier artifacts alone does not establish the authoritative outcome
of rerun source jobs. The existing Linux contract also binds all three lanes to
the quality attempt, including command/report paths. Cross-attempt selection
would need a separate verified source-job/attempt contract; the current workflow
deliberately keeps one complete same-attempt set.

Windows smoke retains the native taskkill exit code and output plus the verified
root/descendant identities (PID, name, command line and creation time). A single
root-scoped `/PID <root> /T /F` call is followed by bounded checks of every
captured tree member, including children whose parent has already exited.
Native exit 0 is `terminated`. Exit 255 can be `exited-during-termination` only
when every native error is the English runner diagnostic `There is no running
instance of the task.` for a captured owned PID, and every captured identity is
absent or proven reused by a successful query with a trustworthy different
CreationTime, and the native reported PID set equals the captured tree. The
exact English transcript grammar and complete line consumption remain mandatory.
Post-termination observations classify each captured root/child independently
as absent, same-identity-alive, reused, or unknown. Reuse evidence retains the
captured and observed UTC DateTime ticks plus observed PID/name/command line
and query result. A generic identity-change list is never reuse proof. Same CreationTime with
changed non-empty name/command line remains an identity failure. During bounded
post-termination polling, a successful query with the same trustworthy
CreationTime but transiently missing Name/CommandLine is still the captured
instance and therefore remains a non-success `same-identity-alive` state to poll
again; if that state survives to the deadline/final evidence it fails. Invalid
or missing CreationTime, unknown queries and surviving captured children fail.
Root reuse does not
stop checks of captured children or authorize traversal from the reused PID.
These observations do not provide process-handle/object-bound guarantees.
Unrecognized/localized diagnostics and other exit codes fail. Both ports must
also be closed and the external synthetic runtime removed. No second kill or
process-name-wide operation is used. A root absent before the ownership
snapshot is unproven and fails. Artifact schema 3 requires this lifecycle
evidence, both termination and final observations for every captured PID, and
rejects all identity-change entries. Historical artifacts that
discarded native output cannot retrospectively prove this diagnostic or be
waived under the new contract.

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
