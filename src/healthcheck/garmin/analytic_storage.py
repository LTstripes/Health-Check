"""Short-lived, bounded storage inputs for one Garmin scalar-series assembly.

No cross-request cache: keep ORM rows alive only while assembling the selected
window. Validation remains in analytic_contract, shared with single-row reads.
"""

from collections import defaultdict
from collections.abc import Sequence
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSleepStageInterval,
    GarminSource,
    GarminSourceRecord,
    IngestBatch,
    IngestEvent,
    Provider,
)

# Stay below SQLite's conservative bind limit, even at the 2000-point series cap.
_CHUNK_SIZE = 400


class GarminAnalyticStorageBatch:
    def __init__(self, session: Session, rows: Sequence, *, stress_provenance: bool = False):
        self._rows = {}
        self.observations = defaultdict(list)
        self.metrics = defaultdict(list)
        self.stages = defaultdict(list)
        for metric, record in rows:
            self._remember(metric)
            self._remember(record)
        records = list(self._rows.get(GarminSourceRecord, {}).values())
        raws = self._load(session, GarminRawPayload, {r.raw_payload_id for r in records})
        sources = self._load(session, GarminSource, {r.garmin_source_id for r in records})
        observations = self._load(
            session, GarminPayloadObservation, {r.id for r in raws},
            column=GarminPayloadObservation.garmin_raw_payload_id,
            order=(GarminPayloadObservation.received_at, GarminPayloadObservation.id),
        )
        for observation in observations:
            self.observations[observation.garmin_raw_payload_id].append(observation)
        sleep_ids = {record.id for metric, record in rows
                     if metric.metric_code == "sleep_duration_seconds"}
        metric_ids = sleep_ids | {r.id for r in records if r.stream_code == "activity"}
        for metric in self._load(session, GarminRecordMetric, metric_ids,
                                 column=GarminRecordMetric.record_id):
            self.metrics[metric.record_id].append(metric)
        for stage in self._load(session, GarminSleepStageInterval, sleep_ids,
                                column=GarminSleepStageInterval.sleep_record_id,
                                order=(GarminSleepStageInterval.ordinal,)):
            self.stages[stage.sleep_record_id].append(stage)
        if stress_provenance:
            self._load(session, Provider, {s.provider_id for s in sources})
            events = self._load(session, IngestEvent,
                                {o.ingest_event_id for o in observations if o.ingest_event_id})
            self._load(session, IngestBatch, {e.ingest_batch_id for e in events})

    def _remember(self, row):
        self._rows.setdefault(type(row), {})[row.id] = row

    def get(self, model, row_id):
        return self._rows.get(model, {}).get(row_id)

    def _load(self, session, model, ids, *, column=None, order=()):
        column = model.id if column is None else column
        ids = sorted(ids)
        rows = []
        for offset in range(0, len(ids), _CHUNK_SIZE):
            # These are bounded, read-only assembly inputs, not entities to
            # mutate. Preserve SQLAlchemy's typed decoding without identity-map
            # hydration or later lazy refreshes after a nested snapshot read.
            statement = select(*model.__table__.columns).where(
                column.in_(ids[offset:offset + _CHUNK_SIZE]))
            for values in session.execute(statement.order_by(*order)).mappings():
                row = SimpleNamespace(**values)
                self._rows.setdefault(model, {})[row.id] = row
                rows.append(row)
        return rows
