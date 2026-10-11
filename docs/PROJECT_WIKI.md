# Health-Check Project Wiki

This is the compact current-state entry point. The [roadmap](ROADMAP.md#current-backlog)
owns sequencing, issues own execution contracts, and release/history documents retain
proof. Do not use an older status paragraph as an instruction to repeat completed work.

<a id="current-canonical-state"></a>

## Current canonical state — 2026-10-11

Canonical accepted engineering checkpoint:
`main f0e6c36c4d10f03069111665f10201575ee6ea0e`;
[full post-main CI 38070804783](https://github.com/LTstripes/Health-Check/actions/runs/38070804783)
SUCCESS attempt 1. Read [live main](https://github.com/LTstripes/Health-Check/commits/main)
and [issues](https://github.com/LTstripes/Health-Check/issues) before implementation.

- The full A+ Owner wave is **engineered and integrated**: #343 7/30 Sleep timeline
  [PR #368](https://github.com/LTstripes/Health-Check/pull/368), #358 fixed-seed
  multidomain synthetic demo [#369](https://github.com/LTstripes/Health-Check/pull/369),
  #347 Statistics parity [#370/#371](https://github.com/LTstripes/Health-Check/pull/370),
  #295 request-local /brief read reuse [#372](https://github.com/LTstripes/Health-Check/pull/372),
  #345 saved Activity detail [#373](https://github.com/LTstripes/Health-Check/pull/373)
  and #344 chart/readability [#374](https://github.com/LTstripes/Health-Check/pull/374).
  No repeat of delivered implementation tasks.
- **Owner UAT #330 PARTIAL** on a verified disposable real-data clone as of Oct 8:
  A+ look, Sleep chart and working Activity were positively reviewed; last known
  measurements/source selection/data UX/timezone form and Statistics long windows
  remain next steps. Perceived speed improved but first `/brief` still timed out.
  Clone/old stored provider statuses are not present-day Stable/provider facts.
  [Owner decision](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6106537913).
- New contract/task ownership: #375 one Weight+composition history table,
  #376 dated last-known values, #377 typed steps evidence, #378 Activity
  function discovery, #379 A+ cross-app consistency, #380 long-range Statistics,
  while #342/#343/#347 own exact provider identity and #319 owns energy.
- R01–R05 remain numbered releases. R06/R09 as complete releases and durable
  rollout of this UI are not declared. CI acceptance is not private Owner
  readback, Stable deployment or live provider recovery.
- Dependabot #270/#271 remain independent review proposals; #126/#167 deferred
  Owner/admin controls are not automatic housecleaning.

## What the product can do today

### Owner interface

The primary accepted desktop 1024px+ A+ navigation is **Обзор / Вес / Сон /
Активность / Статистика / Данные**. Overview opens at `/brief`, Weight `/`,
Sleep `/sleep` (legacy source-night modes and secondary `/agreement`),
Activity `/garmin` with source-bound saved-session detail and A/B,
Statistics `/statistics` with **7/30-day source-specific Garmin/Google
columns**, Data `/imports` with saved freshness/import review. `/context`
provides existing revisioned notes but **Комментарии** is still a hidden
secondary link: Owner requested it in primary nav in #294.

Sleep B2 already uses readable Garmin and Google source histories, faithful
gaps and exact detail; the next source-default choice needs read-only evidence
(#342) because stored Google/Fitbit and family-aggregate identities may overlap.
Normal product display has two *provider concepts*, not three independent
brands. Statistics labels are still too technical with multiple exact source
identities, long periods and Steps/Energy are not yet implemented. Defaults
must not sum independent source identities or fabricate a Google score.

Overview and Weight retain real source-backed values, accepted 21d weight
trend, honest measured-point connectors and distinct BIA compatibility groups.
The new [#375](https://github.com/LTstripes/Health-Check/issues/375) request
consolidates all full-history confirmed Weight+composition into one dated table
and a method-distinguished metric chart — **planned, not delivered**.

Common **last eligible stored data with actual date/age** as a useful default
on days without a new observation is [#376](https://github.com/LTstripes/Health-Check/issues/376);
it must not silently change explicitly requested periods, claim today's
measurement or imply recovered providers. Forms/tables/secondary screens need
bounded A+ style consistency under #379, not another global redesign.

### Weight / body composition

- Xiaomi Home/S400 screenshots use the repo skill and strict Owner-assisted extraction over R01; foreign algorithm identity is rejected before semantic writes (#226).
- Original evidence, source/device/algorithm provenance and confirmed history are preserved; #240 records visible/Owner-attested/workflow-profile/unknown origins, while legacy NULL remains historical.
- Owner-supplied date is date-only; fixed workflow identity is not falsely called visual evidence. Exact attachment replay is duplicate-safe; cross-image semantic dedup is not implemented (#228).
- Changed-sidecar/provenance corrections (#229/#240) require explicit review; reject is non-mutating and confirm preserves revision/supersession history.
- openScale/openScale-sync compatibility remains delivered optional contract; #153 is closed as not planned. Screenshots are the operational path.
- Deterministic trends, observed daily medians and separate composition compatibility groups retain their meaning. #344 will add honest thin connectors and readability polish without changing EWMA or creating daily measurements.

### Garmin

- Protected Owner-assisted session reuse; incremental sync/backfill with coverage/checkpoints/reconciliation.
- Deterministic baselines/trends, activity/cycling comparison and bounded exploratory lagged associations.
- Garmin-native Training Status/load/ACWR, Load Focus and Readiness/Recovery with source chronology/provenance; requested acquisition date is not necessarily source date.
- Bounded Training sync is part of normal Owner refresh. No invented recovery-time unit, provider attribution or custom score.
- #319 already integrated typed max-HR and anaerobic Training Effect; saved history requires separate Owner replay. Calories/BMR meaning remains blocked; daily Steps source evidence is #377. Current #345 saved session detail is delivered.

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

The Oct 11 Owner-local UAT on the accepted current code opened all seven
primary pages successfully on an **older disposable copy** of genuine data.
Initial `/brief` exceeded a 30s budget; repeat ~14s. Nine checked tables
passed scoped verification; the full clone DB integrity scan timed out,
**UNVERIFIED**, not PASS or evidence of corruption. Old saved Garmin reauth
and Google failed collection statuses coexist with valid stored history:
they do not describe current provider reachability. Source freshness
and last eligible saved readings must be presented separately (#305/#376).

The earlier [offline #342 classification](https://github.com/LTstripes/Health-Check/issues/342#issuecomment-6087155625)
distinguished accepted account sleep pairs from device/family Compare,
source family vs data-source identities and saved record role exclusions.
A further read-only per-source eligibility/overlap decision is needed before
simplifying the normal Google source line in #343/#347; no pool or automatic
canonical switch. One disputed screenshot measurement date remains a
separate Owner-assisted correction gate; current code does not resolve it.

## Next product capabilities, not implemented promises

Execution is tracked in [Roadmap](ROADMAP.md#current-backlog) and live issues.
High-priority accepted decisions: #375 unified full-history Weight table/chart;
#342/#343/#347 provider meaning and readable Statistics source selectors;
#376 most recent **eligible** dated observation vs missing-today cue; #294
'Комментарии' primary navigation and selectable city/IANA timezone while
preserving internal offset/DST/date-only; #305 last saved values vs
copied provider state; #377 typed Steps and #319 calorie/BMR contract;
#380 trailing 365/calendar-year/all-history source-backed Statistics;
#379 A+ consistency for forms/tables and #378 Owner-requested Activity
functional analytics **research only** (avoid #346 duplicate cards).
Personal stress baseline #357 and lab-doc intake #348 are later independent
gates. Direct ChatGPT connection under #341 is deferred.

All changes need their own acceptance/candidate/PR/post-main gates. No hidden
date fallback, Google provider pooling, fake calories/steps or broad
unbounded historical query is authorized by product direction alone.

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
