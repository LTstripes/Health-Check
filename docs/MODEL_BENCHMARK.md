# Model evidence journal — Health-Check

Protocol: `model-evidence-v2`, compact intake from 2026-09-28; Owner-attribution clarification and case-table refresh: **2026-10-01**. A dated observational journal for real project tasks, not a permanent ranking of models and not a replacement for acceptance gates.

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


## Cases reconciled on 2026-10-01

These are evidenced project cases, not a leaderboard. Costs/tokens/active execution times remain unknown unless explicitly measured. Owner-refresh wall time is product runtime, not model execution time.

| Case / role | Model | Effort / attribution | Provider/client | First outcome -> current disposition | Substantive fix rounds |
| --- | --- | --- | --- | --- | ---: |
| [#212](https://github.com/LTstripes/Health-Check/issues/212) Worker; bounded transport reliability | Sol | Medium; Owner-reported actual selection; exact runtime version unknown | unknown | ACCEPT -> COMPLETE | 0 |
| [#203](https://github.com/LTstripes/Health-Check/issues/203) Worker; limited-encoding CLI | DeepSeek V4.1 Flash | Max; runtime-reported / Owner-selected | opencode-go / OpenCode | ACCEPT -> COMPLETE | 0 |
| Project audit -> #226–#229; research | Astra | Owner-confirmed; effort/version unknown | unknown | Four findings promoted to backlog; research evidence only | not applicable |
| [#226](https://github.com/LTstripes/Health-Check/issues/226) Worker; screenshot provenance | Sol | High; Owner-confirmed; raw client model unknown | OpenAI / Codex desktop | ACCEPT -> COMPLETE | 0 |
| #226 independent semantic Reviewer | DeepSeek V4.1 Flash | Runtime-reported | opencode-go / OpenCode | ACCEPT | not applicable |
| [#227](https://github.com/LTstripes/Health-Check/issues/227) Worker + remediation; coherent reads | Astra | Medium; Owner-confirmed | OpenAI / Codex desktop | FIXES REQUIRED -> remediation ACCEPT -> COMPLETE | 1 |
| #227 independent Reviewer + re-review | Sol | High; Owner-confirmed | OpenAI / Codex desktop | Found cached-before-BEGIN blocker -> ACCEPT after fix | not applicable |
| [#228](https://github.com/LTstripes/Health-Check/issues/228) Phase 1 researcher | Sol | High; Owner-confirmed | unknown | Research ACCEPTED; implementation PARKED | not applicable |
| [#229](https://github.com/LTstripes/Health-Check/issues/229) Worker; corrected-sidecar workflow | DeepSeek V4.1 Flash | Max; Owner-confirmed exact model/effort | opencode-go / OpenCode | FIXES REQUIRED by external reviewer -> remediation ACCEPT -> COMPLETE | 1 |
| #229 Codex Reviewer attempts | Sol 6.1 | High; Owner-confirmed exact model/effort | OpenAI / Codex | Two BLOCKED / INCONCLUSIVE pre-semantic runtime-isolation attempts | not applicable |
| #229 independent semantic Reviewer + re-review | GPT-6 Astra Pro | Owner-confirmed exact model | OpenAI / ChatGPT | Found SQLite signed-zero fingerprint blocker -> re-review ACCEPT | not applicable |
| [#233](https://github.com/LTstripes/Health-Check/issues/233) Worker; test reliability/privacy oracle | Luna 6.0 | Medium; Owner-confirmed exact model/effort | OpenAI / Codex desktop | ACCEPT -> COMPLETE | 0 |
| [#181](https://github.com/LTstripes/Health-Check/issues/181) Worker; Windows cleanup/CI provenance | Sol 6.1 | High; Owner-confirmed exact model/effort | OpenAI / Codex | Multiple bounded security/lifecycle refinements -> reviewed candidate ACCEPT; later exact-main escape repaired separately | 2 Worker remediation rounds |
| #181 independent security Reviewer | GPT-6 Astra Pro | Owner-confirmed exact model | OpenAI / ChatGPT | Found transcript blocker; accepted narrow CreationTime reuse contract; final reviewed Worker candidate ACCEPT | not applicable |
| #181 post-main Integrator follow-up | GPT-5.6 Sol | Very high; Owner-selected current Integrator route | OpenAI / ChatGPT | Reproduced retained WMI transient -> bounded polling repair -> COMPLETE | 1 escaped follow-up |
| [#214](https://github.com/LTstripes/Health-Check/issues/214) Owner-controlled local operations | unknown | No confirmed implementation model | Codex/client details incomplete | Scheduler configured and manual PASS; untouched automatic proof pending | not applicable |


### Candidate and gate index

| Case | Baseline -> candidate(s) | Integration / evidence |
| --- | --- | --- |
| #212 | `9468ad7...` -> `7738c066...` | PR #213; exact-head `36340791539`, exact-main `36342547115` SUCCESS |
| #203 | `9ac6cb0...` -> `6650861...` | PR #225 -> `aafc407...`; CI `36454254338` / `36455331957` / `36455940446` SUCCESS |
| #226 | `aafc407...` -> `0f0ff31...` | PR #230 -> `18e0142...`; CI `36616892861` / `36621443529` SUCCESS |
| #227 | `aafc407...` -> rejected `dbdd780...` -> accepted `2a6bae4...` | PR #231 -> `f8ed3b5...`; final head/PR/main CI `36620266088` / `36622573834` / `36623160664` SUCCESS |
| #228 | read-only `aafc407...`; no implementation SHA | Research accepted; no cross-image implementation |
| #233 | `f8ed3b5...` -> `37df19b...` | PR #234 -> `f6939f5...`; exact-head/PR/main CI `36632773686` / `36633662826` / `36634392128` SUCCESS |
| #181 | `f6939f5...` -> `ce43eca...` -> `96d710c...` -> reviewed `a23edfc...` -> escaped follow-up `eeafc91...` | PR #236 -> `19f8201...` exposed exact-main WMI transient; PR #237 -> `783938d...`; final CI `36817301838` / `36817662855` / `36818078133` SUCCESS |
| #229 | `f8ed3b5...` -> `532a069...` -> remediated `f0b77da...` | exact-head `36672586650` SUCCESS; GPT-6 Astra Pro ACCEPT; fresh PR #235 `36818522332` SUCCESS; merged `ac1df6d...`; exact-main `36818997839` SUCCESS |
| #214 | Owner operational configuration, not a product candidate | Manual selected-stream run 35m32.734s; untouched automatic proof still pending |


### Interpretation and confounders

Completed product-implementation cases in this current journal include #212/#203/#226/#227/#229, with #233 as a bounded test-reliability case and #181 as a separate CI/security-reliability case. This is a heterogeneous sample, **not a cross-model win rate**.

- #229 is a useful role-separation example: DeepSeek V4.1 Flash Max implemented the feature; two Sol 6.1 Codex review attempts were blocked by tooling before semantics; GPT-6 Astra Pro then found a real SQLite signed-zero blocker; DeepSeek remediated it; Astra re-review ACCEPT.
- #181 should not be reduced to a model score. Sol 6.1 delivered the main reliability line and bounded review remediations; GPT-6 Astra Pro found the transcript weakness and constrained the CreationTime contract; after the reviewed candidate merged, exact-main exposed a real WMI transient that the Integrator repaired separately with GPT-5.6 Sol. The red exact-main run remains part of the evidence rather than being erased by later green gates.
- #227 likewise preserves its first-pass blocker after final acceptance.
- #233 demonstrates that even a test-only privacy oracle deserves collision-safe structure rather than substring heuristics.
- #228's refusal to invent fuzzy cross-image identity is an accepted research outcome, not failure.
- Assignment/recommendation remains distinct from actual execution evidence.

Routing remains task-specific: inexpensive models for bounded low-risk work; stronger models for cross-layer/concurrency/security semantics; C3 independent review remains risk-based and is not waived because a model is premium.

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
