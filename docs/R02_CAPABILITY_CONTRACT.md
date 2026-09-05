# R02 Garmin capability contract

This document freezes the pre-ingestion capability inventory for a Garmin
Vivoactive 5 and the reviewed `python-garminconnect` `0.3.12` source surface.
The matrix itself remains an offline/static contract. Issue #31 adds a
separate owner-assisted authentication and capability-probe harness; it does
not mutate this matrix or add ingestion, backfill, database/schema work, or a
UI.

The matrix has four deliberately separate questions:

1. What the R00 static review says about the physical watch.
2. What Garmin Connect may expose.
3. Which `python-garminconnect` method/field can be used later to retrieve a
   source payload.
4. What remains safe to claim before a payload from the target
   device/account is observed.

The third column never answers the first or fourth. A method or typed field is
not evidence that a Vivoactive 5 produces that metric.

## Issue #31 owner-assisted boundary

The #31 commands run only when the owner invokes them from a checkout. They
use the pinned `python-garminconnect` source revision recorded in
`docs/REFERENCE_PROJECTS.md`, prompt for credentials and MFA through hidden
input, and keep the reusable tokenstore below the external
`HEALTHCHECK_DATA_DIR` runtime tree. The runtime path is rejected if it
resolves inside the checkout. The implementation and CI tests use only fake
clients and synthetic payloads; no agent or CI process runs these commands
against an owner account.

The live probe accepts one or two adjacent owner-selected dates and at most
one activity selected from that small window. It calls only the allowlisted
read/download methods in `healthcheck.garmin.probe`. It does not call
`prepare-runtime`, migrate a database, write R02 persistence tables, ingest,
backfill, or render a UI. The probe retains raw responses only transiently in
memory so it can return a structural summary.

The sanitized report has this shape:

```text
contract_version: r02-garmin-capability-spike-v1
source: provider_code, target_device_code, target_device_model
library: name, version
application: name, version (unknown when no owner-safe app version is exposed)
auth: status, session_reused, mfa, storage, fixed-vocabulary error
probe: window_day_count, activity_requested, activity_selected, request_count,
       raw_payloads_retained=false, database_writes=false
privacy: raw_values_emitted=false, private_identifiers_emitted=false,
         tokens_emitted=false, health_timestamps_emitted=false
capabilities[]: code, static_audit_status, static_device_support, methods,
                method_callable, request_succeeded, status, value_state,
                payload_shapes, safe field_paths, shape_counts,
                field_state_counts, device_attribution,
                target_device_evidence, method_calls, fixed-vocabulary errors
```

`status` distinguishes `succeeded`, `empty`, `null`, `unsupported`,
`shape_drift`, `method_unavailable`, `reauth_required`, `failed`, and
`not_run`/`partial`. `method_callable=true` never upgrades static device
support. A target-device capability claim requires both a present response
and target-device evidence; otherwise the live result remains unknown or
unattributed.

The report contains no health values, activity/profile/device IDs, routes,
coordinates, precise health timestamps, credentials, cookies, tokens, or raw
payload dumps. If a raw owner response is deliberately saved for later shape
work, it must stay outside the checkout and be passed through the separate
`garmin-redact` command before anything is shared. The redaction output keeps
only types, bounded counts, safe field names, presence states, and coarse
attribution status.

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
`healthcheck.garmin.contracts`. The typed normalization, temporal, source
identity, and idempotency continuation is documented in
`docs/R02_NORMALIZATION_CONTRACT.md` and implemented by
`healthcheck.garmin.normalization`.

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

## Owner live step and remaining questions

The exact owner procedure is in
`docs/R02_OWNER_AUTH_CAPABILITY_SPIKE.md`. In short, the owner runs auth first
and then the separate capability probe:

```powershell
$ownerData = Join-Path $env:LOCALAPPDATA "Health-Check"
uv run --locked healthcheck garmin-auth --data-dir $ownerData
$probeDate = (Get-Date).ToString("yyyy-MM-dd")
uv run --locked healthcheck garmin-capabilities --data-dir $ownerData --date $probeDate
```

Only the sanitized JSON summary may be copied back. Until the owner performs
this step and an Integrator reviews the summary, every owner-account result
below remains `UNVERIFIED`:

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
