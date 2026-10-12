# Decisions and Open Questions

Current architecture/product decisions and remaining meaningful UNVERIFIED items.
Historical decision evidence stays in release issues, audits and Git history.
Current engineering is reconciled on **2026-10-12** against accepted product
`main 8100b7ae7051af181a6bf3151ce3bc3e1d4c4151`; the
[Wiki](PROJECT_WIKI.md#current-canonical-state) owns live receipts and the separate
daytime installed Stable SHA. No new product decision is made here. Historical
Owner direction and PARTIAL UAT remain evidence, not a repeat launch queue.
[Current History](EXECUTION_HISTORY_CURRENT.md) owns outcomes;
[Roadmap](ROADMAP.md#current-backlog) owns remaining deltas.

## Final decisions

### Product and release sequence

- Health-Check remains a single-user personal health observatory on a Windows laptop; dashboard and conversational AI are equal surfaces over deterministic evidence.
- Health domains remain weight/body composition → sleep → activity/fitness → recovery/wellbeing. This domain order is distinct from the immediate implementation priorities below.
- R01–R05 are released. R05 closed with exploratory agreement, Garmin canonical/default and #105 NOT_ELIGIBLE.
- Period Brief #119, durable Runtime, Context v0, Training/Recovery, source freshness, screenshots/corrections and technical maintenance foundations are complete.
- #189 and #306–#309 are historical completed UI work. A+ shared shell/Overview, Sleep v3, compact Activity A/B and Activity v4, Weight-chart clarity and compact source attention are now integrated; they are not awaiting the original design discussion.
- #295 now has indexed freshness and request-local /brief reuse integrated; Owner reports perceived speed improvement but first open exceeded 30s and repeat ~14s on copied data, so no cold performance PASS. #298 Stress and #153 optional openScale work remain not planned.
- A custom Health-Check Recovery Score remains deferred until an evidenced unmet decision need.

### Owner decisions and remaining gates — 2026-10-12

**Accepted engineering is not reassigned.** #375 history, #376 last-eligible RHR,
#380 bounded long Statistics windows, #395 routine Steps wiring, primary Comments
navigation/city-IANA timezone and saved-session/drilldown work are delivered.
PRs #407–#411 additionally delivered Google401 recovery, readable dates/units,
compact Data, completed-day Steps and provider-first presentation. Their exact
receipts/post-main SUCCESS are [indexed in the Wiki](PROJECT_WIKI.md#current-canonical-state).
Installed Stable is daytime `aca4b8f…`; night changes have no rollout/Owner UAT.

- #305/#376 still require eligible saved metric value/date/age and clone age.
  Compact stream chronology/refresh status is not that evidence.
- #347 delivered presentation only. General per-metric eligible-source
  discovery/autoselection is outstanding; preserve exact identities and
  Sleep-only #342 default, no pooling or false metric availability.
- [#393 Stage A research ACCEPT](https://github.com/LTstripes/Health-Check/issues/393#issuecomment-6115459995)
  leaves Stage B PARKED for Owner minimum eligible days/coverage, precision and
  rounding, and custom windows >400 days. Proposed defaults are not decisions.
- [#319 energy disposition](https://github.com/LTstripes/Health-Check/issues/319#issuecomment-6113152691)
  is an evidence blocker: authoritative leaf/unit/category/interval, resting
  inclusion, correction authority and separately authorized eligible coverage
  are missing. No component addition, zero-fill or invented formula; typed
  max-HR/anaerobic B1 is complete.
- #377 completed-day view selects latest proved acquisition after Europe/Moscow
  day end, preserving repeats/lower corrections/ties/missing and v1/history.
  It is not final Garmin totals; cooperative 5-second guard is not a hard SQL
  deadline and real latency awaits UAT. #392 Google Steps and #394 Body Battery
  meaning remain separately gated.
- #379/#378 retain broader style/discovery/Owner acceptance work, without
  repeating date/unit or session drilldown delivery. Google #406 repair is
  synthetic-only; real Stable recovery/original failure cause remains unproven.

No new health score, inference, sharing, mobile scope or release/provider/write
authority. #341 direct ChatGPT connection, #348 labs, #357 stress baseline and
weight-goal Settings stay separately deferred. No product choices are resolved
by this closeout.

### Owner source comparison is not canonical-source switching

The A+ design, accepted source-specific reader and 7/30 Sleep/Statistics
implementation remain intact. Ordinary product language presents two providers
(Garmin and Google) while retaining exact saved source identities and eligibility
for the chosen metric/window. A Fitbit source and a Google family-aggregate
may overlap; they must not be treated as independently additive without proof.

Independent per-source values may be shown side by side without Agreement pairs.
A numerical delta requires compatible metric meaning, actual observation/period
windows, eligible denominators and units. Missing sources stay visible and
dated, not copied from another source or silently zeroed. The existing canonical
Garmin/R05 decision remains unchanged until the separate evidence gate is met.

Longitudinal "latest eligible" display is a *presentation of saved evidence*,
not a new canonical/current-day value or blanket completeness certification.
Stored time and BIA source provenance must be preserved under the accepted
precise time/date-only, correction and method rules.

### Runtime

- Python 3.12+, FastAPI, SQLite WAL, SQLAlchemy/Alembic, Windows-first local operation.
- One local codebase/database; loopback dashboard/read/import listener plus optional separate ingest-only process.
- Long sync/report jobs are explicit idempotent CLI/application-service operations suitable for Task Scheduler.
- Runtime data/artifacts/secrets live outside Git under an Owner-scoped data directory.
- No Redis/Celery/Kafka/Postgres/Kubernetes/multi-tenancy without demonstrated need.
- A disposable copy of real data is not synthetic and not automatically current Stable. Updating application code does not refresh the copy or recover providers. Startup may prepare/migrate its selected runtime; do not use it as a read-only probe.

### Data and provenance

- Raw evidence, typed source data, current/canonical selection, derived analytics and LLM narrative are separate layers.
- Preserve competing source values and historical revisions; canonical rules/algorithms are versioned and reproducible.
- Physical device, provider/input method and measurement algorithm are separate identities. Provider/query family is not physical-device proof.
- Missing/null/zero/unavailable/unknown never collapse silently. Exact coverage/eligibility matter even when both sources are visually adjacent.
- Original comments/documents are evidence, not instructions to model tools or permission for autonomous writes.

### Xiaomi S400 / R01

- Routine Weight: Xiaomi Home/S400 screenshot → repo `health-weight-screenshot-import` skill → Owner-assisted strict extraction → R01 pipeline → Stable.
- #217/#219/#221 live proof covered OLD/NEW imports, exact duplicate replay, two new sessions and retained history, not every cross-image/revision case.
- openScale/openScale-sync remain external GPL applications and optional alternative contract. #153 is not planned; its historical numeric-userId issue is not a screenshot gate.
- Xiaomi-app and openScale composition remain distinct compatibility groups without an accepted paired-evidence calibration.
- #226 validates accepted screenshot algorithm identities before auto-confirm. Foreign explicit code, incompatible group or conflicting producer/metric-family metadata requires review before semantic writes; omitted permitted versions stay unknown.
- Model confidence is not confirmation policy. #229 reviewable changed-sidecar corrections and #240 metadata origins preserve history; date-only Owner attestation does not become visual evidence or invented time.
- #228 artifact vs source-event identity research is accepted, not cross-image dedup implementation. No fuzzy/date/value auto-merge, midnight inference or historical rewrite without trustworthy event proof.

### Garmin / R02–R03

- Use pinned `python-garminconnect`, not a second HTTP client. Protected Owner auth/session state stays external.
- Only reviewed read/download semantics are permitted; method existence is not device capability proof.
- Preserve raw/observation/current provenance, coverage, incremental/historical checkpoints and authoritative/partial reconciliation. Parser changes are version-aware.
- R03 metrics/time definitions and immutable manifests own analytics; UI does not reimplement statistics.
- Native scores remain native. Accepted Training includes Status, daily/chronic load, ACWR, Load Focus, Readiness/Recovery and activity Effect/load. Acquisition date is not necessarily provider source date.
- Associated device/activity recorder is not metric-producer proof. Recovery Time units and VO2/max metrics stay unavailable without accepted evidence.
- Normal Owner refresh includes bounded Training sync with the same auth/client.
- Only evidenced `tennis_v2` renders as Теннис; codes/formulas stay unchanged. #319 max-HR/anaerobic B1 is complete; calories still require authoritative meaning/coverage evidence, not requested cards.
- Maintenance #98 updated python-garminconnect 0.3.12 → 0.3.15; #99 hardened Google auth/sync tests. Both are complete, not new semantic dependencies.

### Google Health / R04

R04 is released; accepted contract remains:

- Google Health API v4 only, no new legacy Fitbit Web API implementation.
- Web Application/Web Server OAuth with fixed exactly registered loopback callback.
- Client secret/token/session stays external with Windows user-scoped DPAPI; non-Windows #247 writes purpose-bound AEAD v2, reads authenticated v1 and migrates on normal writes only. Reads do not create missing keys.
- Exactly two accepted read scopes: sleep and health metrics/measurements. Historical In-production/External Owner consent/session reuse was proven, not perpetual token durability.
- `list`, `reconcile`, `rollUp`, `dailyRollUp` and `dataSourceFamily` are acquisition context, not stable device identity. Raw/list evidence is separate from aggregates/reconciled output.
- Accepted types include sleep, HR/HRV/daily HRV, daily resting HR, SpO2/daily SpO2, sleep-summary and daily respiration. A Google proprietary sleep score is not automatically available or equivalent to sleep efficiency; #342 verifies actual support.
- Pagination follows nextPageToken; bounded sleep pages and inclusive-lower/exclusive-upper windows. No assumed undocumented ordering.
- Historical/incremental/refresh namespaces are distinct; completed windows can skip calls only when coverage proves completion. Explicit bounded refresh may fetch corrections.
- Missing/null/zero/confirmed-empty are distinct; unknown shapes fail closed.

#### Owner collection selection — 2026-09-29

High-frequency Google heart_rate remains OFF in the Owner Ops runner; Garmin is the
primary high-frequency HR source. This does not delete history, change bare CLI
defaults or disable Google HRV/daily resting HR/fixed wearables-sleep reconciliation.
The gap is intentionally uncollected, not provider-empty or complete. Re-enable
and historical catch-up require separate bounded decisions; no automatic backfill.

#### Live terminal-envelope decision from #110

Owner evidence proved terminal HTTP-200 LIST omitted both dataPoints and nextPageToken.
Only LIST/RECONCILE missing collection with no usable token becomes complete empty
terminal page. A usable token continues; arrays follow normal rules; null/object/
string/number/boolean/malformed shapes stay invalid. Rollup is not broadened. The
repaired completed-window replay made zero calls.

### R05 agreement / canonical sleep

Frozen design from #97:

- Legacy sleep pairing uses local wake date and one eligible main overnight session per source/date; naps and ambiguous mains are excluded.
- device_pair needs explicit device metadata; family_pair is exploratory. Manual Google-edited evidence is excluded from the strong 42-night gate.
- Comparable session metrics are projected separately; native scores are display-only, not equivalent measurements.
- Difference is google minus garmin; N, bias, MAE, RMSE, Bland–Altman limits and robust summaries retain coverage, association secondary.
- Exploratory gate: 14 paired nights. Canonical gate: 42 valid device-pair nights across at least six weeks plus coverage/stability. Garmin remains default until a reviewed versioned per-metric rule; no switch from N/correlation alone.
- R05 may close without a canonical change when evidence is insufficient.

The separately accepted [account-observation contract](R05_ACCOUNT_SLEEP_OBSERVATIONS.md)
permits eligible identified account/family evidence and uncertain singleton roles
without device-equivalence/canonical claims. #317 source-only views reuse those
rules, exclude explicit naps, preserve multiple sessions without pooling/winner and
apply source/record/provenance gates to Garmin score/naps and the primary table.
The original DEVICE_PAIR/role/native-gate findings were corrected and independently
re-reviewed before integration; legacy Compare/Agreement is unchanged.

### Period Brief / post-R05

- #119 is the deterministic bounded cross-domain packet; Weight/sleep/activity/data-quality facts retain coverage and stable identity.
- UI/text/CLI are renderers; display changes cannot rewrite formula/count/hash. Direct R05 report reuse avoids copied agreement semantics.
- #146/#133/#129/#127 correctness/UAT, #172 UX, #189 and later A+ page work are integrated. New #341 is a separate versioned evidence envelope, not a silent rewrite of #119.
- #203 changes limited-encoding stdout only; #248 explicit JSON/text preserves default packets.
- #307 retains full custom Period Brief/Garmin range; only Google daily-vitals display is bounded to the trailing 400 inclusive days with exact visible scope.

#### Compound read consistency — #227 accepted

Weight/Period Brief compound reads establish one physical SQLite snapshot including
assembled queue/freshness. Clean pre-BEGIN or prior-transaction ORM objects must
align; expire_on_commit=False alone is insufficient. The local helper preserves
caller-owned transaction/close, rejects pending new/dirty/deleted state before cache
actions, retains flushed writes and expires clean caches on new/reused physical
transactions. It does not globally change engine/writer/provider semantics. The
initial missed pre-BEGIN cache case required independent review/remediation.

### Stable Owner Runtime / owner operations

- Private durable profile: `D:\HealthCheck\stable`; clean code/control: `D:\HealthCheck\main`; Ops: `D:\HealthCheck\ops`; disposable UAT and Worker roles follow [Owner Machine Layout](OWNER_MACHINE_LAYOUT.md).
- Stable is long-lived, never reset as UAT. Verified backup/restore clones are separate; no direct SQLite grafting between profiles.
- Bounded backup/verify/restore retains checksum/integrity/atomic protections; a local archive alone is not off-site recovery proof. #148's practical verified Drive ZIP/restore is accepted; protected age publication remains optional.
- Dense selected Google HR uses civil-day partitioned resumable staging/bounded transient retries; instant/interval identity is path-free, with retained legacy observations.
- Provider operations and cutoff-bounded stale-run recovery share the runtime lock; no fabricated success/checkpoint reset. #132's no-stale/no-duplicate outcome is dated, not perpetual.
- Owner code/Ops is separate from GitHub main and Worker trees. Merges never auto-deploy.
- Comments navigation/timezone is in the daytime installed rollout; durable save/edit/persistence Owner UAT remains separate. UAT comments do not automatically become Stable history.

#### Owner refresh / collection-policy operational status

#214 proved an automatic/logon selected-stream run with Scheduler result 0 and
successful Garmin/Training/Google/wearables-sleep layers; it does not guarantee
future runtime duration, sleep-resume, exactly-once or perpetual availability.
#238 makes collection intent explicit/reversible: disabled HR is non-actionable
without false fresh/provider-empty labels; enabled failures remain visible and
re-enabling does not authorize broad backfill.

### Source freshness / data quality

- #147/#191/#193 are complete provider-call-free shared projections; vocabulary fresh | quiet | stale | unavailable | unknown | not_requested.
- Attempt/success, evidence time, coverage/checkpoints and configuration/request state remain distinct.
- Daily due/grace is versioned; activities use proven inventory; voluntary Weight is non-alert by default. Unknown chronology does not become healthy; optional metrics do not fail a healthy provider.
- #305 compact provider/action/stream presentation is integrated; eligible metric value/date/age and clone age are still missing. Successful freshness reads do not prove provider recovery or full Data acceptance.
- #295 per-source indexed Google freshness reads are integrated with preserved facts. Latest clone /brief still takes 12–18 seconds; no arbitrary cache or deadline increase is authorized.
- P1 #342 diagnoses missing Google sleep/scores, provider failure and clone-vs-live state; #340 owns the stored RHR surface exclusion. Weekly HRV remained missing in the inspected window; Google daily values cannot substitute it.

### Time, coverage and agreement

- Store valid UTC plus original local time/offset/zone when present; preserve date-only/local-only precision.
- Sleep is aligned by local wake date; lag direction is explicit.
- Nontrivial results carry coverage; missing days are not zero.
- Associations are exploratory, never causal/medical claims.
- Independent side-by-side values may have different coverage. A numerical comparison additionally requires compatible definitions, windows and denominators.

### CI, verification and repository integration

#123–#125 and #181/#243 are accepted: targeted iteration, frozen exact candidate,
PR integration and post-main gates; final checks fails on incomplete/malformed/
cross-run evidence or missing mandatory proof. Exact Linux nodeids/multiplicity
reconcile across the three lanes; Windows actually runs DPAPI/startup/HTTP/cleanup.
No green subset or partial rerun replaces full same-attempt evidence.

#251 lane balance, #246 docs-only/event dedup, #242 dependency audit, #244 Host/Origin
and #302 deterministic Linux environment are complete. A docs filename alone does
not authorize skipping CI; the classifier decides. No broader Windows matrix,
cache/xdist or new CI optimization without measured need. Preserve old failures.
See [Development Process](DEVELOPMENT_PROCESS.md).

#### Repository protection / #126

- Recheck current visibility/plan/capability before settings changes; private-data boundaries remain regardless of visibility.
- #126 remains an Owner/capability decision. Exact-SHA checks SUCCESS is required regardless of server enforcement.
- No force-push/deletion of canonical history, billing/settings/visibility change or implicit public-data clearance.
- #167 historical metadata rewrite is deferred and requires an explicit coordinated freeze.

### AI / reports / context

- Typed bounded read-only analytical access, not unrestricted SQL or inherited sync/import/restore powers.
- Deterministic/versioned reports precede narrative and delivery.
- Context v0 stores revisioned original text, explicit time and optional confirmed tags; #215 proved first private Stable adoption. No mandatory diary, inferred date/tag or assumed negative exposure.
- #294 portal/navigation/city-IANA input and #341 selected evidence export are integrated. Preserve one Context system and packet/revision/source identity; original content is untrusted data. Durable Owner UAT and direct chat transport remain separate.
- Direct authenticated ChatGPT connection is planned and must be verified end-to-end with account/host capability and consent; no current direct localhost access claimed. Telegram is optional.
- R09 first document intake is #348; extraction candidates are not confirmed lab values. Preserve original document/report-specific units/ranges/qualifiers and event dates before interpretation.

### Development model bookkeeping — retired 2026-10-03

The Owner discontinued model benchmarking/attribution in [#210](https://github.com/LTstripes/Health-Check/issues/210).
Reports retain actual technical outcomes/checks without runtime model/provider
confirmation or journals. Recommend complexity/model outside short task prompts;
Sol 6.1 High remains the usual implementation route, not a benchmark claim.
Independent review and CI/privacy boundaries remain unchanged.

### License

- Health-Check is MIT; python-garminconnect is an MIT dependency.
- External GPL/AGPL projects stay external/reference-only unless obligations are accepted.
- Donor reuse is reviewed and pinned to exact versions.

## Remaining UNVERIFIED / open observations

### Xiaomi / R01

- #153's optional device E2E path is not newly proven and not a screenshot gate.
- Historical algorithm/application versions may remain unknown; no calibration without accepted paired evidence.
- #229/#240 are integrated; #228 cross-image identity is parked, not implemented.

### Garmin / R02–R03

- Future MFA behavior, shape drift and retention beyond released proof.
- Recovery Time units/producer attribution and VO2/dedicated max metrics outside accepted evidence.
- #319 calories remain blocked on field meaning/units/coverage; max-HR/anaerobic B1 and #340/#353 RHR eligibility repair are delivered, not new implementation assignments.
- Current provider health and weekly HRV upstream cause remain unproven by the clone report. #98 maintenance is complete.

### Google Health / R04

- Long-elapsed OAuth durability and late-correction frequency remain observational.
- Device attribution is record/surface-specific; family membership is insufficient.
- Pre-July Owner history was not established by the prior audit; no speculative broad backfill.
- Disabled sample-HR history is incomplete by Owner choice, not a provider limitation.
- #342 accepted saved-source classification and the Sleep-only default; current provider recovery and Google vendor-score support remain unproven. Preserve source absence, dates/filters/eligibility and copied-failure distinctions; never rename sleep efficiency as a vendor score.

### R05 / agreement

- Device-pair evidence remains insufficient for #105; account observations remain noncanonical.
- Firmware/app/algorithm change points may need separate epochs.
- #317 and #343 two-source Sleep history are integrated; that does not prove current real Google coverage. Both source series remain visible without changing pairing/statistics/canonical rules.

### Operations / durability / CI / Owner UAT

- #214 one automatic run, #215 first Context adoption, #148 practical recovery and #256 filesystem/janitor are complete foundations, not current service guarantees.
- #181/#243 lifecycle/transcript and #251/#246 CI maintenance are complete. #126 enforcement remains separate.
- Current human #330 UAT is PARTIAL. Keep positive design/Weight/Activity findings and unresolved per-screen data/performance requirements; do not describe it as unperformed or overall PASS.
- Latest installed Stable activation is the daytime `aca4b8f65eb276dddb3ae5de718a734afd19f369` rollout, confirmed by the [local receipt attribution](PROJECT_WIKI.md#current-canonical-state); Comments navigation/city-IANA input is included. Night PRs #407–#411 rollout, durable Context save/edit/persistence Owner UAT and direct chat connection remain separate pending gates. This documentation work performs no deployment/provider recovery/backup.

## Deferred owner choices

1. #126 protection/capability: no implicit purchase/settings change.
2. R07 email/scheduled transport remains unselected.
3. #341 direct read connection needs actual capability/auth/revocation/host setup; export is first useful transport, not a blocker on connection choice.
4. Recovery Score only for an evidenced unmet need.
5. Full remote portal exposure remains out of scope; bounded read tools are separately authorized.
6. A+ style is decided. Assign only remaining issue deltas after checking delivered stages and source contracts; #343 Sleep, Context and evidence-export foundations are integrated. No new global redesign or lost shared-file ownership.
7. #167 history rewrite requires a new Owner decision/freeze.
8. #228 cross-image merge requires trustworthy event proof.

## Change protocol

Architecture-invariant changes cite primary evidence, affected releases/migrations
and the owning contract/ADR. A donor README, method name or plausible model answer
is not enough. Owner product priorities/layout can change by explicit decision;
that never silently changes source/health semantics or grants runtime access.
