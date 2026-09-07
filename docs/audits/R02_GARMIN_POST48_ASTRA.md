# R02 Garmin post-48 targeted architecture audit

## Checkpoint 1 — remote baseline and scope (2026-09-07)

Status: IN PROGRESS — NOT SAFE TO CLAIM READY.

- CONFIRMED: GitHub `integration/r02-garmin` = `aea777e418d8d16c275a860c31b11c72641a73e6`; isolated clone pinned to this SHA. Audit branch: `audit/r02-garmin-post48-astra`.
- CONFIRMED: remote `main` = `c6f48d26a9eefee73b52f68835d931cce7b18388` (read only; not audit baseline).
- CONFIRMED: #48 is closed; PR #50 merged candidate `7fc10358a1d1713a562a4c9d3096b4398ba2c313` as `a820f8c1335a3178a4d61a6750f0752b1d7a5446`.
- CONFIRMED: #49 is already closed/integrated via PR #51 (`c223d683ec65188a0b9c68866d2ad103a7435dd3`, accepted candidate `0a9c453f87efb10dde977c70c735347bff100ed4`). Current integration is nine commits ahead of post-48 and includes #53/#57/#59. Readiness here means preserving/evaluating the #49 contract on the requested current integration, not authorizing duplicate implementation.
- CONFIRMED: #52 release tracker is closed. #55 is open, #56 closed; their issue bodies explicitly identify analytic identity/time and collection/reprocessing follow-ups. Closure/report text is context, not proof of baseline implementation.

Read: AGENTS.md; docs/agents/codex.md; PRODUCT_VISION; relevant ARCHITECTURE sections 4-7; ROADMAP R02; DECISIONS_AND_OPEN_QUESTIONS Garmin; EXECUTION_HISTORY R02; R02 normalization/persistence contracts; GitHub #48/#49 bodies, #49 integrator comments, PR #50 and compare API; tracker #52 and scoped #55/#56 context. No standalone ADR files or R02_IMPLEMENTATION_SPEC exist in the pinned tree: architecture/decisions + roadmap + issues govern. R01 spec is historical, not silently reused.

Scope: incremental/trailing, bounded backfill/replay, partial/error coverage, id-less corrections, provenance/time/series and CLI/API/storage agreement; at most eight adversarial scenarios. Only this report is a deliverable change. No production changes, provider calls, private runtime access, PR or merge.

Understood invariants: missing/null/zero differ; unknown/empty/unavailable differ; incomplete fetch must not advance successful checkpoint; history retained; stable current projection on replay/correction; explicit device evidence only; production provider identity separate from synthetic; historical state isolated from incremental; explicit bounded range/budget and coverage-driven resume.

Initial inspection targets (not findings yet): sample identity and timestamp fallback; aggregate aliases vs field provenance; source identity change when device evidence appears; authoritative empty/removal vs existing current rows; coverage-skip versioning; watermark vs unresolved earlier dates. Historical contract markdown still describes synthetic-only/semantic-value identity and must not be mistaken for the full production orchestration contract.

NOT CHECKED yet: implementation invariants, tests, eight scenarios, final #49 minimum contract. Owner-live behavior remains UNVERIFIED in this session.

## Checkpoint 2 — static sync/normalization audit

### C1 — CONFIRMED / PASS: bounded shared orchestration and state isolation
`garmin/backfill.py:292 GarminHistoricalBackfill.__init__` uses GarminIncrementalSync with `garmin_historical` namespace and coverage skip. `sync.py:1253 _ingest_window`, `1480 _fetch`, `369 _disable_provider_retries` bound application requests/retries; auth abort is explicit. `sync.py:1737 _write_checkpoint` changes success cursor/watermark only for present/confirmed_empty; failures preserve prior success state. Per-day surfaces are actually requested per day, not inferred from a sparse multi-day list. Watermark is latest successful date, not a contiguous-history proof; normal sync computes a fixed trailing interval and does not backfill gaps outside it.

### C2 — BLOCKER candidate pending reproduction: truncated activities can become complete
`sync.py:1506 _fetch_activities` breaks at exhausted budget after a nonempty full page, or exits MAX_ACTIVITY_PAGES, then returns `collected, None, used` without incomplete marker. `881 _coverage_status_for` accepts any expected duration metric; `1550 _persist_payload` writes successful coverage. `1317 _completed_coverage_status` then lets historical resume skip that exact interval. Static path is unambiguous; synthetic end-to-end probe will establish classification. This is directly within #49 bounded/resumable correctness, unlike analytic follow-ups.

### C3 — CONFIRMED semantic gaps; RISK for future consumers
- `sync.py:729 _reconcile_record` rekeys every sample with mutable `record_index`, discarding the sample_token supplied by `743 _series_records`; normalization.py:920 key also includes sample_index. Reorder/insertion can fork unchanged timestamp records. Persistence upserts received members only (`persistence.py:484`, `persist_result`) and does not retire absent collection members. Empty/removal/timestamp correction therefore is not a complete current-collection reconciliation policy. #56 explicitly tracks this scope, but its CLOSED state does not establish its presence in this pinned integration.
- `sync.py:809 _sample_temporal` attaches UTC to naive strings/datetimes, loses aware source-offset/local evidence, and assigns date-only request-day fallback to unstamped samples. This violates local-only no-invented-UTC intent; exact real provider exposure is UNKNOWN without live input (not needed/authorized here).
- `sync.py:488 _adapt_known_provider_shape` maps avg/max stress and daily/seven-day SpO2 into the same alias; `528 _summary_scalar` takes the last array element rather than a defined statistic/time ordering. Typed scalar field provenance reports the alias, while original field survives in raw evidence. Do not consume this as an analytic daily average. #55 is the existing bounded follow-up.
- `_source_identity_for` changes source identity on later target-device evidence. Identity partitions are honest, but same event can have both unattributed and attributed current rows without a supersession relation. No automatic cross-source dedup is justified without an explicit contract.

### C4 — CONFIRMED / PASS with limits: immutable evidence and replay
`persistence.py:805 persist_result`, `301 GarminPayloadObservationRepository`, `1068 _replay_current_records`: raw content and logical observations retained; exact existing observation replay returns current projection without replacing it. New observations can update existing stable keys. This does not prove receive-order independence for old payload reacquired under a new sync-run observation; retain that distinction in tests/report. Production `source_kind=provider` is explicitly passed by sync; raw fixture defaults remain synthetic.

### C5 — CONFIRMED operational/analytic distinction
`sync.py:857 _has_expected_metric` is existential (sleep duration or any expected value); `585 _parse_series` filters non-numeric samples. Thus present is acquisition-level, not complete series/score/stage/metric coverage. Unknown drift with no expected value remains refetchable, but mixed valid/invalid members can still be present. This needs explicit worker/consumer limits; no invented zero occurs in the inspected scalar-state path.

Checkpoint 2 is static evidence, not a claim that tests passed. Next: eight bounded scenarios, focused existing tests and a compact reproduction script. No production edits.

## Checkpoint 3 — adversarial review and reproductions

B1 — BLOCKER / CONFIRMED: bounded activity pagination can silently lose history. Synthetic end-to-end run on the pinned code returns `succeeded`, `present`, one request, zero remaining chunks after a full first page with a second page available. Exact rerun returns zero requests; page two is never requested. This violates complete coverage/resume, rather than merely limiting analytics. The same truncation return path exists in merged #48 (`git show a820f8c:src/healthcheck/garmin/sync.py`); it is not introduced by this audit. MAX_ACTIVITY_PAGES exhaustion follows the same path (static evidence; page-cap variant not separately executed). No real-account incidence claimed.

Exactly eight scenarios below. PASS denotes the specified invariant only; RISK can contain a confirmed behavior without declaring it a #49 blocker. Row 1's RISK is escalated to B1 above.

| Scenario | Expected invariant | Current behavior / evidence | Result |
| --- | --- | --- | --- |
| 1. Activities range returns a full first page, request budget ends before page two | Never mark truncated range complete; resume must fetch outstanding data | End-to-end probe: succeeded/present, remaining=0, rerun requests=0; sync.py:1506/1317/1550 | RISK — CONFIRMED B1 BLOCKER |
| 2. Yesterday's id-less samples corrected; array reordered/inserted/removed | Value correction converges; unchanged timestamps do not gain new current identities; absence requires authority | Existing value-correction regression keeps order and passes; probe reverses two samples and both keys change. No absent-member retirement in persistence upsert path. | RISK — confirmed key/collection gap, #56 scope |
| 3. Same sample instant has offset/Z forms, or naive local time crosses DST/day boundary | Equivalent instants agree; local-only never invents UTC; original offset retained | time_key uses normalized instant (static); probe naive string becomes UTC with no local evidence. Sample DTO drops offset/zone; date is request day. Offline scalar temporal tests do not exercise this adapter. | RISK — confirmed adapter gap, #55 scope |
| 4. Aggregate present, series absent (max-only stress / seven-day SpO2) | Aggregate meaning and source field remain distinct; no claim of complete samples | Probe maxStressLevel becomes typed payload.stress; present can be aggregate-only. Sleep duration does not prove scores/stages/naps; HRV expected field is weekly average. | RISK — confirmed semantic gap, #55 scope |
| 5. unknown -> valid, reviewed empty, or endpoint 404 | Missing is not zero; unavailable distinct from empty; unresolved fetch remains retryable | Existing unknown/empty/not-found and historical retry tests; skip includes only present/confirmed_empty. Generic empty container is accepted by existing contract, reviewed shells remain narrow. Later provider changes behind completed coverage require explicit reprocessing. | PASS for error/unknown retry; RISK for later correction of skipped complete history |
| 6. Retry supplies one valid and one malformed sample (or malformed activity sibling) | Retain evidence; do not imply whole collection analytically complete | Probe one valid + malformed HR sample gives present; parser filters bad sample. Coverage checks any expected metric, not every member. Normalization exceptions before raw serialization retain failure coverage but no raw observation (`_persist_payload` try ordering). | RISK — confirmed completeness/provenance limitation |
| 7. Device metadata appears only on second observation | No invented attribution; no unnoticed cross-source double counting | Probe source identities differ; source/record key partitions include attribution. Honest evidence retained, but no cross-partition supersession rule. Existing method/other-device tests cover no false Vivoactive promotion. | RISK — confirmed partition change; automatic merge policy UNKNOWN |
| 8. One requested day fails/is omitted while later days succeed; retry unchanged observation | Failure never becomes zero or successful day; preserve successes/history | Per-day fetch loop and failure tests preserve failed day coverage; later success can move max watermark past gap. Fixed trailing window may age gap out; backfill retries unknown/failed. Existing observation replay is protected; same bytes in a new sync run are a new observation, not guaranteed stale-replay protection. | PASS for bounded retry; RISK if watermark/readers assume contiguous history |

Additional interface finding — CONFIRMED: CLI prints the same service report JSON (`cli.py:284/326`), returns success for SUCCEEDED (or dry-run), failure otherwise. Thus B1 falsely succeeds through CLI too, by direct delegation; no separate live CLI invocation. `backfill.py:361 _run` also reports zero remaining once all chunks have been attempted without an abort, even if coverage is unknown/failed: remaining is unattempted work, not unresolved work. Status/attempt coverage must be read alongside counts. No Garmin HTTP read/sync endpoint exists in the pinned app/web routers; API parity is not an implemented Garmin surface, not a passing Garmin analytic contract. No divergent duplicate API implementation found in that bounded search.

Confirmed absence of a gap: existing raw observation replay, missing/null/zero scalar persistence, fixed-order id-less value correction, explicit source kind, not-found no-watermark, historical checkpoint isolation, and bounded capped-resume are covered by focused tests. Those tests do not negate B1 or collection/time gaps.

Reproduction command: `.venv\Scripts\python.exe .pytest-tmp/audit_probe.py` (exit 0). Script below asserts the defective behavior, not desired acceptance. Synthetic temporary runtime is outside checkout; no auth/provider network occurs. This script is embedded to make evidence reproducible without adding production/test files.

```python
from pathlib import Path
from datetime import date
import tempfile, json
from healthcheck.config import Settings
from healthcheck.garmin.backfill import GarminHistoricalBackfill
from healthcheck.garmin.sync import (GarminIncrementalSync, PRODUCTION_SYNC_SURFACES, ACTIVITY_PAGE_SIZE, _normalize_provider_payload, _prepare_normalization_result, _source_identity_for, _sample_temporal, _coverage_status_for)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.db.engine import create_sqlite_engine, create_session_factory
from healthcheck.db.models import GarminSourceRecord
from healthcheck.runtime import resolve_runtime_paths
from sqlalchemy import select, func
DAY=date(2099,1,2)
class Pages:
    garmin_connect_activities='/activitylist-service/activities/search/activities'
    def __init__(self): self.calls=0
    def connectapi(self, endpoint, params):
        self.calls+=1
        offset=int(params['start'])
        return [dict(activityId=offset+i+1,startTimeGMT='2099-01-02T08:00:00',duration=60) for i in range(ACTIVITY_PAGE_SIZE)] if offset==0 else [dict(activityId=9999,startTimeGMT='2099-01-02T09:00:00',duration=60)]
root=Path(tempfile.mkdtemp(prefix='r02-audit-probe-',dir='D:/Codex/Garmin'))
settings=Settings(data_dir=root/'runtime')
c=Pages()
svc=GarminHistoricalBackfill(settings,client=c,max_provider_requests=1)
a=svc.run(start=DAY,end=DAY,streams=['activities'],chunk_days=1)
b=svc.run(start=DAY,end=DAY,streams=['activities'],chunk_days=1)
assert a.status.value=='succeeded' and a.attempts[0].coverage_status=='present'
assert b.request_count==0 and c.calls==1
print('pagination',json.dumps(dict(first_status=a.status.value,first_requests=a.request_count,remaining=a.remaining_chunk_count,rerun_requests=b.request_count,never_requested_second_page=True)))

def normalized(code,payload):
    surface=next(s for s in PRODUCTION_SYNC_SURFACES if s.code==code)
    base=normalize_garmin_payload(_normalize_provider_payload(surface,payload,day=DAY),stream=surface.stream,source_identity=_source_identity_for(payload))
    return surface,_prepare_normalization_result(surface,payload,base,day=DAY)
p={'calendarDate':str(DAY),'heartRateValues':[[4070995200000,60],[4070995260000,61]]}
_,r1=normalized('heart_rate',p)
_,r2=normalized('heart_rate',dict(p,heartRateValues=list(reversed(p['heartRateValues']))))
k1={r.temporal.measured_at_utc:r.idempotency_key for r in r1.records if r.source_path.startswith('payload.heartRateValues[')}
k2={r.temporal.measured_at_utc:r.idempotency_key for r in r2.records if r.source_path.startswith('payload.heartRateValues[')}
assert len(k1)==2 and all(k1[t]!=k2[t] for t in k1)
print('reorder',json.dumps(dict(unchanged_timestamps_with_changed_keys=sum(k1[t]!=k2[t] for t in k1))))
t=_sample_temporal('2099-01-02T08:00:00',day=DAY,fallback=None)
assert t.measured_at_utc is not None and t.source_local_timestamp is None
print('naive_time',json.dumps(dict(invented_utc=True,local_evidence_lost=True)))
s,r=normalized('stress',{'calendarDate':str(DAY),'maxStressLevel':80})
m=next(m for rec in r.records for m in rec.metrics if m.metric_code=='stress' and m.has_value)
assert m.field_path=='payload.stress'
print('aggregate_alias',json.dumps(dict(original_max_field_replaced_in_typed_path=True)))
q=dict(p,heartRateValues=[p['heartRateValues'][0],['bad','bad']])
s,r=normalized('heart_rate',q)
assert _coverage_status_for(s,r,q,day=DAY)=='present'
print('mixed_shape',json.dumps(dict(coverage='present',invalid_sample_excluded=True)))
assert _source_identity_for(p)!=_source_identity_for(dict(p,device={'model':'Vivoactive 5'}))
print('late_device',json.dumps(dict(source_partition_changes=True)))
print('synthetic_runtime',str(root))
```

Probe output: pagination first_status=succeeded / first_requests=1 / remaining=0 / rerun_requests=0 / second page never requested; reorder changes both unchanged timestamp keys; naive-time UTC invented/local evidence lost; typed aggregate path loses max identity; mixed-shape coverage present; late device changes source partition. Assertions all passed.

Targeted existing tests: `.venv\Scripts\python.exe -m pytest tests/test_garmin_incremental_sync.py tests/test_garmin_historical_backfill.py tests/test_garmin_normalization.py tests/test_garmin_persistence.py -q --basetemp=D:\Codex\Garmin\audit-post48-tests-20260907` — **92 passed in 86.18s**, exit 0. Environment: `uv sync --locked`, CPython 3.13.15, pinned dependency unchanged. Full suite deliberately not run: no code change; targeted tests plus direct reproduction settle the blocking verdict. No owner-live verification.
