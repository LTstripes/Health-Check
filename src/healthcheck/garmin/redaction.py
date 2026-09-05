"""Value-free shape inspection for owner-controlled Garmin responses.

This module intentionally does not preserve provider values.  It can inspect a
live response in memory and return only types, safe field paths, bounded
counts, presence states, and coarse device-attribution evidence.  The same
shape transformer is used by the optional owner export helper before a file
is shared with an Integrator or reviewer.
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
        "devicename",
        "sourcedevice",
        "source",
    }
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
        if path:
            field_paths.add(path)
        if isinstance(current, Mapping):
            items = sorted(current.items(), key=lambda item: str(item[0]))
            for key, nested in items:
                key_text = str(key)
                if _is_sensitive_key(key_text):
                    redacted_field_count += 1
                    continue
                segment = _safe_key(key_text)
                if segment is None:
                    redacted_field_count += 1
                    continue
                child_path = f"{path}.{segment}" if path else segment
                walk(nested, child_path)
        elif _is_sequence(current):
            for nested in list(current)[:max_array_items]:
                walk(nested, f"{path}[]" if path else "[]")
            if len(current) > max_array_items:
                truncated = True

    walk(value)
    item_count = len(value) if _is_sequence(value) else None
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
        return GarminValueState.EMPTY if len(value) == 0 else GarminValueState.PRESENT
    if isinstance(value, (bytes, bytearray, str)) and len(value) == 0:
        return GarminValueState.EMPTY
    return GarminValueState.PRESENT


def field_state_at_path(value: Any, path: str) -> GarminValueState:
    """Read a dotted field path and return only its presence state."""

    if not isinstance(path, str) or not path.strip():
        raise ValueError("field path is required")
    return _field_state_at_segments(value, tuple(path.split(".")))


def _field_state_at_segments(value: Any, segments: tuple[str, ...]) -> GarminValueState:
    if not segments:
        return garmin_value_state(value)
    if isinstance(value, Mapping):
        segment = segments[0]
        if segment not in value:
            return GarminValueState.MISSING
        return _field_state_at_segments(value[segment], segments[1:])
    if _is_sequence(value):
        if not value:
            return GarminValueState.EMPTY
        states = [
            _field_state_at_segments(item, segments) for item in list(value)[:MAX_ARRAY_ITEMS]
        ]
        return _combine_field_states(states)
    return GarminValueState.MISSING


def _combine_field_states(states: Sequence[GarminValueState]) -> GarminValueState:
    unique = set(states)
    if GarminValueState.PRESENT in unique:
        return GarminValueState.PRESENT
    if len(unique) == 1:
        return states[0]
    return GarminValueState.UNKNOWN


def field_state_counts(value: Any, paths: Sequence[str]) -> dict[str, int]:
    """Return deterministic counts for expected paths, never their values."""

    counts: Counter[str] = Counter()
    for path in sorted(set(paths)):
        counts[field_state_at_path(value, path).value] += 1
    return {key: counts[key] for key in sorted(counts)}


def infer_device_attribution(value: Any) -> GarminDeviceAttributionEvidence:
    """Infer only coarse target/other/unknown/unattributed evidence.

    A missing device field is deliberately ``unattributed``.  A present field
    that contains only an opaque identifier is ``unknown``.  Values are
    inspected transiently to recognize the synthetic target marker but are
    never returned or logged.
    """

    has_device_field = False
    has_opaque_device_field = False
    explicit_unattributed = False
    target_found = False
    other_found = False

    def inspect(current: Any, device_context: bool = False) -> None:
        nonlocal has_device_field, has_opaque_device_field, explicit_unattributed
        nonlocal target_found, other_found
        if isinstance(current, Mapping):
            for key, nested in current.items():
                normalized = _normalize_key(str(key))
                is_device_key = normalized in _DEVICE_KEY_NAMES or "device" in normalized
                if is_device_key:
                    has_device_field = True
                    if normalized in {"deviceattributed", "isdeviceattributed"}:
                        if nested is False:
                            explicit_unattributed = True
                        elif nested is True:
                            has_opaque_device_field = True
                        continue
                    if isinstance(nested, (str, int, float)) and not isinstance(nested, bool):
                        text = _normalize_marker_text(str(nested))
                        if any(
                            marker.replace(" ", "") in text for marker in _TARGET_DEVICE_MARKERS
                        ):
                            target_found = True
                        elif any(marker in text for marker in _OTHER_DEVICE_MARKERS):
                            other_found = True
                        else:
                            has_opaque_device_field = True
                    elif nested is None or nested == {} or nested == []:
                        has_opaque_device_field = True
                    inspect(nested, True)
                elif device_context and isinstance(nested, str):
                    text = _normalize_marker_text(nested)
                    if any(marker.replace(" ", "") in text for marker in _TARGET_DEVICE_MARKERS):
                        target_found = True
                    elif any(marker in text for marker in _OTHER_DEVICE_MARKERS):
                        other_found = True
                    else:
                        has_opaque_device_field = True
                elif isinstance(nested, (Mapping, Sequence)) and not isinstance(
                    nested, (str, bytes, bytearray)
                ):
                    inspect(nested, device_context)
        elif _is_sequence(current):
            for nested in list(current)[:MAX_ARRAY_ITEMS]:
                inspect(nested, device_context)

    inspect(value)
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
    """Convert a raw response into a value-free shareable shape document."""

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
    """Validate raw-input and sanitized-output paths before file I/O.

    Both paths must be absolute and outside the checkout.  Existing symlinked
    files or parent directories are rejected so a redaction export cannot be
    redirected into Git or an unexpected location.
    """

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
) -> dict[str, Any]:
    shape = _shape_name(value)
    if remaining_nodes[0] < 1:
        return {"type": shape, "truncated": True}
    remaining_nodes[0] -= 1
    if isinstance(value, Mapping):
        fields: list[dict[str, Any]] = []
        redacted = 0
        truncated = False
        for key, nested in sorted(value.items(), key=lambda item: str(item[0])):
            if remaining_nodes[0] < 1:
                truncated = True
                break
            key_text = str(key)
            safe_key = None if _is_sensitive_key(key_text) else _safe_key(key_text)
            if safe_key is None:
                redacted += 1
                continue
            child_shape = _redact_node(
                nested,
                max_array_items=max_array_items,
                remaining_nodes=remaining_nodes,
            )
            fields.append(
                {
                    "key": safe_key,
                    "shape": child_shape,
                }
            )
            truncated = truncated or bool(child_shape.get("truncated"))
        result = {
            "type": shape,
            "field_count": len(value),
            "redacted_field_count": redacted,
            "fields": fields,
        }
        if truncated:
            result["truncated"] = True
        return result
    if _is_sequence(value):
        items = list(value)
        redacted_items: list[dict[str, Any]] = []
        truncated = len(items) > max_array_items
        for item in items[:max_array_items]:
            if remaining_nodes[0] < 1:
                truncated = True
                break
            child_shape = _redact_node(
                item,
                max_array_items=max_array_items,
                remaining_nodes=remaining_nodes,
            )
            redacted_items.append(child_shape)
            truncated = truncated or bool(child_shape.get("truncated"))
        return {
            "type": shape,
            "item_count": len(items),
            "items": redacted_items,
            "truncated": truncated,
        }
    if isinstance(value, (bytes, bytearray)):
        return {"type": shape, "byte_count": len(value)}
    return {"type": shape}


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _normalize_marker_text(value: str) -> str:
    return re.sub(r"[-_\s]", "", value.casefold())


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


def _safe_key(value: str) -> str | None:
    if not _SAFE_KEY_RE.fullmatch(value) or _is_sensitive_key(value):
        return None
    return value


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
    "GarminDeviceAttribution",
    "GarminDeviceAttributionEvidence",
    "GarminPayloadShape",
    "GarminValueState",
    "MAX_ARRAY_ITEMS",
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
