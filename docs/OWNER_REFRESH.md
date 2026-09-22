# Owner refresh

`owner-refresh` is the bounded, manual command for refreshing the established
owner Garmin and Google profiles over one shared inclusive local-date window.
It reuses the existing provider sync services, preserves their separate
checkpoints and semantics, and returns one privacy-safe JSON report.

Under the same established-runtime overlap lock the default command runs three
required refresh steps:

1. existing bounded Garmin incremental sync;
2. existing normal bounded Google refresh (default production streams / list
   semantics unless optional CLI stream or query overrides are supplied for
   this layer only);
3. fixed sleep-only Google refresh with `query_mode=reconcile` and
   `dataSourceFamily=google-wearables`, which keeps the R05 exploratory
   `account_wearables_sleep_observations_v1` evidence layer current.

Scheduled or default use therefore needs no extra manual `--family` /
`--query-mode` command for the wearables-sleep layer. The overall refresh
status is `succeeded` only when every required step converges as
`succeeded` or `empty`; each provider/sub-step outcome is reported honestly.

For normal list-mode Google refresh, `heart_rate` is split into deterministic
civil-day windows and processed newest to oldest. Every day has its own refresh
checkpoint and staging/promotion epoch. A day that reaches the existing bounded
`page_ceiling` can use at most two continuation calls; each continuation
revalidates the head page before resuming its durable cursor. Page size and the
40-page / 80-request per-call caps are unchanged.

Garmin, unrelated normal Google streams, and the fixed `google-wearables` sleep
layer still run once. Non-list Google modes and all non-HR streams retain their
existing full-window behavior. If a day does not converge within its bounded
continuations, it remains unknown and resumable, older days are not attempted,
and the overall result remains `partial`. The normal Google report's
`request_count` is the aggregate across its calls; every attempt's counters stay
scoped to its own capped provider operation.

## Run manually

Run from the Health-Check checkout with the same Windows user account that
established the external profile:

```powershell
uv run --locked python -m healthcheck.cli owner-refresh `
  --data-dir $OwnerDataDir `
  --trailing-window-days 7
```

`--date YYYY-MM-DD` optionally fixes the window end date; otherwise the local
date is used. The trailing window is bounded to 1–14 days. A missing directory,
or a directory without the established Health-Check config and migrated
database, fails closed. The command never bootstraps a new profile because of
a mistyped path. A second refresh for the same profile fails immediately while
the first one holds the external profile lock.

The command does not perform historical backfill or offline reprocess. Use the
existing dedicated commands only when that separate operation is intentional.

## Windows Task Scheduler setup

No scheduled task is created by this repository change. When the Stable Owner
Runtime is established and scheduling is explicitly wanted, create the task
manually in **Task Scheduler**:

1. Create a basic task with a descriptive name such as `Health-Check owner refresh`.
2. Choose a trigger appropriate for the owner, for example daily after the
   device sync is normally complete.
3. Set **Run only when the user is logged on** unless the protected provider
   sessions have been separately proven for another mode.
4. Set the action to start `uv.exe` (or the absolute `uv.exe` path) with
   arguments:
   `run --locked python -m healthcheck.cli owner-refresh --data-dir <OwnerDataDir>`.
5. Set **Start in** to the Health-Check checkout. Keep `<OwnerDataDir>` outside
   the checkout and point it at the already-established owner profile.
6. Save the task without enabling additional retries that could overlap a
   still-running refresh. The command itself also rejects same-profile overlap.
7. Run the action once manually from Task Scheduler and inspect the sanitized
   JSON result and exit code before enabling a recurring trigger.

Scheduling does not authorize reauthentication, historical backfill, provider
scope changes, or live UAT. Credentials and health data remain in the external
user-scoped runtime and are never placed in task arguments or repository files.
