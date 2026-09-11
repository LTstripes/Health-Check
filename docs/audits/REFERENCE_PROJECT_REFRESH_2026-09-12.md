# Reference-project refresh — 2026-09-12

## Purpose

Refresh the external projects recorded in `docs/REFERENCE_PROJECTS.md` against their current upstream state, add Haelan as a new reference, and turn new donor observations into bounded Health-Check questions and regression ideas.

This audit does **not** silently repin an approved donor, approve new copied code, change a runtime dependency, or make a third-party repository authoritative for provider/API facts. The detailed reuse decisions in `docs/REFERENCE_PROJECTS.md` remain tied to their reviewed source SHAs until a later implementation task explicitly re-audits the exact file/license/commit it wants to reuse.

Canonical Health-Check baseline reviewed here:

`main @ 43abef5454e1778c9449a61635aca7c45c84a5b7`

Health-Check is MIT licensed at this baseline.

## Evidence rule

Reference repositories serve three different purposes and must not be conflated:

1. **Provider truth** — for R04 Google Health/OAuth, current first-party Google documentation and explicit owner-live evidence remain authoritative. Donor behavior can only create a question to verify.
2. **Implementation pattern** — data-flow, failure, coverage, replay, query-boundary and testing patterns may inform Health-Check when they fit our architecture.
3. **Adversarial regression** — a bug another project found can become a synthetic Health-Check regression even when none of that project's code is reused.

License classification still applies independently. In particular, AGPL/GPL projects are reference/external boundaries unless a later explicit licensing decision says otherwise.

## Refresh matrix

| Project | Previously reviewed pin | Upstream checked 2026-09-12 | Delta from pin | Health-Check action |
|---|---|---|---:|---|
| `python-garminconnect` | `981d150caeda7d632224a75f3895c08df27a2a34` (`0.3.12`) | `6569a424c9d44cc93fdd1b0444cc878d1a630866` (`0.3.13`) | +19 commits | Keep released R02 pin. Record 0.3.13 as an upgrade candidate only; require bounded auth/activity regression and owner verification before changing the dependency. |
| `garmin-stats-ai` | `936974ac8c78781e7d0075040f459ea7676b3819` | `b648f015e5bd914d27f82c19021e187473639068` | +10 commits | Add overnight-series, DST and sparse-upsert failures as reference/regression ideas. Do not adopt medical thresholds/causal narratives. |
| `fettle` | `82929df268124f0a3470b180adbbbeb0802d03cd` | same | 0 | Existing audit remains current. |
| `healthquery` | `f175148f67cb954fc4db2e026e497984dfccac29` | same | 0 | Existing audit remains current. |
| `garmin_ai` | `ca6d298cc4a7e4e95e036c76dce69d211a47aeee` | same | 0 | Existing reference-only decision remains current. |
| `openScale` | `6613db5838e4674a19652441073f82b3ee3d7009` | `573beb1d3588bd73597fb8a2da7474bf465157d2` | +21 commits | Keep GPL external boundary. Recheck API-v3 measurement identity and S400 generic values before any future Xiaomi ingest contract change. |
| `openScale-sync` | `32e38651cf78bbf230e33d17abb00b147130f305` | `afff7625c6a1cfc946caf76da87d7bc418a29270` (`0.6.3` line) | +4 commits | Keep GPL external boundary. Current generic webhook is still usable as a reference, but pre-v3 key/type-id assumptions are stale. |
| `open-wearables` | `72351e24de045e87da4fe4fd86142494e304e17b` | `53de57cade876df104720c0c5be07bbf462a55b1` (`0.8`) | +37 commits | Add `SyncRun`/per-data-type status, source attribution and migration-chain guards as reference patterns. Provider claims remain non-authoritative. |
| `VitaSync` | `f299cd134edea8effca9ac52436fc83d439792b6` | same | 0 | Existing AGPL reference-only decision remains current. |
| `haelan` | new | `89d512115acc9b1529a6380399a0d451556da0b1` (`1.6.0`) | new | **AGPL-3.0 / REFERENCE ONLY / no code copying.** Useful as an adversarial Google-v4 and local-health-store/query design reference. |

## Findings that change our watch list

### 1. Haelan — add as AGPL reference only

Repository: `bardesss/haelan @ 89d512115acc9b1529a6380399a0d451556da0b1`.

The root license is GNU Affero General Public License version 3. Health-Check must not copy Haelan code into the MIT core under the current project policy. The useful material is architectural and adversarial:

- terminal provider responses are archived before parsing;
- API irregularities are centralized in a provider data-type catalogue rather than scattered across mappers;
- sync windows are local-day aligned and repeatedly re-fetch a trailing window for late device uploads;
- unreadable/schema-drift responses hold the cursor back instead of turning an unknown shape into apparent completed coverage;
- provider reconciled/rollup rows remain semantically different from a locally explainable merge;
- corrections/overrides are applied during derivation rather than mutating raw/source rows, so removing a correction restores original evidence;
- dirty-day invalidation is transactional with the write that made a day dirty;
- one bounded typed query layer feeds HTTP/CLI/MCP rather than each surface reimplementing semantics;
- read-only agent access opens storage without migrations and bounds high-cardinality time-series requests;
- its planned source-staleness work captures a useful failure mode: a source that silently stops reporting can otherwise look like a merely sparse chart.

Haelan also records Google-v4 implementation observations such as irregular data-type names, string-encoded integer fields and proto3 omission of zero-valued fields. These are **hypotheses to verify** in #81, not evidence for #81: the issue's first-party-Google evidence standard remains unchanged.

### 2. `python-garminconnect` — 0.3.13 exists, but no automatic upgrade

The reviewed R02 dependency remains `0.3.12 @ 981d150...`. Upstream has moved to `0.3.13 @ 6569a424...`.

Relevant changes since our pin include:

- activities-response normalization to a list;
- activity-subtype filtering;
- token-store login robustness when the Garmin social profile initially lacks a usable `displayName`;
- removal of debug logging that serialized the social-profile response because it contains personal information;
- personal-record schema/documentation additions;
- new write-side gear creation.

The privacy/logging fix is a good adversarial check for our wrappers. The login/activity changes touch already released behavior and therefore argue **against** opportunistic upgrading: a later dependency bump should be its own bounded task with synthetic tests, exact-head CI, token/session reuse regression, activity-shape regression and owner-live verification. New write APIs remain outside Health-Check's allowlist.

### 3. `garmin-stats-ai` — useful overnight and failure-mode references

Current checked head: `b648f015e5bd914d27f82c19021e187473639068`.

The new overnight physiology work reads per-sample sleep series rather than only one-row nightly summaries. Useful patterns for later R08/deeper analytics include per-night shape extraction and personal robust baseline ideas. We should not copy its health thresholds, alcohol/meal/training signatures, screening claims or medical knowledge wording.

More valuable than the feature itself are bugs the project found:

- **DST mislabelling:** deriving historical local time from the machine's *current* fixed offset mislabels nights across DST. Health-Check should continue resolving temporal semantics from source evidence / the instant being classified, never from a present-day offset shortcut.
- **Sparse sibling upsert clobber:** two provider points sharing a natural identity but each carrying one field caused the second write to replace the first field with `NULL`. The repair merged non-null siblings rather than treating partial shapes as full replacements. This is a strong synthetic regression pattern for any future multi-fragment provider record.
- **Fixture/schema drift:** a test fixture had invented column names that did not match the fetcher's real persisted schema, so an analytic could pass tests while reading nothing in production. Contract fixtures must be generated/validated against the same typed persistence boundary they claim to test.
- **Late data and cache invalidation:** per-night cache invalidation uses evidence changes and recomputes recent nights that may still receive samples. The exact mechanism is donor-specific, but the principle matches Health-Check's version/evidence-driven reprocessing model.

### 4. `openScale` / `openScale-sync` — API-v3 identity is a real contract change

`openScale` has moved to an identity-based measurement-type registry. The relevant upstream change describes stable namespaced identities such as `builtin.*`, `ble.*` and `user.*`; first S400 users include ECW/ICW/BCM. `openScale-sync` 0.6.3 follows this as **API v3** and drops pre-v3 generic entries without an identity.

Current `WebhookSync.kt` still emits the convenience top-level fields (`weight`, `body_fat`, `water`, `muscle`) plus a self-describing `values[]` array. Each generic value carries a backend `key`, display `name`, UCUM-style `unit`, `isDerived`, and optional numeric/text value. The receiver therefore must not treat the convenience zero defaults as authoritative missingness and must not assume an old numeric/type-id vocabulary.

Health-Check action:

- do not change the released R01 ingest path merely because upstream moved;
- before any future Xiaomi/openScale ingest work, re-audit the installed app + sync versions and exact v3 webhook payload;
- preserve unknown generic values/unit/provenance conservatively rather than silently mapping every new BLE identity into an existing canonical metric;
- keep GPL code external.

A separate recent openScale bug is also a useful warning: publishing a weight-only reading while composition fields were missing interacted with value inheritance and made stale composition appear current. Health-Check already treats missing as missing; do not introduce cross-measurement value carry-forward without an explicit, visible derivation contract.

### 5. `open-wearables` — richer sync diagnostics, still architecture-only

Current checked head: `53de57cade876df104720c0c5be07bbf462a55b1` (`0.8`).

Useful additions since our previous pin:

- explicit `SyncRun` plus per-data-type tracking and stale-run handling;
- stronger sync-status surfaces;
- source/recording-source attribution on workout data;
- a CI migration-chain guard that rejects multiple Alembic heads and the dangerous case where an already-merged migration is re-parented so an existing owner database silently skips a new revision.

The first two are useful comparison points for R04 coverage/diagnostics; the migration rule is a good general engineering guard. We still reject the project's SaaS/Celery/Postgres/Redis/S3 surface for Health-Check.

Open Wearables also publishes provider-history observations, including a statement that the cloud Google Health API has no documented lookback limit. This is secondary donor evidence only. #81 must independently establish the official Google contract or preserve the point as UNKNOWN.

## Repositories with no material upstream delta

As of this refresh, `fettle`, `healthquery`, `garmin_ai`, and `VitaSync` are still at the SHAs already reviewed in `docs/REFERENCE_PROJECTS.md`. Their existing classifications do not change.

## Combined implications for R04 audits

### R04-00 / #81 — external Google contract

Use Haelan, Fettle and Open Wearables only as an **adversarial checklist**. Specifically ask current first-party Google evidence to confirm/refute:

- exact data-type names across URL path, filters and response envelopes;
- which R04 types support `list`, reconciled/reconcile and/or rollup surfaces;
- whether numeric fields may arrive as strings and how zero-valued proto3 fields/empty nested objects are represented;
- pagination and exact time-bound semantics;
- source/device attribution differences between raw/list and reconciled/rollup families;
- current documented historical/lookback limits or explicit lack of a guarantee;
- provider correction/late-arrival behavior where documented.

If first-party documentation is silent, keep UNKNOWN and move only the minimum point to owner-live verification. A donor implementation does not resolve an UNKNOWN by itself.

### R04-01 / #82 — repository design

Evaluate these patterns against the released Health-Check architecture without creating a generic provider framework:

- archive immutable provider evidence before normalization/parsing decisions can lose information;
- fail closed on unreadable/schema-drift responses and do not advance completion state past unparsed evidence;
- separate operational request/sync outcome from metric-level analytic availability;
- bounded local-day/source-family sync windows with an explicit trailing reconciliation policy when provider semantics justify it;
- per-data-type/source-family sync-run diagnostics and coverage rather than one global "sync succeeded" bit;
- keep provider-reconciled values distinct from Health-Check-local canonical/derived values;
- make later reprocessing/version bumps explicit and evidence-backed;
- keep future typed query/MCP surfaces thin over one deterministic read layer;
- consider metric/source-aware **source freshness/staleness** later, so a source that silently stops reporting is distinguishable from expected sparse metrics such as weekly weight.

The source-staleness idea is a future product/backlog candidate, not an R04 implementation requirement.

## Reusable adversarial regression catalogue

The refresh adds the following regression classes to the project watch list:

1. historical timestamp classified using today's UTC offset;
2. a partial sibling/upsert nulling a field observed in another fragment;
3. provider response shape drift accidentally treated as an empty successful window;
4. proto3 omitted zero confused with missing;
5. string-encoded numeric field rejected or silently mis-typed;
6. fixture schema diverging from the real typed persistence shape;
7. late-arriving data not invalidating recent derived/cache output;
8. provider aggregate mislabeled as a locally reproducible merge;
9. source silently stops reporting but UI presents only a thinning chart;
10. convenience zero/defaults overriding an authoritative generic-value presence model.

These are patterns to encode only in the owning implementation task where the corresponding data shape actually exists; they are not a reason to add unused generic infrastructure now.

## Final verdict

No existing donor classification needs to be relaxed. The refresh strengthens the project's current direction:

- keep immutable/source-specific evidence;
- preserve missing/unknown distinctions;
- make correction/reprocessing explicit and reproducible;
- keep agent/query surfaces bounded and downstream of deterministic semantics;
- treat provider documentation/live owner evidence as authoritative over donor memory;
- keep GPL/AGPL code out of the MIT core unless a future explicit licensing decision changes that boundary.

Haelan is added as a particularly useful **AGPL-3.0 reference-only adversarial donor** for R04 and later correction/query/freshness design.