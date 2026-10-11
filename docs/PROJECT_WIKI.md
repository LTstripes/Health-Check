# Health-Check Project Wiki

This is the compact current-state entry point. The [roadmap](ROADMAP.md#current-backlog)
owns sequencing, issues own execution contracts, and release/history documents retain
proof. Do not use an older status paragraph as an instruction to repeat completed work.

<a id="current-canonical-state"></a>

## Current canonical state — 2026-10-11

Accepted **product** immediately before this docs-only reconciliation:
[`main fa36dc5b6402fe6e6e166091002faf4af1ec0993`](https://github.com/LTstripes/Health-Check/commit/fa36dc5b6402fe6e6e166091002faf4af1ec0993);
independent [post-main CI 38164560091](https://github.com/LTstripes/Health-Check/actions/runs/38164560091)
**SUCCESS attempt 1**. Check [live main](https://github.com/LTstripes/Health-Check/commits/main)
and issues again before assigning new work. This docs closeout does not deliver product code.

- The earlier #343/#358/#347/#295/#345/#344 A+ Owner wave was already engineered,
  reviewed and integrated. Do **not** repeat #344 chart readability or #345
  Activity detail. Follow-up Activity design is [#378 Owner-held](https://github.com/LTstripes/Health-Check/issues/378).
- Accepted further code: #375 one complete saved Weight+composition table/chart
  ([PR #382](https://github.com/LTstripes/Health-Check/pull/382));
  #376 exact latest saved RHR reader and Overview consumer (PRs #383/#385);
  #343 exact eligible Google sleep family selection (PR #384);
  #347 human Statistics labels (PR #386);
  #380 bounded 365/calendar-year/YTD Statistics backend+UI (PRs #387/#388);
  #377 **Garmin-only** typed saved daily Steps projection/window/Stats
  ([PRs #389/#390/#391](https://github.com/LTstripes/Health-Check/issues/377)).
  This is not Google Steps acquisition, normal-refresh projector wiring,
  all-history Statistics, or a calorie entitlement.
- A clean local code checkout was advanced to accepted main and served against a
  previously verified **disposable saved-data clone as of Oct 8**; all main
  routes reported HTTP 200. Initial/repeat Overview 23.098s/9.470s
  (cache not controlled), fresh full DB integrity **UNVERIFIED**.
  [Human Owner UAT #330](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6113161066)
  stays **PARTIAL**, even though overall A+ reception is positive.
  Copied auth/refresh failures are not present-day provider reachability.
- **New bounded Owner issues**, not automatically launched:
  [#392 Google Steps](https://github.com/LTstripes/Health-Check/issues/392),
  [#395 Garmin routine Steps wiring](https://github.com/LTstripes/Health-Check/issues/395),
  [#393 period RHR mean](https://github.com/LTstripes/Health-Check/issues/393),
  [#394 Body Battery daily maximum/source proof](https://github.com/LTstripes/Health-Check/issues/394).
  Existing #379 Weight table display, #347 provider-first source selection,
  #294 primary Comments nav/timezone and #305 grouped saved-vs-refresh statuses
  retain their issues. #319 energy/BMR meaning is **BLOCKED**.
- R01–R05 remain named releases. Durable **Stable deployment has not occurred
  for this accepted UI**. Plan bounded Owner backup/restore rehearsal, process
  coordination, reversible code update and distinct human UAT
  ([dated handoff](OWNER_UAT_CHECKPOINT_2026-10-11.md)).
  The two open Dependabot PRs #270/#271 remain separate proposals.

## What the product can do today

### Owner interface

Desktop 1024px+ A+ primary navigation is **Обзор / Вес / Сон /
Активность / Статистика / Данные**. Overview `/brief`, Weight `/`,
Sleep `/sleep` (secondary `/agreement`), Activity `/garmin` with a
source-bound saved session detail route and A/B, Statistics `/statistics`,
Data `/imports`. The revisioned `/context` notes service/portal exists;
its small repeated header link is **not** the requested primary
`Комментарии` tab yet (#294).

**Already delivered:** one all-history Weight+composition table and
method-separated selectable chart (#375); Garmin+eligible Google Sleep timeline
with exact provenance/unknowns (#343); human Statistics source labels and
7/30/trailing365/calendar-year/year-to-date windows (#347/#380);
dated latest-eligible RHR Overview card (#376);
Garmin `observed_daily_steps` typed saved projection, bounded offline reader
and daily Statistics view (#377). A saved Steps cell requires prior
materialization and one exact source; current normal refresh wiring remains #395,
Google Steps production acquisition #392. All-history Statistics is a distinct
unimplemented bounded task; Energy/BMR #319 BLOCKED.

Normal Owner provider concepts are **Garmin and Google**, but exact saved
Google source identities still have metric-specific eligibility/ambiguity:
the accepted sole `google-wearables` family default applies to **Sleep only**
(#342), not physiology/Steps/Activity. Never pool Fitbit list copies,
family source, Google physiology or Garmin accounts. #347 still owns the
source-selection usability delta. Missing/ineligible/uncollected is not zero.

The new Owner screenshots confirm large unresolved presentation density in
Weight history/Context/Data, despite positive overall A+ feedback. A bounded
first formatting slice is #379; permanent source/form values remain exact in
technical disclosure.

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
- #319 already integrated typed max-HR and anaerobic Training Effect; saved history requires separate Owner replay. Calories/BMR meaning remains blocked; Garmin saved daily Steps are delivered under #377, normal refresh wiring remains #395, and Google Steps need #392. Current #345 saved session detail is delivered.

### Google Health

- Web Application OAuth with fixed registered loopback callback and external protected state; Windows DPAPI unchanged, non-Windows purpose-bound AEAD v2 (#247), compatible authenticated legacy reads and no key creation on pure reads.
- Accepted read-only sleep/health-metrics scopes; raw/current typed evidence and bounded incremental/backfill/refresh, privacy-safe diagnostics, coverage/checkpoints and replay.
- Collection intent remains explicit. The bare CLI default includes sample HR, but the Owner Ops wrapper applies HR-OFF; disabled history is not relabelled fresh/provider-empty. Fixed wearables-sleep reconciliation remains distinct.
- Historical release/live collection proof does not establish today's provider auth or completeness. Empty accepted pairs are not proof that Google has no source records. See #342 and [Owner Refresh](OWNER_REFRESH.md).

### Reporting and context

- Deterministic Period Brief and thin API/text/CLI rendering with stable packet/hash, explicit JSON/text stdout (#248), limited-encoding compatibility (#203) and coherent compound SQLite/ORM reads (#227).
- Shared persisted freshness (#147/#191/#193/#238), not ad-hoc UI thresholds. #295's indexed Google reads and request-local chart reuse are delivered; cold Overview on Owner clone still needs a measured follow-up despite perceived improvement.
- Context v0 adds/lists/revises original text with explicit time precision, append-only history and idempotent requests. #294 Stage A portal, #341 Stage A versioned bounded export and #356 read-only MCP endpoint are integrated without rewriting Period Brief packet or doing LLM-side raw-series mathematics. Direct ChatGPT connection remains deferred in #341.

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

[Owner UAT checkpoint](OWNER_UAT_CHECKPOINT_2026-10-11.md) is the current
sanitized owner handoff: code `fa36dc5b…` opened all primary routes on
the as-of-2026-10-08 disposable real-data clone; full fresh DB integrity
remains UNVERIFIED; `/brief` first/repeat 23.098/9.470s with uncontrolled
cache, not a performance PASS. Saved record presence and copied provider
failures do not establish live Stable synchronization; #305 keeps these
statuses distinct and #376 owns last-known dated evidence.

Confirmed UAT issues and their bounded owners: #379 Weight table rounded
display/human dates (NOT calculation), #393 eligible-day RHR mean, #394
Body Battery maximum interpretation before value change, #347 provider-first
Statistics with unambiguous exact source semantics, #294 primary Comments and
human IANA timezone, #305 condensed Data source status, #395 automatic
Garmin post-save Steps projection contract and #392 Google Steps type/source
research. **No new reader** for already integrated #377. #319
calories remains BLOCKED by authoritative field/unit/category/interval meaning;
do not add components or infer totals. #378 speculative Activity redesign
is held for Owner discovery.

The former five Google exact identities on the clone were classified under
[#342 accepted sleep overlap](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6107122463).
That acceptance authorizes one **Sleep** Google series, not a default for all
Google health metrics. Existing #343/#344/#345 engineering is integrated,
not an unstarted queue. No unapproved Stable rewrite, automatic provider
call, retrospective Garmin Steps projection or migration to change old
source definitions.

**Next operational choice:** an Owner-assigned controlled Stable code
deployment after fresh supported backup, verification and a restored-clone
startup/migration rehearsal. Stable/live provider UAT follows separately;
docs-only GitHub updates are not deployment.

## Next product capabilities, not implemented promises

Use [Roadmap](ROADMAP.md#current-backlog) for actual remaining deltas and
their dependencies. The key gaps are Google Steps producer proof,
routine Garmin saved-Step projection, source-specific RHR period mean,
Body Battery daily-maximum semantics, useful provider-first Statistics,
Comments navigation/timezone, Data freshness clarity and bounded A+ form/table
polish. #380 longer bounded windows are already merged; only complete
all-history remains. #319 energy and Activity redesign stay gated.
New code must pass exact candidate/PR/post-main gates; private Owner UAT,
Stable rollout and provider freshness need separately verified evidence.

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
