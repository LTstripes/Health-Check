# Owner refresh

`owner-refresh` is the bounded command for refreshing the established Owner Garmin and Google profile over one shared inclusive local-date window. It reuses provider services, preserves separate checkpoints/semantics, and returns one operational JSON report.

## Accepted execution layers

Under the established-runtime overlap lock the command runs:

1. normal Garmin incremental sync;
2. bounded Garmin Training sync, reusing the Garmin auth/client;
3. normal Google refresh, using default production streams/list semantics unless optional CLI stream/query overrides select this layer;
4. fixed sleep-only Google refresh with `query_mode=reconcile` and `dataSourceFamily=google-wearables`, maintaining the R05 exploratory sleep layer.

Normal Google stream selection does not turn off Garmin, Garmin Training or the fixed wearables-sleep layer. Overall success requires the required substeps to converge as succeeded/empty under their contracts. Preserve partial/failed/reauth and actual freshness honestly.

When selected in list mode, high-frequency `heart_rate` is split into civil days, newest first, with individual checkpoint/staging epochs. Each day may use at most two bounded continuation calls after the initial operation; head-page revalidation and 40-page/80-request per-call limits remain. Aggregate counters can exceed one call's limit. A final attempt entry is not a count of all continuation operations. Nonconverged days remain resumable/unknown and stop older-day work.

#206/#207 reduced local promotion/setup work; #212 added narrowly classified bounded transport retries. They did not make refresh a new-records-only operation. The accepted routine horizon is seven days; it deliberately rechecks prior data for corrections. Do not shrink it or skip a selected stream silently to make a run look faster.

## Owner-selected normal profile — 2026-09-29

The local Ops runner defaults **high-frequency Google `heart_rate` to OFF** by explicit Owner decision. Garmin remains the primary high-frequency HR source. The retained normal Google selection is:

```text
sleep
hrv
daily_hrv
daily_resting_hr
spo2
daily_spo2
respiratory_rate_sleep
daily_respiratory_rate
```

The runner supplies these via repeated `--stream` arguments. It adds `heart_rate` only when its local enable flag exists. This selection does not remove historical Google HR records, disable HRV/resting-HR summaries, change provider/query/correction semantics, or disable fixed wearables-sleep reconciliation.

**The bare repository CLI default is unchanged and includes high-frequency HR.** For the Owner's selected profile, run the Scheduler task or its Ops wrapper. A direct `owner-refresh` command without the stream selection bypasses the local flag.

The historical Google HR gap is intentionally not a backfill target while disabled. Re-enabling affects future selected windows; it does not silently backfill all missing history. Review dates/coverage before a separate bounded historical operation. Disabled/unrequested evidence must not be described as complete or provider-empty.

## Local assignment

| Role | Owner-local location |
| --- | --- |
| Accepted-code operation checkout | `D:\Garmin\HealthCheck-Owner-Main` |
| Durable private data | `D:\Garmin\HealthCheck-Stable` |
| Operational wrapper | `D:\Garmin\HealthCheck-Ops\owner-refresh-scheduled.ps1` |
| Enable Google sample HR | `D:\Garmin\HealthCheck-Ops\google-hr.enabled` |
| Private operational logs | `D:\Garmin\HealthCheck-Stable\logs\owner-refresh-*.log` |
| Task name | `Health-Check owner refresh` |

These are operational assignments, not Worker development locations. Never use reset/clean against an existing Owner checkout as routine setup. GitHub merges do not deploy automatically; verify an accepted SHA, clean local state and idle Owner processes before an explicit safe code update. This documentation refresh does not change the local task, runner, code checkout or Stable data.

## Manual controls using the existing task

Run under the same Windows account that established the protected sessions:

```powershell
Start-ScheduledTask -TaskName 'Health-Check owner refresh'
Get-ScheduledTask -TaskName 'Health-Check owner refresh' | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName 'Health-Check owner refresh' |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

HR toggle, applied by the runner at its next start:

```powershell
# ON
New-Item -ItemType File -Path 'D:\Garmin\HealthCheck-Ops\google-hr.enabled' -Force | Out-Null
# OFF
Remove-Item -LiteralPath 'D:\Garmin\HealthCheck-Ops\google-hr.enabled' -ErrorAction SilentlyContinue
```

Disable/enable future task execution:

```powershell
Disable-ScheduledTask -TaskName 'Health-Check owner refresh'
Enable-ScheduledTask -TaskName 'Health-Check owner refresh'
```

The task exposes `Stop-ScheduledTask`, but real in-flight Stop was not validated in the operational check. Do not present it as graceful cancellation or exercise it just for a checkbox. An interruption requires checking final task/log state and existing supported recovery before any further mutation; never kill all Python processes or edit SQLite directly.

Watching a log with `Get-Content -Wait` is separate from running the refresh. Ending that viewer is not a tested cancellation mechanism for the provider process.

## Direct CLI / explicit profile selection

From an accepted checkout, an explicit seven-day command is:

```powershell
uv run --locked python -m healthcheck.cli owner-refresh `
  --data-dir $OwnerDataDir `
  --trailing-window-days 7
```

This example uses the full default normal Google selection, including HR. To match the local HR-OFF profile, supply all eight retained `--stream` values or use the existing Ops runner/task above.

`--date YYYY-MM-DD` fixes the inclusive end date; otherwise local date is used. Windows are bounded to 1–14 days. The command requires an established external profile/config/migrated database and fails closed rather than creating a profile after a mistyped path. Overlapping supported operations on the same profile are rejected by the external-runtime lock.

No historical backfill, reprocess or reauthentication is implied by routine refresh.

## Scheduler configuration and remaining proof

Owner/Codex reported this local configuration on 2026-09-29:

- daily 10:30 in Windows local time, plus a trigger at Owner logon;
- interactive Owner account, limited privileges;
- `StartWhenAvailable=True`, `MultipleInstances=IgnoreNew`;
- battery start allowed; switching to battery does not itself stop the task;
- no deliberate wake requirement (`WakeToRun=False` in the observed configuration);
- the existing wrapper and HR flag selection were retained; protected secrets are not task arguments.

Battery permissions are not proof of execution through system sleep. A closed lid/sleep/offline period and Windows logon/unlock are different conditions; successful late/logon execution still needs observed evidence. The logon trigger may also request an extra run after a daily run has already finished; IgnoreNew only prevents simultaneous instances. No once-per-day de-duplication is claimed.

### Evidence / #214 acceptance

- Phase A historical inventory accepted; no broad Garmin/all-stream Google rebuild justified.
- 2026-09-28 ten-day full catch-up: succeeded; total 117m06.216s. This is not a daily runtime promise.
- First automatic attempt during operational testing: `0xC000013A`, provider substeps reportedly finished but no final JSON. Cause unknown; Disable/Enable testing was concurrent context, not proven causation.
- Subsequent manual Scheduler run: exit 0, all four layers succeeded, HR OFF, no new sample-HR observations; 35m32.734s. Latest persisted structural dates were 2026-09-29 across Garmin, Google, Training and wearables sleep.
- **Still required:** one untouched automatic daily/logon-triggered run with final JSON, task outcome, selected streams and truthful freshness. Manual success does not close this gate.

These are sanitized Owner/Codex reports; they do not authorize uploading local logs, databases, tokens or measurements to GitHub. Confirm the active run/result rather than using file modification time or latest data date alone as proof of completion.

The two runtime samples differ in window, data and provider conditions. Do not claim a controlled percentage speedup or promise 10–20 minute daily runs from them.

Sources: [#214 operational follow-up](https://github.com/LTstripes/Health-Check/issues/214#issuecomment-5896581801), [#199 final performance closeout](https://github.com/LTstripes/Health-Check/issues/199#issuecomment-5859263862). No further live run was executed by this documentation refresh.
