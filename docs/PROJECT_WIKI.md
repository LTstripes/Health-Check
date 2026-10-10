# Health-Check Project Wiki

This is the compact current-state entry point. The [roadmap](ROADMAP.md#current-backlog)
owns sequencing, issues own execution contracts, and release/history documents retain
proof. Do not use an older status paragraph as an instruction to repeat completed work.

<a id="current-canonical-state"></a>

## Current canonical state — 2026-10-10

This is a dated engineering snapshot of `main 6cef1e1875afd0c8bfc2279154a15785a0230c67`.
Read [live main](https://github.com/LTstripes/Health-Check/commits/main) and the
[active issues](https://github.com/LTstripes/Health-Check/issues) before assigning work.
The roadmap owns sequence/dependencies; issue/PR receipts own candidate checks,
review, acceptance and remaining gates. History and closeouts retain dated evidence.

- The desktop A+ wave, Context portal and standalone evidence export remain integrated.
  Subsequent accepted slices are [stored Garmin RHR projection (#353)](https://github.com/LTstripes/Health-Check/pull/353),
  [source-specific period summaries (#355)](https://github.com/LTstripes/Health-Check/pull/355),
  [bounded read-only evidence MCP endpoint (#356)](https://github.com/LTstripes/Health-Check/pull/356),
  [Owner data workflow (#359)](https://github.com/LTstripes/Health-Check/pull/359) and
  [source-specific sleep range reader (#360)](https://github.com/LTstripes/Health-Check/pull/360).
  A backend reader or transport does not establish completed UI or account connection.
- [Owner UAT #330](https://github.com/LTstripes/Health-Check/issues/330) remains PARTIAL;
  [#295](https://github.com/LTstripes/Health-Check/issues/295) owns remaining real Overview latency,
  [#342](https://github.com/LTstripes/Health-Check/issues/342) source availability,
  and [#341](https://github.com/LTstripes/Health-Check/issues/341) export/MCP connection disposition.
  Use those live records for remaining private/runtime gates, not an older launch list.
- Latest numbered release remains R05; R06 as a whole and R09 are not declared released.
  GitHub acceptance does not deploy Owner-local code, refresh Stable/providers or complete human UAT.
- Dependabot #270/#271 remain review proposals; administrative #126 and deferred #167
  remain separate Owner decisions. Existing CI/review gates apply to each new candidate.

## What the product can do today

### Owner interface

The primary sections are **Обзор / Вес / Сон / Активность / Данные** under one
approved A+ Russian visual/state/disclosure system, desktop CSS width 1024px+.
Overview is `/brief`; Weight remains `/`; Sleep is `/sleep` with secondary
`/agreement`; Activity is `/garmin` with Сессии and Тренировки и восстановление;
Data is `/imports` with freshness and existing import review.

Overview has real source-backed primary readings/charts and quieter source-specific
metrics. #334 improved sparse Weight axes/legend; #333 made source actions compact.
Interpretation-changing dates/limitations stay visible; full provenance and raw
packet evidence remain behind disclosure. #307's Google daily-vitals display for
custom periods over 400 days is bounded to the trailing 400 inclusive days, without
narrowing the full Period Brief/Garmin period or fabricating older absence.

Sleep v3 displays bounded persisted Garmin/Google source sessions, including
unpaired account observations, exact wake dates, role uncertainty, source-specific
stage/timing limits and Garmin-native score/nap gates. Daily Google vitals remain
separate. Compare/Agreement retain their statistical and canonical boundaries.
The source-specific 7/30-day reader is integrated in #360; the primary history UI
remains a separate #343 slice.

Activity has five recent sessions with full existing history under disclosure
(#335), five-column A/B and human duration (#318). B−A/percent-to-A, genuine zero,
missing values and technical evidence remain unchanged. The evidenced `tennis_v2`
alias renders as Теннис without rewriting stored codes. Detailed sessions (#345),
period recovery cards (#346) and Statistics UI (#347) are planned; #355 supplies
the accepted source-specific summary backend.

Data prioritizes pending imports and folds completed history. An unconfigured
browser photo extractor remains honestly unconfigured; the accepted screenshot
skill is separate. In the latest real-clone observation the freshness request
returned a result, but saved reauth/failure/disabled states are not collection
success. #305/#342 own those distinct remaining questions.

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
- #319 remains the evidence gate for new calories/max-HR/dual-effect fields. Existing duration/distance/average-HR detail need not wait for optional fields.

### Google Health

- Web Application OAuth with fixed registered loopback callback and external protected state; Windows DPAPI unchanged, non-Windows purpose-bound AEAD v2 (#247), compatible authenticated legacy reads and no key creation on pure reads.
- Accepted read-only sleep/health-metrics scopes; raw/current typed evidence and bounded incremental/backfill/refresh, privacy-safe diagnostics, coverage/checkpoints and replay.
- Collection intent remains explicit. The bare CLI default includes sample HR, but the Owner Ops wrapper applies HR-OFF; disabled history is not relabelled fresh/provider-empty. Fixed wearables-sleep reconciliation remains distinct.
- Historical release/live collection proof does not establish today's provider auth or completeness. Empty accepted pairs are not proof that Google has no source records. See #342 and [Owner Refresh](OWNER_REFRESH.md).

### Reporting and context

- Deterministic Period Brief and thin API/text/CLI rendering with stable packet/hash, explicit JSON/text stdout (#248), limited-encoding compatibility (#203) and coherent compound SQLite/ORM reads (#227).
- Shared persisted freshness (#147/#191/#193/#238), not ad-hoc UI thresholds. #295's indexed per-source Google reads preserve the existing facts; current real Overview is still slow.
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

## Current real-data limitations

The [Owner-local report](https://github.com/LTstripes/Health-Check/issues/330#issuecomment-6074940976)
at the product checkpoint records `/brief` first 18.402 s, one repeat 11.983 s,
7-day 9.345 s; `/api/source-freshness` 1.846 s, all HTTP 200. These are bounded
observations, not controlled before/after benchmarks. #295 remains open.

#353 repaired the stored Garmin RHR Overview surface exclusion under #340;
that engineering result does not establish fresh provider collection. Weekly Garmin
HRV had missing stored values in the inspected window even ignoring that predicate. #342 separates clone
snapshot, absence, projection exclusion, source/window mismatch, disabled
collection and provider failures; no substitution from Google or broad sync is
implied. #330 human comments are more recent than the earlier automated readiness
report: overall acceptance remains PARTIAL, not «human UAT not performed».

## Next product capabilities, not implemented promises

The [current backlog](ROADMAP.md#current-backlog) records scope and dependencies:
#343 two-source Sleep history; #344 Overview chart/disclosure polish; #345 session
details; #346 weekly/monthly training/recovery cards; #347 Statistics; #348 lab
candidate/confirmation flow; #294 Stage B weight-goal settings.

For **#347 Statistics**, default paired columns show **one source left, another
right**, both visible with names, units, effective dates, eligible counts and
coverage. A compatible right-minus-left difference may be shown; incompatible
windows/definitions remain independently visible without a numerical delta.
Missing does not become zero; sources/devices are not pooled into one total.
The same aggregates can later supply Activity, Overview and chat evidence.

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
