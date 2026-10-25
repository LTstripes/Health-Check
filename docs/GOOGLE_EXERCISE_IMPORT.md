# Offline Google exercise sessions

This candidate adds a source-specific saved-evidence path, without provider
requests, OAuth changes, collection activation or real-profile operations.
`persist_exercise_page(session, payload_store=..., payload=...)` accepts one
already-acquired Google Health v4 exercise list page in the caller's transaction.
The input is bounded to 1 MiB and 25 sessions. It is not an acquisition command.

## Verified provider surface

Checked against first-party documentation on 2026-10-25:

- [Workout sessions](https://developers.google.com/health/data-types/workouts):
  `exercise` supports list/get/reconcile under
  `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`.
  This is the same optional scope already implemented for Steps; default sleep
  and measurement scopes do not establish it. Session summaries need no location
  scope. GPS and telemetry are outside this slice.
- [List contract](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list):
  `GET https://health.googleapis.com/v4/users/me/dataTypes/exercise/dataPoints`,
  empty body, `pageSize=25`; use `nextPageToken` for subsequent pages. Exercise
  filtering supports civil start dates, for example
  `exercise.interval.civil_start_time >= "2099-01-02" AND exercise.interval.civil_start_time < "2099-01-03"`.
  V1 explicitly selects `users/me/dataSourceFamilies/google-wearables`; manual
  records and Health Connect are excluded. The query family is not device identity.
- [Exercise and session interval schema](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints):
  preserve provider name, exerciseType, updateTime and both UTC endpoints/offsets.
  Active duration is optional and distinct from elapsed time. The current storage
  supports microsecond physical/civil times and whole-minute offsets; finer
  unsupported precision is rejected, rather than silently rounded.
- [Historical availability](https://developers.google.com/health/data-types):
  recorded history has no API age limit, but pagination and quotas apply.
- [Rate limits](https://developers.google.com/health/rate-limits): default per-user
  quota is 300 requests/minute; 429 requires backoff. No live budget is authorized
  by this document.

## Saved-evidence contract

`google-exercise-session-v1` uses the existing point-source identity resolver and
partitions a full immutable page by source. Explicit source metadata is preserved;
family fallback is used only where the established resolver cannot identify a
source. Device identity is never invented. Each source retains its own typed
records, observations and normalization attempts over the full raw page.

The logical session key is the provider's resource name within its Google source.
Date, corrected timestamps, list order and page position are not session identity.
Equal conflicting provider updateTime versions invalidate the current projection;
only a strictly newer provider version resolves that conflict. Stale imports and
replays cannot replace a newer version. Revision ordering preserves nanoseconds.
Exact retry converges on existing evidence. Missing or unusable required identity,
interval or revision rejects the page's typed projection, without a successful
prefix. A valid correction with missing duration clears the previous duration.

Type, active duration and elapsed duration are the only product metrics here.
Missing, null, invalid and explicit zero are distinct. Active duration never falls
back to elapsed time. Source offsets, including different start/end offsets, drive
local time; no IANA zone or fixed-day length is inferred. Calories, free-text names,
notes, events, splits and telemetry are retained only in raw evidence.

No provider paginator is implemented or run. A page with a continuation remains
one page, and later pages can be imported independently/repeated safely. There is
no coverage checkpoint or claim of complete acquisition. The reader always exposes
provider coverage/pagination/finality as unknown, including empty results.
Saved search is bounded to 25 sources and 200 sessions in one selected source;
overflow returns an explicitly incomplete packet without a successful prefix.
The reader optionally selects 1–30 civil start dates, without arbitrary history
stitching. These application bounds are not provider history limits.

`GET /google/exercise` renders the saved reader and a reusable
`google_exercise.html` partial. Sources remain separate from Garmin. The shared
Activity template connection is intentionally pending coordination with #319;
this candidate must not be described as a completed Activity entrypoint until
that connection is integrated. No Garmin total or date-based deduplication changes.

## Migration and follow-up

Migration `0020_google_exercise` follows `0019_garmin_summary_date_proofs`, adding
exercise to four Google stream CHECKs and exercise_session to generic intervals.
It recreates append-only triggers and refuses downgrade when exercise evidence
exists. No existing history is relabeled, reprocessed or discarded. Only synthetic
migration and backup/restore checks are permitted in this task; actual installation
and operational documentation updates belong to the Integrator.

For a later explicitly authorized operational step, inspect only the existing
cached session's activity readonly grant and report present/absent/unknown. Use
the established cached-only token-health/preflight path, with no refresh, consent,
token output or credential replacement. A cached grant does not prove token/API
validity or actual session availability. Current grant and live access remain
UNVERIFIED. If absent, return the exact activity readonly scope to the Integrator;
do not add it automatically. Before live collection separately agree the profile,
civil date range, page/request/byte budget and interruption behavior.
