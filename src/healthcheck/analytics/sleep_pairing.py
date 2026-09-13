"""Read-only R05 pairing and source-eligibility over persisted sleep rows.

This module deliberately has no persistence, provider, or schema behavior.  It
starts with current logical projections and source eligibility, then applies
the wake-date/main-session pairing rules from ``r05-sleep-agreement-v1``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GoogleMetricState,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceKind,
    GoogleSourceRecord,
)
from healthcheck.garmin.capabilities import VIVOACTIVE_5_DEVICE_CODE, VIVOACTIVE_5_MODEL
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GoogleStream,
)

R05_SLEEP_PAIRING_CONTRACT_VERSION = "r05-01-sleep-pairing-v1"
DEVICE_PAIR = "device_pair"
FAMILY_PAIR = "family_pair"
ALL_COHORTS = "all"
_UNATTRIBUTED_SOURCE_INSTANCE = "unattributed"
_CURRENT = "current"
_VALUE = GoogleMetricState.VALUE.value
_EXPLICIT_MAIN = "explicit_main"
_FALLBACK_MAIN = "fallback_main"


@dataclass(frozen=True, slots=True)
class SleepPairingQuery:
    """Bounded persisted read selection; no query performs a provider call."""

    start_date: date | None = None
    end_date: date | None = None
    cohort: str = ALL_COHORTS
    garmin_source_id: str | None = None
    google_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("sleep pairing end_date cannot precede start_date")
        if self.cohort not in {ALL_COHORTS, DEVICE_PAIR, FAMILY_PAIR}:
            raise ValueError("sleep pairing cohort must be all, device_pair, or family_pair")
        if any(not isinstance(item, str) or not item.strip() for item in self.google_source_ids):
            raise ValueError("google_source_ids must contain non-empty identifiers")

    def as_dict(self) -> dict[str, object]:
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "cohort": self.cohort,
            "garmin_source_id": self.garmin_source_id,
            "google_source_ids": list(self.google_source_ids),
            "contract_version": R05_SLEEP_PAIRING_CONTRACT_VERSION,
        }


@dataclass(frozen=True, slots=True)
class SleepSourceEligibility:
    """One persisted record's source/cohort decision and exact evidence basis."""

    record_id: str
    source_id: str
    source_class: str
    cohort: str | None
    eligible: bool
    reason: str | None
    basis: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "source_class": self.source_class,
            "cohort": self.cohort,
            "eligible": self.eligible,
            "reason": self.reason,
            "basis": dict(self.basis),
        }


@dataclass(frozen=True, slots=True)
class SleepPairingExclusion:
    """A deterministic exclusion retained for audit/reporting."""

    wake_date: date | None
    cohort: str | None
    reason: str
    garmin_record_ids: tuple[str, ...] = ()
    google_record_ids: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "wake_date": self.wake_date.isoformat() if self.wake_date else None,
            "cohort": self.cohort,
            "reason": self.reason,
            "garmin_record_ids": list(self.garmin_record_ids),
            "google_record_ids": list(self.google_record_ids),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class SleepPair:
    """One accepted Garmin ↔ Google night pair."""

    wake_date: date
    cohort: str
    source_class: str
    garmin_record_id: str
    google_record_id: str
    garmin_source_id: str
    google_source_id: str
    google_manually_edited: bool | None
    google_main_state: str
    google_nap_state: str
    garmin_source_eligibility: SleepSourceEligibility
    google_source_eligibility: SleepSourceEligibility

    def as_dict(self) -> dict[str, object]:
        return {
            "wake_date": self.wake_date.isoformat(),
            "cohort": self.cohort,
            "source_class": self.source_class,
            "garmin_record_id": self.garmin_record_id,
            "google_record_id": self.google_record_id,
            "garmin_source_id": self.garmin_source_id,
            "google_source_id": self.google_source_id,
            "google_manually_edited": self.google_manually_edited,
            "google_main_state": self.google_main_state,
            "google_nap_state": self.google_nap_state,
            "garmin_source_eligibility": self.garmin_source_eligibility.as_dict(),
            "google_source_eligibility": self.google_source_eligibility.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SleepPairingResult:
    """Deterministic R05 read result; no rows are written by its reader."""

    query: SleepPairingQuery
    pairs: tuple[SleepPair, ...]
    exclusions: tuple[SleepPairingExclusion, ...]
    source_eligibility: tuple[SleepSourceEligibility, ...]

    @property
    def device_pairs(self) -> tuple[SleepPair, ...]:
        return tuple(item for item in self.pairs if item.cohort == DEVICE_PAIR)

    @property
    def family_pairs(self) -> tuple[SleepPair, ...]:
        return tuple(item for item in self.pairs if item.cohort == FAMILY_PAIR)

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": R05_SLEEP_PAIRING_CONTRACT_VERSION,
            "query": self.query.as_dict(),
            "pairs": [item.as_dict() for item in self.pairs],
            "exclusions": [item.as_dict() for item in self.exclusions],
            "source_eligibility": [item.as_dict() for item in self.source_eligibility],
        }


@dataclass(frozen=True, slots=True)
class _GarminCandidate:
    record: GarminSourceRecord
    typed: GarminSleepRecord
    source: GarminSource
    eligibility: SleepSourceEligibility


@dataclass(frozen=True, slots=True)
class _GoogleCandidate:
    record: GoogleSourceRecord
    typed: GoogleSleepRecord
    source: GoogleSource
    eligibility: SleepSourceEligibility
    main_state: str
    nap_state: str
    main_value: bool | None
    nap_value: bool | None
    main_selection: str
    manually_edited: bool | None


class PersistedSleepPairingReader:
    """Read current persisted sleep projections and pair them by stored date."""

    def __init__(self, session: Session):
        self.session = session

    def read(self, query: SleepPairingQuery | None = None) -> SleepPairingResult:
        selection = query or SleepPairingQuery()
        garmin = self._garmin_candidates(selection)
        google, eligibility, exclusions = self._google_candidates(selection)
        eligibility.extend(item.eligibility for item in garmin)

        eligible_garmin: list[_GarminCandidate] = []
        for candidate in garmin:
            reason = candidate.eligibility.reason
            if reason is not None:
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=candidate.typed.wake_date,
                        cohort=None,
                        reason=reason,
                        garmin_record_ids=(candidate.record.id,),
                    )
                )
                continue
            if candidate.record.record_status == "invalid":
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=candidate.typed.wake_date,
                        cohort=None,
                        reason="garmin_record_invalid",
                        garmin_record_ids=(candidate.record.id,),
                    )
                )
                continue
            if candidate.typed.wake_date is None:
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=None,
                        cohort=None,
                        reason="wake_date_missing",
                        garmin_record_ids=(candidate.record.id,),
                    )
                )
                continue
            eligible_garmin.append(candidate)

        pairs: list[SleepPair] = []
        for cohort in (DEVICE_PAIR, FAMILY_PAIR):
            if selection.cohort not in {ALL_COHORTS, cohort}:
                continue
            cohort_google = [item for item in google if item.eligibility.cohort == cohort]
            self._pair_cohort(
                cohort,
                eligible_garmin,
                cohort_google,
                pairs,
                exclusions,
            )

        pairs.sort(key=lambda item: (item.wake_date, item.cohort, item.google_record_id))
        exclusions.sort(
            key=lambda item: (
                item.wake_date or date.max,
                item.cohort or "",
                item.reason,
                item.google_record_ids,
                item.garmin_record_ids,
            )
        )
        eligibility.sort(key=lambda item: (item.source_id, item.record_id))
        return SleepPairingResult(
            query=selection,
            pairs=tuple(pairs),
            exclusions=tuple(exclusions),
            source_eligibility=tuple(eligibility),
        )

    def _garmin_candidates(self, query: SleepPairingQuery) -> list[_GarminCandidate]:
        conditions = [
            GarminSourceRecord.stream_code == "sleep",
            GarminSourceRecord.projection_status == _CURRENT,
        ]
        if query.garmin_source_id is not None:
            conditions.append(GarminSourceRecord.garmin_source_id == query.garmin_source_id)
        if query.start_date is not None:
            conditions.append(GarminSleepRecord.wake_date >= query.start_date)
        if query.end_date is not None:
            conditions.append(GarminSleepRecord.wake_date <= query.end_date)
        rows = self.session.execute(
            select(GarminSourceRecord, GarminSleepRecord, GarminSource)
            .join(GarminSleepRecord, GarminSleepRecord.record_id == GarminSourceRecord.id)
            .join(GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id)
            .where(*conditions)
        )
        return [
            _GarminCandidate(
                record=row[0],
                typed=row[1],
                source=row[2],
                eligibility=_garmin_source_eligibility(row[0], row[2]),
            )
            for row in rows
        ]

    def _google_candidates(
        self, query: SleepPairingQuery
    ) -> tuple[list[_GoogleCandidate], list[SleepSourceEligibility], list[SleepPairingExclusion]]:
        conditions = [
            GoogleSourceRecord.stream_code == GoogleStream.SLEEP.value,
            GoogleSourceRecord.projection_status == _CURRENT,
        ]
        if query.google_source_ids:
            conditions.append(GoogleSourceRecord.google_source_id.in_(query.google_source_ids))
        if query.start_date is not None:
            conditions.append(GoogleSleepRecord.wake_date >= query.start_date)
        if query.end_date is not None:
            conditions.append(GoogleSleepRecord.wake_date <= query.end_date)
        rows = list(
            self.session.execute(
                select(GoogleSourceRecord, GoogleSleepRecord, GoogleSource)
                .join(GoogleSleepRecord, GoogleSleepRecord.record_id == GoogleSourceRecord.id)
                .join(GoogleSource, GoogleSource.id == GoogleSourceRecord.google_source_id)
                .where(*conditions)
            )
        )
        record_ids = [row[0].id for row in rows]
        metrics = self._metrics_by_record(record_ids)
        evidence = self._evidence_by_record(record_ids)
        candidates: list[_GoogleCandidate] = []
        eligibility: list[SleepSourceEligibility] = []
        exclusions: list[SleepPairingExclusion] = []
        for record, typed, source in rows:
            source_decision = _google_source_eligibility(
                record,
                source,
                evidence.get(record.id),
            )
            eligibility.append(source_decision)
            if not source_decision.eligible:
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=typed.wake_date,
                        cohort=None,
                        reason=source_decision.reason or "google_source_ineligible",
                        google_record_ids=(record.id,),
                        details={"source_eligibility": source_decision.as_dict()},
                    )
                )
                continue
            if record.record_status == "invalid":
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=typed.wake_date,
                        cohort=source_decision.cohort,
                        reason="google_record_invalid",
                        google_record_ids=(record.id,),
                    )
                )
                continue
            if typed.wake_date is None:
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=None,
                        cohort=source_decision.cohort,
                        reason="wake_date_missing",
                        google_record_ids=(record.id,),
                    )
                )
                continue
            role = _google_main_role(metrics.get(record.id, ()))
            if role[0] is None:
                exclusions.append(
                    SleepPairingExclusion(
                        wake_date=typed.wake_date,
                        cohort=source_decision.cohort,
                        reason=role[1],
                        google_record_ids=(record.id,),
                        details={"main_state": role[2], "nap_state": role[3]},
                    )
                )
                continue
            candidates.append(
                _GoogleCandidate(
                    record=record,
                    typed=typed,
                    source=source,
                    eligibility=source_decision,
                    main_state=role[2],
                    nap_state=role[3],
                    main_value=role[4],
                    nap_value=role[5],
                    main_selection=role[6],
                    manually_edited=_metric_bool(
                        metrics.get(record.id, ()), "sleep_metadata_manually_edited"
                    ),
                )
            )
        return candidates, eligibility, exclusions

    def _metrics_by_record(
        self, record_ids: Sequence[str]
    ) -> dict[str, tuple[GoogleRecordMetric, ...]]:
        if not record_ids:
            return {}
        grouped: dict[str, list[GoogleRecordMetric]] = defaultdict(list)
        for metric in self.session.scalars(
            select(GoogleRecordMetric)
            .where(GoogleRecordMetric.record_id.in_(record_ids))
            .order_by(GoogleRecordMetric.record_id, GoogleRecordMetric.metric_code)
        ):
            grouped[metric.record_id].append(metric)
        return {key: tuple(value) for key, value in grouped.items()}

    def _evidence_by_record(
        self, record_ids: Sequence[str]
    ) -> dict[str, GoogleRecordSourceEvidence]:
        if not record_ids:
            return {}
        return {
            row.record_id: row
            for row in self.session.scalars(
                select(GoogleRecordSourceEvidence).where(
                    GoogleRecordSourceEvidence.record_id.in_(record_ids)
                )
            )
        }

    @staticmethod
    def _pair_cohort(
        cohort: str,
        garmin: Sequence[_GarminCandidate],
        google: Sequence[_GoogleCandidate],
        pairs: list[SleepPair],
        exclusions: list[SleepPairingExclusion],
    ) -> None:
        garmin_by_date: dict[date, list[_GarminCandidate]] = defaultdict(list)
        google_by_date: dict[date, list[_GoogleCandidate]] = defaultdict(list)
        for item in garmin:
            if item.typed.wake_date is not None:
                garmin_by_date[item.typed.wake_date].append(item)
        for item in google:
            if item.typed.wake_date is not None:
                google_by_date[item.typed.wake_date].append(item)
        for wake_date in sorted(set(garmin_by_date) | set(google_by_date)):
            garmin_rows = garmin_by_date.get(wake_date, [])
            google_rows = google_by_date.get(wake_date, [])
            explicit_main_rows = [
                item for item in google_rows if item.main_selection == _EXPLICIT_MAIN
            ]
            if explicit_main_rows:
                google_rows = explicit_main_rows
            if len(garmin_rows) != 1:
                if len(garmin_rows) > 1:
                    exclusions.append(
                        SleepPairingExclusion(
                            wake_date=wake_date,
                            cohort=cohort,
                            reason="ambiguous_garmin_main",
                            garmin_record_ids=tuple(item.record.id for item in garmin_rows),
                            google_record_ids=tuple(item.record.id for item in google_rows),
                        )
                    )
                elif google_rows:
                    exclusions.append(
                        SleepPairingExclusion(
                            wake_date=wake_date,
                            cohort=cohort,
                            reason="missing_garmin_main",
                            google_record_ids=tuple(item.record.id for item in google_rows),
                        )
                    )
                continue
            if len(google_rows) != 1:
                if len(google_rows) > 1:
                    reason = (
                        "ambiguous_fitbit_source"
                        if cohort == DEVICE_PAIR
                        and len({item.source.id for item in google_rows}) > 1
                        else "ambiguous_google_main"
                    )
                    exclusions.append(
                        SleepPairingExclusion(
                            wake_date=wake_date,
                            cohort=cohort,
                            reason=reason,
                            garmin_record_ids=(garmin_rows[0].record.id,),
                            google_record_ids=tuple(item.record.id for item in google_rows),
                        )
                    )
                else:
                    exclusions.append(
                        SleepPairingExclusion(
                            wake_date=wake_date,
                            cohort=cohort,
                            reason="missing_google_main",
                            garmin_record_ids=(garmin_rows[0].record.id,),
                        )
                    )
                continue
            google_row = google_rows[0]
            pairs.append(
                SleepPair(
                    wake_date=wake_date,
                    cohort=cohort,
                    source_class=google_row.eligibility.source_class,
                    garmin_record_id=garmin_rows[0].record.id,
                    google_record_id=google_row.record.id,
                    garmin_source_id=garmin_rows[0].source.id,
                    google_source_id=google_row.source.id,
                    google_manually_edited=google_row.manually_edited,
                    google_main_state=google_row.main_state,
                    google_nap_state=google_row.nap_state,
                    garmin_source_eligibility=garmin_rows[0].eligibility,
                    google_source_eligibility=google_row.eligibility,
                )
            )


def read_persisted_sleep_pairing(
    session: Session, query: SleepPairingQuery | None = None
) -> SleepPairingResult:
    """Return R05 pairs/exclusions from persisted current projections only."""

    return PersistedSleepPairingReader(session).read(query)


def _garmin_source_eligibility(
    record: GarminSourceRecord, source: GarminSource
) -> SleepSourceEligibility:
    basis = {
        "provider_code": source.provider_code,
        "source_kind": source.source_kind,
        "source_instance_id": source.source_instance_id,
        "device_attributed": source.device_attributed,
        "device_code": source.device_code,
        "device_model": source.device_model,
        "record_projection_status": record.projection_status,
    }
    if (
        source.provider_code != "garmin_connect"
        or not source.device_attributed
        or source.device_code != VIVOACTIVE_5_DEVICE_CODE
        or source.device_model != VIVOACTIVE_5_MODEL
    ):
        return SleepSourceEligibility(
            record.id,
            source.id,
            "garmin_source",
            None,
            False,
            "garmin_not_target_device",
            basis,
        )
    return SleepSourceEligibility(
        record.id,
        source.id,
        "garmin_vivoactive_5",
        DEVICE_PAIR,
        True,
        None,
        basis,
    )


def _google_source_eligibility(
    record: GoogleSourceRecord,
    source: GoogleSource,
    evidence: GoogleRecordSourceEvidence | None,
) -> SleepSourceEligibility:
    basis: dict[str, object] = {
        "google_source_kind": source.source_kind,
        "google_source_instance_id": source.source_instance_id,
        "google_data_source_name": source.data_source_name,
        "google_data_source_id": source.data_source_id,
        "google_source_platform": source.platform,
        "data_source_family": record.data_source_family,
        "record_source_evidence": None,
    }
    if source.source_kind == GoogleSourceKind.FAMILY_AGGREGATE.value:
        if source.source_instance_id == FAMILY_GOOGLE_WEARABLES:
            return SleepSourceEligibility(
                record.id,
                source.id,
                "google_wearables_family",
                FAMILY_PAIR,
                True,
                None,
                basis,
            )
        return SleepSourceEligibility(
            record.id,
            source.id,
            "excluded_family",
            None,
            False,
            _family_exclusion_reason(source.source_instance_id),
            basis,
        )
    if source.source_kind != GoogleSourceKind.DATA_SOURCE.value:
        return SleepSourceEligibility(
            record.id, source.id, "unknown_source", None, False, "google_source_kind_invalid", basis
        )
    if record.data_source_family in {FAMILY_ALL_SOURCES, FAMILY_GOOGLE_SOURCES}:
        return SleepSourceEligibility(
            record.id,
            source.id,
            "excluded_family",
            None,
            False,
            "google_family_excluded",
            basis,
        )
    if record.data_source_family == FAMILY_GOOGLE_WEARABLES:
        family_evidence = _decode_source_evidence(evidence) if evidence is not None else None
        if family_evidence is None or family_evidence.get("state") in {
            GoogleMetricState.MISSING.value,
            GoogleMetricState.NULL.value,
        }:
            basis["record_source_evidence"] = family_evidence
            return SleepSourceEligibility(
                record.id,
                source.id,
                "google_wearables_family",
                FAMILY_PAIR,
                True,
                None,
                basis,
            )
    if source.source_instance_id == _UNATTRIBUTED_SOURCE_INSTANCE:
        return SleepSourceEligibility(
            record.id, source.id, "unattributed", None, False, "google_source_unattributed", basis
        )
    target_source_state = _explicit_fitbit_target_source(source)
    basis["explicit_target_source"] = target_source_state
    if target_source_state == "missing":
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_target_source_missing",
            basis,
        )
    if target_source_state == "ambiguous":
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_target_source_ambiguous",
            basis,
        )
    if evidence is None:
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_record_source_evidence_missing",
            basis,
        )
    decoded = _decode_source_evidence(evidence)
    basis["record_source_evidence"] = decoded
    if decoded is None:
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_record_source_evidence_invalid",
            basis,
        )
    if decoded.get("state") != _VALUE:
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_record_source_evidence_unavailable",
            basis,
        )
    fields = decoded.get("fields")
    values = _source_field_values(fields)
    platform = values.get("data_source_platform")
    manufacturer = values.get("data_source_device_manufacturer")
    display_name = values.get("data_source_device_display_name")
    if platform is None or platform.casefold() != "fitbit":
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_source_not_fitbit",
            basis,
        )
    if manufacturer is not None and "fitbit" not in manufacturer.casefold():
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_source_device_conflict",
            basis,
        )
    if manufacturer is None and display_name is None:
        return SleepSourceEligibility(
            record.id,
            source.id,
            "google_data_source",
            None,
            False,
            "google_source_device_metadata_missing",
            basis,
        )
    return SleepSourceEligibility(
        record.id,
        source.id,
        "fitbit_device",
        DEVICE_PAIR,
        True,
        None,
        basis,
    )


def _explicit_fitbit_target_source(source: GoogleSource) -> str:
    """Classify persisted source identity without promoting record evidence."""

    if not source.source_instance_id or source.source_instance_id.startswith("unattributed:"):
        return "missing"
    labels = tuple(
        value.casefold()
        for value in (
            source.source_instance_id,
            source.data_source_name,
            source.data_source_id,
        )
        if isinstance(value, str) and value.strip()
    )
    target_labels = tuple("fitbit" in value for value in labels)
    if not any(target_labels):
        return "missing"
    if any(not is_target for is_target in target_labels):
        return "ambiguous"
    return "explicit"


def _family_exclusion_reason(source_instance_id: str) -> str:
    if source_instance_id == FAMILY_ALL_SOURCES:
        return "google_all_sources_excluded"
    if source_instance_id == FAMILY_GOOGLE_SOURCES:
        return "google_sources_excluded"
    return "google_family_not_target_wearables"


def _decode_source_evidence(row: GoogleRecordSourceEvidence) -> dict[str, object] | None:
    try:
        value = json.loads(row.evidence_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _source_field_values(raw_fields: object) -> dict[str, str]:
    if not isinstance(raw_fields, list):
        return {}
    values: dict[str, str] = {}
    for item in raw_fields:
        if not isinstance(item, Mapping) or item.get("state") != _VALUE:
            continue
        code = item.get("metric_code")
        text = item.get("value_text")
        if isinstance(code, str) and isinstance(text, str) and text.strip():
            values[code] = text.strip()
    return values


def _metric_bool(metrics: Sequence[GoogleRecordMetric], code: str) -> bool | None:
    metric = next((item for item in metrics if item.metric_code == code), None)
    if metric is None or metric.state != _VALUE:
        return None
    if metric.value_text == "true":
        return True
    if metric.value_text == "false":
        return False
    return None


def _metric_state(metrics: Sequence[GoogleRecordMetric], code: str) -> str:
    metric = next((item for item in metrics if item.metric_code == code), None)
    return metric.state if metric is not None else GoogleMetricState.MISSING.value


def _google_main_role(
    metrics: Sequence[GoogleRecordMetric],
) -> tuple[bool | None, str, str, str, bool | None, bool | None, str]:
    main_state = _metric_state(metrics, "sleep_metadata_main")
    nap_state = _metric_state(metrics, "sleep_metadata_nap")
    main_value = _metric_bool(metrics, "sleep_metadata_main")
    nap_value = _metric_bool(metrics, "sleep_metadata_nap")
    if nap_state == _VALUE and nap_value is True:
        return None, "google_nap_only", main_state, nap_state, main_value, nap_value
    if nap_state != _VALUE:
        return None, "google_nap_state_unknown", main_state, nap_state, main_value, nap_value
    if main_state == _VALUE and main_value is True and nap_value is False:
        return True, "", main_state, nap_state, main_value, nap_value, _EXPLICIT_MAIN
    if main_state in {GoogleMetricState.MISSING.value, GoogleMetricState.NULL.value}:
        return True, "", main_state, nap_state, main_value, nap_value, _FALLBACK_MAIN
    if main_state == _VALUE and main_value is False:
        return None, "google_non_main", main_state, nap_state, main_value, nap_value, ""
    return None, "google_main_state_invalid", main_state, nap_state, main_value, nap_value, ""


__all__ = [
    "ALL_COHORTS",
    "DEVICE_PAIR",
    "FAMILY_PAIR",
    "PersistedSleepPairingReader",
    "R05_SLEEP_PAIRING_CONTRACT_VERSION",
    "SleepPair",
    "SleepPairingExclusion",
    "SleepPairingQuery",
    "SleepPairingResult",
    "SleepSourceEligibility",
    "read_persisted_sleep_pairing",
]
