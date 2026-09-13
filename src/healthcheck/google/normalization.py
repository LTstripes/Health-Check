"""Pure, bounded normalization of the accepted Google Health API v4 types.

The entrypoint accepts an already acquired JSON response and returns explicit
Google DTOs.  It has no OAuth, provider client, network, synchronization, or
analytics behavior.  Parsing is intentionally conservative: a materially
incompatible response is ``INVALID`` and never becomes a successful current
projection.  Diagnostics and unknown-field evidence contain only fixed
reason codes, paths, and shapes; the immutable raw response remains the
authoritative evidence for later replay.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from healthcheck.db.models import GoogleMetricState, GooglePayloadStatus, GoogleSourceKind
from healthcheck.db.repositories import canonical_json
from healthcheck.google.contracts import (
    SOURCE_CONTRACT_VERSION,
    GoogleDataSourceDTO,
    GoogleIntervalDTO,
    GoogleIntervalKind,
    GoogleMetricDTO,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleRecordDTO,
    GoogleSleepStageDTO,
    GoogleSourceIdentity,
    GoogleStream,
    GoogleTemporalDTO,
    GoogleTemporalPrecision,
)

NORMALIZATION_CONTRACT_VERSION = "r04-google-normalization-contract-v1"
GOOGLE_NORMALIZATION_CONTRACT_VERSION = NORMALIZATION_CONTRACT_VERSION
MAX_NORMALIZATION_RECORDS = 4096
MAX_DIAGNOSTICS = 128
MAX_UNKNOWN_FIELDS = 128
MAX_NESTED_FIELDS = 64

_MISSING = object()
_SAFE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
_INT_TEXT = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
_DURATION_TEXT = re.compile(r"^([+-]?)([0-9]+)(?:\.([0-9]{1,9}))?s$")

_DATA_FIELD_BY_STREAM = {
    GoogleStream.HEART_RATE: "heartRate",
    GoogleStream.SLEEP: "sleep",
    GoogleStream.DAILY_RESTING_HR: "dailyRestingHeartRate",
    GoogleStream.DAILY_HRV: "dailyHeartRateVariability",
    GoogleStream.HRV: "heartRateVariability",
    GoogleStream.SPO2: "oxygenSaturation",
    GoogleStream.DAILY_SPO2: "dailyOxygenSaturation",
    GoogleStream.RESPIRATORY_RATE_SLEEP: "respiratoryRateSleepSummary",
    GoogleStream.DAILY_RESPIRATORY_RATE: "dailyRespiratoryRate",
}
_STREAM_ALIASES = {
    "heart-rate": GoogleStream.HEART_RATE,
    "heart-rate-variability": GoogleStream.HRV,
    "daily-heart-rate-variability": GoogleStream.DAILY_HRV,
    "daily-resting-heart-rate": GoogleStream.DAILY_RESTING_HR,
    "oxygen-saturation": GoogleStream.SPO2,
    "daily-oxygen-saturation": GoogleStream.DAILY_SPO2,
    "respiratory-rate-sleep-summary": GoogleStream.RESPIRATORY_RATE_SLEEP,
    "daily-respiratory-rate": GoogleStream.DAILY_RESPIRATORY_RATE,
}
_SLEEP_TYPE_VALUES = frozenset({"SLEEP_TYPE_UNSPECIFIED", "CLASSIC", "STAGES"})
_SLEEP_STAGE_VALUES = frozenset(
    {"SLEEP_STAGE_TYPE_UNSPECIFIED", "AWAKE", "LIGHT", "DEEP", "REM", "ASLEEP", "RESTLESS"}
)
_SLEEP_STAGE_STATUS_VALUES = frozenset(
    {
        "STAGES_STATE_UNSPECIFIED",
        "REJECTED_COVERAGE",
        "REJECTED_MAX_GAP",
        "REJECTED_START_GAP",
        "REJECTED_END_GAP",
        "REJECTED_NAP",
        "REJECTED_SERVER",
        "TIMEOUT",
        "SUCCEEDED",
        "PROCESSING_INTERNAL_ERROR",
    }
)
_SAMPLE_QUERY_MODES = frozenset({GoogleQueryMode.LIST, GoogleQueryMode.RECONCILE})
_HEART_RATE_QUERY_MODES = frozenset(
    {
        GoogleQueryMode.LIST,
        GoogleQueryMode.RECONCILE,
        GoogleQueryMode.ROLL_UP,
        GoogleQueryMode.DAILY_ROLL_UP,
    }
)


@dataclass(frozen=True, slots=True)
class GoogleNormalizationDiagnostic:
    """Sanitized deterministic parser diagnostic."""

    code: str
    message: str
    path: str | None = None
    severity: str = "warning"

    def __post_init__(self) -> None:
        code = self.code.strip().lower()
        severity = self.severity.strip().lower()
        if not _SAFE_TOKEN.fullmatch(code):
            raise ValueError("Google diagnostic code must be a stable token")
        if severity not in {"warning", "error"}:
            raise ValueError("Google diagnostic severity must be warning or error")
        if not self.message.strip():
            raise ValueError("Google diagnostic message is required")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        if self.path is not None:
            object.__setattr__(self, "path", self.path.strip()[:255] or None)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class GoogleNormalizationResult:
    """Deterministic result of one bounded Google response normalization."""

    stream: GoogleStream
    query: GoogleQueryContext
    status: GooglePayloadStatus
    records: tuple[GoogleRecordDTO, ...] = ()
    diagnostics: tuple[GoogleNormalizationDiagnostic, ...] = ()
    unknown_fields: tuple[Mapping[str, object], ...] = ()
    source_identity: GoogleSourceIdentity | None = None
    source_contract_version: str = SOURCE_CONTRACT_VERSION
    normalization_contract_version: str = NORMALIZATION_CONTRACT_VERSION
    next_page_token_state: GoogleMetricState = GoogleMetricState.MISSING

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream", GoogleStream(self.stream))
        if not isinstance(self.query, GoogleQueryContext):
            raise TypeError("Google normalization query must be GoogleQueryContext")
        object.__setattr__(self, "status", GooglePayloadStatus(self.status))
        records = tuple(self.records)
        if any(not isinstance(item, GoogleRecordDTO) for item in records):
            raise TypeError("Google normalization records must be GoogleRecordDTO values")
        if any(item.stream is not self.stream for item in records):
            raise ValueError("Google normalization record stream conflicts with result stream")
        object.__setattr__(self, "records", records)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, GoogleNormalizationDiagnostic) for item in diagnostics):
            raise TypeError("Google diagnostics must be GoogleNormalizationDiagnostic values")
        object.__setattr__(self, "diagnostics", diagnostics[:MAX_DIAGNOSTICS])
        object.__setattr__(self, "unknown_fields", tuple(self.unknown_fields)[:MAX_UNKNOWN_FIELDS])
        object.__setattr__(
            self, "next_page_token_state", GoogleMetricState(self.next_page_token_state)
        )
        if (
            not isinstance(self.source_contract_version, str)
            or not self.source_contract_version.strip()
        ):
            raise ValueError("Google source contract version is required")
        if (
            not isinstance(self.normalization_contract_version, str)
            or not self.normalization_contract_version.strip()
        ):
            raise ValueError("Google normalization contract version is required")

    @property
    def contract_version(self) -> str:
        """Compatibility alias used by other offline normalization contracts."""

        return self.normalization_contract_version

    @property
    def projection_fingerprint(self) -> str:
        """Hash of the normalized DTO, independent of database identifiers."""

        return hashlib.sha256(canonical_json(self.as_dict()).encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "stream": self.stream.value,
            "query": {
                "query_mode": self.query.query_mode.value,
                "data_source_family": self.query.data_source_family,
            },
            "status": self.status.value,
            "records": [item.as_dict() for item in self.records],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "unknown_fields": list(self.unknown_fields),
            "source_contract_version": self.source_contract_version,
            "normalization_contract_version": self.normalization_contract_version,
            "next_page_token_state": self.next_page_token_state.value,
        }


@dataclass(slots=True)
class _ParseContext:
    diagnostics: list[GoogleNormalizationDiagnostic]
    unknown_fields: list[dict[str, object]]
    material_error: bool = False
    partial: bool = False

    def diagnostic(
        self,
        code: str,
        path: str | None,
        *,
        severity: str = "warning",
        material: bool = False,
        partial: bool = False,
    ) -> None:
        if len(self.diagnostics) < MAX_DIAGNOSTICS:
            self.diagnostics.append(
                GoogleNormalizationDiagnostic(
                    code=code,
                    message=_DIAGNOSTIC_MESSAGES.get(code, "Google provider evidence is unusable"),
                    path=path,
                    severity="error" if material else severity,
                )
            )
        self.material_error = self.material_error or material
        self.partial = self.partial or partial

    def unknown(self, path: str, field_name: str, kind: str = "unknown") -> None:
        if len(self.unknown_fields) < MAX_UNKNOWN_FIELDS:
            self.unknown_fields.append(
                {"path": path[:255], "field": field_name[:120], "kind": kind[:80]}
            )


def normalize_google_payload(
    payload: Mapping[str, object] | bytes | bytearray,
    *,
    stream: str | GoogleStream,
    query: GoogleQueryContext | None = None,
    query_context: GoogleQueryContext | None = None,
    source_identity: GoogleSourceIdentity | None = None,
    source_contract_version: str = SOURCE_CONTRACT_VERSION,
    normalization_contract_version: str = NORMALIZATION_CONTRACT_VERSION,
    max_records: int = MAX_NORMALIZATION_RECORDS,
) -> GoogleNormalizationResult:
    """Normalize one bounded Google v4 list/reconcile/rollup response.

    The response envelope is selected by the query mode: ``dataPoints`` for
    list/reconcile and ``rollupDataPoints`` for the two accepted heart-rate
    rollup modes.  Output ordering is canonicalized by stable record identity;
    provider response order is never used as semantic identity.
    """

    normalized_stream = _normalize_stream(stream)
    if query is not None and query_context is not None and query != query_context:
        raise ValueError("query and query_context cannot disagree")
    normalized_query = query or query_context or GoogleQueryContext(GoogleQueryMode.LIST)
    if source_identity is not None and not isinstance(source_identity, GoogleSourceIdentity):
        raise TypeError("source_identity must be a GoogleSourceIdentity")
    if not isinstance(max_records, int) or isinstance(max_records, bool) or max_records <= 0:
        raise ValueError("max_records must be a positive integer")

    top_context = _ParseContext([], [])
    if normalized_query.query_mode not in _allowed_query_modes(normalized_stream):
        top_context.diagnostic(
            "unsupported_query_mode",
            "$.query.query_mode",
            material=True,
        )
        return _result(
            normalized_stream,
            normalized_query,
            GooglePayloadStatus.INVALID,
            source_identity,
            source_contract_version,
            normalization_contract_version,
            diagnostics=top_context.diagnostics,
            unknown_fields=top_context.unknown_fields,
        )

    value = _decode_payload(payload, top_context)
    if value is None:
        return _result(
            normalized_stream,
            normalized_query,
            GooglePayloadStatus.INVALID,
            source_identity,
            source_contract_version,
            normalization_contract_version,
            diagnostics=top_context.diagnostics,
            unknown_fields=top_context.unknown_fields,
        )

    expected_envelope = (
        "rollupDataPoints"
        if normalized_query.query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}
        else "dataPoints"
    )
    for key in value:
        if key not in {expected_envelope, "nextPageToken"}:
            top_context.unknown(f"$.{key}", key, "envelope_field")
    if expected_envelope not in value:
        top_context.diagnostic(
            "response_collection_missing", f"$.{expected_envelope}", material=True
        )
        return _result(
            normalized_stream,
            normalized_query,
            GooglePayloadStatus.INVALID,
            source_identity,
            source_contract_version,
            normalization_contract_version,
            diagnostics=top_context.diagnostics,
            unknown_fields=top_context.unknown_fields,
        )
    points = value[expected_envelope]
    if not isinstance(points, list):
        top_context.diagnostic("response_collection_shape", f"$.{expected_envelope}", material=True)
        return _result(
            normalized_stream,
            normalized_query,
            GooglePayloadStatus.INVALID,
            source_identity,
            source_contract_version,
            normalization_contract_version,
            diagnostics=top_context.diagnostics,
            unknown_fields=top_context.unknown_fields,
        )
    if len(points) > max_records:
        top_context.diagnostic(
            "response_record_limit_exceeded", f"$.{expected_envelope}", material=True
        )
        return _result(
            normalized_stream,
            normalized_query,
            GooglePayloadStatus.INVALID,
            source_identity,
            source_contract_version,
            normalization_contract_version,
            diagnostics=top_context.diagnostics,
            unknown_fields=top_context.unknown_fields,
        )

    next_page_state = _next_page_token_state(value, top_context)
    if not points:
        return _result(
            normalized_stream,
            normalized_query,
            GooglePayloadStatus.EMPTY,
            source_identity,
            source_contract_version,
            normalization_contract_version,
            diagnostics=top_context.diagnostics,
            unknown_fields=top_context.unknown_fields,
            next_page_token_state=next_page_state,
        )

    records: list[GoogleRecordDTO] = []
    record_material_error = False
    record_partial = False
    for index, item in enumerate(points):
        point_path = f"$.{expected_envelope}[{index}]"
        if not isinstance(item, Mapping):
            top_context.diagnostic("record_shape_drift", point_path, material=True)
            record_material_error = True
            continue
        record_context = _ParseContext([], [])
        record = _normalize_point(
            item,
            stream=normalized_stream,
            query=normalized_query,
            path=point_path,
            context=record_context,
            source_identity=source_identity,
        )
        if record is None:
            record_material_error = record_material_error or record_context.material_error
            record_partial = record_partial or record_context.partial
            continue
        record = replace(
            record,
            diagnostics=tuple(item.as_dict() for item in record_context.diagnostics),
            unknown_fields=tuple(record_context.unknown_fields),
        )
        records.append(record)
        record_material_error = record_material_error or record_context.material_error
        record_partial = record_partial or record_context.partial
        top_context.diagnostics.extend(
            record_context.diagnostics[: max(0, MAX_DIAGNOSTICS - len(top_context.diagnostics))]
        )
        top_context.unknown_fields.extend(
            record_context.unknown_fields[
                : max(0, MAX_UNKNOWN_FIELDS - len(top_context.unknown_fields))
            ]
        )

    records.sort(key=lambda item: item.idempotency_key)
    if normalized_stream is GoogleStream.SLEEP:
        # An unkeyed sleep record has no provider identity that can survive a
        # correction.  Keep identical-looking records explicit rather than
        # treating their interval/date as a guessed logical identity.  The
        # occurrence is deterministic after canonical sorting and therefore
        # exact replay remains idempotent.
        occurrences: dict[str, int] = {}
        disambiguated: list[GoogleRecordDTO] = []
        for record in records:
            if record.external_record_id is not None:
                disambiguated.append(record)
                continue
            occurrence = occurrences.get(record.idempotency_key, 0)
            occurrences[record.idempotency_key] = occurrence + 1
            if occurrence:
                disambiguated.append(
                    replace(
                        record,
                        idempotency_key=_unidentified_occurrence_key(
                            record.idempotency_key, occurrence
                        ),
                    )
                )
            else:
                disambiguated.append(record)
        records = disambiguated
    records = [replace(item, record_index=index) for index, item in enumerate(records)]
    status = GooglePayloadStatus.OK
    if top_context.material_error or record_material_error:
        status = GooglePayloadStatus.INVALID
    elif (
        top_context.partial
        or record_partial
        or any(item.status is GooglePayloadStatus.PARTIAL for item in records)
    ):
        status = GooglePayloadStatus.PARTIAL
    return _result(
        normalized_stream,
        normalized_query,
        status,
        source_identity,
        source_contract_version,
        normalization_contract_version,
        records=records,
        diagnostics=top_context.diagnostics,
        unknown_fields=top_context.unknown_fields,
        next_page_token_state=next_page_state,
    )


normalize_google_response = normalize_google_payload


def _unidentified_occurrence_key(base_key: str, occurrence: int) -> str:
    payload = {
        "version": "google-unidentified-sleep-occurrence-v1",
        "base_key": base_key,
        "occurrence": occurrence,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "google-source-record-v1:" + digest
google_normalize = normalize_google_payload


def _result(
    stream: GoogleStream,
    query: GoogleQueryContext,
    status: GooglePayloadStatus,
    source_identity: GoogleSourceIdentity | None,
    source_contract_version: str,
    normalization_contract_version: str,
    *,
    records: Sequence[GoogleRecordDTO] = (),
    diagnostics: Sequence[GoogleNormalizationDiagnostic] = (),
    unknown_fields: Sequence[Mapping[str, object]] = (),
    next_page_token_state: GoogleMetricState = GoogleMetricState.MISSING,
) -> GoogleNormalizationResult:
    return GoogleNormalizationResult(
        stream=stream,
        query=query,
        status=status,
        records=tuple(records),
        diagnostics=tuple(diagnostics)[:MAX_DIAGNOSTICS],
        unknown_fields=tuple(unknown_fields)[:MAX_UNKNOWN_FIELDS],
        source_identity=source_identity,
        source_contract_version=source_contract_version,
        normalization_contract_version=normalization_contract_version,
        next_page_token_state=next_page_token_state,
    )


def _decode_payload(
    payload: Mapping[str, object] | bytes | bytearray, context: _ParseContext
) -> Mapping[str, object] | None:
    if isinstance(payload, (bytes, bytearray)):
        try:
            decoded = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            context.diagnostic("payload_json_invalid", "$", material=True)
            return None
    else:
        decoded = payload
    if not isinstance(decoded, Mapping):
        context.diagnostic("payload_shape_invalid", "$", material=True)
        return None
    return decoded


def _next_page_token_state(
    value: Mapping[str, object], context: _ParseContext
) -> GoogleMetricState:
    if "nextPageToken" not in value:
        return GoogleMetricState.MISSING
    token = value["nextPageToken"]
    if token is None:
        return GoogleMetricState.NULL
    if isinstance(token, str):
        return GoogleMetricState.VALUE
    context.diagnostic("next_page_token_invalid", "$.nextPageToken", partial=True)
    return GoogleMetricState.INVALID


def _allowed_query_modes(stream: GoogleStream) -> frozenset[GoogleQueryMode]:
    return _HEART_RATE_QUERY_MODES if stream is GoogleStream.HEART_RATE else _SAMPLE_QUERY_MODES


def _normalize_stream(stream: str | GoogleStream) -> GoogleStream:
    if isinstance(stream, GoogleStream):
        return stream
    if not isinstance(stream, str):
        return GoogleStream(stream)
    return GoogleStream(_STREAM_ALIASES.get(stream, stream))


def _normalize_point(
    item: Mapping[str, object],
    *,
    stream: GoogleStream,
    query: GoogleQueryContext,
    path: str,
    context: _ParseContext,
    source_identity: GoogleSourceIdentity | None,
) -> GoogleRecordDTO | None:
    if query.query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}:
        record = _normalize_heart_rate_rollup(item, query=query, path=path, context=context)
        if source_identity is not None and source_identity.device_attributed:
            if _validate_attributed_source(source_identity, None, path, context):
                return _invalid_record(
                    item, stream=GoogleStream.HEART_RATE, path=path, context=context
                )
        return record

    expected = _DATA_FIELD_BY_STREAM[stream]
    common_fields = (
        {"name", "dataSource"}
        if query.query_mode is GoogleQueryMode.LIST
        else {"dataPointName"}
    )
    unexpected_union = [
        key for key in item if key not in common_fields and key != expected
    ]
    for key in unexpected_union:
        context.unknown(f"{path}.{key}", key, "unsupported_data_type")
    if unexpected_union:
        context.diagnostic(
            "data_type_union_multiple" if expected in item else "data_type_union_unsupported",
            path,
            material=True,
        )
        return _invalid_record(item, stream=stream, path=path, context=context)
    if expected not in item:
        context.diagnostic("data_type_union_missing", f"{path}.{expected}", material=True)
        return _invalid_record(item, stream=stream, path=path, context=context)
    component = item[expected]
    if not isinstance(component, Mapping):
        context.diagnostic("data_type_component_shape", f"{path}.{expected}", material=True)
        return _invalid_record(item, stream=stream, path=path, context=context)

    data_source = _parse_data_source(
        item.get("dataSource", _MISSING), f"{path}.dataSource", context
    )
    if source_identity is not None and _validate_source_identity_evidence(
        source_identity, data_source, path, context
    ):
        return _invalid_record(item, stream=stream, path=path, context=context)
    external_record_id = _point_name(item, path, context)
    if stream is GoogleStream.SLEEP:
        record = _normalize_sleep(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.HEART_RATE:
        record = _normalize_heart_rate(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.HRV:
        record = _normalize_hrv(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.DAILY_HRV:
        record = _normalize_daily_hrv(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.DAILY_RESTING_HR:
        record = _normalize_daily_resting_hr(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.SPO2:
        record = _normalize_spo2(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.DAILY_SPO2:
        record = _normalize_daily_spo2(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    elif stream is GoogleStream.RESPIRATORY_RATE_SLEEP:
        record = _normalize_respiratory_sleep(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    else:
        record = _normalize_daily_respiratory_rate(
            component,
            path=f"{path}.{expected}",
            external_record_id=external_record_id,
            data_source=data_source,
            context=context,
        )
    return record


def _validate_attributed_source(
    identity: GoogleSourceIdentity,
    data_source: GoogleDataSourceDTO | None,
    path: str,
    context: _ParseContext,
) -> bool:
    """Validate a caller-supplied device claim against point-level evidence."""

    if identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE:
        context.diagnostic("source_attribution_invalid", path, material=True)
        return True
    if data_source is None or data_source.state is not GoogleMetricState.VALUE:
        context.diagnostic("source_attribution_invalid", f"{path}.dataSource", material=True)
        return True
    platform = data_source.platform
    required_device_fields = (
        data_source.device_form_factor,
        data_source.device_manufacturer,
        data_source.device_display_name,
    )
    if (
        platform is None
        or platform.state is not GoogleMetricState.VALUE
        or platform.value_text != "FITBIT"
        or any(
            field is None or field.state is not GoogleMetricState.VALUE
            for field in required_device_fields
        )
    ):
        context.diagnostic("source_attribution_invalid", f"{path}.dataSource", material=True)
        return True
    return False


def _validate_source_identity_evidence(
    identity: GoogleSourceIdentity,
    data_source: GoogleDataSourceDTO,
    path: str,
    context: _ParseContext,
) -> bool:
    if (
        identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE
        and data_source.state is GoogleMetricState.VALUE
    ):
        context.diagnostic("source_identity_conflict", f"{path}.dataSource", material=True)
        return True
    if identity.device_attributed:
        return _validate_attributed_source(identity, data_source, path, context)
    return False


def _invalid_record(
    item: Mapping[str, object], *, stream: GoogleStream, path: str, context: _ParseContext
) -> GoogleRecordDTO:
    context.material_error = True
    temporal = GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.UNKNOWN,
        state=GoogleMetricState.INVALID,
        source_field=path,
    )
    return _finish_record(
        stream=stream,
        temporal=temporal,
        external_record_id=_point_name(item, path, context, diagnose=False),
        metrics=(),
        status=GooglePayloadStatus.INVALID,
        data_source=None,
        semantic_basis={"invalid": _shape_key(item)},
    )


def _finish_record(
    *,
    stream: GoogleStream,
    temporal: GoogleTemporalDTO,
    external_record_id: str | None,
    metrics: Sequence[GoogleMetricDTO],
    status: GooglePayloadStatus | None = None,
    wake_date: date | None = None,
    data_source: GoogleDataSourceDTO | None,
    semantic_basis: Mapping[str, object],
    interval: GoogleIntervalDTO | None = None,
    sleep_interval: GoogleIntervalDTO | None = None,
    sleep_stages: Sequence[GoogleSleepStageDTO] = (),
    sleep_stages_state: GoogleMetricState = GoogleMetricState.MISSING,
    out_of_bed_segments: Sequence[GoogleIntervalDTO] = (),
    out_of_bed_state: GoogleMetricState = GoogleMetricState.MISSING,
) -> GoogleRecordDTO:
    if stream is GoogleStream.SLEEP and external_record_id is not None:
        identity_basis = {
            "stream": stream.value,
            "logical_external_record_id": external_record_id,
        }
    else:
        identity_basis = {
            "stream": stream.value,
            "external_record_id": external_record_id,
            "semantic": semantic_basis,
        }
    idempotency_key = (
        "google-source-record-v1:"
        + hashlib.sha256(canonical_json(identity_basis).encode("utf-8")).hexdigest()
    )
    return GoogleRecordDTO(
        stream=stream,
        idempotency_key=idempotency_key,
        temporal=temporal,
        status=status or GooglePayloadStatus.OK,
        external_record_id=external_record_id,
        wake_date=wake_date,
        metrics=tuple(metrics),
        interval=interval,
        sleep_interval=sleep_interval,
        sleep_stages=tuple(sleep_stages),
        sleep_stages_state=sleep_stages_state,
        out_of_bed_segments=tuple(out_of_bed_segments),
        out_of_bed_state=out_of_bed_state,
        data_source=data_source,
    )


def _record_status(context: _ParseContext) -> GooglePayloadStatus:
    if context.material_error:
        return GooglePayloadStatus.INVALID
    return GooglePayloadStatus.PARTIAL if context.partial else GooglePayloadStatus.OK


def _point_name(
    item: Mapping[str, object], path: str, context: _ParseContext, *, diagnose: bool = True
) -> str | None:
    name = item.get("name", _MISSING)
    reconciled_name = item.get("dataPointName", _MISSING)
    if name is not _MISSING and reconciled_name is not _MISSING and name != reconciled_name:
        if diagnose:
            context.diagnostic("record_identity_conflict", path, material=True)
        return None
    value = name if name is not _MISSING else reconciled_name
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        if diagnose:
            context.diagnostic("record_identity_invalid", f"{path}.name", partial=True)
        return None
    return value.strip()


def _shape_key(value: Mapping[str, object]) -> str:
    """Return a bounded hash, never a raw payload fragment."""

    try:
        encoded = canonical_json(value)
    except (TypeError, ValueError):
        encoded = str(sorted(str(key) for key in value))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _path(parent: str, field_name: str) -> str:
    return f"{parent}.{field_name}"


def _string_metric(
    *,
    code: str,
    field_path: str,
    raw: object,
    context: _ParseContext,
    allowed: frozenset[str] | None = None,
    allow_empty: bool = False,
    required: bool = False,
) -> GoogleMetricDTO:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_field_missing", field_path, material=True)
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.MISSING,
            reason="required_field_missing" if required else "field_missing",
        )
    if raw is None:
        if required:
            context.diagnostic("required_field_null", field_path, material=True)
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.NULL,
            reason="required_field_null" if required else "field_null",
        )
    if not isinstance(raw, str) or (not allow_empty and not raw.strip()):
        context.diagnostic(
            "field_string_invalid",
            field_path,
            material=required,
            partial=not required,
        )
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.INVALID,
            reason="string_shape_invalid",
        )
    normalized = raw.strip()
    if allowed is not None and normalized not in allowed:
        context.diagnostic(
            "field_enum_unknown", field_path, material=required, partial=not required
        )
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.INVALID,
            reason="enum_unknown",
        )
    return GoogleMetricDTO(
        metric_code=code,
        field_path=field_path,
        state=GoogleMetricState.VALUE,
        value_text=normalized,
    )


def _boolean_metric(
    *, code: str, field_path: str, raw: object, context: _ParseContext, required: bool = False
) -> GoogleMetricDTO:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_field_missing", field_path, material=True)
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.MISSING,
            reason="required_field_missing" if required else "field_missing",
        )
    if raw is None:
        if required:
            context.diagnostic("required_field_null", field_path, material=True)
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.NULL,
            reason="required_field_null" if required else "field_null",
        )
    if not isinstance(raw, bool):
        context.diagnostic(
            "field_boolean_invalid", field_path, material=required, partial=not required
        )
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.INVALID,
            reason="boolean_shape_invalid",
        )
    return GoogleMetricDTO(
        metric_code=code,
        field_path=field_path,
        state=GoogleMetricState.VALUE,
        value_text="true" if raw else "false",
    )


def _numeric_metric(
    *,
    code: str,
    field_path: str,
    raw: object,
    context: _ParseContext,
    unit: str | None,
    required: bool = False,
    integer: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> GoogleMetricDTO:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_field_missing", field_path, material=True)
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.MISSING,
            unit=unit,
            reason="required_field_missing" if required else "field_missing",
        )
    if raw is None:
        if required:
            context.diagnostic("required_field_null", field_path, material=True)
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.NULL,
            unit=unit,
            reason="required_field_null" if required else "field_null",
        )
    parsed = _parse_number(raw, integer=integer)
    if parsed is None:
        context.diagnostic(
            "numeric_value_invalid",
            field_path,
            material=required,
            partial=not required,
        )
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.INVALID,
            unit=unit,
            reason="numeric_invalid_or_non_finite",
        )
    if (minimum is not None and parsed < minimum) or (maximum is not None and parsed > maximum):
        context.diagnostic(
            "numeric_range_invalid", field_path, material=required, partial=not required
        )
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.INVALID,
            unit=unit,
            reason="numeric_out_of_range",
        )
    return GoogleMetricDTO(
        metric_code=code,
        field_path=field_path,
        state=GoogleMetricState.VALUE,
        value_number=parsed,
        value_text=raw.strip() if isinstance(raw, str) else None,
        unit=unit,
    )


def _parse_number(raw: object, *, integer: bool) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or (integer and not _INT_TEXT.fullmatch(text)):
            return None
        try:
            decimal = Decimal(text)
        except InvalidOperation:
            return None
    else:
        decimal = Decimal(str(raw))
    if not decimal.is_finite():
        return None
    if integer and decimal != decimal.to_integral_value():
        return None
    try:
        value = float(decimal)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _parse_data_source(raw: object, path: str, context: _ParseContext) -> GoogleDataSourceDTO:
    if raw is _MISSING:
        return GoogleDataSourceDTO(state=GoogleMetricState.MISSING, field_path=path)
    if raw is None:
        return GoogleDataSourceDTO(state=GoogleMetricState.NULL, field_path=path)
    if not isinstance(raw, Mapping):
        context.diagnostic("data_source_shape_invalid", path, partial=True)
        return GoogleDataSourceDTO(state=GoogleMetricState.INVALID, field_path=path)
    known = {"recordingMethod", "device", "application", "platform"}
    for key in raw:
        if key not in known:
            context.unknown(_path(path, str(key)), str(key), "data_source_field")
    fields: list[GoogleMetricDTO] = [
        _string_metric(
            code="data_source_recording_method",
            field_path=_path(path, "recordingMethod"),
            raw=raw.get("recordingMethod", _MISSING),
            context=context,
            allow_empty=False,
        ),
        _string_metric(
            code="data_source_platform",
            field_path=_path(path, "platform"),
            raw=raw.get("platform", _MISSING),
            context=context,
            allow_empty=False,
        ),
    ]
    device = raw.get("device", _MISSING)
    fields.extend(_data_source_nested_fields(device, _path(path, "device"), context, "device"))
    application = raw.get("application", _MISSING)
    fields.extend(
        _data_source_nested_fields(application, _path(path, "application"), context, "application")
    )
    return GoogleDataSourceDTO(state=GoogleMetricState.VALUE, field_path=path, fields=tuple(fields))


def _data_source_nested_fields(
    raw: object, path: str, context: _ParseContext, kind: str
) -> list[GoogleMetricDTO]:
    if kind == "device":
        definitions = (
            ("data_source_device_form_factor", "formFactor"),
            ("data_source_device_manufacturer", "manufacturer"),
            ("data_source_device_display_name", "displayName"),
        )
    else:
        definitions = (
            ("data_source_application_package_name", "packageName"),
            ("data_source_application_web_client_id", "webClientId"),
            ("data_source_application_google_web_client_id", "googleWebClientId"),
        )
    if raw is _MISSING:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.MISSING,
                reason="parent_field_missing",
            )
            for code, field_name in definitions
        ]
    if raw is None:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.NULL,
                reason="parent_field_null",
            )
            for code, field_name in definitions
        ]
    if not isinstance(raw, Mapping):
        context.diagnostic("data_source_nested_shape_invalid", path, partial=True)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.INVALID,
                reason="parent_shape_invalid",
            )
            for code, field_name in definitions
        ]
    allowed_fields = {field_name for _, field_name in definitions}
    for key in raw:
        if key not in allowed_fields:
            context.unknown(_path(path, str(key)), str(key), f"data_source_{kind}_field")
    return [
        _string_metric(
            code=code,
            field_path=_path(path, field_name),
            raw=raw.get(field_name, _MISSING),
            context=context,
            allow_empty=True,
        )
        for code, field_name in definitions
    ]


def _parse_timestamp(
    raw: object, path: str, context: _ParseContext, *, required: bool
) -> datetime | None:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_timestamp_missing", path, material=True)
        return None
    if raw is None:
        if required:
            context.diagnostic("required_timestamp_null", path, material=True)
        return None
    if not isinstance(raw, str) or not raw.strip():
        context.diagnostic("timestamp_invalid", path, material=required, partial=not required)
        return None
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        context.diagnostic("timestamp_invalid", path, material=required, partial=not required)
        return None
    return parsed.astimezone(UTC)


def _parse_offset(raw: object, path: str, context: _ParseContext, *, required: bool) -> int | None:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_offset_missing", path, material=True)
        return None
    if raw is None:
        if required:
            context.diagnostic("required_offset_null", path, material=True)
        return None
    if isinstance(raw, bool):
        context.diagnostic("offset_invalid", path, material=required, partial=not required)
        return None
    if isinstance(raw, (int, float)):
        text = str(raw)
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        context.diagnostic("offset_invalid", path, material=required, partial=not required)
        return None
    match = _DURATION_TEXT.fullmatch(text)
    if match is None:
        context.diagnostic("offset_invalid", path, material=required, partial=not required)
        return None
    sign, whole, fraction = match.groups()
    seconds = Decimal(f"{sign}{whole}.{fraction or '0'}")
    minutes = seconds / Decimal(60)
    if minutes != minutes.to_integral_value() or minutes < -1439 or minutes > 1439:
        context.diagnostic("offset_invalid", path, material=required, partial=not required)
        return None
    return int(minutes)


def _parse_date_value(
    raw: object, path: str, context: _ParseContext, *, required: bool
) -> date | None:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_date_missing", path, material=True)
        return None
    if raw is None:
        if required:
            context.diagnostic("required_date_null", path, material=True)
        return None
    if not isinstance(raw, Mapping):
        context.diagnostic("date_shape_invalid", path, material=required, partial=not required)
        return None
    _note_unknown_fields(raw, path, {"year", "month", "day"}, context)
    values: list[int] = []
    for field_name in ("year", "month", "day"):
        value = raw.get(field_name, _MISSING)
        if not isinstance(value, int) or isinstance(value, bool):
            context.diagnostic(
                "date_shape_invalid",
                _path(path, field_name),
                material=required,
                partial=not required,
            )
            return None
        values.append(value)
    year, month, day = values
    if year < 1 or month < 1 or day < 1:
        context.diagnostic(
            "date_partial_not_supported", path, material=required, partial=not required
        )
        return None
    try:
        return date(year, month, day)
    except ValueError:
        context.diagnostic("date_invalid", path, material=required, partial=not required)
        return None


def _parse_time_of_day(
    raw: object, path: str, context: _ParseContext
) -> tuple[int, int, int, int] | None:
    if raw is _MISSING:
        return 0, 0, 0, 0
    if raw is None or not isinstance(raw, Mapping):
        context.diagnostic("civil_time_shape_invalid", path, partial=True)
        return None
    _note_unknown_fields(raw, path, {"hours", "minutes", "seconds", "nanos"}, context)
    values: list[int] = []
    limits = {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 999_999_999}
    for field_name in ("hours", "minutes", "seconds", "nanos"):
        value = raw.get(field_name, 0)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > limits[field_name]
        ):
            context.diagnostic("civil_time_invalid", _path(path, field_name), partial=True)
            return None
        values.append(value)
    return tuple(values)  # type: ignore[return-value]


def _parse_civil_datetime(
    raw: object, path: str, context: _ParseContext, *, required: bool
) -> tuple[date | None, str | None] | None:
    if raw is _MISSING:
        if required:
            context.diagnostic("required_civil_time_missing", path, material=True)
        return None
    if raw is None:
        if required:
            context.diagnostic("required_civil_time_null", path, material=True)
        else:
            context.diagnostic("civil_time_null", path, partial=True)
        return None
    if not isinstance(raw, Mapping):
        context.diagnostic(
            "civil_time_shape_invalid", path, material=required, partial=not required
        )
        return None
    _note_unknown_fields(raw, path, {"date", "time"}, context)
    local_date = _parse_date_value(
        raw.get("date", _MISSING), _path(path, "date"), context, required=required
    )
    time_values = _parse_time_of_day(raw.get("time", _MISSING), _path(path, "time"), context)
    if local_date is None or time_values is None:
        return None
    hours, minutes, seconds, nanos = time_values
    fraction = f".{nanos:09d}".rstrip("0") if nanos else ""
    return local_date, f"{local_date.isoformat()}T{hours:02d}:{minutes:02d}:{seconds:02d}{fraction}"


def _empty_temporal(
    path: str,
    state: GoogleMetricState,
    *,
    source_local_field: str | None = None,
    source_utc_field: str | None = None,
) -> GoogleTemporalDTO:
    return GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.UNKNOWN,
        state=state,
        source_field=path,
        source_local_field=source_local_field,
        source_utc_field=source_utc_field,
    )


def _sample_temporal(raw: object, path: str, context: _ParseContext) -> GoogleTemporalDTO:
    if raw is _MISSING:
        context.diagnostic("required_sample_time_missing", path, material=True)
        return _empty_temporal(path, GoogleMetricState.MISSING, source_utc_field=path)
    if raw is None:
        context.diagnostic("required_sample_time_null", path, material=True)
        return _empty_temporal(path, GoogleMetricState.NULL, source_utc_field=path)
    if not isinstance(raw, Mapping):
        context.diagnostic("sample_time_shape_invalid", path, material=True)
        return _empty_temporal(path, GoogleMetricState.INVALID, source_utc_field=path)
    _note_unknown_fields(raw, path, {"physicalTime", "utcOffset", "civilTime"}, context)
    physical_path = _path(path, "physicalTime")
    offset_path = _path(path, "utcOffset")
    measured_at = _parse_timestamp(
        raw.get("physicalTime", _MISSING), physical_path, context, required=True
    )
    offset = _parse_offset(raw.get("utcOffset", _MISSING), offset_path, context, required=True)
    if measured_at is None or offset is None:
        physical_value = raw.get("physicalTime", _MISSING)
        offset_value = raw.get("utcOffset", _MISSING)
        state = (
            GoogleMetricState.MISSING
            if physical_value is _MISSING and offset_value is _MISSING
            else GoogleMetricState.NULL
            if physical_value is None or offset_value is None
            else GoogleMetricState.INVALID
        )
        return _empty_temporal(physical_path, state, source_utc_field=physical_path)
    local_date: date | None = None
    local_wall_time: str | None = None
    local_source_field: str | None = None
    civil = _parse_civil_datetime(
        raw.get("civilTime", _MISSING), _path(path, "civilTime"), context, required=False
    )
    if civil is not None:
        local_date, local_wall_time = civil
        local_source_field = _path(path, "civilTime")
    else:
        local = (measured_at + timedelta(minutes=offset)).replace(tzinfo=None)
        local_date = local.date()
        local_wall_time = local.isoformat()
        local_source_field = offset_path
    return GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.INSTANT,
        state=GoogleMetricState.VALUE,
        local_date=local_date,
        measured_at_utc=measured_at,
        local_wall_time=local_wall_time,
        source_local_timestamp=local_wall_time,
        source_utc_offset_minutes=offset,
        source_field=path,
        source_local_field=local_source_field,
        source_utc_field=physical_path,
    )


def _physical_temporal(raw: object, path: str, context: _ParseContext) -> GoogleTemporalDTO:
    measured_at = _parse_timestamp(raw, path, context, required=True)
    if measured_at is None:
        state = (
            GoogleMetricState.NULL
            if raw is None
            else GoogleMetricState.MISSING
            if raw is _MISSING
            else GoogleMetricState.INVALID
        )
        return _empty_temporal(path, state, source_utc_field=path)
    return GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.INSTANT,
        state=GoogleMetricState.VALUE,
        measured_at_utc=measured_at,
        source_field=path,
        source_utc_field=path,
    )


def _civil_temporal(raw: object, path: str, context: _ParseContext) -> GoogleTemporalDTO:
    parsed = _parse_civil_datetime(raw, path, context, required=True)
    if parsed is None:
        state = (
            GoogleMetricState.NULL
            if raw is None
            else GoogleMetricState.MISSING
            if raw is _MISSING
            else GoogleMetricState.INVALID
        )
        return _empty_temporal(path, state, source_local_field=path)
    local_date, local_wall_time = parsed
    return GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.LOCAL,
        state=GoogleMetricState.VALUE,
        local_date=local_date,
        local_wall_time=local_wall_time,
        source_local_timestamp=local_wall_time,
        source_field=path,
        source_local_field=path,
    )


def _interval_endpoint(
    raw: object,
    path: str,
    context: _ParseContext,
    *,
    endpoint: str,
    time_field: str,
    offset_field: str | None,
    civil_field: str | None,
) -> GoogleTemporalDTO:
    endpoint_path = _path(path, endpoint)
    physical_path = _path(path, time_field)
    if not isinstance(raw, Mapping):
        context.diagnostic("interval_shape_invalid", endpoint_path, material=True)
        return _empty_temporal(
            physical_path,
            GoogleMetricState.INVALID,
            source_utc_field=physical_path,
        )
    offset_path = _path(path, offset_field) if offset_field is not None else None
    measured_at = _parse_timestamp(
        raw.get(time_field, _MISSING), physical_path, context, required=True
    )
    offset = (
        _parse_offset(raw.get(offset_field, _MISSING), offset_path, context, required=True)
        if offset_field is not None and offset_path is not None
        else None
    )
    if offset_field is None:
        offset = 0
    if measured_at is None or offset is None:
        time_value = raw.get(time_field, _MISSING)
        offset_value = raw.get(offset_field, _MISSING) if offset_field is not None else 0
        state = (
            GoogleMetricState.MISSING
            if time_value is _MISSING and offset_value is _MISSING
            else GoogleMetricState.NULL
            if time_value is None or offset_value is None
            else GoogleMetricState.INVALID
        )
        return _empty_temporal(physical_path, state, source_utc_field=physical_path)
    local_date: date | None = None
    local_wall_time: str | None = None
    local_field: str | None = None
    if civil_field is not None:
        civil = _parse_civil_datetime(
            raw.get(civil_field, _MISSING), _path(path, civil_field), context, required=False
        )
        if civil is not None:
            local_date, local_wall_time = civil
            local_field = _path(path, civil_field)
    if local_date is None or local_wall_time is None:
        local = (measured_at + timedelta(minutes=offset)).replace(tzinfo=None)
        local_date = local.date()
        local_wall_time = local.isoformat()
        local_field = offset_path
    return GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.INSTANT,
        state=GoogleMetricState.VALUE,
        local_date=local_date,
        measured_at_utc=measured_at,
        local_wall_time=local_wall_time,
        source_local_timestamp=local_wall_time,
        source_utc_offset_minutes=offset,
        source_field=physical_path,
        source_local_field=local_field,
        source_utc_field=physical_path,
    )


def _parse_source_interval(
    raw: object,
    path: str,
    context: _ParseContext,
    *,
    interval_kind: GoogleIntervalKind,
    civil_start_field: str | None,
    civil_end_field: str | None,
) -> GoogleIntervalDTO:
    if raw is _MISSING:
        context.diagnostic("required_interval_missing", path, material=True)
        return GoogleIntervalDTO(
            start=_empty_temporal(
                _path(path, "startTime"),
                GoogleMetricState.MISSING,
                source_utc_field=_path(path, "startTime"),
            ),
            end=_empty_temporal(
                _path(path, "endTime"),
                GoogleMetricState.MISSING,
                source_utc_field=_path(path, "endTime"),
            ),
            interval_kind=interval_kind,
            state=GoogleMetricState.MISSING,
        )
    if raw is None:
        context.diagnostic("required_interval_null", path, material=True)
        return GoogleIntervalDTO(
            start=_empty_temporal(
                _path(path, "startTime"),
                GoogleMetricState.NULL,
                source_utc_field=_path(path, "startTime"),
            ),
            end=_empty_temporal(
                _path(path, "endTime"),
                GoogleMetricState.NULL,
                source_utc_field=_path(path, "endTime"),
            ),
            interval_kind=interval_kind,
            state=GoogleMetricState.NULL,
        )
    if not isinstance(raw, Mapping):
        context.diagnostic("interval_shape_invalid", path, material=True)
        return GoogleIntervalDTO(
            start=_empty_temporal(
                _path(path, "startTime"),
                GoogleMetricState.INVALID,
                source_utc_field=_path(path, "startTime"),
            ),
            end=_empty_temporal(
                _path(path, "endTime"),
                GoogleMetricState.INVALID,
                source_utc_field=_path(path, "endTime"),
            ),
            interval_kind=interval_kind,
            state=GoogleMetricState.INVALID,
        )
    known_fields = {"startTime", "startUtcOffset", "endTime", "endUtcOffset"}
    if civil_start_field is not None:
        known_fields.add(civil_start_field)
    if civil_end_field is not None:
        known_fields.add(civil_end_field)
    _note_unknown_fields(raw, path, known_fields, context)
    start = _interval_endpoint(
        raw,
        path,
        context,
        endpoint="start",
        time_field="startTime",
        offset_field="startUtcOffset",
        civil_field="civilStartTime" if civil_start_field else None,
    )
    end = _interval_endpoint(
        raw,
        path,
        context,
        endpoint="end",
        time_field="endTime",
        offset_field="endUtcOffset",
        civil_field="civilEndTime" if civil_end_field else None,
    )
    interval_state = GoogleMetricState.VALUE
    if start.state is not GoogleMetricState.VALUE or end.state is not GoogleMetricState.VALUE:
        interval_state = GoogleMetricState.INVALID
    if (
        start.measured_at_utc is not None
        and end.measured_at_utc is not None
        and end.measured_at_utc <= start.measured_at_utc
    ):
        context.diagnostic("interval_order_invalid", path, material=True)
        interval_state = GoogleMetricState.INVALID
    return GoogleIntervalDTO(
        start=start,
        end=end,
        interval_kind=interval_kind,
        state=interval_state,
    )


def _note_unknown_fields(
    value: Mapping[str, object], path: str, known: set[str], context: _ParseContext
) -> None:
    for key in value:
        if key not in known:
            context.unknown(_path(path, str(key)), str(key), "provider_field")


def _normalize_heart_rate(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(value, path, {"sampleTime", "metadata", "beatsPerMinute"}, context)
    temporal = _sample_temporal(
        value.get("sampleTime", _MISSING), _path(path, "sampleTime"), context
    )
    metrics = [
        _numeric_metric(
            code="heart_rate_bpm",
            field_path=_path(path, "beatsPerMinute"),
            raw=value.get("beatsPerMinute", _MISSING),
            context=context,
            unit="bpm",
            required=True,
            integer=True,
        )
    ]
    metadata = value.get("metadata", _MISSING)
    metrics.extend(_heart_rate_metadata_metrics(metadata, _path(path, "metadata"), context))
    return _finish_record(
        stream=GoogleStream.HEART_RATE,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"time": temporal.as_dict()},
    )


def _heart_rate_metadata_metrics(
    value: object, path: str, context: _ParseContext
) -> list[GoogleMetricDTO]:
    if value is _MISSING:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.MISSING,
                reason="parent_field_missing",
            )
            for code, field_name in (
                ("heart_rate_motion_context", "motionContext"),
                ("heart_rate_sensor_location", "sensorLocation"),
            )
        ]
    if value is None:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.NULL,
                reason="parent_field_null",
            )
            for code, field_name in (
                ("heart_rate_motion_context", "motionContext"),
                ("heart_rate_sensor_location", "sensorLocation"),
            )
        ]
    if not isinstance(value, Mapping):
        context.diagnostic("metadata_shape_invalid", path, partial=True)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.INVALID,
                reason="parent_shape_invalid",
            )
            for code, field_name in (
                ("heart_rate_motion_context", "motionContext"),
                ("heart_rate_sensor_location", "sensorLocation"),
            )
        ]
    _note_unknown_fields(value, path, {"motionContext", "sensorLocation"}, context)
    return [
        _string_metric(
            code="heart_rate_motion_context",
            field_path=_path(path, "motionContext"),
            raw=value.get("motionContext", _MISSING),
            context=context,
        ),
        _string_metric(
            code="heart_rate_sensor_location",
            field_path=_path(path, "sensorLocation"),
            raw=value.get("sensorLocation", _MISSING),
            context=context,
        ),
    ]


def _normalize_hrv(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(
        value,
        path,
        {
            "sampleTime",
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds",
            "standardDeviationMilliseconds",
        },
        context,
    )
    temporal = _sample_temporal(
        value.get("sampleTime", _MISSING), _path(path, "sampleTime"), context
    )
    metrics = [
        _numeric_metric(
            code="hrv_rmssd_ms",
            field_path=_path(path, "rootMeanSquareOfSuccessiveDifferencesMilliseconds"),
            raw=value.get("rootMeanSquareOfSuccessiveDifferencesMilliseconds", _MISSING),
            context=context,
            unit="ms",
        ),
        _numeric_metric(
            code="hrv_sdnn_ms",
            field_path=_path(path, "standardDeviationMilliseconds"),
            raw=value.get("standardDeviationMilliseconds", _MISSING),
            context=context,
            unit="ms",
        ),
    ]
    return _finish_record(
        stream=GoogleStream.HRV,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"time": temporal.as_dict()},
    )


def _normalize_daily_hrv(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    field_names = {
        "date",
        "averageHeartRateVariabilityMilliseconds",
        "nonRemHeartRateBeatsPerMinute",
        "entropy",
        "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds",
    }
    _note_unknown_fields(value, path, field_names, context)
    temporal = _date_temporal(value.get("date", _MISSING), _path(path, "date"), context)
    metrics = [
        _numeric_metric(
            code="daily_hrv_average_ms",
            field_path=_path(path, "averageHeartRateVariabilityMilliseconds"),
            raw=value.get("averageHeartRateVariabilityMilliseconds", _MISSING),
            context=context,
            unit="ms",
        ),
        _numeric_metric(
            code="daily_hrv_non_rem_bpm",
            field_path=_path(path, "nonRemHeartRateBeatsPerMinute"),
            raw=value.get("nonRemHeartRateBeatsPerMinute", _MISSING),
            context=context,
            unit="bpm",
            integer=True,
        ),
        _numeric_metric(
            code="daily_hrv_entropy",
            field_path=_path(path, "entropy"),
            raw=value.get("entropy", _MISSING),
            context=context,
            unit=None,
        ),
        _numeric_metric(
            code="daily_hrv_deep_sleep_rmssd_ms",
            field_path=_path(path, "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds"),
            raw=value.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds", _MISSING),
            context=context,
            unit="ms",
        ),
    ]
    if not any(metric.state is GoogleMetricState.VALUE for metric in metrics):
        context.diagnostic("daily_hrv_value_missing", path, material=True)
    return _finish_record(
        stream=GoogleStream.DAILY_HRV,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"date": temporal.local_date.isoformat() if temporal.local_date else None},
    )


def _date_temporal(raw: object, path: str, context: _ParseContext) -> GoogleTemporalDTO:
    local_date = _parse_date_value(raw, path, context, required=True)
    if local_date is None:
        state = (
            GoogleMetricState.NULL
            if raw is None
            else GoogleMetricState.MISSING
            if raw is _MISSING
            else GoogleMetricState.INVALID
        )
        return _empty_temporal(path, state)
    return GoogleTemporalDTO(
        precision=GoogleTemporalPrecision.DATE,
        state=GoogleMetricState.VALUE,
        local_date=local_date,
        source_field=path,
        source_local_field=path,
    )


def _normalize_daily_resting_hr(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(
        value, path, {"date", "dailyRestingHeartRateMetadata", "beatsPerMinute"}, context
    )
    temporal = _date_temporal(value.get("date", _MISSING), _path(path, "date"), context)
    metrics = [
        _numeric_metric(
            code="daily_resting_heart_rate_bpm",
            field_path=_path(path, "beatsPerMinute"),
            raw=value.get("beatsPerMinute", _MISSING),
            context=context,
            unit="bpm",
            required=True,
            integer=True,
        )
    ]
    metadata = value.get("dailyRestingHeartRateMetadata", _MISSING)
    if metadata is _MISSING:
        metrics.append(
            GoogleMetricDTO(
                metric_code="daily_resting_heart_rate_calculation_method",
                field_path=_path(path, "dailyRestingHeartRateMetadata.calculationMethod"),
                state=GoogleMetricState.MISSING,
                reason="parent_field_missing",
            )
        )
    elif metadata is None:
        metrics.append(
            GoogleMetricDTO(
                metric_code="daily_resting_heart_rate_calculation_method",
                field_path=_path(path, "dailyRestingHeartRateMetadata.calculationMethod"),
                state=GoogleMetricState.NULL,
                reason="parent_field_null",
            )
        )
    elif not isinstance(metadata, Mapping):
        context.diagnostic(
            "metadata_shape_invalid", _path(path, "dailyRestingHeartRateMetadata"), partial=True
        )
        metrics.append(
            GoogleMetricDTO(
                metric_code="daily_resting_heart_rate_calculation_method",
                field_path=_path(path, "dailyRestingHeartRateMetadata.calculationMethod"),
                state=GoogleMetricState.INVALID,
                reason="parent_shape_invalid",
            )
        )
    else:
        metadata_path = _path(path, "dailyRestingHeartRateMetadata")
        _note_unknown_fields(metadata, metadata_path, {"calculationMethod"}, context)
        metrics.append(
            _string_metric(
                code="daily_resting_heart_rate_calculation_method",
                field_path=_path(metadata_path, "calculationMethod"),
                raw=metadata.get("calculationMethod", _MISSING),
                context=context,
                required=True,
            )
        )
    return _finish_record(
        stream=GoogleStream.DAILY_RESTING_HR,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"date": temporal.local_date.isoformat() if temporal.local_date else None},
    )


def _normalize_spo2(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(value, path, {"sampleTime", "percentage"}, context)
    temporal = _sample_temporal(
        value.get("sampleTime", _MISSING), _path(path, "sampleTime"), context
    )
    metric = _numeric_metric(
        code="oxygen_saturation_percentage",
        field_path=_path(path, "percentage"),
        raw=value.get("percentage", _MISSING),
        context=context,
        unit="%",
        required=True,
        minimum=0,
        maximum=100,
    )
    return _finish_record(
        stream=GoogleStream.SPO2,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=(metric,),
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"time": temporal.as_dict()},
    )


def _normalize_daily_spo2(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(
        value,
        path,
        {
            "date",
            "averagePercentage",
            "lowerBoundPercentage",
            "upperBoundPercentage",
            "standardDeviationPercentage",
        },
        context,
    )
    temporal = _date_temporal(value.get("date", _MISSING), _path(path, "date"), context)
    metrics = [
        _numeric_metric(
            code="daily_oxygen_saturation_average_percentage",
            field_path=_path(path, "averagePercentage"),
            raw=value.get("averagePercentage", _MISSING),
            context=context,
            unit="%",
            required=True,
            minimum=0,
            maximum=100,
        ),
        _numeric_metric(
            code="daily_oxygen_saturation_lower_percentage",
            field_path=_path(path, "lowerBoundPercentage"),
            raw=value.get("lowerBoundPercentage", _MISSING),
            context=context,
            unit="%",
            required=True,
            minimum=0,
            maximum=100,
        ),
        _numeric_metric(
            code="daily_oxygen_saturation_upper_percentage",
            field_path=_path(path, "upperBoundPercentage"),
            raw=value.get("upperBoundPercentage", _MISSING),
            context=context,
            unit="%",
            required=True,
            minimum=0,
            maximum=100,
        ),
        _numeric_metric(
            code="daily_oxygen_saturation_standard_deviation_percentage",
            field_path=_path(path, "standardDeviationPercentage"),
            raw=value.get("standardDeviationPercentage", _MISSING),
            context=context,
            unit="%",
            minimum=0,
        ),
    ]
    return _finish_record(
        stream=GoogleStream.DAILY_SPO2,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"date": temporal.local_date.isoformat() if temporal.local_date else None},
    )


def _normalize_respiratory_sleep(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(
        value,
        path,
        {"sampleTime", "deepSleepStats", "lightSleepStats", "remSleepStats", "fullSleepStats"},
        context,
    )
    temporal = _sample_temporal(
        value.get("sampleTime", _MISSING), _path(path, "sampleTime"), context
    )
    metrics: list[GoogleMetricDTO] = []
    for prefix, field_name, required in (
        ("deep_sleep", "deepSleepStats", False),
        ("light_sleep", "lightSleepStats", False),
        ("rem_sleep", "remSleepStats", False),
        ("full_sleep", "fullSleepStats", True),
    ):
        metrics.extend(
            _respiratory_stats_metrics(
                value.get(field_name, _MISSING),
                _path(path, field_name),
                prefix,
                context,
                required=required,
            )
        )
    return _finish_record(
        stream=GoogleStream.RESPIRATORY_RATE_SLEEP,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"time": temporal.as_dict()},
    )


def _respiratory_stats_metrics(
    raw: object,
    path: str,
    prefix: str,
    context: _ParseContext,
    *,
    required: bool,
) -> list[GoogleMetricDTO]:
    definitions = (
        (f"respiratory_{prefix}_breaths_per_minute", "breathsPerMinute", None, required),
        (f"respiratory_{prefix}_standard_deviation", "standardDeviation", None, False),
        (f"respiratory_{prefix}_signal_to_noise", "signalToNoise", None, False),
    )
    if raw is _MISSING:
        if required:
            context.diagnostic("required_field_missing", path, material=True)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.MISSING,
                unit=unit,
                reason="parent_field_missing",
            )
            for code, field_name, unit, _ in definitions
        ]
    if raw is None:
        if required:
            context.diagnostic("required_stats_null", path, material=True)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.NULL,
                unit=unit,
                reason="parent_field_null",
            )
            for code, field_name, unit, _ in definitions
        ]
    if not isinstance(raw, Mapping):
        context.diagnostic("stats_shape_invalid", path, material=required, partial=not required)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.INVALID,
                unit=unit,
                reason="parent_shape_invalid",
            )
            for code, field_name, unit, _ in definitions
        ]
    _note_unknown_fields(raw, path, {field_name for _, field_name, _, _ in definitions}, context)
    return [
        _numeric_metric(
            code=code,
            field_path=_path(path, field_name),
            raw=raw.get(field_name, _MISSING),
            context=context,
            unit=unit,
            required=field_required,
            minimum=0,
        )
        for code, field_name, unit, field_required in definitions
    ]


def _normalize_daily_respiratory_rate(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(value, path, {"date", "breathsPerMinute"}, context)
    temporal = _date_temporal(value.get("date", _MISSING), _path(path, "date"), context)
    metric = _numeric_metric(
        code="daily_respiratory_rate_breaths_per_minute",
        field_path=_path(path, "breathsPerMinute"),
        raw=value.get("breathsPerMinute", _MISSING),
        context=context,
        unit="breaths_per_minute",
        required=True,
        minimum=0,
    )
    return _finish_record(
        stream=GoogleStream.DAILY_RESPIRATORY_RATE,
        temporal=temporal,
        external_record_id=external_record_id,
        metrics=(metric,),
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={"date": temporal.local_date.isoformat() if temporal.local_date else None},
    )


def _normalize_sleep(
    value: Mapping[str, object],
    *,
    path: str,
    external_record_id: str | None,
    data_source: GoogleDataSourceDTO,
    context: _ParseContext,
) -> GoogleRecordDTO:
    _note_unknown_fields(
        value,
        path,
        {
            "interval",
            "type",
            "stages",
            "outOfBedSegments",
            "metadata",
            "summary",
            "createTime",
            "updateTime",
        },
        context,
    )
    sleep_interval = _parse_source_interval(
        value.get("interval", _MISSING),
        _path(path, "interval"),
        context,
        interval_kind=GoogleIntervalKind.SLEEP_SESSION,
        civil_start_field="civilStartTime",
        civil_end_field="civilEndTime",
    )
    metrics: list[GoogleMetricDTO] = []
    sleep_type = _string_metric(
        code="sleep_type",
        field_path=_path(path, "type"),
        raw=value.get("type", _MISSING),
        context=context,
        allowed=_SLEEP_TYPE_VALUES,
    )
    metrics.append(sleep_type)
    metrics.extend(
        _sleep_metadata_metrics(value.get("metadata", _MISSING), _path(path, "metadata"), context)
    )
    metrics.extend(
        _sleep_summary_metrics(value.get("summary", _MISSING), _path(path, "summary"), context)
    )
    metrics.extend(
        [
            _timestamp_text_metric(
                code="sleep_create_time",
                field_path=_path(path, "createTime"),
                raw=value.get("createTime", _MISSING),
                context=context,
            ),
            _timestamp_text_metric(
                code="sleep_update_time",
                field_path=_path(path, "updateTime"),
                raw=value.get("updateTime", _MISSING),
                context=context,
            ),
        ]
    )
    metadata_external = _sleep_external_id(
        value.get("metadata", _MISSING), _path(path, "metadata"), context
    )
    effective_external = external_record_id or metadata_external
    stages_state, stages = _sleep_stages(
        value.get("stages", _MISSING), _path(path, "stages"), context
    )
    out_state, out_segments = _sleep_out_of_bed(
        value.get("outOfBedSegments", _MISSING), _path(path, "outOfBedSegments"), context
    )
    temporal = (
        sleep_interval.end
        if sleep_interval is not None
        else _empty_temporal(_path(path, "interval.endTime"), GoogleMetricState.INVALID)
    )
    return _finish_record(
        stream=GoogleStream.SLEEP,
        temporal=temporal,
        external_record_id=effective_external,
        metrics=metrics,
        status=_record_status(context),
        data_source=data_source,
        semantic_basis={
            "interval": sleep_interval.as_dict() if sleep_interval else None,
            "metrics": [metric.as_dict() for metric in metrics],
            "stages": [stage.as_dict() for stage in stages],
            "out_of_bed": [segment.as_dict() for segment in out_segments],
        },
        sleep_interval=sleep_interval,
        sleep_stages=stages,
        sleep_stages_state=stages_state,
        out_of_bed_segments=out_segments,
        out_of_bed_state=out_state,
        wake_date=(
            sleep_interval.end.local_date
            if sleep_interval is not None
            and sleep_interval.state is GoogleMetricState.VALUE
            and sleep_interval.end.state is GoogleMetricState.VALUE
            else None
        ),
    )


def _timestamp_text_metric(
    *, code: str, field_path: str, raw: object, context: _ParseContext
) -> GoogleMetricDTO:
    if raw is _MISSING:
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.MISSING,
            reason="field_missing",
        )
    if raw is None:
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.NULL,
            reason="field_null",
        )
    parsed = _parse_timestamp(raw, field_path, context, required=False)
    if parsed is None:
        return GoogleMetricDTO(
            metric_code=code,
            field_path=field_path,
            state=GoogleMetricState.INVALID,
            reason="timestamp_invalid",
        )
    return GoogleMetricDTO(
        metric_code=code,
        field_path=field_path,
        state=GoogleMetricState.VALUE,
        value_text=raw.strip() if isinstance(raw, str) else None,
    )


def _sleep_external_id(raw: object, path: str, context: _ParseContext) -> str | None:
    if raw is _MISSING or raw is None:
        return None
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("externalId", _MISSING)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not _MISSING and value is not None:
        context.diagnostic("external_id_invalid", _path(path, "externalId"), partial=True)
    return None


def _sleep_metadata_metrics(
    raw: object, path: str, context: _ParseContext
) -> list[GoogleMetricDTO]:
    definitions = (
        ("sleep_metadata_stages_status", "stagesStatus", _SLEEP_STAGE_STATUS_VALUES, False),
        ("sleep_metadata_processed", "processed", None, True),
        ("sleep_metadata_main", "main", None, True),
        ("sleep_metadata_nap", "nap", None, True),
        ("sleep_metadata_manually_edited", "manuallyEdited", None, True),
        ("sleep_metadata_external_id", "externalId", None, False),
    )
    if raw is _MISSING:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.MISSING,
                reason="parent_field_missing",
            )
            for code, field_name, _, _ in definitions
        ]
    if raw is None:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.NULL,
                reason="parent_field_null",
            )
            for code, field_name, _, _ in definitions
        ]
    if not isinstance(raw, Mapping):
        context.diagnostic("metadata_shape_invalid", path, partial=True)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.INVALID,
                reason="parent_shape_invalid",
            )
            for code, field_name, _, _ in definitions
        ]
    _note_unknown_fields(raw, path, {field_name for _, field_name, _, _ in definitions}, context)
    metrics: list[GoogleMetricDTO] = []
    for code, field_name, allowed, is_boolean in definitions:
        field_path = _path(path, field_name)
        if is_boolean:
            metrics.append(
                _boolean_metric(
                    code=code,
                    field_path=field_path,
                    raw=raw.get(field_name, _MISSING),
                    context=context,
                )
            )
        elif allowed is not None:
            metrics.append(
                _string_metric(
                    code=code,
                    field_path=field_path,
                    raw=raw.get(field_name, _MISSING),
                    context=context,
                    allowed=allowed,
                )
            )
        else:
            metrics.append(
                _string_metric(
                    code=code,
                    field_path=field_path,
                    raw=raw.get(field_name, _MISSING),
                    context=context,
                    allow_empty=False,
                )
            )
    return metrics


def _sleep_summary_metrics(raw: object, path: str, context: _ParseContext) -> list[GoogleMetricDTO]:
    summary_fields = (
        ("sleep_summary_minutes_in_sleep_period", "minutesInSleepPeriod"),
        ("sleep_summary_minutes_after_wake_up", "minutesAfterWakeUp"),
        ("sleep_summary_minutes_to_fall_asleep", "minutesToFallAsleep"),
        ("sleep_summary_minutes_asleep", "minutesAsleep"),
        ("sleep_summary_minutes_awake", "minutesAwake"),
    )
    stages_code = "sleep_summary_stages"
    if raw is _MISSING:
        return [
            *[
                GoogleMetricDTO(
                    metric_code=code,
                    field_path=_path(path, field_name),
                    state=GoogleMetricState.MISSING,
                    unit="min",
                    reason="parent_field_missing",
                )
                for code, field_name in summary_fields
            ],
            GoogleMetricDTO(
                metric_code=stages_code,
                field_path=_path(path, "stagesSummary"),
                state=GoogleMetricState.MISSING,
                reason="parent_field_missing",
            ),
        ]
    if raw is None:
        return [
            *[
                GoogleMetricDTO(
                    metric_code=code,
                    field_path=_path(path, field_name),
                    state=GoogleMetricState.NULL,
                    unit="min",
                    reason="parent_field_null",
                )
                for code, field_name in summary_fields
            ],
            GoogleMetricDTO(
                metric_code=stages_code,
                field_path=_path(path, "stagesSummary"),
                state=GoogleMetricState.NULL,
                reason="parent_field_null",
            ),
        ]
    if not isinstance(raw, Mapping):
        context.diagnostic("summary_shape_invalid", path, partial=True)
        return [
            *[
                GoogleMetricDTO(
                    metric_code=code,
                    field_path=_path(path, field_name),
                    state=GoogleMetricState.INVALID,
                    unit="min",
                    reason="parent_shape_invalid",
                )
                for code, field_name in summary_fields
            ],
            GoogleMetricDTO(
                metric_code=stages_code,
                field_path=_path(path, "stagesSummary"),
                state=GoogleMetricState.INVALID,
                reason="parent_shape_invalid",
            ),
        ]
    _note_unknown_fields(
        raw, path, {field_name for _, field_name in summary_fields} | {"stagesSummary"}, context
    )
    metrics = [
        _numeric_metric(
            code=code,
            field_path=_path(path, field_name),
            raw=raw.get(field_name, _MISSING),
            context=context,
            unit="min",
            integer=True,
        )
        for code, field_name in summary_fields
    ]
    stages_raw = raw.get("stagesSummary", _MISSING)
    stage_path = _path(path, "stagesSummary")
    if stages_raw is _MISSING:
        metrics.append(
            GoogleMetricDTO(
                metric_code=stages_code,
                field_path=stage_path,
                state=GoogleMetricState.MISSING,
                reason="field_missing",
            )
        )
    elif stages_raw is None:
        metrics.append(
            GoogleMetricDTO(
                metric_code=stages_code,
                field_path=stage_path,
                state=GoogleMetricState.NULL,
                reason="field_null",
            )
        )
    elif not isinstance(stages_raw, list) or len(stages_raw) > MAX_NESTED_FIELDS:
        context.diagnostic("summary_stages_shape_invalid", stage_path, partial=True)
        metrics.append(
            GoogleMetricDTO(
                metric_code=stages_code,
                field_path=stage_path,
                state=GoogleMetricState.INVALID,
                reason="collection_shape_invalid",
            )
        )
    else:
        normalized_stages: list[dict[str, object]] = []
        for index, item in enumerate(stages_raw):
            item_path = f"{stage_path}[{index}]"
            if not isinstance(item, Mapping):
                context.diagnostic("summary_stage_shape_invalid", item_path, partial=True)
                continue
            _note_unknown_fields(item, item_path, {"type", "minutes", "count"}, context)
            stage_type = item.get("type", _MISSING)
            minutes = _parse_number(item.get("minutes", _MISSING), integer=True)
            count = _parse_number(item.get("count", _MISSING), integer=True)
            if (
                not isinstance(stage_type, str)
                or stage_type not in _SLEEP_STAGE_VALUES
                or minutes is None
                or count is None
            ):
                context.diagnostic("summary_stage_value_invalid", item_path, partial=True)
                continue
            normalized_stages.append(
                {"type": stage_type, "minutes": int(minutes), "count": int(count)}
            )
        if len(normalized_stages) != len(stages_raw):
            metrics.append(
                GoogleMetricDTO(
                    metric_code=stages_code,
                    field_path=stage_path,
                    state=GoogleMetricState.INVALID,
                    reason="collection_value_invalid",
                )
            )
        else:
            metrics.append(
                GoogleMetricDTO(
                    metric_code=stages_code,
                    field_path=stage_path,
                    state=GoogleMetricState.VALUE,
                    collection_json=canonical_json(normalized_stages),
                )
            )
    return metrics


def _sleep_stages(
    raw: object, path: str, context: _ParseContext
) -> tuple[GoogleMetricState, tuple[GoogleSleepStageDTO, ...]]:
    if raw is _MISSING:
        return GoogleMetricState.MISSING, ()
    if raw is None:
        return GoogleMetricState.NULL, ()
    if not isinstance(raw, list) or len(raw) > MAX_NESTED_FIELDS:
        context.diagnostic("sleep_stages_shape_invalid", path, material=True)
        return GoogleMetricState.INVALID, ()
    values: list[GoogleSleepStageDTO] = []
    invalid = False
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        if not isinstance(item, Mapping):
            context.diagnostic("sleep_stage_shape_invalid", item_path, material=True)
            invalid = True
            continue
        _note_unknown_fields(
            item,
            item_path,
            {
                "startTime",
                "startUtcOffset",
                "endTime",
                "endUtcOffset",
                "type",
                "createTime",
                "updateTime",
            },
            context,
        )
        start = _interval_endpoint(
            item,
            item_path,
            context,
            endpoint="start",
            time_field="startTime",
            offset_field="startUtcOffset",
            civil_field=None,
        )
        end = _interval_endpoint(
            item,
            item_path,
            context,
            endpoint="end",
            time_field="endTime",
            offset_field="endUtcOffset",
            civil_field=None,
        )
        stage_type = item.get("type", _MISSING)
        if not isinstance(stage_type, str) or stage_type not in _SLEEP_STAGE_VALUES:
            context.diagnostic("sleep_stage_type_invalid", _path(item_path, "type"), material=True)
            invalid = True
            continue
        if start.state is not GoogleMetricState.VALUE or end.state is not GoogleMetricState.VALUE:
            invalid = True
            continue
        if (
            start.measured_at_utc is None
            or end.measured_at_utc is None
            or end.measured_at_utc <= start.measured_at_utc
        ):
            context.diagnostic("sleep_stage_interval_invalid", item_path, material=True)
            invalid = True
            continue
        create_time = _optional_timestamp_text(
            item.get("createTime", _MISSING), _path(item_path, "createTime"), context
        )
        update_time = _optional_timestamp_text(
            item.get("updateTime", _MISSING), _path(item_path, "updateTime"), context
        )
        values.append(
            GoogleSleepStageDTO(
                ordinal=index,
                stage_type=stage_type,
                start=start,
                end=end,
                create_time=create_time,
                update_time=update_time,
            )
        )
    values.sort(
        key=lambda item: (
            item.start.measured_at_utc or datetime.max.replace(tzinfo=UTC),
            item.stage_type,
        )
    )
    values = [replace(item, ordinal=index) for index, item in enumerate(values)]
    return GoogleMetricState.INVALID if invalid else GoogleMetricState.VALUE, tuple(values)


def _optional_timestamp_text(raw: object, path: str, context: _ParseContext) -> str | None:
    if raw is _MISSING or raw is None:
        return None
    parsed = _parse_timestamp(raw, path, context, required=False)
    return raw.strip() if parsed is not None and isinstance(raw, str) else None


def _sleep_out_of_bed(
    raw: object, path: str, context: _ParseContext
) -> tuple[GoogleMetricState, tuple[GoogleIntervalDTO, ...]]:
    if raw is _MISSING:
        return GoogleMetricState.MISSING, ()
    if raw is None:
        return GoogleMetricState.NULL, ()
    if not isinstance(raw, list) or len(raw) > MAX_NESTED_FIELDS:
        context.diagnostic("out_of_bed_shape_invalid", path, material=True)
        return GoogleMetricState.INVALID, ()
    values: list[GoogleIntervalDTO] = []
    invalid = False
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        interval = _parse_source_interval(
            item,
            item_path,
            context,
            interval_kind=GoogleIntervalKind.SLEEP_OUT_OF_BED,
            civil_start_field=None,
            civil_end_field=None,
        )
        if interval is not None:
            values.append(interval)
            invalid = invalid or interval.state is not GoogleMetricState.VALUE
    values.sort(
        key=lambda item: (
            item.start.measured_at_utc or datetime.max.replace(tzinfo=UTC),
            item.end.measured_at_utc or datetime.max.replace(tzinfo=UTC),
        )
    )
    return GoogleMetricState.INVALID if invalid else GoogleMetricState.VALUE, tuple(values)


def _normalize_heart_rate_rollup(
    item: Mapping[str, object],
    *,
    query: GoogleQueryContext,
    path: str,
    context: _ParseContext,
) -> GoogleRecordDTO:
    is_daily = query.query_mode is GoogleQueryMode.DAILY_ROLL_UP
    if is_daily:
        known = {"civilStartTime", "civilEndTime", "heartRate"}
        start = _civil_temporal(
            item.get("civilStartTime", _MISSING), _path(path, "civilStartTime"), context
        )
        end = _civil_temporal(
            item.get("civilEndTime", _MISSING), _path(path, "civilEndTime"), context
        )
        interval_kind = GoogleIntervalKind.DAILY_ROLL_UP
    else:
        known = {"startTime", "endTime", "heartRate"}
        start = _physical_temporal(
            item.get("startTime", _MISSING), _path(path, "startTime"), context
        )
        end = _physical_temporal(item.get("endTime", _MISSING), _path(path, "endTime"), context)
        interval_kind = GoogleIntervalKind.ROLL_UP
    unexpected_union = [key for key in item if key not in known]
    if unexpected_union:
        for key in unexpected_union:
            context.unknown(_path(path, key), key, "unsupported_data_type")
        context.diagnostic(
            "data_type_union_multiple"
            if len(unexpected_union) > 1 or "heartRate" in item
            else "data_type_union_unsupported",
            path,
            material=True,
        )
        return _invalid_record(item, stream=GoogleStream.HEART_RATE, path=path, context=context)
    interval_state = GoogleMetricState.VALUE
    if start.state is not GoogleMetricState.VALUE or end.state is not GoogleMetricState.VALUE:
        interval_state = GoogleMetricState.INVALID
    if start.state is GoogleMetricState.VALUE and end.state is GoogleMetricState.VALUE:
        if (
            start.measured_at_utc is not None
            and end.measured_at_utc is not None
            and end.measured_at_utc <= start.measured_at_utc
        ):
            context.diagnostic("interval_order_invalid", path, material=True)
            interval_state = GoogleMetricState.INVALID
        elif (
            start.local_date is not None
            and end.local_date is not None
            and start.precision is GoogleTemporalPrecision.LOCAL
            and end.precision is GoogleTemporalPrecision.LOCAL
            and end.local_wall_time <= start.local_wall_time
        ):
            context.diagnostic("interval_order_invalid", path, material=True)
            interval_state = GoogleMetricState.INVALID
    interval = GoogleIntervalDTO(
        start=start,
        end=end,
        interval_kind=interval_kind,
        state=interval_state,
    )
    metrics = _heart_rate_rollup_metrics(
        item.get("heartRate", _MISSING), _path(path, "heartRate"), context
    )
    status = _record_status(context)
    return _finish_record(
        stream=GoogleStream.HEART_RATE,
        temporal=start,
        external_record_id=None,
        metrics=metrics,
        status=status,
        data_source=GoogleDataSourceDTO(state=GoogleMetricState.MISSING),
        semantic_basis={
            "start": start.as_dict(),
            "end": end.as_dict(),
            "kind": interval_kind.value,
        },
        interval=interval,
    )


def _heart_rate_rollup_metrics(
    raw: object, path: str, context: _ParseContext
) -> list[GoogleMetricDTO]:
    definitions = (
        ("heart_rate_bpm_avg", "beatsPerMinuteAvg"),
        ("heart_rate_bpm_max", "beatsPerMinuteMax"),
        ("heart_rate_bpm_min", "beatsPerMinuteMin"),
    )
    if raw is _MISSING:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.MISSING,
                unit="bpm",
                reason="rollup_value_missing",
            )
            for code, field_name in definitions
        ]
    if raw is None:
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.NULL,
                unit="bpm",
                reason="rollup_value_null",
            )
            for code, field_name in definitions
        ]
    if not isinstance(raw, Mapping):
        context.diagnostic("rollup_value_shape_invalid", path, material=True)
        return [
            GoogleMetricDTO(
                metric_code=code,
                field_path=_path(path, field_name),
                state=GoogleMetricState.INVALID,
                unit="bpm",
                reason="rollup_value_shape_invalid",
            )
            for code, field_name in definitions
        ]
    _note_unknown_fields(raw, path, {field_name for _, field_name in definitions}, context)
    return [
        _numeric_metric(
            code=code,
            field_path=_path(path, field_name),
            raw=raw.get(field_name, _MISSING),
            context=context,
            unit="bpm",
            integer=False,
        )
        for code, field_name in definitions
    ]


_DIAGNOSTIC_MESSAGES = {
    "payload_json_invalid": "Google response JSON is invalid",
    "payload_shape_invalid": "Google response must be an object",
    "response_collection_missing": "Google response collection is missing",
    "response_collection_shape": "Google response collection has an incompatible shape",
    "response_record_limit_exceeded": "Google response exceeds the bounded normalization limit",
    "record_shape_drift": "Google data point is not an object",
    "unsupported_query_mode": "Google query mode is not supported for this R04 type",
    "data_type_union_missing": "The expected Google data type union member is missing",
    "data_type_union_multiple": "Google data point contains multiple data type union members",
    "data_type_union_unsupported": "Google rollup contains an unsupported data type union member",
    "data_type_component_shape": "Google data type component has an incompatible shape",
    "record_identity_conflict": "Google data point identifiers conflict",
    "record_identity_invalid": "Google data point identifier is invalid",
    "source_attribution_invalid": "Google device attribution lacks accepted provider evidence",
    "source_identity_conflict": "Google source identity conflicts with point-level source evidence",
    "required_field_missing": "A required Google field is missing",
    "required_field_null": "A required Google field is explicitly null",
    "field_string_invalid": "Google string field has an incompatible shape",
    "field_enum_unknown": "Google enum field has an unsupported value",
    "field_boolean_invalid": "Google boolean field has an incompatible shape",
    "numeric_value_invalid": "Google numeric field is malformed or non-finite",
    "numeric_range_invalid": "Google numeric field is outside its documented range",
    "data_source_shape_invalid": "Google data-source evidence has an incompatible shape",
    "data_source_nested_shape_invalid": (
        "Google nested data-source evidence has an incompatible shape"
    ),
    "metadata_shape_invalid": "Google metadata has an incompatible shape",
    "timestamp_invalid": "Google timestamp is not a valid RFC3339 instant",
    "required_timestamp_missing": "A required Google timestamp is missing",
    "required_timestamp_null": "A required Google timestamp is explicitly null",
    "offset_invalid": "Google UTC offset is not a whole-minute Duration in range",
    "required_offset_missing": "A required Google UTC offset is missing",
    "required_offset_null": "A required Google UTC offset is explicitly null",
    "date_shape_invalid": "Google date has an incompatible shape",
    "date_partial_not_supported": "Google date is partial and cannot identify a R04 local date",
    "date_invalid": "Google date is not a valid Gregorian date",
    "required_date_missing": "A required Google date is missing",
    "required_date_null": "A required Google date is explicitly null",
    "civil_time_shape_invalid": "Google civil time has an incompatible shape",
    "civil_time_invalid": "Google civil time is invalid",
    "required_civil_time_missing": "A required Google civil time is missing",
    "required_civil_time_null": "A required Google civil time is explicitly null",
    "interval_shape_invalid": "Google interval has an incompatible shape",
    "required_interval_missing": "A required Google interval is missing",
    "required_interval_null": "A required Google interval is explicitly null",
    "interval_order_invalid": "Google interval end is not after its start",
    "daily_hrv_value_missing": "Google daily HRV has no set value field",
    "summary_shape_invalid": "Google sleep summary has an incompatible shape",
    "summary_stages_shape_invalid": "Google sleep stage summary has an incompatible shape",
    "summary_stage_shape_invalid": "Google sleep stage summary item is not an object",
    "summary_stage_value_invalid": "Google sleep stage summary item is invalid",
    "sleep_stages_shape_invalid": "Google sleep stages collection has an incompatible shape",
    "sleep_stage_shape_invalid": "Google sleep stage item is not an object",
    "sleep_stage_type_invalid": "Google sleep stage type is invalid",
    "sleep_stage_interval_invalid": "Google sleep stage interval is invalid",
    "external_id_invalid": "Google sleep externalId is invalid",
    "out_of_bed_shape_invalid": "Google out-of-bed collection has an incompatible shape",
    "required_stats_null": "Required Google respiratory statistics are explicitly null",
    "stats_shape_invalid": "Google respiratory statistics have an incompatible shape",
    "next_page_token_invalid": "Google pagination token has an incompatible shape",
    "rollup_value_shape_invalid": "Google heart-rate rollup value has an incompatible shape",
}


__all__ = [
    "GOOGLE_NORMALIZATION_CONTRACT_VERSION",
    "MAX_DIAGNOSTICS",
    "MAX_NORMALIZATION_RECORDS",
    "MAX_UNKNOWN_FIELDS",
    "NORMALIZATION_CONTRACT_VERSION",
    "GoogleNormalizationDiagnostic",
    "GoogleNormalizationResult",
    "google_normalize",
    "normalize_google_payload",
    "normalize_google_response",
]
