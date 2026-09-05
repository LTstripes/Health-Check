# R01 Owner UAT checklist

Release-specific owner gate for R01 weight-core. Use synthetic or owner-private data only. Never commit runtime DB, photos, payloads, tokens, or secrets.

## 1. Checkout / ref verification

Work only in the owner UAT checkout:

`D:\Garmin\Garmin-UAT`

1. Confirm the checkout tracks the reviewed release candidate branch/ref (not an agent workspace).
2. Record the exact SHA under test (`git rev-parse HEAD`).
3. Do not develop or push from this checkout.

## 2. Separate runtime data directory

Set a UAT-only data dir outside Git, for example:

`HEALTHCHECK_DATA_DIR=%LOCALAPPDATA%\Health-Check\uat`

Do not reuse the production/profile database across branches.

## 3. Dependencies / bootstrap

From the UAT checkout:

1. Install/sync dependencies with the project `uv` workflow.
2. Confirm the runtime directory is created under `HEALTHCHECK_DATA_DIR`, not inside the repo.
3. Confirm no private artifacts are staged in Git (`git status` clean of DB/photos/secrets).

## 4. Mandatory Windows fresh-start smoke (AC-01)

Run:

`scripts/start.ps1`

Expectations:

- fresh empty runtime migrates cleanly;
- loopback UI and ingest listener start with the documented binds;
- no secrets printed.

**Status rule:** this step is **OWNER-UNVERIFIED** until Nikita runs it on Windows from `D:\Garmin\Garmin-UAT`. Team Linux/CLI substitutes do **not** make AC-01 PASS.

## 4a. Synthetic demo helper (developer/UAT preparation)

Use a new dedicated directory outside this checkout and outside any private profile. In PowerShell:

```powershell
$env:HEALTHCHECK_DATA_DIR = Join-Path $env:LOCALAPPDATA "Health-Check\r01-synthetic-demo"
uv run python -m healthcheck.cli seed-demo
```

The command creates a labelled synthetic six-month / 26-weigh-in profile through the accepted photo-import service path. Repeating it is a safe no-op after the manifest is validated. To explicitly rebuild that same marked synthetic profile:

```powershell
uv run python -m healthcheck.cli seed-demo --reset
```

An existing non-empty directory without the synthetic manifest is refused, including with `--reset`. This prevents a private-looking profile from being overwritten; choose a new empty directory instead. The reset removes only the marked demo database and `artifacts` tree, and leaves unknown files in place. The manifest and all runtime artifacts stay outside Git.

After seeding, run the mandatory owner start from this checkout (the helper does not replace AC-01):

```powershell
.\scripts\start.ps1 -DataDir $env:HEALTHCHECK_DATA_DIR
```

In another PowerShell window, run the read-only helper:

```powershell
.\scripts\uat-smoke.ps1
```

If the optional ingest listener is running, include its URL:

```powershell
.\scripts\uat-smoke.ps1 -IngestUrl "http://127.0.0.1:8121"
```

The helper prints only endpoint paths, statuses, and sanitized shape/readiness assertions. It checks UI/ingest liveness, dashboard/API reachability, ingest route isolation, and that the UI does not mount the openScale write route. It never prints response bodies or secrets and never reports AC-01 PASS.

Open the populated dashboard at `http://127.0.0.1:8120/`.

When finished, stop `start.ps1` with `Ctrl+C`, then remove only the dedicated synthetic profile after confirming its path:

```powershell
$demoDir = [IO.Path]::GetFullPath($env:HEALTHCHECK_DATA_DIR)
$expectedDemoDir = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Health-Check\r01-synthetic-demo"))
if (-not $demoDir.Equals($expectedDemoDir, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing cleanup outside the dedicated synthetic demo path" }
Remove-Item -LiteralPath $demoDir -Recurse -Force
```

Do not run that cleanup against a production or owner-private data directory.

## 5. Loopback UI and ingest route checks

- UI `/healthz` reports loopback-ui.
- Ingest `/healthz` reports ingest.
- Ingest does not expose dashboard/import/static/settings routes.
- UI does not expose openScale ingest write surface.

Record PASS / FAIL with exact URL and status code.

## 6. Synthetic dashboard / import checks

Using synthetic fixtures only:

1. Import a synthetic batch → pending review (no implicit confirm).
2. Confirm/reject/edit paths as documented.
3. Dashboard shows raw + trend + coverage without inventing zeros.
4. If a stale/failed canonical recomputation is present, the dashboard shows the visible canonical warning banner.

## 7. Owner real-photo UAT

Optional private photos on the owner machine only.

- Before the explicit upload, set `HEALTHCHECK_PHOTO_VISION_BASE_URL`,
  `HEALTHCHECK_PHOTO_VISION_MODEL`, and the provider API key in the owner
  process environment only. Do not put the key in `config.toml`, Git, or an
  issue/comment.
- Upload one ordinary Xiaomi S400 PNG/JPEG from the owner-private runtime
  profile. The expected first result is a failed-safe or pending review queue:
  successful extraction must create nonzero pending candidates, with zero
  confirmed/canonical measurements before owner action.
- Check that provider/model/prompt/schema and visible source/device/time
  provenance are shown without an authorization header, key, raw provider
  response, or absolute image path. Date-only evidence must remain date-only.
- If the provider is unavailable or returns malformed data, record the
  sanitized diagnostic and verify the immutable artifact remains reprocessable.
- Keep files under the UAT data dir, never in Git.
- Record PASS / FAIL / UNVERIFIED.

## 8. Optional live S400 / openScale

Live device/LAN proof remains **UNVERIFIED** unless the owner performs it personally.

## 9. How to record results

For each checklist item record one of:

- **PASS** — owner observed the required behavior on this SHA;
- **FAIL** — blocker with short reproduction;
- **OWNER-UNVERIFIED** — required owner step not yet run (especially AC-01 `start.ps1`);
- **UNVERIFIED** — allowed live/optional limitation (S400/openScale, real-photo if skipped).

## 10. Privacy cleanup

Before closing UAT:

1. Confirm runtime DB/photos/payloads/secrets remain outside Git.
2. Confirm `git status` in the UAT checkout shows no private additions.
3. Do not paste tokens, bearer secrets, or raw health values into issues/chat.
