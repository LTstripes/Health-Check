# Decisions and Open Questions

R00 turns earlier hypotheses into decisions or explicit `UNVERIFIED` items. An implementation PR may refine mechanics after a live spike, but it must not silently change these invariants.

## Final decisions

### Product and sequence

- Health-Check is a single-user personal health observatory on a Windows laptop.
- Dashboard and AI are equal product interfaces over one deterministic evidence layer.
- Priority is weight/body composition, then sleep, activity/fitness, then recovery/wellbeing.
- R01 is the Weight & Body Composition vertical slice plus the reusable core. Garmin-first is rejected because it delays the highest-priority unique value while Garmin Connect already covers daily Garmin viewing.
- R01 includes a minimal dashboard and both Xiaomi historical/live contracts; it excludes Garmin, Fitbit, Recovery Score, and full notifications.

### Runtime

- Python 3.12+, FastAPI, SQLite WAL, SQLAlchemy/Alembic, and simple Windows-first operation.
- One local codebase/database, a loopback UI/read/import listener, and an optional separate LAN ingest-only listener/process plus idempotent scheduled commands; no queue/broker/enterprise deployment.
- Runtime data/artifacts/secrets live outside Git under a user-scoped data directory.
- Windows Task Scheduler is the default automation host.

### Data and provenance

- Raw evidence, typed source data, canonical selection, derived analytics, and LLM narrative are separate layers.
- Preserve competing source values and historical revisions.
- Canonical rules and derived algorithms are versioned/reproducible.
- Physical device, provider/input method, and measurement algorithm are separate identities.
- Sleep, stages, activities, intraday series, and context intervals use typed entities rather than one generic EAV table.
- Missing/unavailable/unknown is never stored or reported as zero.

### Xiaomi S400

- Preferred live path: S400 → openScale → openScale-sync generic webhook → Health-Check.
- openScale/openScale-sync remain external GPL-3.0 applications.
- Webhook is the preferred live acquisition path for the pinned/current contracts because it preserves materially more S400/openScale evidence. This is a transport choice, not a claim that it is canonical truth. Dual-ingesting both paths is forbidden without deterministic deduplication.
- Xiaomi-app and openScale body-composition algorithms are distinct non-equivalent groups. No crosswalk/calibration exists until an actual overlap study supports a versioned rule.
- Historical application name/version is evidence-based; unknown is recorded as unknown. Do not assume Mi Fitness when official S400 material points to Xiaomi Home/Mi Home.
- Photo extraction creates candidates only; human confirmation is distinct from nullable per-field model confidence.
- openScale-sync insert/update upserts by stable configured sender-instance UUID, user ID, and measurement ID; credential rotation does not change that UUID. A mixed-validity batch durably commits valid items and quarantines invalid items before acknowledging. Delete/clear create tombstones; raw history is not physically deleted.
- `values[]` presence is authoritative because missing convenience values may appear as numeric zero.

### Weight/body composition analytics

- R01 display trend: daily-median, time-aware EWMA with a 21-day half-life.
- R01 rate: Theil–Sen slope over the trailing 90 days, requiring at least six observations spanning 42 days.
- Estimated fat/lean mass uses same-session weight/body-fat inputs and an explicit Health-Check algorithm version.
- Muscle and lean mass are distinct labels.
- Recomposition is shown as compatible evidence; R01 does not classify tiny BIA changes as real tissue change.
- Kalman, LOESS, and STL are not R01 defaults.

### Garmin

- R02 uses pinned `python-garminconnect` `0.3.12`; it does not build another Garmin HTTP client.
- Current `python-garminconnect` no longer depends on deprecated `garth`.
- Only read/download methods are allowlisted. Sign-in/MFA is user-assisted; credential state needs Windows-appropriate protection.
- Garmin sync uses raw retention, idempotency, per-stream coverage, and an explicit trailing reconciliation window.
- Client endpoint existence is never treated as device capability.
- Vivoactive 5 Recovery Time is available on the watch but is not promised through Garmin Connect/API for a sole-Vivoactive-5 account.
- Training Readiness, Training Status, Training Effect, and Acute Load are not treated as Vivoactive 5-produced metrics merely because client schemas expose fields.

### Google Fitbit / OAuth

- R04 targets Google Health API v4, not legacy Google Fit or the retiring Fitbit Web API.
- Request only implemented read scopes; partial consent is a stream capability state.
- Preserve raw `list` source metadata separately from reconcile/rollup results. `google-wearables`, `google-sources`, and `all-sources` are distinct families; ambiguous family aggregates are never labelled as Fitbit-device evidence or used for Garmin/Fitbit device agreement.
- One-user automation uses an External, In-production project under the personal-use/unverified exception; the separate 100-user unverified-app audience cap is not the exception definition. The client is Desktop with system browser, random loopback callback, PKCE S256, validated one-use state, offline access, and a securely stored refresh token.
- Testing publishing status is rejected for routine automation because its refresh token expires after seven days.
- Installed-app incremental authorization is not assumed. Scope changes trigger deliberate reauthorization with the complete set.
- Proprietary Fitbit Sleep Score/Readiness is not exposed by the documented APIs reviewed in R00. Any local/adapted score has a Health-Check/fettle algorithm identity, never a Fitbit/provider identity.
- fettle OAuth/store are not copied directly; selected Google client/sync/sleep/test semantics are adapted.

### Time, coverage, and agreement

- Store UTC instant plus original local time/offset/zone where available; preserve date-only precision.
- Sleep belongs to its local wake date.
- Lag direction is explicit; an evening-X exposure aligns to wake-date-X+1 sleep and morning-X+1 HRV.
- Coverage is first-class and accompanies analytics/reports.
- Garmin/Fitbit first exploratory agreement report requires 14 paired nights; a provisional canonical-source decision requires 42 paired nights across at least six weeks plus stability/coverage checks.
- Agreement uses paired bias/differences, MAE, RMSE, Bland–Altman or robust limits, with correlation secondary. Vendor scores are not treated as equivalent measurements.

### Context, AI, reports, and recovery

- Context is raw free text plus an event/exposure interval and optional suggested/confirmed tags; no mandatory daily diary.
- Context analysis uses event-aligned/matched-control methods, not a sparse yearly boolean Pearson shortcut.
- LLM access is typed, bounded, and read-only through application analytics services. The MCP credential cannot mutate settings/imports/context or read raw/config/secret tables.
- Generic SQL is not a default interface. A future expert mode has a separate read-only database connection, allowlisted views, AST/authorizer and hard limits.
- A report is computed once, persisted as a versioned evidence packet, then rendered/delivered to dashboard, Telegram, and email.
- A custom Recovery Score is deferred until accumulated personal data demonstrates a missing decision need.

### License

- Health-Check uses the MIT License from this branch onward.
- `python-garminconnect` is a direct MIT dependency.
- MIT/BSD donor code is selective, attributed, and pinned; donor notices/copyright obligations remain applicable when code is incorporated.
- openScale/openScale-sync are external GPL components; VitaSync is AGPL reference-only; unlicensed `garmin_ai` is reference-only.

## `UNVERIFIED` live items

These are not architecture gaps; they are explicit acceptance probes for the owning release.

### Xiaomi / R01

- Owner's installed openScale/openScale-sync versions, S400 MAC/bind-key flow, profile inputs, bone/BMR choices, and phone-log handling.
- Real phone-to-laptop webhook envelope and LAN reliability with the installed build.
- Exact Xiaomi app/version/algorithm behind each historical screenshot.
- Any numeric Xiaomi/openScale calibration. It must remain absent until paired evidence exists.
- Whether openScale reliability/timeout information can be recovered outside the current persisted/exported record.

### Garmin / R02–R03

- Owner-region MFA/login behavior, endpoint retention depth, rate limits, and payload stability.
- Exact nap intervals in owner payloads.
- Vivoactive 5 `recovery_time` in downloaded ORIGINAL FIT.
- Empty/non-empty account fields for Training Readiness/Status/Effect/Load when Vivoactive 5 is the only compatible producer.
- Cycling power/advanced dynamics fields for this device/accessory setup.
- Windows at-rest protection behavior chosen for Garmin auth state.

### Google Fitbit / R04

- Successful owner-project Google Health v4 enablement and the exact live data types populated by Fitbit Air.
- Long-lived refresh behavior over more than seven days in the owner's In-production personal-use project.
- Verification/audience policy behavior at implementation time; Google policy is external and may change.
- Live sleep-stage/HRV/RHR/SpO2 semantics and backfill depth for the owner account.

### Agreement / later releases

- Whether Fitbit should become canonical for any sleep metric; only paired data can decide.
- Firmware/app/algorithm change points that require separate agreement epochs.
- Travel/timezone edge cases observed in real history.

## Deferred owner choices

1. **Email transport.** Pick SMTP/application password or a provider API in R07 based on the owner's account and Windows reliability.
2. **External AI provider/deployment.** The evidence-packet/tool contract is provider-neutral; select a model/provider when the AI release begins.
3. **Recovery Score.** Decide only after R05+ data and a written unmet use case.
4. **Advanced remote access.** Keep loopback/local by default; design remote MCP/API exposure only with an explicit threat model and need.

## Change protocol

Any change to an architecture invariant must cite new primary evidence, identify affected releases/data migrations, and update the R00 audit or add an ADR. A donor README, a method name, or a plausible model answer is not sufficient.
