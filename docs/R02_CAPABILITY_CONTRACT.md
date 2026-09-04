# R02 Garmin capability contract

This document freezes the pre-ingestion capability inventory for a Garmin
Vivoactive 5 and the reviewed `python-garminconnect` `0.3.12` source surface.
It is an offline contract only. This issue does not add Garmin authentication,
live calls, token handling, backfill, database/schema work, or an ingestion
adapter.

The matrix has four deliberately separate questions:

1. What the R00 static review says about the physical watch.
2. What Garmin Connect may expose.
3. Which `python-garminconnect` method/field can be used later to retrieve a
   source payload.
4. What remains safe to claim before a payload from the target
   device/account is observed.

The third column never answers the first or fourth. A method or typed field is
not evidence that a Vivoactive 5 produces that metric.

## Matrix

`VERIFIED` and `VERIFIED_CONDITIONAL` below mean the R00 static source/device
review result. `owner_account_verification` is `not_run` for every row in this
issue because no live Garmin account is accessed.

| Code | Stream | Watch/device review | Garmin Connect surface | Client surface (`0.3.12`) | Static status |
| --- | --- | --- | --- | --- | --- |
| `sleep` | sleep | Supported | Detailed sleep | `get_sleep_data` | `VERIFIED` |
| `sleep_score` | sleep | Supported | Sleep payload overall score | `get_sleep_data`, `sleepScore` | `VERIFIED` |
| `sleep_stages` | sleep | Supported | Raw levels and totals | `get_sleep_data`, `levels` | `VERIFIED` |
| `naps` | sleep | Conditional: totals/events reviewed, exact intervals unknown | Watch/app/web totals and events | `get_sleep_data`, `get_body_battery_events`, `napTimeSeconds` | `VERIFIED_CONDITIONAL` |
| `heart_rate` | intraday | Supported | Daily/activity/FIT records | `get_heart_rates` | `VERIFIED` |
| `resting_heart_rate` | daily health | Supported | Daily history | `get_rhr_day` | `VERIFIED` |
| `hrv_status` | daily health | Supported after overnight baseline | Status/trends | `get_hrv_data` | `VERIFIED` |
| `stress` | intraday | Supported | Daily timeline | `get_stress_data` | `VERIFIED` |
| `body_battery` | intraday | Supported | Trends/events | `get_body_battery_events`, body-battery fields | `VERIFIED` |
| `spo2` | intraday | Conditional: setting/region/sleep dependent | Trends | `get_spo2_data` | `VERIFIED_CONDITIONAL` |
| `respiration` | intraday | Conditional: activity-type limits | Daily/sleep records | `get_respiration_data` | `VERIFIED_CONDITIONAL` |
| `vo2_max` | daily health | Watch/endpoint reviewed; owner payload unknown | Max metrics | `get_max_metrics` | `UNVERIFIED` |
| `recovery_time` | original FIT | Watch-only, up to four days | Not promised in Connect for sole VA5 | Possible `recoveryTimeSeconds`; no dedicated method | `WATCH_ONLY` |
| `training_readiness` | daily health | Not supported for VA5 | No VA5-produced value | `get_training_readiness` exists | `UNAVAILABLE` |
| `training_status` | daily health | Not VA5-produced | May be another compatible device's account value | `get_training_status` exists | `NOT_DEVICE_PRODUCED` |
| `unified_training_status` | daily health | Participant only | Account-level with another compatible device | No separate method | `PARTICIPANT_ONLY` |
| `training_effect` | activity | Unverified for sole VA5 | Sole-VA5 behavior unknown | Typed activity field | `UNVERIFIED` |
| `acute_training_load` | activity | Unverified for sole VA5 | Sole-VA5 behavior unknown | Typed activity field | `UNVERIFIED` |
| `activities` | activity | Supported | List/details/download | `get_activities_by_date`, `download_activity` | `VERIFIED` |
| `cycling_metrics` | activity | Basic metrics reviewed; advanced fields unknown | Recorded fields/FIT | activity details/download, speed/distance/HR/cadence/power/dynamics fields | `VERIFIED_CONDITIONAL` |

The machine-readable source of truth is
`healthcheck.garmin.capabilities.GARMIN_CAPABILITY_INVENTORY`; the checked-in
fixtures under `tests/fixtures/garmin/` exercise the offline envelope in
`healthcheck.garmin.contracts`.

## Synthetic fixture contract

Fixtures are provider-shaped but invented. They must:

- use `fixture_contract_version: r02-garmin-capability-fixture-v1`;
- identify `source_kind: synthetic` and a `synthetic-` fixture id;
- use the synthetic Vivoactive 5 identity only when the payload is explicitly
  device-attributed;
- keep raw field presence separate from non-null value presence;
- allow client methods/fields to be listed without promoting them to device
  capability;
- contain no credentials, tokens, MFA/OTP data, private identifiers, or owner
  payloads.

`method_surface_only.json` is the negative fixture: it lists methods for
Training Readiness, Training Status, and VO2 Max but has no device attribution
or payload evidence. `unattributed_account_value.json` has an account-level
Training Status value but no producer attribution. `daily_health.json` also
keeps null Training Readiness and Training Status fields explicit. None of
these fixtures changes the inventory status.

## Future owner-controlled live spike questions

The following remain `UNVERIFIED` and require a separately authorized owner
environment. They are not run by this issue:

- Prove owner-region login/MFA, token refresh/reconnect, and Windows at-rest
  storage.
- Probe backfill depth, rate limits, and a safe trailing reconciliation window
  for each stream.
- Record actual payload availability and device attribution for every matrix
  row with Vivoactive 5 as the only source device.
- Verify exact nap intervals and timezone behavior.
- Inspect downloaded ORIGINAL FIT for Recovery Time; retain `UNVERIFIED` if
  absent or ambiguous.
- Verify Training Effect and Acute/Training Load provenance when those fields
  appear in activity payloads.
- Verify cycling power, advanced dynamics, cycling VO2, accessory attribution,
  and eBike fields for the owner's setup.
- Confirm conditional SpO2/respiration settings, region, sampling, and sleep
  semantics.
