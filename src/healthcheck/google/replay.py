"""Bounded offline replay of persisted Google Health observations."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleSource,
    GoogleSourceKind,
    RawArtifact,
)
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
        result = normalize_google_payload(
            content,
            stream=observation.stream_code,
            query=GoogleQueryContext(
                query_mode=observation.query_mode,
                data_source_family=observation.data_source_family,
            ),
            source_identity=identity,
            source_contract_version=observation.source_contract_version
            or raw.source_contract_version,
            normalization_contract_version=normalization_contract_version,
        )
        return self.persistence.persist_result(
            result,
            identity=identity,
            payload=content,
            payload_format=observation.payload_format,
            fixture_id=observation.fixture_id,
            source_filename=observation.source_filename,
            received_at=observation.received_at,
            source_window_start_utc=observation.source_window_start_utc,
            source_window_end_utc=observation.source_window_end_utc,
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
