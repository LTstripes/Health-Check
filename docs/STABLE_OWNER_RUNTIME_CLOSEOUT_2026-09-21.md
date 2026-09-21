# Stable Owner Runtime Closeout — 2026-09-21

This is the durable sanitized closeout for the post-R05 Owner Runtime reconstruction and operations hardening.

No owner health values, raw payloads, credentials, tokens, screenshots, databases or private runtime artifacts are stored here.

## Accepted owner runtime

- Canonical owner **data/runtime profile**: `D:\Garmin\\HealthCheck-Stable`
- Accepted live-tested code line: `integration/stable-owner-runtime @ 0b05a80749e3ef0d2fa736778baa49cc23f18a61`
- Exact integration CI: `35581607069` — SUCCESS
- Runtime closeout tracker: #132 — CLOSED / completed
- Canonical Git release source remains `main`; owner-data/runtime canon and Git branch canon are different concepts.

Important repository state at closeout:

- current canonical handoff checkpoint: `main @ b887fceceb85931ad8ead9423c0f86e0cac09291` with exact-main CI `35608281796` SUCCESS;
- historical divergence-analysis checkpoint: `main @ 6f21eeacf80491f73bcf9c5b5411eba1922dd1a4`;
- Stable integration and current main diverged from merge base `2c19ca968f84efb5e69c1a859ce6016939e617ca`;
- the accepted Stable-runtime code must therefore be reconciled with current main before canonical code promotion. Do not treat the integration SHA as a replacement for main.

## What is now proven

### One durable cross-domain profile

Stable contains the accepted historical Weight/body-composition base plus reconstructed Garmin and Google evidence through supported application paths. No SQLite table grafting was used.

The accepted R05 exploratory agreement can be rebuilt from Stable's own persisted evidence and remains exploratory/non-canonical. Garmin remains the canonical/default sleep source.

### Provider operation and convergence

The Stable runtime has live-proven:

- protected Garmin and Google session reuse;
- bounded Garmin and Google refresh/backfill behavior;
- dense Google heart-rate historical continuation;
- deterministic daily partitioning for dense heart-rate refresh;
- bounded transient Google retry behavior;
- Body Battery duplicate-series coalescing without weakening fail-closed persistence;
- resumable provider interruption with staged evidence preserved until successful continuation.

### Google semantic identity repair

The pre-repair Stable evidence exposed response-position/path-driven semantic churn. #156 replaced that with path-free instant/interval identity semantics while retaining query/family acquisition-context separation.

Live migration evidence:

- legacy current projections were migrated/retired through repository code, not manual SQL;
- conflicts: 0;
- second migration pass: exact no-op;
- canonical current instant duplicate groups: 0;
- raw payload / observation / artifact provenance remained preserved;
- exact-window rerun and later targeted continuation produced no renewed semantic identity growth.

### Backup / restore

The real Stable SQLite database grew beyond the earlier 4 GiB ZIP-member cap. #158 raised only the bounded member envelope needed by the owner profile while keeping the total expanded cap bounded and preserving format-v1/ZIP64/checksum/integrity/atomic-restore behavior.

A fresh real Stable backup was:

1. created through the supported profile-backup path;
2. independently verified;
3. restored into a new disposable external profile;
4. checked against Stable migration/table state;
5. used successfully for the #156 migration rehearsal.

The restored clone, not Stable, is the normal place for release/UAT experiments.

### Orphaned SyncRun recovery

#140 added an explicit fail-closed maintenance command using the existing terminal `failed` status and a shared profile-scoped external-runtime operation lock.

Owner-live recovery:

- dry-run found exactly the two known historical stale `running` rows;
- apply recovered exactly those two rows;
- remaining running rows became 0;
- immediate repeat apply was a no-op.

No provider checkpoints, source evidence, counters or raw/artifact data were rewritten by recovery.

## Closed work in this slice

Major completed issues include:

- #132 — durable Stable Owner Runtime
- #134 — one-command owner refresh
- #136 — supported R05 agreement rebuild
- #138 — dense Google historical HR convergence
- #139 — Garmin Body Battery convergence
- #140 — stale SyncRun recovery
- #141 / #158 — real large-profile backup envelope and restore proof
- #150 — dense Google HR refresh convergence
- #154 — transient Google provider retry reliability
- #156 — semantic identity stabilization

## Normal operating model

```text
accepted code
     |
     v
D:\Garmin\HealthCheck-Stable
  - persistent private owner evidence
  - Weight / Garmin / Google
  - agreement / deterministic analytics
     |
     +--> verified backup
              |
              +--> disposable UAT/runtime clone
```

Stable is not reset for candidate releases. Owner UAT uses a disposable restore/clone. Development Workers never use or inspect the private Stable runtime.

## Next integration/product gate

The next session must not assume the repository lines are already unified.

First:

1. re-read current `main` (handoff checkpoint `b887fceceb85931ad8ead9423c0f86e0cac09291`), `integration/stable-owner-runtime`, and `integration/period-brief-ui-v1`;
2. reconcile accepted Stable-runtime code with current main without losing the completed CI/Period Brief work;
3. preserve exact accepted behavior and rerun the required exact-SHA gates.

Then continue Period Brief:

- #146 — producer/consumer DTO correctness and effective-window truthfulness;
- #133 — compact owner-facing source labels / hierarchy / deduplication;
- #129 — Owner UAT/closeout using a disposable clone of Stable;
- #127 closes with the successful Period Brief UI/UAT slice.

Separate future owner-value work remains intentionally outside that gate, including #147 source freshness, #148 off-site disaster recovery, #153 real Xiaomi S400/openScale E2E verification and #160 Garmin-native training analytics.

## Repository enforcement note

#126 remains blocked by the current private-repository GitHub capability. Until the Owner separately changes that capability, exact-SHA final `checks: SUCCESS` remains a mandatory manual Integrator promotion gate. The repository remains private.
