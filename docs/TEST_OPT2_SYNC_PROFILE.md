# TEST-OPT2 #274: measured NO-GO

Outcome: **NO-GO for a retained test optimization**. The only delivered change is
this profiling record. The experimental three-line removal from the Google
result-inspection helper was restored byte-for-byte; no test, production source,
schema, dependency, skip, lane assignment or CI routing change remains.

Authority: [issue #274](https://github.com/LTstripes/Health-Check/issues/274) and
[Integrator launch](https://github.com/LTstripes/Health-Check/issues/274#issuecomment-5979032695).
Pinned baseline/target: `main @ a1c8e1a1bc25de6a3ec7b0a8580739f13ca5b0a0`.
Delivery branch: `task/test-opt2-sync-fixtures`. Independent review and Integrator
acceptance remain separate; no PR, merge, dependency update or #275 work is included.

## Method and comparable measurements

One serial local Python process at a time, Windows 11 build 26200, CPython 3.12.14,
uv 0.12.17, pytest 9.0.3, SQLAlchemy 2.0.52 and Alembic 1.19.1. The task has its
own locked environment/cache and external synthetic runtime/temp directories.
`uv sync --frozen --python 3.12` resolved the unchanged baseline lockfile:
`8b70606d5df2314d9a1ac8873b1abe6b4a13deaec392c45e6b87be3a46b4236f` (SHA-256).
No Dependabot #271 changes were taken.

A temporary external harness times real calls with `perf_counter`, retaining
per-node pytest setup/call/teardown reports and JUnit. It wraps migration,
runtime-directory preparation, fixture builders, payload storage, sync `_run`,
engine disposal and lock entry/exit, always invoking the original function.
Nested durations have exclusive accounting; inclusive columns below must not
be added together. There are no mocked sync results or migration guards.

Each invocation starts a new process with fresh empty runtime/temp directories.
Installed packages and OS file caches are warm; OS caches were not flushed.
The two comparable Google invocations use the same harness, parameters, exact
59-nodeid multiset, versions and equally short temp paths. They are targeted
suite runs, not local full-repository suites.

| Target | Variant | Cases/result | Pytest terminal | Harness wall | Setup / call / teardown sum |
| --- | --- | --- | ---: | ---: | ---: |
| Garmin incremental sync | baseline | 68 passed | 125.16 s | 133.121 s | 0.264 / 120.899 / 0.030 s |
| Google sync/backfill | baseline, short temp | 59 passed | 121.53 s | 124.377 s | 0.289 / 120.298 / 0.025 s |
| Google sync/backfill | experimental helper | 59 passed | 123.66 s | 127.477 s | 0.251 / 121.292 / 0.027 s |

The experiment was the baseline plus deletion of the local `migrate_database`
import and its call in `_session()`. All 30 helper invocations inspect results
after a real production sync/backfill operation has initialized the database.
Production startup, migration, lock, persistence and replay calls were retained.
No other optimization was attempted.

## Measured cause and decision

| Measured component | Garmin baseline | Google baseline | Google experiment |
| --- | ---: | ---: | ---: |
| Fresh schema/migrations, inclusive | 77.322 s / 64 calls | 84.472 s / 69 calls | 87.906 s / 69 calls |
| Existing DB migration in production, inclusive | 0.488 s / 13 calls | 1.315 s / 37 calls | 1.396 s / 37 calls |
| Extra migration in result inspection, inclusive | absent | 1.382 s / 30 calls | absent |
| Runtime directory/file preparation, exclusive | 0.764 s | 1.543 s | 1.137 s |
| Selected synthetic fixture builders, exclusive | 0.091 s | 0.009 s | 0.010 s |
| Real sync `_run`, inclusive | 39.598 s / 77 calls | 29.134 s / 110 calls | 28.324 s / 110 calls |
| Payload file storage within sync | 5.330 s | 4.510 s | 4.358 s |
| Lock acquisition / release | 0.210 / 0.068 s | 0.214 / 0.088 s | 0.190 / 0.097 s |
| Engine disposal across all paths, inclusive | 1.579 s | 1.916 s | 1.943 s |

The material preparation cost is **fresh production Alembic schema creation
inside test call**, not pytest setup or fixture JSON parsing. Remaining call
time includes assertions, inspection queries, other data construction,
serialization and work outside the measured functions; it is not all attributed
to fixture preparation. Engine disposal includes disposal nested in migrations;
pytest teardown is reported separately above.

Removing inspection migrations eliminates only 1.382 s of measured baseline
work. The experimental suite was 2.13 s slower by pytest terminal time, while
fresh schema creation alone varied by 3.434 s. This single pair establishes no
repeatable end-to-end gain. The small removable cost is negligible relative to
the dominant schema bootstrap and is masked by observed variation: the narrow
fix is rejected, with no claimed implemented savings.

A session-local schema template would address the dominant cost, but adds
per-scenario bootstrap decisions and SQLite snapshot/WAL/lifetime/copy isolation
machinery. It was not implemented or validated in this bounded small-fix task;
its potential savings and safety remain unverified. Fresh-start, lock/lifecycle,
setup-error and migration boundaries were preserved as they stood. Existing
retry clock/sleeper injection and assertions were unchanged; no real lock wait
was replaced with simulated time.

## Isolation, scope and checks

- Exact Google before/experiment nodeid multisets match: 59 cases, zero skips,
  no scenario or assertion edits. Garmin baseline has 68 cases, zero skips.
- An external synthetic isolation probe passed on both the experiment and
  restored baseline: independent DB/session paths, commit visibility, rollback,
  absence of cross-runtime cursor leakage, populated record/metric relationships,
  enforced FK rejection, clean `foreign_key_check`, WAL checkpoint, disposed
  Windows database handles (rename round trip) and complete probe cleanup.
- Four restored Google persistence/replay/failure/page-order scenarios also ran
  in reversed collection order: **4 passed in 13.30 s**.
- The restored Google source SHA-256 is
  `f59aca5524981b7cb0214be0b7e5b89dba2b8039567ce5c7d21052fe2d4e87d6`, matching
  the baseline bytes. Experiment SHA-256:
  `6e93e075fb7acad400c05c54ebbe10b6cf26aef25d2b386c243ddd0b5c000caa`.
- No shared mutable database/session/payload was introduced. Each scenario keeps
  its original independent synthetic runtime; no cached or Owner schema is used.
- `src/`, migrations, `pyproject.toml`, `uv.lock`, `ci/test-lanes.json` and workflows
  are unchanged. Full collection/lane-union and declared-skip checks use the
  existing exact-candidate CI gate after the profiling record freezes.

## Commands, retained evidence and limitations

The external evidence package contains `profile_suite.py`, its JSON/JUnit/log
outputs, the rejected `experiment.diff`, `isolation_probe.py` and probe logs.
The harness SHA-256 for the comparable Google runs is
`f7b22d924cd4d6cd0111ca331c69743e4b473042bc4b7554d486540bbff3ca83`.
With `$EvidenceRoot` denoting the task's external synthetic evidence directory,
the actual profiling invocations were:

```powershell
& "$EvidenceRoot/venv312/Scripts/python.exe" "$EvidenceRoot/profile_suite.py" baseline-garmin tests/test_garmin_incremental_sync.py
& "$EvidenceRoot/venv312/Scripts/python.exe" "$EvidenceRoot/profile_suite.py" google-b1 tests/test_google_sync_backfill.py
& "$EvidenceRoot/venv312/Scripts/python.exe" "$EvidenceRoot/profile_suite.py" google-c1 tests/test_google_sync_backfill.py
& "$EvidenceRoot/venv312/Scripts/python.exe" "$EvidenceRoot/isolation_probe.py"
```

The harness uses `-q --durations=10 --basetemp <external-temp> --junitxml
<external-evidence>`. Baseline Git SHA is the pinned SHA above; the experiment
was its uncommitted three-line helper delta, preserved separately, then restored.
The final branch SHA and single final CI run are supplied in the Worker handoff.

The first Google profile used a longer temp path and ended **58 passed / 1 failed**
at a 260-character temporary payload path (`FileNotFoundError`). That run is
retained as failed environmental evidence and excluded from the comparison.
The same failed node passed at the shorter path (**1 passed in 5.14 s**) before
the successful 59-case baseline was repeated. An initial reverse-order probe
plugin was unhashable and failed before tests; using a hashable plugin repaired
the probe. These failures are not relabeled as passes or production fixes.

Reference [CI 37188050103, attempt 1](https://github.com/LTstripes/Health-Check/actions/runs/37188050103)
was read back as SUCCESS on the exact baseline. Its Linux JUnit testcase sums
are Garmin 52.350 s / 68 cases and Google 51.766 s / 59 cases; garmin lane terminal
time 196.98 s and whole workflow 4:06, as recorded in the issue. These hosted
reference timings are separate from the instrumented local Windows measurements.
No whole-CI/application/monthly/cost savings are claimed.

CBM: used `D-Codex-index-sources-health-check-main` to locate the sync preparation
helpers; checked against current pinned-worktree source. Best-effort index
freshness was missing for the cited paths; no index refresh was performed.
