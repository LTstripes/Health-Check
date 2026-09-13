"""Bounded offline replay of persisted Google Health observations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleSource,
    GoogleSourceKind,
    GoogleSourceRecord,
    RawArtifact,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.google.contracts import (
    GoogleQueryContext,
    GoogleSourceIdentity,
)
from healthcheck.google.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    normalize_google_payload,
)
from healthcheck.google.persistence import GooglePersistenceOutcome, GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.google.sync import query_level_source_identity, source_identity_from_point

MAX_REPLAY_OBSERVATIONS = 256


class GoogleNormalizationReplayer:
    """Replay only explicitly selected immutable observations, offline."""

    def __init__(
        self,
        session: Session,
        *,
        payload_store: ContentAddressedGooglePayloadStore,
        persistence: GooglePersistenceRepository | None = None,
    ):
        self.session = session
        self.payload_store = payload_store
        self.persistence = persistence or GooglePersistenceRepository(
            session, payload_store=payload_store
        )

    def replay(
        self,
        *,
        observation_ids: Sequence[str],
        normalization_contract_version: str = NORMALIZATION_CONTRACT_VERSION,
        max_observations: int = MAX_REPLAY_OBSERVATIONS,
    ) -> tuple[GooglePersistenceOutcome, ...]:
        selected = _bounded_observation_ids(observation_ids, max_observations)
        outcomes: list[GooglePersistenceOutcome] = []
        for observation_id in selected:
            observation = self.session.get(GooglePayloadObservation, observation_id)
            if observation is None:
                raise KeyError(f"unknown Google observation {observation_id}")
            outcomes.append(
                self._replay_one(
                    observation,
                    normalization_contract_version=normalization_contract_version,
                )
            )
        return tuple(outcomes)

    def _replay_one(
        self,
        observation: GooglePayloadObservation,
        *,
        normalization_contract_version: str,
    ) -> GooglePersistenceOutcome:
        raw = self.session.get(GoogleRawPayload, observation.google_raw_payload_id)
        if raw is None:
            raise RuntimeError("Google observation references a missing raw payload")
        artifact = self.session.get(RawArtifact, raw.raw_artifact_id)
        if artifact is None:
            raise RuntimeError("Google raw payload references a missing raw artifact")
        content = self.payload_store.read(artifact.relative_storage_path)
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash != raw.content_hash or content_hash != artifact.content_hash:
            raise ValueError("Google replay raw artifact hash does not match persisted evidence")
        source = self.session.get(GoogleSource, observation.google_source_id)
        if source is None:
            raise RuntimeError("Google observation references a missing source")
        identity = _source_identity(source)
        query = GoogleQueryContext(
            query_mode=observation.query_mode,
            data_source_family=observation.data_source_family,
        )
        partition = _partition_replay_payload(
            content,
            query=query,
            identity=identity,
            persisted_records=_persisted_source_records(self.session, observation, query),
        )
        result = normalize_google_payload(
            content,
            stream=observation.stream_code,
            query=query,
            source_identity=identity,
            source_contract_version=observation.source_contract_version
            or raw.source_contract_version,
            normalization_contract_version=normalization_contract_version,
        )
        records = (
            result.records
            if partition.all_points_selected
            else tuple(
                record
                for record in result.records
                if record.external_record_id in partition.selected_record_names
            )
        )
        result = replace(result, records=records, source_identity=identity)
        return self.persistence.persist_result(
            result,
            identity=identity,
            payload=content,
            payload_format=observation.payload_format,
            fixture_id=observation.fixture_id,
            source_filename=observation.source_filename,
            received_at=restore_stored_utc(observation.received_at),
            source_window_start_utc=restore_stored_utc(observation.source_window_start_utc),
            source_window_end_utc=restore_stored_utc(observation.source_window_end_utc),
            sync_run_id=observation.sync_run_id,
            ingest_event_id=observation.ingest_event_id,
            create_ingest_event=False,
        )


def replay_google_observations(
    session: Session,
    *,
    payload_store: ContentAddressedGooglePayloadStore,
    observation_ids: Sequence[str],
    normalization_contract_version: str = NORMALIZATION_CONTRACT_VERSION,
    max_observations: int = MAX_REPLAY_OBSERVATIONS,
    persistence: GooglePersistenceRepository | None = None,
) -> tuple[GooglePersistenceOutcome, ...]:
    """Replay an explicit bounded observation selection without provider calls."""

    return GoogleNormalizationReplayer(
        session, payload_store=payload_store, persistence=persistence
    ).replay(
        observation_ids=observation_ids,
        normalization_contract_version=normalization_contract_version,
        max_observations=max_observations,
    )


replay_google_normalization = replay_google_observations


def _persisted_source_records(
    session: Session,
    observation: GooglePayloadObservation,
    query: GoogleQueryContext,
) -> Mapping[str, tuple[GoogleSourceRecord, ...]]:
    """Index current persisted records that can disambiguate replay points."""

    conditions = [
        GoogleSourceRecord.google_source_id == observation.google_source_id,
        GoogleSourceRecord.stream_code == observation.stream_code,
        GoogleSourceRecord.query_mode == query.query_mode.value,
    ]
    if query.data_source_family is None:
        conditions.append(GoogleSourceRecord.data_source_family.is_(None))
    else:
        conditions.append(GoogleSourceRecord.data_source_family == query.data_source_family)
    by_external_id: dict[str, list[GoogleSourceRecord]] = defaultdict(list)
    for record in session.scalars(select(GoogleSourceRecord).where(*conditions)):
        if record.external_record_id:
            by_external_id[record.external_record_id].append(record)
    return {key: tuple(value) for key, value in by_external_id.items()}


@dataclass(frozen=True, slots=True)
class _ReplayPartition:
    selected_record_names: frozenset[str]
    all_points_selected: bool = False


def _partition_replay_payload(
    content: bytes,
    *,
    query: GoogleQueryContext,
    identity: GoogleSourceIdentity,
    persisted_records: Mapping[str, tuple[GoogleSourceRecord, ...]],
) -> _ReplayPartition:
    """Reconstruct the selected source's record membership from page evidence."""

    try:
        decoded = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Google replay cannot establish source membership") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("Google replay cannot establish source membership")

    envelope = (
        "rollupDataPoints" if query.query_mode.value in {"rollUp", "dailyRollUp"} else "dataPoints"
    )
    points = decoded.get(envelope)
    if not isinstance(points, list):
        raise ValueError("Google replay cannot establish source membership")

    fallback = query_level_source_identity(query)
    selected_names: set[str] = set()
    point_names: set[str] = set()
    selected_point_count = 0
    unresolved = False
    explicit_source_seen = False
    for point in points:
        if not isinstance(point, Mapping):
            unresolved = True
            continue
        point_identity, explicit = _point_source_identity(point, query, fallback)
        explicit_source_seen = explicit_source_seen or explicit
        point_name = _point_record_name(point)
        if point_name is not None:
            if point_name in point_names:
                unresolved = True
            point_names.add(point_name)
        if explicit:
            if identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE:
                unresolved = True
            elif _source_partition_key(point_identity) == _source_partition_key(identity):
                if point_name is None:
                    unresolved = True
                else:
                    selected_names.add(point_name)
                    selected_point_count += 1
            continue

        matches = persisted_records.get(point_name, ()) if point_name is not None else ()
        if _source_partition_key(point_identity) != _source_partition_key(fallback):
            if _source_partition_key(point_identity) == _source_partition_key(identity):
                if point_name is None:
                    unresolved = True
                else:
                    selected_names.add(point_name)
                    selected_point_count += 1
            elif len(matches) == 1:
                # Older observations can have a fingerprint-only dataSource
                # while their stable source identity was supplied externally.
                if point_name is None:
                    unresolved = True
                else:
                    selected_names.add(point_name)
                    selected_point_count += 1
            continue

        if identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE:
            if _source_partition_key(fallback) == _source_partition_key(identity):
                selected_point_count += 1
                if point_name is not None:
                    selected_names.add(point_name)
            else:
                unresolved = True
            continue

        if len(matches) == 1:
            if point_name is None:
                unresolved = True
            else:
                selected_names.add(point_name)
                selected_point_count += 1
        else:
            unresolved = True

    if identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE and explicit_source_seen:
        unresolved = True
    if unresolved:
        raise ValueError("Google replay cannot establish source membership safely")

    return _ReplayPartition(
        selected_record_names=frozenset(selected_names),
        all_points_selected=(
            identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE
            and selected_point_count == len(points)
        ),
    )


def _point_source_identity(
    point: Mapping[str, object],
    query: GoogleQueryContext,
    fallback: GoogleSourceIdentity,
) -> tuple[GoogleSourceIdentity, bool]:
    data_source = point.get("dataSource")
    point_identity = source_identity_from_point(point, query)
    if not isinstance(data_source, Mapping):
        return fallback, False
    name = data_source.get("name")
    if isinstance(name, str) and name.strip():
        return point_identity, True
    return point_identity, False


def _point_record_name(point: Mapping[str, object]) -> str | None:
    values = [
        value.strip()
        for key in ("name", "dataPointName")
        if isinstance(value := point.get(key), str) and value.strip()
    ]
    if len(values) == 2 and values[0] != values[1]:
        return None
    return values[0] if values else None


def _source_partition_key(identity: GoogleSourceIdentity) -> tuple[GoogleSourceKind, str]:
    return identity.source_kind, identity.source_instance_id


def _bounded_observation_ids(
    observation_ids: Sequence[str], max_observations: int
) -> tuple[str, ...]:
    if isinstance(observation_ids, (str, bytes, bytearray)) or not isinstance(
        observation_ids, Sequence
    ):
        raise TypeError("Google replay requires an explicit sequence of observation ids")
    if (
        not isinstance(max_observations, int)
        or isinstance(max_observations, bool)
        or max_observations <= 0
    ):
        raise ValueError("max_observations must be a positive integer")
    selected = tuple(str(item).strip() for item in observation_ids)
    if not selected:
        raise ValueError("Google replay requires at least one selected observation")
    if len(selected) > max_observations:
        raise ValueError("Google replay selection exceeds its explicit bound")
    if any(not item for item in selected):
        raise ValueError("Google replay observation ids must be nonempty")
    if len(set(selected)) != len(selected):
        raise ValueError("Google replay selection contains duplicate observation ids")
    return selected


def _source_identity(source: GoogleSource) -> GoogleSourceIdentity:
    return GoogleSourceIdentity(
        source_kind=GoogleSourceKind(source.source_kind),
        source_instance_id=source.source_instance_id,
        provider_code=source.provider_code,
        data_source_name=source.data_source_name,
        data_source_id=source.data_source_id,
        platform=source.platform,
        recording_method=source.recording_method,
        device_attributed=source.device_attributed,
        device_code=source.device_code,
        device_manufacturer=source.device_manufacturer,
        device_model=source.device_model,
        device_uid=source.device_uid,
        source_contract_version=source.source_contract_version,
    )


__all__ = [
    "MAX_REPLAY_OBSERVATIONS",
    "GoogleNormalizationReplayer",
    "replay_google_normalization",
    "replay_google_observations",
]
