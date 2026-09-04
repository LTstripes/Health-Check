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
