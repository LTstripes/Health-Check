# Model evidence journal — Health-Check

Protocol: `model-evidence-v2`, compact intake from 2026-09-28; latest reconciliation: **2026-10-01 after #214 automatic-run acceptance**. This is an observational journal for real project work, not a permanent model ranking or a replacement for acceptance gates.

Coordination: [#210](https://github.com/LTstripes/Health-Check/issues/210). Finance's paired journal is separate; this update does not change Finance or count its outcomes as Health successes. See [Current History](EXECUTION_HISTORY_CURRENT.md) and the byte-preserved [preceding journal](MODEL_BENCHMARK_THROUGH_2026-10-01_RELIABILITY.md) for the prior exact record.

## Evidence and maintenance

The issue contract, exact diff, CI, independent review and Integrator disposition are authoritative. Preserve first-pass findings, useful failed attempts and escaped defects after later successes. Follow-up commits are attempts of one case, not separate wins. Worker, Reviewer, research and Owner operations are distinct roles.

### Owner-confirmed attribution

The Owner's explicit confirmation of the model actually used is accepted even when Codex prints unknown. Preserve the raw unknown and record effort/source separately from the two-field block. Proposed assignments/subscription labels are not execution evidence. Do not retroactively number older generic Sol/Astra/Luna records or expand aliases into unreported versions. Self-reported runtime metadata is not independent provider attestation. Conflicting sources remain explicit.

```text
Model evidence
model: <known model label/version, otherwise unknown>
provider/client: <known provider/client, otherwise unknown>
```

Workers do not edit shared journals or grade themselves. Unknown timing/cost/token counts remain unknown. Owner-refresh duration is product runtime, not model execution time.

## Common case format

A case is repository/issue/role/baseline/initial-candidate/execution route. Record exact candidate and integration references, first-pass verdict, substantive remediation rounds, actual checks, escaped findings, independent-review status and remaining Owner gates. Keep recommendations and actual execution separate.

A successful rerun proves that attempt passed, not the cause of the prior failure. Formatting-only changes and duplicate comments are not remediation rounds. Integrator process errors and blocked runtime preflights are not semantic model findings.

### Outcome vocabulary

A: first substantive candidate accepted. B: accepted after 1–2 bounded corrections. C: 3+ substantive rounds or material contract drift. D: abandoned/replaced. Pending/blocked/unverified is not D. Use descriptive outcomes only at a named completed stage. Heterogeneous small samples do not establish model equivalence or a cross-model win rate.

## Cases reconciled on 2026-10-01

| Case / role | Model | Effort / attribution | Provider/client | Outcome | Substantive rework |
| --- | --- | --- | --- | --- | --- |
| #212 Worker, transport reliability | Sol | Medium, Owner-reported; exact version unknown | unknown | ACCEPT / COMPLETE | 0 |
| #203 Worker, limited-encoding CLI | DeepSeek V4.1 Flash | Max, runtime/Owner evidence | opencode-go / OpenCode | ACCEPT / COMPLETE | 0 |
| Project audit leading to #226–#229 | Astra | Owner-confirmed; exact version/effort unknown | unknown | Four findings promoted; research, not four completed implementations | not applicable |
| #226 Worker, screenshot provenance | Sol | High, Owner-confirmed; raw client unknown | OpenAI / Codex desktop | ACCEPT / COMPLETE | 0 |
| #226 independent review | DeepSeek V4.1 Flash | Runtime-reported | opencode-go / OpenCode | ACCEPT | not applicable |
| #227 Worker/remediation | Astra | Medium, Owner-confirmed | OpenAI / Codex desktop | FIXES REQUIRED -> remediation ACCEPT / COMPLETE | 1 |
| #227 independent review/re-review | Sol | High, Owner-confirmed | OpenAI / Codex desktop | Found pre-BEGIN ORM cache blocker; re-review ACCEPT | not applicable |
| #228 Phase 1 research | Sol | High, Owner-confirmed | unknown | Research ACCEPTED; implementation PARKED | not applicable |
| #229 Worker/remediation | DeepSeek V4.1 Flash | Max, Owner-confirmed exact label | opencode-go / OpenCode | Signed-zero fix -> Astra ACCEPT / COMPLETE | 1 |
| #229 blocked review attempts | Sol 6.1 | High, Owner-confirmed | OpenAI / Codex | Two pre-semantic isolation BLOCKED attempts; no code findings | not applicable |
| #229 external review/re-review | GPT-6 Astra Pro | Owner-confirmed exact label | OpenAI / ChatGPT | Found SQLite signed-zero fingerprint blocker; re-review ACCEPT | not applicable |
| #233 Worker, privacy test oracle | Luna 6.0 | Medium, Owner-confirmed | OpenAI / Codex desktop | First-candidate ACCEPT / COMPLETE | 0 |
| #181 Worker, Windows cleanup / CI | Sol 6.1 | High, Owner/runtime-reported | OpenAI / Codex | Reviewed candidate ACCEPT; separate post-main escape retained | 2 Worker remediation rounds |
| #181 external security review | GPT-6 Astra Pro | Owner-confirmed | OpenAI / ChatGPT | Transcript blocker; constrained CreationTime contract; ACCEPT on a23edfc | not applicable |
| #181 Integrator post-main follow-up | GPT-5.6 | Very high, Owner-selected route; prior journal called this GPT-5.6 Sol without a separate runtime attestation | OpenAI / ChatGPT | Bounded WMI polling follow-up, PR/main gates green | 1 separate escaped follow-up |
| #214 Owner-controlled local setup | unknown | Actual model not confirmed; proposed route is not evidence | Codex details incomplete | Setup/manual proof followed by Owner automatic-run acceptance | not a scored model case |
| #214 automatic/logon run | not applicable | Owner live operational evidence, not model inference | Windows Task Scheduler / existing Ops runner | Operational PASS / CLOSED; freshness caveat split to #238 | not applicable |
| #238 issue intake | not assigned | No Worker launched or candidate produced | not applicable | Contract checkpoint pending; not an implementation success | not applicable |

The legacy expanded GPT-5.6 Sol follow-up label is retained in the archival journal; the current table uses only the version the Owner explicitly selected. This is an attribution clarification, not a reassignment of Sol 6.1 Worker work or of the prior Astra review.

### Candidate and gate index

| Case | Candidate / lineage | Integration evidence |
| --- | --- | --- |
| #212 | 7738c066 from 9468ad7 | PR #213; head 36340791539, main 36342547115 SUCCESS |
| #203 | 6650861 from 9ac6cb0 | PR #225; head/PR/main 36454254338 / 36455331957 / 36455940446 SUCCESS |
| #226 | 0f0ff31 from aafc407 | PR #230; head/PR 36616892861 / 36621443529 SUCCESS |
| #227 | dbdd780 -> 2a6bae4 | PR #231; head/PR/main 36620266088 / 36622573834 / 36623160664 SUCCESS |
| #228 | Read-only aafc407; no implementation SHA | Research accepted, no cross-image implementation |
| #233 | 37df19b from f8ed3b5 | PR #234; head/PR/main 36632773686 / 36633662826 / 36634392128 SUCCESS |
| #181 | ce43eca -> 96d710c -> a23edfc; later eeafc91 | PR #236 exposed exact-main escape; PR #237 head/PR/main 36817301838 / 36817662855 / 36818078133 SUCCESS |
| #229 | 532a069 -> f0b77da | head 36672586650; refreshed PR #235 36818522332; main 36818997839 SUCCESS |
| Docs #232 | affe3dc -> main 4029fd8 | PR 36820041558 / main 36820492189 SUCCESS; #224 superseded |
| #214 | Last observed Owner code aafc407; no new product commit | Automatic run reported 2026-10-01; Ready/result 0; final successful seven-day report, all four layers succeeded, 19m03.819s; #238 retains stale disabled-HR aggregate |

Full exact SHAs and review boundaries remain in issue closeouts and current/archived execution history.

### Interpretation and confounders

- #229: DeepSeek implemented, Codex/Sol review preflights could not start, Astra found a real SQLite edge, DeepSeek remediated and Astra accepted. Do not count blocked preflights as substantive failures.
- #181: keep Worker remediation, contract review and the later Integrator patch separate. The external ACCEPT on a23edfc is not an invented review of eeafc91. Historical red exact-main remains evidence, not erased by later green gates.
- #227's first-pass ORM defect remains recorded after acceptance.
- #233 demonstrates collision-safe structural testing rather than substring matching.
- #228's refusal to invent identity is useful research, not implementation failure.
- #214 proves an Owner run, not a model benchmark. The 19-minute versus earlier 35-minute durations are uncontrolled operational samples. Its owner/Google freshness aggregates remain stale due to intentionally disabled HR; #238 is open.
- Earlier claims of unavailable GitHub tooling or of active execution without tool calls were Integrator process errors, not evidence of permission loss or completed operations.

## Initial historical index — not rescored

| Source | Historical assignment | Evidence boundary |
| --- | --- | --- |
| #8 | Hermes + Muse Spark 1.3 Contributor, Weight analytics | Assigned-only in this journal; verify actual run/candidate/review before grading |
| #19 | Hermes + Muse Spark 1.3 Contributor, openScale contract | Assigned-only; no invented outcome |
| #217/#219/#221 | Model not established in current intake | Live product proof is in history; no retrospective model identity/grade |

## Future task proposals

Provide one Codex option and one external/OpenCode option, with a task-specific preference. Use the Owner-confirmed roster as launch context, not permanent policy. Inexpensive models suit bounded low-risk work; stronger models and separate review are appropriate for concurrency/provenance/security semantics. New/untested models start on bounded noncritical synthetic work, not migrations or security acceptance.

## Shared laptop budget

One primary Worker; at most two independent writers in separately assigned workspaces when resources permit. Only one heavyweight local verification across projects/clients at a time. No blanket timeout inflation, excluded failures, weaker assertions or killing sibling/Owner processes.

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

Only sanitized technical metadata and source links belong here. Never publish private measurements, screenshots, credentials, raw provider reports or unfiltered transcripts.
