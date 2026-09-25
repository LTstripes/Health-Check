# Reference project refresh — 2026-09-25

## Scope and evidence limits

Owner-requested research, tracked in [#194](https://github.com/LTstripes/Health-Check/issues/194). Health-Check research/write baseline: `main @ 9800ed957b3b332e2011b3bcb9106821787f4345`.

The comparison starts from the September 12 refresh and September 13 clarifications, not from each project's original reuse pin. The [reference registry](../REFERENCE_PROJECTS.md) records all thirteen observed commits, dates, classifications and the new license checks.

Method: read canonical guidance, reference audits/registry, current dependency pin and open Health-Check work; inspect upstream recent commit messages, changelog, relevant PR/report and release/tag evidence; search additional repositories and read candidate READMEs/licenses. This is a bounded reference survey, **not an exhaustive code/security audit**. Upstream-reported reproduction and tests are not tests run by Health-Check. No private Owner data, account, device or credentials were accessed and no donor program was executed. Donor implementations are not authoritative provider specifications or validated physiology.

Result: **six existing code heads changed, four remained unchanged; three new watch-only references added**. This task changes documentation only, not dependencies, schema, source policy, health formulas, AI integration or scheduling.

## 1. Changed existing references

| Reference | Previous observation | New observation | Main useful change |
|---|---|---|---|
| python-garminconnect | `54079fb` / 0.3.15 | `c3c1c0d` / 0.3.16, September 18 | Successful HTTP response can still omit expected data. |
| garmin-stats-ai | `b648f01`, September 5 | `99987f7`, September 24 | Partial-day/nonwear/journal-gap correctness; shared MCP context; scale semantics. |
| openScale | `573beb1`, September 11 | `7a5c2ad`, September 21 | Comparison UX, goal baseline dates and model-specific BLE fixes. |
| openScale-sync | `afff762`, September snapshot | `58cbb87`, September 23 | Zero-weight feedback corruption and failed-read reconciliation guards. |
| open-wearables | `53de57c` / 0.8 line | `db55ea3`, September 25 | Pagination, transaction and auth-state fixes; opt-out telemetry. |
| haelan | `4fc2bab` / 1.14.0 | `ff0dd63`, September 25; changelog through 2.11.1 | Source-status panel, home/day navigation and projection consistency. |

Unchanged heads: fettle `82929df`, healthquery `f175148`, garmin_ai `ca6d298`, VitaSync `f299cd1`. This does not imply that every issue or non-default branch is inactive. Their existing reuse boundaries remain in force.

### 1.1 openScale-sync: records must survive failed reads

The most immediately actionable finding is [PR #38](https://github.com/oliexdev/openScale-sync/pull/38), merged September 13 at [`8a216f6cee5f8bb514766b9df41e9c44a98b0837`](https://github.com/oliexdev/openScale-sync/commit/8a216f6cee5f8bb514766b9df41e9c44a98b0837).

The author reported actual zero-weight corruption: an absent weight became a convenience default of zero, was exported, and two-way sync subsequently overwrote a real openScale value. The investigation also identified a separate destructive path: a failed local read became an empty list, which reconciliation could interpret as authorization to delete previously synced destination records. The author explicitly did **not** establish that this latter path caused the observed corruption.

The integrated fix guards finite positive weight on common submission/reconciliation paths, rejects invalid inbound weight, retains skipped IDs in the current-ID set, and makes null-cursor/read failures fail rather than masquerade as a complete empty inventory. Later changes address [service timeout](https://github.com/oliexdev/openScale-sync/commit/03c32b5b7b448bfd49d9fc4dded071eecfac38b8) and [API-v3 instrumented-test drift](https://github.com/oliexdev/openScale-sync/commit/58cbb87b9ea764bee6d487ccc80eeef169a01521).

**Released package is not current source:** the observed latest published [v0.6.3 release](https://github.com/oliexdev/openScale-sync/releases/tag/v0.6.3) is dated September 6 and requires openScale 3.1.3 or newer. The native GitHub [tag-to-fix comparison](https://github.com/oliexdev/openScale-sync/compare/v0.6.3...8a216f6cee5f8bb514766b9df41e9c44a98b0837) reports the fix four commits ahead of tag commit `0961540781a90581eee71c1e684af7d7838ae47a`, without divergence. Installing the latest published release does not prove this fix is present.

**Disposition:** preflight research for existing Owner-live [#153](https://github.com/LTstripes/Health-Check/issues/153). Identify the actual installed app/sync build and webhook contract; preserve the internal `identity` versus transmitted `key` distinction and Xiaomi-app versus openScale composition provenance. No Health-Check receiver defect or Owner installation state was established. Do not automatically upgrade an Owner device or start a second sync implementation.

Reusable invariant: **failed/incomplete inventory is not a complete empty inventory; invalid skipped input is not an authorized deletion**. Add synthetic tests only where the owning receiver/reconciliation contract makes that failure possible.

### 1.2 garmin-stats-ai: not recorded does not mean absent

[The September 24 quality fix](https://github.com/dandwhelan/garmin-stats-ai/commit/013576d2788c8dc67636b3ca569888c46accee87) addresses three upstream problems: today's still-growing sedentary counter looked anomalous; nights without usable watch recording contaminated the baseline; and days after journaling stopped were treated as days without the tracked behavior.

For future Context analytics, distinguish **explicit present / explicit absent / not recorded or unknown**. Do not turn diary gaps into the negative comparison group. Partial-day eligibility and recording quality are distinct from freshness: a current source may still provide an unsuitable observation for a particular comparison. The donor's one-hour/three-day heuristics are not approved Health-Check policy.

[PR #78](https://github.com/dandwhelan/garmin-stats-ai/pull/78) also adds per-user MCP context and evidence-rule queries using shared application instructions rather than a second divergent prompt. Reuse the idea of a compact deterministic evidence packet with provenance/caveats, not raw health dumps or model-generated medical judgments.

The Fitdays changes provide additional failure lessons:

- [Body type is not Garmin physique rating](https://github.com/dandwhelan/garmin-stats-ai/commit/3155ba847fd79f90db9315f64e69b2af39611435): similar names and numeric ranges do not establish equivalent meaning.
- [Invalid impedance](https://github.com/dandwhelan/garmin-stats-ai/commit/9edc3be7799bebd866e35abe0bbbfed2310e4a7d): preserve usable/raw evidence and withhold unsupported composition, without importing device-specific thresholds into S400.
- [Wrong byte offset passing a single vector](https://github.com/dandwhelan/garmin-stats-ai/commit/93e8261e58d8e3be40c883d440f573896189eac1): test multiple independent protocol examples, not one self-confirming fixture.
- [Full scan implementation](https://github.com/dandwhelan/garmin-stats-ai/commit/77ea903739dfb10df5000aedb289d37d26c23e0e): depends on a separately supplied proprietary WLA37 library. Root MIT does not license that dependency, and Fitdays/Lefu hardware is not S400.

### 1.3 Haelan: one explanation across home, calendar and detail

The [pinned changelog](https://github.com/bardesss/haelan/blob/ff0dd6355505f7efebaf9bd120b9c73c55af3c71/CHANGELOG.md) reaches 2.11.1 on September 25. Freshness now exists; the September 13 statement to the contrary is historical. Generated changelog sections can repeat old work, so the findings below are tied to specific recent commits:

- [#368 status panel](https://github.com/bardesss/haelan/commit/42d6b732ee3d9b1e2e9c10874f9daf5a0bc23b38): connection health, actual device delivery and persisted last sync are separate facts.
- [#373 warning consolidation](https://github.com/bardesss/haelan/commit/8dc8c85fb9c8010e4e2c44589e042641c2f48922): explain a quiet source once instead of repeating the warning on every card.
- [#374 home screen](https://github.com/bardesss/haelan/commit/54b183e19bec65448ae7da261a88de6b2d70a032): lead with last night/today/week; distinguish running and finished days; compare steps through the same observed minute; preserve earlier complete nights when the latest night is missing.
- [#377 day navigation](https://github.com/bardesss/haelan/commit/8c808fa0ac815501bfcfae19135b5e30d943c9d2): use canonical daily availability, not raw excluded sessions; do not silently substitute the previous day's recovery for a missing historical reading.
- [#379 historical bands](https://github.com/bardesss/haelan/commit/14b5175939ab4f54165350b217790be16b1bd471): each historical dot uses its own day's baseline and agrees with detail/calendar; baseline reads are batched.
- [#371 stale projections](https://github.com/bardesss/haelan/commit/611ab1506158a4aeca1a93c513a181e766a9342c): exclusions/restorations must refresh the home projection, and MCP must not omit secondary sources that HTTP already exposes.
- [#370 status cost/counts](https://github.com/bardesss/haelan/commit/3ac9662e1cb790567263b793cae4d3d708859ce3): grouped reads replace repeated raw parsing; sync results include backfill writes.

These are strong references for deferred [#172](https://github.com/LTstripes/Health-Check/issues/172) / [#189](https://github.com/LTstripes/Health-Check/issues/189), not permission to start a redesign. Freshness core #191 already exists; #193 must reuse it. Deduplicate actions without hiding missing evidence or importing cadence thresholds.

Browser-test lesson from #368/#374: a valid bounding rectangle or passing simulated-DOM assertion did not prove a popover/disclosure was visible and clickable in Chromium. Later UX acceptance should open actual desktop/mobile layers and test visibility, hit targets, focus and loading transitions. **AGPL reference only; no code copying or homemade recovery scores.**

### 1.4 openScale: understandable comparison, conservative device handling

The [September 21 comparison change](https://github.com/oliexdev/openScale/commit/40fd726494b70dc0c9cc87152daa907916b5215d) places two weigh-ins or aggregate periods side by side and selects one delta mode—absolute, relative or per-week—rather than displaying several confusing changes at once. The [goal start-date change](https://github.com/oliexdev/openScale/commit/e79e8005ed64826b7f31c2910f0fa01313e20519) makes the baseline date explicit.

Reuse presentation ideas later: show periods, units, observation counts and uncertainty; distinguish percent from percentage points. Do not silently change analytical values/hashes to reproduce a donor's display rounding. Goals remain an optional product choice.

The [ALPHA/Taylor](https://github.com/oliexdev/openScale/commit/7a5c2ad3dd4ca0d13b4059e11118ee77b4f306d9) and [Runstar](https://github.com/oliexdev/openScale/commit/d9e3ec15f3c3bea246abf0616b9aa2517ca1a4e5) work reinforces model-specific matching, checksums and raw preservation; it does not establish new S400 capability. Do not transplant a fallback that turns an invalid historic measurement timestamp into the current time. Preserve measurement-time uncertainty separately from receipt time. GPL code remains external.

### 1.5 python-garminconnect: keep the accepted pinned path

Upstream [0.3.16](https://github.com/cyberjunky/python-garminconnect/releases/tag/0.3.16) includes [the goals fix](https://github.com/cyberjunky/python-garminconnect/commit/1184e340013366d2a4a124be249837cacb9a31f6): a particular endpoint returned HTTP 200 with an empty list because a fetch-metadata header was missing. This is not a rule to reject every valid empty response or add the header to all provider requests.

Health-Check already pins 0.3.15. This survey establishes no need for the affected goals method or an immediate bump; tie any upgrade to an actually used method and run the existing bounded gate. New write APIs stay out of scope.

Open [issue #439](https://github.com/cyberjunky/python-garminconnect/issues/439) reports legacy garth-token resume breaking after a 0.3.x upgrade. This is an unresolved upstream user report, not a reproduced regression of our native-auth pin. Useful recovery guidance is explicit reauthorization for incompatible sessions rather than unexplained retries.

### 1.6 Open Wearables: completeness, persistence and privacy

Recent fixes include [Suunto history pagination](https://github.com/the-momentum/open-wearables/commit/6b8945d1d3949db00daec5e3f5511a00ae53bf44), [Polar webhook transaction/response handling](https://github.com/the-momentum/open-wearables/commit/7c1cbd454d7ab33bb156b5ec91310776c84302c1), [revoked-token diagnostics](https://github.com/the-momentum/open-wearables/commit/aded5ad9c25957f43ffcb6b6add8a6ca7f9375f2) and [webhook deregistration when switching to pull](https://github.com/the-momentum/open-wearables/commit/b509569145d6cbfb7578e896cf7471c597ec9dc5).

Transfer failure classes, not a new provider/platform stack: complete pagination before claiming complete history; commit persistence before success; distinguish authentication required from transport failure; prevent duplicate delivery modes. None proves our providers have those defects.

The latest observed commit [adds opt-out telemetry](https://github.com/the-momentum/open-wearables/commit/db55ea3cbcddd9841f12f95f5fe57acef252d04a). Its revisions remove health-related flags and precise counts that could describe one person's activity. Do not import telemetry, external pings, Redis/Celery infrastructure or the assumption that aggregate health metadata is harmless. Provider/API policy conclusions still require first-party evidence.

## 2. Three new watch-only references

### GarminDB — archive and replay

`tcgoetz/GarminDB @ 62409888d853d7cf4acd1bb7320337ce9f942176`: [README](https://github.com/tcgoetz/GarminDB/blob/62409888d853d7cf4acd1bb7320337ce9f942176/README.md), [GPL-2.0 license](https://github.com/tcgoetz/GarminDB/blob/62409888d853d7cf4acd1bb7320337ce9f942176/LICENSE).

Watch retained FIT/JSON, offline regeneration, daily-to-yearly exploration and coverage/count inventories. Useful before deeper history or fallback import work. Our raw archive/backup primitives already exist: do not recreate them, replace the accepted client, transplant plaintext credential examples or add another database model. **Reference only, no code copying.**

### garmin-local-mcp — compact analysis and explicit demo identity

`anup-shesh/garmin-local-mcp @ 5e895441e0b3ec21a2373a115a0e5e1c323c4a40`: [README](https://github.com/anup-shesh/garmin-local-mcp/blob/5e895441e0b3ec21a2373a115a0e5e1c323c4a40/README.md), [MIT license](https://github.com/anup-shesh/garmin-local-mcp/blob/5e895441e0b3ec21a2373a115a0e5e1c323c4a40/LICENSE).

Watch compact query tables, gaps, exploratory lag tools, zero-auth wellness FIT import and deterministic synthetic stores with `demo_store` identification. A future Health-Check tool packet should return a trend/comparison with N, coverage, freshness, source/policy version and withholding reasons—not months of raw JSON for model-side arithmetic.

The whole donor server is **not read-only**: documented tools include `sync` and `import_fit`. Its provisional-RHR heuristic, fixed baselines and lag scans are not approved Health-Check policies. Future inference needs calendar alignment, minimum evidence and consideration of multiple comparisons/autocorrelation. Local storage also does not keep data local once it is sent to an external model/client. MIT allows consideration after exact-file review; no donation or importer is approved here.

### Vitals Command Center — calm home and mobile onboarding

`8tp/Vitals-Command-Center @ 514ef0c51c3f00baa3176d9aff4a486bf21d546d`: [README](https://github.com/8tp/Vitals-Command-Center/blob/514ef0c51c3f00baa3176d9aff4a486bf21d546d/README.md), [MIT license](https://github.com/8tp/Vitals-Command-Center/blob/514ef0c51c3f00baa3176d9aff4a486bf21d546d/LICENSE).

Useful for a calm home, progressive phone-sized detail and synthetic onboarding without accounts. It is a newly discovered reference, **not a new September code release**. Revisit when #189 resumes and #172 is reconciled with the information architecture.

Reject weighted consensus across non-equivalent device measures, homemade readiness/confidence, automatic cloud-AI fallback and public remote access assumptions. Our source/sleep-agreement policies are not replaced by a prettier dashboard. This candidate has not received a deployment/security audit.

## 3. Reuse map, without duplicate implementation tasks

| Order / owning work | Proposed use | Boundary |
|---|---|---|
| First: Owner-live #153 | Exact app/sync build check, API-v3 presence/identity, weight-only composition provenance, replay/deletion behavior. | Research/preflight, not a confirmed local bug or automatic app upgrade. |
| Current: #193 under #147 | One compact freshness projection and actionable explanation reused by owner-refresh and Period Brief. | Core #191 is done. No new thresholds, provider calls or UI redesign in this task. |
| Later: Context analytics | Explicit present/absent/unknown, partial-day/recording-quality eligibility, calendar-aligned comparison groups. | Future semantic design, not a new requirement for completed Context capture or a causal health claim. |
| Later: #172 / #189 | Summary first, one source-status explanation, units/N, details on demand and consistent historical days. | Deferred; preserve uncertainty and deterministic contracts, measure cost before optimizing. |
| Later: AI/MCP readers | Typed evidence packets and a read-only capability boundary over existing services/Period Brief. | No bulk raw dumps, sync/restore tools or new AI/Telegram implementation here. |
| Before relevant adoption | Synthetic counterexamples tied to real persistence; actual browser checks for UI. | Do not import every donor test or change separate Windows CI #181 scope. |

Compact regression packet for future owning tasks:

1. Failed/incomplete inventory cannot authorize deletion; an invalid skipped row is not a missing ID.
2. Missing weight cannot become zero or overwrite a valid value; missing composition cannot silently inherit the preceding weigh-in.
3. An unrecorded diary day is not an explicit negative exposure; unsuitable/partial observations do not silently enter a full-day baseline.
4. Correction/exclusion/restoration updates every affected summary/detail projection without a stale success claim.
5. Historical dots and detail use the same declared as-of baseline; a missing value is not an unlabelled prior-day fallback.
6. Comparison display distinguishes units, percent/percentage points and precision without changing analytical semantics.
7. Pagination, backfill counts, committed writes and attribution agree across interfaces; successful HTTP alone does not prove completeness.
8. A demo identifies itself and refuses to overwrite real data; real-browser tests exercise opened overlays, not only geometry.

Several underlying principles already occur in the September 12 ten-class catalogue or accepted Health-Check contracts. These extend concrete evidence and fixtures; they are **not eight new Health-Check bugs and not eight new implementation issues**.

## 4. Non-actions and next refresh

No source switch, dependency bump, code donation, telemetry, clinical threshold, daemon, cloud connector or Owner runtime mutation is authorized by this report. Accepted pins and GPL/AGPL/no-license exclusions remain intact. Product proposals need an explicitly scoped owning task; #194 is the documentation refresh only.

Next time, compare with the observed commits in this registry, not the original donation pins. Check releases separately from code heads, distinguish unresolved reports from confirmed defects, re-read exact licenses and map useful changes to existing work before creating tasks. The registry suggests a review cadence; **no recurring automation was installed in this session**.
