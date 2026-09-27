# Model evidence journal — Health-Check

Protocol: `model-evidence-v1`, 2026-09-27. A dated observational journal for real project tasks, not a permanent ranking of models and not a replacement for acceptance gates.

Coordination/intake: [Health-Check #210](https://github.com/LTstripes/Health-Check/issues/210). Paired journal: [Finance #605](https://github.com/LTstripes/hermes-finance/issues/605) and its `docs/MODEL_BENCHMARK.md`. The two repositories use the same fields and interpretation rules; cases remain in their originating repository. Do not duplicate Finance outcomes as Health successes.

## Evidence and maintenance

The exact issue contract, candidate diff, CI, separate review and Integrator disposition remain authoritative. This file is their compact index, maintained by the Integrator after review together with a link to the relevant `docs/EXECUTION_HISTORY.md` entry. Workers supply evidence; they do not concurrently edit the shared journal.

Record rejected, abandoned and pending attempts as well as successes. Preserve the first-pass outcome after later fixes. Append escaped defects and UAT findings; do not erase them. An implementation model switch, an informal critique and independent review are different events.

## Common case format

A case is `(repository, issue, role, assigned baseline, initial candidate, execution route)`. Follow-up SHAs are attempts of that case, not independent successes. Record Worker, Reviewer and research/critique roles separately. Make any model/provider/version switch or delegate/fallback chain explicit.

| Field | What to record |
| --- | --- |
| Task | Repo/issue/PR; profile such as UI, health analytics, ingestion, provenance, persistence, research or review; complexity and risk separately |
| Execution | Client/version, requested model/effort, actual runtime model ID/provider/effort, delegates/fallbacks |
| Attribution | `runtime_confirmed`, `owner_reported`, `worker_reported`, `assigned_only`, or `unknown`; selection is not runtime proof |
| Identity | Assigned baseline, first candidate, reviewed candidates, accepted/merged SHA and source links |
| Quality | First-pass verdict, unique confirmed blockers/severity, escaped defects, scope discipline |
| Rework | Substantive correction rounds; formatting-only commits, duplicate comments and unchanged-SHA reruns do not add rounds |
| Evidence | Actual targeted/full/API/browser/CI results; local-reported versus independently inspected; missing evidence explicit |
| Outcome | Candidate review, isolated-slice merge, shared integration, independent review and Owner UAT are separate states |
| Cost/time | Measured tokens/API spend/quota, active work/review/test time and waiting time only when known; otherwise `unknown` |
| Confounders | Unclear assignment, missing review locator, scope changes, resource contention, tool isolation or provider outages |

Do not credit an unconfirmed model identity as fact. Do not count a disproven reviewer finding as a model defect. Record Integrator errors separately. A successful CI rerun proves that attempt passed, not why the earlier run failed. Subscription access does not mean zero resource cost; public list prices do not measure this run's cost.

### Outcome vocabulary

Use the same descriptive categories as Finance #605, only after a case is completed at a named stage:

- A: accepted first substantive candidate.
- B: accepted after 1–2 bounded correction rounds.
- C: accepted after 3+ substantive rounds or material contract drift.
- D: abandoned/replaced implementation.

`PENDING`, `BLOCKED` and `UNVERIFIED` are not D. State the stage and confounders beside any grade; no overall 100-point leaderboard or fabricated plus/minus precision. A leaf acceptance cannot be labelled end-to-end product acceptance.

Group summaries show numerator/denominator, role/profile, client/provider and attribution coverage. Do not pool pure normalization with network/security or canonical-selection work. Small, heterogeneous samples support provisional routing, not equivalence claims. Five comparable cases are a useful collection target, not a statistical guarantee.

## Initial historical index — not rescored

| Source | Recorded assignment | Role/profile | Evidence state in this journal |
| --- | --- | --- | --- |
| [#8](https://github.com/LTstripes/Health-Check/issues/8) | Hermes + Muse Spark 1.3 Contributor | Worker; deterministic weight/body-composition analytics under a frozen contract | `assigned_only`; historical candidate, runtime identity, reviews, rounds and integration outcome must be verified before grading |
| [#19](https://github.com/LTstripes/Health-Check/issues/19) | Hermes + Muse Spark 1.3 Contributor | Worker; pure openScale contract/normalization, excluding network/persistence | `assigned_only`; historical candidate, runtime identity, reviews, rounds and integration outcome must be verified before grading |

These are retrieval pointers, not new claims of success or failure. This initial Health index contains no newly scored cases. Finance's editor cohort is useful routing context only; it does not establish suitability for Health provenance, device attribution, migrations or canonical history.

## Future task proposals

Add two recommendations to the existing short Owner card: **Codex option** (model and supported effort) and **external option** (model and provider/client), with a one-sentence preference/confidence explanation. Either option can be unavailable or not recommended for the risk. The Owner chooses; launch pins one route and the actual runtime identity is recorded later. A concrete model roster belongs to a dated launch or observation, not permanent repository policy.

New/anonymous/temporary-free models start on bounded noncritical tasks using synthetic data, not on migrations, private provider state or security acceptance. Do not guess the vendor behind an alias or assume a preview remains free. Required independent review is unchanged by model price or a successful unrelated task.

Normal outcome logging does not activate an orchestration loop, automatic queue, telemetry collector, new app or blind A/B. Controlled blind A/B requires a separate explicit assignment with identical contract/baseline, isolated workspaces and no candidate cross-reading before comparison.

## Shared laptop budget

One primary Worker; at most two genuinely independent writers in separately assigned workspaces when resources permit. Only one heavyweight local verification process at a time across **both projects and all clients**: full test suites, browser/Playwright, production build or substantial backend suites. Another Worker may read/edit but does not start a competing heavy run. Keep each project's required checks intact; Finance's current local Vitest limit is `--maxWorkers=1`, not a substitute for cross-process coordination. No blanket timeout inflation, excluded failing files or weaker assertions. Do not terminate sibling or Owner-runtime processes.

## Compact case template

```text
case_id / role / profile / complexity / risk:
issue / PR / contract link / baseline:
client + requested model/effort:
actual model/provider/effort + attribution source (or unknown):
first SHA -> attempts -> accepted SHA:
first-pass verdict / substantive fix rounds / confirmed blockers:
scope / test & browser evidence / independent review:
slice integration / aggregate integration / Owner UAT:
measured time/cost (or unknown) / confounders:
provisional use / avoid / next evidence needed:
```

Only technical metadata, synthetic-safe summaries and source links belong here. Never include real health values, private finance values, measurements/photos, credentials, MAC/bind keys, DBs, private screenshots, raw provider payloads or unsanitized model transcripts. Follow `AGENTS.md` and the existing review/private-UAT boundaries.
