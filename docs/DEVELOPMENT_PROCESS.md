<a id="book--development-process"></a>
# Development Process

This book owns task execution, risk, review, verification and documentation upkeep.
[AGENTS](../AGENTS.md) owns universal authority and boundaries. Load the chapter
needed for the assignment; optional clients and orchestration are not prerequisites.

<a id="book--1-core-operating-model"></a>
## 1. Core operating model

1. Integrator records the outcome, boundaries, assignment and necessary acceptance checks in an issue.
2. One Worker uses its assigned isolated branch/workspace and pinned base; investigates and implements within scope without repeated approval.
3. Worker runs proportional checks, stabilizes the candidate, pushes the authorized branch and returns the [completion report](../AGENTS.md#completion-reporting).
4. Required Reviewer and Integrator inspect actual diff/contract/evidence; add focused checks for gaps, not duplicate full suites by role.
5. Integrator accepts, requests fixes or rejects; integrates only after required gates, then records a concise linked outcome.
6. Release integration and genuinely private/device UAT use the separate [release gate](#10-release-integration-and-uat).

Explicit requirements of ongoing tasks remain in force. A new default does not silently amend an accepted contract/assignment.

<a id="book--11-owner-execution-intent"></a>
### 1.1 Owner execution intent

A named implementation client means a single Worker by default. Honor the Owner's choice. A task series is an ordering proposal, not automatic queue authorization. Client/queue activation examples are maintained only in [Agent orchestration](#orchestration--mode-a--manual--brokered-execution).

<a id="book--12-codex-delivery-loop-route"></a>
### 1.2 Codex `$delivery-loop` route

Only explicit orchestration uses [Agent orchestration](#orchestration) for queue/delegation/remediation mechanics. Ordinary tasks and independent reviews do not load that protocol.

<a id="book--2-branch-strategy"></a>
## 2. Branch strategy

<a id="book--main"></a>
### `main`

Only canonical accepted/stable history and release source. Workers never write to it; Integrator-controlled integration is explicit.

<a id="book--release-integration-branch"></a>
### Release integration branch

For a multi-task release, Integrator creates one `integration/<release>` from then-current main. It is staging, not a second source of truth. Task PRs target it; the completed release is promoted through an integration-to-main PR. A deliberately small standalone task may target main through its own PR.

After release, the old integration branch is historical/staging-only; start the next release from the new canonical main. Accepted-but-held work is not automatically merge-ready after a freeze. Reconcile its semantic delta/lineage and required gates against the current target, preserving migration order and accepted behavior rather than blindly merging old stacks.

<a id="book--task-branches"></a>
### Task branches

Use the assigned `task/<issue>-<slug>` at the exact specified baseline. A Worker commits/pushes only that branch; Integrator creates PRs by default. Push CI does not require a Worker-created PR. Other Git permissions remain in [AGENTS.md](../AGENTS.md#git-ownership).

<a id="book--parallel-work"></a>
### Parallel work

One isolated task needs no launch-compatibility form. When actual dependencies/shared contracts or parallel proposals exist, Integrator records a short decision in the issue: ready dependency/pinned interface, common artifact owner, separate boundaries and safe order. Use a table only when useful for a task set.

Parallel implementation requires explicit Owner opt-in and compatible scopes. Check shared/new modules, exports, schema/migrations, DTOs and version/evidence fields; separate worktrees alone do not establish independence. Dependent consumers start after integration unless an explicit stable fixture/contract and safe baseline strategy are assigned. Unresolved ownership/dependency conflicts block the affected launch; queue continuation follows its explicit contract.

Workers stay pinned while implementing. Integrator decides whether a candidate merges cleanly or needs one refresh/retest pass; overlapping files, schema/security/network/canonical-data changes normally require refresh. Low-risk independent work need not chase each new target SHA. Never reset/rebase another task's workspace/branch.

<a id="book--3-local-workspace-layout"></a>
## 3. Local workspace layout

The current Owner Windows paths are maintained in [Owner machine layout](OWNER_OPERATIONS.md#machine-layout). Use those roots for new Health-Check assignments unless the Integrator explicitly assigns a temporary exception. Record the exact task workspace and resolve missing/conflicting protected-location assignments before writing; portable process policy remains role-based rather than duplicating the absolute path table here.

Protected location roles are unchanged:
- Owner canonical checkout: accepted-main read/run location, not agent development; do not inspect/switch/reset without an explicit Owner-controlled assignment.
- Owner preview/UAT checkout: Owner-only candidate/live gates, not development.
- Stable private runtime: durable evidence and verified backup source outside Git; never reset/repurpose for testing.
- Per-client development root: separate assigned task clones/worktrees, not a shared mutable checkout switched between sessions.

Real datasets, credentials and backups stay outside code workspaces and synthetic fixtures.
Assigned Owner analysis may read relevant real data and show it in the authorized AI
conversation under [Owner data workflow](OWNER_OPERATIONS.md#owner-data-boundary), without per-read
approval or mandatory value masking. Candidate UAT uses an isolated approved clone.

<a id="book--4-workspace-creation-rules-for-workers"></a>
## 4. Workspace creation rules for workers

A Worker may create/fetch/checkout only its explicitly assigned task directory below the authorized client root. Do not inspect protected locations or unrelated siblings, reuse another task directory, create other roots, link private data or switch/reset another session's tree. Concurrent writers use separate assigned trees; details of client delegation belong only in the relevant adapter.

<a id="book--5-task-definition"></a>
## 5. Task definition

Before implementation, the issue contains the outcome and scope, relevant contract/notes, assigned branch/workspace/exact base/target, observable acceptance criteria and necessary checks. The Integrator records separate complexity/risk and the selected route. The [implementation template](../.github/ISSUE_TEMPLATE/implementation_task.md) is a compact aid, not a requirement to fill irrelevant fields.

Add dependency/parallel/early-contract/queue details only when applicable. For an isolated task, do not write compatibility tables or N/A sections. Scope changes are recorded in the issue or explicit Integrator note before implementation; a launch prompt is not another specification.

<a id="book--6-launch-prompt-convention"></a>
## 6. Launch prompt convention

Use the [Owner task proposal](#c4--critical--architecture--owner-task-proposal): short Russian explanation/model recommendation outside a copyable locator prompt. The prompt gives the issue/note, role, base/target, branch/workspace and authorized delivery. Resolve safety-critical omissions; omit unused process fields rather than expanding every launch into a checklist.

<a id="book--7-worker--orchestrator-completion---integrator-review"></a>
## 7. Worker / Orchestrator completion -> Integrator review

The handoff is context, not proof. Inspect exact base/candidate/ref, actual diff and scope, contract compliance, check evidence and limitations, protected-data boundaries and any affected migrations/security/semantics/docs. Determine whether the target moved materially and whether required independent review actually ran.

Verdicts: **ACCEPT** (integrated or explicitly accepted-and-held with remaining gate), **FIXES REQUIRED** (concrete findings on this task), or **REJECT** (not integrated, reason retained). Local queue verdicts do not replace this decision.

Reviewers do not silently repair the candidate. Small explicit Integrator-owned documentation/metadata commits are permitted; behavioral fixes normally return to a Worker. Independent review is not claimed for self-authored work.

Keep one authoritative current task status in the active issue or designated
tracker. Link concise Worker delivery, required independent review and Integrator
acceptance receipts there; the PR summary links to that status.
Receipts retain their exact candidate/check scope and remaining gates; link them
instead of copying their evidence into each status update or closeout. A changed
candidate invalidates affected evidence, not the record of the earlier attempt.

<a id="book--verification-by-change"></a>
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

<a id="book--quick-local-checks"></a>
### Quick local checks

In the assigned isolated workspace, establish the locked toolchain and use focused checks. Before commands that can access runtime, set `HEALTHCHECK_DATA_DIR` to an assigned external **synthetic** directory and use an external pytest temp path; never fall back to Owner/private defaults.

```text
uv sync --locked
uv run ruff check .
uv run pytest <affected-test-paths> --basetemp <external-synthetic-temp-dir>
```

For migration work, also use `uv run python -m healthcheck.db.migration_guard`. Exact CI lane commands are in section 13. These are command examples, not instructions to run every check for a documentation edit.


<a id="engineering-history"></a>

<a id="engineering-history--engineering-history-and-durable-decisions"></a>
## Engineering history and durable decisions


Detailed scope, attempts, exact candidates, checks, review, integration and meaningful
failures live in the issue/PR. The Integrator keeps concise dated linked outcomes in
[Wiki recent outcomes](PROJECT_WIKI.md#recent-outcomes). Existing execution-history
volumes are frozen archives, not journals to append. Preserve useful rejected and
abandoned evidence; a later success does not rewrite an earlier failure.


<a id="durable-decision-split--durable-decision-split"></a>
### Durable decision split

The five canonical homes and their maintenance checklist are below. The issue owns
task authority and exact evidence; Wiki owns the dated current engineering entry
point. Live GitHub is authoritative for refs and issue/PR states. README is a short
bootstrap and front door, not a status ledger. Update another home only when its
own meaning changes. Git preserves replaced policy; do not make an archival copy
merely because prose was edited. Release notes explain product changes without
copying engineering reports.

<a id="durable-decision-split--10-release-integration-and-uat"></a>
## 10. Release integration and UAT

At release, review the integrated diff against the active spec; pass full automated release checks; run the required Owner-only preview/device/provider gates from a disposable verified Stable backup/restore clone. Do not use old release checklists as current by default; use that release's issue/checklist. Unperformed permitted live gates stay UNVERIFIED, never implicitly passed.

Resolve findings in dedicated task branches, not ad-hoc UAT edits. After accepted integration-to-main PR merge, read back canonical main and exact post-merge CI, record release/UAT outcome and start subsequent release work from this new main. GitHub publication does not update/restart Owner-local code. Owner fast-forwards the clean operation checkout only when relevant processes are idle and the update is appropriate.

<a id="durable-decision-split--resuming-owner-analysis-and-uat"></a>
### Resuming Owner analysis and UAT

Use the [offline/runtime distinction and evidence receipt](OWNER_OPERATIONS.md#offline-runtime-evidence--offline-evidence-and-runtime-continuation).
Do not require a running UI for an offline clone audit. For runtime checks, verify
current process/code/profile binding; retain completed steps and resume only after
checking the dependencies of the next step. Missing human UAT is not a reason to
rerun successful synthetic tests. Use atomic physical-checkout ownership before
local writing/verification, not just different branch names in a shared tree.

<a id="durable-decision-split--12-current-codex-and-future-provider-automation"></a>
## 12. Current Codex and future provider automation

Automation may remove manual message shuttling, not issue authority, workspace/data boundaries, evidence or Integrator acceptance. Optional queue/delegation protocol lives only in [Agent orchestration](#orchestration).


<a id="checkout-ownership"></a>

<a id="checkout-ownership--one-writer-review-readiness-and-evidence-continuation"></a>
## One writer, review readiness and evidence continuation

<a id="checkout-ownership--one-writer-per-physical-checkout"></a>
### One writer per physical checkout

Before editing or local verification, claim the canonical physical checkout with
the current chat/task identity using the available local ownership helper. Check
the claim before commit/push and release it at handoff or cancellation. Concurrent
claim acquisition must be atomic. Never steal a claim because a timer elapsed or
adopt another chat's identity. A paused task retains ownership until handed off.
If occupied, use a fresh authorized checkout; read-only remote review can continue.
The helper is cooperative coordination, not an OS lock against arbitrary editors.
If the helper is unavailable, use a freshly created uniquely named checkout and
record its owner once; do not turn missing tooling into repeated approval requests.
This fallback never permits resuming/reusing an enrolled checkout. Such unmanaged
clones remain preserved by automatic cleanup. For managed standalone clones use
the [workspace lifecycle protocol](OWNER_OPERATIONS.md#workspace-lifecycle): Create/Bind before work,
Check the active claim before writing/verification, Pause while paused, Resume with
the current owner/ClaimId before further writes, and Complete only after delivery.
The matching helper and janitor share one mutex; loose completion/`released`
markers and elapsed time never release ownership. Legacy workspaces are not adopted.

<a id="checkout-ownership--review-and-proportional-verification"></a>
### Review and proportional verification

Read-only review preflight checks actual Git/source access, not just configured
permissions. Keep environment readiness, source identity and model findings distinct.
Receiving a final model message is not a review PASS. On setup/access failure, save
the diagnostic and repair the cause before one new preflight. Do not repeatedly
launch model reviews with the same broken environment or enlarge packets to disguise
missing source access. Required review remains required; retain useful prior findings.

Routine prose/UI work does not acquire a second reviewer, a full local suite or real
runtime UAT merely because an agent can imagine a risk. Apply the existing risk and
verification policies. Reuse applicable evidence with its original candidate/scope;
rerun only invalidated or missing checks, including explicitly required CI gates.

<a id="checkout-ownership--concrete-blockers"></a>
### Concrete blockers

Every STOP/approval request identifies the actual missing authority, conflicting
contract or reproducible failure and the smallest next action. General discomfort
about personal values is not a blocker. Continue independent authorized work.
Do not add mandatory report fields or new gates beyond what the task needs.

<a id="documentation-maintenance"></a>

<a id="documentation-maintenance--maintaining-the-five-books"></a>
## Maintaining the five books


| Information | Canonical home | Update trigger |
| --- | --- | --- |
| Purpose, user journeys, visual/interactions and health meaning | Product Vision | Accepted product/UX decision or changed delivered behavior |
| Schemas, time/provenance, source DTOs, algorithms, envelopes, versions and guards | Architecture | Accepted technical contract or implementation changes its meaning |
| Roles, task/risk/client procedure, review, CI, dependencies and this upkeep rule | Development Process | Accepted execution or verification policy changes |
| Setup, complete commands, action authority, backup/recovery and workspace operations | Owner Operations | Accepted operator procedure or operational consumer changes |
| Dated accepted-main state, installed Stable, human UAT, delivered/remaining work and decisions | Project Wiki | Integrator integration, verified local receipt, human observation or changed issue disposition |

Before editing, identify the governing home and inspect the accepted contract/code
and task evidence. Change the canonical rule once, preserving defaults, identities,
versions, budgets and exceptions. A move cannot introduce new semantics. Update
affected links, examples, client prompts and templates when their own meaning is
stale, including literal paths outside Markdown. Keep useful stable anchors.

After integration, update the one Wiki snapshot with date, accepted commit and
supporting evidence. Record installed-code proof and human UAT separately; a merge
does not deploy Stable or pass human UAT. Detailed attempts and receipts stay in the
issue/PR; link useful concise outcomes in Wiki. Existing archives are frozen.

Check links/fragments, scope, privacy and the routes for implementation, independent
review, an authorized Owner operation and selecting next work. Apply the required
exact-candidate gates; prose alone adds no manual product suite or provider calls.
Read command examples as data during docs validation.

Do not create a document per PR, slice or version, duplicate current status, or add
another reporting system. A new active document needs a distinct durable contract
or real consumer that cannot reasonably fit these five homes; record that concrete
reason and its canonical scope in the Integrator's task decision. Routine edits
need no extra form or repeated Owner approval.


<a id="ci-gates"></a>

<a id="ci-gates--ci-evidence-and-complete-suite-gates"></a>
## CI evidence and complete-suite gates

<a id="ci-gates--13-ci-evidence-and-complete-suite-gates"></a>
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
entrypoint are recorded in `docs/DEVELOPMENT_PROCESS.md#dependency-security`.

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

Measured rollout results, live proofs and accepted limitations for #251/#246/#243/#242 are recorded in [CI Optimization Closeout — 2026-10-04](archive/closeouts/CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md). No further CI optimization stage is implied by that closeout.

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

Local reuse of an already validated full code-mode gate is supported by
[`ci_evidence_receipt.py`](../scripts/ci_evidence_receipt.py), with adversarial and
real-validator coverage in [its tests](../tests/test_ci_evidence_receipt.py).
The trusted operator adapter first retains every original ZIP and its GitHub
digest, complete metadata and extracted bytes. `cold_verify` calls the unchanged
official validators and atomically publishes a versioned receipt outside that
bundle. The Integrator conveys its SHA256 separately; a receipt is not a signature.

`warm_reuse` requires that trusted pin, unchanged retained bytes, canonical Git
configuration and actual loaded verifier/adapter identities, plus fresh complete
authenticated run/attempt/jobs/artifacts/checkout/PR metadata. It performs no
downloads or official content-validator calls. Expired/deleted artifacts,
superseded attempts or PR identities, uncertainty, changed bytes/configuration,
unsafe paths and legacy unbound receipts reject reuse. Rejection is not a pass or
permission for implicit reruns, replacement receipts or another candidate's evidence.
The same-attempt, independent-review and pre-merge identity gates above still apply.
This first bounded slice covers full CI evidence only; reuse of prose/link outcomes
remains tracked in [#511](https://github.com/LTstripes/Health-Check/issues/511).
Documentation delta/privacy review is never replaced by a cached link result.

Windows smoke retains the native taskkill exit code, every raw output item and
verified root/descendant identities (PID, name, command line and CreationTime).
Only one root-scoped `/PID <root> /T /F` call is permitted after ownership
verification; an absent root before the snapshot is unproven and fails. No second
kill, process-name-wide operation or traversal from a reused PID is allowed.
Artifact schema 3 requires bounded post-termination and final observations for
every captured member, including children whose parent exited. Root reuse cannot
hide surviving children. Both ports must close and the external synthetic runtime
must be removed; DPAPI and a complete same-attempt evidence set remain mandatory.

Each captured identity must be absent or proven reused by a successful query with
a trustworthy different CreationTime. Evidence retains captured/observed UTC
DateTime ticks, observed PID/name/command line and query result. Generic
identity-change lists are not reuse proof; schema 3 rejects identity-change
entries. Unknown queries, invalid/missing CreationTime and surviving identities
fail. The same trustworthy CreationTime with transiently missing name/command line
remains non-success `same-identity-alive` during bounded polling and fails if it
survives to final evidence; changed non-empty fields with the same CreationTime
are an identity failure. These observations provide no process-handle/object-bound
guarantee. Reported parent text and role names constrain exception shape; the
coherent ownership snapshot and full identities remain the ownership proof.

Native exit 0 is `terminated`. Only the exact bounded exit-255 and separate
exit-128 exceptions can yield `exited-during-termination`, with all identity and
postconditions above still required. Complete raw-item consumption, exact English
diagnostics and captured PID coverage remain mandatory; no trimming, normalization,
localized/unrecognized output or other nonzero exit code is accepted. Executable
grammar, suffix/role/edge constraints and fixture matrices live in:

- [Test-Exit255LifecycleTranscript](../scripts/ci_windows_process.ps1#L183) and
  [Test-Exit128LifecycleTranscript](../scripts/ci_windows_process.ps1#L237).
- [Get-PostTerminationProcessObservation](../scripts/ci_windows_process.ps1#L294),
  [Invoke-RootProcessTreeTermination](../scripts/ci_windows_process.ps1#L344) and
  the independent [Windows artifact verifier](../scripts/ci_windows_smoke.py).
- [Workflow/evidence tests](../tests/test_ci_workflow.py),
  [PowerShell lifecycle tests](../tests/test_ci_windows_process.ps1) and
  [shared Python regressions](../tests/ci_windows_transcript_regressions.py).
- The exact [exit-255 fixtures](../tests/fixtures/ci_windows_exit255_transcripts.json)
  and [exit-128 fixtures](../tests/fixtures/ci_windows_exit128_transcripts.json),
  including retained source artifact identities and ZIP hashes.

The failed [#403 run](https://github.com/LTstripes/Health-Check/actions/runs/38229347233)
and [PR #415 run 38544069167, attempt 1](https://github.com/LTstripes/Health-Check/actions/runs/38544069167)
remain failures. Discarded native output cannot retrospectively prove a diagnostic;
native scheduling/exit-code and blank-item capture causes remain unproven.
Unreached DPAPI remains absent. Synthetic replay demonstrates recognition, not
native kill reproduction; a new complete exact-attempt gate including DPAPI is
required for a candidate.

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

<a id="ci-gates--stabilize-before-a-full-gate"></a>
### Stabilize before a full gate

For a shared DB/session, serialization, restore or other cross-cutting primitive, map its direct consumers and failure/lifecycle boundaries before the expensive gate. Cover those boundaries with focused regressions, including known failure clusters and the actual production entry points. Review an unresolved contract early when warranted; this is not an extra mandatory review for every small task or a replacement for final independent review.

Finish formatting/lint fixes and focused tests before starting the full suite. Freeze its source, relevant configuration and dependencies until it finishes; do not run a formatter or another writer against the candidate in parallel. If a full suite fails, preserve its failures, diagnose and rerun the failed nodes plus the affected contract tests first. Run the required complete gate after the fixes stabilize, not as the next diagnostic command after every change.

Before any repeat record the previous evidence, what changed and the concrete unresolved risk/gate. A changed commit SHA, lost polling session or desire for extra confidence alone is not a reason. A nonsemantic-only edit can reuse evidence only where policy permits and its exact diff is proven; a source-changed or interrupted record is never silently relabeled passed. Keep stricter issue/CI/independent-review/UAT requirements. There is no blanket numeric cap that waives a required full gate.

Readiness means an actual writable, short external temp/cache and resolved toolchain plus an appropriate small check, not only a path/dry-run check. Once an infrastructure fault is known, fix its conditions before another expensive suite; do not weaken the tested safety contract.

<a id="risk-and-routing"></a>

<a id="risk-and-routing--risk-capability-routing-and-task-proposals"></a>
## Risk, capability routing and task proposals

Integrator guidance for task proposals, capability selection and risk-based review. An already-assigned Worker needs its issue/contract, not this whole document. Roles are defined in [AGENTS.md](../AGENTS.md#roles); ordinary delivery/checks in [Development Process](#1-core-operating-model).

<a id="risk-and-routing--effort-and-coordination-choice"></a>
### Effort and coordination choice

Choose a model that comfortably handles the bounded contract and the lowest suitable reasoning setting. Higher effort is useful for unresolved architecture, provenance, replay/state transitions or statistics, not automatically for every task. Resolve missing requirements, ownership and runtime readiness before upgrading the model.

One Worker is the default regardless of client. Coordination is separate from model strength: use [orchestration](#orchestration) only for an explicitly authorized queue or a concrete delegation/review/remediation benefit. Dependency or parallel work follows [Parallel work](#book--parallel-work); an isolated task requires no compatibility form.

<a id="risk-and-routing--roles"></a>
### Roles

Use [project role ownership](../AGENTS.md#roles). This document owns capability/review decisions, not a second set of acceptance permissions.

<a id="risk-and-routing--complexity-classes"></a>
### Complexity classes

Implementation effort and risk are separate. A small privacy/migration change can still be high risk.

| Class | Typical scope / capability | Review |
| --- | --- | --- |
| <a id="c0--trivial--mechanical"></a>C0 — Trivial / Mechanical | Typo, link, formatting or unambiguous small fixture/test change; reliable fast model | Integrator; separate review optional unless requested/risk appears |
| <a id="c1--routine"></a>C1 — Routine | Isolated UI, established CRUD/parser mapping, bounded docs/tests; reliable coding model | Integrator; separate review for material cross-cutting risk or explicit request |
| <a id="c2--normal"></a>C2 — Normal | Multi-file feature under stable architecture, non-destructive API or established analytics; capable coding model | Integrator plus targeted independent review when multiple layers/risk warrant it |
| <a id="c3--hard--high-risk"></a>C3 — Hard / High risk | Ingestion, migrations, replay/idempotency, auth/network, canonical selection, cross-source analytics; strong coding/reasoning | Strong Integrator review; independent Reviewer normally required; live gates Owner-controlled |
| <a id="c4--critical--architecture"></a>C4 — Critical / Architecture | Destructive/history reinterpretation, privacy/security architecture or canonical-model redesign; strongest appropriate reasoning | Mandatory independent review plus explicit Integrator decision/ADR before implementation or merge as applicable |

<a id="c4--critical--architecture--routing-principles"></a>
### Routing principles

Use current capability and availability, not permanent model names. High reasoning is not a substitute for tests; stronger models do not turn self-review into independent review. For provider/device/API facts use pinned contracts/current official sources; for analytics prefer explainable methods appropriate to coverage/sample size.

<a id="c4--critical--architecture--independent-review-triggers"></a>
### Independent review triggers

A separate Reviewer is required by the risk class above, explicit Owner/Integrator request, or justified execution risk. Required independent review can run alongside CI on the same frozen candidate unless the issue says otherwise. The Reviewer inspects existing exact-candidate evidence and runs focused checks for identified gaps; a second full suite is not required solely because a different role is reviewing.

Risk escalation does not authorize new requirements or scope expansion. If it changes architecture, privacy, canonical data or health semantics, return to the Integrator for a bounded decision. Existing explicit task gates stay in force unless the Integrator explicitly revises that assignment.

<a id="c4--critical--architecture--capability-based-selection"></a>
### Capability-based selection

Choose fast execution for mechanical work, strong coding for established cross-layer contracts and strong reasoning for unresolved decisions. Concrete model IDs/effort are local execution choices, not required task or completion metadata. Selection never waives required semantic/privacy review.

<a id="c4--critical--architecture--manual-and-orchestrated-clients"></a>
### Manual and orchestrated clients

Codex, Grok, Hermes and other clients may all be ordinary Workers. A client name or a request for a task series does not activate a queue. Execution-mode rules live only in [Agent orchestration](#orchestration).

<a id="c4--critical--architecture--hermes-delegationfallback"></a>
### Hermes delegation/fallback

The accountable Worker reports material changes to scope, verification or review independence caused by delegation/fallback, not model identities. Client-specific coordination belongs in [the Hermes adapter](#client-hermes).

<a id="c4--critical--architecture--escalation-triggers"></a>
### Escalation triggers

Return to the Integrator for conflicting authority; possible history loss/reinterpretation; identity ambiguity affecting history; access outside the Owner-authorized data scope or credential disclosure; changed security exposure/provider contracts; out-of-scope services/dependencies; or newly required architecture/health semantics. Ordinary reversible implementation choices within a resolved contract need no repeated approval.

<a id="c4--critical--architecture--owner-task-proposal"></a>
### Owner task proposal

In plain Russian: task title; intended change/value; implementation complexity and separate risk; a suitable execution client and necessary review/Owner action. Honor an already selected route. A model/effort recommendation may help choose execution, but no model confirmation or attribution intake is needed before starting or accepting work.

Add one short copyable locator prompt, normally 5–8 lines: repo/issue/applicable note, role, target/exact baseline, assigned branch/workspace, outcome and authorized delivery. The issue is the specification; do not duplicate it in the prompt. Resolve missing safety-critical assignments first. Add queue/parallel fields only when that mode is actually authorized.

<a id="orchestration"></a>

<a id="orchestration--optional-orchestration-and-queue-policy"></a>
## Optional orchestration and queue policy

Optional execution-local coordination for explicitly authorized queues/delegation. Reading this file, naming a client or asking for an audit does not activate it. Ordinary single-Worker work uses [Development Process](#1-core-operating-model); roles/acceptance authority are defined in [AGENTS.md](../AGENTS.md#roles).

<a id="orchestration--roles"></a>
### Roles

Use the canonical roles; do not require a Builder/Breaker/Auditor pipeline. An Orchestrator coordinates delegated work rather than becoming a second writer. Independent review requires a separate Reviewer, not root/Worker self-review.

<a id="orchestration--launch-compatibility-assessment"></a>
### Launch compatibility assessment

For a genuinely isolated single task, the issue assignment is sufficient: no compatibility table or N/A sections. For dependencies/shared contracts or proposed parallel work, record the compact decision required by [Parallel work](#book--parallel-work): dependency readiness, pinned interface/base, shared artifact owner, boundaries and order. Add applicable comment IDs when they establish that decision.

Parallel execution requires explicit Owner opt-in and compatible scopes, not merely separate worktrees. Unresolved shared schema/API/module/export/migration/version ownership blocks the affected launch. Do not inspect other workspaces to discover ownership; use assignment records. Do not silently change an existing assignment.

<a id="orchestration--early-contract-checkpoint-and-final-gates"></a>
### Early contract checkpoint and final gates

[Verification by change](#book--verification-by-change) owns risk-proportional early checks; [CI evidence](#ci-gates--13-ci-evidence-and-complete-suite-gates) owns final-gate identity/completeness. An orchestrated run adds no automatic extra full suite or mandatory early review. Required final checks/review may overlap on one frozen candidate when the issue permits.

<a id="orchestration--mode-a--manual--brokered-execution"></a>
### Mode A — manual / brokered execution

One Worker is the default for `дай задачу для <model/client>`, including Codex, and for `Codex без оркестрации`. A request for a task series asks the Integrator to propose compatible order; it does not authorize automatic execution. Follow the ordinary process without loading queue mechanics.

<a id="orchestration--mode-b--codex-delivery-loop"></a>
### Mode B — Codex `$delivery-loop`

An explicit orchestration launch identifies repo, authorized task list, per-task exact baseline/target, branch/workspace, queue/completion mode and required review. State the actual coordination benefit.

1. Root coordinates; a Worker owns each implementation candidate.
2. Worker returns exact candidate/check evidence; root inspects the actual result.
3. Use a separate Reviewer when [risk policy](#c4--critical--architecture--independent-review-triggers) requires it; a network-disabled reviewer receives accessible literal source/evidence, not just URLs.
4. `review-and-stop` returns findings without automatic fixes. Otherwise use one remediation cycle; a second requires explicit authorization or a demonstrably mechanical bounded fix. Never exceed two.
5. Internal states are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED` and `BLOCKED_FOR_INTEGRATION`. `INTERNAL_ACCEPT` is execution evidence, never project ACCEPT or merge permission.

<a id="orchestration--queue-policy"></a>
### Queue policy

<a id="orchestration--single"></a>
#### Single

One authorized task, its checks/review and report; then stop.

<a id="orchestration--independent-queue"></a>
#### Independent queue

Only explicitly listed eligible tasks may advance. Each owns its assigned branch, physical write workspace and pinned baseline; the prior task's candidate is not an implicit base. A sequential queue advances after the previous task reaches INTERNAL_ACCEPT; explicitly authorized parallel work keeps separate per-task gates.

<a id="orchestration--dependency--integration-block"></a>
#### Dependency / integration block

A task requiring an unintegrated dependency and lacking an explicit safe baseline/fixture strategy is BLOCKED_FOR_INTEGRATION. This blocks that dependency chain. Unrelated listed eligible items may continue only if the launch expressly enables integration-block continuation; otherwise stop. Do not invent stacked history, merge canonical branches or pick replacement backlog work.

<a id="orchestration--independent-review-triggers"></a>
### Independent review triggers

Use [risk and routing](#c4--critical--architecture--independent-review-triggers); queue activation neither adds an automatic Reviewer to every task nor waives a required one.

<a id="orchestration--reporting"></a>
### Reporting

<a id="orchestration--per-task-report"></a>
#### Per-task report

Use [Completion reporting](../AGENTS.md#completion-reporting), adding only material delegation/remediation facts and evidence references. A compact phase ledger is useful for actual coordinated work; unknown timings/costs remain unknown, not a mandatory form.

<a id="orchestration--final-queue-report"></a>
#### Final queue report

List each authorized task's final internal state, candidate SHA when present, review path and unresolved Integrator action. This is not batch project acceptance.

<a id="orchestration--local-skillsconfig"></a>
### Local skills/config

Client skills, model routing and subagent definitions are local mechanics; do not hardcode machine paths/model IDs here. A new project skill is justified by a reusable distinct procedure, not symmetry or a copy of policy. Keep implicit delivery-loop activation disabled.

<a id="orchestration--invariants-automation-cannot-weaken"></a>
### Invariants automation cannot weaken

All [project boundaries](../AGENTS.md) still apply, including privacy, workspace isolation, health semantics, honest evidence and Integrator-controlled acceptance.

<a id="dependency-security"></a>

<a id="dependency-security--dependency-security-and-reproducible-audit"></a>
## Dependency security and reproducible audit

The reproducible entrypoint is:

```shell
uv run --locked python scripts/dependency_audit.py --output-dir <fresh-external-evidence-directory>
```

Use a new directory for every attempt. The entrypoint reads every registry
name and version from `uv.lock`, including development groups and
platform-specific packages. It invokes `pip-audit==2.10.1` in an isolated uv
tool environment with `--no-deps --disable-pip --strict` and
`--vulnerability-service osv`. It does not resolve or install project code,
change the lock, or apply fixes.

Exit `0` means a complete clean registry audit. Exit `1` means complete
advisory findings. Exit `2` means a scanner, network, tool, or coverage
failure. Missing packages, malformed output, and status disagreement fail
closed. Neither nonzero outcome is a pass. Ordinary CI does not run this
audit. `.github/workflows/dependency-audit.yml` runs it for pull requests and
pushes to `main` that touch dependency or audit policy paths, and for manual
dispatch. It uploads evidence even when the audit fails. Docs-only and
unrelated code changes do not trigger that network work. A dependency change
needs both ordinary CI and this workflow.

Weekly Dependabot groups cover uv registry version updates (limit two open
PRs) and GitHub Actions version updates (limit one). Those limits do not cap
GitHub security updates. Garmin is ignored: its VCS pin needs a separately
assigned update. No automatic merge is enabled.

<a id="dependency-security--issue-242-reproduction"></a>
### Issue #242 reproduction

Baseline: `754f19068cede943ddfb5c5f4ce0cfe72fa9689e`.
Audit date: 2026-10-03 UTC. Tools: uv 0.12.17, Python 3.12.14,
pip-audit 2.10.1, service OSV. Both audits covered 45 registry packages.
Baseline lock SHA-256:
`782c554fd00f0f311f61e1b93228e317552435d0242bc14a8b96b49181590fcd`.
Patched lock SHA-256:
`6ea5dbd974972d855042b41e25fd6b616873884616838fdc64d6e9187f7e3f4f`.

| Package | Baseline | Patched | Exposure | Advisory |
| --- | --- | --- | --- | --- |
| urllib3 | 2.7.0 | 2.8.0 | runtime | PYSEC-2026-4175 / GHSA-8988-9cw3-xx77, PYSEC-2026-4176 / GHSA-gh4c-6fx4-qh6g, PYSEC-2026-4177 / GHSA-vxq7-64xx-v4gw |
| pytest | 8.4.2 | 9.0.3 | development | PYSEC-2026-1845 / GHSA-6w46-j5rx-g56g / CVE-2025-71176 |

The baseline OSV result was `findings` (exit 1) for those four IDs only.
Fix versions were urllib3 2.8.0 and pytest 9.0.3. The patched OSV result was
`clean` (exit 0). No other registry package had an OSV finding. The only
version changes are those two packages. The lock also records the pytest
specifier `>=9.0.3,<10` and the uv constraint `urllib3>=2.8.0,<3`.
A clean-workspace re-run at 2026-10-03T21:19Z repeated that result: the same
entrypoint against an isolated checkout of baseline `754f190` and against the
patched lock. Python for that re-run was 3.13.15. The git blob of `uv.lock`
was unchanged.

urllib3 is reachable through the Garmin client's requests dependency. The
audit establishes affected versions, not exploitation in any Owner runtime.
pytest is development tooling. Its temporary-directory advisory concerns Unix
multi-user conditions.

On 2026-10-03 one pip-audit PyPI JSON query of the two vulnerable pins
returned no advisories. A later query the same day returned the same four IDs
and duplicated the pytest row. The gate stays on OSV so a false-clean PyPI
response cannot pass. OSV has no global snapshot version; reproduction fixes
the inventory and scanner, not future advisory content.

Coverage excludes the first-party editable project and the unaudited Garmin
VCS source at `54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5`. Registry dependencies
of that source are included. The scanner checks known package advisories, not
VCS integrity, build dependencies, exploitability, or live providers.
No Owner or provider access was used.

Ordinary CI pins action SHAs and defaults the token to `contents: read`.
Only classify keeps `pull-requests: read` and `actions: read` for Stage B
discovery. The audit workflow uses `contents: read` and the same pinned
action SHAs. No write scopes were added.

<a id="synthetic-demo"></a>

<a id="synthetic-demo--synthetic-demo-and-browser-mechanics"></a>
## Synthetic demo and browser mechanics

Fixed-seed, fixed-date synthetic profile for local viewing, safe screenshots and
agent UI checks (#358). Synthetic only: no Owner data, no provider calls, and
the runtime always stays outside the source checkout.

<a id="synthetic-demo--dataset"></a>
### Dataset

`seed-demo` writes one marked profile (`multidomain-synthetic-v2`) through the
accepted application services:

- the existing six-month Weight batch: 26 weigh-ins / 59 confirmed candidates
  (Xiaomi photo-import path, `Health-Check Synthetic Demo` label);
- 25 Garmin `Vivoactive 5` sleep nights (3 duration-only sparse nights and
  5 missing days) plus one nap;
- 26 Google `google-wearables` family sleep records (5 missing days, 1 manually
  edited night, 1 partial night without asleep minutes and naps);
- 6 Garmin activities: 3 cycling, 2 tennis and 1 walking session;
- 6 dated Context notes (date/instant/interval) tagged `synthetic-demo`.

Reproducibility: random seed `358` and anchor date `2026-10-10` make reruns
idempotent and two fresh seeds produce identical stored rows. Missing and
partial days stay missing; nothing is zero-filled.

Safety: `seed-demo` refuses symlink/junction targets (including aliases that
resolve into another Git workspace), targets inside any Git checkout or
workspace, and non-empty unmarked profiles (also with `--reset`). Before any
destructive reset it re-reads the persisted database through a private
read-only copy and validates it against the versioned fixed-seed manifest:
foreign content, extra records or a marker/content version mismatch are refused
without modifying any file. `--reset` then rebuilds only the positively
identified marked demo (v1 or v2).

<a id="synthetic-demo--prepare-and-run"></a>
### Prepare and run

```powershell
$env:HEALTHCHECK_DATA_DIR = Join-Path $env:LOCALAPPDATA "Health-Check\multidomain-synthetic-demo"
uv run python -m healthcheck.cli seed-demo
uv run python -m healthcheck.cli serve --app ui --port 8126
```

Open `http://127.0.0.1:8126/`. Re-running `seed-demo` is a safe no-op;
`seed-demo --reset` rebuilds the same marked profile. To clean up, stop the
server and remove only the confirmed dedicated demo directory above.

<a id="synthetic-demo--screen-scenarios"></a>
### Screen scenarios

- `/` and `/brief?start_date=2026-01-01&end_date=2026-07-31` — Weight history,
  EWMA trend and coverage; no observation is rendered as zero.
- `/sleep?wake_date=2026-10-10` — the default 30-day Garmin + Google duration
  timeline with separate exact-source rows and explicit gaps.
- `/sleep?wake_date=2026-10-10&view=garmin` — legacy Garmin night with duration,
  score and four stage intervals; `/sleep?wake_date=2026-10-08&view=garmin` — a
  missing night.
- `/sleep?wake_date=2026-10-04&view=google` and
  `/sleep?wake_date=2026-09-23&view=google` — the independent Google family
  label with present and partial nights.
- `/sleep?wake_date=2026-10-10&view=compare` — comparison boundary: pairs are
  persisted but no agreement run is published, so the page shows the explicit
  unavailable state instead of inventing numbers.
- `/garmin` — 3 cycling / 2 tennis / 1 walking sessions from the demo source.
- `/context` — six dated, clearly synthetic notes with `synthetic-demo` tags.

<a id="synthetic-demo--desktop-browser-evidence"></a>
### Desktop browser evidence

Playwright must resolve for Node (for example via an agent browser runner).

```powershell
$env:HEALTHCHECK_BROWSER_BASE_URL = "http://127.0.0.1:8126"
$env:HEALTHCHECK_BROWSER_EVIDENCE_DIR = Join-Path $env:TEMP "hc358-demo-evidence"
# optional: $env:HEALTHCHECK_BROWSER_EXECUTABLE = "<chromium executable>"
node scripts/check_358_demo_browser.cjs
```

The script checks the screens above at 1024 and 1440 px, including the default
sleep timeline, blocks external requests, fails on page errors and horizontal
overflow, and writes screenshots plus `demo-browser.json` into the evidence
directory. That evidence is synthetic demo evidence only; it is not Owner UAT,
provider verification or a real-profile performance claim.

<a id="owner-ui-verification"></a>

<a id="owner-ui-verification--owner-ui-verification-mechanics"></a>
## Owner UI verification mechanics

<a id="owner-ui-verification--verification-and-post-uat-follow-up"></a>
### Verification and post-UAT follow-up

Focused `scripts/check_owner_{data,brief,weight,sleep,activity}_browser.cjs`, shared
`check_owner_acceptance_browser.cjs` and relevant page-specific checks use
representative **1024/1440px** desktop widths. No suite/CI lane/Windows/guard is
removed and no skip/xfail replaces functional coverage. Exact gates follow
[Development Process](#ci-gates--13-ci-evidence-and-complete-suite-gates).

#321 retired only phone-target loops, one-column/breakpoint ordering, forced
narrow-table/phone tick-density expectations. Desktop checks retain source truth,
chart points/date endpoints, readable axes, focus, pointer/keyboard, imports,
unconfigured extraction, disclosures, comparison, tables and request race/errors.
Pytest retains viewport/skip-link/focus/targets/table contracts. Legacy Brief packet
checks select `.brief-packet`; Google-vitals checks use its source view/disclosure;
the missing Garmin night check remains separately source-specific.

Synthetic browser evidence and CI do not prove human Owner UAT. #330 records the
latest **partial real review**, including the requested Sleep experience and data
questions. New candidates' unperformed private gates remain UNVERIFIED. The static
reference approval was a design choice, not automatic acceptance of every later
implementation. Historical #189 and #305–#309 checks/failures are retained in their
issue/PR records. #295 was reopened for new latency evidence; #298 remains not planned.



<a id="worker-checkout-workflow--managed-worker-checkout-recipe"></a>
## Managed worker checkout recipe

<a id="worker-checkout-workflow--worker-checkout-workflow"></a>
### Worker checkout workflow

The existing Codex, Hermes and Grok adapters use this one workflow when the task
explicitly selects **managed lifecycle v1**. OpenCode or other executors reading
the shared Owner workflow use the same entrypoint. The task assignment supplies
the accepted installed `$janitor`, configured client root/new `$task` child,
unique `$taskOwner`, official origin, pinned `$baseline`, `$branch` and delivery scope.
Owner identifiers use ASCII letters/digits, dot, underscore, hyphen (maximum 80).
These are task inputs, not new machine configuration or an executable launcher.
Do not use Stable, Test, staging, recovery or backups.

Dot-source the accepted installed script with its matching native helper, under
the existing PowerShell authorization policy. `Invoke-WorkerLifecycle` is the
worker consumer in that script: each operation acquires the existing project
mutex and either returns one claim object or throws. This avoids treating a stale
native `$LASTEXITCODE`, a JSON string or diagnostic Check as authorization to write.
If loading is denied by AuthorizationManager, stop and report that exact failure;
do not use ExecutionPolicy Bypass, Unblock-File, alternate hosts or evaluation of
the script text to evade it. Do not load a disposable checkout as the production helper.

```powershell
$ErrorActionPreference = 'Stop'
. $janitor
$claim = Invoke-WorkerLifecycle -Action Create -Workspace $task -Owner $taskOwner
# Retain owner/path/Claim/generation in the existing task checkpoint now.
git clone -- $officialOrigin $task
if ($LASTEXITCODE -ne 0) { throw 'clone failed; retain active claim for recovery' }
$claim = Invoke-WorkerLifecycle -Action Bind -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
$claim = Invoke-WorkerLifecycle -Action CheckActive -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
git -C $task switch -c $branch $baseline
if ($LASTEXITCODE -ne 0) { throw 'task branch/baseline setup failed' }
# CheckActive again before each bounded edit/test/commit/publication phase.
# Perform only the assigned work and its separately authorized delivery.
$claim = Invoke-WorkerLifecycle -Action Pause -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
# On continuation, use the same owner and the current checkpoint Claim:
$claim = Invoke-WorkerLifecycle -Action Resume -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
# Persist the NEW Claim/generation before continuing. The old Claim must fail.
$claim = Invoke-WorkerLifecycle -Action CheckActive -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
# Commit/publish only as authorized, retain the delivered SHA/resource receipt.
# Complete AFTER delivery exists and no further writes are intended:
$claim = Invoke-WorkerLifecycle -Action Complete -Workspace $task -Owner $taskOwner -ClaimId $claim.Claim
```

This is a sequence of explicit phase boundaries, not a script to run unattended
from start to finish. Do not Complete in a `finally` block, on failure, or merely
because a chat turn ended. If the client disappears before Pause, active remains
durable and preserves the checkout. Review fixes after Complete require Resume,
the new Claim, then CheckActive before edits. Missing/stale task checkpoint or
unknown ownership means preserve, never borrow another task's token or identity.
The checkpoint is a resume receipt, not cleanup authority; the external registry
remains authoritative. A local-only delivery can Complete but remains protected
by the janitor's independent unpublished-history guard.

A short task prompt can select this workflow without a new launcher:

```text
Worker: <repo / issue / accepted note>, baseline <SHA>, target <branch>.
Use a NEW task clone under <configured client root>, branch <task branch>.
Lifecycle: managed v1, accepted helper <Ops script>, owner <unique task identity>.
Follow docs/DEVELOPMENT_PROCESS.md#worker-checkout-workflow through Invoke-WorkerLifecycle.
Keep current Claim/generation in the task checkpoint; require CheckActive before work.
Delivery: <local-only or explicitly allowed branch/PR>. Complete after delivery.
Do not enroll an existing platform checkout or operate on runtime/Owner folders.
```

There is no platform task-created/paused/resumed/completed hook in this API. The
executor must execute the boundary calls in its task/checkout workflow; a prompt
cannot intercept a platform event. A platform-created checkout already exists,
so Create refuses it. Keep it unmanaged, or use a separate fresh authorized clone
for managed work; never claim automatic enrollment or move an active checkout.
Existing worktrees stay outside managed v1. Client root/helper-path selection and
adoption of these prompts remain explicit setup/rollout steps; this change does
not edit app configuration, install Ops, register tasks or activate scheduling.

The standalone CLI retains diagnostic `Check` and also accepts `CheckActive`.
Diagnostic success alone is never a write guard. Scan is the default; real scan
or Apply is a separate authorized operation, not a worker completion hook. Finance
derives roots from the accepted installation directory, so source execution inside
a disposable checkout is not an Ops install.


<a id="reuse-and-license"></a>

<a id="reuse-and-license--reviewed-reuse-licensing-and-adversarial-regression-rules"></a>
## Reviewed reuse, licensing and adversarial regression rules

<a id="reuse-and-license--reviewed-reuse-classifications"></a>
### Reviewed reuse classifications

| Project | Reviewed source | Verified license at reviewed source | Final use |
|---|---|---|---|
| [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect/tree/981d150caeda7d632224a75f3895c08df27a2a34) | Original R02: `981d150caeda7d632224a75f3895c08df27a2a34` (`0.3.12`); accepted maintenance runtime: `54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5` (`0.3.15`) | MIT | **DIRECT runtime dependency**, pinned; do not write a competing client. The former 0.3.13 watch is superseded. Current upstream 0.3.16 requires a separate bounded upgrade decision. |
| [`garmin-stats-ai`](https://github.com/dandwhelan/garmin-stats-ai/tree/936974ac8c78781e7d0075040f459ea7676b3819) | `936974ac8c78781e7d0075040f459ea7676b3819` | Root MIT; bundled `garmin-grafana/` BSD-3-Clause | **Selective donor/reference**: tiny pure statistics may be direct after file-level review; adapt transforms/sync/lag/activity/test semantics; do not adopt product/medical claims. |
| [`fettle`](https://github.com/Deekshith-Dade/fettle/tree/82929df268124f0a3470b180adbbbeb0802d03cd) | `82929df268124f0a3470b180adbbbeb0802d03cd` | MIT | **Selective donor** for Google Health v4 registry/client/sync/sleep/test patterns. No module-level direct reuse approved. |
| [`healthquery`](https://github.com/nikira-studio/healthquery/tree/f175148f67cb954fc4db2e026e497984dfccac29) | `f175148f67cb954fc4db2e026e497984dfccac29` | MIT | **Selective pattern donor** for raw batch replay, migrations and typed MCP shapes; reject its generic SQL/capability boundary. |
| [`garmin_ai`](https://github.com/TolmachevKirill/garmin_ai/tree/ca6d298cc4a7e4e95e036c76dce69d211a47aeee) | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee` | **UNVERIFIED**: no LICENSE/COPYING in reviewed tree | **REFERENCE ONLY**; no code copying. |
| [`openScale`](https://github.com/oliexdev/openScale/tree/6613db5838e4674a19652441073f82b3ee3d7009) | `6613db5838e4674a19652441073f82b3ee3d7009`; stable S400 code also in `v3.1.2` | GPL-3.0 | **EXTERNAL Android component**; use its BLE/output boundary, copy no code into core. Current upstream has moved to an identity-based API-v3 measurement model; re-audit before future Xiaomi ingest changes. |
| [`openScale-sync`](https://github.com/oliexdev/openScale-sync/tree/32e38651cf78bbf230e33d17abb00b147130f305) | `32e38651cf78bbf230e33d17abb00b147130f305` | GPL-3.0 | **EXTERNAL Android component**; implement/maintain a compatible generic-webhook receiver contract, but re-audit current API-v3 identity semantics before changing the released R01 path. |
| [`open-wearables`](https://github.com/the-momentum/open-wearables/tree/72351e24de045e87da4fe4fd86142494e304e17b) | `72351e24de045e87da4fe4fd86142494e304e17b` | MIT | **ARCHITECTURE/SELECTIVE PATTERN**: typed MCP-over-API, provider registry/chunking, sync diagnostics; reject SaaS infrastructure and unsafe derived math. Current upstream observations are secondary evidence only. |
| [`haelan`](https://github.com/bardesss/haelan/tree/89d512115acc9b1529a6380399a0d451556da0b1) | `89d512115acc9b1529a6380399a0d451556da0b1` (`1.6.0`) | **AGPL-3.0** | **REFERENCE ONLY / NO CODE COPYING**: adversarial Google Health v4 observations; raw/cache/derived rebuild patterns; correction/rederive; bounded shared query layer; source-staleness idea. |
| [`VitaSync`](https://github.com/biosync-io/vitasync/tree/f299cd134edea8effca9ac52436fc83d439792b6) | `f299cd134edea8effca9ac52436fc83d439792b6` | AGPL-3.0 | **REFERENCE ONLY**; do not copy. Product/infrastructure mismatch. |

Network/process separation reduces code-incorporation risk but does not settle every licensing obligation. Distribution choices must still comply with each program's license.

<a id="reuse-and-license--evidence-discipline-for-active-r04-work"></a>
### Evidence discipline for active R04 work

`fettle`, `open-wearables` and `haelan` are useful **adversarial references**, not authorities for Google Health behavior. R04-00/#81 keeps its stricter rule: current first-party Google documentation is required for material provider/API/OAuth/policy conclusions; owner-live evidence is used only where the official contract remains ambiguous.

A donor implementation may suggest that we ask about string-encoded integer fields, proto3 zero omission, irregular data-type names, source-family behavior, pagination or historical lookback, but it may not turn an official UNKNOWN into a Health-Check fact.


Full dated upstream observations and donor-specific examples are retained in the
[reference registry archive](archive/research/REFERENCE_PROJECTS.md). They are
observations at exact source commits, never an automatic dependency repin. Before
copying code, recheck the exact file/license, retain notices and record provenance.
Use the archive's adversarial regression catalogue for applicable boundary tests;
donor thresholds, derived scores and generic SQL never override project contracts.


<a id="retired-model-bookkeeping--retired-model-bookkeeping"></a>
## Retired model bookkeeping

The Owner discontinued Health-Check model benchmarking and attribution bookkeeping on 2026-10-03. [#210](https://github.com/LTstripes/Health-Check/issues/210) is closed as not planned. This page is a historical pointer, not an active protocol or task queue.

The former journal remains in [Git history](https://github.com/LTstripes/Health-Check/blob/d4529df9b5c0f3df28d637a259fbe82d0b4fde43/docs/MODEL_BENCHMARK.md); the existing [earlier archive](archive/history/MODEL_BENCHMARK_THROUGH_2026-10-01_RELIABILITY.md) is historical only. No new entries, model confirmations, backfill or rescoring are required.

Current technical outcomes and checks belong in issues/PRs and [current engineering outcomes](PROJECT_WIKI.md#recent-outcomes). Current completion reporting is defined in [AGENTS.md](../AGENTS.md#completion-reporting).

<a id="client-chatgpt"></a>

<a id="client-chatgpt--optional-chatgpt-client-chapter"></a>
## Optional chatgpt client chapter

ChatGPT/Lera remains the normal Health-Check Integrator. Role authority is in [AGENTS.md](../AGENTS.md#roles); routine delivery/review/release is defined once in [Development Process](#1-core-operating-model).

<a id="client-chatgpt--github-native-work"></a>
### GitHub-native work

Use connected GitHub directly for issues, branches, PRs, reviews, integration and documentation when available; do not make the Owner a GitHub courier. Read actual candidate/ref/check evidence, not only a forwarded summary. Use the [Owner task proposal](#c4--critical--architecture--owner-task-proposal) for external execution and honor the selected implementation client.

Small explicit Integrator-owned documentation/metadata changes may be made directly. Behavioral remediation normally returns to a Worker through the current issue or a bounded follow-up; do not silently modify a candidate and claim independent review of it.

<a id="client-chatgpt--local-limitation"></a>
### Local limitation

GitHub access does not imply access to Owner Windows files, private runtime, browser or devices. Delegate genuinely local synthetic checks to an appropriate execution environment and private/live checks to Owner UAT. Never claim such checks from GitHub inspection alone.

<a id="client-chatgpt--optional-orchestration"></a>
### Optional orchestration

Only explicit Owner authorization activates [Agent orchestration](#orchestration). Ordinary task proposals and reviews do not require queue packets or compatibility forms for an isolated task.

<a id="client-chatgpt--owner-effort"></a>
### Owner effort

The Owner normally launches the short prompt, returns its report, and performs genuinely private/manual gates. Integrator handles the GitHub actions and concise linked history; no duplicate report relaying or full-suite rerun just because the result reached this client.

<a id="client-codex"></a>

<a id="client-codex--optional-codex-client-chapter"></a>
## Optional codex client chapter

Use [AGENTS.md](../AGENTS.md) and the assigned issue. A session is one Worker unless explicitly assigned otherwise. Local configuration selects models/effort/workspaces; no model roster or duplicate delivery policy lives here.

<a id="client-codex--independent-review-mechanics"></a>
### Independent review mechanics

Give a separate Reviewer the pinned base/candidate, relevant contract/comment text, prior findings and check evidence. A network-disabled reviewer needs literal accessible sources, not only URLs. Resolve packet/runtime readiness before starting review inference.

Enforced read-only review requires a separate context/runtime with the intended permissions. A child inheriting writable rights is not proof of isolation. Independent review does not require an orchestration loop or another automatic full suite.

<a id="client-codex--explicit-orchestration-only"></a>
### Explicit orchestration only

Only an explicit request activates [Agent orchestration](#orchestration). A mention, audit or ordinary task/review does not invoke `$delivery-loop`.

<a id="client-codex--local-helpers"></a>
### Local helpers

Load only a relevant procedure skill; keep implicit delivery-loop invocation disabled and avoid duplicate active skills. Skills may add mechanics, not weaken policy. Concrete model IDs/effort/local paths stay in local configuration; return the technical [completion report](../AGENTS.md#completion-reporting).

<a id="client-codex--managed-owner-local-task-checkout"></a>
### Managed Owner-local task checkout

When the task explicitly selects managed lifecycle v1, use the executable
`Invoke-WorkerLifecycle` consumer in the accepted installed helper and follow
[worker checkout workflow](#worker-checkout-workflow--worker-checkout-workflow).
The assignment supplies the helper path, client root, new child and unique owner;
retain the current Claim/generation in the existing task checkpoint. Require
CheckActive before work, Pause/Resume explicitly, and Complete after delivery.
This does not hook platform task events or enroll an already-created checkout.
Without configured/accepted support, use only the shared fresh-unmanaged fallback.

<a id="client-grok"></a>

<a id="client-grok--optional-grok-client-chapter"></a>
## Optional grok client chapter

Grok Build is an ordinary Worker under [AGENTS.md](../AGENTS.md), not a mandatory multi-bot pipeline. Use the assigned issue and relevant [development/check procedure](#book--verification-by-change).

<a id="client-grok--build-specific-use"></a>
### Build-specific use

Exploration and browser/UI inspection are useful inside the assigned scope; they do not authorize redesign or access to private Owner data. Use synthetic browser fixtures and distinguish observed browser checks from code inspection.

Return the shared [completion report](../AGENTS.md#completion-reporting). Only explicit authorization changes delivery permissions or enables coordinated bots.

<a id="client-grok--managed-owner-local-task-checkout"></a>
### Managed Owner-local task checkout

When the task explicitly selects managed lifecycle v1, use the executable
`Invoke-WorkerLifecycle` consumer in the accepted installed helper and follow
[worker checkout workflow](#worker-checkout-workflow--worker-checkout-workflow).
The assignment supplies the helper path, client root, new child and unique owner;
retain the current Claim/generation in the existing task checkpoint. Require
CheckActive before work, Pause/Resume explicitly, and Complete after delivery.
This does not hook platform task events or enroll an already-created checkout.
Without configured/accepted support, use only the shared fresh-unmanaged fallback.

<a id="client-hermes"></a>

<a id="client-hermes--optional-hermes-client-chapter"></a>
## Optional hermes client chapter

Use [AGENTS.md](../AGENTS.md). The receiving Hermes Worker remains accountable for the final candidate when it delegates or changes execution route.

<a id="client-hermes--delegation-mechanics"></a>
### Delegation mechanics

Helpers are Delegates unless explicitly assigned another role. Read-only helpers may share context; concurrent writers need explicitly assigned isolated sub-workspaces/branches, otherwise run sequentially. The Worker assembles the bounded result before handoff; helpers do not create an implicit second candidate or start another roadmap task.

A helper that contributes implementation is not the independent Reviewer of that work. Apply the issue's review requirement independently of the delegation mechanism.

<a id="client-hermes--completion"></a>
### Completion

Report material effects of delegation/fallback on scope, verification or review independence through the shared [completion report](../AGENTS.md#completion-reporting).

<a id="client-hermes--client-distinction"></a>
### Client distinction

Hermes does not need the Codex-local `$delivery-loop` skill. Only explicit coordination/queue authorization loads [Agent orchestration](#orchestration). Ordinary Hermes execution follows [Development Process](#1-core-operating-model).

<a id="client-hermes--managed-owner-local-task-checkout"></a>
### Managed Owner-local task checkout

When the task explicitly selects managed lifecycle v1, use the executable
`Invoke-WorkerLifecycle` consumer in the accepted installed helper and follow
[worker checkout workflow](#worker-checkout-workflow--worker-checkout-workflow).
The assignment supplies the helper path, client root, new child and unique owner;
retain the current Claim/generation in the existing task checkpoint. Require
CheckActive before work, Pause/Resume explicitly, and Complete after delivery.
This does not hook platform task events or enroll an already-created checkout.
Without configured/accepted support, use only the shared fresh-unmanaged fallback.

<a id="accepted-ci-decisions"></a>

<a id="accepted-ci-decisions--accepted-ci-and-repository-protection-decisions"></a>
## Accepted CI and repository-protection decisions

<a id="accepted-ci-decisions--ci-verification-and-repository-integration"></a>
#### CI, verification and repository integration

#123–#125 and #181/#243 are accepted: targeted iteration, frozen exact candidate,
PR integration and post-main gates; final checks fails on incomplete/malformed/
cross-run evidence or missing mandatory proof. Exact Linux nodeids/multiplicity
reconcile across the three lanes; Windows actually runs DPAPI/startup/HTTP/cleanup.
No green subset or partial rerun replaces full same-attempt evidence.

#251 lane balance, #246 docs-only/event dedup, #242 dependency audit, #244 Host/Origin
and #302 deterministic Linux environment are complete. A docs filename alone does
not authorize skipping CI; the classifier decides. No broader Windows matrix,
cache/xdist or new CI optimization without measured need. Preserve old failures.
See [Development Process](#1-core-operating-model).

<a id="accepted-ci-decisions--repository-protection--126"></a>
##### Repository protection / #126

- Recheck current visibility/plan/capability before settings changes; private-data boundaries remain regardless of visibility.
- #126 remains an Owner/capability decision. Exact-SHA checks SUCCESS is required regardless of server enforcement.
- No force-push/deletion of canonical history, billing/settings/visibility change or implicit public-data clearance.
- #167 historical metadata rewrite is deferred and requires an explicit coordinated freeze.


<a id="license-decisions"></a>

<a id="license-decisions--license-boundary"></a>
## License boundary

<a id="license-decisions--license"></a>
#### License

- Health-Check is MIT; python-garminconnect is an MIT dependency.
- External GPL/AGPL projects stay external/reference-only unless obligations are accepted.
- Donor reuse is reviewed and pinned to exact versions.


<a id="adversarial-regressions"></a>

<a id="adversarial-regressions--cross-project-adversarial-regression-catalogue-and-reuse-gate"></a>
## Cross-project adversarial regression catalogue and reuse gate

<a id="adversarial-regressions--cross-project-adversarial-regression-catalogue"></a>
### Cross-project adversarial regression catalogue

The 2026-09-12 refresh adds these reusable failure classes to the watch list. Encode them only in an owning implementation task whose data shape actually makes the regression meaningful:

1. historical timestamp classified using today's UTC offset;
2. a partial sibling/upsert nulling a field observed in another fragment;
3. provider shape drift accidentally treated as an empty successful window;
4. proto3 omitted zero confused with missing;
5. string-encoded numeric field rejected or silently mistyped;
6. synthetic fixture schema drifting away from production persistence;
7. late-arriving evidence not invalidating recent derived/cache output;
8. provider aggregate mislabeled as a locally reproducible merge;
9. a source silently stops reporting but appears only as a thinning chart;
10. convenience zero/default fields overriding a more authoritative explicit-presence/generic-value model.

<a id="adversarial-regressions--reuse-gate-for-every-later-pr"></a>
### Reuse gate for every later PR

1. Record exact upstream repository, SHA, file, and license.
2. Prefer a normal dependency over copied code when the dependency boundary fits.
3. Copy only the smallest independently tested unit.
4. Preserve copyright/license notices and provenance.
5. Port semantics into Health-Check's source/canonical/coverage model rather than importing a donor schema.
6. Re-test with synthetic Health-Check fixtures.
7. Never reuse a health threshold, formula, provider fact, or device claim solely because a donor test passes.
8. A newer upstream head is observation only until an explicit task re-audits and approves the exact reuse boundary.


<a id="weight-regression-coverage--weight-regression-coverage"></a>
## Weight regression coverage

These retained R01 regression cases describe domain coverage. Current proportional/exact-CI rules govern when to run them; the old release-wide local acceptance sequence is historical.

Required suites:

- migration from empty database; migration idempotency; WAL and foreign-key assertions;
- configuration/runtime-directory isolation on Windows-compatible paths;
- synthetic photo batch, extractor contract, per-field normalization, edit/reject/confirm, and reprocessing;
- exact-image and semantic-record idempotency;
- pinned openScale-sync webhook contract fixture, listener route isolation, auth/secret rotation with stable sender identity, unknown fields, malformed envelope, mixed valid/invalid batch, out-of-order replay, lost-response duplicate retry, and transaction failure;
- algorithm-provenance and incompatible-series rejection;
- canonical selection-run determinism/input-snapshot hash under input reordering, failed-run behavior, and rule/input version change;
- time-aware EWMA with irregular gaps and same-day medians;
- Theil–Sen slope with outlier, minimum count/span, and no-data cases;
- fat/lean derivation with explicit input IDs and no cross-session pairing;
- coverage state/precedence with present, confirmed-empty, unavailable, failed, unknown, and missing-not-zero cases;
- instant/minute/date temporal precision with a date-only case proving that no midnight UTC timestamp is invented;
- API/UI smoke tests and safe error rendering;
- repository hygiene check for database/image/payload/secret patterns.

Use generated/synthetic data only. A private owner UAT data directory may validate real screenshots and the live phone path, but its contents and output never enter Git or test artifacts.
