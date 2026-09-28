---
name: health-weight-screenshot-import
description: Import an Owner-supplied Xiaomi Home or Xiaomi S400 weight screenshot into Health-Check when asked to add, import, or process weight from a scale screenshot.
---

# Health weight screenshot import

Use only the accepted Owner command and existing R01 photo/Xiaomi pipeline. When you can
inspect the attached image directly and no external photo-vision provider is configured,
prefer the Owner-assisted structured route:

```powershell
uv run --locked healthcheck owner-weight-screenshot-import `
  --data-dir "D:\Garmin\HealthCheck-Stable" `
  --image "<single uploaded PNG or JPEG>" `
  --extraction-json "<temporary JSON outside the repository>"
```

- Treat `D:\Garmin\HealthCheck-Stable` as a protected Owner runtime. Run against it only with explicit Owner authorization for that live import.
- Pass one screenshot to one normal invocation. Do not scan folders or batch attachments. Replay only when the Owner explicitly requests an idempotency/live-gate check.
- Do not copy the screenshot, extraction JSON, or private runtime artifacts into Git, fixtures, GitHub, CI, or ordinary logs.
- Do not write SQLite directly or bypass the command with ad hoc scripts. Do not add or invoke the separate #153/openScale webhook path.
- Let the R01 pipeline retain the original evidence and preserve Xiaomi Home, Xiaomi S400, and `photo_import` provenance. Never invent or repair missing values, dates, times, timezones, units, metrics, or provenance.
- Read only the command's privacy-safe JSON result. Do not expose health values, timestamps, paths, IDs, hashes, provider responses, or private artifacts.

For an Owner-assisted payload, read only visibly evidenced fields and create exactly the
strict `r01-photo-v1` object accepted by `ingestion/photo/vision.py`. Include every required
key and type from its `_response_schema()` contract, using `null` rather than guesses:

- top level: `schema_version`, `provider_code`, `physical_device_code`,
  `source_application`, `source_application_version`, `source_timezone`,
  `source_utc_offset_minutes`, `groups`;
- each group: `key`, `source_local_date`, `source_timestamp`, `temporal_precision`, `fields`;
- each field: `metric_code`, `value`, `unit`, `source_text`, `confidence`,
  `source_local_date`, `source_timestamp`, `temporal_precision`, `evidence_region`,
  `algorithm_code`, `algorithm_version`.

Use the fixed Owner profile only when visibly consistent: `provider_code=xiaomi_home`,
`physical_device_code=xiaomi_s400`, and `source_application=Xiaomi Home`. Keep date-only
evidence date-only with a null timestamp/timezone/offset. Do not invent confidence,
algorithm/app versions, missing metrics, or a timestamp. If the image is ambiguous, stop
before invoking the CLI and report that review is required instead of fabricating JSON.

Write the JSON in the normal OS temporary directory outside the repo/workspace.
Pass that one file with `--extraction-json`, then remove it in a `finally` cleanup whether the
command succeeds or fails. The existing command without `--extraction-json` remains the route
when an explicitly configured external vision provider is appropriate.

Handle the result exactly:

- `IMPORTED`: report success and do not repeat the normal import.
- `DUPLICATE`: report that the evidence was already handled; do not create or attempt to force another semantic measurement.
- `NEEDS_REVIEW`: stop and tell the Owner manual import review is required. Do not retry around or weaken the guard.
- `FAILED`: stop and report only the returned safe `reason_code`. Do not debug by dumping private inputs or adding workarounds.

For an authorized live import, compare the existing repository/service/CLI read path before and after without printing private values or identifiers. Verify structurally that measurement-session and canonical-selection counts changed only as expected, pre-existing Weight history remains present, and an explicitly requested replay creates no second semantic weigh-in or canonical change.
