# Health-Check Project Wiki

This is the compact current-state entry point. The [roadmap](ROADMAP.md#current-backlog)
owns sequencing, issues own execution contracts, and release/history documents retain
proof. Do not use an older status paragraph as an instruction to repeat completed work.

<a id="current-canonical-state"></a>

## Current canonical state - 2026-10-15 #357 arithmetic-mean comparison

The backend-only arithmetic-mean option is accepted and integrated in
[PR #430](https://github.com/LTstripes/Health-Check/pull/430), at
[`main 72fe2572be734c26fe7c1e713725ecfc77f3b26c`](https://github.com/LTstripes/Health-Check/commit/72fe2572be734c26fe7c1e713725ecfc77f3b26c).
[Exact post-main CI 38743920025, attempt 1](https://github.com/LTstripes/Health-Check/actions/runs/38743920025)
is SUCCESS: 4118 exact nodeids, 4115 passed and three expected Linux skips,
Windows/DPAPI PASS. Complete same-attempt artifacts were locally revalidated;
merge parents and tree match the accepted candidate. The PR records independent
semantic/code ACCEPT for `cea623cc15a0a59f3acbc3bcdf56419138947a21` against
`86f572df98727c237d8025f967f5336a36e8f580` and its exact pre-merge gates.

Explicit `comparison_method="arithmetic-mean-v1"` selects adapter v4 and frozen
R03 `baseline.mean`, with equal weight per eligible saved daily value and signed,
unrounded current-minus-mean delta. The omitted-option v2/v3 bodies and hashes
remain unchanged; Moscow still requires its explicit day-policy opt-in. The
[versioned contract](R03_ANALYTIC_INPUT_CONTRACT.md#explicit-arithmetic-mean-comparison-357)
owns the detailed finite/overflow, provenance, completion and coverage guards.

The [bounded mean-mode real-copy receipt](https://github.com/LTstripes/Health-Check/issues/357#issuecomment-6194781870)
subsequently verified one completed-day control as available and another fixed D
as blocked by early acquisition on one isolated snapshot. It did not establish
universal coverage or missing-day behavior. The authorized UI candidate connects
the existing Overview daily-stress card to explicit v4/Moscow comparison for the
end date of the selected period, with independent preceding-28-day history and
short unavailable reasons. Independent review and Owner UAT remain pending;
the UI candidate is not yet accepted or rolled out. [#357](https://github.com/LTstripes/Health-Check/issues/357)
remains OPEN. The
[earlier real-copy applicability check](https://github.com/LTstripes/Health-Check/issues/357#issuecomment-6191881424)
was **median-mode only** and is not mean-mode verification. No Stable/Owner
runtime or data, provider operation or rollout was changed. GitHub integration
does not update the Owner's local runtime. Earlier checkpoints retain their
dated scope and evidence.

## Previous #357 Moscow analysis-day checkpoint - 2026-10-15

The backend-only explicit Moscow analysis-day policy is integrated in
[PR #428](https://github.com/LTstripes/Health-Check/pull/428). Its code checkpoint
is [`main 9340def7aef61e5e96f610b25422836b5f501085`](https://github.com/LTstripes/Health-Check/commit/9340def7aef61e5e96f610b25422836b5f501085);
[exact post-main CI 38720989149, attempt 1](https://github.com/LTstripes/Health-Check/actions/runs/38720989149)
is SUCCESS. [Independent ACCEPT relayed by parent and integration receipt](https://github.com/LTstripes/Health-Check/pull/428#issuecomment-6190237162)
bind candidate `f48a824a7e354e5686eb5edfe632fdb6b2e8c359` on base
`be92a019b4c8d8b0ed2b9fa91308f6cabacbee3b` and its exact pre-merge gates.
[#357](https://github.com/LTstripes/Health-Check/issues/357) owns the current task
status. This is a bounded backend update, not a new global product/runtime audit.

Adapter v3 requires explicit opt-in to
`owner-selected-europe-moscow-analysis-day-v1`; omitted policy retains strict
adapter v2. Garmin calendarDate, timestamps and saved daily means remain original
source evidence, without Moscow-day reaggregation. The selected analysis zone and
nullable/unproven source zone stay distinct. Completion still needs ordinary
successful acquisition with receipt at/after the next ZoneInfo Moscow midnight;
replay or late evaluation cannot rescue an earlier receipt. The source/method,
21-of-28, frozen median/Type-7, partial/cap and two-query snapshot guards remain.

All supplied clocks are checked, including raw fields normalization did not
select: DST gaps, unresolved folds and conversion overflow fail closed. Both
folds remain supported with coherent UTC/offset evidence. Conservative limitation:
selected date-only plus unselected naive clock/standalone offset can remain
unavailable when normalized clock proof is absent; no inferred instant or source
zone is persisted to rescue it. The [versioned backend contract](R03_ANALYTIC_INPUT_CONTRACT.md#explicit-owner-selected-moscow-analysis-day-policy-357)
retains the detailed meaning.

Only code and synthetic evidence are accepted. #357 remains OPEN for separately
authorized UI/surface and real-copy saved-coverage/readiness verification, then
Owner UAT. No Stable/Owner runtime or data, provider operation, rollout or extra
technical panel was changed. GitHub integration does not update the Owner's local
runtime. Earlier dated checkpoints retain their original scope and evidence.

## Previous #357 applicability checkpoint - 2026-10-15

The accepted source-only stress adapter ([PR #425](https://github.com/LTstripes/Health-Check/pull/425))
and its versioned applicability correction ([PR #426](https://github.com/LTstripes/Health-Check/pull/426))
are integrated in [`main 023b3e1adf78cf46d1437c76b002206c6f9a4991`](https://github.com/LTstripes/Health-Check/commit/023b3e1adf78cf46d1437c76b002206c6f9a4991).
The exact post-main evidence is [CI 38701739186, attempt 1](https://github.com/LTstripes/Health-Check/actions/runs/38701739186).
[Independent ACCEPT and integration receipt](https://github.com/LTstripes/Health-Check/pull/426#issuecomment-6187257557)
bind the reviewed candidate and pre-merge gates; [#357](https://github.com/LTstripes/Health-Check/issues/357)
owns the current task status. This is a bounded #357 update, not a new global product audit.

R03 rule v2 distinguishes positively proven foreign-surface missing placeholders
from daily stress mean candidates before date ambiguity resolution. Its separate
applicability audit and frozen inputs remain hashed; the compatible adapter reads
current and preceding history in one snapshot without subset recomputation.
Genuine missing/null/invalid, unknown or conflicting provenance, unexpected
nonmissing and genuine duplicate rows retain fail-closed per-date semantics.
Source/date, method/unit, caps/partial, original timezone and ordinary acquisition
guards remain; absent timezone proof preserves current value but blocks comparison.

Only code and synthetic evidence are accepted. #357 remains OPEN: UI/surface,
actual Owner coverage and Owner UAT are held/unverified. No Stable/Owner runtime
or data, provider operation, rollout or future Moscow timezone policy is included.
Earlier dated checkpoints below retain their original scope and evidence.

## Previous canonical checkpoint - 2026-10-14 product closeout

Accepted product: [`main a27aa46b844ab944ce012513dd9a86d26919c07f`](https://github.com/LTstripes/Health-Check/commit/a27aa46b844ab944ce012513dd9a86d26919c07f).
[Exact post-main CI 38598439243](https://github.com/LTstripes/Health-Check/actions/runs/38598439243)
SUCCESS, attempt 1: 3656 exact nodeids reconciled and actual Windows/DPAPI evidence PASS. Live GitHub remains authoritative for subsequent refs;
check [live main](https://github.com/LTstripes/Health-Check/commits/main) before a new assignment.

| Accepted since the night checkpoint | Delivered boundary |
| --- | --- |
| [PR #413](https://github.com/LTstripes/Health-Check/pull/413), #341 Sleep + Context evidence | Transport-independent, source-specific bounded Sleep 7/30 + Context packet; existing v1/MCP contract remains unchanged. No direct assistant connection or actual private export was performed |
| [PR #414](https://github.com/LTstripes/Health-Check/pull/414), weekly report reference | Sanitized presentation inspiration in the existing reference document only; no feature, new app section or automation |
| [PR #415](https://github.com/LTstripes/Health-Check/pull/415), #305/#376 Data RHR | [Receipt](https://github.com/LTstripes/Health-Check/issues/305#issuecomment-6169913449): latest eligible saved RHR value/source/date/age with explicit source choice and honest missing/unknown states; other metrics and clone-age policy remain open |
| [PR #416](https://github.com/LTstripes/Health-Check/pull/416), #393 RHR period mean | [Receipt](https://github.com/LTstripes/Health-Check/issues/393#issuecomment-6166370119): equally weighted eligible days, n/N, n=1 one observation, n=0 no number, final sign-aware integer half-up rounding, inclusive 400-day cap |
| [PR #417](https://github.com/LTstripes/Health-Check/pull/417), Windows lifecycle evidence | Narrow exact native-128 transcript recognition with ownership, identity, survivor, port, raw-output and DPAPI gates retained; [old failed PR #415 run](https://github.com/LTstripes/Health-Check/actions/runs/38544069167) stays failed, cause unproven |
| [PR #418](https://github.com/LTstripes/Health-Check/pull/418), #394 Body Battery | Maximum of eligible saved typed measurements per preserved source-local day, then equally weighted mean over the exact 7/30/custom selected period, n/N and folded evidence; finite-value contract and unknown date-only UTC chronology retained |

These are accepted code/synthetic evidence, not new Stable or Owner-live proof.
Installed Stable remains separately `aca4b8f65eb276dddb3ae5de718a734afd19f369`;
no rollout is performed by this closeout. Later UI/Google recovery still need the
separately authorized rollout and Owner UAT. Body Battery saved maxima do not prove
full-day collection, wear, provider finality, morning values or medical meaning;
record caps fail closed, and real-database latency remains unverified.

## Previous canonical checkpoint — 2026-10-12 night closeout

Accepted product: [`main 8100b7ae7051af181a6bf3151ce3bc3e1d4c4151`](https://github.com/LTstripes/Health-Check/commit/8100b7ae7051af181a6bf3151ce3bc3e1d4c4151);
[post-main CI 38319794454](https://github.com/LTstripes/Health-Check/actions/runs/38319794454)
SUCCESS, attempt 1. Live source/PR/issues and these receipts were reread for this
closeout; check [live main](https://github.com/LTstripes/Health-Check/commits/main)
before a new assignment.

| Night integration | Authoritative closeout and retained boundary |
| --- | --- |
| [PR #407](https://github.com/LTstripes/Health-Check/pull/407), Google GET-401 recovery | [#406 receipt](https://github.com/LTstripes/Health-Check/issues/406#issuecomment-6131450279): merged, post-main SUCCESS; synthetic only, original failure/expiry unproven, no Stable-live verification |
| [PR #408](https://github.com/LTstripes/Health-Check/pull/408), readable dates and session units | [#379 dates](https://github.com/LTstripes/Health-Check/issues/379#issuecomment-6132044382), [#378 duration/km](https://github.com/LTstripes/Health-Check/issues/378#issuecomment-6132046243): merged, post-main SUCCESS; exact native values/precision retained, umbrella issues OPEN |
| [PR #409](https://github.com/LTstripes/Health-Check/pull/409), compact Data | [#305 receipt](https://github.com/LTstripes/Health-Check/issues/305#issuecomment-6133059796): merged, post-main SUCCESS; eligible metric value/date/age and clone snapshot age NOT implemented |
| [PR #410](https://github.com/LTstripes/Health-Check/pull/410), completed-day Steps | [#377 receipt](https://github.com/LTstripes/Health-Check/issues/377#issuecomment-6133714095): merged, post-main SUCCESS; latest proved acquisition after Europe/Moscow day end, v1/history unchanged; cooperative 5-second guard, real latency unmeasured, no final Garmin total claim |
| [PR #411](https://github.com/LTstripes/Health-Check/pull/411), provider-first selector | [#347 receipt](https://github.com/LTstripes/Health-Check/issues/347#issuecomment-6134364766): merged, post-main SUCCESS; presentation only, general per-metric discovery/autoselection NOT implemented |

Installed Stable is separately `aca4b8f65eb276dddb3ae5de718a734afd19f369`.
The read-only local `D:\HealthCheck\ops\stable-rollout-20261012-task14\rollout-result.json`
reports PASS for the daytime rollout, completed 2026-10-12 17:58 +03:00, with
that exact `after_sha` and [post-main 38242290747](https://github.com/LTstripes/Health-Check/actions/runs/38242290747).
No real DB/key was read for this closeout. Old #397 is not proof of this SHA.
PRs #407–#411 are not installed there; all their new screens and Google recovery
still require separately authorized rollout/Owner UAT.

Earlier #395 routine Garmin Steps wiring ([PR #398](https://github.com/LTstripes/Health-Check/pull/398)),
Comments primary navigation/city-IANA timezone and Statistics session drilldown
([PR #405](https://github.com/LTstripes/Health-Check/pull/405)) are delivered;
do not assign them again. Human #330 acceptance remains PARTIAL. Earlier clone
UAT/latency observations are dated evidence, not current Stable/provider proof.
The [roadmap](ROADMAP.md#current-backlog) lists only remaining deltas; R01–R05
remain named releases. This closeout adds no product decision or runtime action.

## What the product can do today

### Owner interface

Desktop 1024px+ A+ primary navigation is **Обзор / Вес / Сон /
Активность / Статистика / Данные / Комментарии**. Overview `/brief`, Weight `/`,
Sleep `/sleep` (secondary `/agreement`), Activity `/garmin` with a
source-bound saved session detail route and A/B, Statistics `/statistics`,
Data `/imports` and primary Comments `/context`. Comments navigation and
city/IANA timezone input are delivered in PRs #401/#402.

**Already delivered:** one all-history Weight+composition table and
method-separated selectable chart (#375); Garmin+eligible Google Sleep timeline
with exact provenance/unknowns (#343); human Statistics source labels and
7/30/trailing365/calendar-year/year-to-date windows (#347/#380);
dated latest-eligible RHR Overview/Data value (#376/#415), separate eligible-day
RHR period mean (#393/#416), and saved Body Battery daily maxima/period mean
(#394/#418);
Garmin `observed_daily_steps` v1 projection/window and the separate completed-day
Statistics read-only view (#377/#410). The latter verifies saved originals and
latest proved acquisition for one exact source; normal refresh wiring #395 is delivered.
Google Steps production acquisition remains #392. All-history Statistics is a distinct
unimplemented bounded task; Energy/BMR #319 BLOCKED.

Normal Owner provider concepts are **Garmin and Google**, but exact saved
Google source identities still have metric-specific eligibility/ambiguity:
the accepted sole `google-wearables` family default applies to **Sleep only**
(#342), not physiology/Steps/Activity. Never pool Fitbit list copies,
family source, Google physiology or Garmin accounts. #347's presentation slice
is delivered; general per-metric eligible-source discovery remains open. Missing/ineligible/uncollected is not zero.

The dated Owner screenshots motivated the delivered date/unit and compact Data
presentation slices. Broader #379 style acceptance remains open; source/form
values stay exact in technical disclosure.

### Weight / body composition

- Xiaomi Home/S400 screenshots use the repo skill and strict Owner-assisted extraction over R01; foreign algorithm identity is rejected before semantic writes (#226).
- Original evidence, source/device/algorithm provenance and confirmed history are preserved; #240 records visible/Owner-attested/workflow-profile/unknown origins, while legacy NULL remains historical.
- Owner-supplied date is date-only; fixed workflow identity is not falsely called visual evidence. Exact attachment replay is duplicate-safe; cross-image semantic dedup is not implemented (#228).
- Changed-sidecar/provenance corrections (#229/#240) require explicit review; reject is non-mutating and confirm preserves revision/supersession history.
- openScale/openScale-sync compatibility remains delivered optional contract; #153 is closed as not planned. Screenshots are the operational path.
- Deterministic trends, observed daily medians and separate composition compatibility groups retain their meaning. #344 already added honest thin connectors and readable Sleep ticks without changing EWMA or creating daily measurements.

### Garmin

- Protected Owner-assisted session reuse; incremental sync/backfill with coverage/checkpoints/reconciliation.
- Deterministic baselines/trends, activity/cycling comparison and bounded exploratory lagged associations.
- Garmin-native Training Status/load/ACWR, Load Focus and Readiness/Recovery with source chronology/provenance; requested acquisition date is not necessarily source date.
- Bounded Training sync is part of normal Owner refresh. No invented recovery-time unit, provider attribution or custom score.
- #319 already integrated typed max-HR and anaerobic Training Effect; saved history requires separate Owner replay. Calories/BMR meaning remains blocked; Garmin saved daily Steps are delivered under #377, normal refresh wiring #395 is delivered, and Google Steps need #392. Current #345 saved session detail is delivered.

### Google Health

- Web Application OAuth with fixed registered loopback callback and external protected state; Windows DPAPI unchanged, non-Windows purpose-bound AEAD v2 (#247), compatible authenticated legacy reads and no key creation on pure reads.
- Accepted read-only sleep/health-metrics scopes; raw/current typed evidence and bounded incremental/backfill/refresh, privacy-safe diagnostics, coverage/checkpoints and replay.
- Collection intent remains explicit. The bare CLI default includes sample HR, but the Owner Ops wrapper applies HR-OFF; disabled history is not relabelled fresh/provider-empty. Fixed wearables-sleep reconciliation remains distinct.
- Historical release/live collection proof does not establish today's provider auth or completeness. Empty accepted pairs are not proof that Google has no source records. See #342 and [Owner Refresh](OWNER_REFRESH.md).

### Reporting and context

- Deterministic Period Brief and thin API/text/CLI rendering with stable packet/hash, explicit JSON/text stdout (#248), limited-encoding compatibility (#203) and coherent compound SQLite/ORM reads (#227).
- Shared persisted freshness (#147/#191/#193/#238), not ad-hoc UI thresholds. #295's indexed Google reads and request-local chart reuse are delivered; cold Overview on Owner clone still needs a measured follow-up despite perceived improvement.
- Context v0 adds/lists/revises original text with explicit time precision, append-only history and idempotent requests. #294 Stage A portal, #341 Stage A versioned bounded export and #356 read-only MCP endpoint are integrated without rewriting Period Brief packet or doing LLM-side raw-series mathematics. PR #413 adds the source-specific bounded Sleep 7/30 + Context service without
changing the existing v1/MCP contract. Direct on-demand assistant connection
remains a separate access/security decision in #341.

### Durable Owner runtime

The accepted foundation provides a persistent private profile, supported
large-profile backup/verify/restore, external-runtime locking and bounded provider
refresh/recovery. Historical integrity/duplicate/run findings are dated evidence,
not perpetual guarantees. #214 proved one automatic selected-stream run, not
uninterrupted daily service or future provider availability.

Stable is data, not Git state. Follow [Owner Machine Layout](OWNER_MACHINE_LAYOUT.md)
for code, Stable, Ops, UAT and Worker roles. Never reset Stable for UAT or copy a
private clone into a development workspace. A routine note written in UAT is not
a durable Stable journal entry; explicit rollout is required before normal use.

## Current real-data limitations and next work

The [2026-10-11 UAT checkpoint](OWNER_UAT_CHECKPOINT_2026-10-11.md) describes
the as-of-Oct-8 disposable clone and uncontrolled `/brief` latency, not current
Stable or night-code UAT. The daytime rollout receipt above proves its specific
installed SHA; it does not prove live provider recovery or acceptance of later UI.

Remaining work is tracked in [the roadmap](ROADMAP.md#current-backlog): #305/#376
eligible value/date/age for metrics beyond the delivered RHR slice and clone
age policy; #347 per-metric eligible-source discovery/autoselection; #392 Google
Steps evidence. #393's mean rules and #394's saved-day maxima/period means are
implemented; their Owner UAT remains pending. #319 calories are blocked by authoritative leaf/unit/category/interval,
resting inclusion and eligible-coverage evidence, not a missing formula;
max-HR/anaerobic B1 is complete. #379/#378 umbrella work and new-screen Owner UAT
remain open. Completed wiring/navigation/timezone/drilldown are not a new queue.

Steps completed-day display preserves exact sources, repeat bytes, later lower
corrections and honest ties/missingness. It is a read-only projection of latest
proved acquisition after the Europe/Moscow day end, not an attestation of Garmin
finality. v1 projection/history remain intact; real latency is UNVERIFIED. See
[Steps contract](GARMIN_OBSERVED_DAILY_STEPS_CONTRACT.md). No provider calls,
replay, Stable writes or new product choices follow from these docs.

## Source-attribution rule that matters for R05

`dataSourceFamily`, query mode and broad wearable-family membership are acquisition
context, not proof of one physical Fitbit device. Device-pair evidence needs
explicit metadata; family and uncertain account observations remain exploratory.
Source-only display (#317/#343/#347) does not qualify for a canonical switch.
Garmin remains default and #105 NOT_ELIGIBLE until its separate gate is satisfied.
See [R05 closeout](R05_RELEASE_CLOSEOUT.md) and
[account observations](R05_ACCOUNT_SLEEP_OBSERVATIONS.md).

## Engineering reliability / CI

#123–#125 established provenance-bound quality, exact Linux nodeid/multiplicity
reconciliation and native Windows proof. #181/#243 retain ownership/PID/CreationTime,
transcript, cleanup and same-attempt completeness. Failed/incomplete attempts are
not erased by later green runs; partial reruns do not supply acceptance.

The completed optimization wave preserves test coverage: #251 lane balance,
#246 docs-only/exact-tree event delegation, #242 separate dependency audit,
#244 Host/Origin and #302 deterministic Linux environment. Historical timing
observations are not current runtime/billing promises. See
[CI closeout](CI_OPTIMIZATION_CLOSEOUT_2026-10-04.md). #126 enforcement still needs
an Owner/capability decision; manual Integrator exact gates remain required.

## Core engineering rules

- `main` is the only canonical source; no automatic local deployment.
- Issue = contract; a short prompt locates the role, baseline/workspace and delivery.
- Workers do not self-accept or merge; independent review is risk-based.
- Real datasets and credentials stay outside tracked code/CI; assigned Owner reads and presentation follow [Owner data workflow](OWNER_DATA_WORKFLOW.md).
- Missing/null/zero/unavailable/unknown remain distinct; UI/LLM do not invent mathematics.
- #210 model bookkeeping is retired. Complexity/model recommendations route work; they are not benchmark logs.
- No feature task, provider call, network exposure or Owner runtime mutation is started by this documentation update.

## Useful docs

- [README](../README.md)
- [Product Vision](PRODUCT_VISION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Owner UI](OWNER_UI_SHELL.md)
- [Owner UAT checkpoint 2026-10-11](OWNER_UAT_CHECKPOINT_2026-10-11.md)
- [Context Capture](CONTEXT_CAPTURE.md)
- [Backlog Ideas](BACKLOG_IDEAS.md)
- [Decisions and Open Questions](DECISIONS_AND_OPEN_QUESTIONS.md)
- [Current Execution History](EXECUTION_HISTORY_CURRENT.md)
- [Owner Refresh](OWNER_REFRESH.md)
- [Owner Refresh Closeout](OWNER_REFRESH_CLOSEOUT_2026-10-01.md)
- [Owner Screenshot Import](OWNER_WEIGHT_SCREENSHOT_IMPORT.md)
- [Stable Owner Runtime Closeout](STABLE_OWNER_RUNTIME_CLOSEOUT_2026-09-21.md)
- [CI Maintenance Closeout](CI_MAINTENANCE_CLOSEOUT_2026-09-17.md)
- [R04 Release Closeout](R04_RELEASE_CLOSEOUT.md)
- [R05 Release Closeout](R05_RELEASE_CLOSEOUT.md)
- [Agent Orchestration](AGENT_ORCHESTRATION.md)
- [Development Process](DEVELOPMENT_PROCESS.md)
