# Current Execution History

Current handoff: **2026-09-29**. Older R00–R05 and post-release history through 2026-09-27 is preserved byte-for-byte in [EXECUTION_HISTORY_THROUGH_2026-09-27.md](EXECUTION_HISTORY_THROUGH_2026-09-27.md); it is a historical snapshot, not current launch guidance. The verbose engineering log remains in [EXECUTION_HISTORY.md](EXECUTION_HISTORY.md) and GitHub.

Only sanitized technical evidence belongs here. Private measurements, screenshots, credentials, databases and raw reports remain outside Git.

## Canonical checkpoint

Accepted product main before this docs-only refresh:
`f6939f531d4384e28fa9bd65fce59b498a0e6032`.

Exact-main CI [36634392128](https://github.com/LTstripes/Health-Check/actions/runs/36634392128): SUCCESS, all mandatory lanes including Windows smoke and final checks.

This includes #226 / PR #230, #227 / PR #231 and test-only reliability fix #233 / PR #234. #229 remains a task-branch candidate; it is not part of released main. Re-read GitHub main/CI for every later launch. GitHub product integration does not itself deploy to the local Owner checkout/Stable runtime.

## 2026-09-28 — Owner Weight screenshot workflow

The optional physical S400/openScale path reached Health-Check transport/auth, then exposed a numeric `userId` versus string receiver compatibility issue. #153 stays open, but is no longer a prerequisite for Weight accumulation.

The accepted routine path is screenshot -> repo skill -> strict Owner-assisted extraction -> existing R01 photo pipeline -> Stable:

| Slice | Delivered |
| --- | --- |
| #217 / PR #218 | One-command Owner screenshot import with bounded fail-closed auto-confirm |
| #219 / PR #220 | Repo-scoped `health-weight-screenshot-import` skill |
| #221 / PR #222 | Strict Owner-assisted structured extraction without requiring a second external vision API |

The actual Stable gate proved OLD and NEW `IMPORTED`, exact NEW replay `DUPLICATE`, two additional measurement sessions, canonical Weight updated, historical evidence unchanged and no exact-replay semantic duplicate. This does not prove every cross-image/revision case; later audit follow-ups are distinct.

Checkpoint after screenshot work: `b9a3ab2678f6c5d3ada6a575be48a03811aacef4`; exact-main CI `36442128547` SUCCESS. Compact two-field model reporting then merged via PR #223 to `9ac6cb03e3cef2b7b5b321bcf88194c704df3bb2`, CI `36447735415` SUCCESS.

## 2026-09-28 — #203 limited-encoding Period Brief CLI

Worker: DeepSeek V4.1 Flash, opencode-go / OpenCode (runtime-reported); Owner selected Max. Candidate `6650861856b901010489be4abd888ac5cd99ef3e` from `9ac6cb03e3cef2b7b5b321bcf88194c704df3bb2`.

The bounded stdout strategy escapes characters unrepresentable in cp1251/ASCII while leaving UTF-8 rendering and evidence packets unchanged. Worker reported before/after reproduction plus regression, 39 affected tests, Ruff/migration/diff checks. Integrator reviewed the two-file diff; first substantive candidate accepted, no remediation round.

PR #225 merged to `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`. Candidate/PR/main CI `36454254338` / `36455331957` / `36455940446` all SUCCESS. #203 COMPLETE.

## 2026-09-28 to 2026-09-29 — #214 collection operationalization

Phase A read-only Stable inventory was accepted. Garmin history did not justify a broad backfill. Google history was stream-dependent; a historical sample-HR gap was identified, but pre-July provider availability was not established. Weight and Context remain event-driven/manual, not daily provider coverage.

The ten-day full catch-up on accepted code succeeded in 117m06.216s and populated Stable Training. Owner then chose high-frequency Google `heart_rate` OFF in the local Ops runner, with a reversible flag, because Garmin remains the primary HR source. Other normal Google streams, fixed wearables sleep, Garmin and Training remain enabled. No retained history was deleted; the sample-HR gap is intentionally not backfilled while disabled, not labelled complete.

Scheduler setup was Owner-controlled. Battery restrictions initially blocked execution. Codex later reported daily 10:30 plus Owner-logon triggers, StartWhenAvailable, one-instance behavior, allowed battery start and no stop merely on battery transition. Only local task settings were changed in that operational check; product code/runner were reported unchanged.

Operational evidence:

- initial automatic attempt: `0xC000013A`, no final JSON; cause not established;
- subsequent manual Scheduler run: exit 0, all four layers succeeded, HR OFF and no new sample-HR observations;
- runtime: 35m32.734s; latest persisted dates across Garmin/Google/Training/wearables sleep: 2026-09-29;
- actual in-flight Stop was not tested; no graceful-cancellation proof;
- no historical backfill executed.

**#214 remains open for one untouched successful automatic run with final report and honest freshness.** Manual validation is not scheduled-run proof. Runtime comparisons are observational, not a controlled speedup. The runbook also distinguishes battery policy from laptop sleep/logon behavior.

Authoritative record: [#214](https://github.com/LTstripes/Health-Check/issues/214#issuecomment-5896581801). #215 still needs a real Owner-authored note/read-back; no entry was invented by an agent.

## 2026-09-29 — project audit and bounded follow-ups

Owner identifies the project auditor as Astra; exact version/effort/client were not supplied. Four new code-risk/workflow findings became #226–#229; existing #181 and #214/#215 were not duplicated. Function-level/SQLite mechanism probes are not represented as full Owner/application E2E proof.

Parallel launch was bounded: #226 and #227 separate writers/workspaces; #228 read-only researcher; #229 held behind #226 to avoid screenshot ownership overlap. No automatic task queue was authorized.

### #226 — screenshot algorithm/provenance guard — COMPLETE

- Worker: Sol / High, Owner-confirmed; raw client block: model unknown, OpenAI / Codex desktop.
- Candidate: `0f0ff31d53b0d37c4e8c48eb86c247fbb1b284f3` from `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`.
- Scope: two files, +133/-0. Foreign algorithm/group or conflicting existing producer/metric-family metadata cannot auto-confirm; omitted permitted version remains unknown. No historical repair/schema change.
- Worker reports 92 focused photo tests and quality checks; exact-head CI `36616892861` SUCCESS.
- Independent semantic reviewer: DeepSeek V4.1 Flash / opencode-go / OpenCode, ACCEPT with no blockers.
- PR #230 gate `36621443529` SUCCESS; merged `18e0142a4f7562394c7ddfb1bac55cf473fac9f5`; subsequent combined exact-main gate `36623160664` includes this tree and passed.

[Closeout](https://github.com/LTstripes/Health-Check/issues/226#issuecomment-5897748347). First-pass implementation acceptance; no substantive remediation.

### #227 — coherent SQLite/ORM compound reads — COMPLETE after remediation

- Worker and remediation: Astra / Medium, Owner-confirmed; raw client model unknown, OpenAI / Codex desktop. No model switch occurred.
- Original candidate: `dbdd780580964973496f2d5fcdbeca214681cc83` from the same `aafc407...` baseline.
- Initial helper held a physical snapshot but reused caller-owned transactions without expiring clean pre-BEGIN ORM objects.
- Independent Sol / High reviewer demonstrated an actual import-queue contradiction: stale ORM versus direct SQLite inside the same transaction. FIXES REQUIRED; this was one real semantic blocker, not the CI flake.
- Remediation: `2a6bae478a99c9e75ef01dcf644d2825124848c0`. Guard pending new/dirty/deleted state before cache actions; align clean identity-map state for new/reused physical transactions; preserve flushed writes and caller-owned commit/rollback.
- Worker reports six new before/after variants, 23 snapshot and 129 affected tests PASS. Independent Sol re-review ACCEPT.
- Original Windows smoke failure `36617534245` remains #181 evidence; failed review-runtime isolation is a separate infrastructure limitation, not another completed review.
- Final exact-head/PR/main CI `36620266088` / `36622573834` / `36623160664` SUCCESS.
- PR #231 merged to `f8ed3b5bd11ebec06b3fe583091ec5aa729bb38d` without global writer/migration/provider changes.

[Blocker](https://github.com/LTstripes/Health-Check/issues/227#issuecomment-5897163549), [closeout](https://github.com/LTstripes/Health-Check/issues/227#issuecomment-5897749064). One substantive correction round, preserved in the model journal.

### #228 — cross-image identity research — ACCEPTED / implementation PARKED

Sol / High, Owner-confirmed, completed read-only Phase 1 on `aafc407...`; no implementation branch/commit. Exact bytes identify an artifact, not a real weigh-in across different images. Existing persisted fields could hold a proven event link, but current extraction supplies no trustworthy source-event ID. Date/value/timestamp resemblance is not an accepted uniqueness contract.

[Integrator decision](https://github.com/LTstripes/Health-Check/issues/228#issuecomment-5897048424): no fuzzy auto-dedup, no automatic history repair or migration now. Research accepted; issue remains parked until a trustworthy identity/Owner-decision contract exists.

### #229 — changed-sidecar review workflow — CANDIDATE ONLY

Owner confirms the #229 Worker as DeepSeek V4.1 Flash, Max, provider/client `opencode-go / OpenCode`. The candidate's own compact report did not carry that exact identity; the journal preserves the Owner-confirmed source explicitly.

Candidate: `532a069c2b1253b4a3ce88c56f8d3b843f6b2f05`, branch `task/229-owner-screenshot-correction`, actual baseline `f8ed3b5bd11ebec06b3fe583091ec5aa729bb38d`. The older issue note named `18e0142...`; the final Owner launch and delivered branch used `f8ed3b5...`. [Integrator clarified this](https://github.com/LTstripes/Health-Check/issues/229#issuecomment-5898555102); no Worker fault/rebase is inferred.

Five-file diff, +794/-81, proposes pending `correction:` evidence sets and existing review/revision reuse without schema changes. Worker reports 104 focused and 292 app-ingest tests PASS plus quality checks. [Exact-head CI](https://github.com/LTstripes/Health-Check/actions/runs/36628220352) and current review status belong to the issue; no implementation ACCEPT/merge is claimed here. Independent semantic review is required before canonical promotion.

## Model-attribution reconciliation

The Owner explicitly asked that his report of the model actually used be trusted when the client prints unknown. [AGENTS](../AGENTS.md), [routing](MODEL_ROUTING.md) and the [journal/table](MODEL_BENCHMARK.md) now accept that source while retaining raw client evidence and unknown finer details.

Use Sol, Astra or DeepSeek exactly as established, with effort separate. The earlier Integrator expansion to GPT-5.6 Sol was unsupported and is corrected to Sol / High, Owner-confirmed. Recommendations are not execution evidence. #227's first-pass blocker and remediation remain one Worker case; independent reviews/research are not counted as extra implementation successes.

## Documentation reconciliation and next work

The stale docs-only PR #224 carried useful screenshot/handoff facts but still described #203 as next work and had red CI. This refresh incorporates its relevant content plus later accepted work from current main instead of merging the obsolete handoff. Close/supersede #224 only after this replacement is safely published; preserve its failure/history evidence.

Next proposed order: #229 independent review/integration; #214 untouched scheduled proof and #215 real note; #181 separate CI reliability repair; #148 protection/recovery design and delivery. #181 can proceed independently with explicit file ownership; no new worker launch is implicit in this documentation update.

The [roadmap](ROADMAP.md#current-backlog--2026-09-29) lists all 13 open issues. #228/#153 are conditional/optional; #172/#189, #167, #126 and #105 retain their specific defer/block/eligibility states; #210 is an ongoing journal. No UI/AI/Recovery Score, privacy rewrite or speculative backfill starts here.


## 2026-09-30 — #233 privacy-oracle reliability fix

Docs PR #232 exposed a real **test-oracle false positive**, not a Garmin product/privacy leak: the synthetic fixture ID `811` was searched as a substring across the entire JSON and happened to occur inside a legitimate internal source UUID.

Owner-confirmed Worker: **Luna 6.0 Medium**, OpenAI / Codex desktop. Candidate `37df19ba11b3f1e32b58d49319fdc0afe3b555ca` changed only `tests/test_garmin_training_owner_view.py`. The repaired oracle checks exact numeric/string fixture IDs structurally and retains negative controls for provider/device keys, raw payload and token fields while allowing an unrelated UUID containing those digits.

PR #234 merged to `f6939f531d4384e28fa9bd65fce59b498a0e6032`; exact-head/PR/main CI `36632773686` / `36633662826` / `36634392128` all SUCCESS. #233 is COMPLETE. No production code or privacy semantics changed.

## 2026-09-30 — #229 review attempt blocked before semantics

#229 Worker attribution is Owner-confirmed **DeepSeek V4.1 Flash, Max**, `opencode-go / OpenCode`; candidate remains `532a069c2b1253b4a3ce88c56f8d3b843f6b2f05` with exact-head CI `36628220352` SUCCESS.

The first independent reviewer attempt used **Sol 6.1 High**, OpenAI / Codex. It stopped during preflight with `review runtime inventory is not isolated` and did not execute the requested semantic checks. Record this as **BLOCKED / INCONCLUSIVE**, not a semantic `FIXES REQUIRED`, not an ACCEPT, and not a code remediation round. The candidate remains frozen; repeat the same review in an isolated read-only runtime.
