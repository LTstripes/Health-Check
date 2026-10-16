"""Request-local bounded input loading for #380; aggregation stays in #347."""

from collections import Counter, defaultdict
from time import monotonic

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from healthcheck.analytics.sleep_metrics import (
    _record_evidence,
    _SleepEvidenceInputs,
    _StoredSleepSide,
)
from healthcheck.analytics.sleep_pairing import (
    ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
    _garmin_source_eligibility,
    _google_account_eligibility,
    _google_source_eligibility,
)
from healthcheck.analytics.sleep_source_view import _session_view
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GoogleNormalizationAttempt,
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSource,
)

MAX_PERIOD_RECORDS = 4096
MAX_NIGHT_RECORDS = 200
MAX_PERIOD_SOURCES = 32
MAX_METRIC_ROWS = 16384
MAX_METADATA_ROWS = 8192
MAX_COVERAGE_ROWS = 2048
READ_BUDGET_SECONDS = 2.0
BATCH_SIZE = 256


class IncompletePeriodRead(Exception):
    """A complete official aggregate cannot be established within the limits."""


class PeriodReadBudget:
    def __init__(self, session, *, preserve_sql_guard=False):
        self.session = session
        self.preserve_sql_guard = preserve_sql_guard
        self.deadline = monotonic() + READ_BUDGET_SECONDS
        self.driver = session.connection().connection.driver_connection

    def __enter__(self):
        if self.preserve_sql_guard:
            return self
        self.busy_timeout = self.driver.execute("PRAGMA busy_timeout").fetchone()[0]
        self.driver.set_progress_handler(lambda: int(monotonic() >= self.deadline), 1000)
        return self

    def __exit__(self, *exc):
        if self.preserve_sql_guard:
            return
        self.driver.set_progress_handler(None, 0)
        self.driver.execute(f"PRAGMA busy_timeout = {self.busy_timeout}")

    def check(self):
        if monotonic() >= self.deadline:
            raise IncompletePeriodRead("time_budget_exceeded")

    def rows(self, query, cap, reason, *, scalar=True):
        self.check()
        # SQLite VM callbacks do not run during lock waits. Bound that wait by
        # the remaining request budget too, then restore caller connection policy.
        remaining_ms = max(1, int((self.deadline - monotonic()) * 1000))
        if not self.preserve_sql_guard:
            self.driver.execute(f"PRAGMA busy_timeout = {min(self.busy_timeout, remaining_ms)}")
        try:
            result = self.session.execute(query.limit(cap + 1))
            rows = list(result.scalars() if scalar else result)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlite_errorcode", None) in {5, 6, 9}:
                # SQLITE_BUSY, SQLITE_LOCKED or SQLITE_INTERRUPT.
                raise IncompletePeriodRead("time_budget_exceeded") from exc
            raise
        self.check()
        if len(rows) > cap:
            raise IncompletePeriodRead(reason)
        return rows

    def related(self, model, column, identities, *, cap=None, conditions=()):
        cap = MAX_METADATA_ROWS if cap is None else cap
        identities = sorted(set(identities))
        rows = []
        for offset in range(0, len(identities), BATCH_SIZE):
            rows.extend(
                self.rows(
                    select(model).where(
                        column.in_(identities[offset : offset + BATCH_SIZE]), *conditions
                    ),
                    cap - len(rows),
                    "ancillary_row_limit_exceeded",
                )
            )
        return rows

    def observations(self, records, *, google):
        model = GooglePayloadObservation if google else GarminPayloadObservation
        column = model.google_raw_payload_id if google else model.garmin_raw_payload_id
        rows = self.related(model, column, [r.raw_payload_id for r in records])
        return sorted(rows, key=lambda r: (r.received_at, r.id))

    def sleep_sessions(self, source, records):
        """Load only duration/role/variant inputs and their accepted immutable evidence."""
        google = isinstance(source, GoogleSource)
        provider = "google" if google else "garmin"
        current = [r for r in records if r.projection_status == "current"]
        ids = [r.id for r in current]
        metric_model = GoogleRecordMetric if google else GarminRecordMetric
        codes = (
            (
                "sleep_summary_minutes_asleep",
                "sleep_type",
                "sleep_metadata_main",
                "sleep_metadata_nap",
            )
            if google
            else ("sleep_duration_seconds",)
        )
        metrics = self.related(
            metric_model,
            metric_model.record_id,
            ids,
            cap=MAX_METRIC_ROWS,
            conditions=(metric_model.metric_code.in_(codes),),
        )
        metrics_by_record = defaultdict(list)
        for metric in metrics:
            metrics_by_record[metric.record_id].append(metric)
        raw_model = GoogleRawPayload if google else GarminRawPayload
        raw = {
            r.id: r
            for r in self.related(raw_model, raw_model.id, [r.raw_payload_id for r in current])
        }
        observations = self.observations(current, google=google)
        by_raw = defaultdict(list)
        for row in observations:
            raw_id = row.google_raw_payload_id if google else row.garmin_raw_payload_id
            by_raw[raw_id].append(row)
        by_id = {r.id: r for r in observations}
        evidence = {}
        attempts_by_observation = defaultdict(list)
        if google:
            # Explicit observation references may be mismatched: load, then let
            # the original evidence rules reject them rather than invent absence.
            missing_ids = {r.observation_id for r in current if r.observation_id} - by_id.keys()
            for row in self.related(
                GooglePayloadObservation,
                GooglePayloadObservation.id,
                missing_ids,
                cap=MAX_METADATA_ROWS - len(observations),
            ):
                by_id[row.id] = row
            evidence = {
                r.record_id: r
                for r in self.related(
                    GoogleRecordSourceEvidence, GoogleRecordSourceEvidence.record_id, ids
                )
            }
            attempts = self.related(
                GoogleNormalizationAttempt, GoogleNormalizationAttempt.observation_id, by_id.keys()
            )
            for row in sorted(
                attempts,
                key=lambda r: (
                    r.normalization_contract_version,
                    r.attempted_at,
                    r.id,
                ),
            ):
                attempts_by_observation[row.observation_id].append(row)
        sessions = {}
        for record in current:
            self.check()
            source_evidence = evidence.get(record.id)
            eligibility = (
                _google_account_eligibility(
                    _google_source_eligibility(record, source, source_evidence),
                    source,
                    source_evidence,
                )
                if google
                else _garmin_source_eligibility(
                    record,
                    source,
                    cohort=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
                )
            )
            candidates = (
                (by_id[record.observation_id],)
                if google and record.observation_id in by_id
                else tuple(by_raw[record.raw_payload_id])
            )
            if google and record.observation_id and record.observation_id not in by_id:
                candidates = ()
            inputs = _SleepEvidenceInputs(
                raw=raw.get(record.raw_payload_id),
                observations=candidates,
                attempts=tuple(a for o in candidates for a in attempts_by_observation[o.id]),
                source_evidence=source_evidence,
            )
            side = _StoredSleepSide(
                provider=provider,
                source=source,
                record=record,
                metrics=tuple(metrics_by_record[record.id]),
                stages=(),
                field_state=None,
                evidence=_record_evidence(
                    self.session,
                    provider=provider,
                    source=source,
                    record=record,
                    eligibility=eligibility,
                    inputs=inputs,
                ),
            )
            sessions[record.id] = side
        self.check()
        return sessions

    def night(self, source, records, sides, wake_date):
        self.check()
        if len(records) > MAX_NIGHT_RECORDS:
            raise IncompletePeriodRead("night_group_limit_exceeded")
        sessions = [
            _session_view(sides[r.id], wake_date, metric_codes=("sleep_duration_asleep_seconds",))
            for r in records
        ]
        self.check()
        return sessions

    def snapshot_evidence(self, records, *, google):
        observations = self.observations(records, google=google)
        counts = Counter(
            r.google_raw_payload_id if google else r.garmin_raw_payload_id for r in observations
        )
        if records:
            self.check()
        return {
            "duplicate_payload_observation_count": sum(max(0, n - 1) for n in counts.values()),
            "normalization_versions": sorted({r.normalization_contract_version for r in records}),
            "retirement_reason_counts": dict(
                sorted(
                    Counter(
                        r.retire_reason or "unspecified"
                        for r in records
                        if r.projection_status == "retired"
                    ).items()
                )
            ),
        }


def read_limits():
    return {
        "candidate_records_per_source_surface": MAX_PERIOD_RECORDS,
        "records_per_night": MAX_NIGHT_RECORDS,
        "source_identities": MAX_PERIOD_SOURCES,
        "metric_rows_per_surface": MAX_METRIC_ROWS,
        "metadata_rows_per_table_surface": MAX_METADATA_ROWS,
        "coverage_intervals_per_surface": MAX_COVERAGE_ROWS,
        "budget_seconds": READ_BUDGET_SECONDS,
    }
