# Decisions and Open Questions

This file contains current architecture/product decisions plus only those `UNVERIFIED` items that still matter after released R01–R05 evidence. Historical decision archaeology remains in release issues, audits and Git history.

Current status refresh: 2026-10-01, accepted product checkpoint `ac1df6dd5bdcfdc57c56a9b531e89a108a658d2b`, exact-main CI `36818997839` SUCCESS. Re-read live GitHub state before an assignment; see [current backlog](ROADMAP.md#current-backlog--2026-10-01).

## Final decisions

### Product and release sequence

- Health-Check is a single-user personal health observatory on a Windows laptop.
- Dashboard and AI are equal product interfaces over one deterministic evidence layer.
- Priority remains weight/body composition → sleep → activity/fitness → recovery/wellbeing.
- R01, R02, R03, R04 and R05 are released to canonical `main`.
- R05 closed with exploratory sleep agreement; Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.
- #119 deterministic Period Brief, its correctness/presentation/UAT closeout, durable Runtime foundation, Context v0, Garmin Training/Recovery and source freshness are completed and canonical.
- Owner screenshot workflow #217/#219/#221, Windows CLI fix #203, screenshot algorithm guard #226, coherent reads #227, Garmin Training privacy-oracle fix #233, Windows cleanup/CI reliability #181 and changed-sidecar correction workflow #229 are also complete.
- Near-term work is the non-UI technical maintenance track: #246 Stage A CI fast path, then separately selected #243/#242/#244 work according to overlap/priority. #247/#248/#240 remain bounded follow-ups; #228/#153 stay parked/optional; UI remains deferred under #172/#189.
- A custom Health-Check Recovery Score remains deferred until accumulated evidence demonstrates a concrete unmet decision need.

### Runtime

- Python 3.12+, FastAPI, SQLite WAL, SQLAlchemy/Alembic, Windows-first local operation.
- One local codebase/database; loopback dashboard/read/import listener plus optional separate ingest-only listener/process.
- Long sync/report jobs are explicit idempotent CLI/application-service operations suitable for Windows Task Scheduler.
- Runtime data/artifacts/secrets live outside Git under a user-scoped data directory.
- No Redis/Celery/Kafka/Postgres/Kubernetes/multi-tenancy without demonstrated need.

### Data and provenance

- Raw evidence, typed source data, current/canonical selection, derived analytics and LLM narrative are separate layers.
- Preserve competing source values and historical revisions.
- Canonical rules and derived algorithms are versioned/reproducible.
- Physical device, provider/input method and measurement algorithm are separate identities.
- Missing/null/zero/unavailable/unknown are distinct and never collapsed silently.
- Provider/query family context is not physical-device identity.

### Xiaomi S400 / R01

- Accepted routine Owner Weight path: Xiaomi Home/S400 screenshot -> repo `health-weight-screenshot-import` skill -> Owner-assisted strict structured extraction -> existing R01 photo pipeline -> Stable.
- #217/#219/#221 Owner-live proof covers OLD and NEW imports, exact NEW duplicate replay, two new sessions and unchanged historical evidence. It does not prove every possible cross-image/revision case.
- openScale/openScale-sync remain external GPL applications and an optional alternative path. #153's observed numeric `userId` compatibility defect is not a prerequisite for screenshot Weight accumulation.
- Xiaomi-app and openScale composition remain distinct compatibility groups until paired evidence supports an accepted versioned calibration.
- #226 pins the accepted Xiaomi screenshot algorithm identities before auto-confirm. Foreign explicit code, incompatible group or conflicting existing producer/metric-family metadata returns `NEEDS_REVIEW` before session/measurement/canonical writes. Omitted permitted versions stay unknown; no historical repair was performed.
- Model confidence is not a substitute for accepted confirmation policy. Ambiguous evidence is never silently auto-confirmed.
- #229's changed-sidecar correction staging is an unmerged candidate at this checkpoint. No claim that corrected sidecars are already reviewable in released main.
- #228 Phase 1 is accepted: artifact bytes and semantic source-event identity are distinct. Current photo extraction lacks a trustworthy cross-artifact event ID. No fuzzy/date/value/timestamp-based auto-dedup, no midnight inference and no automatic rewriting of history are authorized. Research acceptance does not retrofit review detection into existing code.

### Garmin / R02–R03

- Garmin uses the pinned `python-garminconnect` dependency; no second Garmin HTTP client.
- Protected owner-assisted auth/session state remains outside Git.
- Only reviewed read/download semantics are permitted; method existence never proves Vivoactive 5 capability.
- Garmin ingestion preserves raw/observation/current provenance, explicit coverage and separated incremental/historical checkpoints.
- Current collection reconciliation is deterministic under accepted authoritative/partial semantics; parser/reconciliation upgrades are explicit and version-aware.
- R03 analytics consume reviewed metric/time identities and immutable evidence manifests; UI does not reimplement statistics.
- Garmin-native scores remain provider-native and are not relabelled as a Health-Check readiness/recovery score.
- Accepted Training evidence includes Training Status, daily/chronic load, ACWR, Load Focus, Training Readiness/Recovery and activity Training Effect/load; requested acquisition date remains distinct from provider source date/timestamp.
- Associated-device/activity-recorder evidence is not metric-producer proof. Recovery Time units remain unavailable until the persisted contract proves a unit.
- Normal Owner refresh includes bounded Training sync using the same Garmin auth/client.

Post-R04 maintenance #98 completed `python-garminconnect` 0.3.12 -> 0.3.15. It was maintenance, not an R04/R05 semantic dependency. #99 Google auth/sync test hardening is also complete.

### Google Health / R04

R04 is released. Accepted contract:

- Google Health API v4 only; no new legacy Fitbit Web API implementation.
- OAuth uses a Web Application / Web Server client with a fixed exactly registered loopback callback.
- Client secret/token/session material stays outside Git in the external Owner runtime with Windows user-scoped DPAPI protection.
- Exactly two accepted read scopes: sleep and health metrics/measurements.
- Owner Google Auth Platform In-production/External status, fresh protected consent and immediate session reuse were proven.
- `list`, `reconcile`, `rollUp`, `dailyRollUp` and `dataSourceFamily` are acquisition/query context, not stable source identity.
- `google-wearables` is not automatic Fitbit-device proof; explicit persisted metadata is required for a physical-device claim.
- Raw/list metadata stays separate from family aggregate/reconciled/rollup results.
- Accepted types include sleep, heart rate, HRV/daily HRV, daily resting HR, SpO2/daily SpO2, respiratory-rate sleep summary and daily respiratory rate.
- Pagination follows `nextPageToken`; bounded sleep page size; inclusive-lower/exclusive-upper windows; undocumented list ordering is never assumed.
- Historical/incremental/refresh namespaces are distinct.
- Exact completed historical/incremental windows may skip provider work when coverage proves completion; explicit bounded refresh intentionally re-fetches to discover corrections.
- Missing/null/zero/confirmed-empty remain distinct; unknown shapes fail closed.

#### Owner collection selection — 2026-09-29

The Owner chose high-frequency Google `heart_rate` OFF in the local Ops runner; Garmin remains the primary high-frequency HR source. The local flag allows explicit re-enabling. This does not delete retained history, change repository CLI defaults, alter provider correction semantics, disable Google HRV/daily resting HR, or disable fixed wearables-sleep reconciliation.

The previously identified historical sample-HR gap is not a Phase C backfill target while the stream is intentionally disabled. Record it as intentionally uncollected, not complete or provider-empty. Re-enabling is not automatic historical catch-up; a bounded window/coverage decision is still required. Freshness must remain honest rather than fabricating healthy state for skipped data.

#### Live terminal-envelope decision from #110

Live Owner evidence proved a terminal HTTP-200 LIST object omitting both `dataPoints` and `nextPageToken`.

The repair remains narrow:

- LIST/RECONCILE + missing collection + no usable token -> complete empty terminal page;
- missing collection + usable token continues pagination;
- arrays follow normal complete/continue rules;
- null, object, string, number, boolean or other malformed collection shapes stay invalid;
- rollup shapes are not broadened.

The repaired window completed and exact rerun made zero provider calls.

### R05 agreement / canonical sleep

Frozen design from #97:

- sleep is paired by local wake date;
- one main overnight session per source/date; naps excluded;
- ambiguous multiple-main sessions fail closed;
- `device_pair` requires explicit persisted physical/provider metadata;
- `family_pair` from `google_wearables_family` is exploratory only;
- manual Google-edited evidence is excluded from the strong 42-night gate;
- comparable sleep metrics are projected separately; provider scores are display-only, not equivalent measurements;
- difference convention: `google - garmin`;
- statistics: N, bias, MAE, RMSE, Bland–Altman limits and robust summaries; association is secondary;
- exploratory gate: 14 paired nights;
- provisional canonical decision: 42 valid device-pair nights across at least six weeks plus coverage/stability checks;
- Garmin stays canonical until a reviewed versioned per-metric rule changes it;
- no automatic switch from N/correlation/coverage;
- R05 may close without a canonical change when evidence is insufficient.

### Period Brief / post-R05

- #119 is the deterministic packet contract for bounded cross-domain review.
- Weight/sleep/activity/data-quality facts retain coverage/unavailable states and stable result identity.
- UI/text/CLI are thin renderers; no formula/count/hash changes through display thinning.
- Direct R05 sleep-report reuse is preferred to copying agreement semantics.
- #146/#133/#129/#127 correctness/presentation/UAT closeout is complete. #172 and #189 own later UX work.
- #203 changes limited-encoding stdout only; UTF-8 packets and analytics remain unchanged.

#### Compound read consistency — #227 accepted

Weight and Period Brief compound reads establish one physical SQLite snapshot, including the import queue and freshness components they assemble. Clean ORM objects from before BEGIN or a prior Session transaction must align with that snapshot; `expire_on_commit=False` alone is not a coherence guarantee.

The accepted local helper preserves caller-owned commit/rollback/close, rejects pending new/dirty/deleted state before cache actions, retains flushed writes, and expires clean cached ORM state on both new and reused physical transactions. It does not globally change engine, writer, migration or provider semantics. The first candidate missed pre-BEGIN cached entities; independent review required the regression and remediation before PR #231 integration.

### Stable Owner Runtime / owner operations

- Private durable profile: `D:\HealthCheck\stable`; clean Owner/control checkout: `D:\HealthCheck\main`; Owner Ops: `D:\HealthCheck\ops`.
- Stable is the long-lived accumulation point, never reset for release UAT. Use verified backup/restore clones.
- No direct SQLite grafting between historical profiles.
- Supported bounded large-profile backup/verify/restore retains checksum/integrity/atomic-restore protections; a prior verified local archive is not an off-site disaster-recovery proof.
- Dense Google HR remains civil-day partitioned with resumable fail-closed staging and bounded transient retries where selected.
- Google instant/HR-interval identity is path-free; query mode/family remain acquisition context. Legacy retirement preserves raw observations/artifacts.
- Provider operations and explicit cutoff-bounded stale-run recovery share the external-runtime lock; no fabricated success or checkpoint reset.
- Historical #132 closeout proved no stale running SyncRun rows/current instant duplicate groups at that time. Later interruptions need their own honest assessment.
- Owner operation checkout and local Ops runner are separate from GitHub main and from Worker workspaces. No automatic deployment is implied by merge.

#### Owner refresh / collection-policy operational status

#214 automatic collection proof is complete: the accepted Owner-reported automatic/logon run finished with Scheduler result 0 and all selected Garmin / Garmin Training / Google normal / wearables-sleep layers succeeded. The observed run time is evidence for that run, not a future duration guarantee.

#238 is also complete. Durable collection intent is explicit and reversible: intentionally disabled Google high-frequency HR is non-actionable for collection without being relabelled fresh/provider-empty, while real age/history remains preserved. Re-enabling does not authorize broad backfill. Shared freshness consumers use the accepted policy rather than inferring durable intent from a one-off omitted stream.

`Health-Check owner refresh` remains the normal bounded Scheduler workflow. The project does not claim guaranteed resume-from-sleep, exact once-per-day semantics or perpetual provider availability from one successful run.

### Source freshness / data quality

- #147/#191/#193 are complete, provider-call-free and reused by Owner refresh/Period Brief.
- State vocabulary: `fresh | quiet | stale | unavailable | unknown | not_requested`.
- Attempt/success, evidence time, coverage/checkpoints and configuration/request state remain distinct facts.
- Daily streams use versioned due/grace policy; activities use proven inventory; voluntary Weight is non-alert by default.
- Unknown/insufficient chronology never becomes healthy; optional/unsupported metrics do not fail an otherwise healthy provider.
- #238 completes the policy alignment: explicit disabled collection remains historically truthful and non-actionable without being relabelled fresh; enabled/unknown/unavailable failures remain visible.

### Time, coverage and agreement

- Store valid UTC plus original local time/offset/zone when available; preserve date-only/local-only precision.
- Sleep belongs to local wake date; lag direction is explicit.
- Coverage accompanies non-trivial analytic/report results.
- Associations are exploratory, never causal/medical claims.

### CI, verification and repository integration

#123–#125 are accepted and integrated. Durable rules:

- targeted iteration, frozen exact candidate gate, exact integration gate and exact post-main gate;
- final `checks` fails closed on incomplete/malformed/cross-run evidence, mandatory failure/skip/cancel or inventory/provenance mismatch;
- Linux exact nodeids/multiplicity reconcile across the manifest and three serial lanes;
- Windows actually executes required DPAPI and real startup/HTTP/cleanup scenarios;
- no skipped platform proof or green subset is substituted for the final gate;
- no full Windows matrix, xdist/cache or micro-tuning without a material measured need.

#181 is complete for its accepted Windows ownership/lifecycle and same-attempt evidence contract. #251 later rebalanced the three serial Linux lanes without changing their exact complete union. #246 is the current staged CI-efficiency track (docs-only PR fast path first, event dedup separately); #243 remains the narrow post-#181 blank-transcript recurrence investigation. Green later runs never erase retained failed evidence.

#### Repository protection / #126

- Visibility is currently public; private-data boundaries remain unchanged.
- #126 remains an Owner/capability decision; re-evaluate actual visibility/plan before settings changes.
- Require exact-SHA final `checks: SUCCESS` regardless of server enforcement.
- No force-push/deletion of canonical/integration history.
- #167 historical metadata rewrite is deferred by Owner decision. No rewrite, visibility change or privacy-safe-public claim is authorized here.

### AI / reports / context

- LLM access is typed, bounded and read-only through analytics services, not unrestricted SQL.
- Reports are deterministic/versioned before rendering/delivery.
- Context v0 preserves revisioned Owner-authored text and optional tags; no mandatory diary.
- #215 completed the first real private Stable adoption; Context Capture v0 is an accepted manual evidence source. Later adapters must not invent dates/tags/interpretations.

### Model attribution — Owner clarification 2026-09-29

Explicit Owner confirmation of the model actually used is valid alongside runtime-reported evidence. Preserve raw client unknown fields, label the journal attribution Owner-confirmed, and use exactly the supplied model label without unreported version expansion. Keep routine Model evidence to only model and provider/client. This records attribution; it never relaxes code/CI/independent-review gates. See [Model Journal](MODEL_BENCHMARK.md).

### License

- Health-Check is MIT; python-garminconnect is an MIT dependency.
- External GPL/AGPL projects stay external/reference-only unless obligations are accepted.
- Donor reuse is reviewed and pinned to exact versions.

## Remaining UNVERIFIED / open observations

### Xiaomi / R01

- #153 optional numeric-userId compatibility and real openScale measurement E2E remain open.
- Historical algorithm/application version may remain unknown where evidence is insufficient; no cross-algorithm calibration without paired evidence.
- #229 correction candidate awaits independent review/integration; #228 cross-image event identity remains parked, not implemented.

### Garmin / R02–R03

- MFA-specific future behavior, longer-term shape drift and retention beyond released proof.
- Recovery Time unit/producer attribution and VO2/dedicated max-metrics outside accepted evidence stay unverified.
- #98 dependency upgrade is complete, not residual backlog.

### Google Health / R04

- Long-elapsed OAuth token durability remains observational.
- Late-correction frequency/policy is not assumed.
- Physical-device attribution is record/surface-specific; family membership is not sufficient.
- Pre-July Owner history was not established by the local audit; no speculative provider-wide backfill.
- Disabled sample-HR history remains incomplete by Owner choice, not a provider limitation or complete coverage claim.

### R05 / agreement

- Device-pair evidence remains insufficient for #105; Garmin stays default.
- Strict legacy cohorts remain fail-closed; the uncertain account cohort is never canonical-eligible.
- Future firmware/app/algorithm change points may require separate epochs.

### Operations / durability / CI

- #214 automatic selected-stream collection proof is complete.
- #215 first real private Context note/read-back is complete.
- #148 practical off-site recovery is complete; the accepted Owner workflow is an ordinary verified ZIP in the materialized Google Drive folder plus supported clean restore. Optional protected age publication is not required.
- #181 accepted Windows ownership/lifecycle and full-rerun-only evidence contract is complete; #243 separately tracks the narrow blank transcript recurrence.
- #251 CI lane balancing is complete; #246 owns the next CI-efficiency stages.
- #256 Owner filesystem migration and automatic workspace cleanup are complete. Canonical roots are under `D:\HealthCheck`; janitor runs daily at 12:00 with seven-day minimum retention and does not touch legacy roots.
- #126 server-side enforcement still requires an Owner/capability decision before settings changes.

## Deferred owner choices

1. #126 protection/capability: no implicit plan purchase or settings change.
2. Email transport: choose in R07.
3. External AI provider/deployment: choose when that release begins.
4. Recovery Score: only for an evidenced unmet need.
5. Remote access: local/loopback until an explicit need/threat model.
6. #172/#189 UI: deferred while operational readiness/durability take priority; #153 is not a prerequisite.
7. #167 privacy rewrite: deferred; requires a new Owner decision and coordinated freeze.
8. #228 cross-image identity: no automatic semantic merge until a trustworthy event-proof contract is accepted.

## Change protocol

Any change to an architecture invariant must cite new primary evidence, identify affected releases/migrations and update the owning contract/ADR. A donor README, method name or plausible model answer is not sufficient evidence.
