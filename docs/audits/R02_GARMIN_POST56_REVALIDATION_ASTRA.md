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
