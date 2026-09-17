# CI Feedback / Reliability Maintenance Closeout — 2026-09-17

## Status

The bounded CI maintenance track is complete at the implementation level:

- #123 — bounded verification, evidence and cancellation semantics — **CLOSED / ACCEPTED**;
- #124 — balanced Linux lanes + fail-closed completeness gate — **CLOSED / ACCEPTED**;
- #125 — focused Windows runtime/auth smoke with mandatory native DPAPI execution — **CLOSED / ACCEPTED**;
- #126 — server-side required-check / branch-protection enforcement — **OPEN, BLOCKED / OWNER DECISION REQUIRED** because the current GitHub capability does not provide private-repository branch protection/rulesets.

This work changed CI/repository verification only. It did not change health semantics, provider contracts, canonical-data rules, analytics formulas or Owner runtime data.

## Before

The accepted pre-parallel reference was one largely serial Ubuntu verification path. A representative full remote run took about **5m02s**. A green run proved the suite passed, but it did not yet provide the final set of guarantees introduced by this track:

- no stable exact-nodeid partition reconciliation across independent lanes;
- no dedicated fail-closed aggregate verdict over retained same-run evidence;
- no mandatory native Windows DPAPI execution;
- no real Windows `start.ps1` process/HTTP smoke;
- no server-side protection requiring the final aggregate check.

## #123 — trustworthy evidence and bounded feedback

#123 established the evidence/gating substrate used by the later work:

- exact run/attempt/event/ref/HEAD/tree/lock provenance;
- retained JUnit/log/status/timing evidence with explicit consistency checks;
- fail-closed behavior for missing, malformed or contradictory mandatory evidence;
- task/PR supersession without collapsing distinct canonical/integration runs into one concurrency slot;
- bounded timing evidence instead of relying on a green label alone;
- repair of the observed pre-existing timestamp-sensitive privacy test flake.

Accepted candidate: `e1767bbd6820f183b6e70e78c4f843bcbbd259af`.

Evidence:

- exact task CI `35183585714` — SUCCESS;
- exact integration CI `35184385269` — SUCCESS.

## #124 — parallel Linux lanes without losing completeness

#124 removed the dominant serial wall-time stall while preserving full-suite semantics.

The Linux suite became three ordinary serial pytest lanes started independently alongside the quality job:

- `test (garmin)`;
- `test (core-sleep)`;
- `test (app-ingest)`.

A checked manifest owns every discovered `tests/**/test_*.py` file exactly once. Independent collection/execution evidence is reconciled by exact nodeid and multiplicity. Missing, overlapping, stale or substituted inventory fails the final gate.

The stable final job is named **`checks`**. It is the aggregate verdict rather than a fourth full serial pytest run.

Accepted candidate/integration SHA: `54ba37adc79dfb4cf0c5997a758f868a32d12af6`.

Evidence:

- task CI `35203141032` — SUCCESS, about **2m13s**;
- integration CI `35207859309` — SUCCESS, about **2m32s**;
- candidate inventory: `881` exact nodeids, with `880 passed + 1` exact allowlisted non-Windows DPAPI skip;
- final `checks` reconciled the exact mandatory evidence rather than trusting constituent job labels.

The material performance objective was therefore considered complete. No xdist, fixture-template caching, docs-only bypass or second-level setup/cache tuning was justified by the remaining measured wall time.

## #125 — focused real Windows reliability coverage

#125 closed the platform/auth/runtime gap without duplicating the full suite on Windows.

The final accepted design performs on a GitHub-hosted Windows runner:

- the designated native Windows user-scoped DPAPI regression, which must **execute and pass**; Windows-side unavailability is a failure, not a permissive skip;
- a real PowerShell `scripts/start.ps1` launch against external synthetic runtime paths containing spaces;
- an ingest-disabled scenario proving the UI is healthy while the ingest surface remains absent;
- an ingest-enabled scenario proving UI and ingest are separate loopback-only surfaces with the existing route contract;
- finite readiness/HTTP waits;
- root process ownership established by captured PID + Name + CommandLine;
- root-scoped tree termination using `taskkill /PID <verified-root> /T /F`, never process-name-wide killing;
- post-cleanup verification that the owned root is gone, expected ports are closed and the synthetic runtime is removed;
- schema-v2 evidence bound to exact workflow provenance and consumed by final `checks`.

Real Windows runs were valuable precisely because they exposed lifecycle races that synthetic/local reasoning had not proved. After four distinct cleanup-edge failures, the Integrator stopped the micro-patch loop and required a bounded root-tree redesign rather than growing more per-descendant PID logic. The final port probe was also changed from connect/refusal inference to a deterministic loopback bind/listener probe.

Final accepted candidate: `e7edf3d9c04f137a77f6345a183e87872bac62a7`.

Evidence:

- exact task CI `35232981949` — SUCCESS;
- Windows designated DPAPI node: `1 passed / 0 skipped`;
- final task gate: `checks PASS: 890 exact nodeids reconciled across all mandatory jobs` and `WINDOWS_SMOKE_EVIDENCE: PASS`;
- exact integration CI `35235216797` — SUCCESS on the same SHA/tree;
- integration wall: about **2m48s**;
- integration final gate again reported `890 exact nodeids` and `WINDOWS_SMOKE_EVIDENCE: PASS`.

The independent final reviewer used Grok 4.6 as a different model family from the implementation route and returned ACCEPT; the Integrator separately re-read the actual code, evidence, refs and CI before integration.

## Net result — time

Representative accepted comparison:

| Stage | Remote wall |
| --- | ---: |
| Pre-parallel accepted full-run reference | ~5m02s |
| #124 task candidate, three Linux lanes | ~2m13s |
| #124 integration | ~2m32s |
| #125 integration, including focused Windows | ~2m48s |

Using the pre-parallel `5m02s` reference and final Windows-inclusive `2m48s` integration run:

- `302s -> 168s`;
- about **134 seconds less wall time**;
- about **44% reduction**.

Runner variance means these are not benchmark-lab numbers, but the dominant serial wait is clearly gone. Windows reliability coverage was added while retaining most of the speedup because it runs independently of the Linux lanes.

## Net result — quality

The larger gain is qualitative:

1. **Completeness is explicit.** The project proves the expected Linux inventory by exact nodeids/multiplicity rather than assuming that three green subsets equal the full suite.
2. **Evidence is provenance-bound.** Final verdicts are tied to exact SHA/tree/run/ref/attempt and retained reports.
3. **The final verdict is fail-closed.** Missing/malformed/cross-run evidence, mandatory job failure/skip/cancel, unexpected skips/xfails or partition drift cannot silently become a green `checks` result.
4. **Windows is real, not inferred.** Native DPAPI, PowerShell startup, loopback HTTP surfaces, runtime paths with spaces and cleanup run on a real Windows hosted runner.
5. **Iteration is cheaper.** Workers should use targeted checks while coding, then pay for one stabilized candidate gate rather than repeatedly running an unchanged full suite.
6. **Integration is independently re-proven.** Accepted task work receives an exact integration gate before canonical publication, and `main` receives its own exact post-promotion gate.

## #126 — server-side enforcement blocker

The accepted aggregate check exists and is named `checks`, but the current private repository is not server-side protected.

Verified state before this closeout:

- repository remains private;
- `main` reports `protected: false`;
- required status-check enforcement is off;
- the Rulesets API returns HTTP 403 with `Upgrade to GitHub Pro or make this repository public to enable this feature.`;
- an independent Owner-authorized token review with repository admin capability received the same private-repository plan/capability blocker for classic branch protection.

Decision:

- do **not** make the repository public;
- do **not** purchase/upgrade a GitHub plan as an implicit engineering action;
- do **not** imitate branch protection with workflow-YAML tricks;
- leave #126 open as `BLOCKED / OWNER DECISION REQUIRED`.

### Manual gate while #126 is blocked

Until the Owner separately changes repository capability:

1. the exact SHA being advanced to integration or `main` must have final GitHub Actions `checks: SUCCESS`;
2. constituent quality/Linux/Windows jobs are not a substitute for final `checks`;
3. only the Integrator advances shared integration/canonical refs after explicit acceptance;
4. force-push/deletion of canonical/integration history is process-prohibited even though GitHub cannot enforce it server-side;
5. a green CI workflow is not evidence that branch protection is enabled.

If private-repository protection later becomes available, the minimal intended policy is to protect canonical `main`, require the final `checks` aggregator in strict/up-to-date mode, apply protection to admins, and disallow force-push/deletion. Requiring every constituent lane separately or protecting temporary task branches is unnecessary.

## Operating rule after closeout

The normal verification rhythm is now:

```text
targeted iteration
    -> stabilized exact candidate gate
    -> Integrator ACCEPT
    -> exact integration gate
    -> canonical main promotion
    -> exact main gate
```

Do not reopen CI-performance work because a few seconds might be removable. Revisit only when measured development feedback again shows a material bottleneck or the current verification contracts become a demonstrated maintenance problem.

## References

- #123 — bounded verification / evidence / cancellation semantics
- #124 — three balanced Linux lanes + fail-closed completeness gate
- #125 — focused Windows runtime/auth smoke + mandatory native DPAPI
- #126 — required-check/branch-protection Owner action (open blocker)
- exact #125 integration CI: `35235216797`
