# Model evidence journal — Health-Check

Protocol: `model-evidence-v2`, compact intake from 2026-09-28; Owner-attribution clarification and case-table refresh: **2026-09-30**. A dated observational journal for real project tasks, not a permanent ranking of models and not a replacement for acceptance gates.

Coordination/intake: [Health-Check #210](https://github.com/LTstripes/Health-Check/issues/210). Paired journal: [Finance #605](https://github.com/LTstripes/hermes-finance/issues/605) and its `docs/MODEL_BENCHMARK.md`. Cases remain in their originating repository. Do not duplicate Finance outcomes as Health successes. This update changes Health documentation only; it does not claim that Finance's separate files have been updated.

## Evidence and maintenance

The exact issue contract, candidate diff, CI, separate review and Integrator disposition remain authoritative. This file is their compact index, maintained by the Integrator after review together with [Current Execution History](EXECUTION_HISTORY_CURRENT.md). Workers supply evidence; they do not concurrently edit the shared journal.

Record rejected, abandoned and pending attempts as well as successes. Preserve the first-pass outcome after later fixes. Append escaped defects and UAT findings; do not erase them. An implementation model switch, an informal critique and independent review are different events.

### Owner-confirmed attribution

On 2026-09-29 the Owner explicitly confirmed that his account of the model actually used is valid evidence even when a Codex handoff reports `model: unknown`.

- **Runtime-reported:** use the reported label/version and provider/client; self-reported metadata is not an independent provider attestation.
- **Owner-confirmed:** use the model label the Owner says actually ran; preserve the raw client `unknown` and keep effort in a separate context column.
- **Assigned-only:** a recommendation or intended launch is not actual execution evidence. It stays unconfirmed.
- **Unknown:** neither a runtime report nor an explicit Owner confirmation establishes the field.

Use an exact version only when runtime evidence or the Owner explicitly confirms that exact version. Do not retroactively assign today's version to older generic `Sol`/`Astra`/`Luna` records. The earlier Integrator expansion of an older `Sol` run to a guessed numbered version was over-specific. Current confirmed executions may therefore appear as **Luna 6.0** or **Sol 6.1**, while older cases remain generic when that is all the evidence supports. A model name does not establish other unreported metadata. Conflicts remain explicit rather than silently overwritten.

Routine handoffs still contain only:

```text
Model evidence
model: <known model label/version, otherwise unknown>
provider/client: <known provider/client, otherwise unknown>
```

Attribution source and effort below are journal context, not new mandatory handoff fields.

## Common case format

A case is `(repository, issue, role, assigned baseline, initial candidate, execution route)`. Follow-up SHAs are attempts of that case, not independent successes. Record Worker, Reviewer and research/critique roles separately.

| Field | What to record |
| --- | --- |
| Task | Repo/issue/PR; profile; complexity and risk separately |
| Model evidence | `model`; `provider/client`, using runtime-reported or explicit Owner-confirmed information and preserving unknown details |
| Identity | Assigned baseline, first candidate, reviewed candidates, accepted/merged SHA and source links |
| Quality | First-pass verdict, unique confirmed blockers/severity, escaped defects, scope discipline |
| Rework | Substantive correction rounds; formatting-only commits, duplicate comments and unchanged-SHA reruns do not add rounds |
| Evidence | Actual targeted/full/API/browser/CI results; local-reported versus independently inspected; missing evidence explicit |
| Outcome | Candidate review, slice merge, shared integration, independent review and Owner UAT are separate states |
| Cost/time | Measured counters only; otherwise unknown. Not part of the routine two-field block |
| Confounders | Assignment/locator errors, scope changes, resource contention, runtime isolation or provider outages |

A successful CI rerun proves that attempt passed, not why the earlier run failed. Record Integrator errors separately. Do not count a disproven reviewer finding as a model defect.

### Outcome vocabulary

Use descriptive categories only after a case is completed at a named stage:

- A: accepted first substantive candidate.
- B: accepted after 1–2 bounded correction rounds.
- C: accepted after 3+ substantive rounds or material contract drift.
- D: abandoned/replaced implementation.

`PENDING`, `BLOCKED` and `UNVERIFIED` are not D. No overall 100-point leaderboard. Group summaries must retain role/profile, denominator, client/provider and attribution coverage; heterogeneous small samples do not establish model equivalence.

## Cases reconciled on 2026-09-30

These are the cases evidenced in #210 and the current Owner handoffs, not an exhaustive historical model census. Unconfirmed historical work stays below as retrieval pointers. Costs/tokens/active execution times are unknown for these cases unless a linked report explicitly measures them. Owner-refresh wall time is product runtime, not model execution time.

| Case / role | Model | Effort / attribution | Provider/client | First outcome -> current disposition | Substantive fix rounds |
| --- | --- | --- | --- | --- | ---: |
| [#212](https://github.com/LTstripes/Health-Check/issues/212) Worker; bounded transport reliability | Sol | Medium; Owner-reported actual selection in #210; exact runtime version unknown | unknown; Codex was assigned, not independently established by that intake | ACCEPT -> COMPLETE; A at implementation/integration stage | 0 |
| [#203](https://github.com/LTstripes/Health-Check/issues/203) Worker; limited-encoding CLI | DeepSeek V4.1 Flash | Runtime-reported; Owner selected Max | opencode-go / OpenCode | ACCEPT -> COMPLETE; A at implementation/integration stage | 0 |
| Project audit -> #226–#229; research | Astra | Owner-confirmed; effort/version unknown; no model block in audit | unknown | Four findings promoted to backlog; two existing tracks not duplicated. Research accepted, not four independently reproduced application defects | not applicable |
| [#226](https://github.com/LTstripes/Health-Check/issues/226) Worker; screenshot provenance | Sol | High; Owner-confirmed; raw client model was unknown | OpenAI / Codex desktop | ACCEPT -> COMPLETE; A at implementation/integration stage | 0 |
| #226 independent semantic Reviewer | DeepSeek V4.1 Flash | Runtime-reported; effort not established by returned block | opencode-go / OpenCode | ACCEPT, no blockers; separate review gate satisfied | not applicable |
| [#227](https://github.com/LTstripes/Health-Check/issues/227) Worker + remediation; coherent reads | Astra | Medium; Owner-confirmed for both attempts; raw client model was unknown | OpenAI / Codex desktop | FIXES REQUIRED -> remediation ACCEPT -> COMPLETE; B at implementation/integration stage | 1 |
| #227 independent Reviewer + re-review | Sol | High; Owner-confirmed; raw client model was unknown | OpenAI / Codex desktop | Found one accepted cached-before-BEGIN identity-map blocker; re-review ACCEPT | not applicable |
| [#228](https://github.com/LTstripes/Health-Check/issues/228) Phase 1 researcher | Sol | High; Owner-confirmed; no compact model block returned | unknown | Research ACCEPTED; implementation PARKED pending trustworthy event-identity contract | not applicable |
| [#229](https://github.com/LTstripes/Health-Check/issues/229) Worker; corrected-sidecar workflow | DeepSeek V4.1 Flash | Max; Owner-confirmed exact model/effort | opencode-go / OpenCode | Candidate delivered; exact-head CI SUCCESS; independent semantic ACCEPT still missing. PENDING, ungraded | not finalized |
| #229 independent Reviewer attempt | Sol 6.1 | High; Owner-confirmed exact model/effort; raw client model was unknown | OpenAI / Codex | BLOCKED / INCONCLUSIVE before semantic review: review runtime inventory not isolated; candidate unchanged | not applicable |
| [#233](https://github.com/LTstripes/Health-Check/issues/233) Worker; test-reliability/privacy oracle | Luna 6.0 | Medium; Owner-confirmed exact model/effort; raw client model was unknown | OpenAI / Codex desktop | ACCEPT -> COMPLETE; A at bounded test-reliability stage | 0 |
| [#214](https://github.com/LTstripes/Health-Check/issues/214) Owner-controlled local operations | unknown | No confirmation of the actual model; earlier Luna recommendation is assigned-only | Codex; provider/client version not reported | Scheduler configured and manual validation PASS; untouched automatic-run proof remains pending | not applicable |

### Candidate and gate index

| Case | Baseline -> candidate(s) | Integration / evidence |
| --- | --- | --- |
| #212 | `9468ad7ab347fdf1ef0bf8a6fbac9a8528a4ba83` -> `7738c066e6a785d81d5aa62242dfe1fc062a6f38` | [Intake](https://github.com/LTstripes/Health-Check/issues/210#issuecomment-5858832727); PR #213; exact-head `36340791539`, exact-main `36342547115` SUCCESS |
| #203 | `9ac6cb03e3cef2b7b5b321bcf88194c704df3bb2` -> `6650861856b901010489be4abd888ac5cd99ef3e` | PR #225 -> `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`; CI `36454254338` / `36455331957` / `36455940446` SUCCESS |
| #226 | `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e` -> `0f0ff31d53b0d37c4e8c48eb86c247fbb1b284f3` | [Closeout](https://github.com/LTstripes/Health-Check/issues/226#issuecomment-5897748347); PR #230 -> `18e0142a4f7562394c7ddfb1bac55cf473fac9f5`; CI `36616892861` / `36621443529` SUCCESS; included in green combined main `36623160664` |
| #227 | `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e` -> rejected `dbdd780580964973496f2d5fcdbeca214681cc83` -> accepted `2a6bae478a99c9e75ef01dcf644d2825124848c0` | [Blocker](https://github.com/LTstripes/Health-Check/issues/227#issuecomment-5897163549), [closeout](https://github.com/LTstripes/Health-Check/issues/227#issuecomment-5897749064); PR #231 -> `f8ed3b5bd11ebec06b3fe583091ec5aa729bb38d`; final head/PR/main CI `36620266088` / `36622573834` / `36623160664` SUCCESS |
| #228 | Read-only `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`; no implementation SHA | [Research acceptance](https://github.com/LTstripes/Health-Check/issues/228#issuecomment-5897048424); no full two-image import/E2E claim |
| #229 | `f8ed3b5bd11ebec06b3fe583091ec5aa729bb38d` -> `532a069c2b1253b4a3ce88c56f8d3b843f6b2f05` | Exact-head CI `36628220352` SUCCESS. Worker: DeepSeek V4.1 Flash Max, Owner-confirmed. First Sol 6.1 High independent-review attempt stopped before semantics on non-isolated review runtime; repeat isolated review required |
| #233 | `f8ed3b5bd11ebec06b3fe583091ec5aa729bb38d` -> `37df19ba11b3f1e32b58d49319fdc0afe3b555ca` | PR #234 -> `f6939f531d4384e28fa9bd65fce59b498a0e6032`; exact-head/PR/main CI `36632773686` / `36633662826` / `36634392128` SUCCESS; test-only Integrator ACCEPT |
| #214 | Owner operational configuration, not a product candidate | [Operational record](https://github.com/LTstripes/Health-Check/issues/214#issuecomment-5896581801); manual selected-stream run 35m32.734s; automatic attempt interrupted, cause not established |

### Interpretation and confounders

Four completed product-implementation cases are indexed here (#212/#203/#226/#227), plus one completed bounded test-reliability case (#233). Three product cases were accepted without substantive remediation; #227 required one real correction round; #233 was accepted first candidate. These are heterogeneous denominators, not a cross-model win rate. Reviewer/research attempts stay separate. #229 and #214 remain ungraded at unfinished stages.

- #203: DeepSeek delivered a bounded CLI fix first pass; the earlier Astra recommendation was excessive for this low-risk task, an Integrator routing issue.
- #226: small diff but C3 provenance risk; Sol implementation and DeepSeek review are separate contributions.
- #227: initial test coverage missed clean ORM objects cached before caller BEGIN; Sol's review found the real blocker and Astra Medium repaired it. Preserve that first-pass finding after final acceptance. The initial Windows cleanup failure and failed review-runtime isolation are separate infrastructure confounders, not additional semantic bugs or remediation rounds.
- #228: refusing unsupported automatic cross-image dedup is a useful research outcome, not implementation failure.
- #229: the prior issue note named `18e0142...` while the final Owner prompt named `f8ed3b5...`; the delivered candidate follows the final prompt. Worker is Owner-confirmed DeepSeek V4.1 Flash Max. The first Sol 6.1 High review attempt was blocked by review-runtime isolation before semantics and is not a candidate defect or fix round.
- #233: Luna 6.0 Medium repaired a deterministic test-oracle collision first candidate; production privacy behavior was untouched.
- The initial #226/#227 task choices were recommendations, not evidence that DeepSeek/Astra High ran. Owner later confirmed Sol High and Astra Medium respectively.

Provisional routing remains task-specific: inexpensive models for bounded low-risk work; Sol for established multi-file contracts; reserve Astra for difficult analysis, concurrency or unresolved semantics. C3 independent review is not optional because a model is premium or a diff is small.

## Initial historical index — not rescored

| Source | Recorded assignment | Role/profile | Evidence state in this journal |
| --- | --- | --- | --- |
| [#8](https://github.com/LTstripes/Health-Check/issues/8) | Hermes + Muse Spark 1.3 Contributor | Worker; deterministic weight/body-composition analytics under a frozen contract | assigned_only; verify candidate, actual identity, review and outcome before grading |
| [#19](https://github.com/LTstripes/Health-Check/issues/19) | Hermes + Muse Spark 1.3 Contributor | Worker; pure openScale contract/normalization | assigned_only; not a new claim of success or failure |
| #217/#219/#221 screenshot workflow | Not established in the current model intake | Implementation / skill / Owner-assisted extraction | Product live closeout is recorded in execution history; no retrospective model grade or identity invented |

## Future task proposals

Add two recommendations to the existing short Owner card: **Codex option** and **external option**, with preference/confidence. The Owner chooses; record actual execution from runtime evidence or explicit Owner confirmation. Concrete rosters belong to dated launches, not permanent policy.

New/anonymous/temporary-free models start on bounded noncritical synthetic tasks, not migrations, private provider state or security acceptance. Normal outcome logging does not activate orchestration, an automatic queue, telemetry or blind A/B.

## Shared laptop budget

One primary Worker; at most two independent writers in separately assigned workspaces when resources permit. Only one heavyweight local verification process at a time across both projects and all clients. Another Worker may read/edit but must not start a competing heavy run. No blanket timeout inflation, excluded failing tests, weaker assertions or termination of sibling/Owner-runtime processes.

## Compact case template

```text
case_id / role / profile / complexity / risk:
issue / PR / contract link / baseline:
model:
provider/client:
identity source and raw unknown/Owner-confirmed context:
first SHA -> attempts -> accepted SHA:
first-pass verdict / substantive fix rounds / confirmed blockers:
scope / actual checks / independent review:
integration / Owner UAT / limitations:
measured time/cost (or unknown) / confounders:
```

Only technical metadata, synthetic-safe summaries and source links belong here. Never include real measurements, private screenshots, credentials, raw provider payloads, databases or unsanitized model transcripts.
