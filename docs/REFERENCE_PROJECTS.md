# Reference Projects and Reuse Strategy

Snapshot refreshed: **2026-09-13** (post-R04 mechanical closeout for #90; reviewed pins and reuse classifications unchanged since 2026-09-12). Detailed reuse approvals remain tied to the reviewed source SHAs below. A newer upstream head recorded in this document or in an audit is **not** an automatic repin and does not expand the code-copy/reuse boundary.

Health-Check is MIT licensed. Before copying code in a later release, recheck the exact upstream file and license at the exact commit, preserve required notices, and record that provenance in the implementation PR/task evidence.

The full 2026-09-12 upstream comparison, including old/current SHAs, deltas and adversarial regression ideas, is in [`docs/audits/REFERENCE_PROJECT_REFRESH_2026-09-12.md`](audits/REFERENCE_PROJECT_REFRESH_2026-09-12.md). The 2026-09-13 post-R04 closeout (baseline `integration/r04-google-health @ 767a06a`, no repins, #94 attribution unresolved) is in [`docs/audits/REFERENCE_PROJECT_REFRESH_2026-09-13.md`](audits/REFERENCE_PROJECT_REFRESH_2026-09-13.md).

## 2026-09-13 post-R04 closeout note (#90)

Accepted research verdict: **no R04 reopen blocker**. Reviewed pins and reuse classifications are unchanged. Observed upstream heads recorded by the accepted 2026-09-13 research (observation only — not repins):

- `python-garminconnect` — observed `0.3.15 @ 54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5`, including the material sleep-respiration DTO alias fix. Health-Check's reviewed runtime pin stays `0.3.12`; the accepted maintenance disposition is bounded **`0.3.12 → 0.3.15`**, matching #98 (not the older 0.3.13 watch).
- `haelan` — observed `1.14.0 @ 4fc2bab4136ed46f950c0d2dc3ef1e03c5c50324`. The reviewed pin/license classification stays `1.6.0` / **AGPL-3.0 reference-only, no code copying**. Accepted material deltas are typed MCP/HTTP/read-boundary failure-class ideas, untrusted-text/tool-doc/runtime-budget ideas, and night-detail evidence; source **freshness itself remains not implemented upstream**.
- `openScale` / `openScale-sync` — clarification preserved: the namespaced `identity` is **internal** between openScale and openScale-sync, while the webhook sends the transformed backend `key` (e.g. `builtin.weight → weight`). The full namespace must not be assumed to cross the HTTP boundary.

Still **WATCH / DEFER**: openScale/openScale-sync API-v3 handling of a future Xiaomi ingest change, source freshness/staleness, and the 10-class adversarial regression catalogue. Owner-live source attribution (#94, including Fitbit-specific attribution) is **unresolved** and is not inferred.

Follow-up dispositions from the accepted #90 report were promoted by the **Integrator**, not by this docs worker: **#96** (guard Alembic migration ancestry before new schema work), **#97** (R05-00 Garmin/Google sleep agreement and canonical-source contract) and **#98** (bounded `python-garminconnect` 0.3.12 → 0.3.15 upgrade). An R06 typed-tool packet remains a future candidate, not an issue created for this closeout.

## Final classification

| Project | Reviewed source | Verified license at reviewed source | Final use |
|---|---|---|---|
| [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect/tree/981d150caeda7d632224a75f3895c08df27a2a34) | `981d150caeda7d632224a75f3895c08df27a2a34` (`0.3.12`) | MIT | **DIRECT runtime dependency** in released R02, pinned; do not write a competing client. Upstream `0.3.13` is a separate future upgrade decision, not an implicit repin. |
| [`garmin-stats-ai`](https://github.com/dandwhelan/garmin-stats-ai/tree/936974ac8c78781e7d0075040f459ea7676b3819) | `936974ac8c78781e7d0075040f459ea7676b3819` | Root MIT; bundled `garmin-grafana/` BSD-3-Clause | **Selective donor/reference**: tiny pure statistics may be direct after file-level review; adapt transforms/sync/lag/activity/test semantics; do not adopt product/medical claims. |
| [`fettle`](https://github.com/Deekshith-Dade/fettle/tree/82929df268124f0a3470b180adbbbeb0802d03cd) | `82929df268124f0a3470b180adbbbeb0802d03cd` | MIT | **Selective donor** for Google Health v4 registry/client/sync/sleep/test patterns. No module-level direct reuse approved. |
| [`healthquery`](https://github.com/nikira-studio/healthquery/tree/f175148f67cb954fc4db2e026e497984dfccac29) | `f175148f67cb954fc4db2e026e497984dfccac29` | MIT | **Selective pattern donor** for raw batch replay, migrations and typed MCP shapes; reject its generic SQL/capability boundary. |
| [`garmin_ai`](https://github.com/TolmachevKirill/garmin_ai/tree/ca6d298cc4a7e4e95e036c76dce69d211a47aeee) | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee` | **UNVERIFIED**: no LICENSE/COPYING in reviewed tree | **REFERENCE ONLY**; no code copying. |
| [`openScale`](https://github.com/oliexdev/openScale/tree/6613db5838e4674a19652441073f82b3ee3d7009) | `6613db5838e4674a19652441073f82b3ee3d7009`; stable S400 code also in `v3.1.2` | GPL-3.0 | **EXTERNAL Android component**; use its BLE/output boundary, copy no code into core. Current upstream has moved to an identity-based API-v3 measurement model; re-audit before future Xiaomi ingest changes. |
| [`openScale-sync`](https://github.com/oliexdev/openScale-sync/tree/32e38651cf78bbf230e33d17abb00b147130f305) | `32e38651cf78bbf230e33d17abb00b147130f305` | GPL-3.0 | **EXTERNAL Android component**; implement/maintain a compatible generic-webhook receiver contract, but re-audit current API-v3 identity semantics before changing the released R01 path. |
| [`open-wearables`](https://github.com/the-momentum/open-wearables/tree/72351e24de045e87da4fe4fd86142494e304e17b) | `72351e24de045e87da4fe4fd86142494e304e17b` | MIT | **ARCHITECTURE/SELECTIVE PATTERN**: typed MCP-over-API, provider registry/chunking, sync diagnostics; reject SaaS infrastructure and unsafe derived math. Current upstream observations are secondary evidence only. |
| [`haelan`](https://github.com/bardesss/haelan/tree/89d512115acc9b1529a6380399a0d451556da0b1) | `89d512115acc9b1529a6380399a0d451556da0b1` (`1.6.0`) | **AGPL-3.0** | **REFERENCE ONLY / NO CODE COPYING**: adversarial Google Health v4 observations; raw/cache/derived rebuild patterns; correction/rederive; bounded shared query layer; source-staleness idea. |
| [`VitaSync`](https://github.com/biosync-io/vitasync/tree/f299cd134edea8effca9ac52436fc83d439792b6) | `f299cd134edea8effca9ac52436fc83d439792b6` | AGPL-3.0 | **REFERENCE ONLY**; do not copy. Product/infrastructure mismatch. |

Network/process separation reduces code-incorporation risk but does not settle every licensing obligation. Distribution choices must still comply with each program's license.

## Evidence discipline for active R04 work

`fettle`, `open-wearables` and `haelan` are useful **adversarial references**, not authorities for Google Health behavior. R04-00/#81 keeps its stricter rule: current first-party Google documentation is required for material provider/API/OAuth/policy conclusions; owner-live evidence is used only where the official contract remains ambiguous.

A donor implementation may suggest that we ask about string-encoded integer fields, proto3 zero omission, irregular data-type names, source-family behavior, pagination or historical lookback, but it may not turn an official UNKNOWN into a Health-Check fact.

## `python-garminconnect`

The reviewed R02 dependency `0.3.12` replaced the deprecated `garth` login path with its native authentication engine. Runtime dependencies at that pin are `curl_cffi`, `requests`, and `ua-generator`; `garth` is not one of them. The client supports MFA continuation, token persistence/refresh, daily/range endpoints, and activity downloads. Raw typed APIs are still treated conservatively.

Health-Check decision:

- keep released R02 pinned to `0.3.12 @ 981d150caeda7d632224a75f3895c08df27a2a34` until an explicit dependency-upgrade task exists;
- allowlist only the read/download methods Health-Check actually needs;
- wrap returned payloads behind Health-Check raw/source/typed contracts;
- keep reusable credentials outside Git with Windows-appropriate at-rest protection;
- preserve trailing reconciliation/live-account contract tests;
- never infer Vivoactive/device support from a library method name.

### 2026-09-12 upstream watch

Upstream is now `0.3.13 @ 6569a424c9d44cc93fdd1b0444cc878d1a630866`, 19 commits past our reviewed pin. Changes relevant to us include activities-response normalization, an activity-subtype filter, token-store login recovery when the social profile lacks a usable `displayName`, and removal of debug logging that serialized a personal social-profile response.

Those are reasons to create a bounded upgrade task later, **not** reasons to silently change a stable R02 dependency. Any bump must rerun auth/session-reuse and activity-shape regressions plus owner-live verification. New write-side APIs such as gear creation stay outside our allowlist.

The separate `garth` repository remains deprecated; do not revive old donor branches that depend on it.

### 2026-09-13 update

The accepted 2026-09-13 refresh observed upstream `0.3.15 @ 54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5`, superseding the 0.3.13 watch above. The material change for us is a **sleep-respiration DTO alias fix**. The accepted maintenance disposition is a bounded **`0.3.12 → 0.3.15`** upgrade tracked as #98; the reviewed runtime pin and allowlist rules above are unchanged by this docs closeout.

## `garmin-stats-ai`

### DIRECT (small, audited, attributed)

At the reviewed pin, only tiny pure statistical helpers such as `pearson_r_p`, `benjamini_hochberg`, and `finalize_correlations` were candidates for direct reuse after exact-file license/provenance review. Do not copy the whole utility module: it mixes conversions, heuristics, lag/product policy and hard-coded thresholds.

### ADAPT / REFERENCE

Useful reviewed patterns include:

- wake-date sleep semantics and missing-not-zero transforms;
- historical/trailing reconciliation ideas without obsolete `garth` or global side effects;
- natural-key/upsert concepts, not its storage schema;
- real-calendar lag joins, slopes/effect-size/experiment shapes after Health-Check-specific policy review;
- activity-query aggregation helpers as reference for an explicit comparison service;
- scanner/evidence-tier/confounder metadata as a communication pattern, not a source of medical thresholds;
- adapter/registry and malformed-frame test style for hardware integrations.

Do not adopt its Fitdays/Lefu formulas or vectors as Xiaomi S400 evidence, and do not adopt author-specific illness/health rules as validated physiology.

### 2026-09-12 upstream watch

Current checked head `b648f015e5bd914d27f82c19021e187473639068` adds substantial overnight-series analytics. The feature is reference material for later deeper analytics; the **bugs found while building it** are even more useful as adversarial tests:

- historical local time must not be classified using today's fixed UTC offset;
- partial sibling rows sharing a natural identity must not overwrite another observed field with `NULL` merely because a later fragment omits it;
- synthetic fixtures must match the same typed persistence schema production readers consume;
- late/recent data must invalidate affected derived/cache output explicitly.

Do not import the project's medical/screening thresholds, alcohol/late-meal signatures or causal narrative.

## `fettle`

No upstream delta was observed since the reviewed pin as of 2026-09-12.

### ADAPT

- closed Google Health data-type registry shape, corrected against official scope mapping;
- pagination and bounded rollup windows;
- per-stream failure isolation plus sleep wake-day/stage parsing;
- bounded typed MCP vocabulary/deterministic-tool direction;
- neutral test semantics: missing is not zero, CLASSIC versus STAGES, wake-date/offset handling, incomplete-current-day exclusion.

Do not adapt its actual watermark policy: some paths re-read only the watermark day while others re-fetch broad history, and the watermark is date-only. R04 needs an explicit bounded per-type/source-family sync/backfill/reconciliation contract.

### REFERENCE ONLY

Readiness/sleep/anomaly ideas may be inspected as local heuristics, not Fitbit proprietary algorithms or validated physiology.

### IGNORE / REPLACE

- its reviewed OAuth implementation with plaintext token/client JSON, repeated consent and insufficient state/PKCE discipline;
- storage that overwrites competing source evidence behind generic metric/day keys;
- homemade readiness/sleep formulas and author-specific constants;
- unrelated coach/Vital Age/goals/Matter/macOS functionality.

Any Google scope/data-type statement must be rechecked against current official Google documentation for R04.

## `healthquery`

No upstream delta was observed since the reviewed pin as of 2026-09-12.

Useful patterns:

- WAL and numbered migrations;
- raw ingest-batch retention/replay/idempotency;
- distinct-looking ingest/read capability concepts;
- typed MCP query shapes/tests.

Do not transfer its security boundary unchanged. Its generic SQL guard proves SELECT/no mutation but does not adequately allowlist tables/columns, runs through an ordinary writable connection, and can expose raw/config/schema state. Its nominal read router also contained a settings-mutating route at the reviewed pin.

Health-Check keeps typed deterministic read DTOs as the normal AI boundary. Any future optional SQL needs a genuinely read-only connection, allowlisted analytic views, AST/authorizer/time/row/byte constraints, and no raw/config/secret visibility.

## `openScale` and `openScale-sync`

The reviewed S400 line verifies the important hardware boundary:

- encrypted broadcast-only BLE;
- MAC plus 16-byte bind key;
- dual-frequency impedance packets, weight and heart rate;
- openScale's own public-equation composition pipeline/reliability categories rather than the proprietary Xiaomi-app algorithm.

Health-Check therefore keeps openScale/openScale-sync external GPL applications and records their provenance/version rather than copying their code or silently presenting openScale-derived composition as Xiaomi-app-equivalent.

At the reviewed webhook contract, the generic webhook carried richer values than the Health Connect mapping, including raw impedances, HR, muscle, visceral-fat index, ECW/ICW, protein/BCM, generic values and `isDerived`. The sender is retry/reconcile capable but not exactly-once; Health-Check owns durable receiver idempotency/tombstone semantics.

### 2026-09-12 API-v3 change watch

Current upstream openScale is `573beb1d3588bd73597fb8a2da7474bf465157d2`; openScale-sync is on the `0.6.3` line at `afff7625c6a1cfc946caf76da87d7bc418a29270`.

The material change is an identity-based measurement vocabulary: stable namespaced identities (`builtin.*`, `ble.*`, `user.*`) replace the older generic key/type identity, and openScale-sync treats this as **API v3**. S400-specific generic types now include ECW/ICW/BCM use cases.

Current `WebhookSync.kt` still emits convenience top-level fields (`weight`, `body_fat`, `water`, `muscle`) plus `values[]` items containing a backend key, name, unit, `isDerived`, and optional numeric/text value. Because convenience fields can derive missing values to zero, `values[]`/explicit presence remains the safer semantic signal.

Health-Check action: do **not** reopen R01 solely because upstream changed. Before any future Xiaomi/openScale ingest task, re-audit the exact installed openScale/openScale-sync pair and current v3 webhook payload. Do not silently map every new BLE identity to an existing canonical metric.

A separate upstream bug also reinforces our missing-data rule: publishing weight-only data while composition was absent interacted with donor-side value inheritance and made old composition look current. Health-Check must not add cross-measurement carry-forward without an explicit visible derivation contract.

### 2026-09-13 clarification

`identity` is the **internal** measurement vocabulary between openScale and openScale-sync. What the webhook actually sends is the transformed backend `key` (e.g. `builtin.weight → weight`), so the full `builtin.*` / `ble.*` / `user.*` namespace must not be assumed to cross the HTTP boundary or to be reproducible from the receiver side.

## `open-wearables`

At the reviewed pin, useful patterns were:

- typed bounded MCP over authenticated API rather than direct shared-database access;
- cursor/page ceilings for time-series reads;
- Google-v4 registry/list/reconcile/rollup chunking as questions to check against official Google docs;
- per-metric failure isolation;
- source/device attribution and raw-payload-reference concepts.

Do not adopt multi-user SaaS/Celery/Postgres/Redis/S3 infrastructure, provider OAuth choices that conflict with Health-Check's accepted R04 contract, or unsafe physiology derivations.

### 2026-09-12 upstream watch

Current checked head is `53de57cade876df104720c0c5be07bbf462a55b1` (`0.8`), 37 commits past our reviewed pin. New patterns worth retaining as references:

- explicit `SyncRun` and per-data-type sync tracking/status;
- source/recording-source attribution on activity records;
- migration-chain CI that rejects multiple Alembic heads and re-parenting an already-merged migration in a way that could make an existing owner database silently skip a new migration.

Open Wearables also documents provider historical-range observations. These remain secondary evidence; e.g. its claim that cloud Google Health has no documented lookback limit must be independently established from first-party Google material in #81 or left UNKNOWN.

## `haelan`

Reviewed: `bardesss/haelan @ 89d512115acc9b1529a6380399a0d451556da0b1` (`1.6.0`). Root license: **AGPL-3.0**.

Health-Check decision: **REFERENCE ONLY / NO CODE COPYING** into the MIT core.

Useful architectural/adversarial ideas:

- archive terminal provider evidence before parsing;
- centralize provider data-type irregularities rather than duplicating them in mappers;
- local-day-aligned bounded sync windows plus a trailing re-fetch window for late uploads;
- fail closed on unreadable/schema-drift responses and hold the cursor/coverage boundary back;
- keep provider-reconciled/rollup rows semantically different from a locally reproducible merge;
- apply reversible overrides during derivation rather than destroying raw/source evidence;
- transactionally mark affected days dirty for re-derivation;
- one bounded typed query layer shared by HTTP/CLI/MCP adapters;
- open agent/query storage read-only and do not run migrations as a side effect of a read surface;
- detect future **source staleness/freshness** so a source that silently stops reporting is not presented merely as a thinner chart.

For R04, Haelan's Google-v4 observations about irregular naming, string-encoded integers and proto3 omitted-zero behavior are an **adversarial checklist only**. #81 must confirm them from first-party Google evidence or preserve UNKNOWN.

Source staleness is a future product/backlog candidate and should be metric/source-aware: a daily/intraday sensor going silent differs from an intentionally sparse source such as weekly weight. It is not an R04 implementation requirement.

### 2026-09-13 update

Observed upstream head is `1.14.0 @ 4fc2bab4136ed46f950c0d2dc3ef1e03c5c50324`; the reviewed pin stays `1.6.0` and the **AGPL-3.0 reference-only / no-code-copying** classification is unchanged. Accepted material deltas are typed MCP/HTTP/read-boundary failure-class ideas, untrusted-text/tool-doc/runtime-budget ideas, and night-detail evidence. Source **freshness itself is still not implemented upstream**, so it remains a Health-Check design idea rather than a donor capability to copy.

## `VitaSync` and `garmin_ai`

Neither changed from the reviewed pin as of the 2026-09-12 refresh.

VitaSync remains conceptually useful for encrypted-token, hashed-key, streaming/idempotent-sync and typed-MCP ideas. Its AGPL license, direct-database MCP caveats and multi-tenant platform surface keep it reference-only.

`garmin_ai` remains useful as a reference for raw-first/FIT fallback, Windows scheduling/packaging, Telegram, and explicit read-vs-write human-in-the-loop ideas. No root license was present at the reviewed SHA, so no code may be copied. Its model-computes-from-raw MCP posture also conflicts with Health-Check's deterministic analytics boundary.

## Cross-project adversarial regression catalogue

The 2026-09-12 refresh adds these reusable failure classes to the watch list. Encode them only in an owning implementation task whose data shape actually makes the regression meaningful:

1. historical timestamp classified using today's UTC offset;
2. a partial sibling/upsert nulling a field observed in another fragment;
3. provider shape drift accidentally treated as an empty successful window;
4. proto3 omitted zero confused with missing;
5. string-encoded numeric field rejected or silently mistyped;
6. synthetic fixture schema drifting away from production persistence;
7. late-arriving evidence not invalidating recent derived/cache output;
8. provider aggregate mislabeled as a locally reproducible merge;
9. a source silently stops reporting but appears only as a thinning chart;
10. convenience zero/default fields overriding a more authoritative explicit-presence/generic-value model.

## Reuse gate for every later PR

1. Record exact upstream repository, SHA, file, and license.
2. Prefer a normal dependency over copied code when the dependency boundary fits.
3. Copy only the smallest independently tested unit.
4. Preserve copyright/license notices and provenance.
5. Port semantics into Health-Check's source/canonical/coverage model rather than importing a donor schema.
6. Re-test with synthetic Health-Check fixtures.
7. Never reuse a health threshold, formula, provider fact, or device claim solely because a donor test passes.
8. A newer upstream head is observation only until an explicit task re-audits and approves the exact reuse boundary.