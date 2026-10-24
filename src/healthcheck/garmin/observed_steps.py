"""Bounded projection of saved Garmin account-level Steps observations.

This contract does not establish full-day coverage, device attribution, timezone,
or correction authority. The caller owns acquisition/runtime; this service reads saved bytes only.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from time import monotonic

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminDailySummaryDateProof,
    GarminPayloadObservation,
    GarminRawPayload,
    GarminSource,
    RawArtifact,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.capabilities import CapabilityStatus, GarminStream
from healthcheck.garmin.normalization import (
    GarminFieldState,
    GarminMetricDTO,
    GarminRecordDTO,
    GarminSourceIdentity,
    GarminTemporalDTO,
    GarminTemporalPrecision,
)
from healthcheck.garmin.persistence import GarminCollectionScope, GarminSourceRecordRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore

CONTRACT_VERSION = "garmin-observed-daily-steps-v1"
METRIC_CODE = "observed_daily_steps"
MAX_ARTIFACTS = 1000
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_OBSERVATIONS = 4096
DATE_PROOF_VERSION = "garmin-daily-summary-saved-date-v1"
MAX_TOTAL_READ_BYTES = 16 * 1024 * 1024
MAX_READ_SECONDS = 5.0
MAX_SQL_STEPS = 20_000_000
DEFAULT_INDEX_BATCH = 64
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class SavedStepsEvidenceError(ValueError):
    """The bounded saved-evidence snapshot could not be verified completely."""


class SavedStepsBudgetError(SavedStepsEvidenceError):
    """The complete operation exceeded its shared cooperative work allowance."""


@dataclass(frozen=True, slots=True)
class UnprovenSummaryDate:
    raw_payload_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SavedSummaryDateIndexBatch:
    """Proposed cursor is usable only after the caller successfully commits.

    Suffix exhaustion describes this snapshot, never complete source history.
    New lower-ID arrivals and unresolved rows require a fresh sweep from None.
    """

    garmin_source_id: str
    input_after_raw_id: str | None
    proposed_after_raw_id: str | None
    examined_raws: int
    inspected_observations: int
    read_allowance_bytes: int
    inserted_proofs: int
    unproven: tuple[UnprovenSummaryDate, ...]
    stop_reason: str
    exhausted_after_cursor: bool


class _SavedStepsBudget:
    """Own the guard on a dedicated writer connection with no prior callback.

    The normal factory installs no progress handler. Nested repository methods
    borrow this same scope. SQLite cannot introspect an arbitrary external
    callback; callers must not supply a connection guarded by another service.
    """

    def __init__(self, session):
        self.driver = session.connection().connection.driver_connection
        self.deadline = monotonic() + MAX_READ_SECONDS
        self.sql_steps = 0
        self.read_allowance_bytes = 0

    def __enter__(self):
        self.busy_timeout = self.driver.execute("PRAGMA busy_timeout").fetchone()[0]
        self.driver.execute(f"PRAGMA busy_timeout = {min(self.busy_timeout, 100)}")
        self.driver.set_progress_handler(self._progress, 1000)
        return self

    def _progress(self):
        self.sql_steps += 1000
        return int(self.sql_steps >= MAX_SQL_STEPS or monotonic() >= self.deadline)

    def __exit__(self, *_exc):
        self.driver.set_progress_handler(None, 0)
        self.driver.execute(f"PRAGMA busy_timeout = {self.busy_timeout}")

    def check(self):
        if monotonic() >= self.deadline or self.sql_steps >= MAX_SQL_STEPS:
            raise SavedStepsBudgetError("saved daily-summary work bound exceeded")

    def rows(self, session, query, cap, *, scalar=True):
        self.check()
        result = session.execute(query.limit(cap + 1))
        rows = list(result.scalars() if scalar else result)
        self.check()
        return rows

    def reserve_read(self, max_bytes):
        self.check()
        # read(max_bytes + 1) must remain bounded even when metadata is corrupt.
        allowance = max_bytes + 1
        if self.read_allowance_bytes + allowance > MAX_TOTAL_READ_BYTES:
            raise SavedStepsBudgetError("saved daily-summary total byte bound exceeded")
        self.read_allowance_bytes += allowance


@dataclass(frozen=True, slots=True)
class SavedStepsEvidence:
    raw_payload_id: str
    raw_artifact_id: str
    content_hash: str
    observation_ids: tuple[str, ...]
    record_id: str
    state: GarminFieldState
    value: int | None


@dataclass(frozen=True, slots=True)
class ExcludedStepsArtifact:
    raw_payload_id: str
    observation_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ObservedDailySteps:
    """One source/day's saved observations; never a fused or final daily total."""

    garmin_source_id: str
    calendar_date: date
    state: str
    value: int | None
    reason: str | None
    evidence: tuple[SavedStepsEvidence, ...]
    excluded_artifacts: tuple[ExcludedStepsArtifact, ...]
    metric_code: str = METRIC_CODE
    unit: str = "steps"
    attribution: str = "account"
    coverage: str = "unknown"
    device: str = "unknown"
    timezone: str = "unknown"
    finality: str = "unknown"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _decode(content: bytes) -> tuple[dict[str, object] | None, str | None]:
    try:
        payload = json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "unsupported_payload_shape"
    return payload, None


def _calendar_date(payload: dict[str, object]) -> date | None:
    value = payload.get("calendarDate")
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _metric(payload: dict[str, object]) -> GarminMetricDTO:
    value = payload.get("totalSteps")
    if "totalSteps" not in payload:
        state, reason = GarminFieldState.MISSING, "field_absent_in_payload"
    elif value is None:
        state, reason = GarminFieldState.NULL, "source_null"
    elif type(value) is int and value >= 0:
        state, reason = GarminFieldState.VALUE, None
    else:
        state, reason = GarminFieldState.INVALID, "expected_nonnegative_integer"
    return GarminMetricDTO(
        capability_code=METRIC_CODE,
        metric_code=METRIC_CODE,
        field_path="totalSteps",
        state=state,
        value=value if state is GarminFieldState.VALUE else None,
        unit="steps",
        reason=reason,
        capability_status=CapabilityStatus.UNVERIFIED,
        source_device_attributed=False,
    )


class SavedDailyStepsRepository:
    """Materialize a bounded snapshot from immutable saved daily-summary bytes.

    Retain every target-day or unproven original. Only strict saved-byte proof
    can exclude a different returned day; acquisition windows cannot. The SQL
    anti-join remains subject to a cooperative work ceiling as metadata grows.
    The caller owns the transaction, including derived records and date proofs.
    """

    def __init__(self, session: Session, *, payload_store: ContentAddressedGarminPayloadStore):
        self.session = session
        self.payload_store = payload_store
        self.records = GarminSourceRecordRepository(session)
        self._active_budget = None

    def project_saved_summary(
        self, garmin_source_id: str, observation_id: str, *, start_date: date, end_date: date
    ) -> ObservedDailySteps | None:
        """Project only the saved response day inside one normal refresh window."""
        if type(start_date) is not date or type(end_date) is not date:
            raise ValueError("saved Steps refresh requires civil dates")
        if not 1 <= (end_date - start_date).days + 1 <= 14:
            raise ValueError("saved Steps refresh window must contain 1 to 14 days")
        with self._operation():
            return self._project_saved_summary(
                garmin_source_id, observation_id, start_date=start_date, end_date=end_date
            )

    def _project_saved_summary(self, garmin_source_id, observation_id, *, start_date, end_date):
        observation = self.session.get(GarminPayloadObservation, observation_id)
        if (
            observation is None
            or observation.garmin_source_id != garmin_source_id
            or observation.stream_code != "daily_health"
            or observation.payload_format != "json"
            or observation.source_filename != "daily_summary.json"
        ):
            raise SavedStepsEvidenceError("saved daily-summary acquisition mismatch")
        raw = self.session.get(GarminRawPayload, observation.garmin_raw_payload_id)
        artifact = self.session.get(RawArtifact, raw.raw_artifact_id) if raw else None
        if artifact is None or observation.raw_artifact_id != artifact.id:
            raise SavedStepsEvidenceError("saved daily-summary provenance mismatch")
        payload, _reason = self._read_summary(raw, artifact, garmin_source_id, MAX_ARTIFACT_BYTES)
        day = _calendar_date(payload) if payload is not None else None
        if day is None or not start_date <= day <= end_date:
            return None
        return self.project_day(garmin_source_id, day)

    @contextmanager
    def _operation(self):
        if self._active_budget is not None:
            self._active_budget.check()
            yield self._active_budget
            return
        self._begin_snapshot()
        try:
            with _SavedStepsBudget(self.session) as budget:
                self._active_budget = budget
                try:
                    # Keep new proof/Steps rows reversible through the FINAL
                    # shared-budget check; the caller still owns the outer tx.
                    with self.session.begin_nested():
                        yield budget
                        budget.check()
                finally:
                    self._active_budget = None
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlite_errorcode", None) in {5, 6, 9}:
                raise SavedStepsBudgetError("saved daily-summary SQL work bound exceeded") from exc
            raise

    def _begin_snapshot(self) -> None:
        if self.session.new or self.session.dirty or self.session.deleted:
            raise InvalidRequestError("saved Steps projection requires flushed session changes")
        # SQLite's legacy driver needs a physical BEGIN before compound reads.
        # The caller owns this transaction, including rollback of insert savepoints.
        connection = self.session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        self.session.expire_all()

    def _read_summary(
        self, raw: GarminRawPayload | None, artifact: RawArtifact | None,
        source_id: str, max_bytes: int,
    ) -> tuple[dict[str, object] | None, str | None]:
        if (
            raw is None
            or artifact is None
            or raw.garmin_source_id != source_id
            or raw.stream_code != "daily_health"
            or raw.payload_format != "json"
            or artifact.content_hash != raw.content_hash
        ):
            raise SavedStepsEvidenceError("saved daily-summary provenance mismatch")
        if type(artifact.byte_size) is not int or not 0 <= artifact.byte_size <= max_bytes:
            raise SavedStepsEvidenceError("saved daily-summary byte bound exceeded")
        read_limit = max(1, artifact.byte_size)
        self._active_budget.reserve_read(read_limit)
        try:
            content = self.payload_store.read(artifact.relative_storage_path, max_bytes=read_limit)
        except (OSError, ValueError) as exc:
            raise SavedStepsEvidenceError("saved daily-summary artifact unreadable") from exc
        if (
            len(content) != artifact.byte_size
            or hashlib.sha256(content).hexdigest() != raw.content_hash
        ):
            raise SavedStepsEvidenceError("saved daily-summary artifact integrity mismatch")
        self._active_budget.check()
        decoded = _decode(content)
        self._active_budget.check()
        return decoded

    @staticmethod
    def _eligible_observations():
        obs = GarminPayloadObservation
        return (
            obs.stream_code == "daily_health",
            obs.payload_format == "json",
            obs.source_filename == "daily_summary.json",
        )

    def _raw_candidates(self, source_id, *, day=None, missing_only=False):
        obs, raw, proof = GarminPayloadObservation, GarminRawPayload, GarminDailySummaryDateProof
        query = (
            select(obs.garmin_raw_payload_id)
            .outerjoin(raw, raw.id == obs.garmin_raw_payload_id)
            .outerjoin(RawArtifact, RawArtifact.id == raw.raw_artifact_id)
            .outerjoin(proof, proof.raw_payload_id == obs.garmin_raw_payload_id)
            .where(obs.garmin_source_id == source_id, *self._eligible_observations())
        )
        if missing_only:
            query = query.where(proof.raw_payload_id.is_(None))
        elif day is not None:
            # A valid index must not hide an observation's contradictory spine.
            trusted = and_(
                proof.contract_version == DATE_PROOF_VERSION,
                raw.garmin_source_id == source_id,
                raw.stream_code == "daily_health", raw.payload_format == "json",
                obs.raw_artifact_id == raw.raw_artifact_id,
                RawArtifact.id.is_not(None), RawArtifact.content_hash == raw.content_hash,
            )
            query = query.where(or_(
                not_(func.coalesce(trusted, False)), proof.original_calendar_date == day
            ))
        return query.distinct().order_by(obs.garmin_raw_payload_id)

    def _validate_source(self, source_id):
        source = self.session.get(GarminSource, source_id)
        if source is None or source.provider_code != "garmin_connect":
            raise SavedStepsEvidenceError("unknown Garmin source")
        return source

    def _validate_links(self, raw, artifact, observations, source_id):
        if raw is None or artifact is None or not observations or any(
            item.garmin_source_id != source_id
            or item.garmin_raw_payload_id != raw.id
            or item.raw_artifact_id != artifact.id
            for item in observations
        ):
            raise SavedStepsEvidenceError("saved daily-summary provenance mismatch")

    @staticmethod
    def _validate_proof(proof, day):
        if proof is not None and (
            proof.contract_version != DATE_PROOF_VERSION
            or type(proof.original_calendar_date) is not date
            or proof.original_calendar_date != day
        ):
            raise SavedStepsEvidenceError("saved daily-summary date proof mismatch")

    def project_day(
        self,
        garmin_source_id: str,
        calendar_date: date,
        *,
        max_artifacts: int = MAX_ARTIFACTS,
        max_artifact_bytes: int = MAX_ARTIFACT_BYTES,
        max_observations: int = MAX_OBSERVATIONS,
    ) -> ObservedDailySteps:
        if type(calendar_date) is not date:
            raise TypeError("calendar_date must be a date without a time")
        if type(max_artifacts) is not int or not 1 <= max_artifacts <= MAX_ARTIFACTS:
            raise ValueError("max_artifacts must be a positive integer")
        if type(max_artifact_bytes) is not int or not 1 <= max_artifact_bytes <= MAX_ARTIFACT_BYTES:
            raise ValueError("max_artifact_bytes must be a positive integer")
        if type(max_observations) is not int or not 1 <= max_observations <= MAX_OBSERVATIONS:
            raise ValueError("max_observations must be a positive integer")
        with self._operation():
            return self._project_day(
                garmin_source_id, calendar_date, max_artifacts=max_artifacts,
                max_artifact_bytes=max_artifact_bytes, max_observations=max_observations,
            )

    def _project_day(
        self, garmin_source_id, calendar_date, *, max_artifacts, max_artifact_bytes,
        max_observations,
    ):
        budget = self._active_budget
        source = self._validate_source(garmin_source_id)
        raw_ids = budget.rows(
            self.session, self._raw_candidates(garmin_source_id, day=calendar_date), max_artifacts
        )
        if len(raw_ids) > max_artifacts:
            raise SavedStepsEvidenceError("saved daily-summary artifact bound exceeded")
        obs = GarminPayloadObservation
        # Bound ALL associated observations before reading even the first original.
        observations = budget.rows(
            self.session,
            select(obs).where(obs.garmin_raw_payload_id.in_(raw_ids),
                              *self._eligible_observations())
            .order_by(obs.garmin_raw_payload_id, obs.id),
            max_observations,
        )
        if len(observations) > max_observations:
            raise SavedStepsEvidenceError("saved daily-summary observation bound exceeded")
        by_raw = {raw_id: [] for raw_id in raw_ids}
        for item in observations:
            by_raw[item.garmin_raw_payload_id].append(item)
        prepared, excluded, proofs = [], [], []
        for raw_id in raw_ids:
            budget.check()
            observations = tuple(by_raw[raw_id])
            observation_ids = tuple(item.id for item in observations)
            raw = self.session.get(GarminRawPayload, raw_id)
            artifact = self.session.get(RawArtifact, raw.raw_artifact_id) if raw else None
            self._validate_links(raw, artifact, observations, garmin_source_id)
            payload, reason = self._read_summary(
                raw, artifact, garmin_source_id, max_artifact_bytes
            )
            day = _calendar_date(payload) if payload is not None else None
            proof = self.session.get(GarminDailySummaryDateProof, raw_id)
            self._validate_proof(proof, day)
            if day is None:
                excluded.append(ExcludedStepsArtifact(
                    raw_id, observation_ids, reason or "unsupported_calendar_date"
                ))
            else:
                if proof is None:
                    proofs.append(GarminDailySummaryDateProof(
                        raw_payload_id=raw_id, contract_version=DATE_PROOF_VERSION,
                        original_calendar_date=day,
                    ))
                if day == calendar_date:
                    prepared.append((raw, artifact, observations, _metric(payload)))

        # The account identity is retained; device attribution is not promoted
        # from an existing source row into this metric's unverified contract.
        identity = GarminSourceIdentity(
            source_kind=source.source_kind,
            provider_code=source.provider_code,
            source_instance_id=source.source_instance_id,
            device_attributed=False,
        )
        evidence = []
        with self.session.begin_nested():
            self.session.add_all(proofs)
            self.session.flush()
            for raw, artifact, observations, metric in prepared:
                budget.check()
                key = hashlib.sha256(
                    json.dumps(
                        [
                            CONTRACT_VERSION,
                            garmin_source_id,
                            calendar_date.isoformat(),
                            raw.content_hash,
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                row = self.records.get_by_idempotency_key(
                    garmin_source_id=garmin_source_id, idempotency_key=key
                )
                if row is None:
                    first = min(
                        observations,
                        key=lambda item: (restore_stored_utc(item.received_at), item.id),
                    )
                    row, _, _ = self.records.upsert(
                        garmin_source_id=garmin_source_id,
                        raw_payload_id=raw.id,
                        ingest_event_id=first.ingest_event_id,
                        seen_at=restore_stored_utc(first.received_at),
                        normalization_contract_version=CONTRACT_VERSION,
                        reconciliation_contract_version=CONTRACT_VERSION,
                        collection_scope=GarminCollectionScope(
                            METRIC_CODE,
                            "daily_health",
                            "day_singleton",
                            calendar_date,
                            calendar_date,
                            False,
                        ),
                        record=GarminRecordDTO(
                            stream=GarminStream.DAILY_HEALTH,
                            source=identity,
                            temporal=GarminTemporalDTO(
                                precision=GarminTemporalPrecision.DATE_ONLY,
                                local_date=calendar_date,
                                source_field="calendarDate",
                                local_date_source="calendarDate",
                            ),
                            idempotency_key=key,
                            metrics=(metric,),
                            source_path="$",
                        ),
                    )
                evidence.append(
                    SavedStepsEvidence(
                        raw.id,
                        artifact.id,
                        raw.content_hash,
                        tuple(item.id for item in observations),
                        row.id,
                        metric.state,
                        metric.value,
                    )
                )
        values = {item.value for item in evidence if item.state is GarminFieldState.VALUE}
        states = {item.state.value for item in evidence}
        if len(values) > 1:
            state, value, reason = "ambiguous", None, "divergent_saved_observations"
        elif values:
            state, value, reason = "value", next(iter(values)), None
        elif len(states) == 1:
            state, value, reason = next(iter(states)), None, "no_valid_saved_count"
        else:
            state, value, reason = "unavailable", None, "no_valid_saved_count"
        return ObservedDailySteps(
            garmin_source_id,
            calendar_date,
            state,
            value,
            reason,
            tuple(sorted(evidence, key=lambda item: item.content_hash)),
            tuple(excluded),
        )


    def index_saved_summary_dates(
        self, garmin_source_id: str, *, after_raw_id: str | None = None,
        max_artifacts: int = DEFAULT_INDEX_BATCH,
    ) -> SavedSummaryDateIndexBatch:
        """Verify one explicit saved-byte batch; never commit or project Steps.

        Commit before using the proposed cursor. A fatal failure rolls this
        entire caller transaction back; retry from the INPUT cursor, possibly
        with a smaller batch. Unsupported originals stay unproven forever until
        their saved bytes can actually be verified. Advancing a scan cursor does
        not remove them from the ordinary projector's independent unknown query.
        """
        if type(max_artifacts) is not int or not 1 <= max_artifacts <= MAX_ARTIFACTS:
            raise ValueError("saved date index batch must contain 1 to 1000 originals")
        if after_raw_id is not None and (
            not isinstance(after_raw_id, str) or not 1 <= len(after_raw_id) <= 36
        ):
            raise ValueError("saved date index cursor must be a raw identity")
        try:
            with self._operation() as budget:
                return self._index_saved_summary_dates(
                    garmin_source_id, after_raw_id, max_artifacts, budget
                )
        except BaseException:
            # Scope cleanup restores SQLite policy before rollback is attempted.
            self.session.rollback()
            raise

    def _index_saved_summary_dates(self, source_id, after_raw_id, max_artifacts, budget):
        self._validate_source(source_id)
        query = self._raw_candidates(source_id, missing_only=True)
        if after_raw_id is not None:
            query = query.where(GarminPayloadObservation.garmin_raw_payload_id > after_raw_id)
        raw_ids = budget.rows(self.session, query, max_artifacts)
        exhausted = len(raw_ids) <= max_artifacts
        stop = "suffix_exhausted" if exhausted else "artifact_batch_bound"
        cursor, examined, inspected = after_raw_id, 0, 0
        proofs, unproven = [], []
        obs = GarminPayloadObservation
        for raw_id in raw_ids[:max_artifacts]:
            budget.check()
            remaining = MAX_OBSERVATIONS - inspected
            observations = budget.rows(
                self.session,
                select(obs).where(obs.garmin_raw_payload_id == raw_id,
                                  *self._eligible_observations()).order_by(obs.id),
                remaining,
            )
            if len(observations) > remaining:
                # A group gets a fresh full allowance on the next batch. A group
                # too large even then stays unknown, but cannot starve later IDs.
                if inspected == 0:
                    examined += 1
                    inspected = len(observations)
                    cursor = raw_id
                    unproven.append(UnprovenSummaryDate(raw_id, "observation_bound"))
                stop, exhausted = "observation_batch_bound", False
                break
            raw = self.session.get(GarminRawPayload, raw_id)
            artifact = self.session.get(RawArtifact, raw.raw_artifact_id) if raw else None
            if (artifact is not None and type(artifact.byte_size) is int
                    and 0 <= artifact.byte_size <= MAX_ARTIFACT_BYTES):
                allowance = max(1, artifact.byte_size) + 1
                if budget.read_allowance_bytes + allowance > MAX_TOTAL_READ_BYTES:
                    stop, exhausted = "byte_batch_bound", False
                    break
            examined += 1
            inspected += len(observations)
            cursor = raw_id
            try:
                self._validate_links(raw, artifact, observations, source_id)
                payload, reason = self._read_summary(raw, artifact, source_id, MAX_ARTIFACT_BYTES)
            except SavedStepsBudgetError:
                raise
            except SavedStepsEvidenceError:
                unproven.append(UnprovenSummaryDate(raw_id, "original_unverified"))
                continue
            day = _calendar_date(payload) if payload is not None else None
            if day is None:
                unproven.append(UnprovenSummaryDate(
                    raw_id, reason or "unsupported_calendar_date"
                ))
                continue
            proofs.append(GarminDailySummaryDateProof(
                raw_payload_id=raw_id, contract_version=DATE_PROOF_VERSION,
                original_calendar_date=day,
            ))
        budget.check()
        self.session.add_all(proofs)
        self.session.flush()
        budget.check()
        return SavedSummaryDateIndexBatch(
            source_id, after_raw_id, cursor, examined, inspected, budget.read_allowance_bytes,
            len(proofs), tuple(unproven), stop, exhausted,
        )
