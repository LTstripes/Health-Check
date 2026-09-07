# R02 post-56 targeted revalidation

## Checkpoint A — baseline and probe plan

IN PROGRESS. Review only F1–F4, not a general #56 audit.

- Remote main verified by git ls-remote: `c6f48d26a9eefee73b52f68835d931cce7b18388`; audit worktree pinned to that exact commit.
- Previous remote audit verified: `83cc2ac4e515bdb5a83e23192853148e931def3f`; report read from that object. Its reviewed integration was `aea777e418d8d16c275a860c31b11c72641a73e6`.
- New branch: `audit/r02-garmin-post56-revalidation-astra`.
- Read current AGENTS.md, #56 GitHub body (CLOSED), current R02_COLLECTION_RECONCILIATION_CONTRACT.md, scoped sync code and ROADMAP pre-R03 prerequisites.

| Finding | #56 change mapped in current code | Verification plan |
| --- | --- | --- |
| F1 pagination | sync.py `_fetch_activities` now returns `complete=False` for truncation; `_collection_scope` uses it for retirement. `_persist_payload` still computes checkpoint/status from coverage. | Repeat old full-first-page budget=1 backfill twice; inspect stored checkpoint, skipped requests, missing second-page record; retry also with larger budget. |
| F2 reorder identity | `_reconcile_record` retains sample_token and omits index when token exists; collection persistence maintains current/retired members. | Reorder/insert synthetic samples; compare keys and persisted current row IDs/counts; run exact existing regression. |
| F3 timezone | `_sample_temporal` still attaches UTC to naive stamps in static inspection. | Probe shared five surface adapters; inspect preserved date/offset and contract, no fix. |
| F4 completeness | collection completeness controls retirement; roadmap explicitly requires #55 metric analytic availability/manifest after #56. | Probe mixed invalid series and aggregate-only payload; distinguish collection scope from analytic sufficiency. |

Only this document will be committed. No provider calls or private runtime; synthetic temp runtime outside checkout. Tests/probe results remain NOT CHECKED at checkpoint A.

## Checkpoint B — F1/F2 completed

### F1 — STILL REPRODUCIBLE (CONFIRMED blocker)

Same synthetic full-first-page case as previous report: ACTIVITY_PAGE_SIZE=20, first page contains 20 valid activities, second page contains one additional valid activity. Budget=1; explicit one-day historical activities range. Three invocations: budgets 1, 1, then 2.

Observed: statuses `[succeeded, succeeded, succeeded]`; requests `[1, 0, 0]`; remaining chunks `[0, 0, 0]`; requested page offsets `[0]`; stored activities=20; second-page activity absent. Coverage=`present`; historical activities cursor=requested end, watermark and last_success set; job cursor=requested end and last_success set. Increasing budget after the false completion does not help ordinary same-range resume because coverage skip prevents fetching. The unread page is indefinitely omitted by that normal resume path; this is not a claim that explicit other recovery paths cannot reacquire it.

Evidence: `sync.py:1601 _fetch_activities` now flags truncation, but `1711 _persist_payload` passes completeness only to `_collection_scope`; `_write_checkpoint` still sets succeeded solely from present/confirmed_empty, and `_completed_coverage_status:1370` skips present. #56 fixed retirement authority, not this operational status/checkpoint/resume blocker. Regression oracle asserting safe completion would FAIL.

### F2 — FIXED (CONFIRMED)

Independent persisted probe: two timestamped HR samples -> reversed same samples -> new sample inserted before reversed samples. Total sample rows `[2,2,3]`; the original idempotency keys AND database row IDs remained identical; zero duplicate sample rows. Current `_reconcile_record:732` preserves sample_token and excludes mutable index when token exists. This finding was a property of the old integration baseline and is fixed by #56 on current main. Scope is stable-token reorder/insert, not a claim about identity of genuinely unstamped samples.

Existing focused tests: `test_reorder_and_insert_keep_stable_sample_identity` and `test_activity_collection_retires_only_when_pages_complete` — **2 passed in 7.55s**. The latter proves retirement safety only and does not invalidate F1.

Command: `.venv\Scripts\python.exe -m pytest tests/test_garmin_collection_reconciliation.py::test_reorder_and_insert_keep_stable_sample_identity tests/test_garmin_collection_reconciliation.py::test_activity_collection_retires_only_when_pages_complete -q --basetemp=D:\Codex\Garmin\post56-targeted-20260907`.

Probe command: `.venv\Scripts\python.exe .pytest-tmp/revalidate.py`, exit 0. Initial probe-only inspection typo (`source_record_id` instead of model's `external_record_id`) was corrected; successful run above used a fresh synthetic temp runtime. No production changes.

### Reproducible F1/F2 probe

```python
from pathlib import Path
from datetime import date
import tempfile, json, sys
from sqlalchemy import select
from healthcheck.config import Settings
from healthcheck.garmin.backfill import GarminHistoricalBackfill
from healthcheck.garmin.sync import ACTIVITY_PAGE_SIZE
from healthcheck.db.engine import create_sqlite_engine, create_session_factory
from healthcheck.db.models import GarminSourceRecord, SyncStreamState, CoverageInterval
from healthcheck.runtime import resolve_runtime_paths
DAY=date(2099,1,2)
class Pages:
    garmin_connect_activities='/activitylist-service/activities/search/activities'
    def __init__(self): self.offsets=[]
    def connectapi(self, endpoint, params):
        offset=int(params['start']); self.offsets.append(offset)
        return [dict(activityId=offset+i+1,startTimeGMT='2099-01-02T08:00:00',duration=60) for i in range(ACTIVITY_PAGE_SIZE)] if offset==0 else [dict(activityId=9999,startTimeGMT='2099-01-02T09:00:00',duration=60)]
root=Path(tempfile.mkdtemp(prefix='r02-post56-',dir='D:/Codex/Garmin'))
settings=Settings(data_dir=root/'pagination'/'runtime'); client=Pages()
def run(budget):
    return GarminHistoricalBackfill(settings,client=client,max_provider_requests=budget).run(start=DAY,end=DAY,streams=['activities'],chunk_days=1)
a=run(1); b=run(1); c=run(2)
engine=create_sqlite_engine(resolve_runtime_paths(settings)); factory=create_session_factory(engine)
with factory() as session:
    rows=list(session.scalars(select(GarminSourceRecord)))
    states=list(session.scalars(select(SyncStreamState)))
    coverage=list(session.scalars(select(CoverageInterval)))
    result=dict(statuses=[r.status.value for r in (a,b,c)],requests=[r.request_count for r in (a,b,c)],remaining=[r.remaining_chunk_count for r in (a,b,c)],offsets=client.offsets,records=len(rows),page_size=ACTIVITY_PAGE_SIZE,second_page_missing=not any(r.external_record_id=='9999' for r in rows),coverage=[r.status for r in coverage],states=[dict(stream=r.stream_code,cursor=r.cursor,watermark_set=r.watermark is not None,last_success_set=r.last_success_at is not None) for r in states])
    assert result['requests']==[1,0,0] and result['second_page_missing']
    assert all(s=='succeeded' for s in result['statuses'])
    assert any(r.cursor==str(DAY) and r.watermark is not None for r in states)
print('F1',json.dumps(result)); engine.dispose()
# Use existing synthetic client helpers, but inspect exact persisted IDs independently.
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_garmin_collection_reconciliation import _run, _client, _hr, _engine_factory, _hr_rows
location=root/'identity'
samples=[['2099-01-02T08:00:00Z',60],['2099-01-02T08:15:00Z',72]]
def snapshot(payload):
    assert _run(location,_client(heart_rate=_hr(payload))).status.value=='succeeded'
    e,f=_engine_factory(location)
    with f() as s:
        rows=_hr_rows(s)
        result={r.idempotency_key:r.id for r in rows if r.projection_status=='current'}
        total=len(rows)
    e.dispose(); return result,total
first,n1=snapshot(samples)
second,n2=snapshot(list(reversed(samples)))
third,n3=snapshot([['2099-01-02T07:45:00Z',58],*reversed(samples)])
assert first==second and all(third[k]==v for k,v in first.items()) and [n1,n2,n3]==[2,2,3]
print('F2',json.dumps(dict(total_rows=[n1,n2,n3],original_ids_preserved=True,duplicate_rows=0)))

```

## Checkpoint C — F3/F4 and final verdict

### F3 — RISK (confirmed semantic defect; not an accepted contract)

Current `sync.py:860 _sample_temporal` attaches UTC to naive strings/datetimes. Independent adapter probes reproduce it on **heart_rate, stress, body_battery, spo2, respiration** sample surfaces. Each naive sample becomes a UTC instant, original local evidence is absent, requested local date stays unchanged. Aware sample offset evidence is also not retained.

Boundary probe: naive `2099-01-02T00:30:00` vs explicitly offset `2099-01-02T00:30:00+03:00` produces different UTC dates while both stored local dates remain the requested day. Thus it does not shift the request-day column in ordinary day fetches, but can shift UTC-day grouping, ordering against correctly zoned samples, lag/duration calculations and analytic day attribution. Without a supplied day, fallback date is derived from the assumed UTC instant. The true offset of a naive provider sample is unknown; this probe does not claim it is +03:00, it demonstrates why assuming UTC is unsafe.

This is a confirmed code/normalization-contract mismatch (`R02_NORMALIZATION_CONTRACT.md:34` forbids invented timezone), not ACCEPTED CONTRACT. Classified RISK because actual owner payload incidence is unverified and this session does not implement analytics. #55 explicitly requires the correction before R03. Sleep/RHR/HRV/daily summary singleton timestamps are not claimed affected by this shared sample helper; no extra surface audit performed.

### F4 — R03 CONTRACT GAP (CONFIRMED)

`present` is operational surface acquisition coverage, intentionally not proof of metric-level analytical sufficiency. Current `sync.py:908 _has_expected_metric` needs any expected value. `588 _parse_series` drops malformed/non-numeric samples. Probe with one valid + one malformed HR sample gives one parsed sample, coverage=present, and `_collection_scope(... fetch_complete=True)` complete=True. This complete flag authorizes collection reconciliation; it is not an analytic completeness certificate.

Aggregate-only probes still map `maxStressLevel` to typed `payload.stress` and `lastSevenDaysAvgSpO2` to typed `payload.spo2`, both present. Treating those as a daily mean or treating present as a full sample series can therefore produce false health conclusions. Raw provenance survives, but raw retention by itself does not provide a safe analytic metric definition.

Separate mechanisms now present: collection authority/current-retired state, reconciliation versions, explicit reprocess, history gaps. None is a metric-specific sufficiency/aggregation/exclusion/evidence-manifest API. Scoped search of current Garmin code plus current ROADMAP:73-78 and open GitHub #55 confirm that the bounded analytic availability + input DTO/manifest contract remains a prerequisite, not a delivered feature of #56. R03 must use that future accepted contract; it must not consume surface present as sufficiency. No R03 implementation or new broad review performed.

### F3/F4 reproducible probe

Command `.venv\Scripts\python.exe .pytest-tmp/semantic_probe.py` — exit 0, all assertions passed (assertions describe current behavior, not desired correctness).

```python
from datetime import date
import json
from healthcheck.garmin.sync import (PRODUCTION_SYNC_SURFACES, _normalize_provider_payload, _prepare_normalization_result, _source_identity_for, _coverage_status_for, _collection_scope, _sample_temporal)
from healthcheck.garmin.normalization import normalize_garmin_payload
DAY=date(2099,1,2)
def normalize(code,payload):
    s=next(s for s in PRODUCTION_SYNC_SURFACES if s.code==code)
    r=normalize_garmin_payload(_normalize_provider_payload(s,payload,day=DAY),stream=s.stream,source_identity=_source_identity_for(payload))
    return s,_prepare_normalization_result(s,payload,r,day=DAY)
fields={'heart_rate':'heartRateValues','stress':'stressValuesArray','body_battery':'bodyBatteryValuesArray','spo2':'spo2Values','respiration':'respirationValues'}
for code,field in fields.items():
    p={'calendarDate':str(DAY),field:[['2099-01-02T00:30:00',60]]}
    s,r=normalize(code,p)
    sample=next(r for r in r.records if r.source_path.startswith('payload.'+field+'['))
    t=sample.temporal
    assert t.measured_at_utc is not None and t.source_local_timestamp is None and t.local_date==DAY
    print('F3',code,'naive_promoted_to_utc; local_evidence_missing; request_day_retained')
naive=_sample_temporal('2099-01-02T00:30:00',day=DAY,fallback=None)
aware=_sample_temporal('2099-01-02T00:30:00+03:00',day=DAY,fallback=None)
assert naive.measured_at_utc.date()!=aware.measured_at_utc.date()
assert naive.local_date==aware.local_date==DAY
print('F3_day_boundary',json.dumps(dict(utc_date_differs=True,requested_local_date_unchanged=True,aware_offset_lost=aware.source_utc_offset_minutes is None)))
p={'calendarDate':str(DAY),'heartRateValues':[['2099-01-02T08:00:00Z',60],['bad','bad']]}
s,r=normalize('heart_rate',p); coverage=_coverage_status_for(s,r,p,day=DAY)
scope=_collection_scope(s,day=DAY,window_start=DAY,window_end=DAY,fetch_complete=True,coverage_status=coverage)
assert coverage=='present' and scope.complete
samples=[x for x in r.records if x.source_path.startswith('payload.heartRateValues[')]
assert len(samples)==1
print('F4_mixed',json.dumps(dict(raw_samples=2,parsed_samples=1,coverage=coverage,collection_complete=scope.complete)))
for code,field,metric in [('stress','maxStressLevel','stress'),('spo2','lastSevenDaysAvgSpO2','spo2_percent')]:
    p={'calendarDate':str(DAY),field:80}; s,r=normalize(code,p)
    m=next(m for x in r.records for m in x.metrics if m.metric_code==metric and m.has_value)
    assert _coverage_status_for(s,r,p,day=DAY)=='present'
    print('F4_aggregate',json.dumps(dict(surface=code,original_field=field,typed_field=m.field_path,coverage='present')))
```

## Final disposition

| Finding | Current main verdict | Old-only / remaining |
| --- | --- | --- |
| F1 | STILL REPRODUCIBLE | Still current blocker; #56 changed retirement protection, not false-success/resume. |
| F2 | FIXED | Old integration finding resolved for timestamp/token-backed reorder/insert, including persisted row identity. |
| F3 | RISK | Confirmed current naive-to-UTC defect; existing #55 prerequisite, no owner-incidence claim. |
| F4 | R03 CONTRACT GAP | Deliberate operational coverage meaning; safe analytic sufficiency contract remains in #55. |

**OVERALL: BLOCKED.** F1 remains a reproduced current-main ingestion/resume blocker. Additionally #55 is required before R03 can safely consume metric/time/completeness semantics. No claim that all #56 behavior was reviewed, and no duplicate implementation requested for fixed F2.

Required follow-ups (two only):
1. Focused F1 fix: carry pagination incompleteness into run status, successful checkpoint and coverage-skip/resume. Regression must prove unread page is fetched on subsequent invocation and cannot remain hidden behind present; cover request budget/page cap. Audit does not implement the fix.
2. Finish existing #55 for F3/F4: evidence-based sample time, distinct aggregate identities, metric analytic sufficiency/exclusions and reproducible input manifest. Do not invent a second analytics stack in this audit.

## Delivery / validation

- Current reviewed remote main: `c6f48d26a9eefee73b52f68835d931cce7b18388`.
- Audit branch: `audit/r02-garmin-post56-revalidation-astra`.
- Only changed file: `docs/audits/R02_GARMIN_POST56_REVALIDATION_ASTRA.md`.
- Checkpoints A, B, C committed and pushed separately; final commit SHA reported outside its own content and verified by remote read-back.
- Locked environment (CPython 3.13.15), two targeted existing tests passed; F1/F2 persisted probes and F3/F4 adapter probes passed their observed-behavior assertions. No full suite needed/run.
- No production edits, live provider calls, private runtime access, PR or merge. Scope is exactly F1–F4. `git diff --check` clean; final tracked working tree checked at handoff.
