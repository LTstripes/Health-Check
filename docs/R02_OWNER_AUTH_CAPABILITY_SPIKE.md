# R02 owner-assisted Garmin auth and capability spike

This is the owner runbook for issue #31. The implementation agent does not
log in, handle the owner's Garmin credentials, inspect real health data, or
run the live probe. The owner performs the live step locally; only the
sanitized capability JSON may be returned for review.

## AGENT/CI TESTS

These commands are for the implementation checkout and use fake clients and
synthetic payloads only. They do not contact Garmin:

```powershell
$taskCache = Join-Path (Get-Location) ".uv-cache"
$env:UV_CACHE_DIR = $taskCache
uv lock --check
uv run --locked ruff check .
uv run --locked pytest
git diff --check
```

Pytest's default temporary directory is outside the checkout. In a restricted
environment, an overridden base directory must likewise be a short, writable
directory outside the checkout. No real tokenstore, payload, screenshot, or
owner runtime data belongs in this checkout.

## OWNER LIVE STEP

Run these commands from the checked-out task branch, with `uv` available. The
default path below is outside the checkout and is the only place where the
pinned Garmin tokenstore is created:

```powershell
$ownerData = Join-Path $env:LOCALAPPDATA "Health-Check"
uv run --locked healthcheck garmin-auth --data-dir $ownerData
```

The command prompts for the Garmin email and password without command-line
arguments and without echoing input. If Garmin requests MFA, it prompts for
the MFA code without echoing or storing it as report output. The command emits
only a fixed-vocabulary auth result. If the cached session is expired or
unusable, rerun the same command; to explicitly replace a usable cached
session, use:

```powershell
uv run --locked healthcheck garmin-auth --data-dir $ownerData --force-reauth
```

After authentication, choose one recent date (or two adjacent recent dates)
that the owner wants to inspect and run the separate probe. The example uses
today; replace `$probeDate` with another recent `yyyy-MM-dd` value if needed:

```powershell
$probeDate = (Get-Date).ToString("yyyy-MM-dd")
uv run --locked healthcheck garmin-capabilities --data-dir $ownerData --date $probeDate
```

For two adjacent dates:

```powershell
$probeDate = (Get-Date).ToString("yyyy-MM-dd")
$previousProbeDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
uv run --locked healthcheck garmin-capabilities --data-dir $ownerData --date $previousProbeDate --date $probeDate
```

The probe selects at most the first recent activity returned for that small
window. It does not perform broad backfill and does not write Health-Check
database tables. Its stdout is a machine-readable sanitized summary. Save or
copy only that summary, never provider logs or raw responses.

The summary reports, per capability:

- whether the method is callable and whether its request succeeded;
- response shape, bounded counts, safe field paths, and present/empty/null or
  missing state;
- unsupported/404-like, expired-session, shape-drift, and other fixed error
  classes;
- coarse target-device/other-device/unattributed/unknown evidence;
- the static R00 status next to the live observation, without changing it.

It never reports health values, activity/profile/device IDs, routes,
coordinates, precise health timestamps, email, device serials, cookies,
tokens, or raw payloads. `target_device_evidence` is false unless the response
has a present value and explicit target-device evidence. Method presence alone
is not capability evidence.

## Optional sanitized shape export

The probe does not save raw responses. If the owner separately has a raw JSON
response and later needs to share its structure, keep both files outside the
checkout and run:

```powershell
$rawPath = Join-Path $ownerData "owner-only\raw-response.json"
$sanitizedPath = Join-Path $ownerData "owner-only\sanitized-shape.json"
uv run --locked healthcheck garmin-redact --input $rawPath --output $sanitizedPath
```

The helper rejects checkout-local or symlinked input/output paths, omits
sensitive/dynamic identifier fields, and writes only a value-free bounded
shape. Do not copy the raw input, tokenstore, logs, screenshots, or the
owner-only directory into Git or an issue comment. Share only the sanitized
summary/shape if explicitly requested.

## Live questions that remain review-gated

The sanitized result is discovery evidence, not ingestion acceptance. An
Integrator must review it before any later adapter work. The following remain
unverified until that review:

- region-specific login/MFA and token refresh/reconnect behavior;
- actual availability and target-device attribution for each matrix row;
- exact nap intervals and timezone behavior;
- Recovery Time visibility in ORIGINAL FIT;
- Training Effect, Acute Training Load, and cycling advanced-field provenance;
- conditional SpO2/respiration settings and sampling semantics;
- expected absence/non-device-production of Training Readiness and Training
  Status, unless the live summary contains contradictory attributed evidence.
