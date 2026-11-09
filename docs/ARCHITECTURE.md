# Architecture and Data Contracts

This book describes current data, runtime, calculation and access contracts.
[Product Vision](PRODUCT_VISION.md) owns purpose; [Development](DEVELOPMENT_PROCESS.md) owns
delivery/verification; [Owner Operations](OWNER_OPERATIONS.md) owns procedures;
[Project Wiki](PROJECT_WIKI.md) is dated status. Release-numbered versions remain meaningful wherever
code still reads them.

## Contents

- [3.1 Core invariants and value states](#core-invariants)
- [3.2 System, runtime and access boundaries](#runtime)
- [3.3 Evidence model, originals and revisions](#evidence-model)
- [3.4 Time, coverage and consistent reads](#time-and-coverage)
- [3.5 Acquisition, synchronization and reprocessing](#acquisition)
- [3.6 Source identity, eligibility and selection](#source-selection)
- [3.7 Weight, body composition and image intake](#weight)
- [3.8 Garmin records, capability and native metrics](#garmin)
- [3.9 Google records and acquisition contracts](#google)
- [3.10 Sleep eligibility, quality and agreement](#sleep)
- [3.11 Steps: observed, completed and all-time](#steps)
- [3.12 Deterministic analytics and saved-data analyses](#analytics)
- [3.13 Context and laboratory documents](#context-and-labs)
- [3.14 UI, routes and presentation](#presentation)
- [3.15 Evidence packets, reports and AI access](#evidence-and-ai)

<a id="core-invariants"></a>
## 3.1 Core invariants and value states

Preserve original evidence, competing values and revisions. Physical device, provider/input application
and measurement algorithm are distinct identities. Canonical selection references eligible evidence
without erasing alternatives. Parsers, rules and derived algorithms are versioned; equal inputs/rules
produce reproducible ordered results and hashes.

Every result identifies source, observation date or actual window, unit and coverage. Provider-native
scores and Health-Check-derived metrics have distinct names. Consumer BIA, wearable associations and
assistant interpretation establish neither diagnosis nor causation. No universal Health-Check Recovery
Score is implemented; a new score requires a separate validated contract.

| Leaf state | Meaning |
| --- | --- |
| `missing` | Owning source field is absent. |
| `null` | Explicit JSON null. |
| `value` | Supported value, including genuine permissible zero. |
| `invalid` | Unsupported type, shape, unit or field-specific value. |

Availability (`unavailable`, `unknown`, `confirmed_empty`, `failed`, `partial`, `not_requested`)
describes another layer, never replacement zero. `confirmed_empty` requires successful semantically
complete acquisition. Request loading/error and explicit no-change comparison are separate states.
Quality labels do not replace counts/exclusions.

One deterministic Python layer serves UI, reports and AI. Framework objects do not enter pure
calculations. An LLM explains evidence rather than calculating raw time series. Read capability never
implies sync/import/confirmation/admin access. Original comments/documents are untrusted data, not tool
instructions.

<a id="runtime"></a>
## 3.2 System, runtime and access boundaries

Windows-first runtime: Python 3.12+, FastAPI/Uvicorn, SQLAlchemy/Alembic, SQLite WAL. Routes call
services, repositories transact, pure analytics consumes typed input. One codebase/database supports CLI
acquisition and dashboard. No required Redis/Celery/Kafka/Postgres/container or multi-tenant
infrastructure.

```text
provider / image / document / optional openScale webhook
  -> immutable artifacts and acquisition observations
  -> provider-specific typed current records
  -> canonical references and deterministic analytics
  -> dashboard / frozen evidence / configured read adapters
```

Runtime data/artifacts/logs/secrets live outside Git/checkout. `%LOCALAPPDATA%\Health-Check` is the
generic default; actual roles belong in [machine layout](OWNER_OPERATIONS.md#machine-layout). Startup
can create/migrate its selected profile and is not a read-only diagnostic. Code updates do not refresh
restored copies. Copied real data remains real, excluded from fixtures/CI.

UI/read/import defaults to `127.0.0.1` with Host/Origin protections. A separate ingest-only app exposes
`GET /healthz` and authenticated `POST /api/ingest/openscale`, without product/read/admin routes.
Independent port/credential/transport policy applies. HTTPS/encrypted overlay is preferred; plaintext
trusted-LAN ingest requires explicit opt-in/confidentiality warning. Public exposure is unsupported.

<a id="home-server"></a>
### Optional single-owner home server

`ui_mode=home-server` mounts the same services behind direct Uvicorn TLS/global authentication. Bind is
one explicit RFC1918 IPv4; `127.0.0.1` is also allowed for verification.
Wildcard/public/hostname/link-local/overlay binds are rejected. Externally supplied certificate/key must
be currently valid and match the IP. Client trust is an operator gate; proxy-header trust/access logs
are disabled.

Interactive passphrase setup stores a salted scrypt verifier: N=131072, r=8, p=1, 16-byte salt.
Verifier/TLS files are outside checkout and profile; profile backup does not transfer browser access. No
automatic credentials or password argument/environment input exists.

Only exact `/login` and nonsensitive `/healthz` are public. Authentication precedes
pages/APIs/exports/documents/errors/static files. Login rejects queries/return URLs. Unsafe methods
including login/logout require exact HTTPS Origin; Referer/Fetch Metadata, when present, must be
same-origin. Duplicate authority, Origin/session-cookie ambiguity is rejected. Loopback exceptions do
not apply.

Login replaces the cookie with a fresh 256-bit opaque token; the bounded 16-session process store
retains SHA256 keys/timestamps. Cookie: `__Host-healthcheck`, Secure, HttpOnly, SameSite=Strict, Path=/,
no Domain. Idle expiry 30 minutes; absolute expiry 12 hours. POST logout/restart revoke sessions.
Verifier replacement/unreadability fails closed until restart. Five login attempts/minute precede KDF;
form cap 4096 bytes, arrival deadline ten seconds. Responses are no-store with framing/referrer
protection. Passwords/cookies/bodies/URLs are not application log fields. This code does not establish
an installed home-server setup.

Read, ingest, Context/import write and admin are distinct capabilities. OS/user controls protect local
files. MIT core retains donor attribution/license obligations. openScale/openScale-sync are external GPL
programs connected through data contracts; AGPL VitaSync and unlicensed `garmin_ai` are reference-only.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `healthcheck-offsite-v1` | Offsite backup | Versioned encrypted envelope | [Operations](OWNER_OPERATIONS.md) owns backup/recovery; not read access. |
| `multidomain-synthetic-v2` | Fixed demo seed | Synthetic reset certificate | Never authorizes real-profile reset. |
| `r01-six-month-synthetic-v1` | Legacy demo | Recognized seed identity | Strict reset allowlist. |
| `synthetic-demo-v1` | Demo extractor | Invented deterministic extraction | No real provider evidence. |

<a id="evidence-model"></a>
## 3.3 Evidence model, originals and revisions

Generic spine: `providers`, `physical_devices`, `acquisition_sources`, `measurement_algorithms`,
`raw_artifacts`, `ingest_batches`, `ingest_events`, `sync_runs`, `sync_stream_state`,
`coverage_intervals`. Algorithm identity belongs to each measurement, not merely its session.
Unattributed account data never acquires a physical device by inference.

| Layer | Identity and responsibility |
| --- | --- |
| Original | Immutable content-addressed bytes, SHA-256, size, media type and safe relative reference; filenames are metadata. |
| Acquisition | Source/window/run receipt with independent chronology even for repeated bytes; exact retries converge. |
| Typed evidence | Separate scalar/session, sleep/stage, activity/intraday, Context and lab entities, not universal EAV. |
| Current projection | Provider-specific revision/recency interpretation, not immutable history or automatically canonical. |
| Canonical selection | Versioned references retaining losing evidence. |
| Derived/frozen output | Input IDs/content hashes, rule/algorithm, time and frozen selected values; corrections do not rewrite it. |

Garmin originals use `garmin_raw_payloads`/shared artifacts under
`artifacts/payloads/<aa>/<sha256>.<ext>`. Immutable `garmin_payload_observations` retain
event/run/window/received time/filename/interpretation/diagnostics. `garmin_source_records` parents have
daily/sleep/activity/intraday/FIT children, `garmin_record_metrics` and `garmin_sleep_stage_intervals`.
ORIGINAL FIT retains raw evidence with a typed marker.

Google has dedicated `google_sources`, `google_raw_payloads`, `google_payload_observations`,
normalization attempts, source records and typed children/metrics. Artifacts use
`artifacts/google/payloads/<aa>/<sha256>.<ext>`. It reuses the generic spine, never Garmin tables. Query
context and device evidence remain separate.

Photo confirmation uses `measurement_sessions`/`scalar_measurements`; corrections supersede, never
erase. Derived measurements record input IDs/hash. Canonical rules store serialized rule/hash. Runs
retain scope, rule/input-revision hash, build, times, status/counts/sanitized failure; selections
require a run. Successful `(scope, rule_hash, input_snapshot_hash)` replay converges. Changed
inputs/rules create a new run; failed runs cannot become active.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `r02-garmin-persistence-contract-v1` | Garmin repository | Original/observation/current spine | Caller-owned transaction; no acquisition. |
| `garmin-observation-v1` | Observation key | Source/run/window/interpretation | Hash alone is not acquisition identity. |
| `r04-google-persistence-contract-v1` | Google repository | Dedicated evidence spine | No context pooling. |
| `r04-google-persistence-shell-v2` | Typed shell | Shell interpretation | Not full normalization. |
| `google-observation-v1` | Acquisition key | Query provenance | Replay cannot advance chronology. |
| `google-normalization-attempt-v1` | Attempt key | Original interpretation | Separate from fetch success. |
| `google-record-v1` | Legacy current key | Context/path identity | Compatibility retained. |
| `google-record-v2` | Current key | Path-free instant/interval scope | Not device identity. |
| `google-instant-sample-v1` | Samples | Source/stream/context/UTC instant | No response-position identity. |
| `google-no-instant-identity-v1` | Unidentified evidence | Missing instant identity | No invented chronology. |
| `google-hr-interval-v1` | HR rollups | Path-free interval identity | Distinct from samples. |
| `google-unidentified-sleep-occurrence-v1` | Id-less sleep | Occurrence fingerprint | Not external session proof. |
| `google-sleep-logical-session-v1` | Sleep revisions | Logical grouping | Acquisitions stay separate. |
| `google-steps-unidentified-v1` | Invalid Steps | Audit identity | No valid projection without endpoints. |

<a id="time-and-coverage"></a>
## 3.4 Time, coverage and consistent reads

Date-only stays civil date/null UTC. Local-only naive time has no invented zone. UTC instant, original
local timestamp, numeric offset, IANA zone and field paths retain separate roles. Explicit GMT/UTC
fields establish UTC by semantics; paired Local fields preserve wall time. Garmin offsets accept
-1439..1439 minutes (-23:59 through +23:59). Conflicts give diagnostics, not clock repair.

Sleep aligns to local **wake date**; activity to persisted `source_local_date`.
Receipt/filename/requested day/UTC date cannot supply missing source date. `lag 0` means same analytic
date; `lag +1` pairs next date; direction is explicit. Travel policy does not rewrite saved clocks.

### Owner calendar and completed days

`Settings.owner_timezone` is a `ZoneInfo`-validated IANA zone, default `Europe/Moscow`, env
`HEALTHCHECK_OWNER_TIMEZONE`. `owner_time.owner_now/owner_today` convert current UTC; host/browser zones
do not choose Owner today. This includes initial editable Context date. Explicit Context “Сейчас” still
proposes browser-local clock/zone for review.

Owner calendar does not reinterpret saved dates, fixed analysis/completion policies, Weekly Digest
schedule or Google Steps catch-up cursor binding. Completed Garmin Steps and Overview
Sleep/Steps/Stress/Body Battery use explicit `Europe/Moscow`: rolling windows end yesterday retaining
day count; custom Overview retains start and caps end at yesterday. Empty intersection yields no number.
Weight/Activity retain requested windows. This is not provider finality.

Overview Sleep/Stress use one eligible daily value per source date, never intraday averaging to resolve
collisions. Means weight eligible days equally; missing days are excluded, valid zero participates.
Incomplete reads withhold means. Sleep/Stress retain 400-day/2000-point bounds; Garmin Steps 1–366 days;
Google Steps exact 7/30. Unsupported spans stay unavailable without clipping. Selected-day Stress
baseline is separate.

### Coverage, freshness and physical snapshots

Acquisition completeness, usable dates, wear coverage, local-search completeness, refresh success,
evidence age and restored-copy age are distinct. Watermark is not contiguous history. Return
requested/actual bounds, observed/expected counts where meaningful, gaps/freshness, source/algorithm
breakdown, exclusions/versions. Sparse Weight cadence defaults to seven days, not daily expectation.

Atomic coverage precedence: evidence gives `present`; otherwise capability block gives `unavailable`;
complete successful empty fetch gives `confirmed_empty`; required failed attempt without later success
gives `failed`; otherwise `unknown`. Contradictions remain visible to domain readers.

`source-freshness-v1`: `fresh | quiet | stale | unavailable | unknown | not_requested`. Daily cadence
24h, due 36h, grace 72h, refresh overdue 48h; activity inventory seven civil days/refresh overdue 48h.
Voluntary Weight is non-alert by default. Required/optional scopes differ; unavailable optional metrics
do not alone fail provider health. Unresolved/future chronology is not fresh; read success is not
recovery.

Compound reads pin one physical SQLite transaction including queue/freshness.
Pre-BEGIN/prior-transaction ORM caches must align: reject pending new/dirty/ deleted state before cache
actions, retain flushed writes, expire clean caches for new/reused physical transactions, preserve
caller transaction/close. `expire_on_commit=False` is insufficient alone. Export guards:
[3.15](#evidence-and-ai).

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `coverage-v1` | Weight | Cadence bins/counts/states | Not imputation. |
| `garmin-coverage-v1` | Garmin repository | Shared coverage/sync facts | Static capability is not availability. |
| `source-freshness-v1` | Diagnostics | Scoped chronology | No provider call/recovery. |

<a id="acquisition"></a>
## 3.5 Acquisition, synchronization and reprocessing

Raw transport is stored before/atomically with normalization. Stable identity converges retries; receive
order never defines event order. Failures retain replayable evidence/sanitized codes. Only complete
authoritative collections retire absences; partial/unknown/failed/truncated reads preserve prior
members. Complete empty can retire all; retired rows/originals/observations remain.

Garmin `garmin:v1:record:<sha256>` binds source/stream/stable ID. Semantic fallback binds
source/stream/time/sorted present non-null typed metrics, including zero, excluding receive
time/order/unknown fields. Identical id-less events may stay indistinguishable. Production
`garmin:v1:reconcile:` binds source/stream/surface/ time/sample token; provider token precedes array
index. Index-only identity retains reorder ambiguity. Changed timestamp creates new identity; complete
authority may retire old identity.

Newer observation `received_at` updates current state; older replay cannot roll back/insert
vanished/un-retire members. Ordinary sync/backfill uses whole-collection stale guard; per-row handling
is reserved for offline overlapping replay. Singleton/intraday need complete day response; activities
require all pages plus terminal short/empty page. Full last page/budget stop stays partial/unknown
without successful checkpoint. Resume refetches page zero.

Historical/incremental/refresh namespaces are separate. Ordinary backfill skips present/confirmed-empty;
`--reprocess` refetches version-stale present, still skips confirmed-empty. Offline `garmin-reprocess`
reads originals without providers or historical/incremental checkpoint writes. Newest eligible windows
replay in receipt order; requested dates hard-bound effects; clipped/incomplete collections cannot
retire absences. Empty currentness uses versions, not invented rows.

| Entry | Exact bounds |
| --- | --- |
| Garmin incremental | Trailing default 7 days, maximum 14; 140 provider requests; activities page size 20, maximum 5 pages. |
| Garmin history | Chunk default 7 days, maximum 14; span 3660 days, 140 provider requests. |
| Garmin offline replay | Span 3660 days, 140 observations; HRV original 1 MiB, duplicate-key rejection. |
| Training sync | At most 14 Readiness days and one Status response requested at end date. |
| Google sync | 80 data requests, 40 pages/fetch, page size 500 (Sleep 25 records/page), 3 attempts/page; backoff 0.25/0.5/1.0 seconds; first-run lookback 1 day, HR rollup maximum 14 days/default window 60s. |
| Google history | Chunk default 7/maximum 14 days, span maximum 3660 days, 80 data requests. |

HRV replay uses verified `hrvSummary.calendarDate`, not window equality. Old v1/v2 undated singleton
retirement requires its own source/surface/version/ integrity/chronology to prove the same in-range day
as the dated replacement, atomically. Other days/clipped/unknown coverage remain intact. Resume cannot
let unrelated restored days/impossible legacy transitions starve newer evidence.

A profile operation lock spans supported sync/backfill/refresh/reprocess. Non-reentrant stale-SyncRun
recovery cutoff-terminalizes only provably orphaned running rows as failed, without deleting
evidence/resetting checkpoints/inferring success. Owner policy disables only `google:heart_rate` or
`google:steps`, JSON cap 64 KiB/nesting 32. Disabled is intentionally uncollected, not provider-empty.
Refresh Steps/catch-up are opt-in, separate from bare CLI defaults. Procedures:
[Operations](OWNER_OPERATIONS.md).

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `r02-garmin-incremental-sync-v1` | Sync | Trailing reconciliation | Not contiguous history. |
| `r02-garmin-historical-backfill-v1` | History | Resumable chunks | Separate namespace. |
| `r02-garmin-collection-reconciliation-v1` | Current collections | Identity/authority/recency | Partial cannot retire absences. |
| `r02-garmin-collection-reprocess-v1` | Offline replay | Version-aware updates | Explicit, never read-triggered. |
| `r04-google-sync-coverage-v1` | Google sync/refresh | Pagination/coverage/cursors | Context-specific completion. |
| `r04-google-historical-backfill-v1` | Google history | Resumable namespace | No assumed ordering. |
| `healthcheck-collection-policy-v1` | Owner policy | Explicit disabled scopes | Does not alter evidence. |
| `healthcheck-owner-refresh-v1` | Base refresh | Operation result | No optional Steps. |
| `healthcheck-owner-refresh-v2` | Steps refresh | Selected Steps result | Optional consent. |
| `healthcheck-owner-refresh-v3` | Catch-up refresh | Bound cursor/result | Not unlimited recovery. |
| `healthcheck-sync-run-recovery-v1` | Maintenance | Orphan/cutoff diagnostics | Not acquisition. |

<a id="source-selection"></a>
## 3.6 Source identity, eligibility and selection

Friendly Garmin/Google labels retain exact account/source/device/algorithm identity per metric/window.
Family is not device proof; overlapping observations are not additive. Display, numerical comparison and
canonical switching differ. Delta requires compatible definitions/units/windows/denominators. Garmin
remains canonical Sleep default under [3.10](#sleep).

`select_metric_source` chooses only after complete metric-specific search proves one eligible source.
Equal values/latest date/UUID/history length never break ties. Ambiguous-only sources compete; two
eligible sources conflict even on disjoint dates. Incomplete blocks selection/prefix mean. Exact
overrides bypass unrelated identities without fallback when empty. No pooling/persisted preference.

| Consumer | Search scope |
| --- | --- |
| Overview Google RHR | 32 sources, 400 days, 4096 records/source, 256/day; selected packet/rational mean reused. |
| Data latest RHR | Opt-in `google_auto_select=True`; 32 sources, 32 date groups, 256 candidates. |
| Data latest Sleep | 32 sources, 32 date groups, 256 candidates, 200/night; complete same-date groups. |
| Statistics Sleep | Five summary windows, shared metric source-cell decision. |
| Sleep evidence | Opt-in `google_auto_select`; combined `sleep_google_auto_select`; exact ID wins; 400/provider range cap remains. |

Latest search is not exhaustive older history. Newer exclusions, real date/age/ historical status stay
visible; explicit dates never fall back. Automatic requests keep exact requested ID null, disclose
resolved `source_identity`/`source_selection`. Conflict/incomplete/no-eligible Sleep gives
`source_range=null`, not omitted section.

Cycling discovery evaluates only `cycling_distance_meters` across exact Garmin sources in 7/30,
trailing365, YTD/calendar-year windows (maximum 366 days). Packet retains `contract_version`,
`reader_contract`, `evaluated_at`, `requested_window`, `metric`, `freshness`, `read_limits`,
providers/options/ eligibility/summary. `selection_policy=caller_owned_no_automatic_selection`; ID order
is enumeration only. Exact `cycling` counts, not `road_biking`; zero is eligible, duplicate-current
ambiguity conflicts.

Provider state precedence: `search_incomplete`, `ambiguous_records`, `multiple_eligible_sources`,
`unique_eligible_source`, `no_eligible_values`, `source_missing`. Incomplete suppresses all Garmin
options/counts (null, not zero). Statistics selects only the completed unique option without ambiguity;
explicit choice never falls back. Automatic return navigation preserves that mode, not provider-wide
override. Other metrics do not inherit this choice.

Google `not_collected`/`typed_activity_stream_not_collected` here is a cycling-reader limitation: counts
null, `options=[]`, `search.scope=persisted_stream_contract`. It does not describe the separate
implemented [exercise import](GOOGLE_EXERCISE_IMPORT.md).

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `sleep-window-selection-v1` | Sleep source choice | Complete eligible-source decision | Not global preference. |
| `cycling-distance-source-discovery-v1` | Cycling discovery | Exact-type reducer/provenance | No persisted choice. |

<a id="weight"></a>
## 3.7 Weight, body composition and image intake

Routine Xiaomi Home/S400 intake retains immutable image, extraction set, editable candidates and
confirmation separately. `ImageMeasurementExtractor` takes artifact reference/locale-zone hints/schema,
not arbitrary paths. Output retains extractor/ provider/model/prompt/schema, group, metric/source text,
proposed value/unit/time, nullable model confidence and optional region evidence. Invented constant
confidence is forbidden; failed extraction leaves replayable evidence.

Exact bytes deduplicate by hash; changed interpretations create candidate sets. Confirmation is
transactional/idempotent; rejection retains audit without measurements. Changed sidecars stage pending
corrections linked to original event even with reused extraction identity. Exact correction replay
converges; confirmed replay is `DUPLICATE`. Rejection leaves current/canonical state unchanged. Equal
date/value across images is not event proof; no fuzzy merge. Photo service accepts at most 100
files/batch, 10 MiB/image; storage names are generated.

### Auto-confirm and metadata origins

Owner adapter commits image/candidates first. Auto-confirm requires one image, one extraction set, one
plausible group, exactly one evidenced weight, no repeated/ unsupported metric, finite values/supported
units, consistent source date/precision, no warnings, all pending Xiaomi Home/S400/photo provenance and
accepted algorithm identity/group/producer. Conflicts give `NEEDS_REVIEW` without confirmation. New
extraction for handled bytes is never auto-confirmed; confidence is not policy.

Post-0015 `metadata_origins_json` has exactly `provider_code`, `physical_device_code`,
`source_application`, `source_local_date`, each in
`visible | owner_attested | workflow_profile | unknown`. Legacy NULL means unrecorded, without backfill.
Workflow defaults are not visual evidence. Date is never workflow-profiled: sidecar gives visible;
explicit current-request `--owner-attested-date` gives owner_attested; otherwise unknown. No clock/EXIF/
filename/prior-chat inference. Vision permits visible/unknown only. Terminal history is immutable. Equal
evidence/origins replay duplicates; unchanged legacy NULL uses read-time wildcard without rewrite;
changed origins stage identity-bearing `correction:` sets.

### Metrics and calculations

Weight is kg; BIA is algorithm-dependent. Xiaomi-app and openScale S400 composition are non-equivalent
without versioned calibration. Unknown app/formula/version does not mean equivalent. Weight can share a
series with proven device/unit/no calibration break. Identity belongs to each value; `muscle_mass` is
not `lean_mass`. `r01-canonical-v1` selects confirmed/non-superseded evidence, latest revision per
semantic weigh-in, composition only within explicit compatibility group. Derived inputs must remain
eligible with requested derivation version.

| Calculation | Exact method/gate |
| --- | --- |
| `weight_trend_taewma_v1` | Daily medians; first initializes; `alpha_i = 1 - 2^(-delta_days / 21)`; `trend_i = alpha_i * value_i + (1 - alpha_i) * trend_(i-1)`. |
| `weight_rate_theil_sen_90d_v1` | Median pairwise slope over trailing 90 calendar days, kg/week; at least 6 observations spanning at least 42 days. |
| `body_composition_decomposition_v1` | Same confirmed session/compatible inputs: `estimated_fat_mass_kg = weight_kg * body_fat_pct / 100`; `estimated_lean_mass_kg = weight_kg - estimated_fat_mass_kg`; both input IDs. |
| Similar weight | Same algorithm, at least 28 days apart, `abs(second.weight_kg-first.weight_kg)/first.weight_kg <= 0.01` (1%); compatible body-fat/fat-mass evidence on both sides, no classifier/causality. |

Coverage retains unique dates, cadence bins, oldest/latest/freshness/longest gap, source/algorithm
breakdown/states. Trend/slope gates are independent. No interpolated measurement date or manufactured
confidence interval.

### Optional openScale webhook

Compatibility target: openScale-sync `32e38651cf78bbf230e33d17abb00b147130f305`. Events
`insert | update | delete | clear | test`; item `id`, `userId`, `username`, `date`, convenience fields,
optional `values[]`; batch `measurements[]`. Values retain `key`, `name`, `unit`, `isDerived`, optional
numeric `value`/`text`. Authoritative `values[]` prevents missing convenience zeros becoming
measurements. Unknown fields stay raw.

Authorization is forwarded verbatim: narrow rotatable Bearer credential, distinct stable sender
`source_instance_id` UUID. Insert/update key `(source_instance_id, userId, id)`; delete fallback
`(source_instance_id, userId, measured_at)`; semantic fallback includes source/
user/time/metrics/algorithm/configuration, not hash alone. Rotation cannot fork identity. Malformed
envelope/auth returns non-2xx/no acknowledged batch. Mixed valid batches store raw once, process item
savepoints, durably retain valid and quarantined failures before 2xx. Lost-ACK retry converges.
Delete/clear retain tombstones/recompute canonical without deleting raw history.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `r01-canonical-v1` | Rule set, integer version 1 | Confirmed revision/group choice | No algorithm bridge. |
| `r01-photo-v1` | Extraction schema | Groups/candidates | Not confirmation. |
| `r01-xiaomi-s400-v1` | Vision prompt | Xiaomi instructions | No invented confidence/time. |
| `owner-weight-screenshot-import-v1` | Owner adapter | Sidecar/replay/confirmation | Review outside narrow gate. |
| `r01-openscale-contract-v1` | Webhook | Sender/item field semantics | External transport. |

<a id="garmin"></a>
## 3.8 Garmin records, capability and native metrics

Pinned `python-garminconnect` 0.3.15 uses reviewed 0.3.12 capability surface. Interactive sign-in/MFA
and Windows-current-user DPAPI/SID protect external `garmin_tokens.json`; no plaintext temp token file.
Protection failure is closed, malformed state reauth-required, outage failure. Method existence is not
device production. `GARMIN_CAPABILITY_INVENTORY` separates static support, Connect/client surface and
account/device proof.

Sleep/score/stages, HR/RHR/HRV, Stress/Body Battery/activities are reviewed supported;
naps/SpO2/respiration/cycling conditional. VO2/max and activity effect/load producer are unverified. VA5
Readiness unavailable, Status not-device-produced, Unified Status participant-only; Recovery Time
watch-only/FIT not evaluated by probe. Probe accepts one/two adjacent dates and at most one activity;
discovery `start=0, limit=1`; 27 provider requests maximum, retries disabled. Optional detail
`maxchart=1, maxpoly=0`; no GPS/polyline/ORIGINAL FIT. Reauth stops remaining calls. Reports/redactor
retain bounded shapes/paths/counts/presence/attribution, not raw values/private IDs/tokens. Reviewed
leaf plus exact attribution is required; mixed markers/nonempty containers are not proof.

Normalization returns typed records/metrics/time, shape metadata/diagnostics for sleep/daily
health/activity/intraday/FIT. Valid siblings survive malformed activities.
`ok | partial | empty | invalid` results are deterministic/sorted. Numeric
strings/booleans/nonfinite/wrong shapes are invalid numbers; first-present alias never falls through
null/invalid/zero.

| Metric | Exact mapping/quality |
| --- | --- |
| Average / maximum HR | Separate `heart_rate_bpm` / `max_heart_rate_bpm` (`maxHR`), positive bpm; reviewed same-parent `averageHR > maxHR` conflicts. |
| Duration/distance/speed | Nonnegative; positive distance/zero duration conflicts only for same-parent `distance/duration` or `distanceMeters/durationSeconds` in meters/seconds. |
| Effects | `training_effect`: first-present `aerobicTrainingEffect`, then `trainingEffect`; `anaerobic_training_effect`: only `anaerobicTrainingEffect`; each 0–5 points including zero, no sum/substitution. |
| Readiness | 1–100, zero invalid; producer/availability separate. |
| Load / Recovery Time | Nonnegative including zero; `recoveryTime` unit unknown, no hours conversion/universal maximum. |
| `session_total_calories` | Exact activity-list `calories`; nonnegative finite native number, `unit=None`; total including resting, not active kcal; no alias/BMR subtraction/daily substitution. |
| HRV | Strict agreeing `hrvSummary.calendarDate`; `hrv_weekly_average_ms` is weekly/trailing snapshot, not daily HRV. |

Quality overlays exclude older invalid projections without rewriting metrics/raw/ frozen outputs. No
universal HR/speed ceiling. `bmrCalories` is outside registry; optional absent fields do not downgrade
complete activities. Recorder/device association is not metric-producer proof; max HR needs reviewed
field evidence. Training uses the immutable spine. Status `mostRecent` is not history: provider dates
label records, requested dates stay acquisition metadata, undated structures stay undated. Readiness
timestamps remain separate. Routine refresh includes bounded Training with same client/auth; activity
effect/load retains list path.

Body Battery accepts current typed `intraday/body_battery` samples at
`payload.bodyBatteryValuesArray[index]`, metric path `payload.bodyBatteryValuesArray`, usable finite
points. Synthesized last-sample alias is not another measurement; legacy `bodyBattery/bodyBatteryLevel`
eligibility stays unknown. Future UTC/unknown time is excluded. Indistinguishable/conflicting
coordinates exclude day even for equal numbers; date-only cannot resolve multi-sample collision. Daily
saved maximum contributes once; mean weights days equally with exact rational arithmetic. Caps
100000/window, 10000/day; incomplete yields no maxima/mean/partial denominator. Not full-day
peaks/morning values/wear coverage.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `r02-garmin-auth-spike-v1` | Auth report | Session/protection | Not device proof. |
| `healthcheck-garmin-dpapi-v1` | Auth envelope | User/SID protection | No plaintext fallback. |
| `r02-garmin-capability-contract-v1` | Inventory | Client/device separation | Account needs evidence. |
| `r02-garmin-capability-fixture-v1` | Synthetic envelope | Synthetic attribution | Not live evidence. |
| `r02-garmin-capability-spike-v1` | Probe | Structural report | No ingestion. |
| `r02-garmin-redaction-v1` | Redactor | Shape/count evidence | Not raw export. |
| `r02-garmin-normalization-contract-v1` | Compatibility gates | Legacy interpretation | No universal equivalence. |
| `r02-garmin-normalization-contract-v2` | General normalizer | Typed max-HR/anaerobic | Specialized versions retained. |
| `garmin-activity-normalization-v2` | Activity | Session-total calories | No active-kcal proof. |
| `garmin-activity-quality-v1` | Quality overlay | Field conflicts/ranges | No physiology ceiling. |
| `garmin-training-phase-a-probe-v1` | Training probe | Structural evidence | Association not producer. |
| `garmin-training-evidence-v2` | Training read | Quality/provenance | Recovery unit unknown. |
| `garmin-training-owner-view-v2` | Training UI | Saved evidence | No new calculation. |
| `garmin-activity-session-owner-view-v2` | Activity UI | Exact saved session | No inferred end. |
| `r02-garmin-hrv-calendar-normalization-v3` | HRV | Explicit civil date | No requested-day fallback. |
| `r394-saved-body-battery-maxima-v1` | Body Battery | Saved maxima/mean | Not full-day peak. |
| `r340-garmin-overview-rhr-v1` | Garmin RHR | Existing eligibility | No substitution. |
| `r376-saved-rhr-read-v1` | Latest RHR | Date/age/exclusions | No relabelled date. |
| `r393-saved-rhr-period-v1` | Period RHR | Eligible-day rational mean | Missing excluded. |

<a id="google"></a>
## 3.9 Google records and acquisition contracts

Google Health API v4 (`health.googleapis.com`) is implemented; no legacy Fitbit Web API path. LIST
records retain `dataSource` platform/device/recording method; `list`, `reconcile`, `rollUp`,
`dailyRollUp` and `dataSourceFamily` are acquisition context, not stable device identity.
`google-wearables`, `google-sources`, `all-sources` differ; even wearables includes Fitbit/Pixel Watch
and is family-level without explicit physical metadata. Broad aggregates may contain manual/third-party
data and cannot become Fitbit-device evidence.

Sample HR supports list/reconcile/rollUp/dailyRollUp. HRV/daily HRV, daily resting HR, SpO2/daily SpO2
and sleep-summary/daily respiration use their list/reconcile surfaces; sleep has session operations. No
generic rollup support is inferred. Follow `nextPageToken`, inclusive lower/exclusive upper bounds;
Sleep page size 25 (not a 25-page cap), with maximum 40 pages/fetch in the sync adapter; HTTP
success/nonempty response is not completion or ordering proof. LIST/RECONCILE missing collection without
usable token is terminal empty; usable token continues; null/object/string/number/boolean collection
stays invalid. Rollup is not broadened.

One-account Web Application OAuth uses fixed exactly registered callback
`http://127.0.0.1:8765/oauth2/callback`, one-use persisted state, browser code flow, offline refresh
token and explicit reauthorization for scope changes. Testing refresh tokens have seven-day limitation;
personal production/unverified setup and Restricted-scope policy are operator prerequisites, not
service-account access. Default scopes: `googlehealth.sleep.readonly` and
`googlehealth.health_metrics_and_measurements.readonly`; optional Steps/exercise uses
`googlehealth.activity_and_fitness.readonly`. Partial consent is stream-level. Configured quota
assumptions (300 requests/minute/user; unverified aggregate 250 QPS/100-user cap) never override tighter
implementation request/retry bounds.

One logical sync permits at most one startup refresh and one GET-401 recovery refresh. Only successful
protected refresh without fallback permits identical GET replay, consuming data budget/per-page
attempts. Repeated 401/invalid_grant or failed/malformed/protection/storage recovery aborts later
streams as not_run. 403/POST rollup retain terminal behavior. No recovery if replay cannot fit. OAuth
bodies never enter raw health ingestion; unauthorized attempts cannot complete pages/checkpoints. Cached
access remains unverified, not refresh proof.

Windows protection retains DPAPI/SID. Non-Windows writes use AES-256-GCM: 32-byte key via HKDF-SHA256
(length 32, salt version constant, info `aes-256-gcm`), random 12-byte nonce, 16-byte tag; canonical
JSON exactly `format,purpose,nonce,ciphertext`. AAD is version ASCII + NUL + trusted
`google-client-credentials` or `google-tokens`. Plaintext 1–65536 UTF-8 bytes, envelope 96 KiB, purpose
`[a-z0-9-]{1,64}`; strict base64/types/fields/authentication fail closed. Legacy HMAC/XOR v1 is
authenticated read-only (16-byte nonce, 32-byte MAC, 1..65536 ciphertext). Reads never create
keys/rewrite envelopes; normal writes migrate individually. Envelope protection does not protect theft
of the whole profile/key/backup.

Instant identity is source/stream/context/canonical UTC, not response position/ field path.
Same-epoch/unorderable divergent revisions invalidate current state; strictly later orderable correction
may replace it. Old replay never restores stale value. Provider-native Fitbit Sleep Score/Readiness is
not established by these health records; derived scores must retain separate names.

[Google Steps acquisition](GOOGLE_STEPS_ACQUISITION.md) owns exact one-day wearables
rollup/request/consent/catch-up details. [Google exercise import](GOOGLE_EXERCISE_IMPORT.md) owns exact
resource/revision/pagination fields. Exercise is explicit `exercise/list/ google-wearables` over 1–14
civil start dates, maximum four pages/twelve data attempts. Resource names identify sessions; updateTime
orders corrections; active versus elapsed duration stays distinct. It does not pool with Garmin or
automatically extend cycling statistics/default streams.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `r04-google-source-contract-v1` | Source identity | Provider/device metadata | Family is not device. |
| `r04-google-web-oauth-v1` | Auth | Fixed callback/protected tokens | No implied optional consent. |
| `r04-google-capability-spike-v1` | Probe | Bounded structure | Not collection coverage. |
| `r04-google-terminal-envelope-diagnostic-v1` | Diagnostic | Sanitized terminal shape | Not raw export. |
| `healthcheck-google-dpapi-v1` | Windows secrets | User/SID protection | No plaintext fallback. |
| `healthcheck-google-local-key-v1` | Legacy local secrets | Authenticated old reads | No new v1 writes/purpose binding. |
| `healthcheck-google-local-key-v2` | Local secrets | Purpose-bound AEAD | Key/profile theft out of boundary. |
| `r04-google-normalization-contract-v1` | Explicit legacy replay | Original shape | Frozen retries retained. |
| `r04-google-normalization-contract-v2` | General normalization/demo | Typed vital interpretation | Sleep v3 separate. |
| `r04-google-normalization-contract-v3` | Sleep | `metadata.mainSleep` state/path | Existing originals need explicit replay. |
| `r297-google-daily-vitals-read-v1` | Saved daily vitals | Source/date/state/units | Not within-sleep measurements; UI clips long custom requests to trailing 400 inclusive dates with visible scope, not full Brief/Garmin period. |
| `google-steps-countsum-v1` | Typed Steps | Exact interval/int64 | [Steps semantics](#steps). |
| `google-steps-acquisition-v1` | Explicit acquisition | Request/raw context | Detailed contract linked above. |
| `google-steps-acquisition-normalization-v1` | Acquisition replay | Immutable request context | No generic timezone proof. |
| `google-steps-owner-catchup-v1` | Owner catch-up | Bound cursor | Not pre-activation history proof. |
| `google-exercise-acquisition-v1` | Exercise fetch | Pages/window receipt | Explicit operation. |
| `google-exercise-session-v1` | Exercise normalization | Named session/revision | No cross-provider merge. |

<a id="sleep"></a>
## 3.10 Sleep eligibility, quality and agreement

Saved night/range readers resolve exact source/local wake date, currentness, main/nap role, variant and
metric quality. They exclude explicit naps and ambiguous competing sessions without longest/latest
winner. Google saved-source policy accepts explicit `metadata.mainSleep=true` with nap
missing/null/false, retaining actual nap state. Invalid/conflicting main aliases exclude; false/null
remain unconfirmed. Absent mainSleep keeps legacy main-only policy. Multiple mains stay ambiguous; a
sole uncertain session is labelled, not promoted to overnight. Frozen account-pairing helpers retain
their separate v1 role rules.

`sleep_metadata_main_sleep` preserves its actual metadata path/state separately from legacy main.
`sleep_duration_asleep_seconds`, `sleep_time_in_bed_seconds`, WASO and `sleep_score` retain individual
units/eligibility; source `sleep_duration_seconds` never implies `sleep_stages`/`nap_duration_seconds`.
Reader methods are `read_source_sleep_night`, `resolve_source_sleep_point`, `read_source_sleep_range`;
`selected_source_id`/`wake_date` remain exact.

Garmin Sleep v4 accepts integral epoch-ms paired `dailySleepDTO.sleepStartTimestampGMT/Local` and
`sleepEndTimestampGMT/Local`. GMT proves instant; Local is nominal wall-clock encoding. Exact
whole-minute difference establishes each endpoint offset, not IANA zone. Original Local/path and
explicit calendarDate survive. Local-only/date-only stay so; malformed or conflicting endpoints are not
eligible instants. Id-less reconciliation retains legacy v2 identity inputs to avoid duplicate
instant-keyed nights.

Independent valid summary endpoints are stored as text metric `sleep_summary_session_bounds`, schema
`garmin-sleep-summary-bounds-v1` with two TemporalDTOs. No synthetic missing metric is added when
unsupported/absent. This metadata does not depend on phase rows, supply phases or become a sleep
measurement itself. Retained v3 fallback requires saved endpoint provenance. Production
`sleepLevels[].startGMT/endGMT` are explicit boundaries; integral `activityLevel`: 0=DEEP, 1=LIGHT,
2=REM, 3=AWAKE. Unknown codes, gaps, overlaps, order/boundary conflicts and competing aliases make
stages incomplete. Summary end validates final stage, never replaces `complete_stage_boundary`. Endpoint
offsets remain independent, without intermediate DST/travel inference.

Complete stage-derived asleep/TIB or absent-stage zero requires recognized, ordered, nonoverlapping
contiguous stages covering independently confirmed session bounds. Legacy contiguous levels without end
cannot prove REM=0/TIB. Separately valid summaries remain usable despite incomplete phases. Google
summary integral minutes convert exactly to seconds without guessed slack. Negative duration or
contradiction with proven session/TIB bounds excludes it. Scalar-valid legacy summaries with unavailable
bounds remain eligible with `session_bound_validation=unverified`, reason/upper bound explicit; absence
alone does not remove a night. Proven bounds cannot be ignored under this exception. Quality snapshots
retain scalar/interval/summary dependencies; old frozen outputs are not reinterpreted. Missing
historical metadata never becomes checked.

Latest saved Sleep returns real wake date/age (evaluation civil date minus wake date), no age threshold
and no future dates. Refresh/copy age does not invalidate history. Preview accepts explicit observation
IDs (maximum 30), exact source, 1–30 dates and 1 MiB verified originals in an existing read-only
snapshot; it reports hypothetical timing/currentness/blockers without replay or persistence.

### Agreement and canonical gates

Legacy pairing uses one main overnight per source/wake date. `device_pair` requires physical
attribution; `family_pair` is exploratory. Manual Google edits cannot enter the strong gate. Proprietary
scores are display-only, not equivalent measurements. Difference is Google minus Garmin. Account cohort
`account_wearables_sleep_observations_v1` is explicitly selected; legacy `all` pairing still means
device/family cohorts, while report all includes published account runs. Account source conflicts
exclude before role selection; explicit Google main=true/nap=false has priority, otherwise only a unique
remaining session may supply uncertain-role evidence. No invented attribution/nap state.

Exploratory statistics require at least 14 valid metric pairs, no extra span gate. Canonical proposal
requires at least 42 strong-eligible device-pair nights, span delta at least 41 days (six calendar
weeks), no known method break and passed stability; coverage/max gaps remain reported, without invented
automatic coverage percentage. Account strong count is always zero/canonical false, including at 42+.
Garmin remains default until separately reviewed versioned rule.

Statistics retain N, bias, MAE, RMSE, sample SD, Bland–Altman limits `bias ± 1.96 * SD`, Type-7 robust
0.025/0.975 quantiles, correlation and Lin CCC. Tukey outlier sensitivity uses 1.5*IQR, not automatic
deletion. Stability splits ordered pairs at `n//2`; each half needs two nights, robust intervals must
overlap and both half biases lie in full robust limits. N/correlation alone cannot switch source. Frozen
pairing/projection/run/report versions and input hashes persist.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `data-saved-sleep-v1` | Latest saved Sleep | Date/age/exclusions | Not current-day substitution. |
| `source-sleep-range-v1` | Exact night/range | Source/roles/metrics/provenance | 400/provider, 200/night. |
| `saved-google-main-sleep-v2` | Saved Google role | mainSleep/nap states | Not frozen account policy. |
| `r02-garmin-sleep-normalization-v3` | Retained Sleep interpretation | Production phase timing | Legacy quality compatibility. |
| `r02-garmin-sleep-normalization-v4` | Current Sleep normalization | Independent summary endpoints | Does not establish stage completeness. |
| `garmin-sleep-summary-bounds-v1` | Boundary metadata | Independent start/end DTOs | Not a scalar sleep result. |
| `sleep-duration-quality-v2` | Quality helper | Nonnegative/bound-compatible duration | Legacy unverified-boundary policy retained. |
| `r03-garmin-sleep-duration-quality-v2` | Legacy scalar overlay | Same quality exclusions | No raw rewrite. |
| `saved-garmin-sleep-normalization-preview-v1` | Read-only preview | Hypothetical interpretation | No write/recovery authority. |
| `r05-01-sleep-pairing-v1` | Legacy pairs | Device/family wake-date pairing | Not account cohort. |
| `r05-account-wearables-sleep-pairing-v1` | Account cohort | Role/source uncertainty | Never canonical evidence. |
| `r05-02-sleep-metric-projection-v3` | Metric projection | Typed quality dependencies | No stage gap filling. |
| `r05-02-sleep-metric-rules-v3` | Metric rules | Per-metric eligibility | Independent summary exception explicit. |
| `r05-03-sleep-agreement-run-v1` | Persisted run | Frozen pairing/projection | Not live recomputation. |
| `r05-03-sleep-agreement-rules-v1` | Run rules | Reproducible manifest | No implicit switch. |
| `r05-03-sleep-statistics-contract-v1` | Statistics boundary | Run/statistics compatibility | Source-specific eligibility. |
| `r05-04-sleep-agreement-v1` | Agreement contract | Statistics packet | Exploratory/strong gates distinct. |
| `r05-04-sleep-agreement-rules-v1` | Statistics rules | Exact methods | No accuracy/causal claim. |
| `r05-04-sleep-agreement-statistics-v1` | Algorithm | Bias/error/association | Not score equivalence. |
| `r05-04-stability-overlap-v1` | Stability | Half-distribution overlap | Not N alone. |
| `r05-05-sleep-agreement-report-v1` | Report | Frozen drill-down/gates | Not canonical mutation. |
| `r05-06-sleep-agreement-build-v1` | CLI build | Build/run identity | Explicit acquisition-independent command. |

<a id="steps"></a>
<a id="garmin-steps"></a>
<a id="saved-google-steps-read-392"></a>
## 3.11 Steps: observed, completed and all-time

### Garmin observed and completed

Observed projection reads saved `daily_health` originals named exactly `daily_summary.json`. Only strict
top-level `calendarDate=YYYY-MM-DD` and nonnegative JSON-integer `totalSteps` qualify;
bool/float/string/negative invalid. Exact integers use canonical decimal `value_text`, never float;
explicit zero is valid. Source/account attribution, unknown device/timezone/coverage/finality remain.
Request bounds/receipt cannot reinterpret source day. Relevant originals include requested returned day
and every unproven day; SHA/size/link verification, duplicate-key rejection precede derivation. Routine
acquisition wires projection; GET never projects. Repeated bytes share derived identity, keep all
acquisitions. Different artifacts remain. One distinct valid count wins; multiple distinct counts are
ambiguous, never latest/largest/sum. Nonvalues remain visible without retracting a valid observed count.
No supported evidence means unavailable, not no collection or zero.

Read-only observed window reads materialized rows without original-byte reads, automatic source choice
or aggregation. It retains independently complete earlier cells; truncated day/later unexamined dates
are `search_incomplete`. No projection gives `projection_unavailable/not_evidenced`, not proof
projection never ran. Unsupported contracts/provenance fail the affected day closed.

Completed reader selects exact source and latest proved **observation** receipt at/after next Moscow
midnight, excluding current/future days. Later lower correction wins; latest
missing/null/invalid/unproven never reveals older number. Equal-time divergent states/values are
ambiguous. Original first-seen time is not selection clock. Require exact
source/run/event/batch/artifact/hash links; reprocess/failed/running evidence cannot prove acquisition.
Successful legacy runs retain their predicate; terminal partial requires valid immutable receipt below.
Moscow completion does not establish Garmin timezone, wear or irrevocable finality.

| Entry | Dates | Candidate/provenance bounds | Original/work policy |
| --- | --- | --- | --- |
| Observed projector | Explicit day | 1000 originals/4096 observations, cap+1 | 1 MiB/original; verified retained/unproven groups. |
| Observed window v1 | 1–366 inclusive | Independent 4096/4096, cap+1 | No bytes; complete earlier cells survive. |
| Completed window v2 | 1–366 inclusive | Source-wide 4096/4096 | 1000 originals, 1 MiB each, 16 MiB total, cooperative 5 seconds; complete search. |
| Completed all-time v1 | Sparse through explicit end/yesterday | Global 4096/4096, cap+1 | Global 4096 unique originals, 1 MiB each, 16 MiB total, cooperative 5 seconds; never reset per year/day. |

All-time requires explicit exact source, no auto-selection/pooling. Start is earliest verified completed
returned day, not account-history start. Effective end caps at Moscow yesterday. Sparse span arithmetic
avoids dense expansion over huge gaps. Any exhausted bound/integrity-unknown original/unproved grain
means `search_incomplete` with no aggregate/winning prefix. Eligible unique dates contribute once: exact
integer sum, mean=sum/eligible days (zero included). Counts strictly `>10000`/`>20000` exclude equality;
streak is `>=10000` on adjacent dates. Gaps/invalid/null/missing/ambiguous/unavailable break streaks.
Retain all record ties/all equally longest ranges. No eligible values means unavailable aggregates;
eligible values with no threshold hits mean true zero threshold count. No Google all-time or
full-provider-history claim.

### Immutable acquisition/date proof

`garmin-daily-summary-acquisition-v1` is append-only one-to-one observation FK. Only complete new
`daily_summary/get_user_summary` acquisition mints it, after optional Steps callback, before
checkpoint/commit in the same transaction. Strict returned day must equal request day, UTC request-day
window and run bounds must bind exactly. Same-key replay cannot add missing proof/advance receipt; new
acquisition may reuse bytes. Invalid/unsupported receipt fails closed. An original is excluded from
completed byte budget only when every observation has valid agreeing receipts proving an outside day.
Legacy/conflicting/unreceipted groups remain relevant; decoded date is checked again for retained
originals. Trusted writer/index is not authentication against internally forged database rows.

`garmin-daily-summary-saved-date-v1` separately certifies strict original day, not
success/Steps/coverage. Ordinary projection shares cooperative SQL budget across
selection/observations/flush, rolling back derivation savepoint on failure. Explicit
`index_saved_summary_dates` bootstrap: default 64, max 1000 originals, 4096 observations, 1
MiB/original, 16 MiB physical reads including sentinel, 5 seconds/20-million SQL steps. Guard restores
busy_timeout/clears its callback, not arbitrary unknown caller callbacks. Malformed rows stay unproven;
cursor can pass them without proof. Cursor reuse requires commit; fatal rollback resumes input cursor.
New sweeps catch low-ID arrivals; no unlimited-history guarantee.

Explicit `--reacquire-unproven-daily-summary` accepts only exact stored source, daily_summary, completed
dates, at most 14 days, incompatible with --reprocess. One unchanged reader snapshot preflights whole
range before auth; no per-chunk budget reset. Proven nonnumeric/zero acquisitions skip.
Corrupt/incomplete/ ambiguous/disputed existing receipts block repair. Per-day error stops, prior
commits remain; all-proven resume makes no provider call. Offline replay cannot mint missing historical
success.

### Google saved intervals

`steps_count_sum`, unit `count`, accepts only canonical string integers 0 through 9223372036854775807.
Signs/whitespace/leading zeros/fractions/exponents/bools/JSON numeric tokens are invalid. Decoder
verifies metric/state/unit/decimal/range and null `value_number`/`collection_json`. Interval identity
retains exact raw `civilStartTime/civilEndTime`, family/daily mode, not response position/name/count.
Different endpoint encodings conservatively differ; no UTC/24-hour inference. Same-epoch conflicts
invalidate, later correction can lower/null/remove value; maximum conflict receipt remains barrier to
stale replay.

Saved reader uses exact 7/30 civil dates and one known family aggregate. Auto-choice requires sole saved
Steps source. Current dailyRollUp exact midnight-to-next-midnight intervals supply dates. Multiple
encodings on a day are ambiguous even at equal count. Partial/multiday intervals exclude every
intersecting date, never split/sum; unlocatable interval withholds whole result. Retired excluded; as-of
uses projection_observed_at. Coverage/pagination/timezone/finality always unknown. Bounds: discovery 128
sources; 4096 current records source-wide; 4096 per child collection; 16 MiB text; cooperative five
seconds. Incomplete withholds all values. Presentation summary sums exact eligible unique integer days
and divides by observed count, not requested count. No eligible days gives no total/mean.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `garmin-observed-daily-steps-v1` | Projection | Distinct-count ambiguity | Not correction authority. |
| `garmin-observed-daily-steps-window-v1` | Materialized window | Complete-cell evidence | No original reverification. |
| `garmin-completed-day-steps-moscow-v2` | Completed window | Latest proved post-boundary acquisition | Not provider finality. |
| `garmin-completed-day-steps-moscow-all-time-v1` | All-time | Sparse exact-source statistics | No partial prefix. |
| `garmin-completed-steps-all-time-budget-v1` | All-time work | Global budgets | Cooperative, not hard I/O deadline. |
| `garmin-daily-summary-acquisition-v1` | Acquisition receipt | Exact new fetch proof | No retroactive certification. |
| `garmin-daily-summary-saved-date-v1` | Saved-date proof | Strict returned day | No acquisition-success claim. |
| `google-saved-steps-window-v1` | Google saved read | Exact source/interval/currentness | No complete-day certification. |
| `google-observed-steps-summary-v1` | Google summary | Observed-day sum/mean | Coverage stays unknown. |
| `garmin-completed-steps-summary-v1` | Garmin presentation | Existing completed statistics | Display-only rounding in 3.14. |

<a id="analytics"></a>
## 3.12 Deterministic analytics and saved-data analyses

`AnalyticInputDTO` freezes code/unit/aggregate/window, selected state/value/path, analytic time,
source/algorithm, metric coverage and immutable raw/hash/observation/
record/metric/normalization/reconciliation references. `manifest_hash` covers canonical JSON excluding
itself. Storage assembly joins/validates provenance; collection metrics freeze selected interval
dependencies, not just locators. Operational present does not prove metric usability; analytic
availability is `available | missing | null | zero | invalid | not_computable | partial` with
counts/exclusions. Sleep duration does not imply score/stages/naps.

Average/maximum/sample Stress and daily/trailing-seven-day/sample SpO2 are distinct:
`stress_daily_average=avgStressLevel`, `stress_daily_maximum=maxStressLevel`, `stress_sample`;
`spo2_daily_average=averageSpO2`, `spo2_trailing_7d_average=lastSevenDaysAvgSpO2`, `spo2_sample`. No
substitution. Scalar series bounds: 400 calendar days/2000 candidates before selection. Type-7
interpolation uses `h=1+(n-1)*p`; personal midrank is `100*(less+0.5*equal)/n` (minimum 5 usable). Trend
is median finite pairwise slope per day (minimum 3 usable on 3 dates). Modified robust z is
`0.67448975*(value-median)/MAD` (minimum 5 usable), deviation at `abs(z)>=3.5`; zero MAD stays
noncomputable rather than division by zero.

Activity comparison accepts 2–20 distinct selected records/reference in that set, one source, compatible
metric definitions. Delta B−A; percentage `(B-A)/A*100`, zero A gives `zero_reference_percent`,
nonfinite result withheld. Default order: `session_total_calories`, `duration_seconds`,
`distance_meters`, `speed_mps`, `heart_rate_bpm`, `power_watts`, `cadence_rpm`, `training_effect`,
`acute_training_load`, `max_heart_rate_bpm`, `anaerobic_training_effect`. Cadence requires unambiguous
RPM leaf (`cadenceRpm`, `averageBikeCadence`, `avgBikeCadence`, `bikeCadence`), not
RunningCadence/StepsPerMinute aliases. Older frozen v1 eight-code/v2 added-HR-effect/v3 quality results
keep their hashes; current rule v4 adds total calories without inventing kcal.

Lagged association uses Spearman midranks, `x_at_d_pairs_y_at_d_plus_k`, minimum 5 pairs/2 distinct
values, |lag| at most 14 days and at most 15 requested lags. No missing-day fill, best-lag causal
ranking or activity-session scalar coercion. Period summaries support 7/30, trailing365, YTD/calendar
year. Shared bounds: 32 sources, 4096 records, 16384 metric rows, 8192 metadata rows/table, 131072 sleep
intervals, 2048 coverage rows, cooperative two seconds, batch size 256. Incomplete cells withhold
official values/counts. Counts/types include valid saved sessions; tennis exactly `tennis|tennis_v2`,
duration independently eligible; cycling exactly `cycling`, distance independently eligible. Proven
complete empty coverage can yield count 0/types {}, not missing duration/distance zero. Observed records
on confirmed-empty days retain contradictory coverage.

### Stress adapters

Daily Stress uses `r03-01-v2`/applicability v1: only proven normalizer-created missing daily-mean
placeholders from heart_rate/body_battery/spo2/respiration may be non-candidates. Require exact
surface/day/path/unit/version plus committed raw/observation/event/batch identity recomputation;
filename/missing alone is not proof. Audit/input hashes retain excluded placeholders. Genuine
duplicates, missing/null/invalid and conflicting provenance remain candidates/fail closed. Explicit
`selection_version=r03-01-v1` retains legacy body/hash.

`stress_baseline` reads D and `[D-28,D-1]` in one physical snapshot with aware evaluation; at least 21
eligible distinct historical days, no subset recomputation. v2 copies frozen median/Type-7 P25/P75 and
current-minus-median. Participant source/method/unit/attribution must agree; only reviewed stress v1/v2
normalizer equivalence is allowed. Metric-specific partial/incompatible evidence withholds comparison.
Successful ordinary incremental/historical stress.json acquisition must bind exact provenance and
post-boundary receipt; at most 29 originals, 1 MiB each. Strict v2 requires original
calendarDate/mean/unambiguous IANA zone and compatible clocks. Optional malformed clock normalized away
need not override independent valid date/zone. Skipped midnight unproven; ambiguous midnight uses later
valid boundary. Saved current may remain with unavailable comparison.

Explicit `analysis_day_policy=owner-selected-europe-moscow-analysis-day-v1` selects v3 median mode.
Source dates/means are not recalculated as Moscow days. Absent source zone or confirmed Moscow is
allowed, not null/invalid/conflicting/ other zone. All supplied clocks/alternate dates/offsets must
validate; DST gaps fail, folds require uniquely supported instant. Receipt chain satisfies
`started <= received <= completed <= evaluated`, `received >= next Moscow midnight`.
Settings/host/evaluation/replay cannot turn pre-boundary receipt into completion.

Explicit `comparison_method=arithmetic-mean-v1` selects v4, independently of day policy. It copies
frozen `statistics.fmean` baseline, equal eligible-day weights; delta is unrounded current-minus-mean,
direction above/below/equal. Nonfinite mean/delta/R03 overflow withholds comparison
(`frozen_baseline_mean_nonfinite`, `comparison_delta_nonfinite`, `r03_statistics_nonfinite`), not a
smaller sample. Median/P25/P75 remain named. Omitted method/policy retains v2/v3 shape/hash.

### Saved Context-to-sleep and regularity

Analyses consume allowlisted Sleep/current Context in the same snapshot. One resolved source night needs
eligible ordered instant endpoints, explicit zone/ offset, accepted role (Google uncertain excluded).
Garmin start is `explicit_record_boundary`, end `complete_stage_boundary`; no duration-made end.
Partition by provider/exact source/variant/endpoint methods/normalization/zone or fixed offset. IANA DST
uses real offsets; changed fixed offsets/travel separate.

Timed Context anchors use instant or interval end, never date-only/created_at midnight. Pair first
eligible sleep start in inclusive `[anchor, anchor+hours]`, default 24, configurable 1–48. Many events
may pair one night; unique nights count once. Compare accepted duration/TIB/WASO/score with matching
unit/method/variant, minimum 3 unique nights/group. Reference is other compatible snapshot nights with
exposure unknown, never event-free controls. No HRV/Body Battery recovery or workout pair (activity end
is not persisted).

Explicit `context_event_revisions=((event_id,revision_id),...)` selects 1–100 distinct current pairs
from already-read Context, no extra read/expanded window. Malformed/duplicate/stale/missing/capped-out
pair fails whole export. Date-only selected event still gets timing exclusion.
`observed_context_by_night` retains selected/other observed paired revisions; `other_event_exclusions`
discloses unpaired others. Empty lists do not prove no confounders/exposure.

Regularity is circular local-clock population variability for start/end and elapsed-UTC midpoint
converted to evidenced zone. For minutes t: `theta=2*pi*t/1440`, `R=abs(mean(exp(i*theta)))`,
`SD=sqrt(-2*ln(R))*1440/(2*pi)` minutes. Minimum 3 unique nights/partition; `R<1e-12` undefined/null.
Social jetlag is uncorrected circular free-minus-work shortest signed minutes `[-720,720)` plus absolute
value, minimum 3/group. Only explicit `sleep_day_types` work/free/unknown classifies wake dates;
duplicates/ out-of-window labels fail. No weekday inference, sleep-debt/shift correction or persisted
classification. Timeline shows source-separated start/end regularity.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `r03-garmin-analytic-input-v1` | Input DTO | Frozen provenance/value | Not current-record lookup alone. |
| `r03-garmin-analytic-coverage-v1` | Metric coverage | Availability/counts | Acquisition is separate. |
| `r03-garmin-analytic-rules-v1` | Legacy gates | Original interpretation | No blanket compatibility. |
| `r03-garmin-analytic-rules-v2` | Current registry | Distinct activity metrics | Activity adds `:activity-quality-v1`. |
| `r03-01-garmin-scalar-baselines-v1` | Scalar algorithm | Quantiles/trend/deviation | Bounded inputs. |
| `r03-01-v1` | Legacy scalar rule | Strict daily selection/hash | Explicit compatibility. |
| `r03-01-v2` | Stress rule | Proven applicability | Other metrics retain v1. |
| `r03-01-stress-daily-mean-applicability-v1` | Stress selection | Placeholder audit | No value-based winner. |
| `garmin-daily-stress-personal-baseline-v2` | Strict adapter | Source-zone/median proof | No implicit Moscow. |
| `garmin-daily-stress-personal-baseline-v3` | Moscow adapter | Explicit analysis policy | Source zone not inferred. |
| `garmin-daily-stress-personal-baseline-v4` | Mean adapter | Frozen arithmetic mean | No participant filtering. |
| `confirmed-source-timezone-day-v1` | Strict completion | Named source-day boundary | Not host clock. |
| `owner-selected-europe-moscow-analysis-day-v1` | Opt-in completion | Moscow analysis boundary | Saved means/dates unchanged. |
| `arithmetic-mean-v1` | Comparison method | Current-minus-frozen-mean | Independent of zone policy. |
| `r03-02-garmin-activity-comparison-v1` | Comparison algorithm | Source-bound deltas | No self-comparison. |
| `r03-02-v4` | Current comparison rule | Total-calories/quality semantics | Unknown native energy unit. |
| `r03-02-garmin-activity-session-detail-v2` | Session detail | Reviewed metric definitions | No inferred end. |
| `r03-03-garmin-lagged-associations-v1` | Lag algorithm | Explicit directional pairs | Association only. |
| `r03-03-v1` | Lag rules | Pair/sample gates | No best-lag causal claim. |
| `source-period-summary-v1` | 7/30 summary | Source-specific reducers | Sleep selection is an optional metric override. |
| `source-period-summary-v2` | Annual summary | trailing365/YTD/calendar_year, period_type/read_limits | Same reducers, at most 366 days; not arbitrary all-history. |
| `period-brief-v2` | Period Brief | Shared calculation packets | Baseline capped to trailing 180 days with explicit reason. |
| `saved-sleep-analysis-inputs-v1` | Analysis input | Partitioned night evidence | Not full history. |
| `saved-context-next-sleep-v1` | Pooled timed Context | First-night descriptive comparison | Reference exposure unknown. |
| `saved-context-next-sleep-v2` | Selected revisions | Explicit chosen set/other context | Not inferred complete category. |
| `saved-sleep-circular-local-clock-v1` | Regularity | Circular variability/jetlag | Explicit work/free labels only. |

Summary cells retain `canonical_metric_code`, `unit`, `aggregation` with `kind`, `value`, `numerator`,
`denominator`, `eligible_count`, `excluded_count`, `observed_count`, `observed_day_count`,
`observed_calendar_dates`, `eligible_dates`, `effective_dates`, `observed_dates`, `availability_counts`
and exclusions (`reason_code`, `count`). Coverage/snapshot facts are not replaced by local search
success. Cycling metadata uses `source_count`, `eligible_source_count`, `ambiguous_source_count`,
`ambiguous_record_count`, `reason_codes`, `search.complete`/reason. Scalar manifests retain
`reader_result_hash`; Stress comparisons expose `delta_points` and method.

<a id="context-and-labs"></a>
## 3.13 Context and laboratory documents

Context storage has stable event UUID/current pointer and append-only numbered revisions/tags. Original
text is untrimmed/unparaphrased, no NUL, maximum 4000 Unicode code points. Capture sources:
cli/manual/dashboard; telegram is reserved, rejected. Tags normalize Unicode/case/separators,
deduplicate, maximum 64 code points. Explicit tags are confirmed; omitted tags retain original
status/provenance. Suggested/rejected states are representable, not automatic AI interpretation.

Explicit date, offset-bearing timestamp, equal-precision date range or timestamp interval is required;
no parsing today/yesterday/last night. Date-only rejects timezone. Optional IANA validates timestamp
wall clock/offset. Reversed/mixed intervals fail. `operation_id` binds operation and explicit normalized
request; identical retry converges even after head advances, changed input conflicts. Expected-revision
CAS/serialized write prevents stale overwrite. Prior versions remain queryable. Service list default
50/max 200; UI current/history each 50 with overflow notice. UI filters inclusive date overlap/newest
first; history is explicit. Forms are 64 KiB with duplicate/foreign fields rejected, escaped drafts,
POST/303/GET committed readback, no-store and generic error messages.

City/IANA input resolves event-date offsets, explicitly chooses each repeated DST endpoint, rejects gaps
and invalidates stale fold choice after changes. Unchanged edits retain original Z/offset spelling,
seconds/fractions, zone absence and tags. Date-only submits no zone/time; legacy offset-only gets no
invented city. Storage does not infer events, negative exposure or associations. Implemented descriptive
comparisons are in [3.12](#analytics); broader experiments, medication/ supplement histories and causal
analysis require separate scope.

Laboratory intake accepts original PDF plus structured transcription, stages review/correction and
explicit selected-result confirmation/full-snapshot revision. One PDF is one report/one patient;
unresolved linkage blocks confirmation. Accepted transcription is separate from
`source_match=unverified|owner_verified`. Exact decimals/raw strings, nullable units/ranges, distinct
result/printed/specimen dates and provenance survive without invented conversion/range/confidence. No
automatic OCR/interpretation/export or generic chat transport is implied.
[Laboratory intake v1](LAB_INTAKE_V1.md) owns the full bounded schema, artifact, revision, confirmation
and original-download contract; it is not duplicated here.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `context-capture-v0` | Context/evidence projection | Original revisions/explicit time/tags | No inferred dates/negative exposure. |
| `lab-draft-v1` | Lab transcription | Exact strings/provenance/linkage | Full schema/limits in linked contract. |

<a id="presentation"></a>
<a id="ui-evidence-states"></a>
## 3.14 UI, routes and presentation

The main view must retain source, date/actual window and incomplete coverage (“N из D дней”).
Method/IDs/qualifiers may use accessible disclosure; incomplete period and interpretation-changing
conflict/search limits cannot be hidden. Some current compact cards place denominator/source detail in
heading disclosures; that existing implementation does not waive this Owner presentation requirement.
Failed refresh does not erase saved history. No-change requires explicit comparison. `owner_ui.html`
shares `present`, `partial`, `confirmed_empty`, `unknown`, `unavailable`, `insufficient`,
`not_requested`, `loading`, `error`, `no_change`; unrecognized states display unknown. Native
info/technical details start closed, keyboard accessible without JS. Disclosure is not an access/privacy
boundary.

| Route | Surface / compatibility |
| --- | --- |
| `/` | 307 to `/brief`; any root query goes to `/weight` preserving exact query string. |
| `/brief` | Overview; Weight/Activity requested dates versus disclosed completed Moscow window. |
| `/weight` | Weight/composition table/chart with method separation. |
| `/sleep`, `/agreement` | Source-separated 7/30 timeline/selected night; secondary exploratory comparison. |
| `/statistics` | 7/30, trailing365, YTD/calendar year; Garmin Steps-only `steps_period=all_time`; Google Steps 7/30. |
| `/statistics/sessions`, `/garmin/session` | Exact source/window sessions and saved session detail. |
| `/garmin#activity-journal`, `/garmin#training-recovery` | Five recent sessions/history/A-B and native Training/series/lag views. |
| `/google/exercise` | Separate saved Google exercise surface. |
| `/imports`, `/imports/{batch_id}` | Data/export/source status/photo queue/review; bounded recent inventory. |
| `/context`, `/context/{event_id}` | Comments/current revisions/history/edit. |
| `/labs`, `/labs/schema` | Lab intake and draft schema; detailed routes in lab contract. |
| `/api/weight/series`, `/api/weight/summary` | Canonical/raw/filter/provenance and deterministic summary. |
| `/api/imports/photos`, `/api/imports`, `/api/imports/{batch_id}` | Photo POST and status GET; candidate edit/confirm/reject at `/api/import-candidates/{action}`. |
| `/api/import-events/{event_id}/reprocess` | Explicit retained-photo reprocessing POST. |
| `/api/imports/saved-sleep`, `/api/imports/saved-rhr` | Bounded saved latest observations. |
| `/api/analysis-export/sources`, `/api/analysis-export` | Source GET, explicit bounded download POST. |
| `/healthz`, `/login`, `/logout` | Health and home-server authentication; listener separation in 3.2. |

Overview detail `period_at` pins an aware selected instant: original civil date anchors rolling
controls, Moscow date completed days, while evaluation stays current. Source changes/Back/Reload
preserve window; new period resets selection. Sleep drilldown retains exact source/completed 7/30
bounds; unsupported spans explain limitation. Activity/Statistics preserve separate list/detail return
context. Data owns `/imports#analysis-export`; prefill accepts only canonical `export_end_date` and
`export_days=7|30`, rejects duplicates/unsupported bounds. GET never generates evidence. Download begins
only after capped JSON/text both succeed; edits invalidate prior result. Source ambiguity needs explicit
choice.

### Formatting and visual system

Presentation never rounds stored values, calculations or export measurements. Current
formatters/templates differ by value; there is no universal two-decimal rule. Exact native
units/seconds/ratios remain accessible.

| Value | Current display rule |
| --- | --- |
| Ordinary duration | Half-up to whole minute; positive <60 seconds shows `<1 мин`; zero `0 мин`; at ≥3.6e12 seconds scientific approximate hours. |
| Distance | Meters to km, half-up 0.01; positive rounding to zero shows `<0,01 км`; at ≥1e12 meters scientific approximate km. |
| Activity number | `owner_number` one decimal using Python formatting; invalid/missing “Не предоставлено”. |
| Overview Sleep | Final mean half-up whole second, then human duration formatter. |
| Overview Stress/Body Battery and period RHR | Final-only whole-number half-up; daily graph/input precision unchanged. |
| Steps averages, including all-time | Exact integer-ratio half-up to whole steps, grouped narrow-space digits. Underlying Google/summary one-decimal HALF_EVEN ratio remains, positive rounded-zero `<0.1`. |
| Selected-day Stress delta | Unrounded reader result; positive magnitude <0.01 described as less than 0.01, never equal. |
| Dates/times | Russian month names, retained source wall time/offset/precision; no browser timezone conversion of date-only data. |

Steps browser data keeps counts/ratios as decimal strings, only bounded SVG geometry numeric. Missing
dates break lines, zero stays a point; keyboard/mouse selection uses same values, no arbitrary initially
selected date. Native table is no-JS fallback. Empty Weight/Body Battery plots disappear only without
any eligible non-None value. `tennis_v2` is a display alias for Теннис, not type reclassification.
Unknown Recovery Time unit stays adjacent to actual value/zero.

Поддерживаемая настольная область начинается с 1024 CSS px. `dashboard.css` задаёт систему Observatory; тёмная тема — базовая, светлая включается системной настройкой или явным выбором. `--owner-focus` ссылается на `--accent`. Цвета не оценивают здоровье.

| Роль | Токен | Тёмная | Светлая |
| --- | --- | --- | --- |
| Фон / навигация / поверхность / вложенная поверхность | `--bg` / `--rail` / `--card` / `--sunken` | `#0d1520` / `#0a111a` / `#131e2c` / `#182638` | `#f2f4f8` / `#e8ecf2` / `#ffffff` / `#eef1f6` |
| Основной / вторичный текст | `--ink` / `--muted` | `#e8eef6` / `#9aa8bb` | `#142031` / `#556275` |
| Разделители / усиленные линии | `--line` / `--line-strong` | `#22324a` / `#3a4d66` | `#dbe1ea` / `#b5c0cf` |
| Действие и фокус / текст на акценте / подложка выбора | `--accent` / `--on-accent` / `--accent-soft` | `#f0bf5a` / `#1a1405` / `#2e2715` | `#8a5a00` / `#ffffff` / `#f7ecd6` |
| Внимание: текст / фон | `--attention-ink` / `--attention-bg` | `#f3cf86` / `#33280f` | `#6b4510` / `#f8eedc` |
| Недоступно: текст / фон | `--unavailable-ink` / `--unavailable-bg` | `#f4b48a` / `#3a2216` | `#6b320c` / `#f6e3d3` |
| Ошибка: текст / фон | `--error-ink` / `--error-bg` | `#ffb3b3` / `#3d1b20` | `#7a2424` / `#f9e9e8` |
| Наблюдение / тренд / ориентир / второй источник | `--series-1` / `--series-2` / `--series-3` / `--series-4` | `#79b0ff` / `#d79bf5` / `#c4cbd6` / `#5ec4b6` | `#2456a6` / `#8a3fb0` / `#5b6577` / `#1f7a70` |

`--raw`, `--trend`, `--goal` ссылаются на первые три ряда. Для текста и заголовков используются локальные семейства `--owner-sans` и `--owner-heading-font`. Навигация расположена сбоку; переключатель «Авто / Тёмная / Светлая» управляет `data-theme`, а без JavaScript действует системная схема. Элементы управления сохраняют доступный фокус, широкие таблицы и графики прокручиваются локально.

The footer in `base.html` unconditionally says “Интерфейс только на этом компьютере” in both loopback
and authenticated home-server mode. Home-server additionally has logout navigation; footer text is not a
bind/access check. Its literal wording does not prove the deployment is loopback or configured remote.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `sleep-timeline-ui-v1` | Timeline | Source-separated 7/30 values/regularity | No wider-reader promise. |

<a id="evidence-and-ai"></a>
## 3.15 Evidence packets, reports and AI access

### Shared read and disclosure boundary

Evidence requires explicit existing profile and trusted operator classification
`synthetic | disposable_owner_clone | durable_owner_runtime`; Owner kinds are private. Classification is
assertion, not authentication or verified Stable/copy identity. Readers do not
prepare/migrate/refresh/discover profiles, call providers or models, write application data or
automatically upload. Missing/outdated schema fails without repair. One WAL-aware SQLite `mode=ro`
transaction uses query_only, deny-write authorizer, current-schema check, 20-million SQL steps/20-second
progress deadline. No immutable=1/normal writer factory. WAL/SHM coordination may occur. Nested readers
retain the outer guard, not replacing callback/busy_timeout. Cooperative budgets are not hard
SQL/lock/I/O/whole-response latency guarantees.

Recursive allowlists retain source/time/metric/role/quality/provenance/version/ exclusion facts, drop
unknown fields and containers in scalar positions. No raw provider
body/GPS/path/credential/config/SQL/queue/debug dump crosses them. Original authorized Context text is
literal untrusted data, JSON-escaped in text, not scrubbed into synthetic text or interpreted as
instructions. Context uses current revisions/date overlap, 1–100 rows (default 50), cap+1,
`has_more/truncated` and unknown total on truncation. Overlap may start before window. Missing note
never proves absence of exposure.

JSON/text serialize one frozen result; canonical compact UTF-8 JSON SHA-256 excludes the envelope's own
hash. Both have independent 2 MiB UTF-8 limits, including text headers. Oversize gives no winning
prefix. Export destinations must be new/outside profile and Git/linked worktrees, including ancestor
`.git` files/directories/resolved directory links; explicit agent roots also excluded. Both serializers
validate before file creation/stdout; files never overwrite. See
[export procedures](OWNER_OPERATIONS.md#analysis-export).

| Version | Where used | Preserves | Limits/semantics |
| --- | --- | --- | --- |
| `health-chat-evidence-v1` | Weight/Garmin scalar/Context export | Source/coverage/algorithms/current revisions | 1–90 dates, at most 8 selected Garmin scalars, series/list 100 rows default 50; Weight input 2000, Garmin candidates 2000. |
| `health-chat-sleep-evidence-v1` | Exact-source Sleep | Unchanged source-range cells/roles | Exact 7/30; at least one provider; 400/provider and 200/night. |
| `health-chat-sleep-provenance-v1` | Sleep provenance | Recursive timing/quality references | No arbitrary source-evidence body. |
| `health-chat-activity-evidence-v1` | Activity + optional Context | Five accepted summary cells | Exact 7/30/explicit Garmin source; shared summary budgets in 3.12. |
| `health-chat-activity-provenance-v1` | Activity provenance | Source/reducer/coverage identity | No per-workout detail in standalone aggregate. |
| `health-chat-activity-temporal-evidence-v1` | Combined Activity timing | Saved date/proven start | 4096 candidates/200 sessions; incomplete gives null sessions/counts without affecting five cells. |

Sleep/Activity requests use `end_date`, integer days 7/30 (not bool), start end−(days−1), reject
underflow/date.max; requested/effective equal, no clipping. IDs must be nonblank within 36 chars, exist
in correct provider before domain read. Existing source with empty period is valid. All exact IDs
validate in the shared snapshot first. Sleep allows optional explicit Google auto-selection; omission
omits provider. Equal windows do not prove shared timezone/causal alignment. Activity timing start
states: absent/date_only/local/instant/ambiguous; proven leaves
startTimeGMT/startTimeLocal/startTimeUTC/startTime, not generic timestamp. End always
`not_persisted_in_activity_contract`; no duration-made endpoint.

<a id="combined-versions"></a>
### Combined versions and selected metrics

`CombinedEvidenceRequest`: end_date/days/activity_garmin_source_id; optional
sleep_garmin_source_id/sleep_google_source_id/sleep_google_auto_select;
include_context=True/context_limit=50; projection=detailed|compact;
stress_garmin_source_id/body_battery_garmin_source_id;
hrv_garmin_source_id/hrv_google_source_id/rhr_garmin_source_id/rhr_google_source_id/
rhr_google_auto_select; steps_garmin_source_id/steps_google_source_id; include_weight=False;
steps_view=observed|completed (default observed);
include_context_recovery/include_sleep_regularity=False; context_pairing_hours=24; sleep_day_types=();
context_event_revisions=None. Metric sources are independent, no Sleep/Activity fallback. Context reads
once. Exact override wins over auto. Domain _assemble hooks share one physical snapshot. Top level
retains version/provenance/clocks/profile/privacy/request/sources/
snapshot/limits/sections/interpretation/envelope_hash.

| Version (detailed / compact) | Selected boundary | Preserves | Limitations |
| --- | --- | --- | --- |
| `health-chat-combined-evidence-v1` / `health-chat-combined-compact-evidence-v1` | Sleep/Activity/current Context | Base shapes/hashes/defaults | Exact 7/30 and shared 2 MiB caps. |
| `health-chat-combined-evidence-v2` / `health-chat-combined-compact-evidence-v2` | Stress and/or Body Battery | Existing daily means/saved maxima | No baseline export or full-day peak proof. |
| `health-chat-combined-evidence-v3` / `health-chat-combined-compact-evidence-v3` | HRV and/or RHR | Source-specific vitals | Weekly Garmin HRV is not Google daily HRV. |
| `health-chat-combined-evidence-v4` / `health-chat-combined-compact-evidence-v4` | Observed Garmin Steps and/or Weight | Saved observations/confirmed overlay | Not all overlay points canonical; no Steps aggregate. |
| `health-chat-combined-evidence-v5` / `health-chat-combined-compact-evidence-v5` | Explicit completed Steps | Latest proved completed acquisition | Exact Steps source required; no requested-window shift. |
| `health-chat-combined-evidence-v6` / `health-chat-combined-compact-evidence-v6` | Context recovery/regularity | Existing partitioned analyses | 3.12 timing/sample gates unchanged. |
| `health-chat-combined-evidence-v7` / `health-chat-combined-compact-evidence-v7` | Saved Google Steps | Closed exact-family reader projection | Incomplete search rejects packet; no aggregate. |
| `health-chat-combined-evidence-v8` / `health-chat-combined-compact-evidence-v8` | Selected Context revisions | Chosen set/other observed context | Requires context recovery; stale/missing pair fails whole packet. |
| `compact-sleep-evidence-v3` | Nested compact Sleep schema | Lossless quality/session registries | Stage segment detail summarized, not reconstructable. |

Selection precedence follows ascending table version: later selected boundaries win, while including
earlier requested sections. Omitted options retain previous shapes/hashes. Source versions and optional
section projections remain explicit:

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `health-chat-combined-provenance-v1` | Combined provenance | Nested reader/source versions | No separate acquisition proof. |
| `health-chat-combined-selected-metrics-v1` | Stress/Body Battery | Accepted reader facts | No new calculation. |
| `health-chat-combined-vitals-v1` | HRV/RHR | Source-specific dates/states | No daily/weekly equivalence. |
| `health-chat-combined-weight-v1` | Weight | Overlay/canonical/coverage facts | No inferred measurements. |

Stress cap 2000 candidates rejects `stress_selected_points_exceed_max`. Body Battery retains
100000/window/10000/day and exact `mean_exact`/decimal-string `mean_value`; incomplete daily
counts/missing dates stay null. Missing day means no eligible value, not collection failure; excluded
days are a subset. Garmin HRV caps 4096 metrics/256 per date, no mean; Google daily HRV 4096 before
projection. RHR retains 32-source/4096-source/256-date bounds/rational mean. Weight input 2000/series
100; overfull rejects `weight_selected_points_exceed_max`, no prefix. Export Weight cadence fixed 7
days, independent of runtime settings. Observed/completed Steps incomplete rejects
`steps_search_incomplete`; v5 discloses
requested_day_count/completed_day_count/excluded_uncompleted_day_count/ effective_completed_range;
completion is calendar count, not acquisition coverage.

<a id="compact-projection"></a>

Compact changes only Sleep representation. summary_record_id replaces duplicate summary. Overlay
per-cell evidence on evidence_common; field_paths_index resolves session-local field_path_sets.
interval_summary keeps counts/groups and SHA-256 of `{interval_ids,interval_snapshots}`, omitting
detailed stage segments. session_intervals_index resolves session_interval_sets; quality_inputs_index
resolves quality_input_sets after overlay. Registries intern exact canonical JSON including numeric
types, never cross sessions/sources. Native endpoints/quality validation survive losslessly. Older
compact v2 has endpoint registry/inline quality; undiscriminated packets retain original inline form.
Hash binds all indices. All other domains remain identical to detailed, not truncated to fit.

<a id="assistant-mcp"></a>
### Assistant, MCP and report delivery

Local assistant request is only end_date/days 7|30. Trusted operator binding fixes physical
profile/classification/code/dependency/interpreter/schema/evaluation zone/ exact sources. Preflight
rechecks compatibility, not authentication. It fixes compact observed semantics, including bound Google
Steps, without auto-choice or retry. Complete packet freezes before sampled digest (at most 3
observations); request cap 256 bytes, binding 16 KiB, digest 64 KiB, Context 50. Consumers must validate
entire output frame/byte length/hash/request agreement via validate_complete_output; prefix/truncated
stdout is refusal, not evidence.

| Version | Where used | Preserves | Limitations |
| --- | --- | --- | --- |
| `health-assistant-period-read-v1` | Bound local reader | Fixed-profile 7/30 snapshot | No transport/startup/provider call. |
| `health-assistant-period-output-v1` | Framed output | Complete packet/digest integrity | Complete serialization is not complete collection. |
| `health-assistant-period-mcp-v1` | Bound MCP result | Complete packet plus validated frame | Entire wire cap includes duplicated text/structure. |
| `health-weekly-digest-v2` | Weekly adapter | Compact packet including Weight/text/hash | Explicit Sunday seven-date read; no scheduler in adapter. |

| MCP mode | Tool | Data | Period | Access |
| --- | --- | --- | --- | --- |
| Default | get_period_evidence(start,end,domains) | Weight/current Context only | 1–90 dates | Trusted startup profile/kind/zone/rows/cadence; Owner gateway required. |
| Optional weekly config | get_weekly_digest_evidence(week_end) | Configured compact combined/Weight | Seven dates ending explicit Sunday | Python config exact sources/view; same authenticated gateway. |
| assistant_period / --assistant-binding | read_assistant_period(end_date,days) | Bound source domains/full packet/frame | 7/30 | Exclusive of legacy/weekly tools; binding cannot be overridden by request/startup profile flags. |

MCP loopback `/mcp` is stateless Streamable HTTP JSON initialize/ping/notifications/ tools/list/call,
protocol 2025-06-18. First initialize may omit header; subsequent POST requires MCP-Protocol-Version.
GET/DELETE 405, no batches/SSE/session store. Body cap 8 KiB; one read at a time, overlap 429
evidence_busy. Entire serialized HTTP result including text/structuredContent/escaping is 2 MiB;
oversize refuses, never splits/digest-only succeeds. Host localhost/127.0.0.1; Origin absent for server
clients or exact configured allowlist. No access/content logs/forwarded trust; no-store responses.

Both Owner kinds require HEALTHCHECK_MCP_GATEWAY_TOKEN, at least 32 non-whitespace ASCII characters,
checked before protocol/discovery/read. Internal bearer is not a ChatGPT API key. Existing OAuth gateway
must authenticate only Owner, validate issuer/signature/resource-audience/expiry/health.evidence:read
every request, publish OAuth metadata/challenges, support authorization-code/PKCE, replace external
Authorization with internal bearer, forward only MCP/required metadata and permit revocation without
content logging. Loopback/tunnel/profile label does not replace authorization. Facade supplies no OAuth
issuer/gateway/tunnel/live connection.
[Connection procedure](OWNER_OPERATIONS.md#assistant-period-mcp-setup) owns setup.

<a id="weekly-digest"></a>

Weekly adapter fixes exact source/view config, compact, seven dates ending explicit Sunday; no
Context/previous-period comparison. It includes Weight latest saved daily median/date or unavailable, no
new weekly rate. Envelope retains intended Sunday 20:00 Europe/Moscow target, actual as-of,
unfinished-Sunday/late-read flags, unknown collection freshness and digest_hash. Schedule is external,
not embedded automation. Delayed reads may include later acquisitions, not time travel. Steps report
observed dates/latest usable value, not total/mean; Sleep uses eligible durations without new mean. New
reads require new revision; retries render the same frozen packet without reading/recalculating.
Ordinary Overview has no preview trigger. Implemented adapters do not prove authenticated ChatGPT
connectivity. Monthly/annual delivery is future scope; report revisions/renderers/delivery attempts must
remain distinct, with no silent recomputation on failed send.
