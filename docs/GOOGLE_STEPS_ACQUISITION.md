# Explicit Google Steps acquisition v1 (#392)

Baseline: `b50f58f0ad489de847e25f30750dcea5c5a4ef83` (offline exact countSum,
PR #476). This narrow implementation contract received independent source/data
review GO before behavioral implementation; the initial replay gap was repaired.
It does not authorize live consent, provider requests or Owner profile access.

## Source and limits

Use only Google Health v4
[`dailyRollUp`](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/dailyRollUp)
for `users/me/dataTypes/steps`. One explicit civil date requests `[date midnight,
next date midnight)`, as CivilDateTime `date` objects, `windowSizeDays=1`,
`pageSize=1`. Only explicitly selected
`users/me/dataSourceFamilies/google-wearables` is supported in this slice.
The provider reconciles this family; Health-Check does not sum devices or families.
No UTC, IANA zone, fixed 24-hour duration or completed-day inference is added.

At most three HTTP attempts, each timeout 30 seconds, on one page. Retry only
transport unavailability or HTTP 429/500/502/503/504, with 0.25/0.5-second waits.
Data POST 401/403 stop without recovery refresh, reauthorization or POST replay.
No page-token following. These data attempts exclude the single startup OAuth
refresh described below.
Successful response bodies are bounded to 1 MiB, with at most one returned bucket.
The documented response omits a continuation field although the request has
paging inputs. **Pagination exhaustion and full-day coverage always remain
unknown**, including when a continuation field is absent or the result is empty.
Any extra envelope field (including any `nextPageToken`), incompatible shape,
duplicate JSON key, extra bucket, or returned interval different from the exact
requested civil midnights prevents all typed projection for that response.
The aggregation guide's same-day `23:59:59` example conflicts with the REST
closed-open wording. Do not repair or reinterpret such a returned endpoint;
reject the mismatch and leave the real response convention for separate UAT.
An explicit empty array is retained as empty observed evidence, never zero activity.
Missing/null/invalid counts remain distinct from explicit string `"0"`.

Reuse the accepted [StepsRollupValue string-int64](https://developers.google.com/health/reference/rest/v4/StepsRollupValue)
normalizer and dedicated typed decoder unchanged. The returned raw civil objects,
exact source family, immutable bytes, observations and normalization attempts
remain authoritative; countSum is never converted through float. Existing
conservative correction/conflict/replay rules apply. This path establishes only
an observed interval count, even if its boundaries match a requested day.

## Opt-in and execution boundary

Add `google-auth --include-steps` for an explicit three-scope authorization request:
the existing sleep/measurement readonly scopes plus
`https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`.
The [official scope table](https://developers.google.com/health/scopes) associates
Steps with that readonly activity scope. Default requests and the legacy
`ALLOWED_SCOPES` meaning stay at the original two scopes; no other scope is allowed.
Request-specific required scopes govern auth outcomes. Missing/partial grants
never silently initiate browser consent or replace existing credentials.
The Steps consent path validates the staged grant before replacing the stored
session; denial, malformed/partial grants and failed exchange/storage preserve
the previous session. Missing cached scope stops before refresh or bootstrap.

Add standalone `google-steps --date YYYY-MM-DD --family google-wearables` with
exactly one of `--dry-run` or `--apply`. Dry-run builds a sanitized bounded plan
without creating auth/runtime objects, reading credentials or requesting data.
`--apply` also requires an explicit absolute `--data-dir`. It is a future Owner
operation, isolated from production sync,
backfill, schedules, UI and automatic collection policy.
Grant inspection uses one cached token snapshot, with no provider request,
refresh, login or token write. Missing activity grant stops before data requests
and before runtime/DB creation. A cached grant is evidence of stored scope only;
validity, API/project/account access and real consent remain unverified until UAT.

The bounded lifecycle fix (baseline `deada912d21bf4cbc59a58dbda1b66bcd2e7b51c`)
received independent contract GO before implementation. Explicit `--apply` checks
all three required readonly scopes in one cached snapshot before OAuth/network
or runtime creation. Unexpected cached scopes also block apply. It then calls the
existing startup refresh once with that same snapshot, without cached fallback.
An omitted refresh scope or refresh token inherits only that known cached grant
or token. Before protected atomic replacement, the refreshed grant must contain
exactly the three readonly scopes; missing/extra scopes fail closed. Denied,
malformed, transport, protection or storage failures preserve the old session and
prevent any Steps data request. No browser is opened and no grant is expanded.
After successful refresh, only the refreshed access token is used for the bounded
data POST. A later POST 401/403 remains terminal; it never triggers refresh/replay.
This fixes a code lifecycle gap; it does not prove the cause of any prior 401.
Default two-scope auth/fallback and existing GET recovery remain unchanged.

## Persistence and diagnostics

Reuse the existing external runtime operation lock and database lifecycle only
after validation/grant preflight. Create a distinct manual Steps SyncRun; leave
its UTC window columns NULL. Link raw response, observation and normalization
attempt to that run. Store an allowlisted acquisition-context diagnostic in the
existing immutable observation/attempt diagnostics: contract ID, exact civil
request body, fixed method/path, request count, `coverage=unknown` and
`pagination=unknown`. A small optional diagnostics argument to `persist_result`
may forward this context through the existing persistence path; no schema change.
Acquired observations carry the distinct source contract
`google-steps-acquisition-v1`. Offline replay recognizes that contract and
revalidates its immutable request-context diagnostic with the same one-bucket,
exact-boundary adapter before reusing the exact countSum normalizer. It preserves
the context on replay. Missing/malformed/duplicate context and unrecognized
`google-steps-acquisition-*` contracts fail closed without falling back to the
offline-only normalizer. Earlier offline countSum observations retain their
existing contract. Rejected-response replay must never create typed records.
Unusable successful response shapes retain bounded raw/audit evidence with no
typed records. Oversize responses and failed HTTP/OAuth bodies are not persisted.
No coverage row, checkpoint, completeness/finality flag or zero-filled day is made.

Console diagnostics expose fixed status/reason codes, HTTP status, request count,
record/metric state counts, startup refresh attempted/succeeded flags, sanitized
auth error codes and unknown coverage/pagination. `request_count` counts only
Steps data HTTP attempts; a refresh flag alone does not prove data access. They
exclude health values/dates, raw bodies, page tokens, private IDs, credential
material and paths.
Runtime/storage failures fail closed and use existing sanitized error patterns.

## Validation and remaining gates

Only synthetic/mock tests: unchanged default scopes; explicit URL scopes; denied,
partial and old grants; no automatic browser or post-rejection refresh;
cached-only inspection; one startup refresh with strict pre-write scope checking;
failed refresh preserves the prior session and prevents data/runtime calls;
dry-run without auth/runtime;
exact request and retry budgets; DST civil dates; zero/int64 precision;
missing/null/invalid counts; empty/absent/malformed/paged/extra/oversize responses;
wrong/partial/out-of-window intervals; exact storage/readback and request provenance;
correction/replay/conflict compatibility; excluded production registries and privacy.
Include rejected out-of-window/multiple-bucket replay and acquired observations
with missing/malformed request context.
Focused checks, independent frozen-source review and complete exact candidate/PR
CI are required. #392 stays OPEN. Owner consent, Console scope eligibility,
real account access, live acquisition and UAT remain separate; no Stable rollout.

## Next manual consent step (not executed by this implementation)

After this candidate is independently accepted and the Owner separately agrees
to real access, use its approved code with an explicitly Owner-selected external
profile, not Stable. First confirm the intended Google project/account and that
its OAuth Data Access configuration includes the exact activity readonly scope
above. The reported API-enabled state and current two-scope screenshot do not
prove that prerequisite. Any Console change belongs to that separate Owner step.

With `$ownerSelectedProfile` already set to that absolute profile path:

```powershell
uv run healthcheck google-auth --include-steps --force-reauth --data-dir $ownerSelectedProfile
```

The Owner reviews the three readonly scopes in the browser and approves or denies.
Do not send a code, token, client secret or URL containing secrets into chat/logs.
A denial/partial grant leaves the previous stored session intact; do not loop.
Check the sanitized auth result and stop unless authenticated with no missing
scope. This flow proves no Steps data or daily coverage. Only after separate
approval for a bounded live acquisition may the Owner preview and apply one day:

```powershell
uv run healthcheck google-steps --date YYYY-MM-DD --family google-wearables --dry-run
uv run healthcheck google-steps --date YYYY-MM-DD --family google-wearables --apply --data-dir $ownerSelectedProfile
```

Replace the date with one explicitly chosen civil day. No historical loop,
background collection or fallback source is implied. Explicit apply performs
the bounded startup refresh above; no live action is authorized by these examples.
Successful observed evidence still has unknown coverage and pagination;
#392 remains OPEN pending real UAT.

## Bounded owner-refresh catch-up (#524)

`owner-refresh --include-google-steps --google-steps-catchup` opts into bounded
missed-day recovery within the existing owner refresh/profile lock. The existing
include-only previous-day mode and default-OFF calls/reports remain unchanged.
Catch-up rejects `--date`; it uses the current Europe/Moscow civil date as a
selection basis, without claiming that zone is the provider's timezone.

After collection-policy validation and before any provider/auth work, first
activation commits yesterday as the activation floor and the adapter's explicit
`google-wearables` family-aggregate identity. Stored values, old acquisitions and
consent do not choose a source, move the floor or seed progress. An unavailable
grant or later interruption retains this activation. Policy OFF conflicts before
auth/network or activation. Omitting the flag does not erase prior progress.

Select at most seven distinct pending civil dates, oldest first, through yesterday.
Each reuses the exact one-day acquisition above: at most three data attempts and
one existing startup OAuth refresh. Therefore one catch-up invocation adds at most
21 data attempts plus seven startup refresh requests (28 Steps HTTP requests).
Other streams retain their budgets. No pagination, broader scope or new job is
introduced. On the first unsuccessful date, stop and report later selected dates
as not run. Preserve the existing per-date retry policy. Larger gaps remain pending
for later invocations; recent dates can remain unavailable until the older backlog
has been handled. A batch that reaches yesterday requests it only once. An invocation
that starts caught up reacquires yesterday once for ordinary corrections; older
successful dates are not automatically rescanned for later corrections.

One small versioned record in existing `sync_stream_state.cursor`, under its own
Steps namespace, holds the immutable activation floor, next pending date, explicit
source/family/query/contracts and latest successful observation/run receipt. It is
acquisition progress, never coverage, UTC watermark or provider finality. Progress
advances in the same transaction as the exact request-context observation and its
succeeded acquisition run. Valid empty/missing/null results count as successfully
handled acquisition, retaining their actual states; none becomes zero. Rejected,
partial, failed or unavailable acquisitions do not advance. Before commit/resume,
validate the exact day, observation, succeeded run and fixed source/family/query/
contracts. Corrupt/mismatched/unavailable state fails closed without a new floor,
source choice or inferred skip. Interruption before commit leaves the date pending;
after commit, the durable receipt/cursor resumes at the next date.

Catch-up uses `healthcheck-owner-refresh-v3`, with separate per-date original
acquisition results/status, requested dates, activation floor, bounded request
counts and remaining pending count/range. Pending backlog prevents Steps success,
even when all attempted dates succeeded. A stopped batch preserves the actual
failure/reauth status and marks later selected dates not run. Internal receipt IDs
are not emitted. Full coverage/pagination/provider timezone/finality remain unknown.
This implementation authorizes no real collection, OAuth changes, Stable rollout,
wrapper/schedule changes or historical backfill #522.
