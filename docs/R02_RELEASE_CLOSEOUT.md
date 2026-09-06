# R02 Garmin Release Closeout

R02 — Garmin ingestion and historical backfill is released to canonical `main`.

This document is the durable sanitized release record. It intentionally contains no health values, private Garmin payloads, credentials, tokens, precise health timestamps, screenshots, databases, or other owner-private evidence.

## Stable release

- Release PR: #61 — `integration/r02-garmin` -> `main`.
- Pre-release `main`: `e116e4deedb5ceea526e4672ccc0049e064b441d`.
- Accepted R02 integration head: `aea777e418d8d16c275a860c31b11c72641a73e6`.
- Released stable `main`: `d3b2fa316242ac11a7ba5851fdc99656cdf8e534`.
- Release PR exact-head CI: run `34049514818` — SUCCESS.
- Exact post-merge `main` CI: run `34049649157` — SUCCESS.
- Release gate tracker: #52 — CLOSED / completed.
- GitHub merge commit is verified and has parents exactly equal to the prior stable `main` and the accepted R02 integration head.

## What R02 delivered

R02 adds the production Garmin ingestion foundation on top of the R01 local-first core:

- owner-assisted Garmin authentication with protected external session storage and session reuse;
- explicit capability contracts that distinguish library/API availability from owner-device/account evidence;
- immutable raw/source payload observations with normalization provenance;
- typed Garmin normalization with missing/null/zero separation and source-time evidence preservation;
- daily, sleep, activity and intraday measurement persistence;
- incremental sync with bounded trailing-window refresh;
- bounded historical backfill with request caps, resumability and coverage-driven skipping;
- explicit `present`, `confirmed_empty`, `unknown`, `failed`/unavailable coverage semantics rather than silent absence;
- separate historical and incremental checkpoint namespaces;
- exact completed-rerun idempotency: already-complete historical coverage requires zero provider requests and does not grow current/observation counts;
- privacy-safe diagnostics and owner UAT procedures that keep real Garmin evidence outside Git and CI.

R02 does not include Garmin analytics/R03, FIT/GPS ingestion, scheduler/background service, Fitbit/Google ingestion, Recovery Score, or dashboard analytics expansion.

## Historical lineage

R02 was intentionally reconstructed onto a fresh integration line after R01 release rather than merging the earlier diverged preparation stack directly.

The accepted preparation layers were:

- #28 — Garmin capability inventory and synthetic capability contracts;
- #29 — normalization, temporal and idempotency contract;
- #30 — persistence/raw-observation contract;
- #31 — owner-assisted authentication/session and bounded live capability spike;
- #36 — live response-shape/capability reconciliation.

The fresh `integration/r02-garmin` line then added production sync/backfill orchestration and went through multiple owner release-gate iterations. Green synthetic CI was not treated as sufficient proof for live historical convergence.

## Release-gate history and repairs

The owner release gate #52 deliberately used one persistent external runtime instead of recreating state between attempts. That exposed several real-provider convergence defects that synthetic tests had not proven.

Important repair rounds included:

- #53 — first historical convergence repair after the initial full-range gate stalled on activity, heart-rate and Body Battery semantics;
- #57 — follow-up live heart-rate / Body Battery convergence repair after owner structural evidence showed the earlier assumptions were still too narrow;
- #59 — final sleep/respiration convergence repair for two reviewed provider-empty response shells.

Each repair was implemented on a worker branch, independently reviewed by the Integrator, merged only into `integration/r02-garmin`, and followed by exact-head/post-merge CI before owner UAT resumed on the same external runtime.

## Final owner gate

Final owner evidence on accepted integration SHA `aea777e418d8d16c275a860c31b11c72641a73e6` proved all mandatory operational criteria:

- historical backfill status: `succeeded`;
- no remaining chunks/days requiring provider work;
- exact rerun of the already completed historical range: `0` provider requests;
- exact rerun left current-record and payload-observation counts unchanged;
- normal incremental `garmin-sync` succeeded afterward;
- historical checkpoint namespace remained isolated from incremental checkpoints;
- protected external session was reused; no MFA retry was required;
- privacy scan passed; no raw values, identifiers, tokens, health timestamps, dates or payload fragments were emitted by the sanitized gate report;
- no code changes or runtime reset/recreation were used to manufacture the PASS.

The final exact rerun is the decisive convergence proof: historical completion is represented by durable coverage/checkpoint state rather than by an endlessly refetched provider range.

## Residual duplicate coverage rows

The release-gate database still contains one old `unknown` coverage row for sleep and one for respiration whose interval bounds duplicate the corresponding newer `confirmed_empty` coverage rows.

These rows are accepted as non-blocking historical residue, not live unresolved work, because:

- the same intervals have reviewed `confirmed_empty` coverage;
- historical checkpoints record completion for those surfaces;
- the exact completed rerun made zero provider requests;
- normal incremental sync succeeded;
- no remaining historical chunks/days were scheduled for retry.

R02 does not destructively rewrite historical coverage merely to make old audit rows disappear. If a later maintenance task introduces explicit coverage compaction/reconciliation, it must preserve provenance and must not reinterpret arbitrary `unknown` rows as empty.

## Release decision

**R02 RELEASED / mandatory release gate PASS.**

`main @ d3b2fa316242ac11a7ba5851fdc99656cdf8e534` is the canonical stable baseline after Garmin ingestion release.

The next work is pre-R03 hardening, in order:

1. #56 — Garmin collection reconciliation and version-aware reprocessing policy;
2. #55 — Garmin metric/time/analytic-coverage contract and reproducible R03 input/evidence manifest;
3. R03 — deterministic Garmin analytics and activity comparison.

Those tasks are intentionally post-R02. They harden how corrected/reprocessed Garmin evidence is consumed by analytics; they are not reasons to reopen the released ingestion gate.