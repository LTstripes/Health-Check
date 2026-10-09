# Health-Check Project Wiki

This is the compact current-state entry point. The [roadmap](ROADMAP.md#current-backlog)
owns sequencing, issues own execution contracts, and release/history documents retain
proof. Do not use an older status paragraph as an instruction to repeat completed work.

## Current canonical state — 2026-10-09

- Latest accepted engineering checkpoint before this docs closeout: `main 8efb1f972ba9a77dc014b69ca93f4168d573482b` after Context PR #350 and exporter PR #351; [post-main CI 37975552600](https://github.com/LTstripes/Health-Check/actions/runs/37975552600) SUCCESS attempt 1. Earlier A+ checkpoint `013482ec3a51d89fd57c3a55ab9b09d1d2228e25` and docs #349 are historical. Read live main before work.
- Approved desktop-only A+ shell/Overview (#321/#322/#326/#328), Sleep v3 (#317), compact Activity A/B (#318), Activity v4 (#335), sparse Overview Weight chart (#334), compact source attention (#333) and indexed Google freshness reads (#295) are integrated.
- Human Owner UAT **#330 is PARTIAL**, not unperformed and not overall PASS. Style, dedicated Weight and shorter Activity history received positive feedback; data availability, Sleep history experience and new functionality remain active requests.
- Latest numbered release remains R05. Post-R05 Runtime, Period Brief, Context v0, Training/Recovery, source freshness/collection policy, screenshots and reliability/correction foundations remain canonical. The first R06 Context/export slices are engineering-integrated, but R06 as a whole and R09 are not declared released.
- The last verified Owner UI was launched from the product checkpoint on an existing verified **disposable copy of real data**. That is neither synthetic data nor an automatically refreshed Stable profile. A GitHub merge alone does not deploy code or refresh records.
- Dependabot #270/#271 remain independent review proposals; administrative #126 and deferred #167 are not housekeeping changes. CI optimization is not reopened by this product plan.

## First wave integrated; Owner-private gates remain

#294 Stage A now supplies the secondary `/context` dated notes/history and
#341 Stage A supplies a bounded standalone selected-period evidence export.
#342 Phase A/B offline classification on the verified UAT clone is ACCEPT;
Google sleep history exists, while selected-date and Compare cohort gates
cause distinct empty views. An app read bug and current provider recovery
were not proven. [Roadmap](ROADMAP.md#current-backlog) owns next sequencing.

Owner durable Context UAT and first private export remain UNVERIFIED; later
share UI/authenticated read access and #343–#348 are not launched. #330 stays
PARTIAL. The old Owner UI stopped; GitHub merges neither restart it nor
refresh Stable or providers. Both Context/export test-lane entries survived
the merged tree, and #351 exact post-main CI passed. Provider rights are
unchanged; Garmin RHR remains #340.

The intended first usable flow is **comment with explicit date/optional time →
durable read-back → selected health/context evidence → discussion in ChatGPT**.
A private export is the first transport. Direct authenticated read tools require
verified account/connection setup and cannot be obtained merely by handing a skill
the Owner's loopback URL. Telegram is optional, not a dependency.

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
The requested two-source 7/30-day primary history is **planned #343**, not shipped.

Activity has five recent sessions with full existing history under disclosure
(#335), five-column A/B and human duration (#318). B−A/percent-to-A, genuine zero,
missing values and technical evidence remain unchanged. The evidenced `tennis_v2`
alias renders as Теннис without rewriting stored codes. Detailed sessions (#345),
period recovery cards (#346) and Statistics (#347) are planned.

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
- Context v0 adds/lists/revises original text with explicit time precision, append-only history and idempotent requests. #294 Stage A portal and #341 Stage A versioned bounded export are integrated without rewriting Period Brief packet or doing LLM-side raw-series mathematics.

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

The selected Garmin RHR has otherwise usable stored evidence excluded by the
Overview surface predicate (#340). Weekly Garmin HRV has missing stored values
in the inspected window even ignoring that predicate. #342 separates clone
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
- Real health data, screenshots, tokens, payloads and runtime DBs stay outside Git/CI/Worker workspaces.
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
