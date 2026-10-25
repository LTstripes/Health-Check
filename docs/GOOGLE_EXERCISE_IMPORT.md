# Bounded Google exercise import

This candidate adds explicit manual acquisition through the existing Google
HTTP/auth boundary and a source-specific saved-evidence path. Development and CI
use synthetic HTTP mocks only; no real provider/account operation is implied.
`persist_exercise_page(session, payload_store=..., payload=...)` accepts one
already-acquired Google Health v4 exercise list page in the caller's transaction.
The offline input is bounded to 1 MiB and 25 sessions.

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

The explicit command follows opaque continuation tokens on the fixed endpoint,
within four pages and twelve total data attempts. A valid terminal page must be
durably saved before `query_exhausted=true`; device/provider history completeness
remains unknown. No coverage or saved cursor checkpoint is created. The reader exposes
provider coverage/pagination/finality as unknown, including empty results.
Saved search is bounded to 25 sources and 200 sessions in one selected source;
overflow returns an explicitly incomplete packet without a successful prefix.
The reader optionally selects 1–30 civil start dates, without arbitrary history
stitching. These application bounds are not provider history limits.

`GET /google/exercise` renders the saved reader and a reusable
`google_exercise.html` partial. The existing Activity page (`GET /garmin`) includes
that partial after its Garmin journal. Sources remain separate from Garmin and
from each other; ambiguous Google sources require explicit selection. Google
source/date forms open the dedicated saved view; Garmin's metric/date selection
does not become a Google history filter. The Activity hook performs only the same
bounded saved read, with no acquisition, auth or provider call. Human activity
labels and dates reuse the existing presentation formatters, with no seconds in
displayed timestamps and with source UTC offsets retained. No Garmin total or
date-based deduplication changes.

## Explicit manual command

```text
healthcheck google-exercise --start 2099-01-03 --end 2099-01-03 --family google-wearables --dry-run
healthcheck google-exercise --start YYYY-MM-DD --end YYYY-MM-DD --family google-wearables --apply --data-dir <explicit-absolute-existing-profile>
```

Exactly one mode is required. Dates are explicit, inclusive civil start dates,
bounded to 1–14 days. Dry-run creates no auth/runtime objects or requests. Apply
requires the current migrated external profile, checked through read-only SQLite
metadata under the existing profile operation lock. It never bootstraps a profile
or migrates one. The lock covers startup refresh, all HTTP and page persistence.

The command shares one existing bounded `UrllibGoogleHttpTransport` with
`GoogleAuthService`; it adds no transport implementation or consent path. It reuses
the strict cached three-scope preflight and single startup refresh already used
by Steps. Missing/partial/unexpected grants stop without browser consent. Data
401/403 are terminal, with no recovery refresh. 429 stops for a later explicit
retry; transport failures and selected 5xx have at most three attempts per page
with 0.25/0.5-second backoff. Each response is at most 1 MiB and each attempt has
the existing 30-second timeout. One startup OAuth refresh is additional to the
twelve-data-attempt cap; it cannot expand scopes or fall back to cached access.

`google-exercise-acquisition-v1` identifies acquired observations separately from
offline inputs. Immutable allowlisted request context records the exact civil
window, fixed method/path/family, page index and attempt count. No authenticated
URL, access token or cursor is copied to diagnostics/output. A response cursor
remains only within the existing private immutable raw response. Replay requires
exactly one valid acquisition context and rechecks the window across **all** source
partitions before any typed promotion; missing context cannot fall back to offline.

Optional missing/null/invalid active duration does not prevent session retention
or pagination. Invalid required evidence/window rejects the entire current page's
typed projection while retaining bounded raw audit. Previously committed pages
survive a later error, page/attempt budget, token cycle or interruption. Such runs
are explicitly partial with `query_exhausted=false`; restart begins at the first
page. Provider name/updateTime makes repeated projection idempotent. A 4-page
ceiling cannot recover a larger unchanged window by repeating the same run; select
a smaller explicit window instead. No automatic history traversal is introduced.

Receipts distinguish observed occurrences, inserts, updates and unique involved
current records. Equal-version conflicts can leave query exhaustion true but the
result partial with an explicit unavailable-current count. Accepted attempt count
includes only the final usable current records, not every received occurrence.
Manual SyncRun UTC request windows remain NULL; its outcome is not a completeness
or success checkpoint for the provider's history. No normal stream, owner refresh,
collection policy, scheduling or UI totals are changed.

## Migration and follow-up

Migration `0020_google_exercise` follows `0019_garmin_summary_date_proofs`, adding
exercise to four Google stream CHECKs and exercise_session to generic intervals.
It recreates append-only triggers and blocks downgrade when exercise evidence
exists. Before an authorized rollout, retain a verified recoverable pre-migration
backup covering the profile and artifacts. Recovery after exercise evidence exists
requires restoring that backup through the established recovery procedure, not
free downgrade or evidence deletion. No existing history is relabeled, reprocessed
or discarded. Only synthetic
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
