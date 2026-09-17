# Decisions and Open Questions

This file contains current architecture/product decisions plus only those `UNVERIFIED` items that still matter after released R01–R05 evidence. Historical decision archaeology remains in release issues, audits and Git history.

## Final decisions

### Product and release sequence

- Health-Check is a single-user personal health observatory on a Windows laptop.
- Dashboard and AI are equal product interfaces over one deterministic evidence layer.
- Priority remains weight/body composition → sleep → activity/fitness → recovery/wellbeing.
- R01, R02, R03, R04 and R05 are released to canonical `main`.
- R05 closed with exploratory sleep agreement; Garmin remains canonical/default; #105 deferred/NOT_ELIGIBLE.
- #119 deterministic period brief v1 is completed on canonical main; current bounded product focus is #127 Period Brief local UI v1.
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

- Preferred live path remains S400 → openScale → openScale-sync webhook → Health-Check.
- openScale/openScale-sync remain external GPL applications.
- Xiaomi-app and openScale body-composition algorithms remain distinct compatibility groups until actual paired evidence supports a versioned calibration.
- Historical image extraction creates candidates; human confirmation remains distinct from model confidence.

### Garmin / R02–R03

- Garmin uses the pinned `python-garminconnect` dependency; no second Garmin HTTP client.
- Protected owner-assisted auth/session state remains outside Git.
- Only reviewed read/download semantics are permitted; method existence never proves Vivoactive 5 capability.
- Garmin ingestion preserves raw/observation/current provenance, explicit coverage and separated incremental/historical checkpoints.
- Current collection reconciliation is deterministic under accepted authoritative/partial semantics; parser/reconciliation upgrades are explicit and version-aware.
- R03 analytics consume reviewed metric/time identities and immutable evidence manifests; UI does not reimplement statistics.
- Garmin-native scores remain provider-native and are not relabelled as a Health-Check readiness/recovery score.

Post-R04 maintenance #98 completed the bounded `python-garminconnect` 0.3.12 → 0.3.15 upgrade. It was maintenance, not an R04/R05 semantic dependency. #99 Google auth/sync test hardening is also closed completed.

### Google Health / R04

R04 is released. Current accepted contract:

- Google Health API v4 only; no new legacy Fitbit Web API implementation.
- OAuth uses a **Web Application / Web Server** client with a fixed exactly registered loopback callback.
- Client secret/token/session material stays outside Git in the external owner runtime and uses Windows user-scoped DPAPI protection.
- Exactly two read scopes are requested in R04: sleep read-only and health metrics/measurements read-only.
- Owner Google Auth Platform is `In production`, External; fresh protected re-consent and immediate session reuse were proven.
- `list`, `reconcile`, `rollUp`, `dailyRollUp` and `dataSourceFamily` are acquisition/query context, not stable source identity.
- `google-wearables` includes more than one possible Google wearable class and is **not** automatic Fitbit-device proof.
- Explicit persisted provider/device metadata is required for a physical-device claim.
- Raw/list source metadata stays separate from family aggregate/reconciled/rollup results.
- Planned R04 types are sleep, heart rate, HRV/daily HRV, daily resting HR, SpO2/daily SpO2, respiratory-rate sleep summary and daily respiratory rate.
- Pagination follows `nextPageToken`; sleep page size is bounded; time windows are inclusive-lower / exclusive-upper; undocumented list ordering is never assumed.
- Historical/incremental/refresh namespaces are distinct.
- Exact completed-window rerun may skip the provider entirely when coverage proves no work remains.
- Explicit bounded refresh may re-fetch completed coverage to discover provider corrections while preserving immutable prior evidence.
- Missing/null/zero/confirmed-empty remain distinct.
- Unknown provider shapes remain fail-closed.

#### Live terminal-envelope decision from #110

Live owner evidence proved one terminal HTTP-200 LIST shape where the top-level object omitted both `dataPoints` and `nextPageToken`. Under current ProtoJSON semantics, an empty repeated field may be omitted.

Accepted repair is intentionally narrow:

- LIST/RECONCILE + **missing collection** + **no usable next-page token** => complete empty terminal page;
- missing collection + usable token continues pagination;
- array collection behaves under normal complete/continue rules;
- `null`, object, string, number, boolean or other malformed collection shapes remain invalid/fail-closed;
- rollup shapes are not broadened by this repair.

The live repaired window completed and its exact rerun made 0 provider calls.

### R05 agreement / canonical sleep

Frozen design from #97:

- sleep is paired by local wake date;
- one main overnight session per source/date; naps excluded from overnight pairing;
- ambiguous multiple-main sessions fail closed;
- `device_pair` requires explicit persisted physical/provider metadata sufficient to qualify the intended Fitbit device/source;
- `family_pair` from `google_wearables_family` is exploratory only and cannot drive a canonical-source switch;
- manual Google-edited evidence may be exploratory but is excluded from the strong 42-night canonical gate;
- comparable sleep metrics are projected separately; provider scores are display-only and are not compared as equivalent measurements;
- difference convention: `google - garmin`;
- agreement statistics: N, bias, MAE, RMSE, Bland–Altman limits and robust summaries; association is secondary;
- exploratory gate: 14 paired nights;
- provisional canonical-source decision: 42 valid `device_pair` nights across at least six weeks plus coverage/stability checks;
- canonical default remains Garmin until a reviewed versioned per-metric rule explicitly changes it;
- no automatic canonical switch from N, correlation or coverage alone;
- R05 may close successfully without a canonical-source change if the evidence is still insufficient.

### Time, coverage and agreement

- Store UTC instant when valid plus original local time/offset/zone when available; preserve date-only/local-only precision rather than inventing UTC.
- Sleep belongs to its local wake date.
- Lag direction is explicit.
- Coverage accompanies every non-trivial analytic/report result.
- Associations are exploratory and never causal/medical claims.

### AI / reports / context

- LLM access is typed, bounded and read-only through application analytics services.
- Generic unrestricted SQL is not the default AI interface.
- Reports are computed from deterministic/versioned evidence before rendering/delivery.
- Context is a raw free-text event/exposure interval with optional suggested/confirmed tags; no mandatory daily diary.

### License

- Health-Check is MIT.
- `python-garminconnect` is an MIT dependency.
- External GPL/AGPL projects remain external/reference-only unless their licensing obligations are explicitly accepted.
- Donor code/pattern reuse is pinned and reviewed at exact source versions.

## Remaining `UNVERIFIED` / open observations

These are observational gaps, not reasons to rewrite released architecture.

### Xiaomi / R01

- Real owner phone-to-laptop openScale/openScale-sync reliability across long routine operation remains only partially owner-observed.
- Exact algorithm/application identity behind every historical screenshot may remain unknown where the screenshot itself does not prove it.
- No Xiaomi↔openScale numeric body-composition calibration exists without paired evidence.

### Garmin / R02–R03

- MFA-specific branch behavior if a future login actually triggers MFA.
- Longer-term provider payload-shape drift and retention boundaries beyond released owner evidence.
- Recovery Time / some advanced activity/device fields remain intentionally outside released claims unless separately proven.
- #98 completed the pinned upgrade to `python-garminconnect` 0.3.15; further upstream drift remains observational maintenance, not residual #98 backlog.

### Google Health / R04

- Refresh-token durability across a long elapsed interval remains observationally `UNVERIFIED`; immediate protected reuse/refresh and In-Production status are proven.
- Longer-term provider late-correction frequency/policy remains observational rather than assumed.
- Exact physical-device attribution may differ per record/surface; R05 must inspect persisted metadata rather than promote family membership.
- Provider policy/documentation may evolve and must be re-read when behavior or scopes materially change.

### R05 / agreement (post-closeout)

- Live provider-attribution evidence was insufficient for a canonical switch; Garmin remains default.
- Strict legacy `device_pair` / `family_pair` remain fail-closed.
- `account_wearables_sleep_observations_v1` is exploratory/uncertain-only and never canonical-eligible.
- #105 remains deferred / NOT_ELIGIBLE until stronger explicit device-pair evidence exists; it is not an actionable next implementation merely because it is open, and no Owner action is required unless future live evidence meets its gate.
- Firmware/app/algorithm change points may still require separate agreement epochs if evidence later accumulates.

## Deferred owner choices

1. **Email transport:** choose SMTP/application password vs provider API in R07.
2. **External AI provider/deployment:** choose when the typed AI release begins.
3. **Recovery Score:** decide only after R05+ evidence demonstrates a concrete need.
4. **Advanced remote access:** remain local/loopback by default until a threat model and need exist.

## Change protocol

Any change to an architecture invariant must cite new primary evidence, identify affected releases/migrations and update the owning contract/ADR. A donor README, method name or plausible model answer is not sufficient evidence.