"""Value-free shape inspection for owner-controlled Garmin responses.

This module intentionally does not preserve provider values.  It can inspect a
live response in memory and return only types, statically allowlisted field
paths, bounded counts, presence states, and coarse device-attribution
evidence.  Unknown or dynamic provider keys are aggregated as redacted fields.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

REDACTION_CONTRACT_VERSION = "r02-garmin-redaction-v1"
MAX_SHAPE_NODES = 512
MAX_ARRAY_ITEMS = 64
MAX_MAPPING_FIELDS = 64
MAX_ATTRIBUTION_NODES = 512

_SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_SENSITIVE_KEY_TERMS = (
    "access_token",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "email",
    "jwt",
    "password",
    "refresh_token",
    "secret",
    "session",
    "token",
    "username",
    "profile",
    "serial",
    "uuid",
    "guid",
    "route",
    "polyline",
    "coordinate",
    "latitude",
    "longitude",
    "address",
    "notes",
    "description",
    "timestamp",
    "activityname",
    "devicename",
    "fullname",
)
_IDENTIFIER_KEY_NAMES = frozenset(
    {
        "id",
        "userid",
        "userprofileid",
        "activityid",
        "deviceid",
        "metricid",
        "sourceid",
        "recordid",
        "gearid",
        "workoutid",
    }
)
_DEVICE_KEY_NAMES = frozenset(
    {
        "device",
        "deviceinfo",
        "deviceattributed",
        "isdeviceattributed",
        "devicemodel",
        "devicemodelname",
        "devicetype",
        "devicemanufacturer",
        "sourcedevice",
    }
)
_DEVICE_MODEL_KEY_NAMES = frozenset(
    {
        "model",
        "modelname",
        "devicemodel",
        "devicemodelname",
        "devicetype",
        "devicemanufacturer",
        "manufacturer",
    }
)
_DEVICE_IDENTIFIER_KEY_NAMES = frozenset(
    {"deviceid", "deviceuuid", "deviceidentifier", "sourcedeviceid"}
)
_TARGET_DEVICE_MARKERS = ("vivoactive5", "vivoactive_5", "vivoactive 5")
_OTHER_DEVICE_MARKERS = (
    "forerunner",
    "venu",
    "fenix",
    "edge",
    "instinct",
    "lily",
    "descent",
    "epix",
    "marq",
    "tactix",
)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


# This is deliberately a closed set.  It is shared by the probe's expected
# metric contracts and the optional shape export so a provider-added key can
# never become output merely because it passes a spelling heuristic.
GARMIN_SAFE_FIELD_PATHS = frozenset(
    {
        "calendarDate",
        "userActivitySummary",
        "sleepTimeSeconds",
        "sleepScore",
        "sleepScore.value",
        "levels",
        "napTimeSeconds",
        "napEvents",
        "heartRateValues",
        "heartRateValue",
        "heartRate",
        "heartRateBpm",
        "timeOffset",
        "restingHeartRate",
        "hrvStatus",
        "hrvStatus.weeklyAverage",
        "hrvStatus.status",
        "stressValues",
        "stress",
        "stressLevel",
        "bodyBatteryChargedValue",
        "bodyBatteryDrainedValue",
        "bodyBatteryLevel",
        "bodyBattery",
        "spo2Values",
        "spo2",
        "spo2Percent",
        "respirationValues",
        "respiration",
        "respirationRate",
        "maxMetrics",
        "maxMetrics.vo2MaxRunning",
        "vo2Max",
        "vo2MaxRunning",
        "trainingReadiness",
        "trainingReadiness.value",
        "trainingStatus",
        "trainingStatus.value",
        "score",
        "trainingEffect",
        "trainingLoad",
        "acuteTrainingLoad",
        "activities",
        "activities.activityType",
        "activities.durationSeconds",
        "activities.distanceMeters",
        "activities.duration",
        "activities.distance",
        "activities.metrics",
        "activities.metrics.speedMps",
        "activities.metrics.heartRateBpm",
        "activities.metrics.cadenceRpm",
        "activities.metrics.powerWatts",
        "activities.metrics.cyclingDynamics",
        "activityType",
        "durationSeconds",
        "distanceMeters",
        "duration",
        "distance",
        "metrics",
        "metrics.speedMps",
        "metrics.heartRateBpm",
        "metrics.cadenceRpm",
        "metrics.powerWatts",
        "metrics.cyclingDynamics",
        "speed",
        "cadence",
        "power",
        "cyclingDynamics",
        "device",
        "device.model",
        "sourceDevice",
        "sourceDevice.model",
        "fitRecords",
        "fitRecords.recoveryTimeSeconds",
        "fitRecords.0.recoveryTimeSeconds",
        "recoveryTimeSeconds",
        "recoveryTime",
    }
)
_SAFE_PATH_KEYS = frozenset(
    tuple(_normalize_key(part) for part in path.split(".") if part != "[]")
    for path in GARMIN_SAFE_FIELD_PATHS
)


class GarminValueState(StrEnum):
    """Coarse state that never includes the value itself."""

    PRESENT = "present"
    EMPTY = "empty"
    NULL = "null"
    MISSING = "missing"
    UNKNOWN = "unknown"


class GarminDeviceAttribution(StrEnum):
    """Evidence level for target-device attribution in one response."""

    TARGET_DEVICE = "target_device"
    OTHER_DEVICE = "other_device"
    MIXED = "mixed"
    UNATTRIBUTED = "unattributed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GarminPayloadShape:
    """Sanitized structural summary of one provider response."""

    root_shape: str
    value_state: GarminValueState
    item_count: int | None
    field_paths: tuple[str, ...]
    shape_counts: tuple[tuple[str, int], ...]
    redacted_field_count: int
    truncated: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "root_shape": self.root_shape,
            "value_state": self.value_state.value,
            "item_count": self.item_count,
            "field_paths": list(self.field_paths),
            "shape_counts": {key: count for key, count in self.shape_counts},
            "redacted_field_count": self.redacted_field_count,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class GarminDeviceAttributionEvidence:
    """Coarse attribution result without returning any identity value."""

    status: GarminDeviceAttribution
    evidence_kind: str

    def as_dict(self) -> dict[str, str]:
        return {"status": self.status.value, "evidence_kind": self.evidence_kind}


def summarize_garmin_payload(
    value: Any,
    *,
    max_nodes: int = MAX_SHAPE_NODES,
    max_array_items: int = MAX_ARRAY_ITEMS,
) -> GarminPayloadShape:
    """Return a bounded, deterministic shape summary with no raw values."""

    if max_nodes < 1 or max_array_items < 1:
        raise ValueError("shape limits must be positive")
    shape_counts: Counter[str] = Counter()
    field_paths: set[str] = set()
    redacted_field_count = 0
    visited = 0
    truncated = False

    def walk(current: Any, path: str = "") -> None:
        nonlocal redacted_field_count, visited, truncated
        if visited >= max_nodes:
            truncated = True
            return
        visited += 1
        shape = _shape_name(current)
        shape_counts[shape] += 1
        if path and _is_allowlisted_path(path):
            field_paths.add(path)
        if isinstance(current, Mapping):
            entries, has_more = _bounded_mapping_items(current)
            truncated = truncated or has_more
            entries.sort(key=lambda item: str(item[0]))
            for key, nested in entries:
                if visited >= max_nodes:
                    truncated = True
                    break
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _safe_key(key_text, child_path) is None:
                    redacted_field_count += 1
                    continue
                walk(nested, child_path)
        elif _is_sequence(current):
            iterator = iter(current)
            for _ in range(max_array_items):
                try:
                    nested = next(iterator)
                except StopIteration:
                    break
                walk(nested, f"{path}[]" if path else "[]")
            length = _sequence_length(current)
            if length is not None and length > max_array_items:
                truncated = True

    walk(value)
    item_count = _sequence_length(value) if _is_sequence(value) else None
    return GarminPayloadShape(
        root_shape=_shape_name(value),
        value_state=garmin_value_state(value),
        item_count=item_count,
        field_paths=tuple(sorted(field_paths)),
        shape_counts=tuple(sorted(shape_counts.items())),
        redacted_field_count=redacted_field_count,
        truncated=truncated,
    )


def garmin_value_state(value: Any) -> GarminValueState:
    """Classify presence without treating numeric zero as empty."""

    if value is None:
        return GarminValueState.NULL
    if isinstance(value, Mapping | Sequence) and not isinstance(value, (str, bytes, bytearray)):
        length = _sequence_length(value)
        return GarminValueState.EMPTY if length == 0 else GarminValueState.PRESENT
    if isinstance(value, (bytes, bytearray, str)) and len(value) == 0:
        return GarminValueState.EMPTY
    return GarminValueState.PRESENT


def field_state_at_path(
    value: Any,
    path: str,
    *,
    max_array_items: int = MAX_ARRAY_ITEMS,
) -> GarminValueState:
    """Read a dotted field path and return only its presence state."""

    if not isinstance(path, str) or not path.strip():
        raise ValueError("field path is required")
    if max_array_items < 1:
        raise ValueError("field state limits must be positive")
    return _field_state_at_segments(value, tuple(path.split(".")), max_array_items)


def _field_state_at_segments(
    value: Any,
    segments: tuple[str, ...],
    max_array_items: int,
) -> GarminValueState:
    if not segments:
        return garmin_value_state(value)
    if isinstance(value, Mapping):
        segment = segments[0]
        if segment not in value:
            return GarminValueState.MISSING
        return _field_state_at_segments(value[segment], segments[1:], max_array_items)
    if _is_sequence(value):
        if segments[0].isdigit():
            index = int(segments[0])
            if index >= max_array_items:
                return GarminValueState.UNKNOWN
            iterator = iter(value)
            for current_index in range(index + 1):
                try:
                    item = next(iterator)
                except StopIteration:
                    return GarminValueState.MISSING
                if current_index == index:
                    return _field_state_at_segments(item, segments[1:], max_array_items)
            return GarminValueState.MISSING
        states: list[GarminValueState] = []
        iterator = iter(value)
        for _ in range(max_array_items):
            try:
                item = next(iterator)
            except StopIteration:
                break
            states.append(_field_state_at_segments(item, segments, max_array_items))
        if not states:
            return GarminValueState.EMPTY
        return _combine_field_states(states)
    return GarminValueState.MISSING


def _combine_field_states(states: Sequence[GarminValueState]) -> GarminValueState:
    unique = set(states)
    if GarminValueState.PRESENT in unique:
        return GarminValueState.PRESENT
    if len(unique) == 1:
        return states[0]
    return GarminValueState.UNKNOWN


def field_state_counts(
    value: Any,
    paths: Sequence[str],
    *,
    max_array_items: int = MAX_ARRAY_ITEMS,
) -> dict[str, int]:
    """Return deterministic counts for expected paths, never their values."""

    counts: Counter[str] = Counter()
    for path in sorted(set(paths)):
        counts[field_state_at_path(value, path, max_array_items=max_array_items).value] += 1
    return {key: counts[key] for key in sorted(counts)}


def infer_device_attribution(
    value: Any,
    *,
    max_array_items: int = MAX_ARRAY_ITEMS,
) -> GarminDeviceAttributionEvidence:
    """Infer only coarse target/other/mixed/unknown attribution evidence."""

    has_device_field = False
    has_opaque_device_field = False
    explicit_unattributed = False
    target_found = False
    other_found = False
    visited = 0
    traversal_truncated = False

    def record_marker(nested: Any) -> None:
        nonlocal has_opaque_device_field, target_found, other_found
        if isinstance(nested, bool) or not isinstance(nested, (str, int, float)):
            has_opaque_device_field = True
            return
        text = _normalize_marker_text(str(nested))
        target = any(_normalize_marker_text(marker) in text for marker in _TARGET_DEVICE_MARKERS)
        other = any(_normalize_marker_text(marker) in text for marker in _OTHER_DEVICE_MARKERS)
        target_found = target_found or target
        other_found = other_found or other
        if not target and not other:
            has_opaque_device_field = True

    if max_array_items < 1:
        raise ValueError("attribution limits must be positive")

    def inspect(current: Any, device_context: bool = False) -> None:
        nonlocal has_device_field, has_opaque_device_field, explicit_unattributed
        nonlocal visited, traversal_truncated
        if visited >= MAX_ATTRIBUTION_NODES:
            traversal_truncated = True
            return
        visited += 1
        if isinstance(current, Mapping):
            entries, has_more = _bounded_mapping_items(current)
            traversal_truncated = traversal_truncated or has_more
            for key, nested in entries:
                normalized = _normalize_key(str(key))
                is_device_key = normalized not in _DEVICE_IDENTIFIER_KEY_NAMES and (
                    normalized in _DEVICE_KEY_NAMES or "device" in normalized
                )
                if is_device_key:
                    has_device_field = True
                    if normalized in {"deviceattributed", "isdeviceattributed"}:
                        if nested is False:
                            explicit_unattributed = True
                        elif nested is True:
                            has_opaque_device_field = True
                        continue
                    if isinstance(nested, (str, int, float)) and not isinstance(nested, bool):
                        record_marker(nested)
                    elif nested is None or _is_empty_container(nested):
                        has_opaque_device_field = True
                    inspect(nested, True)
                elif device_context and (
                    normalized in _DEVICE_MODEL_KEY_NAMES or "model" in normalized
                ):
                    record_marker(nested)
                elif isinstance(nested, (Mapping, Sequence)) and not isinstance(
                    nested, (str, bytes, bytearray)
                ):
                    inspect(nested, device_context)
        elif _is_sequence(current):
            length = _sequence_length(current)
            if length is not None and length > max_array_items:
                traversal_truncated = True
            iterator = iter(current)
            for _ in range(max_array_items):
                try:
                    nested = next(iterator)
                except StopIteration:
                    break
                inspect(nested, device_context)

    inspect(value)
    if traversal_truncated:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.UNKNOWN,
            "attribution_traversal_bounded",
        )
    if target_found and other_found:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.MIXED,
            "mixed_device_models",
        )
    if (target_found or other_found) and (explicit_unattributed or has_opaque_device_field):
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.UNKNOWN,
            "device_attribution_unresolved",
        )
    if target_found:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.TARGET_DEVICE,
            "explicit_target_model",
        )
    if other_found:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.OTHER_DEVICE,
            "explicit_other_model",
        )
    if explicit_unattributed:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.UNATTRIBUTED,
            "explicit_unattributed",
        )
    if has_opaque_device_field:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.UNKNOWN,
            "device_field_without_safe_model",
        )
    if has_device_field:
        return GarminDeviceAttributionEvidence(
            GarminDeviceAttribution.UNKNOWN,
            "device_field_unresolved",
        )
    return GarminDeviceAttributionEvidence(
        GarminDeviceAttribution.UNATTRIBUTED,
        "no_device_attribution_field",
    )


def redact_garmin_payload(
    value: Any,
    *,
    max_nodes: int = MAX_SHAPE_NODES,
    max_array_items: int = MAX_ARRAY_ITEMS,
) -> dict[str, Any]:
    """Convert a raw response into a value-free allowlisted shape document."""

    if max_nodes < 1 or max_array_items < 1:
        raise ValueError("redaction limits must be positive")
    return {
        "redaction_contract_version": REDACTION_CONTRACT_VERSION,
        "payload": _redact_node(
            value,
            max_array_items=max_array_items,
            remaining_nodes=[max_nodes],
        ),
    }


def validate_external_export_paths(
    input_path: str | Path,
    output_path: str | Path,
) -> tuple[Path, Path]:
    """Validate raw-input and sanitized-output paths before file I/O."""

    source = _validate_external_file_path(input_path)
    target = _validate_external_file_path(output_path)
    if source == target:
        raise ValueError("redaction input and output must differ")
    return source, target


def _redact_node(
    value: Any,
    *,
    max_array_items: int,
    remaining_nodes: list[int],
    path: str = "",
) -> dict[str, Any]:
    shape = _shape_name(value)
    if remaining_nodes[0] < 1:
        return {"type": shape, "truncated": True}
    remaining_nodes[0] -= 1
    if isinstance(value, Mapping):
        fields: list[dict[str, Any]] = []
        redacted = 0
        truncated = False
        entries, has_more = _bounded_mapping_items(value)
        truncated = has_more
        entries.sort(key=lambda item: str(item[0]))
        for key, nested in entries:
            if remaining_nodes[0] < 1:
                truncated = True
                break
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _safe_key(key_text, child_path) is None:
                redacted += 1
                continue
            child_shape = _redact_node(
                nested,
                max_array_items=max_array_items,
                remaining_nodes=remaining_nodes,
                path=child_path,
            )
            fields.append({"key": key_text, "shape": child_shape})
            truncated = truncated or bool(child_shape.get("truncated"))
        result: dict[str, Any] = {
            "type": shape,
            "field_count": _sequence_length(value),
            "redacted_field_count": redacted,
            "fields": fields,
        }
        if truncated:
            result["truncated"] = True
        return result
    if _is_sequence(value):
        redacted_items: list[dict[str, Any]] = []
        iterator = iter(value)
        truncated = False
        for _ in range(max_array_items):
            try:
                item = next(iterator)
            except StopIteration:
                break
            if remaining_nodes[0] < 1:
                truncated = True
                break
            child_shape = _redact_node(
                item,
                max_array_items=max_array_items,
                remaining_nodes=remaining_nodes,
                path=f"{path}[]" if path else "[]",
            )
            redacted_items.append(child_shape)
            truncated = truncated or bool(child_shape.get("truncated"))
        length = _sequence_length(value)
        if length is not None and length > max_array_items:
            truncated = True
        return {
            "type": shape,
            "item_count": _sequence_length(value),
            "items": redacted_items,
            "truncated": truncated,
        }
    if isinstance(value, (bytes, bytearray)):
        return {"type": shape, "byte_count": len(value)}
    return {"type": shape}


def _bounded_mapping_items(value: Mapping[Any, Any]) -> tuple[list[tuple[Any, Any]], bool]:
    iterator = iter(value.items())
    entries: list[tuple[Any, Any]] = []
    for _ in range(MAX_MAPPING_FIELDS):
        try:
            entries.append(next(iterator))
        except StopIteration:
            return entries, False
    try:
        next(iterator)
    except StopIteration:
        return entries, False
    return entries, True


def _sequence_length(value: Any) -> int | None:
    try:
        return len(value)
    except (TypeError, ValueError):
        return None


def _normalize_marker_text(value: str) -> str:
    return re.sub(r"[-_\s]", "", value.casefold())


def _path_key(value: str) -> tuple[str, ...]:
    return tuple(_normalize_key(part) for part in value.split(".") if part != "[]")


def _is_allowlisted_path(value: str) -> bool:
    return _path_key(value) in _SAFE_PATH_KEYS


def _validate_external_file_path(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise ValueError("redaction paths must be absolute")
    for candidate in (raw, *raw.parents):
        if candidate.is_symlink():
            raise ValueError("redaction paths must not use symlinks")
    if raw.exists() and not raw.is_file():
        raise ValueError("redaction paths must be regular files")
    resolved = raw.resolve()
    try:
        resolved.relative_to(_repository_root())
    except ValueError:
        return resolved
    raise ValueError("redaction paths must be outside the checkout")


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Health-Check checkout root could not be determined")


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalize_key(value)
    if not normalized:
        return True
    if normalized in _IDENTIFIER_KEY_NAMES:
        return True
    if normalized.endswith(("id", "identifier")):
        return True
    if normalized.endswith(("uuid", "guid", "serialnumber", "serialno")):
        return True
    return any(term.replace("_", "") in normalized for term in _SENSITIVE_KEY_TERMS)


def _safe_key(value: str, path: str) -> str | None:
    if not _SAFE_KEY_RE.fullmatch(value) or _is_sensitive_key(value):
        return None
    if not _is_allowlisted_path(path):
        return None
    return value


def _is_empty_container(value: Any) -> bool:
    if isinstance(value, Mapping | Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _sequence_length(value) == 0
    return False


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _shape_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    if _is_sequence(value):
        return "array"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "other"


__all__ = [
    "GARMIN_SAFE_FIELD_PATHS",
    "GarminDeviceAttribution",
    "GarminDeviceAttributionEvidence",
    "GarminPayloadShape",
    "GarminValueState",
    "MAX_ARRAY_ITEMS",
    "MAX_MAPPING_FIELDS",
    "MAX_SHAPE_NODES",
    "REDACTION_CONTRACT_VERSION",
    "field_state_at_path",
    "field_state_counts",
    "garmin_value_state",
    "infer_device_attribution",
    "redact_garmin_payload",
    "summarize_garmin_payload",
    "validate_external_export_paths",
]
