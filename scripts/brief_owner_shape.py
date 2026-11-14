"""Deterministic, synthetic-only storage shape for the /brief profiler.

Uses the repository's synthetic persistence fixtures for the evidence-bearing
history, then bulk inserts high-frequency history. Never reads an Owner profile.
Scale applies to density/history counts; the most recent 60 days stay populated.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import gettempdir

from sqlalchemy import func, insert, select, update

from healthcheck.config import Settings
from healthcheck.db import models as m
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.demo import seed_demo
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import resolve_runtime_paths

ANCHOR = date(2026, 10, 10)
TARGETS = {
    "google_record_metrics": 2_730_000, "google_source_records": 924_000,
    "google_record_source_evidence": 924_000, "garmin_record_metrics": 269_000,
    "garmin_source_records": 235_000, "garmin_intraday_records": 231_000,
    "garmin_payload_observations": 10_800, "garmin_raw_payloads": 5_500,
    "google_payload_observations": 8_100, "google_raw_payloads": 5_400,
    "google_sleep_intervals": 7_100, "coverage_intervals": 5_900,
    "ingest_events": 18_900, "garmin_daily_records": 1_700,
    "garmin_daily_summary_acquisition_receipts": 1_500,
    "garmin_sleep_records": 1_409, "sync_runs": 986, "canonical_selections": 862,
    "garmin_training_observation_records": 729, "agreement_metric_results": 700,
    "garmin_training_acquisitions": 419, "garmin_training_snapshots": 180,
    "agreement_run_pairs": 70, "agreement_run_exclusions": 240,
    "google_normalization_attempts": 4_100,
}


def generate_owner_shape(root: Path, *, scale: float = 1):
    root = root.resolve()
    if (not 0 < scale <= 1 or root.exists()
            or not root.is_relative_to(Path(gettempdir()).resolve())
            or root == Path(gettempdir()).resolve()):
        raise ValueError("owner-shape requires a new TEMP child and 0 < scale <= 1")
    # Existing offline benchmark fixtures are deliberately synthetic. Keep this
    # tooling dependency out of product imports and share their real write spine.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService
    from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
    from healthcheck.analytics.sleep_pairing import SleepPairingQuery
    from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.training import persist_training_payload
    from test_garmin_completed_steps import acquire
    from test_garmin_training_owner_view import _status
    from test_sleep_account_cohort import COHORT, _google

    settings = Settings(data_dir=root)
    seed_demo(settings)
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            store = ContentAddressedGarminPayloadStore(root / "artifacts")
            identity = garmin_source_identity(source_kind="provider", device_attributed=False)
            repo = GarminPersistenceRepository(session, payload_store=store)
            history = max(60, round(1500 * scale))
            for offset in range(history):
                day = ANCHOR - timedelta(days=offset)
                if offset < max(60, round(1200 * max(.9, scale))):
                    saved = acquire(
                        session, store, 0 if offset % 17 == 0 else 6000 + offset % 4000,
                        day=day, at=datetime.combine(day + timedelta(days=1),
                                                     datetime.min.time(), UTC),
                        receipt=True, commit=False,
                        account=identity.source_instance_id,
                        extra={"averageStressLevel": None if offset % 19 == 0 else offset % 60,
                               "restingHeartRate": 55 + offset % 10,
                               "moderateIntensityMinutes": offset % 30,
                               "vigorousIntensityMinutes": offset % 15})
                else:
                    payload = {"calendarDate": str(day), "totalSteps": 7000}
                    repo.persist_result(normalize_garmin_payload(
                        payload, stream="daily_health", source_identity=identity), payload=payload)
                if offset < max(60, round(1409 * scale)):
                    payload = {"dailySleepDTO": {"calendarDate": str(day),
                               "sleepTimeSeconds": 24000 + offset % 3000,
                               "sleepScores": {"overall": {"value": 65 + offset % 30}}}}
                    repo.persist_result(normalize_garmin_payload(
                        payload, stream="sleep", source_identity=identity), payload=payload)
                    google_saved = _google(session, paths, day, main="true",
                                           nap="false" if offset < 70 else "true")
                if offset < max(5, round(90 * scale)):
                    for repeat in range(4 if offset % 3 else 5):
                        persist_training_payload(session, store, surface="training_status",
                                                 requested_date=day + timedelta(days=repeat),
                                                 payload=_status(str(day)),
                                                 received_at=datetime.combine(
                                                     day + timedelta(days=repeat),
                                                     datetime.min.time(), UTC))
                if offset % 100 == 0:
                    session.commit()
            session.commit()
            session.info["shape_source"] = saved.source.id
            _domain_shape(session, paths, scale)
            # Naps produce exclusions on both sides; keep their fanout near
            # the requested 240 exclusions without suppressing ambiguity.
            for lower, upper in ((0, min(history - 1, 129)),
                                 (130, min(history - 1, 189))):
                if upper < lower:
                    continue
                projection = read_persisted_sleep_metric_projection(session, SleepPairingQuery(
                    cohort=COHORT, start_date=ANCHOR - timedelta(days=upper),
                    end_date=ANCHOR - timedelta(days=lower),
                    garmin_source_id=saved.source.id,
                    google_source_ids=(google_saved.source.id,)))
                PersistedSleepAgreementService(session).persist(
                    projection, scope_key=f"synthetic:owner-shape:{lower}")
            # Demo and long-history Google observations deliberately overlap on
            # recent nights. Keep that ambiguity; add a disjoint unambiguous
            # publication instead of rewriting source evidence to force pairing.
            if history >= 70:
                projection = read_persisted_sleep_metric_projection(session, SleepPairingQuery(
                    cohort=COHORT, start_date=ANCHOR - timedelta(days=69),
                    end_date=ANCHOR - timedelta(days=35), garmin_source_id=saved.source.id,
                    google_source_ids=(google_saved.source.id,)))
                PersistedSleepAgreementService(session).persist(
                    projection, scope_key="synthetic:owner-shape:comparison")
            session.commit()
            _dense_history(session, scale)
            _auxiliary_history(session, scale)
            session.commit()
            return write_manifest(session, root, scale)
    finally:
        engine.dispose()


def write_manifest(session, root, scale):
    from healthcheck.garmin.normalization import garmin_source_identity

    counts = {name: session.scalar(select(func.count()).select_from(
        m.Base.metadata.tables[name])) for name in TARGETS}
    identity = garmin_source_identity(source_kind="provider", device_attributed=False)
    source = session.scalar(select(m.GarminSource.id).where(
        m.GarminSource.source_instance_id == identity.source_instance_id))
    deviations = {name: count for name, count in counts.items()
                  if not .7 * TARGETS[name] <= count <= 1.3 * TARGETS[name]}
    manifest = {"synthetic_only": True, "scale": scale, "anchor": str(ANCHOR),
                "garmin_source_id": source, "counts": counts, "targets": TARGETS,
                "outside_owner_tolerance": deviations}
    (root / "owner-shape.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if scale >= .7 and deviations:
        raise ValueError(f"owner-shape table counts outside tolerance: {deviations}")
    return manifest


def _domain_shape(session, paths, scale):
    from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.sync import (
        PRODUCTION_SYNC_SURFACES,
        _normalize_provider_payload,
        _prepare_normalization_result,
    )
    from healthcheck.garmin.training import persist_training_payload
    from test_body_battery_read import seed_battery
    from test_garmin_training_owner_view import _persist_activity

    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    identity = garmin_source_identity(source_kind="provider", device_attributed=False)
    repo = GarminPersistenceRepository(session, payload_store=store)
    for offset in range(max(10, round(313 * scale))):
        day = ANCHOR - timedelta(days=offset)
        seed_battery(session, store, day=day, values=(80, 50, 20, 40, 60), identity=identity,
                     received=datetime.combine(day, datetime.min.time(), UTC))
        for code, fields in (("spo2", {"averageSpO2": 97 + offset % 3}),
                             ("respiration", {"respiration": 14 + offset % 3}),
                             ("stress", {"avgStressLevel": offset % 60})):
            surface = next(s for s in PRODUCTION_SYNC_SURFACES if s.code == code)
            payload = {"calendarDate": str(day), **fields}
            adapted = _normalize_provider_payload(surface, payload, day=day)
            normalized = normalize_garmin_payload(adapted, stream=surface.stream,
                                                  source_identity=identity)
            normalized = _prepare_normalization_result(surface, payload, normalized, day=day)
            repo.persist_result(normalized, payload=payload,
                                received_at=datetime.combine(day, datetime.min.time(), UTC))
    for offset in range(max(3, round(34 * scale))):
        day = ANCHOR - timedelta(days=offset)
        surface = next(s for s in PRODUCTION_SYNC_SURFACES if s.code == "hrv_status")
        payload = {"hrvSummary": {"calendarDate": str(day), "weeklyAvg": 30 + offset % 20}}
        normalized = normalize_garmin_payload(payload, stream=surface.stream,
                                              source_identity=identity)
        normalized = _prepare_normalization_result(surface, payload, normalized, day=day)
        repo.persist_result(normalized, payload=payload)
    for offset in range(max(4, round(80 * scale))):
        _persist_activity(session, store, activity_id=f"shape-activity-{offset}",
                          day=str(ANCHOR - timedelta(days=offset * 3)),
                          load=None if offset % 7 == 0 else offset % 40)
    count = session.scalar(select(func.count()).select_from(m.GarminTrainingSnapshot))
    for index in range(max(0, round(180 * scale) - count)):
        persist_training_payload(
            session, store, surface="training_status", requested_date=ANCHOR,
            received_at=datetime.combine(ANCHOR, datetime.min.time(), UTC),
            payload={"mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {
                "synthetic-device": {"monthlyLoadAerobicLow": index + 1000}}}})
    session.commit()
    _saved_steps_shape(session, paths, scale)


def _saved_steps_shape(session, paths, scale):
    from healthcheck.garmin.normalization import garmin_source_identity
    from healthcheck.garmin.observed_steps import SavedDailyStepsRepository

    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    identity = garmin_source_identity(source_kind="provider", device_attributed=False)
    source_id = session.scalar(select(m.GarminSource.id).where(
        m.GarminSource.source_instance_id == identity.source_instance_id))
    cursor = None
    while True:
        indexed = SavedDailyStepsRepository(session, payload_store=store).index_saved_summary_dates(
            source_id, after_raw_id=cursor, max_artifacts=64)
        session.commit()
        if indexed.exhausted_after_cursor:
            break
        cursor = indexed.proposed_after_raw_id
    observations = session.execute(select(
        m.GarminPayloadObservation.id,
        m.GarminDailySummaryAcquisitionReceipt.original_calendar_date,
    ).join(m.GarminDailySummaryAcquisitionReceipt).where(
        m.GarminPayloadObservation.garmin_source_id == source_id,
    ).order_by(m.GarminPayloadObservation.received_at.desc()).limit(
        max(3, round(73 * scale)))).all()
    for observation_id, day in observations:
        SavedDailyStepsRepository(session, payload_store=store).project_saved_summary(
            source_id, observation_id, start_date=day, end_date=day)
        session.commit()
    session.execute(update(m.GarminSourceRecord).where(
        m.GarminSourceRecord.surface_code.is_(None),
        m.GarminSourceRecord.stream_code == "daily_health",
        m.GarminSourceRecord.raw_payload_id.in_(select(
            m.GarminPayloadObservation.garmin_raw_payload_id).where(
                m.GarminPayloadObservation.source_filename == "daily_summary.json")),
    ).values(surface_code="daily_summary"))
    session.commit()


def _dense_history(session, scale):
    """High-density independent metric/record rows, spread over 313 source dates."""
    for model, metric_model, provider, total in (
        (m.GoogleSourceRecord, m.GoogleRecordMetric, "google", round(924000 * scale)),
        (m.GarminSourceRecord, m.GarminRecordMetric, "garmin", round(231000 * scale)),
    ):
        template = session.execute(select(model.__table__).limit(1)).mappings().one()
        common = dict(template)
        for field in ("diagnostics_json", "unknown_fields_json", "external_record_id",
                      "local_wall_time", "source_local_timestamp"):
            common[field] = None
        for offset in range(0, total, 5000):
            records, metrics, children = [], [], []
            for index in range(offset, min(offset + 5000, total)):
                stamp = datetime.combine(ANCHOR - timedelta(days=index % 313),
                                         datetime.min.time(), UTC) + timedelta(
                                             seconds=1 + index // 313)
                rid = f"shape-{provider}-{index}"
                stream = ("heart_rate" if provider == "google" or index % 231 < 137
                          else "stress")
                row = dict(common, id=rid, record_identity_key=rid, idempotency_key=rid,
                           stream_code="intraday" if provider == "garmin" else stream,
                           source_local_date=stamp.date(),
                           source_timestamp_utc=stamp, temporal_precision="instant")
                if provider == "garmin":
                    row["surface_code"] = stream
                    row["garmin_source_id"] = session.info["shape_source"] if (
                        "shape_source" in session.info) else common["garmin_source_id"]
                records.append(row)
                codes = ((stream, "synthetic_aux_a", "synthetic_aux_b")
                         if provider == "google" else (stream,))
                for code in codes:
                    metrics.append(dict(id=f"{rid}-{code}", record_id=rid, metric_code=code,
                                        field_path=f"$.{code}", state="value", value_number=60,
                                        unit="bpm" if code == "heart_rate" else "points",
                                        **({"capability_code": code,
                                            "source_device_attributed": False}
                                           if provider == "garmin" else {})))
                children.append(dict(record_id=rid, **(
                    {"state": "missing", "field_path": "$.dataSource", "evidence_json": "{}"}
                    if provider == "google" else {"sample_date": stamp.date(),
                                                  "sample_sequence": index})))
            session.execute(insert(model.__table__), records)
            session.execute(insert(metric_model.__table__), metrics)
            session.execute(insert((m.GoogleRecordSourceEvidence if provider == "google"
                                    else m.GarminIntradayRecord).__table__), children)
        session.commit()


def _auxiliary_history(session, scale):
    """Storage fanout outside the measured window; preserve FK/unique constraints.

    Cloned storage envelopes are synthetic load, not provider-acquisition proof.
    The measured daily receipts and agreement runs above use actual persistence.
    """
    for name in ("garmin_raw_payloads", "google_raw_payloads",
                 "garmin_payload_observations", "google_payload_observations",
                 "google_sleep_intervals", "ingest_events", "canonical_selections",
                 "google_normalization_attempts"):
        table = m.Base.metadata.tables[name]
        statement = select(table)
        if name in {"google_sleep_intervals", "google_normalization_attempts"}:
            column = (table.c.sleep_record_id if name == "google_sleep_intervals"
                      else table.c.observation_id)
            parent = (m.GoogleSourceRecord.id if name == "google_sleep_intervals"
                      else m.GoogleSourceRecord.observation_id)
            statement = statement.join(m.GoogleSourceRecord, parent == column).where(
                m.GoogleSourceRecord.source_local_date < ANCHOR - timedelta(days=90))
        templates = session.execute(statement.limit(10000)).mappings().all()
        if not templates:
            continue
        count = session.scalar(select(func.count()).select_from(table))
        total = max(0, round(TARGETS[name] * scale) - count)
        if name.endswith("raw_payloads") and session.scalar(select(table.c.id).where(
            table.c.id.like("shape-%")).limit(1)) is None:
            # Even tiny scales need a distinct invalid envelope for load-only
            # observations; they must not compete with evidence-bearing rows.
            total = max(1, total)
        envelope = None
        prefix = "garmin" if name.startswith("garmin") else "google"
        if name.endswith("payload_observations"):
            raw = m.GarminRawPayload if prefix == "garmin" else m.GoogleRawPayload
            envelope = session.execute(select(
                raw.id, getattr(raw, f"{prefix}_source_id"), raw.raw_artifact_id,
            ).where(raw.id.like("shape-%")).limit(1)).first()
        for offset in range(0, total, 1000):
            rows = []
            for index in range(offset, min(offset + 1000, total)):
                row = dict(templates[index % len(templates)])
                for column in ("id", "observation_key", "content_hash", "attempt_key",
                               "deduplication_key", "semantic_key"):
                    if column in row:
                        row[column] = f"shape-{name}-{index}"
                if "content_hash" in row:
                    row["content_hash"] = hashlib.sha256(row["id"].encode()).hexdigest()
                if name.endswith(("raw_payloads", "payload_observations")):
                    row["stream_code"] = "intraday" if name.startswith("garmin") else "heart_rate"
                    row["parse_status"] = "invalid"
                    row["record_count"] = 0
                if envelope is not None:
                    row[f"{prefix}_raw_payload_id"] = envelope.id
                    row[f"{prefix}_source_id"] = envelope[1]
                    row["raw_artifact_id"] = envelope.raw_artifact_id
                    row["ingest_event_id"] = row["sync_run_id"] = None
                if name == "google_sleep_intervals":
                    row["ordinal"] += index + 1000
                rows.append(row)
            session.execute(insert(table), rows)
        session.commit()
    # Independent immutable coverage intervals, not complete-wear assertions.
    provider = session.scalar(select(m.Provider.id).where(m.Provider.code == "garmin_connect"))
    count = session.scalar(select(func.count()).select_from(m.CoverageInterval))
    for index in range(max(0, round(5900 * scale) - count)):
        day = datetime.combine(ANCHOR - timedelta(days=index % 1413), datetime.min.time(), UTC)
        session.add(m.CoverageInterval(
            provider_id=provider, stream_code="daily_health", metric_code="stress",
            interval_start=day, interval_end=day + timedelta(days=1), resolution="day",
            status="unknown", calculation_rule_version="synthetic-shape-v1"))
