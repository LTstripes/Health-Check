# Reference Projects and Reuse Strategy

Snapshot date: **2026-09-02**. Every conclusion below is tied to a full commit SHA. Before copying code in a later release, recheck the exact file license, preserve required notices, and record the source commit in that implementation PR.

Health-Check itself has no LICENSE at baseline `2ff87de963f022dfdbfb4960276b09635888501a`. R00 recommends choosing a project license before incorporating donor code; this branch does not create one.

## Final classification

| Project | Pinned source | Verified license at pin | Final use |
|---|---|---|---|
| [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect/tree/981d150caeda7d632224a75f3895c08df27a2a34) | `981d150caeda7d632224a75f3895c08df27a2a34` (`0.3.12`) | MIT | **DIRECT runtime dependency** in R02, pinned; do not write a competing client. |
| [`garmin-stats-ai`](https://github.com/dandwhelan/garmin-stats-ai/tree/936974ac8c78781e7d0075040f459ea7676b3819) | `936974ac8c78781e7d0075040f459ea7676b3819` | Root MIT; bundled `garmin-grafana/` BSD-3-Clause | **Selective donor**: tiny pure statistics may be direct; adapt transforms/sync/lag/activity/test semantics; do not adopt the product. |
| [`fettle`](https://github.com/Deekshith-Dade/fettle/tree/82929df268124f0a3470b180adbbbeb0802d03cd) | `82929df268124f0a3470b180adbbbeb0802d03cd` | MIT | **Selective donor** for Google Health v4 registry/client/sync/sleep/test patterns. No module-level direct reuse approved. |
| [`healthquery`](https://github.com/nikira-studio/healthquery/tree/f175148f67cb954fc4db2e026e497984dfccac29) | `f175148f67cb954fc4db2e026e497984dfccac29` | MIT | **Selective pattern donor** for raw batch replay, migrations, and typed MCP shapes; reject its generic SQL and capability boundary. |
| [`garmin_ai`](https://github.com/TolmachevKirill/garmin_ai/tree/ca6d298cc4a7e4e95e036c76dce69d211a47aeee) | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee` | **UNVERIFIED**: no LICENSE/COPYING in pinned tree | **REFERENCE ONLY**; no code copying. |
| [`openScale`](https://github.com/oliexdev/openScale/tree/6613db5838e4674a19652441073f82b3ee3d7009) | `6613db5838e4674a19652441073f82b3ee3d7009`; stable S400 code also in `v3.1.2` | GPL-3.0 | **EXTERNAL Android component**; use its BLE/output boundary, copy no code into core. |
| [`openScale-sync`](https://github.com/oliexdev/openScale-sync/tree/32e38651cf78bbf230e33d17abb00b147130f305) | `32e38651cf78bbf230e33d17abb00b147130f305`; one unreleased commit after `v0.6.2` | GPL-3.0 | **EXTERNAL Android component**; implement its generic-webhook receiver contract. |
| [`open-wearables`](https://github.com/the-momentum/open-wearables/tree/72351e24de045e87da4fe4fd86142494e304e17b) | `72351e24de045e87da4fe4fd86142494e304e17b` | MIT | **ARCHITECTURE/SELECTIVE PATTERN**: typed MCP-over-API, provider registry/chunking; reject SaaS infrastructure and unsafe derived math. |
| [`VitaSync`](https://github.com/biosync-io/vitasync/tree/f299cd134edea8effca9ac52436fc83d439792b6) | `f299cd134edea8effca9ac52436fc83d439792b6` | AGPL-3.0 | **REFERENCE ONLY**; do not copy. Product/infrastructure mismatch. |

Network/process separation reduces code-incorporation risk but does not settle every licensing obligation. Distribution choices must still comply with each program's license.

## `python-garminconnect`

Current `0.3.12` replaced the deprecated `garth` login path with its native authentication engine. Runtime dependencies at the pin are `curl_cffi`, `requests`, and `ua-generator`; `garth` is not one of them. The client supports MFA continuation, token persistence/refresh, daily/range endpoints, and activity downloads. Raw typed APIs are still marked experimental.

Health-Check decision:

- pin `0.3.12` plus the audited SHA in R02;
- allowlist read/download methods only;
- wrap returned payloads behind Health-Check raw/source/typed contracts;
- store reusable credentials with Windows-appropriate at-rest protection;
- use a trailing resync window and live account contract fixtures;
- never infer device support from a method name.

The separate `garth` repository at `f99159a15c4c9463ce215a60ba9f7cb21f94a3b7` / final `v0.8.0` is deprecated and states that new logins do not work. Do not preserve old `garth` branches found in donor code.

## `garmin-stats-ai`

### DIRECT (small, audited, attributed)

- Only `pearson_r_p`, `benjamini_hochberg`, and `finalize_correlations` from [`garmin-insights/src/garmin_insights/stats_utils.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/stats_utils.py), with [`test_stats_utils.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_stats_utils.py) and [`test_stats_utils_no_scipy.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_stats_utils_no_scipy.py).

Do not copy the module wholesale: it also contains conversion/age heuristics, lag policy, pandas helpers, and hard-coded minimum-pair policy. Thresholds are Health-Check product policy, not scientific constants. Direct reuse waits for a Health-Check license and retained MIT notice.

### ADAPT

- [`garmin-grafana/src/garmin_grafana/transforms.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-grafana/src/garmin_grafana/transforms.py): wake-date sleep semantics, missing-not-zero behavior, and extraction fixtures; translate into typed Health-Check entities. The nested BSD-3-Clause notice applies. Relevant tests: [`test_garmin_transforms.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_garmin_transforms.py) and [`test_sleep_intraday_ingest.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_sleep_intraday_ingest.py).
- [`garmin-grafana/src/garmin_grafana/garmin_fetch.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-grafana/src/garmin_grafana/garmin_fetch.py): historical windows, trailing seven-day reconciliation, and original FIT handling; remove obsolete `garth`, global config, unbounded dependency, and side effects. Review [`test_token_owner.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_token_owner.py).
- [`garmin-grafana/src/garmin_grafana/sqlite_manager.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-grafana/src/garmin_grafana/sqlite_manager.py): natural-key/upsert idea, not its schema.
- [`garmin-insights/src/garmin_insights/tools/analysis_tools.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/tools/analysis_tools.py) plus `stats_utils.NEXT_DAY_LAG_METRICS`: actual next-calendar-date join, real-day slopes, Cohen's d, and experiment shape. Relevant tests: [`test_analysis_engine.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_analysis_engine.py) and [`test_experiments.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_experiments.py).
- [`garmin-insights/src/garmin_insights/tools/query_tools.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/tools/query_tools.py) aggregation helpers for a new explicit activity-comparison service; validate against [`test_query_tools_helpers.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_query_tools_helpers.py). There is no turnkey donor `compare_activities` to copy.

### REFERENCE

- [`garmin-insights/src/garmin_insights/insights/proactive.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/insights/proactive.py) scanner/evidence-tier/confounder metadata; review [`test_proactive_scanner.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_proactive_scanner.py) and [`test_proactive_scans.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_proactive_scans.py) without adopting thresholds/claims.
- [`garmin-insights/src/garmin_insights/db/cache.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/db/cache.py) and [`db/memory.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/db/memory.py) baseline/experiment storage shapes; review [`test_cache_builder.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_cache_builder.py) and [`test_experiments.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_experiments.py).
- [`garmin-insights/src/garmin_insights/scales/base.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/scales/base.py) and [`scales/registry.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/scales/registry.py) adapter/registry and defensive malformed-frame test style; review [`test_scale_adapters.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_scale_adapters.py), [`test_scale_api.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_scale_api.py), and [`test_scale_readings_store.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_scale_readings_store.py) as patterns only.

### IGNORE

- obsolete `garth` logic;
- write/upload/delete/schedule paths;
- Anthropic-specific agent/deployment/cloudflared/systemd surface;
- health/illness rules and thresholds as-is;
- [`garmin-insights/src/garmin_insights/scales/lefu.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/scales/lefu.py) (Fitdays/Lefu FFB0), [`scales/composition.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/scales/composition.py) (ported non-S400 formulas), and their golden vectors as S400 evidence. The pinned [`scales/registry.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/src/garmin_insights/scales/registry.py) registers only `lefu`; [`test_scale_adapters.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_scale_adapters.py), [`test_scale_api.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_scale_api.py), and [`test_scale_readings_store.py`](https://raw.githubusercontent.com/dandwhelan/garmin-stats-ai/936974ac8c78781e7d0075040f459ea7676b3819/garmin-insights/tests/test_scale_readings_store.py) are not Xiaomi S400 contract fixtures.

## `fettle`

### DIRECT

No complete module is approved for direct transfer. Tiny pure helpers or synthetic fixtures may be copied only after file-level review and MIT attribution.

### ADAPT

- [`backend/app/config.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/config.py): closed Google Health data-type registry, corrected against official scope mapping.
- [`backend/app/health_client.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/health_client.py): pagination and bounded rollup windows.
- [`backend/app/sync.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/sync.py): per-stream failure isolation concept plus sleep wake-day/stage parsing; replace its watermark/replay mechanics.
- [`backend/mcp_server.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/mcp_server.py): bounded typed metric vocabulary and deterministic-tool direction.
- neutral fixtures/semantics from [`test_sync_sleep.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/tests/test_sync_sleep.py) and [`test_partial_day.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/tests/test_partial_day.py): missing is not zero, CLASSIC versus STAGES, wake-date/offset handling, and incomplete-current-day exclusion.

Do not adapt the actual pinned watermark policy: rollups re-read only the last watermark day, while daily-list, sleep, and exercise paths re-fetch full history, and the watermark is date-only. R04 needs a bounded per-type backfill/cursor plus an explicit multi-day reconciliation window.

### REFERENCE

- [`readiness.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/readiness.py), [`sleep_analysis.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/sleep_analysis.py), insights, and anomaly ideas as explicitly local heuristics, not Fitbit proprietary algorithms or validated physiology.

### IGNORE / REPLACE

- [`auth.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/auth.py) OAuth implementation: plaintext token/client JSON, process-wide insecure transport, repeated consent, missing explicit state persistence/validation, and no PKCE.
- [`store.py`](https://raw.githubusercontent.com/Deekshith-Dade/fettle/82929df268124f0a3470b180adbbbeb0802d03cd/backend/app/store.py) storage model: metric/day primary keys overwrite competing source evidence; generic leaf extraction lacks device/algorithm/canonical provenance; inline DDL is not the migration strategy.
- Homemade readiness/sleep-score formulas, prescription expectations, and author-specific constants, including tests that pin those values.
- coach, Vital Age, goals/schedules, Matter lighting, macOS launchd, unrelated UI/opencode functionality.

The pinned config also requests a nutrition scope without registering a nutrition stream and maps one sleep-temperature derivation to the wrong official scope. Health-Check derives least-privilege consent from enabled implemented streams and verifies every mapping against official Google documentation.

## `healthquery`

Useful patterns:

- WAL and numbered migrations;
- raw ingest batch retention/replay/idempotency;
- separate-looking ingest/read authentication concepts;
- typed [`mcp_server.py`](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/mcp_server.py) query shapes/tests.

Do not transfer its security boundary unchanged:

- the generic [`sql_guard.py`](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/services/sql_guard.py) proves SELECT/no mutation but does not allowlist tables/columns;
- it runs through the ordinary [`database.py`](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/db/database.py) writable connection;
- raw/config/schema data, including [`operational_settings.py`](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/services/operational_settings.py), can be read;
- the nominal [`read_api.py`](https://raw.githubusercontent.com/nikira-studio/healthquery/f175148f67cb954fc4db2e026e497984dfccac29/backend/routers/read_api.py) router also contains a settings-mutating `PUT` route.

Health-Check uses route-level read/ingest/import-write/admin capabilities and typed analytics DTOs. Optional future SQL needs a genuinely read-only connection, allowlisted analytic views, AST/authorizer/time/row/byte constraints, and no raw/config/secret visibility.

## `openScale` and `openScale-sync`

The stable [`MiScaleS400Handler.kt`](https://github.com/oliexdev/openScale/blob/6613db5838e4674a19652441073f82b3ee3d7009/android_app/app/src/main/java/com/health/openscale/core/bluetooth/scales/MiScaleS400Handler.kt#L237-L369) verifies:

- encrypted broadcast-only BLE;
- MAC plus 16-byte bind key;
- dual-frequency impedance packets, weight, and heart rate;
- openScale's own public-equation composition pipeline and reliability categories.

openScale does not reproduce the proprietary Xiaomi S400 app algorithm. Its S400 handler has no “original Xiaomi app” formula selector; that option belongs to an older mono-frequency handler. Algorithm/reliability metadata is not fully propagated into the persisted/exported measurement, so Health-Check records the installed openScale version/configuration separately and treats missing values carefully.

The [`WebhookSync.kt`](https://github.com/oliexdev/openScale-sync/blob/32e38651cf78bbf230e33d17abb00b147130f305/src/app/src/main/java/com/health/openscale/sync/core/sync/WebhookSync.kt#L17-L92) generic webhook is richer than the current Health Connect mapping: it can carry raw impedances, heart rate, muscle, visceral-fat index, ECW/ICW, protein/BCM, generic values, and `isDerived`. It does not carry a schema version, physical device, algorithm, reliability, request ID, or signature. Convenience missing values may be serialized as zero; `values[]` presence is authoritative.

openScale-sync retries/reconciles but is not exactly-once. Its configured authorization string is copied verbatim into the `Authorization` header. Health-Check therefore configures a stable sender-instance UUID and binds a random rotatable `Bearer` token to it; secret rotation never changes data identity. It durably persists the envelope and per-item outcomes before 2xx, upserts insert/update by `(source_instance, userId, id)`, and records delete/clear as tombstones.

## `open-wearables`

Adapt selectively:

- [typed bounded MCP](https://raw.githubusercontent.com/the-momentum/open-wearables/72351e24de045e87da4fe4fd86142494e304e17b/mcp/README.md) calls authenticated REST rather than a shared database;
- [`timeseries.py`](https://raw.githubusercontent.com/the-momentum/open-wearables/72351e24de045e87da4fe4fd86142494e304e17b/mcp/app/tools/timeseries.py) cursor/page ceiling;
- Google v4 registry/list/reconcile/rollup chunking in [`data_247.py`](https://raw.githubusercontent.com/the-momentum/open-wearables/72351e24de045e87da4fe4fd86142494e304e17b/backend/app/services/providers/google/health_api/data_247.py);
- per-metric savepoint/failure isolation;
- source/device attribution and raw-payload reference concepts.

Do not adopt:

- multi-user SaaS/provider infrastructure, Celery/Postgres/Redis/S3;
- its direct OAuth choices where PKCE/consent behavior conflicts with the final Health-Check decision;
- unsafe physiology derivations such as reconstructing RR/RMSSD from unsuitable sparse HR data.

## `VitaSync` and `garmin_ai`

VitaSync is conceptually useful for encrypted tokens, hashed API keys, streaming/idempotent sync, and typed MCP ideas. Its inspected [`apps/mcp/src/index.ts`](https://raw.githubusercontent.com/biosync-io/vitasync/f299cd134edea8effca9ac52436fc83d439792b6/apps/mcp/src/index.ts), AGPL license, direct-database MCP caveats, and multi-tenant queues/platform surface make it reference-only.

`garmin_ai` remains useful through its pinned [`README.en.md`](https://raw.githubusercontent.com/TolmachevKirill/garmin_ai/ca6d298cc4a7e4e95e036c76dce69d211a47aeee/README.en.md) and source as a reference for raw-first/FIT fallback, Windows scheduling/packaging, Telegram, and explicit read-vs-write human-in-the-loop concepts. No root license was present at the pinned SHA, so no code may be copied. Its model-computes-from-raw MCP posture also conflicts with Health-Check's deterministic analytics boundary.

## Reuse gate for every later PR

1. Record exact upstream repository, SHA, file, and license.
2. Prefer a normal dependency over copied code when the dependency boundary fits.
3. Copy only the smallest independently tested unit.
4. Preserve copyright/license notices and provenance.
5. Port semantics into Health-Check's source/canonical/coverage model rather than importing a donor schema.
6. Re-test with synthetic Health-Check fixtures.
7. Never reuse a health threshold, formula, or device claim solely because a donor test passes.
