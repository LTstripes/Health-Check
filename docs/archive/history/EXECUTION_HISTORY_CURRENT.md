> Historical archive. Original path: `docs/EXECUTION_HISTORY_CURRENT.md`. Frozen at [b51859e9787d](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/EXECUTION_HISTORY_CURRENT.md). Recorded facts and code below describe their original date; old task/model-reporting/recycle instructions are not current authority. Current rules are maintained in the five books. Only this banner and link destinations were changed.

# Current Execution History

## History continuity

The previous current-history edition is preserved in Git at the exact product
checkpoint, with every dated outcome, failed attempt, source link and earlier
handoff intact: [history through the 2026-10-07 UI/UAT reconciliation](https://github.com/LTstripes/Health-Check/blob/013482ec3a51d89fd57c3a55ab9b09d1d2228e25/docs/EXECUTION_HISTORY_CURRENT.md).
It is historical evidence, not today's task queue. This compact current edition
continues it; no old commit, issue comment or review has been rewritten.

Earlier indexes also remain:
- [History through 2026-09-27](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/EXECUTION_HISTORY_THROUGH_2026-09-27.md).
- [Reliability/correction history through 2026-10-01](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/EXECUTION_HISTORY_THROUGH_2026-10-01_RELIABILITY.md).
- [Verbose historical engineering log](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/EXECUTION_HISTORY.md).

## 2026-10-14 — saved-data product integration closeout

Accepted product [`a27aa46b844ab944ce012513dd9a86d26919c07f`](https://github.com/LTstripes/Health-Check/commit/a27aa46b844ab944ce012513dd9a86d26919c07f),
[post-main CI 38598439243](https://github.com/LTstripes/Health-Check/actions/runs/38598439243)
SUCCESS, attempt 1: 3656 exact nodeids reconciled and actual Windows/DPAPI evidence PASS. The [current Wiki index](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/PROJECT_WIKI.md#current-canonical-state)
links accepted PRs #413–#418 and their bounded outcomes; detailed source, visual,
CI and integration evidence stays in those PRs/issues.

#418's first [hygiene failure](https://github.com/LTstripes/Health-Check/actions/runs/38581013534)
stays failed; tracked PNGs were removed without weakening the guard. #415's
[Windows failure](https://github.com/LTstripes/Health-Check/actions/runs/38544069167)
and absent DPAPI evidence are not retrospectively waived by #417 or later green
runs. The native scheduling cause remains unproven.

Stable remains separately `aca4b8f65eb276dddb3ae5de718a734afd19f369`;
no deployment, private/provider operation or Owner UAT occurred in this closeout.
Earlier dated history below is retained and is not a current queue instruction.

## 2026-10-12 — daytime rollout and night engineering closeout

Night product `main 8100b7ae7051af181a6bf3151ce3bc3e1d4c4151`,
[post-main 38319794454](https://github.com/LTstripes/Health-Check/actions/runs/38319794454)
SUCCESS, attempt 1: PR #407 Google401 repair; #408 dates/duration/km;
#409 compact Data; #410 completed-Moscow-day Steps; #411 provider-first
presentation. [Wiki receipt index](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/PROJECT_WIKI.md#current-canonical-state)
links all six reread issue closeouts instead of copying full evidence here.
Independent acceptance/integration are complete for these bounded slices;
their Stable rollout and Owner UAT are not. Google verification is synthetic;
Data metric value/date/age/clone age and #347 general discovery remain missing.
Steps v1/history are preserved; cooperative elapsed guard is not hard latency
proof or Garmin finality.

Read-only `D:\HealthCheck\ops\stable-rollout-20261012-task14\rollout-result.json`
separately confirms daytime installed `aca4b8f65eb276dddb3ae5de718a734afd19f369`,
PASS at 17:58 +03:00; old #397 does not establish that SHA. This closeout did
not read DBs/keys or change Stable. #395 wiring, navigation/timezone and session
drilldown were delivered earlier and must not be re-assigned. #393 Stage B
awaits Owner minimum-days/coverage, rounding and >400-day-window decisions;
#319 calories remain evidence-blocked, max-HR/anaerobic B1 complete. No new
product choices are made; dated historical entries below remain unchanged.

## 2026-10-11 — Steps/Statistics engineering and second Owner UAT checkpoint

Accepted product baseline immediately before this docs-only reconciliation:
[`main fa36dc5b6402fe6e6e166091002faf4af1ec0993`](https://github.com/LTstripes/Health-Check/commit/fa36dc5b6402fe6e6e166091002faf4af1ec0993).
Independent **post-main push CI 38164560091**
([run](https://github.com/LTstripes/Health-Check/actions/runs/38164560091))
SUCCESS attempt 1; classify, quality, all three Linux lanes, Windows and final
checks passed; docs skipped as expected. Repository docs updates are separate,
never recast this product run as a docs candidate gate.

| Integrated delta | Durable engineering evidence |
| --- | --- |
| #375 full-history Weight and separate composition methods | [PR #382](https://github.com/LTstripes/Health-Check/pull/382), [post-main 38125452863](https://github.com/LTstripes/Health-Check/actions/runs/38125452863) SUCCESS |
| #376 dated last eligible RHR reader + first Overview card | [PRs #383/#385](https://github.com/LTstripes/Health-Check/issues/376#issuecomment-6109039836), [post-main #385 38138876653](https://github.com/LTstripes/Health-Check/actions/runs/38138876653) SUCCESS; broader adapters not delivered |
| #343 sole Google eligible sleep source | [PR #384](https://github.com/LTstripes/Health-Check/pull/384), [post-main 38134563549](https://github.com/LTstripes/Health-Check/actions/runs/38134563549) SUCCESS |
| #347 Statistics labels | [PR #386](https://github.com/LTstripes/Health-Check/pull/386) merged; source confusion UAT remains |
| #380 bounded long-window Statistics backend+UI | [PR #387](https://github.com/LTstripes/Health-Check/pull/387) + [PR #388](https://github.com/LTstripes/Health-Check/pull/388), [post-main 38150693455](https://github.com/LTstripes/Health-Check/actions/runs/38150693455) SUCCESS; all-history is not integrated |
| #377 Garmin daily saved Steps projection / window / Stats | [PR #389](https://github.com/LTstripes/Health-Check/pull/389), [PR #390](https://github.com/LTstripes/Health-Check/pull/390), [PR #391](https://github.com/LTstripes/Health-Check/pull/391); [post-main 38164560091](https://github.com/LTstripes/Health-Check/actions/runs/38164560091) SUCCESS; no automatic normal-refresh projection or Google Steps |

**Owner-local separate gate:** clean `D:\HealthCheck\main` fast-forwarded
to accepted product SHA. One real-data disposable UAT profile (snapshot as-of
2026-10-08), code/process/profile binding and seven primary routes HTTP 200
reported; UAT-only startup migration left reported DB hash unchanged and WAL
empty. Fresh full clone integrity remains UNVERIFIED. Observed `/brief`
23.098s first request / 9.470s repeat, system cache not cleared. Neither a
controlled speedup nor an acceptable final response-time claim.
Stable, providers, scheduler and persistent Context were not changed.

**Human result:** A+ reception positive, Weight history/Data/Overview inspected
with eight bounded product follow-ups; [#330 stays PARTIAL](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6113161066).
New source/meaning issues: [#392 Google Steps](https://github.com/LTstripes/Health-Check/issues/392),
[#393 eligible-day RHR mean](https://github.com/LTstripes/Health-Check/issues/393),
[#394 Body Battery daily max vs saved samples](https://github.com/LTstripes/Health-Check/issues/394),
[#395 Garmin routine Steps materialization](https://github.com/LTstripes/Health-Check/issues/395).
Existing #377/#347/#294/#305/#379/#375/#376/ #319 were updated
**without** repeating already merged delivery. #319 calorie/energy semantics
parked BLOCKED, #345 speculative Activity UI remains on Owner design hold.
No Worker or Owner-local Stable operation was launched by these notes.

See [dated sanitized UAT handoff and guarded Stable rollout proposal](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/OWNER_UAT_CHECKPOINT_2026-10-11.md)
for the Owner's observations and precise readiness limits.

## 2026-10-10 — final integrated Owner UI engineering package

Accepted canonical product main:
`f0e6c36c4d10f03069111665f10201575ee6ea0e`.
[Final full post-main CI 38070804783](https://github.com/LTstripes/Health-Check/actions/runs/38070804783)
SUCCESS attempt 1 (quality, three Linux lanes, Windows and final checks).
All previous accepted deliverables remain ancestors; see each task PR for exact
head/merge-tree/readback and independent review evidence.

| Work | Integration / separate engineering gate |
| --- | --- |
| #343 Sleep B2 | [PR #368](https://github.com/LTstripes/Health-Check/pull/368) accepted/merged; [post-main 38042233440](https://github.com/LTstripes/Health-Check/actions/runs/38042233440) SUCCESS; source exactness and R05 retained |
| #358 synthetic multidomain demo | [PR #369](https://github.com/LTstripes/Health-Check/pull/369) merged; [post-main 38042829875](https://github.com/LTstripes/Health-Check/actions/runs/38042829875) SUCCESS; synthetic data is not private Owner proof |
| #347 parity/acceptance | [PRs #370](https://github.com/LTstripes/Health-Check/pull/370), [#371](https://github.com/LTstripes/Health-Check/pull/371) merged; [post-main #371 38059813658](https://github.com/LTstripes/Health-Check/actions/runs/38059813658) SUCCESS |
| #295 /brief read reuse | [PR #372](https://github.com/LTstripes/Health-Check/pull/372) merged, [post-main 38065282880](https://github.com/LTstripes/Health-Check/actions/runs/38065282880) SUCCESS; real cold route latency not yet PASS |
| #345 Activity session detail | [PR #373](https://github.com/LTstripes/Health-Check/pull/373) merged, [post-main 38066888854](https://github.com/LTstripes/Health-Check/actions/runs/38066888854) SUCCESS |
| #344 Overview readability | [PR #374](https://github.com/LTstripes/Health-Check/pull/374) merged after exact independent source review; [PR 38070191305](https://github.com/LTstripes/Health-Check/actions/runs/38070191305) and [post-main 38070804783](https://github.com/LTstripes/Health-Check/actions/runs/38070804783) SUCCESS |

## 2026-10-11 — real-clone Owner visual UAT / next product decisions

Owner-local operator safely updated the clean control checkout to accepted
main, ran an **isolated previously verified 2026-10-08 real-data clone**
and established process/code/profile binding. Seven primary UI routes were
HTTP 200. Nine bounded checked tables PASS; full clone DB integrity scan
hit 180-second cutoff, **UNVERIFIED**. No Stable/provider/scheduler/secret
or durable Owner data changes; browser testing was real-clone human UAT,
distinct from synthetic tests and CI.

Owner reports improved A+ look and perceived responsiveness, strongly prefers
new Sleep history, and confirms saved Activity details work. The same readout
identified confusing extra Google/Fitbit source identities, opaque Statistics
source labels and empty cards, duplicated composition histories/tables,
unavailable copied freshness statuses, hidden Context link and redundant
UTC-offset/IANA fields. First /brief load reached 30-second timeout; repeat
about 14 seconds; no claimed cold speedup. The unverified latest live
provider state cannot be inferred from historical clone errors.

[Owner product record #330](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6106537913)
makes the overall human acceptance **PARTIAL**, not blanket PASS.
Owner then approved:
one full-history weight+composition table and multi-method dated chart
[#375](https://github.com/LTstripes/Health-Check/issues/375);
two conceptual Garmin/Google provider lines after #342 evidence;
readable Stats sources and future long windows [#380](https://github.com/LTstripes/Health-Check/issues/380);
new Steps source inventory+typed UI [#377](https://github.com/LTstripes/Health-Check/issues/377)
and still-blocked calories #319; latest eligible dated evidence rather than
blank default cards [#376](https://github.com/LTstripes/Health-Check/issues/376);
primary 'Комментарии' navigation/city-zone input #294; saved dates vs
refresh state #305; cross-app A+ consistency [#379](https://github.com/LTstripes/Health-Check/issues/379);
and future Owner-requested Activity analytics discovery [#378](https://github.com/LTstripes/Health-Check/issues/378).
No source eligibility, canonical rule, provider, health data or release operation
was changed by these **planning/issue** decisions. #346 duplicate Activity
cards stay deferred and #341 direct ChatGPT connection paused. New Workers
still require explicit launch/checkout ownership.

The 2026-10-09 notes **below** preserve the earlier dated engineering
snapshot/decisions and must not be mistaken for the current unstarted queue.

## 2026-10-09 — accepted Context/export wave and offline sleep diagnosis

| Issue | Integrated/diagnostic outcome and gate |
| --- | --- |
| #349 | Docs closeout merge `b21aaae653482f606dd57f3b02b884684c1230b7`, [post-main CI 37963990764](https://github.com/LTstripes/Health-Check/actions/runs/37963990764) SUCCESS |
| #294 / PR #350 | Context UI merged to `e9069a89697a3021e6053769cc860c2faba97621`, [post-main 37971609489](https://github.com/LTstripes/Health-Check/actions/runs/37971609489) SUCCESS. Worker reports 33 targeted PASS + desktop synthetic 1024/1440 PASS; durable Owner UAT UNVERIFIED |
| #341 / PR #351 | Bounded standalone read-only Weight/Garmin-scalars/Context export merged to `8efb1f972ba9a77dc014b69ca93f4168d573482b`. [Remediation ACCEPT](https://github.com/LTstripes/Health-Check/pull/351#pullrequestreview-5474065208), candidate [push 37973231823](https://github.com/LTstripes/Health-Check/actions/runs/37973231823) + [PR 37973239937](https://github.com/LTstripes/Health-Check/actions/runs/37973239937) SUCCESS attempt 1; separate [post-main 37975552600](https://github.com/LTstripes/Health-Check/actions/runs/37975552600) is linked. Both Context and export tests retained in merged lane manifest. Worker reports 46 local synthetic PASS; Integrator did not rerun them |
| #342 Phase A/B | [OFFLINE diagnosis ACCEPT](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6087155625): typed Garmin/Google sleep exists in the verified disposable Owner clone; the selected evaluation day has none, and 70 accepted account-observation pairs do not qualify for current device/family Compare. No app read defect, new vendor score or current provider recovery proven. Fresh full-DB integrity after time cutoff UNVERIFIED |

#341 original `1dfcb86e6adc72bfd799ae091702a483064ef774` had
[FIXES REQUIRED](https://github.com/LTstripes/Health-Check/pull/351#pullrequestreview-5473753348)
for private exports into Git workspaces. Amended
`2fac1fb3309d5f2ec171177a055da107b62873ba` closed that boundary
before any profile read. Original push CI 37967992189 attempt 1 Windows
smoke FAILED (root cause worker-reported, not independently confirmed),
attempt 2 SUCCESS; later amended push/PR SUCCESS does not erase failure.
#342 first live-runtime-gated UAT was BLOCKED; subsequent authorized offline
read-only inspection passed bounded sleep/Agreement checks without starting
the app or changing clone DB/WAL/SHM. Copied Garmin reauth/Google failures
are historical and cannot establish present provider availability.

Human #330 remains PARTIAL; no new durable Context write/readback, real
Owner export, share UI, direct ChatGPT/MCP connection or provider action was
performed by Integrator. #341/#342 are kept open for next bounded decisions;
#343–#348 remain unstarted. CI, local synthetic and private UAT are separate.

## 2026-10-09 — integrated A+ product checkpoint

Audited product main before the documentation closeout:
`013482ec3a51d89fd57c3a55ab9b09d1d2228e25`. Exact post-main
[CI 37884822270](https://github.com/LTstripes/Health-Check/actions/runs/37884822270)
SUCCESS attempt 1: quality, three Linux lanes, Windows smoke and final checks.
Documentation publication has separate candidate/PR/post-main evidence; no
self-referential future docs SHA or new local product test is guessed here.

| Work | Integrated outcome / primary record |
| --- | --- |
| #321 / PR #325 | Desktop-only 1024px+ acceptance; phone-only checks retired, functional coverage retained |
| #322 / PR #324 | Owner-approved A+ reference; original PNG-bearing PR #323 remained unmerged, clean text-only delivery kept repository hygiene |
| #326 / PR #327 | Shared A+ palette, typography, navigation and contract |
| #328 / PR #329 | Real Overview readings/charts; saved-activity state, actual Sleep-date link and series-role fixes reviewed before merge |
| #318 / PR #331 | Five-column Activity A/B, human duration, optional-field thinning and unchanged comparisons |
| #317 / PR #332 | Garmin/Google source-only Sleep, including unpaired account observations; source/role/native-field corrections independently accepted |
| #335 / PR #336 | Activity v4 five recent sessions and existing full history disclosure |
| #295 / PR #337 | Indexed per-source Google freshness queries with equivalent facts; engineering accepted, real Overview latency still open |
| #334 / PR #338 | Sparse Overview Weight-chart dates/ticks/legend and honest gaps |
| #333 / PR #339 | Compact source attention without changes to packet/actions/source semantics |

#317's original independent FIXES REQUIRED was corrected at
`dc5dc1b801297ce60df081a9fdd638331269fe7f`; the
[independent re-review](https://github.com/LTstripes/Health-Check/pull/332#issuecomment-6064746852)
accepted existing account eligibility, uncertain singleton roles and consistent
Garmin native/primary-table gates. Its passing amended push/PR CI did not erase
the initial findings. Existing Compare/Agreement was preserved. New requested
Sleep history is #343, not unfinished original #317 delivery.

Detailed candidates, failed attempts, reviews and exact gates remain in their
issue/PR histories. #295's former not-planned closure was followed by reopening
on new real evidence; the earlier dated disposition remains preserved, not relabelled.

## Real-clone activation and Owner UAT — separate evidence

[Owner-local report 6074940976](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6074940976)
records a controlled launch from the product checkpoint using an existing verified
disposable **copy of real Owner data**. Code/clone identity and integrity were
checked. No Stable/provider/scheduler change or new backup was performed. This
is neither a synthetic fixture nor an automatically refreshed Stable profile.

Bounded direct-loopback observations, all HTTP 200:

| Request | Total time |
| --- | --- |
| /brief 30-day, first | 18.402 s |
| /brief 30-day, one repeat | 11.983 s |
| /brief 7-day | 9.345 s |
| /api/source-freshness | 1.846 s |

Cache state was not controlled; these are not matched before/after benchmarks.
Overview is still slow (#295). Freshness request completion is not successful
provider collection. The report classified selected-source RHR as otherwise
usable but excluded by Overview's surface filter (#340), and weekly Garmin HRV
as missing in the inspected window even ignoring that filter. No Google daily
metric was substituted and no upstream cause was invented.

Later the Owner supplied real screenshots and concrete feedback. The
[human UAT/priority record](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6084375341)
sets **PARTIAL / NOT overall PASS**: A+ style, dedicated Weight and shorter Activity
history were liked; source availability, Sleep experience, useful detail/summary
views and comments/chat analysis still need work. Human inspection is no longer
unperformed; individual unaccepted capabilities remain unverified. Private images
and health values are not copied into repository documentation.

## Owner decisions — data-first functionality, documentation before launch

The Owner explicitly requested this documentation reconciliation before submitting
new tasks, and raised **#342 data availability to P1 in the first wave** with
#294 Stage A portal Context and #341 Stage A bounded health/context export.
Data is not deferred behind cosmetic polish.

Compatible parallel roles after documentation closeout:
- #342: read-only code/contracts diagnosis; private runtime work stays separately authorized.
- #294: sole UI/Context writer, preserving original text, event-time precision and revisioned history; weight-goal Settings remains Stage B.
- #341: separate exporter/module/script/tests consuming the existing Context interface, with no competing edits to its service/models or shared UI.

Heavy local verification remains serialized on the shared machine. Integrator
reconciles additive test-manifest changes and exact candidate/PR/main gates;
separate branches alone are not proof of independent scope. Workspaces and external
synthetic roots are assigned in #294/#341. No feature Worker is launched by this
record, and no private data are copied into a development tree.

The immediate useful flow is durable dated comments and selected evidence for
conversation in ChatGPT. Export comes first; direct authenticated read access
requires a verified connection. A skill alone does not reach the Owner's localhost;
Telegram is optional. A note in disposable UAT is not automatically a Stable note.

Planned #343–#348 retain the Owner's requests: dual-source Sleep history, Overview
chart/disclosure polish, session details, period recovery cards, Statistics and
lab-document candidate confirmation. The new Statistics clarification is explicit:
**left source / right source, both visible by default**, each with units, effective
window, denominator/count and coverage. Compatible sides may have a numeric delta;
incompatible or absent sides stay independently visible without pooling, combined
totals or fabricated zeros. This is a planned view, not newly delivered analytics.

## Documentation and handoff

README, Project Wiki, Product Vision, Roadmap, Owner UI, Context Capture, Backlog
Ideas and Decisions are reconciled by responsibility: implemented versus planned,
source data versus clone/runtime, CI versus local/human UAT, P1 data availability,
Context/chat priorities, side-by-side Statistics and preserved data contracts.
Old detailed history remains accessible by the pinned link above rather than being
copied into another long active queue.

The first-wave short prompts for #294/#341/#342 remain valid: each locates the
updated issue and starts from live main. #347's later prompt now explicitly includes
left/right source visibility and compatibility-bound deltas. No new feature issue
was needed for the priority/layout clarification. The
[roadmap](https://github.com/LTstripes/Health-Check/blob/b51859e9787dd81ca7959de5d3184e0c801c6cbf/docs/ROADMAP.md#current-backlog) is the sequencing map, not an automatic queue.

The documentation PR must record its own diff/link/privacy review and actual CI
results. No new Owner UAT, local deployment, provider call, schema/runtime change
or model benchmarking is implied. Existing unperformed gates stay unverified.
