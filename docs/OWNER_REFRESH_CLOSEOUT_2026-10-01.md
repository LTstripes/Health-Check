# Owner refresh closeout — 2026-10-01

## Decision

**#214 CLOSED / operational PASS.** Phase A historical inventory and the existing manual/configuration proof were already accepted. The Owner has now supplied the missing automatic post-reboot/logon run result and complete final `healthcheck-owner-refresh-v1` report.

This is acceptance of selected-stream automatic collection, **not an all-fresh claim**, a new local deployment or a multi-day reliability guarantee. Residual collection-intent/freshness alignment is tracked in [#238](https://github.com/LTstripes/Health-Check/issues/238).

Authoritative acceptance: [#214 closeout comment](https://github.com/LTstripes/Health-Check/issues/214#issuecomment-5937770810). Earlier interrupted attempts remain interrupted; they are not relabelled after a later success.

## Evidence source and limits

The Owner reported that the final run started automatically after reboot/logon. Task Scheduler read-back showed start `2026-10-01 20:44:59` in Owner Windows local time, `State=Ready`, `LastTaskResult=0`, next daily run `2026-10-02 10:30`.

The supplied final report was parsed completely. No separate Scheduler event-log audit or new direct Stable SQL inventory was performed for closeout. The report's existing read-only persisted freshness projection is the read-back evidence. The private report, internal sync-run identifiers, measurements, detailed daily counts and provider payloads are not published here.

Last observed local Owner checkout: `aafc407c1760780e82a5ae922a93b4d4d9fdfd0e`. Repository checkpoint at acceptance: `4029fd8c70e5bde0120bdf7902f2016faec118ed`, exact-main CI `36820492189` SUCCESS. A safe local update to newer main has not yet been evidenced. GitHub merge does not update the Owner laptop or restart its processes.

## Automatic run

| Fact | Observed result |
| --- | --- |
| Operation / contract | `owner-refresh` / `healthcheck-owner-refresh-v1` |
| Overall result | `succeeded` |
| Inclusive window | 2026-09-25 through 2026-10-01; seven days |
| Garmin normal | succeeded; all 64 reported attempts succeeded |
| Garmin Training | succeeded |
| Google normal | succeeded; all eight selected-stream attempts succeeded |
| Fixed wearables-sleep reconciliation | succeeded |
| Reported attempt errors / remaining Google cursors | none |
| High-frequency Google HR | OFF in wrapper; absent from actual selected streams; HR-by-civil-day timing array empty |
| Garmin HR | remained selected |
| Historical backfill | not run |
| Reported privacy flags | false; flags are not permission to publish the complete private report |

The normal Google selection remains exactly `sleep`, `hrv`, `daily_hrv`, `daily_resting_hr`, `spo2`, `daily_spo2`, `respiratory_rate_sleep`, `daily_respiratory_rate`. Fixed wearables-sleep reconciliation is a separate required layer.

### Measured timing

| Phase | Monotonic duration (ms) |
| --- | ---: |
| Garmin normal | 488773 |
| Garmin Training | 204333 |
| Google normal | 211737 |
| Fixed wearables sleep | 177036 |
| Freshness evaluation | 61899 |
| Total | 1143819 |

Total: **19m03.819s**. These are measurements of this run, not a promise for future daily runs. The earlier manual selected-stream run was 35m32.734s under different conditions; no controlled speedup percentage is claimed.

## Freshness is not silently changed

The actual report says:

- Owner aggregate: `stale`.
- Garmin aggregate: `fresh`.
- Google aggregate: `stale`.
- Exactly one actionable item: `google:heart_rate / refresh_overdue / stale`.
- Optional Garmin `hrv_status` and `resting_heart_rate`: `unknown / invalid_chronology`.
- The other listed optional details: `fresh`.

The only actionable item is the stream intentionally disabled by the Owner. Its retained historical evidence can truly be old, while automatic acquisition of all selected streams succeeds. These are different facts. #238 must connect explicit, reversible collection intent to the shared freshness projection without making an omitted one-off stream selection hide real failures. Until then, retain the report's stale/unknown values and explain the cause; do not label the whole result fresh, enable HR for a green badge, erase history or call the missing history provider-empty.

## What remains unproven

This closeout does not establish graceful cancellation, operation throughout sleep, exactly one execution per day, independent physical-device attribution or continuous multi-day reliability. `IgnoreNew` prevents overlap, not sequential additional logon runs. An old LastRunTime plus a sleeping/off laptop was not proof of seven active hours; the earlier inference of a hang from that alone was unsupported. Likewise, the earlier run's exact completion state was not reconstructed simply from a later reboot.

The report does not prove that every received point reached a sensor's latest possible timestamp, or that historical coverage is complete. No independent device-source reassignment or canonical-data repair was performed.

## Next work

1. #215: one real private Owner-authored Context note and supported read-back. No invented diary content.
2. #238: bounded collection-intent/freshness contract checkpoint, then implementation and risk-appropriate review.
3. #148: protected off-site publication/retention and clean recovery rehearsal.

#215 and read-only #238 design can proceed independently. UI #172/#189 remains deferred; #228 remains research-accepted/implementation-parked; #153 remains optional compatibility. No new broad backfill or HR re-enable is authorized by this closeout.
