# Decisions and Open Questions

Current architecture/product decisions and remaining meaningful UNVERIFIED items.
Historical decision evidence stays in release issues, audits and Git history.
Reconciled on **2026-10-09** against product main
`013482ec3a51d89fd57c3a55ab9b09d1d2228e25` and Owner #330 feedback.
[Current History](EXECUTION_HISTORY_CURRENT.md) owns exact evidence;
[Roadmap](ROADMAP.md#current-backlog) owns execution order. Planned work below is
not an assertion that its code or connection already exists.

## Final decisions

### Product and release sequence

- Health-Check remains a single-user personal health observatory on a Windows laptop; dashboard and conversational AI are equal surfaces over deterministic evidence.
- Health domains remain weight/body composition → sleep → activity/fitness → recovery/wellbeing. This domain order is distinct from the immediate implementation priorities below.
- R01–R05 are released. R05 closed with exploratory agreement, Garmin canonical/default and #105 NOT_ELIGIBLE.
- Period Brief #119, durable Runtime, Context v0, Training/Recovery, source freshness, screenshots/corrections and technical maintenance foundations are complete.
- #189 and #306–#309 are historical completed UI work. A+ shared shell/Overview, Sleep v3, compact Activity A/B and Activity v4, Weight-chart clarity and compact source attention are now integrated; they are not awaiting the original design discussion.
- #295 was reopened after new real latency evidence. Its indexed Google freshness improvement is delivered, but real Overview is still slow; no blanket speed acceptance. #298 Stress and #153 optional openScale work remain not planned.
- A custom Health-Check Recovery Score remains deferred until an evidenced unmet decision need.

### Owner priority and launch decision — 2026-10-09

**Documentation reconciliation first, then the Owner launches the next tasks.**
No new task/Worker/provider operation is started by recording this decision.

1. **P1 #342 source availability is first-wave work**, alongside #294 Context and #341 health-chat evidence. Data is essential, not polish to postpone. Distinguish real-clone snapshot from current Stable/provider health, stored absence from exclusion and empty comparison from absent source observations. #340 remains the specific RHR surface-filter owner; #319 the extra activity-field evidence owner.
2. **#294 Stage A** adds portal add/list/revise comments with explicit editable event date and optional time/range, preserved wording/revisions/idempotency. Recorded-at is separate. Activate reserved dashboard capture source narrowly; weight-goal Settings remains later Stage B, not a dependency of comments.
3. **#341 Stage A** adds a bounded read-only health-plus-current-Context export over accepted services with its own versioned envelope, not a new Period Brief hash or LLM calculation engine. Later sharing UI follows #294 integration. Direct ChatGPT access requires a verified authenticated connection; a skill does not make Owner localhost reachable. Telegram is optional, not required.
4. Parallel scope: #294 sole UI/Context writer; #341 separate new export module/script/tests, existing Context interface read-only; #342 code/contracts researcher. Assigned host-specific workspaces/external synthetic roots are in the issues. Shared CI manifest additions are reconciled at integration; no overwriting another branch. Serialize heavy local tests on the shared machine.
5. Existing first-wave prompts remain valid because they locate the updated issue and live main. Feature start waits for documentation closeout; each worker pins its actual baseline at launch. New shared-file/private-data scope still needs an explicit decision.

### Owner source-comparison UX — planned, not changed analytics

The A+ appearance remains accepted; source data and useful capture/analysis precede
further cosmetic work. Detailed scope is in #343–#348, not an automatic queue.

- **Sleep #343:** primary 7/30-day independent Garmin/Google duration series, both visible with optional source toggles and point/focus/click detail. Dates are wake dates, units hours with readable intermediate ticks. Statistical Compare/Agreement is secondary; displaying independent observations does not require eligible paired runs or canonical-switch evidence. Missing/ambiguous sessions do not acquire an inferred winner or zero.
- **Overview #344:** thin visual Weight connectors are Owner-approved, with unmeasured spans visually distinct and no interpolated records, daily points or EWMA change. Improve Sleep ticks and move repeated long freshness prose into detail while retaining material date/source/action cues.
- **Activity #345/#346:** existing session detail cards first; optional calories/max-HR/dual effects depend on #319. Period recovery cards keep the dated native snapshot, proper denominators/coverage and meaningful aggregation. No averaging categorical status or summing overlapping rolling-load snapshots.
- **Statistics #347:** default **left-source / right-source columns for the same metric**, both visible, named and source-bound. Each side retains its units, effective dates, observed-day/session count and coverage. A compatible right-minus-left delta may be shown; otherwise display both independently with a short limitation, without a false numerical difference. Missing side remains labelled, not copied or zeroed. Do not combine Garmin/Google totals or pool devices under a brand label. Reuse the same accepted aggregates in Statistics/Activity/Overview/chat.
- **Labs #348:** first R09 contract is original PDF/image → extraction candidates → explicit Owner confirmation → revisioned results with original labels, values/qualifiers, units, report ranges and sample/report dates. Not a diagnosis, automatic acceptance or the whole medication roadmap.

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
- Only evidenced `tennis_v2` renders as Теннис; codes/formulas stay unchanged. #319 owns new calorie/max-HR/dual-effect evidence and units; requested cards do not prove availability.
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
- New routine Context capture needs explicit durable-profile rollout; UAT comments do not automatically become Stable history.

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
- #305 diagnostics/import presentation is integrated. Its old 15-second timeout was real; newer clone endpoint and human screen returned results. That proves request progress, not recovered collection or full Data acceptance.
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
- #294 first portal adapter and #341 selected evidence export are now prioritized. Preserve one Context system and packet/revision/source identity; original content is untrusted data.
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
- #319 fields/units/coverage before new metrics; #340 surface-eligibility review before RHR display repair.
- Current provider health and weekly HRV upstream cause remain unproven by the clone report. #98 maintenance is complete.

### Google Health / R04

- Long-elapsed OAuth durability and late-correction frequency remain observational.
- Device attribution is record/surface-specific; family membership is insufficient.
- Pre-July Owner history was not established by the prior audit; no speculative broad backfill.
- Disabled sample-HR history is incomplete by Owner choice, not a provider limitation.
- #342 must distinguish source absence, dates/filters/eligibility, missing pairs and copied failures, and verify Google vendor-score support without renaming sleep efficiency.

### R05 / agreement

- Device-pair evidence remains insufficient for #105; account observations remain noncanonical.
- Firmware/app/algorithm change points may need separate epochs.
- #317 is integrated; its existence does not meet the new #343 two-source history experience or prove real Google coverage. Both source series can be shown without changing pairing/statistics/canonical rules.

### Operations / durability / CI / Owner UAT

- #214 one automatic run, #215 first Context adoption, #148 practical recovery and #256 filesystem/janitor are complete foundations, not current service guarantees.
- #181/#243 lifecycle/transcript and #251/#246 CI maintenance are complete. #126 enforcement remains separate.
- Current human #330 UAT is PARTIAL. Keep positive design/Weight/Activity findings and unresolved per-screen data/performance requirements; do not describe it as unperformed or overall PASS.
- Latest controlled activation is a verified real-data clone. No new code deployment/provider recovery/backup is performed by documentation work. Permanent Context rollout and actual direct chat connection remain future gates.

## Deferred owner choices

1. #126 protection/capability: no implicit purchase/settings change.
2. R07 email/scheduled transport remains unselected.
3. #341 direct read connection needs actual capability/auth/revocation/host setup; export is first useful transport, not a blocker on connection choice.
4. Recovery Score only for an evidenced unmet need.
5. Full remote portal exposure remains out of scope; bounded read tools are separately authorized.
6. A+ style is decided. Implement the new #343–#348 functionality in bounded stages after P1 data, Context and evidence export; no new global redesign or lost shared-file ownership.
7. #167 history rewrite requires a new Owner decision/freeze.
8. #228 cross-image merge requires trustworthy event proof.

## Change protocol

Architecture-invariant changes cite primary evidence, affected releases/migrations
and the owning contract/ADR. A donor README, method name or plausible model answer
is not enough. Owner product priorities/layout can change by explicit decision;
that never silently changes source/health semantics or grants runtime access.
