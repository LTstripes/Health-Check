# Owner refresh

`owner-refresh` is the bounded command for refreshing the established Owner Garmin and Google profile over one shared inclusive local-date window. It reuses provider services, preserves separate checkpoints/semantics, and returns one operational JSON report.

## Accepted execution layers

Under the established-runtime overlap lock the command runs:

1. Normal Garmin incremental sync.
2. Bounded Garmin Training sync, reusing the Garmin auth/client.
3. Normal Google refresh, using default production streams/list semantics unless optional CLI stream/query overrides select this layer.
4. Fixed sleep-only Google refresh with `query_mode=reconcile` and `dataSourceFamily=google-wearables`, maintaining the R05 exploratory sleep layer.

Normal Google stream selection does not turn off Garmin, Garmin Training or fixed wearables sleep. Overall success requires required substeps to converge as succeeded/empty under their contracts. Preserve partial/failed/reauth and actual freshness honestly.

When selected in list mode, high-frequency `heart_rate` is split into civil days, newest first, with individual checkpoint/staging epochs. Each day may use at most two bounded continuation calls after the initial operation; head-page revalidation and 40-page/80-request per-call limits remain. Aggregate counters can exceed one call's limit. A final attempt entry is not a count of all continuation operations. Nonconverged days remain resumable/unknown and stop older-day work.

#206/#207 reduced local promotion/setup work; #212 added narrowly classified bounded transport retries. They did not make refresh a new-records-only operation. The accepted routine horizon is seven days; it deliberately rechecks prior data for corrections. Do not shrink it or skip a selected stream silently to make a run look faster.

## Owner-selected normal profile

Since the Owner decision of 2026-09-29, the local Ops runner defaults **high-frequency Google `heart_rate` to OFF**. Garmin remains the primary high-frequency HR source. Retained normal Google selection:

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

The runner supplies these via repeated `--stream` arguments. It adds `heart_rate` only when its local enable flag exists. This does not remove historical Google HR records, disable HRV/resting-HR summaries, change provider/query/correction semantics or disable fixed wearables-sleep reconciliation.

**The bare repository CLI default is unchanged and includes high-frequency HR.** Use the Scheduler task or Ops wrapper for this selected profile. A direct command without explicit stream selection bypasses the local flag.

The historical Google HR gap is intentionally not a backfill target while disabled. Re-enabling affects future selected windows, not all missing history; review dates/coverage before a separate bounded historical operation. Disabled/unrequested evidence must not be described as complete or provider-empty.

## Local assignment and deployment state

| Role | Owner-local location |
| --- | --- |
| Accepted-code operation checkout | `D:\Garmin\HealthCheck-Owner-Main` |
| Durable private data | `D:\Garmin\HealthCheck-Stable` |
| Operational wrapper | `D:\Garmin\HealthCheck-Ops\owner-refresh-scheduled.ps1` |
| Enable Google sample HR | `D:\Garmin\HealthCheck-Ops\google-hr.enabled` |
| Private operational logs | `D:\Garmin\HealthCheck-Stable\logs\owner-refresh-*.log` |
| Task name | `Health-Check owner refresh` |

These are operational assignments, not Worker development locations. Never use reset/clean as routine setup. GitHub merges do not deploy automatically. Last observed local HEAD was `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`; only remote-tracking origin/main was fetched to the newer repository checkpoint. A subsequent local update has not been evidenced.

Before an explicit safe code update verify accepted target SHA, clean local state and idle relevant Owner processes, including refresh and application processes using that checkout. Do not switch/pull mid-run. This closeout does not itself modify the task, wrapper, checkout or Stable data.

## Manual controls using the existing task

Run under the same Windows account that established protected sessions:

```powershell
Start-ScheduledTask -TaskName 'Health-Check owner refresh'
Get-ScheduledTask -TaskName 'Health-Check owner refresh' | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName 'Health-Check owner refresh' |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

HR toggle, applied at the next runner start:

```powershell
# ON only after an explicit Owner choice
New-Item -ItemType File -Path 'D:\Garmin\HealthCheck-Ops\google-hr.enabled' -Force | Out-Null
# OFF
Remove-Item -LiteralPath 'D:\Garmin\HealthCheck-Ops\google-hr.enabled' -ErrorAction SilentlyContinue
```

Disable/enable future task execution:

```powershell
Disable-ScheduledTask -TaskName 'Health-Check owner refresh'
Enable-ScheduledTask -TaskName 'Health-Check owner refresh'
```

Real in-flight `Stop-ScheduledTask` was not validated by the operational check. Do not present it as graceful cancellation or exercise it for a checkbox. Interruption requires checking final task/log state and supported recovery before further mutation; never kill all Python processes or edit SQLite directly.

Watching a log with `Get-Content -Wait` is separate from running refresh. Ending that viewer is not a tested cancellation mechanism for the provider process.

## Direct CLI / explicit profile selection

From an accepted checkout:

```powershell
uv run --locked python -m healthcheck.cli owner-refresh `
  --data-dir $OwnerDataDir `
  --trailing-window-days 7
```

This uses the full default normal Google selection, including HR. To match HR-OFF, supply all eight retained streams or use the existing Ops task/wrapper.

`--date YYYY-MM-DD` fixes the inclusive end date; otherwise local date is used. Windows are bounded to 1–14 days. The command requires an established external profile/config/migrated database and fails closed rather than creating a profile after a mistyped path. Overlapping supported operations on the same profile are rejected by the external-runtime lock. Routine refresh does not imply historical backfill, reprocess or reauthentication.

## Scheduler configuration and accepted automatic proof

Owner/Codex reported configuration:

- Daily 10:30 Windows local time, plus Owner logon.
- Interactive Owner account, limited privileges.
- `StartWhenAvailable=True`, `MultipleInstances=IgnoreNew`.
- Battery start allowed; switching to battery does not itself stop the task.
- `WakeToRun=False` in the observed configuration.
- Existing wrapper/HR flag retained; protected secrets are not task arguments.

Battery permissions do not prove execution through sleep. A closed lid, sleep/offline interval, full shutdown, logon and unlock are different conditions. LastRunTime alone is not active CPU/wall execution duration; a small log without progress output alone is not proof of a hang. IgnoreNew prevents overlap, not sequential additional logon runs or once-per-day duplicates.

### #214 acceptance — 2026-10-01

**CLOSED / operational PASS.** The Owner reported automatic post-reboot/logon execution. Scheduler read-back: start 20:44:59, later `Ready`, result 0. The complete final report says `refresh.status=succeeded`, seven-day window, all four acquisition layers succeeded, eight non-HR normal Google streams and no HR-by-civil-day work. Monotonic duration: **19m03.819s**.

The report's persisted freshness projection is the read-back evidence; no separate Scheduler event-log audit or fresh direct SQL inventory was performed. Last observed local code remains the older accepted checkout; this result does not prove deployment of later GitHub work.

**Important residual:** actual freshness is Owner/Google `stale`, Garmin `fresh`. The sole actionable reason is disabled `google:heart_rate / refresh_overdue`; optional Garmin HRV-status/resting-HR chronology remains unknown. [#238](https://github.com/LTstripes/Health-Check/issues/238) owns an explicit collection-intent/freshness contract. Do not relabel these values fresh, silently filter one-off omitted streams, delete old evidence or re-enable HR to obtain a green aggregate.

Earlier evidence remains historical:
- Ten-day full catch-up succeeded in 117m06.216s.
- One early automatic attempt ended with `0xC000013A` and no final JSON; cause unknown.
- Later manual selected-stream Scheduler run succeeded in 35m32.734s.
- Intervening shutdown/reboot context does not prove active runtime duration or a final outcome for an earlier attempt.

These different runs are not a controlled speed benchmark or future runtime promise. The one completed automatic run does not prove graceful cancellation, sleep/resume continuity or multi-day reliability.

Full sanitized evidence and limitations: [Owner Refresh Closeout](OWNER_REFRESH_CLOSEOUT_2026-10-01.md), [#214 acceptance](https://github.com/LTstripes/Health-Check/issues/214#issuecomment-5937770810), [earlier operational follow-up](https://github.com/LTstripes/Health-Check/issues/214#issuecomment-5896581801), [#199 performance closeout](https://github.com/LTstripes/Health-Check/issues/199#issuecomment-5859263862).

Keep private logs local. Public GitHub receives only sanitized technical summaries, not entire logs, internal run IDs, raw values, tokens or databases. No additional live refresh was executed by this documentation update.
