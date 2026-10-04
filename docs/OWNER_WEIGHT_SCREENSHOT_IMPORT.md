# Owner Xiaomi Home Screenshot Import

This command is the Owner/ChatGPT Work entry point for one Xiaomi Home weight screenshot. It calls the existing R01 `PhotoImportService`, photo extractor, normalization and confirmation path. It adds no webhook requirement, listener, poller, OCR stack or table beyond the additive 0015 per-candidate origin map.

## Work handoff

The Work-side integration passes the single uploaded PNG or JPEG attachment as a local file path to one bounded CLI call:

```powershell
uv run --locked healthcheck owner-weight-screenshot-import `
  --data-dir "D:\HealthCheck\stable" `
  --image "<path to this uploaded attachment>"
```

When Work/Codex can inspect the attachment itself, it may instead provide one temporary
strict `r01-photo-v1` extraction object:

```powershell
uv run --locked healthcheck owner-weight-screenshot-import `
  --data-dir "D:\HealthCheck\stable" `
  --image "<path to this uploaded attachment>" `
  --extraction-json "<temporary JSON outside the repository>"
```

When the Owner explicitly states the source date in the same request, Work may add
`--owner-attested-date "YYYY-MM-DD"` together with `--extraction-json`. Never supply
it from memory, prior chat, filename, EXIF, clock, or defaults, and never without the
sidecar. An attested date is strictly date-only: the sidecar must carry no source
timestamp, timezone, UTC offset, or non-date precision, otherwise the request is
rejected before any write. Provider vision routes never accept attestation.

This sidecar is bounded to 512 KiB, parsed and profile-checked before the R01 photo service
writes evidence, and uses the fixed `healthcheck-owner-assisted-structured-extraction` v1
identity with no invented model identity. It must contain the same strict structured payload
accepted from the configured vision adapter; there is no second schema or normalization path.
The caller removes the temporary JSON after the command and never stores or publishes it.

The established profile must already exist. Configure the existing real photo extractor through the normal `HEALTHCHECK_PHOTO_VISION_BASE_URL`, `HEALTHCHECK_PHOTO_VISION_MODEL` and `HEALTHCHECK_PHOTO_VISION_API_KEY` environment settings. The API key is never passed as a CLI argument. The command refuses a missing/unready profile, reads at most the existing 10 MiB photo limit, accepts PNG/JPEG, and stores evidence in the profile's content-addressed R01 photo store. It does not print the supplied path, filename, extracted values, dates, provider response, or exception text.

The external vision configuration is not required or called when `--extraction-json` is
present. Without that option, the configured-provider behavior is unchanged. Malformed,
unreadable or oversized sidecars fail with a fixed safe reason before photo persistence;
Owner-profile conflicts fail closed before confirmation.

Work should pass arguments as separate process arguments, make one invocation for one attachment and use only the returned status. It must not scan a folder, retry a review result, confirm through SQL, or require the openScale webhook. The screenshot attachment itself is not rewritten.

## Auto-confirm boundary

The command commits the R01 photo evidence and extracted candidates before deciding whether to confirm. It calls the existing `PhotoImportService.confirm()` only when all of these hold:

- exactly one image, one extraction set and one plausible measurement group;
- exactly one evidenced `weight` and no repeated or unsupported metric;
- every candidate has a finite value, supported unit, source date and consistent temporal precision, with no normalization warnings;
- all candidates are pending and have Xiaomi Home / Xiaomi S400 / `photo_import` provenance.

The existing R01 normalizer and confirmation service remain responsible for kg/percentage normalization, date-only precision, session identity, photo content-hash idempotency, Xiaomi weight/composition algorithm identity, measurement writes and canonical recomputation. The Owner adapter supplies Xiaomi Home/S400 acquisition context; it does not relabel composition values or invent a timestamp, confidence, formula or missing value. A date-only source remains date-only.

Any conflicting group, candidate set, duplicate metric, missing value/date/unit, unsupported metric/unit, warning, unrecognized source/device or confirmation validation failure returns `NEEDS_REVIEW`. The image and candidate audit stay in the existing photo workflow, but no semantic measurement is confirmed. A replay of already handled bytes returns `DUPLICATE`; a replay with unresolved candidates returns `NEEDS_REVIEW`. If the same bytes yield a new extraction set, the new interpretation is preserved for review and is never auto-confirmed.

A changed Owner-assisted sidecar for already-imported bytes follows the same rule even when it reuses the stored extraction identity: the changed interpretation is appended as its own pending correction candidate set in the existing review queue, linked to the original photo event. The original artifact, original candidate set and confirmed semantic history are never overwritten, and nothing is confirmed before the Owner's explicit decision. Replaying the same changed sidecar resolves to that same pending set (`NEEDS_REVIEW`, no duplicate evidence rows); after the correction has been confirmed, an exact replay is a no-op `DUPLICATE`. Confirming the staged correction uses the existing session/measurement revision mechanics, so the prior value is superseded but never erased; rejecting it leaves the current semantic and canonical state unchanged.

## Metadata origins (#240)

Every post-0015 `ImportCandidate` persists one complete canonical `metadata_origins_json`
map with exactly `provider_code`, `physical_device_code`, `source_application`,
`source_local_date` in `visible | owner_attested | workflow_profile | unknown`.
Database NULL is reserved exclusively for pre-0015 legacy rows and reads as
"origin not recorded"; there is no backfill, default, or history rewrite.

- The fixed `xiaomi_home / xiaomi_s400 / Xiaomi Home` workflow default, when the
  sidecar omits it, is `workflow_profile`, never visible/attested.
- `source_local_date` is never `workflow_profile`. It is `visible` when the
  sidecar carries it, `owner_attested` only for an explicit current-request
  `--owner-attested-date`, otherwise `unknown`. No clock/EXIF/filename/memory/
  prior-chat/default inference is permitted.
- Provider vision routes never accept attestation and never emit
  `workflow_profile` (`visible | unknown` only).
- Terminal-candidate immutability covers the new column; confirmed/rejected
  history stays immutable.

Replay/correction preserves #229:

- exact replay with equal core evidence plus equal origin map stays `DUPLICATE`;
- a fully legacy NULL set with unchanged core evidence uses the D1 read-time
  wildcard and stays `DUPLICATE` with zero provenance rewrite;
- changed core evidence follows normal #229 correction;
- a post-0015 provenance-only change is identity-bearing and stages a reviewable
  correction with its own `correction:` identity; distinct provenance claims get
  distinct identities.

## Work result contract

The command writes one privacy-safe JSON object to stdout:

| Status | Exit code | Work action |
| --- | ---: | --- |
| `IMPORTED` | 0 | Report that the screenshot import completed; do not repeat the import. |
| `DUPLICATE` | 0 | Report that the same evidence was already handled; no new measurement was written. |
| `NEEDS_REVIEW` | 3 | Stop automation and direct the Owner to the existing Health-Check import review; a staged correction appears in the original import batch. |
| `FAILED` | 1 | Stop automation and report the safe reason code; do not echo the file path or retry indefinitely. |

The JSON includes only status, a fixed reason code and structural candidate/measurement counts, plus privacy flags. It never includes health values, timestamps, content hashes, artifact/candidate IDs, filenames or provider text.

## Integration gate

The synthetic worker gate exercises the CLI, existing R01 photo contracts, provenance and replay behavior:

```powershell
uv run --locked ruff check src/healthcheck/owner_weight_screenshot_import.py src/healthcheck/cli.py tests/test_owner_weight_screenshot_import.py tests/test_metadata_origins_240.py
uv run --locked pytest -q -p no:cacheprovider tests/test_owner_weight_screenshot_import.py tests/test_photo_import.py tests/test_photo_vision.py tests/test_metadata_origins_240.py
uv run --locked python scripts/ci_test_lanes.py validate-manifest
```

The new test file is assigned to the existing `app-ingest` CI lane; it does not create a new test lane.

Before enabling the Work handoff against Stable, the Owner/Integrator gate remains required and must be performed with a recovery point and a private Xiaomi Home screenshot on the actual Work-to-local-CLI path:

1. Upload one screenshot in ChatGPT Work and verify Work invokes this CLI against `D:\HealthCheck\stable` with that one attachment.
2. For a clear screenshot, verify through the normal Health-Check read path that one photo evidence/candidate set is retained and exactly one source measurement session is confirmed with Xiaomi Home, Xiaomi S400, `photo_import`, original photo hash, R01 algorithm identities and evidenced temporal precision.
3. Replay the identical attachment. It must return `DUPLICATE` and leave the measurement/session/canonical counts unchanged.
4. Exercise one ambiguous screenshot; it must return `NEEDS_REVIEW` and create no semantic measurement or canonical change.
5. Verify the pre-existing Stable history remains intact. Keep the private screenshot, values, identifiers and runtime evidence out of Git and task logs.

Until this live gate is completed, ChatGPT Work-to-Stable is `UNVERIFIED`; synthetic tests do not claim Owner UAT or Integrator acceptance.

## Historical #153 context

#153 (openScale-sync webhook numeric `userId` compatibility) was closed by the Owner as not planned: screenshot ingestion is the accepted operational Weight path. The historical receiver note (non-empty string `userId`) is retained only as deferred context. This task does not change that contract or implement a webhook fix. The screenshot command is an independent Owner path and must not depend on webhook setup or availability.
