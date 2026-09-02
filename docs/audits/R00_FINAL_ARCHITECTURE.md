# R00 Final Technical Architecture Review

- Review date: **2026-09-02**
- Health-Check baseline: `2ff87de963f022dfdbfb4960276b09635888501a`
- Review branch: `r00/final-architecture-sol`
- Scope: documentation and architecture only; no product implementation

`UNVERIFIED` means that the reviewed source/documentation cannot establish the fact and a live owner/device/account check is still required.

## Executive Decision

Build a clean, small Health-Check core rather than forking any donor product. The Windows runtime is Python 3.12+, FastAPI, SQLite WAL, deterministic Python/SQL analytics, a local artifact store, and Windows Task Scheduler. Android openScale/openScale-sync remain external components.

R01 is **Weight & Body Composition**, not Garmin-first. It delivers the core and a useful vertical slice: confirmed historical photo import, the openScale-sync webhook contract, source/canonical/coverage models, conservative weight/composition analytics, and a minimal dashboard. This directly serves priority #1 and existing S400 history while keeping later Garmin/Fitbit additions schema-compatible.

The central invariant is stronger than “keep provenance”: a physical device, acquisition provider/input method, and measurement algorithm are independent identities. Xiaomi-app S400 composition and openScale S400 composition are not one continuous series. Both remain available; calibration waits for a real overlap study.

No donor becomes the product base. `python-garminconnect` is a future direct dependency. `garmin-stats-ai`, fettle, healthquery, and open-wearables are selective donors. openScale/openScale-sync are external GPL applications. VitaSync and unlicensed `garmin_ai` are reference-only.

## Product Constraints

- One user, one Windows laptop, several personal devices.
- Priority: weight/body composition → sleep → activity/fitness → recovery/wellbeing.
- Dashboard and conversational AI are equal interfaces over the same deterministic evidence.
- Weekly Sunday, month-end, and annual reports; no daily report priority.
- Dashboard and Telegram capture free-text life context; no mandatory structured diary.
- Consumer devices/BIA are not diagnostic instruments.
- Association is not causation; a model narrative is not a calculation source.
- Local-first means simple/reproducible ownership, not a ban on explicitly selected external LLM use.
- Real health data, screenshots, raw payloads, databases, tokens, and documents never enter Git.

## Verified Repository Snapshots

Pins were read from current repository refs and source was inspected at the full SHA on 2026-09-02.

| Repository | Full inspected SHA | Release/ref | License verified at pin | Key scope inspected |
|---|---|---|---|---|
| Health-Check | `2ff87de963f022dfdbfb4960276b09635888501a` | `main` baseline | None present | All six documentation files |
| [python-garminconnect](https://github.com/cyberjunky/python-garminconnect/tree/981d150caeda7d632224a75f3895c08df27a2a34) | `981d150caeda7d632224a75f3895c08df27a2a34` | `0.3.12`, also HEAD | [MIT](https://raw.githubusercontent.com/cyberjunky/python-garminconnect/981d150caeda7d632224a75f3895c08df27a2a34/LICENSE) | auth/MFA/tokens, health/activity endpoints, typed payloads |
| [garth](https://github.com/matin/garth/tree/f99159a15c4c9463ce215a60ba9f7cb21f94a3b7) | `f99159a15c4c9463ce215a60ba9f7cb21f94a3b7` | final `v0.8.0` | Not relied on | Deprecation/new-login status |
| [garmin-stats-ai](https://github.com/dandwhelan/garmin-stats-ai/tree/936974ac8c78781e7d0075040f459ea7676b3819) | `936974ac8c78781e7d0075040f459ea7676b3819` | HEAD; no tag | [MIT](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/LICENSE); nested `garmin-grafana/` BSD-3-Clause | fetch/transforms/storage, stats/lag/experiments, activity/scales/tests |
| [fettle](https://github.com/Deekshith-Dade/fettle/tree/82929df268124f0a3470b180adbbbeb0802d03cd) | `82929df268124f0a3470b180adbbbeb0802d03cd` | HEAD | [MIT](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/LICENSE) | Google auth/client/sync/store, sleep/readiness/insights/MCP/tests |
| [healthquery](https://github.com/nikira-studio/healthquery/tree/f175148f67cb954fc4db2e026e497984dfccac29) | `f175148f67cb954fc4db2e026e497984dfccac29` | HEAD | [MIT](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/LICENSE) | batches/migrations, auth routes, SQL guard, MCP/database/config |
| [garmin_ai](https://github.com/TolmachevKirill/garmin_ai/tree/ca6d298cc4a7e4e95e036c76dce69d211a47aeee) | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee` | HEAD | **UNVERIFIED**; no LICENSE/COPYING in tree | raw/FIT, Windows/Telegram/MCP patterns |
| [openScale](https://github.com/oliexdev/openScale/tree/6613db5838e4674a19652441073f82b3ee3d7009) | `6613db5838e4674a19652441073f82b3ee3d7009` | HEAD; S400 blobs also stable `v3.1.2` | [GPL-3.0](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/LICENSE) | S400 handler/decryption/aggregation/composition/persistence |
| [openScale-sync](https://github.com/oliexdev/openScale-sync/tree/32e38651cf78bbf230e33d17abb00b147130f305) | `32e38651cf78bbf230e33d17abb00b147130f305` | HEAD, one unreleased commit after `v0.6.2` | [GPL-3.0](https://github.com/oliexdev/openScale-sync/blob/32e38651cf78bbf230e33d17abb00b147130f305/LICENSE) | webhook/Health Connect, ledger/retry/full sync |
| [open-wearables](https://github.com/the-momentum/open-wearables/tree/72351e24de045e87da4fe4fd86142494e304e17b) | `72351e24de045e87da4fe4fd86142494e304e17b` | HEAD | MIT | Google v4 provider flow, normalized model, bounded MCP |
| [VitaSync](https://github.com/biosync-io/vitasync/tree/f299cd134edea8effca9ac52436fc83d439792b6) | `f299cd134edea8effca9ac52436fc83d439792b6` | HEAD | [AGPL-3.0](https://raw.githubusercontent.com/biosync-io/vitasync/f299cd134edea8effca9ac52436fc83d439792b6/LICENSE) | provider/MCP/sync/token/platform architecture |

### Key external documentation checked

- Garmin Vivoactive 5 [manual](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-97EA1540-A780-480F-BA4D-9A9E147FB225.html), [product comparison](https://www.garmin.com/en-US/compare/?compareProduct=1057989&compareProduct=886689), [Recovery Time](https://support.garmin.com/en-US/?faq=8ImmxVkZMh4EYYq5Zp2bR8), [Training Status](https://support.garmin.com/en-US/?faq=VxKazDQ2mkAmDoQbJriEBA), and [Unified Training Status](https://support.garmin.com/en-US/?faq=EjPECQK58qA0xzJ5X74vm7).
- Google Health [overview](https://developers.google.com/health), [REST v4](https://developers.google.com/health/reference/rest), [setup](https://developers.google.com/health/setup), [scopes](https://developers.google.com/health/scopes), [filters](https://developers.google.com/health/filters), [data types](https://developers.google.com/health/data-types), [migration/access](https://developers.google.com/health/migration/data-access), and Google OAuth [native-app](https://developers.google.com/identity/protocols/oauth2/native-app), [best practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices), and [restricted-scope personal-use exception](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).
- Fitbit legacy sleep API statement that Sleep Score is not exposed: [Get Sleep Log by Date](https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/).
- Xiaomi [S400 product page](https://www.mi.com/global/product/xiaomi-body-composition-scale-s400/) and [algorithm-change FAQ](https://www.mi.com/global/support/faq/details/KA-235535/).
- Android Health Connect [data types](https://developer.android.com/health-and-fitness/health-connect/data-types) and [`Metadata`](https://developer.android.com/reference/androidx/health/connect/client/records/metadata/Metadata).

## Final Donor Classification

| Donor | DIRECT | ADAPT | REFERENCE | IGNORE |
|---|---|---|---|---|
| python-garminconnect | R02 pinned dependency | Health-Check wrapper/provenance/sync policy | Raw endpoint behavior | Write methods; assumptions from method existence |
| garmin-stats-ai | Only `stats_utils.py::{pearson_r_p, benjamini_hochberg, finalize_correlations}` plus exact focused tests after license gate | Exact transforms/fetch/analysis/query semantics and fixtures listed in the reuse map | Proactive/cache and `scales/{base,registry}.py` shapes/tests | garth logic, agent/deploy/write paths, `scales/{lefu,composition}.py` and scale vectors as S400 evidence |
| fettle | None at module level | Google v4 registry/client/chunking, per-stream sync, sleep parsing, typed tools/tests | Local readiness/sleep/insight ideas | OAuth/store direct transfer, homemade scores, Matter/macOS/coach/UI product |
| healthquery | None wholesale | Raw batch/replay, migrations, typed MCP shapes | Token separation concept | Generic SQL and current route capability model |
| open-wearables | None wholesale | Typed MCP-over-API, bounded time-series tools, provider registry/chunking/source attribution | Canonical/provider architecture | SaaS/Celery/Postgres/Redis/S3 and unsafe derived physiology |
| openScale/openScale-sync | External process/interface only | Receiver contract implemented independently | S400 semantics and fixtures | Any GPL code incorporation |
| garmin_ai | None | None until licensed | Windows/raw/FIT/Telegram/HITL ideas | Code copying and raw-math-by-LLM posture |
| VitaSync | None | None | Token/sync/typed-MCP/platform comparisons | AGPL code and multi-tenant infrastructure |

The expanded reuse map and inspected source paths are in [REFERENCE_PROJECTS.md](../REFERENCE_PROJECTS.md).

## Final Runtime Architecture

Windows runs one Health-Check codebase and one SQLite database in WAL mode. A loopback-only UI/read/import ASGI listener and an optional separate private-LAN ingest-only listener/process share application services without sharing exposed routes or credentials. The LAN listener exposes only webhook plus non-sensitive liveness; HTTPS/encrypted overlay is preferred, while trusted-LAN HTTP is an explicit warned opt-in. Windows Task Scheduler invokes idempotent sync/report commands. A user-scoped artifact directory retains photos/raw JSON/FIT references. Secrets stay outside the repository and need Windows-appropriate at-rest protection.

Android runs stock openScale and openScale-sync. No Health-Check phone application or always-on cloud server is required. The system remains usable when external LLM/report delivery is unavailable.

## Data Flow by Provider

### Xiaomi

- Live: encrypted BLE broadcast → openScale → openScale-sync generic webhook → raw ingest event → source measurement.
- Historical/fallback: image → immutable local artifact → versioned extraction candidates → human confirmation → source measurement.
- Health Connect is a lossy standardized fallback; webhook is the preferred current acquisition path, not an automatically canonical truth.

### Garmin

- User-assisted native `python-garminconnect` login/MFA → protected reusable auth state.
- Per-stream historical windows and incremental/trailing reconciliation → raw response → typed scalar/sleep/activity/series records.
- Original FIT retained/referenced where it adds activity detail.

### Google Fitbit

- Owner OAuth through Google Health API v4 → per-type raw `list` plus explicit family reconcile/rollup fetch → raw response/query identity → typed source records.
- Partial consent and missing data types are explicit stream capability/coverage states.
- Preserve `dataSource` platform/device/recording-method metadata. `google-wearables`, `google-sources`, and `all-sources` outputs are not interchangeable; never label an all/google-sources aggregate as Fitbit-device data.

### Context

- Telegram/dashboard raw text → event/exposure interval → optional suggested/confirmed tags → event-aligned analytics.

## Canonical Data Model

The logical entities are:

1. Identity/provenance: providers, physical devices, acquisition sources, algorithms/configuration.
2. Immutable evidence: raw artifacts, ingest batches/events, provider sync runs.
3. Source semantics: scalar measurement sessions/values; sleep sessions/stages; activities/FIT detail; intraday series; context intervals; later lab documents/results.
4. Interpretation: derived measurements, canonical rule sets/runs/selections, coverage intervals.
5. Output: evidence packets, report revisions, renders, delivery attempts, later experiments.

A scalar metric/value table is allowed only for scalar/source values. Sleep, stages, activities, and series are not flattened into it. Confirmed corrections use superseding revisions. Canonical selection points to evidence and never overwrites it.

## Body Composition Algorithm Provenance

The P0 invariant is confirmed.

Current openScale S400 source receives weight, high/low impedance, and HR, then computes composition using public literature equations and profile inputs. It explicitly lacks Xiaomi proprietary calibration. The [S400 handler](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/scales/MiScaleS400Handler.kt#L237-L261) always uses the [S400 composition pipeline](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/libs/S400BodyComposition.kt#L26-L120); the openScale “original Xiaomi app” selector belongs to an [older mono-frequency handler](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/scales/MiScaleHandler.kt#L103-L117). Xiaomi documents its own dual-frequency algorithm and warns that algorithm changes affect trends. Therefore equivalence is disproven as an assumption; exact Xiaomi equations/crosswalk remain `UNVERIFIED`.

Each metric stores:

- physical scale instance;
- provider/input (`xiaomi_home`/unknown photo, `openscale` webhook);
- algorithm family/version/build/configuration;
- raw versus derived status;
- source reliability/quality if actually exported;
- input measurement IDs for Health-Check derivations.

Historical screenshot composition uses `xiaomi_home_s400_unknown_version` (or an evidenced app/build), never an invented version. Live openScale composition records the installed app/build and available bone/BMR/profile configuration. Weight can remain comparable when device/calibration identity supports it; composition does not cross algorithm groups. Calibration requires same-weigh-in overlap and an explicit versioned rule.

openScale internal `OK/APPROXIMATE/UNRELIABLE/NOT_AVAILABLE`, timeout, and label-swap flags are not currently propagated into its persisted/exported measurement. `OK` would not mean clinical accuracy even if it were available. This missing metadata remains visible as unknown.

## Sync & Idempotency

Every stream defines external ID/fingerprint, backfill, watermark/cursor, reconciliation window, and failure/coverage rules.

For the pinned [openScale-sync webhook contract](https://github.com/oliexdev/openScale-sync/blob/32e38651cf78bbf230e33d17abb00b147130f305/src/app/src/main/java/com/health/openscale/sync/core/sync/WebhookSync.kt#L17-L92):

- insert/update single records include `id`, `userId`, username, date, convenience fields, and optional typed `values[]`; batches use `measurements[]`;
- events also include delete, clear, and test;
- configured authorization is copied verbatim into the HTTP header, so configure a random `Bearer` credential;
- any 2xx is transport acknowledgement only;
- retry/outstanding ledger and [manual/periodic reconciliation](https://github.com/oliexdev/openScale-sync/blob/32e38651cf78bbf230e33d17abb00b147130f305/src/app/src/main/java/com/health/openscale/sync/core/service/ServiceInterface.kt#L503-L715) exist, but delivery is not exactly-once;
- missing convenience fields may appear as zero; only actual `values[]` presence establishes a measurement.

Health-Check uses a stable configured sender-instance UUID independent of its rotatable credential and upserts insert/update by `(source_instance, userId, id)`. Delete falls back to `(source_instance, userId, measured_at)`. Delete/clear create source tombstones and canonical recomputation, not physical history deletion. For a valid batch envelope, it durably stores the envelope, processes items with savepoints, commits valid items, quarantines invalid items with replayable diagnostics, and returns 2xx only after all outcomes are durable. Invalid auth/JSON/top-level envelope returns non-2xx. Lost-response replay deduplicates both valid and failed items.

Garmin/Google use provider IDs when present plus semantic fingerprints, raw retention, and explicit trailing windows. Receive time never substitutes for source time.

## Coverage Model

Coverage is a data contract, not UI decoration:

- request interval and actual covered interval;
- observed/expected count when cadence is meaningful;
- present, confirmed-empty, unavailable, unknown, and failed states;
- freshness and longest gaps;
- source/device/algorithm breakdown;
- exclusions and calculation-rule version.

Weight uses configurable weekly cadence; sleep uses expected nights; intraday streams use time/day coverage. Missing is not zero. Every report/evidence packet includes coverage facts. Analytics returns unavailable when its count/span gate fails.

## Time / Sleep / Lag Semantics

- Store UTC instant, original local time, UTC offset, and zone when available; preserve date-only precision.
- Key sleep to local wake date.
- Define lag direction in domain language. `exposure evening X -> sleep waking X+1` and `-> morning HRV X+1` is a next-day alignment.
- Adapt the donor's actual next-calendar-date join idea, not an ambiguous row shift.
- Defer advanced travel/timezone policy, but retain enough evidence for later reprocessing.

## Deterministic Analytics Architecture

Typed pure services compute trends, baselines, period comparisons, coverage, anomalies, activity comparisons, lagged associations, effect sizes, source agreement, and derived metrics. Every output carries input count/span, algorithm/rule version, provenance, exclusions, and unavailable reason.

LLMs receive bounded evidence packets and never perform raw time-series math. Health thresholds/formulas are not accepted merely because a donor implemented them. Current-day incomplete data and missing values are excluded explicitly, not coerced.

## Weight Analytics Decision

R01 display trend is daily-median time-aware EWMA with a **21-day half-life**:

```text
alpha_i = 1 - 2^(-delta_days / 21)
trend_i = alpha_i*x_i + (1-alpha_i)*trend_(i-1)
```

This is causal, simple, interpretable, and gap-aware for weekly/irregular observations. A constant per-observation alpha is rejected. Kalman/LOESS/STL add complexity or endpoint behavior not justified by 20–30 points.

Rate is trailing-90-day Theil–Sen median pairwise slope in kg/week, requiring at least six observations across 42 days. Raw points, input count, and span remain visible. Insufficient evidence returns unavailable.

## Body Composition Analytics

R01 computes same-session, same-compatible-input:

- `estimated_fat_mass = weight * body_fat_pct / 100`;
- `estimated_lean_mass = weight - estimated_fat_mass`.

The derived algorithm/version and exact input IDs are retained. Source muscle is not relabeled as lean mass. Trend charts split on algorithm compatibility. Recomposition is a scatter/time view plus optional same-algorithm pairs at least 28 days apart and within 1% weight; it does not assert that a small BIA delta is real tissue change.

## Garmin Vivoactive 5 Capability Matrix

“Client retrieval” is source-level method/payload capability, not a promise that the owner's sole device populates it.

| Metric | Watch supports/produces | Garmin Connect | `python-garminconnect` 0.3.12 | Final status |
|---|---|---|---|---|
| [Sleep](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-GB/GUID-70D41BFB-2BB2-4933-BF95-47FF63140112.html) | Yes | Detailed sleep | [`get_sleep_data` and range methods](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1877) | VERIFIED |
| [Sleep Score](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-GB/GUID-70D41BFB-2BB2-4933-BF95-47FF63140112.html) | Yes | Yes | Sleep payload overall score at the same client anchor | VERIFIED |
| [Sleep stages](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-GB/GUID-70D41BFB-2BB2-4933-BF95-47FF63140112.html) | Yes | Yes | Raw levels and totals at the same client anchor | VERIFIED |
| [Naps](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-97EA1540-A780-480F-BA4D-9A9E147FB225.html) | Timer/total; included in sleep stats | Watch/app/web | `napTimeSeconds`; [Body Battery events](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1373) may include naps | Totals/events verified; exact intervals **UNVERIFIED** |
| [HR](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-70A014A0-F378-4A61-AB46-5AD69B239D8F.html) | Wrist/activity HR | Yes | [`get_heart_rates`](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1120) and activity/FIT methods | VERIFIED |
| [RHR](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-70A014A0-F378-4A61-AB46-5AD69B239D8F.html) | Current/7-day watch view | History | [`get_rhr_day` and range](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1947) | VERIFIED |
| [HRV / HRV Status](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-GB/GUID-9282196F-D969-404D-B678-F48A13D8D0CB.html) | Overnight after baseline | Status/trends | [`get_hrv_data` and range](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L2030) | VERIFIED |
| [Stress](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-97EA1540-A780-480F-BA4D-9A9E147FB225.html) | Yes | Daily timeline | [`get_stress_data`](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1931) and all-day method | VERIFIED |
| [Body Battery](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-87E1392B-2C55-40B7-A1FF-3AB9252DA0A0.html) | Yes | Trends/events | [Range and event methods](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1356) | VERIFIED |
| [SpO2](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-2EE28BB8-91F1-4BCE-AE13-6CAEF50AD5C4.html) | Spot/all-day/sleep depending setting/region | Trends | [`get_spo2_data`](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1725) plus sleep payload | VERIFIED conditional |
| [Respiration](https://support.garmin.com/en-US/?faq=2yEgS0Pax53UDqUH7q4WC6) | Current/sleep/all-day; activity-type limits | Yes | [`get_respiration_data`](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1717) plus sleep payload | VERIFIED conditional |
| [VO2 Max](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-GB/GUID-A9651342-D68B-4377-9F64-CF006802838B.html) | Running estimate | Yes | [`get_max_metrics`](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L1448) | Watch/endpoint verified; owner payload **UNVERIFIED** |
| [Recovery Time](https://support.garmin.com/en-US/?faq=8ImmxVkZMh4EYYq5Zp2bR8) | **Yes**, on-watch up to four days | Garmin says devices without Training Readiness, including VA5, do not show it in Connect | No dedicated method; possible ORIGINAL FIT field | Watch-only contract; FIT retrieval **UNVERIFIED** |
| [Training Readiness](https://support.garmin.com/en-US/?faq=8ImmxVkZMh4EYYq5Zp2bR8) | No for VA5 under the official without-Readiness classification | No VA5-produced value | [`get_training_readiness` exists](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L2051) | Unavailable from sole VA5 |
| [Training Status](https://support.garmin.com/en-US/?faq=VxKazDQ2mkAmDoQbJriEBA) | Garmin calls VA5 non-compatible | May appear if another compatible device computes it | [`get_training_status` exists](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L2216) | Not VA5-produced |
| [Unified Training Status](https://support.garmin.com/en-US/?faq=EjPECQK58qA0xzJ5X74vm7) | Primary Wearable participation only; cannot provide status alone | Account-level with another compatible device | No separate UTS method | Partial participant, not producer |
| [Training Effect](https://www.garmin.com/en-US/compare/?compareProduct=1057989&compareProduct=886689) | Not documented for VA5 in reviewed manual/comparison | Sole-VA5 Connect behavior **UNVERIFIED** | [Typed activity fields exist](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/typed.py#L432) | Do not ingest as VA5-produced without live proof |
| [Acute/Training Load](https://www.garmin.com/en-US/compare/?compareProduct=1057989&compareProduct=886689) | Not documented for VA5 in reviewed manual/comparison | Sole-VA5 Connect behavior **UNVERIFIED** | [Typed activity load field exists](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/typed.py#L438) | Do not ingest as VA5-produced without live proof |
| [Activities](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-252F74B6-C24B-495B-8E73-4BD595CA7FE3.html) | GPS/activity profiles | Yes | [`get_activities_by_date`](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L2624), details, and downloads | VERIFIED |
| [Cycling metrics](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-252F74B6-C24B-495B-8E73-4BD595CA7FE3.html) | Basic speed/distance/HR; [cadence accessory](https://www8.garmin.com/manuals/webhelp/GUID-5D183A14-BB43-4A9B-B441-5F824214CE40/EN-US/GUID-1E3CECCF-0343-431C-95F0-5716E0341C75.html); eBike fields | Recorded fields | [Details](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L2957) / [FIT download](https://github.com/cyberjunky/python-garminconnect/blob/981d150caeda7d632224a75f3895c08df27a2a34/garminconnect/__init__.py#L2839) when populated | Basic verified; power/dynamics/cycling VO2 **UNVERIFIED** |

This resolves the key conflict: Recovery Time exists on Vivoactive 5, while Training Readiness does not. Unified Training Status is not Training Status production. Endpoint/schema existence never fills a device capability gap.

Absence from a feature list alone is not proof of impossibility; Training Effect and Acute Load therefore remain `UNVERIFIED` for the sole-VA5 account rather than being inferred from client schema fields.

## Garmin Integration Decision

`python-garminconnect` 0.3.x **did** move away from `garth`. [Release `0.3.0`](https://github.com/cyberjunky/python-garminconnect/releases/tag/0.3.0) says it replaced `garth` with native auth; the current [`0.3.12` dependency list](https://raw.githubusercontent.com/cyberjunky/python-garminconnect/981d150caeda7d632224a75f3895c08df27a2a34/pyproject.toml) does not include `garth`. The separate [`garth` final release](https://github.com/matin/garth/releases/tag/v0.8.0) is deprecated and says new login no longer works. Earlier donor `garth` branches are obsolete.

Use pinned `python-garminconnect==0.3.12`, wrap it behind a read/download allowlist, preserve raw payloads, and adapt only tested donor semantics. Owner MFA/region, history depth/rate limits, payload shapes, and watch-only FIT recovery remain live acceptance work.

## Google Health / Fitbit Decision

Use **Google Health API v4** at `health.googleapis.com`, described by Google as the next-generation Fitbit Web API. Do not implement a legacy Google Fit path. The legacy Fitbit Web API is scheduled for September 2026 turndown per the reviewed Google documentation.

Source-family contract follows the official [filters](https://developers.google.com/health/filters): retain raw `list` points and `dataSource` platform/device/recording method; store reconcile/rollup results with the exact `dataSourceFamily` query. `google-sources` can include Health Connect/manual records and `all-sources` can include third-party data, so neither is Fitbit-device evidence. `google-wearables` is still family-level unless returned metadata identifies the intended device. Cross-device agreement excludes ambiguous family aggregates.

Initial read scopes are limited to implemented streams:

- `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
- `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
- `https://www.googleapis.com/auth/googlehealth.sleep.readonly`

Fettle is the strongest selective donor but not copy-ready. Its [client/pagination](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/health_client.py), registry, [per-stream sync/sleep parsing](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/sync.py), and focused tests are useful. Its [OAuth](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/auth.py) and [store](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/store.py) violate the final state/provenance/security model. A pinned scope mapping also requests unused nutrition and misclassifies a sleep-temperature derivation; Health-Check follows official filters.

The exhaustive documented Google Health data types and sleep API expose source sleep/stages/physiology but no Fitbit Sleep Score or Readiness record. The legacy Fitbit sleep endpoint also explicitly omits Sleep Score. As of the review date, official proprietary score retrieval is not documented; local scores are separately named/versioned derived metrics.

## Google OAuth Decision

All Google Health scopes reviewed are restricted. OAuth Testing status limits offline refresh tokens to seven days, so it cannot support unattended weekly/monthly operation.

Realistic one-user path:

1. External Google Cloud project, publishing status **In production**.
2. Use the documented personal-use exception because the owner is the sole user (or, under the policy, only a few personally known users). The separate unverified-app audience cap is 100 users; do not conflate that cap with the exception's definition or claim verification.
3. Desktop OAuth client and system browser.
4. Random loopback `127.0.0.1` callback, PKCE S256, cryptographically random one-use state persisted and validated.
5. `access_type=offline`; retain refresh token in Windows Credential Manager/DPAPI-equivalent storage.
6. Refresh on demand; expose auth health; owner reconnects on revocation/`invalid_grant`.
7. Request `prompt=consent` only when obtaining a refresh token or deliberately reauthorizing.
8. Installed-app incremental authorization is not supported as assumed by fettle; request the complete required scope set on scope changes.

Service accounts cannot replace user consent. In-production refresh tokens are not guaranteed eternal; standard revocation/inactivity/policy conditions still apply. Live owner-project policy/access remains `UNVERIFIED` until R04.

## Xiaomi S400 Decision

The current stable openScale release contains S400 support. Source verifies broadcast-only AES-CCM in the [decryptor](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/libs/S400Decryptor.kt#L53-L175), a 16-byte bind key, MAC-in-nonce, weight, HR, and high/low impedance [packet aggregation](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/libs/S400Aggregator.kt#L22-L109). Phone logs are sensitive because the reviewed handler [logs the bind key at debug level](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/scales/MiScaleS400Handler.kt#L122-L129).

openScale's S400 pipeline calculates TBW/ECW/ICW/FFM/body fat/skeletal muscle/bone/visceral index/BMR/BCM/protein/SLM from profile inputs and public equations. It is not Xiaomi's proprietary calibration. The current handler does not export its internal reliability, swap, or timeout flags.

Webhook is preferred to current Health Connect because webhook preserves muscle, HR, raw impedances, visceral index, ECW/ICW, protein/BCM, custom metrics, and derived flags. The reviewed [Health Connect exporter](https://github.com/oliexdev/openScale-sync/blob/32e38651cf78bbf230e33d17abb00b147130f305/src/app/src/main/java/com/health/openscale/sync/core/sync/HealthConnectSync.kt#L86-L114) maps only weight, body water mass, body fat, lean mass, bone, and BMR; it also lacks algorithm/device metadata. Do not dual-ingest without deduplication.

## Photo Import Decision

- Original image is immutable, content-hashed, and stored outside Git.
- Extraction is a versioned provider-neutral interface.
- Candidates store per-field nullable model confidence, parser/model/prompt/schema version, and proposed source time/value/unit.
- Human confirmation/edit/rejection is a separate audit fact.
- Confirmed measurement keeps image/batch/event/source/device/algorithm provenance.
- Exact duplicate upload is idempotent; deliberate new-version reprocessing creates another candidate set.
- Historical app label/version is not guessed. Use an explicit unknown identity if evidence is absent.

No extraction result is silently committed or canonicalized.

## Cross-Device Agreement Strategy

Pair main sleep sessions by local wake date and compare total sleep, stages, RHR, and HRV independently. Do not treat vendor scores as equivalent measurements.

- 14 paired nights across at least two weeks: first exploratory report.
- 42 paired nights across at least six weeks, adequate coverage, and no known firmware/method break: provisional canonical-source decision.

Report paired bias/difference distribution, MAE, RMSE, Bland–Altman limits or robust quantile limits, and secondary correlation. Lin's CCC may supplement the stronger gate. ICC is not a default requirement for two personal devices. These sample gates are pragmatic engineering thresholds, not proof of interchangeability.

## Life Context Model

Store raw text immediately with interval/start/end precision, timezone/source, and optional tags whose origin/status is explicit. Do not force confirmation of every obvious note; ask when date/range is material and ambiguous. Preserve suggested tags even if corrected.

Sparse events use event-aligned windows and matched controls (prefer same weekday/baseline regime), not a 365-row alcohol boolean. Fewer than five non-overlapping events supports description only. Five may support clearly exploratory effect estimates with matched coverage; ten or more is a stronger but still non-causal personal signal. These are reporting guardrails, not universal significance thresholds.

Reserve the experiment concept now; implement `start -> exposure tracking -> evaluate + caveats` in R08, not R01.

## AI / MCP Boundary

Default path:

```text
LLM -> typed bounded tool -> Health-Check service -> versioned evidence packet
```

Packets include period, coverage, canonical metrics with source/algorithm/rule, disagreements, trends, anomalies, context, associations, exclusions, and confidence/caveats. Tools include period/weight summaries, comparisons, activity comparison, source agreement, context analysis, coverage, and provenance.

Healthquery's [SQL guard](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/services/sql_guard.py) validates SELECT syntax, but its generic SQL can read raw/config/schema data through a writable connection, and its nominal [read router](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/routers/read_api.py) also includes a settings-mutating PUT. It is not the final boundary. Health-Check separates read/ingest/import-write/admin capabilities at routes. MCP calls only read DTO endpoints.

Generic SQL is absent by default. If later justified: separate SQLite `mode=ro`, `query_only`, authorizer/progress deadline, one AST-validated SELECT, allowlisted analytic views/columns, mandatory bounded dates plus row/byte/time caps, audit, and no raw/config/secret/identity/schema tables.

## Reports & Notification Architecture

A deterministic report builder creates one versioned evidence packet/report revision. Renderers produce dashboard, Telegram, and email forms. Notifiers deliver those renders and record independent attempts/retries. Delivery failure never recomputes analytics. Late data creates an explicit new report revision.

All weekly/monthly/annual reports use the same infrastructure and include coverage/source/algorithm/rule versions. Telegram/email are adapters, not analytics dependencies.

## Recovery Score Decision

Defer. Garmin/Fitbit already provide multiple non-equivalent recovery signals; Health-Check does not yet know what decision a new aggregate would improve. Schema supports future versioned derived metrics, but no formula is scheduled in R01–R05. A later score requires accumulated baseline, a written need, component attribution, transparent versioning, and non-medical wording.

## Testing Architecture

- Pure deterministic functions with hand-checkable synthetic fixtures.
- Empty/forward migration, WAL/foreign-key, transaction/idempotency, and replay tests.
- Exact pinned provider contract fixtures; no live credentials in CI.
- Raw/source/canonical provenance and algorithm-boundary tests.
- Missing/unavailable/not-zero and coverage tests.
- Photo candidate/edit/confirm/reject/reprocess tests.
- Garmin/Google transforms port semantics only after owner-sanitized synthetic contract fixtures.
- API/UI smoke and manual local visual review.
- Privacy/ignore audit: no real values, tokens, DBs, images, payloads, or reports in Git/test artifacts.

## License / Reuse Constraints

Health-Check has no license at the pinned baseline. Choose a permissive project license before incorporating MIT/BSD donor code. Every reused file records upstream SHA/license and preserves notices.

`python-garminconnect` is an MIT dependency. openScale/openScale-sync stay external GPL programs; this lowers incorporation risk but is not a universal legal guarantee. VitaSync AGPL and `garmin_ai` without a discovered license are reference-only. Nested `garmin-grafana` BSD notice must survive any reuse from that subtree.

## R01 Decision

Proceed with [R01 — Weight & Body Composition](../R01_IMPLEMENTATION_SPEC.md).

Why not Garmin-first:

- weight/body composition is the owner's explicit first priority;
- roughly six months of S400 history already exists;
- weekly measurement means a small, explainable analytic slice is sufficient;
- Garmin Connect already supplies daily Garmin views;
- the same provider/device/raw/canonical/coverage core is required later anyway;
- R01 can produce unique value without waiting for fragile unofficial auth/history behavior.

The slice remains small: one codebase/database, a loopback UI/read/import listener plus optional separate ingest-only listener, photo confirmation, one webhook contract, conservative analytics, and one dashboard. No Garmin/Fitbit/Recovery Score/full notifications.

## R02–R10 Roadmap

- R02 — Garmin ingestion/backfill.
- R03 — Garmin analytics and cycling/activity comparison.
- R04 — Google Health/Fitbit ingestion and live OAuth proof.
- R05 — cross-device agreement and canonical sleep decision.
- R06 — Telegram/dashboard context plus typed read-only AI/MCP tools.
- R07 — saved weekly/monthly/annual reports and email/Telegram delivery.
- R08 — deeper context analytics, n-of-1 experiments, and recovery-score decision if justified.
- R09 — lab/document data.
- R10 — optional advanced AI, timezones, providers, mobile, and remote access.

## Explicit Non-Goals

- Product implementation in R00.
- SaaS/multi-user/auth platform.
- Enterprise queues/deployment.
- Workout planning/writes.
- Daily report.
- Mandatory diary or detailed nutrition.
- Medical diagnosis/treatment.
- Automatic Xiaomi/openScale calibration.
- Recovery Score before evidence.
- Generic unrestricted SQL/LLM database access.
- Native mobile application or sophisticated travel logic in early releases.

## Deferred Questions

- Owner-selected Health-Check repository license.
- R07 email transport.
- Exact external LLM/provider when AI tools ship.
- Secure remote access only if a concrete need appears.
- Future Recovery Score only after an unmet use case/data baseline.

## Live Verification Checklist

### R01 Xiaomi

- [ ] Record installed openScale/openScale-sync versions and owner profile/formula configuration.
- [ ] Pair S400 with owner-held MAC/bind key; verify no secret enters logs/artifacts used by Health-Check.
- [ ] Capture the real generic webhook privately and compare it byte/semantically to the pinned fixture.
- [ ] Replay duplicate, update, delete, clear, manual full sync, and lost-response behavior.
- [ ] Verify listener isolation, phone-to-laptop auth/firewall, secret rotation with stable sender identity, and chosen HTTPS/encrypted-overlay or explicitly warned trusted-LAN transport.
- [ ] Import representative historical screenshots privately; record actual app/version evidence or unknown.
- [ ] Collect same-weigh-in Xiaomi/openScale overlap before proposing any calibration.

### R02 Garmin

- [ ] Prove owner-region login/MFA, token refresh/reconnect, and Windows at-rest storage.
- [ ] Probe backfill depth/rate limits per stream and define reconciliation windows.
- [ ] Record actual Vivoactive 5/account payload availability for every capability-matrix row.
- [ ] Inspect ORIGINAL FIT for Recovery Time; keep `UNVERIFIED` if absent/ambiguous.
- [ ] Verify naps and cycling/accessory fields.

### R04 Google Fitbit

- [ ] Enable Google Health v4 for the owner project and prove exact scope/data-type access.
- [ ] Complete desktop loopback PKCE/state flow and partial-consent handling.
- [ ] Observe refresh automation for more than seven days in In-production status.
- [ ] Record actual backfill limits, score absence, field semantics, and stream coverage.

### R05/later

- [ ] Segment paired nights around firmware/app/device changes.
- [ ] Run the 14-night exploratory and 42-night provisional gates independently per metric.
- [ ] Validate travel/timezone samples before adding advanced calendar rules.

## Architecture Invariants

### MUST

- Retain raw evidence where practical and source provenance always.
- Preserve competing source values and superseded revisions.
- Separate physical device, provider/input method, and measurement algorithm.
- Version parser, algorithm, canonical rule, evidence packet, and report revision.
- Distinguish Xiaomi-app and openScale S400 composition.
- Use typed session/interval/activity/series models.
- Make ingestion replayable/idempotent and source-time ordered.
- Calculate analytics deterministically with coverage/exclusions/unavailable reasons.
- Require explicit human confirmation before uncertain image candidates become measurements.
- Permit historical reprocessing without destroying original evidence.
- Name provider-native and Health-Check-derived scores distinctly.
- Validate device/account production separately from client endpoint existence.
- Keep AI access typed, bounded, and capability-read-only.

### MUST NOT

- Silently merge incompatible body-composition algorithms.
- Delete losing source values after canonical selection.
- Convert absent/unknown/unavailable data into zero.
- Let an LLM compute long raw series or write through a read credential.
- Call a fettle/Health-Check score an official Fitbit score.
- Call a Garmin client method proof of Vivoactive 5 support.
- Copy unlicensed/GPL/AGPL code into Health-Check core against the declared boundary.
- Require Docker/Postgres/Redis/Kubernetes/queues for the personal MVP.
- Present BIA precision, wearable association, or LLM prose as medical diagnosis or causation.
