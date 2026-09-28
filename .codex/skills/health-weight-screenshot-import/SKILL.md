---
name: health-weight-screenshot-import
description: Import an Owner-supplied Xiaomi Home or Xiaomi S400 weight screenshot into Health-Check when asked to add, import, or process weight from a scale screenshot.
---

# Health weight screenshot import

Use only the accepted Owner command and existing R01 photo/Xiaomi pipeline:

```powershell
uv run --locked healthcheck owner-weight-screenshot-import `
  --data-dir "D:\Garmin\HealthCheck-Stable" `
  --image "<single uploaded PNG or JPEG>"
```

- Treat `D:\Garmin\HealthCheck-Stable` as a protected Owner runtime. Run against it only with explicit Owner authorization for that live import.
- Pass one screenshot to one normal invocation. Do not scan folders or batch attachments. Replay only when the Owner explicitly requests an idempotency/live-gate check.
- Do not copy the screenshot or private runtime artifacts into Git, fixtures, GitHub, CI, or ordinary logs.
- Do not write SQLite directly or bypass the command with ad hoc scripts. Do not add or invoke the separate #153/openScale webhook path.
- Let the R01 pipeline retain the original evidence and preserve Xiaomi Home, Xiaomi S400, and `photo_import` provenance. Never invent or repair missing values, dates, times, timezones, units, metrics, or provenance.
- Read only the command's privacy-safe JSON result. Do not expose health values, timestamps, paths, IDs, hashes, provider responses, or private artifacts.

Handle the result exactly:

- `IMPORTED`: report success and do not repeat the normal import.
- `DUPLICATE`: report that the evidence was already handled; do not create or attempt to force another semantic measurement.
- `NEEDS_REVIEW`: stop and tell the Owner manual import review is required. Do not retry around or weaken the guard.
- `FAILED`: stop and report only the returned safe `reason_code`. Do not debug by dumping private inputs or adding workarounds.

For an authorized live import, compare the existing repository/service/CLI read path before and after without printing private values or identifiers. Verify structurally that measurement-session and canonical-selection counts changed only as expected, pre-existing Weight history remains present, and an explicitly requested replay creates no second semantic weigh-in or canonical change.
