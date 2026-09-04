"""Pure openScale-sync generic-webhook contract and normalization layer.

Implements the pinned R01 contract (openScale-sync ``32e3865``,
``docs/R01_IMPLEMENTATION_SPEC.md`` §9, R00 audit notes) as typed,
deterministic, framework-free DTOs and pure functions.  The later #10
HTTP/persistence state machine calls this layer *before* any
authentication or database work; nothing here touches FastAPI, SQLite,
repositories, migrations, secrets, or the network.

Top-level events: ``insert``, ``update``, ``delete``, ``clear``, ``test``.
A single insert/update/delete carries ``id`` (stable where supplied),
``userId``, ``username`` (metadata only, never identity), ``date``,
convenience measurements, and optional ``values[]``; a batch carries
``measurements[]``.  Each ``values[]`` item carries ``key``, ``name``,
``unit``, ``isDerived``, and an optional numeric ``value`` or ``text``.

Core invariants:

- ``values[]`` is authoritative when present (including present-but-empty).
  A present non-list ``values`` (including explicit null) fails closed
  with typed ``invalid_values_type``; only true key absence permits the
  convenience fallback.  Convenience fields are consulted only then, and a
  missing convenience field serialized as numeric zero never becomes a
  real zero measurement.  Missing is not zero; explicit zero and missing
  stay distinguishable.
- Known metrics normalize only where the (key, unit) mapping is
  unambiguous (see ``KNOWN_METRICS``); unit guessing and cross-unit
  conversion are never performed.
- Unknown keys/fields are retained as evidence but never invent canonical
  metrics.
- Duplicate known keys with contradictory values fail closed as explicit
  ambiguity — never last-one-wins.
- Numeric JSON strings are never silently coerced.
- Error/failure strings never include measurement values or payload dumps.
- Logical identity never depends on username, JSON key ordering, raw
  payload bytes/hash, or bearer credentials.

Known-metric decision table (``r01-openscale-contract-v1``):

- ``("weight", "kg")`` → ``weight``/kg; zero/negative invalid.
- ``("fat", "%")`` → ``body_fat_pct``/percentage points; zero invalid.
- ``("water", "%")`` → ``body_water_pct``/percentage points; zero invalid.
- ``("muscle", "kg")`` → ``muscle_mass_kg``/kg; zero invalid.
- ``("bone", "kg")`` → ``bone_mass_kg``/kg; zero invalid.

Anything else (``lb``, fractional ``0-1`` body fat, visceral index with an
unknown unit, heart rate, impedances, free text, …) is retained as unknown
or unsupported evidence.  The sender contract carries no schema version,
device, algorithm, or reliability metadata, so algorithm/configuration
identity for fingerprints always comes from Health-Check-side
configuration passed in by the caller.

Temporal semantics for the sender ``date`` field:

- ``YYYY-MM-DD`` → precision ``date``; only the source local date is
  known and no midnight UTC instant is ever invented.
- timezone-aware datetime → precision ``instant``; ``measured_at_utc`` is
  set and the local date is read in the sender-offset frame.
- naive datetime → precision ``minute``; the sender-local wall time is
  preserved verbatim and ``measured_at_utc`` stays null rather than
  inventing a zone.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

OPENSCALE_CONTRACT_VERSION = "r01-openscale-contract-v1"
OPENSCALE_PINNED_REF = "32e38651cf78bbf230e33d17abb00b147130f305"

TOP_LEVEL_EVENTS = ("insert", "update", "delete", "clear", "test")
MEASUREMENT_EVENTS = ("insert", "update", "delete")
CONTROL_EVENTS = ("clear", "test")

# Keys that prove a top-level envelope also carries single-measurement
# fields next to a batch.  Unknown top-level fields are always tolerated
# as extras; only these known single-measurement keys conflict.
_SINGLE_MEASUREMENT_KEYS = frozenset({"id", "userId", "username", "date", "values"})

# Convenience fallback is consulted only when ``values[]`` is absent.
# Only weight has an unambiguous convenience mapping; every other
# convenience key is retained untouched in extras.
_CONVENIENCE_METRICS = {"weight": ("weight", "kg")}

_DATE_ONLY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True, slots=True)
class KnownMetricRule:
    metric_code: str
    canonical_unit: str
    zero_allowed: bool = False


KNOWN_METRICS: Mapping[tuple[str, str], KnownMetricRule] = {
    ("weight", "kg"): KnownMetricRule("weight", "kg"),
    ("fat", "%"): KnownMetricRule("body_fat_pct", "%"),
    ("water", "%"): KnownMetricRule("body_water_pct", "%"),
    ("muscle", "kg"): KnownMetricRule("muscle_mass_kg", "kg"),
    ("bone", "kg"): KnownMetricRule("bone_mass_kg", "kg"),
}


@dataclass(frozen=True, slots=True)
class ContractFailure:
    """One typed, sanitized validation failure (never carries values)."""

    reason_code: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"reason_code": self.reason_code, "message": self.message, "path": self.path}


@dataclass(frozen=True, slots=True)
class RawValueItem:
    """One ``values[]`` entry projected to typed raw evidence."""

    key: str
    name: str | None = None
    unit: str | None = None
    is_derived: bool | None = None
    has_numeric_value: bool = False
    numeric_value: float | None = None
    text: str | None = None
    raw_kind: str = "missing"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "unit": self.unit,
            "is_derived": self.is_derived,
            "has_numeric_value": self.has_numeric_value,
            "numeric_value": self.numeric_value,
            "text": self.text,
            "raw_kind": self.raw_kind,
        }


@dataclass(frozen=True, slots=True)
class NormalizedMetric:
    """One known-metric projection; explicit zero/null/missing stay distinct."""

    metric_code: str
    status: str
    reason: str | None = None
    value: float | None = None
    unit: str | None = None
    source_key: str | None = None
    source_name: str | None = None
    source_unit: str | None = None
    is_derived: bool | None = None
    has_explicit_value: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_code": self.metric_code,
            "status": self.status,
            "reason": self.reason,
            "value": self.value,
            "unit": self.unit,
            "source_key": self.source_key,
            "source_name": self.source_name,
            "source_unit": self.source_unit,
            "is_derived": self.is_derived,
            "has_explicit_value": self.has_explicit_value,
        }


@dataclass(frozen=True, slots=True)
class UnknownItem:
    """Retained non-canonical evidence; never a canonical metric.

    The raw numeric value (when the sender supplied one) travels with the
    item so unknown evidence round-trips without inventing a canonical
    metric.  Unknown evidence is fingerprint-neutral by construction: the
    semantic fingerprint only covers usable canonical metrics.
    """

    key: str
    name: str | None = None
    unit: str | None = None
    is_derived: bool | None = None
    raw_kind: str = "missing"
    text: str | None = None
    detail: str | None = None
    numeric_value: float | None = None
    has_explicit_value: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "unit": self.unit,
            "is_derived": self.is_derived,
            "raw_kind": self.raw_kind,
            "text": self.text,
            "detail": self.detail,
            "numeric_value": self.numeric_value,
            "has_explicit_value": self.has_explicit_value,
        }


@dataclass(frozen=True, slots=True)
class ParsedDateTime:
    precision: str
    measured_at_utc: datetime | None = None
    local_wall_time: str | None = None
    local_date: date | None = None

    def time_key(self) -> str:
        if self.measured_at_utc is not None:
            return self.measured_at_utc.isoformat()
        if self.local_wall_time is not None:
            return self.local_wall_time
        if self.local_date is not None:
            return self.local_date.isoformat()
        return "unknown-time"

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "measured_at_utc": (self.measured_at_utc.isoformat() if self.measured_at_utc else None),
            "local_wall_time": self.local_wall_time,
            "local_date": self.local_date.isoformat() if self.local_date else None,
        }


@dataclass(frozen=True, slots=True)
class NormalizedMeasurement:
    """One normalized sender measurement with deterministic ordering."""

    kind: str
    user_id: str
    record_id: str | None = None
    username: str | None = None
    batch_index: int | None = None
    precision: str = "date"
    measured_at_utc: datetime | None = None
    local_wall_time: str | None = None
    local_date: date | None = None
    metrics: tuple[NormalizedMetric, ...] = ()
    unknown_items: tuple[UnknownItem, ...] = ()
    values_authoritative: bool = False
    extras: Mapping[str, Any] = field(default_factory=dict)
    identity_kind: str = "none"
    identity: str | None = None

    def usable_metrics(self) -> tuple[NormalizedMetric, ...]:
        return tuple(item for item in self.metrics if item.status == "ok")

    def metric_codes(self) -> tuple[str, ...]:
        return tuple(item.metric_code for item in self.metrics if item.status == "ok")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "user_id": self.user_id,
            "record_id": self.record_id,
            "username": self.username,
            "batch_index": self.batch_index,
            "precision": self.precision,
            "measured_at_utc": (self.measured_at_utc.isoformat() if self.measured_at_utc else None),
            "local_wall_time": self.local_wall_time,
            "local_date": self.local_date.isoformat() if self.local_date else None,
            "metrics": [item.as_dict() for item in self.metrics],
            "unknown_items": [item.as_dict() for item in self.unknown_items],
            "values_authoritative": self.values_authoritative,
            "extras": {key: self.extras[key] for key in sorted(self.extras)},
            "identity_kind": self.identity_kind,
            "identity": self.identity,
        }


@dataclass(frozen=True, slots=True)
class InvalidBatchItem:
    batch_index: int
    failures: tuple[ContractFailure, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "failures": [item.as_dict() for item in self.failures],
        }


@dataclass(frozen=True, slots=True)
class EnvelopeResult:
    """Normalized top-level envelope: control, single, or batch.

    ``invalid_items`` quarantines batch entries with fatal failures (no
    measurement produced).  ``item_warnings`` carries index-keyed
    non-fatal failures for entries whose measurement is still present in
    ``measurements`` (for example a duplicate-key conflict recorded as an
    explicit ambiguous metric).  ``failures`` holds envelope-level
    failures plus, in single-measurement mode, that item's failures.
    """

    event: str
    is_control: bool = False
    measurements: tuple[NormalizedMeasurement, ...] = ()
    invalid_items: tuple[InvalidBatchItem, ...] = ()
    item_warnings: tuple[InvalidBatchItem, ...] = ()
    failures: tuple[ContractFailure, ...] = ()
    extras: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = OPENSCALE_CONTRACT_VERSION

    @property
    def ok(self) -> bool:
        return not self.failures and not self.invalid_items and not self.item_warnings

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "is_control": self.is_control,
            "measurements": [item.as_dict() for item in self.measurements],
            "invalid_items": [item.as_dict() for item in self.invalid_items],
            "item_warnings": [item.as_dict() for item in self.item_warnings],
            "failures": [item.as_dict() for item in self.failures],
            "extras": {key: self.extras[key] for key in sorted(self.extras)},
            "contract_version": self.contract_version,
        }


def stable_record_identity(source_instance_id: str, user_id: str, record_id: str) -> str:
    """Return the downstream idempotency identity for insert/update.

    Depends only on ``(source_instance_id, userId, id)`` — never on
    username, JSON ordering, payload bytes, or credentials.
    """

    for label, value in (
        ("source_instance_id", source_instance_id),
        ("user_id", user_id),
        ("record_id", record_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"stable identity requires a non-empty {label}")
    digest = _hash_canonical(
        {
            "kind": "stable",
            "source_instance_id": source_instance_id,
            "user_id": user_id,
            "record_id": record_id,
        }
    )
    return f"stable:{digest}"


def delete_fallback_identity(source_instance_id: str, user_id: str, measured_key: str) -> str:
    """Return the delete fallback identity ``(source_instance, user, time)``."""

    for label, value in (
        ("source_instance_id", source_instance_id),
        ("user_id", user_id),
        ("measured_key", measured_key),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"delete fallback identity requires a non-empty {label}")
    digest = _hash_canonical(
        {
            "kind": "delete",
            "source_instance_id": source_instance_id,
            "user_id": user_id,
            "measured_key": measured_key,
        }
    )
    return f"delete:{digest}"


def semantic_fingerprint(
    source_instance_id: str,
    user_id: str,
    measured_key: str,
    metrics: Iterable[tuple[str, float, str]],
    algorithm_identity: str = "unknown",
    config_identity: str = "unknown",
) -> str:
    """Return the semantic fallback fingerprint for identity-less records.

    Covers source instance, user, source time, the deterministic normalized
    metric set, and algorithm/configuration identity.  A raw payload hash
    alone is forbidden and is never used here.
    """

    if not isinstance(source_instance_id, str) or not source_instance_id.strip():
        raise ValueError("semantic fingerprint requires a non-empty source_instance_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("semantic fingerprint requires a non-empty user_id")
    normalized_metrics = sorted(
        (str(code), repr(float(value)), str(unit)) for code, value, unit in metrics
    )
    digest = _hash_canonical(
        {
            "kind": "semantic",
            "source_instance_id": source_instance_id,
            "user_id": user_id,
            "measured_key": measured_key,
            "metrics": normalized_metrics,
            "algorithm_identity": str(algorithm_identity),
            "config_identity": str(config_identity),
        }
    )
    return f"fp:{digest}"


def measurement_fingerprint(
    measurement: NormalizedMeasurement,
    *,
    source_instance_id: str,
    algorithm_identity: str = "unknown",
    config_identity: str = "unknown",
) -> str:
    """Derive the semantic fingerprint for one normalized measurement."""

    return semantic_fingerprint(
        source_instance_id,
        measurement.user_id,
        _measurement_time_key(measurement),
        [
            (item.metric_code, item.value, item.unit or "")
            for item in measurement.usable_metrics()
            if item.value is not None
        ],
        algorithm_identity,
        config_identity,
    )


def normalize_envelope(
    payload: Any,
    *,
    source_instance_id: str,
    algorithm_identity: str = "unknown",
    config_identity: str = "unknown",
) -> EnvelopeResult:
    """Parse and validate one generic-webhook envelope into typed DTOs."""

    if not isinstance(source_instance_id, str) or not source_instance_id.strip():
        raise ValueError("normalize_envelope requires a non-empty source_instance_id")
    if not isinstance(payload, Mapping):
        return _envelope_failure(
            "",
            (ContractFailure("invalid_envelope", "top-level payload must be an object", None),),
            payload,
        )
    raw_event = payload.get("event")
    if not isinstance(raw_event, str) or raw_event.strip() not in TOP_LEVEL_EVENTS:
        return _envelope_failure(
            raw_event if isinstance(raw_event, str) else "",
            (
                ContractFailure(
                    "invalid_event",
                    "top-level event must be one of insert, update, delete, clear, test",
                    "event",
                ),
            ),
            payload,
        )
    event = raw_event.strip()
    extras = {key: payload[key] for key in payload if key not in {"event", "measurements"}}
    if event in CONTROL_EVENTS:
        measurements = payload.get("measurements")
        if isinstance(measurements, list) and measurements:
            return EnvelopeResult(
                event=event,
                is_control=True,
                failures=(
                    ContractFailure(
                        "conflicting_control_with_measurements",
                        f"control event carries no measurements: {event}",
                        "measurements",
                    ),
                ),
                extras=extras,
            )
        return EnvelopeResult(event=event, is_control=True, extras=extras)
    raw_measurements = payload.get("measurements")
    if raw_measurements is not None:
        if not isinstance(raw_measurements, list) or not raw_measurements:
            return _envelope_failure(
                event,
                (
                    ContractFailure(
                        "invalid_measurements_type",
                        "batch measurements must be a non-empty list",
                        "measurements",
                    ),
                ),
                payload,
            )
        if any(key in payload for key in _SINGLE_MEASUREMENT_KEYS):
            return _envelope_failure(
                event,
                (
                    ContractFailure(
                        "conflicting_single_and_batch",
                        "envelope carries both single-measurement fields and a batch",
                        None,
                    ),
                ),
                payload,
            )
        measurements: list[NormalizedMeasurement] = []
        invalid_items: list[InvalidBatchItem] = []
        item_warnings: list[InvalidBatchItem] = []
        for index, raw_item in enumerate(raw_measurements):
            measurement, failures, fatal = _normalize_measurement(
                raw_item,
                kind=event,
                source_instance_id=source_instance_id,
                algorithm_identity=algorithm_identity,
                config_identity=config_identity,
                batch_index=index,
            )
            if measurement is not None:
                measurements.append(measurement)
            if fatal:
                invalid_items.append(InvalidBatchItem(batch_index=index, failures=tuple(failures)))
            elif failures:
                item_warnings.append(InvalidBatchItem(batch_index=index, failures=tuple(failures)))
        measurements.sort(key=_measurement_sort_key)
        return EnvelopeResult(
            event=event,
            measurements=tuple(measurements),
            invalid_items=tuple(sorted(invalid_items, key=lambda item: item.batch_index)),
            item_warnings=tuple(sorted(item_warnings, key=lambda item: item.batch_index)),
            extras=extras,
        )
    measurement, failures, _fatal = _normalize_measurement(
        {key: payload[key] for key in payload if key != "event"},
        kind=event,
        source_instance_id=source_instance_id,
        algorithm_identity=algorithm_identity,
        config_identity=config_identity,
        batch_index=None,
    )
    if measurement is None:
        return EnvelopeResult(event=event, failures=tuple(failures), extras=extras)
    return EnvelopeResult(
        event=event, measurements=(measurement,), failures=tuple(failures), extras=extras
    )


def _normalize_measurement(
    raw: Any,
    *,
    kind: str,
    source_instance_id: str,
    algorithm_identity: str,
    config_identity: str,
    batch_index: int | None,
) -> tuple[NormalizedMeasurement | None, list[ContractFailure], bool]:
    """Normalize one measurement; ``fatal`` means no measurement is produced."""

    path = f"measurements[{batch_index}]" if batch_index is not None else None
    failures: list[ContractFailure] = []
    fatal = False

    def fail(
        reason: str, message: str, field: str | None = None, *, is_fatal: bool = False
    ) -> None:
        nonlocal fatal
        failures.append(
            ContractFailure(
                reason, message, f"{path}.{field}" if path and field else (path or field)
            )
        )
        if is_fatal:
            fatal = True

    if not isinstance(raw, Mapping):
        fail("invalid_measurement_type", "batch measurement must be an object", is_fatal=True)
        return None, failures, True
    user_id = raw.get("userId")
    if not isinstance(user_id, str) or not user_id.strip():
        fail("missing_user_id", "measurement requires a non-empty userId", "userId", is_fatal=True)
    record_id = raw.get("id")
    if record_id is not None:
        if isinstance(record_id, bool) or not isinstance(record_id, (str, int)):
            fail("invalid_record_id", "measurement id must be text or an integer", "id")
            record_id = None
        else:
            record_id = str(record_id)
            if not record_id.strip():
                fail("invalid_record_id", "measurement id must be non-empty", "id")
                record_id = None
    username = raw.get("username")
    if username is not None and not isinstance(username, str):
        fail("invalid_username", "username must be text when present", "username")
        username = None
    parsed: ParsedDateTime | None = None
    if "date" in raw:
        parsed, date_failure = _parse_sender_datetime(raw.get("date"))
        if date_failure is not None:
            fail(date_failure.reason_code, date_failure.message, "date", is_fatal=True)
    if parsed is None and kind in ("insert", "update"):
        fail("missing_datetime", "measurement requires a sender date", "date", is_fatal=True)
    if parsed is None and kind == "delete" and record_id is None:
        fail(
            "missing_datetime",
            "delete without a stable id requires a sender date",
            "date",
            is_fatal=True,
        )
    metrics: list[NormalizedMetric] = []
    unknown_items: list[UnknownItem] = []
    values_authoritative = False
    if "values" in raw:
        values_authoritative = True
        raw_values = raw["values"]
        if not isinstance(raw_values, list):
            fail(
                "invalid_values_type",
                "values must be a list when present",
                "values",
                is_fatal=True,
            )
        else:
            failures.extend(_project_values(raw_values, metrics, unknown_items, path))
    else:
        _project_convenience(raw, metrics, unknown_items)
    if fatal:
        return None, failures, True
    assert isinstance(user_id, str) and user_id.strip()
    metrics.sort(key=lambda item: (item.metric_code, item.source_key or ""))
    unknown_items.sort(key=lambda item: (item.key, item.raw_kind))
    # Convenience keys are projected above when ``values[]`` is absent;
    # when ``values[]`` is authoritative they survive here as ignored
    # evidence instead of vanishing silently.
    excluded = {"id", "userId", "username", "date", "values"}
    if not values_authoritative:
        excluded |= set(_CONVENIENCE_METRICS)
    extras = {key: raw[key] for key in raw if key not in excluded}
    time_key = parsed.time_key() if parsed is not None else "unknown-time"
    identity_kind = "none"
    identity: str | None = None
    if record_id is not None:
        identity_kind = "stable_id"
        identity = stable_record_identity(source_instance_id, user_id, record_id)
    elif kind == "delete":
        # The R01 §9 time fallback is reserved for delete; without a stable
        # id a delete always carries a sender date (enforced above).
        assert parsed is not None
        identity_kind = "fallback_time"
        identity = delete_fallback_identity(source_instance_id, user_id, time_key)
    else:
        # Insert/update without stable sender identity use the semantic
        # fingerprint so records with different metric content or
        # algorithm/config identity never collapse to one identity.
        identity_kind = "semantic"
        identity = semantic_fingerprint(
            source_instance_id,
            user_id,
            time_key,
            [
                (item.metric_code, item.value, item.unit or "")
                for item in metrics
                if item.status == "ok" and item.value is not None
            ],
            algorithm_identity,
            config_identity,
        )
    return (
        NormalizedMeasurement(
            kind=kind,
            user_id=user_id,
            record_id=record_id,
            username=username,
            batch_index=batch_index,
            precision=parsed.precision if parsed is not None else "date",
            measured_at_utc=parsed.measured_at_utc if parsed is not None else None,
            local_wall_time=parsed.local_wall_time if parsed is not None else None,
            local_date=parsed.local_date if parsed is not None else None,
            metrics=tuple(metrics),
            unknown_items=tuple(unknown_items),
            values_authoritative=values_authoritative,
            extras=extras,
            identity_kind=identity_kind,
            identity=identity,
        ),
        failures,
        False,
    )


def _project_values(
    raw_values: list[Any],
    metrics: list[NormalizedMetric],
    unknown_items: list[UnknownItem],
    path: str | None,
) -> list[ContractFailure]:
    failures: list[ContractFailure] = []
    by_key: dict[str, list[RawValueItem]] = {}
    for index, raw_item in enumerate(raw_values):
        item_path = f"{path or 'values'}[{index}]" if path else f"values[{index}]"
        item, failure = _parse_value_item(raw_item, item_path)
        if failure is not None:
            failures.append(failure)
            continue
        assert item is not None
        by_key.setdefault(item.key, []).append(item)
    for key in sorted(by_key):
        items = by_key[key]
        first_signature = _value_signature(items[0])
        if any(_value_signature(item) != first_signature for item in items[1:]):
            representative = items[0]
            rule = _known_rule(representative.key, representative.unit)
            failures.append(
                ContractFailure(
                    "duplicate_conflicting_values",
                    "duplicate measurement key carries contradictory values",
                    path,
                )
            )
            if rule is not None:
                metrics.append(
                    NormalizedMetric(
                        metric_code=rule.metric_code,
                        status="ambiguous",
                        reason="duplicate_conflicting_values",
                        value=None,
                        unit=rule.canonical_unit,
                        source_key=representative.key,
                        source_name=representative.name,
                        source_unit=representative.unit,
                        is_derived=representative.is_derived,
                        has_explicit_value=True,
                    )
                )
            else:
                unknown_items.append(
                    UnknownItem(
                        key=representative.key,
                        name=representative.name,
                        unit=representative.unit,
                        is_derived=representative.is_derived,
                        raw_kind="conflict",
                        detail="duplicate_conflicting_values",
                    )
                )
            continue
        representative = items[0]
        if len(items) > 1:
            unknown_items.append(
                UnknownItem(
                    key=representative.key,
                    name=representative.name,
                    unit=representative.unit,
                    is_derived=representative.is_derived,
                    raw_kind=representative.raw_kind,
                    detail="duplicate_identical_collapsed",
                    numeric_value=representative.numeric_value,
                    has_explicit_value=representative.has_numeric_value,
                )
            )
        _project_single_value(representative, metrics, unknown_items, failures, path)
    return failures


def _project_single_value(
    item: RawValueItem,
    metrics: list[NormalizedMetric],
    unknown_items: list[UnknownItem],
    failures: list[ContractFailure],
    path: str | None,
) -> None:
    rule = _known_rule(item.key, item.unit)
    if rule is None:
        unknown_items.append(
            UnknownItem(
                key=item.key,
                name=item.name,
                unit=item.unit,
                is_derived=item.is_derived,
                raw_kind=item.raw_kind,
                text=item.text,
                detail="unknown_metric_key_or_unit",
                numeric_value=item.numeric_value,
                has_explicit_value=item.has_numeric_value,
            )
        )
        return
    if not item.has_numeric_value:
        unknown_items.append(
            UnknownItem(
                key=item.key,
                name=item.name,
                unit=item.unit,
                is_derived=item.is_derived,
                raw_kind=item.raw_kind,
                text=item.text,
                detail="known_key_without_numeric_value",
                numeric_value=item.numeric_value,
                has_explicit_value=item.has_numeric_value,
            )
        )
        return
    assert item.numeric_value is not None
    value = item.numeric_value
    if not math.isfinite(value):
        failures.append(
            ContractFailure("non_finite_value", "measurement value is not finite", path)
        )
        metrics.append(
            NormalizedMetric(
                metric_code=rule.metric_code,
                status="invalid",
                reason="non_finite_value",
                value=None,
                unit=rule.canonical_unit,
                source_key=item.key,
                source_name=item.name,
                source_unit=item.unit,
                is_derived=item.is_derived,
                has_explicit_value=True,
            )
        )
        return
    if value < 0 or (value == 0 and not rule.zero_allowed):
        metrics.append(
            NormalizedMetric(
                metric_code=rule.metric_code,
                status="invalid",
                reason="explicit_zero_or_negative_invalid",
                value=value,
                unit=rule.canonical_unit,
                source_key=item.key,
                source_name=item.name,
                source_unit=item.unit,
                is_derived=item.is_derived,
                has_explicit_value=True,
            )
        )
        return
    metrics.append(
        NormalizedMetric(
            metric_code=rule.metric_code,
            status="ok",
            reason=None,
            value=value,
            unit=rule.canonical_unit,
            source_key=item.key,
            source_name=item.name,
            source_unit=item.unit,
            is_derived=item.is_derived,
            has_explicit_value=True,
        )
    )


def _project_convenience(
    raw: Mapping[str, Any],
    metrics: list[NormalizedMetric],
    unknown_items: list[UnknownItem],
) -> None:
    for convenience_key, (metric_code, canonical_unit) in sorted(_CONVENIENCE_METRICS.items()):
        if convenience_key not in raw:
            continue
        raw_value = raw[convenience_key]
        if raw_value is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            metrics.append(
                NormalizedMetric(
                    metric_code=metric_code,
                    status="invalid",
                    reason="numeric_string_not_coerced",
                    value=None,
                    unit=canonical_unit,
                    source_key=convenience_key,
                    source_name=None,
                    source_unit=None,
                    is_derived=None,
                    has_explicit_value=True,
                )
            )
            continue
        value = float(raw_value)
        if not math.isfinite(value):
            metrics.append(
                NormalizedMetric(
                    metric_code=metric_code,
                    status="invalid",
                    reason="non_finite_value",
                    value=None,
                    unit=canonical_unit,
                    source_key=convenience_key,
                    is_derived=None,
                    has_explicit_value=True,
                )
            )
            continue
        if value == 0:
            # A missing convenience field may be serialized as numeric zero
            # by the sender; absence must never become a real measurement.
            unknown_items.append(
                UnknownItem(
                    key=convenience_key,
                    raw_kind="number",
                    detail="convenience_zero_treated_as_missing",
                )
            )
            continue
        if value < 0:
            metrics.append(
                NormalizedMetric(
                    metric_code=metric_code,
                    status="invalid",
                    reason="explicit_zero_or_negative_invalid",
                    value=value,
                    unit=canonical_unit,
                    source_key=convenience_key,
                    is_derived=None,
                    has_explicit_value=True,
                )
            )
            continue
        metrics.append(
            NormalizedMetric(
                metric_code=metric_code,
                status="ok",
                reason=None,
                value=value,
                unit=canonical_unit,
                source_key=convenience_key,
                source_name=None,
                source_unit=None,
                is_derived=None,
                has_explicit_value=True,
            )
        )


def _parse_value_item(raw: Any, path: str) -> tuple[RawValueItem | None, ContractFailure | None]:
    def fail(reason: str, message: str) -> tuple[None, ContractFailure]:
        return None, ContractFailure(reason, message, path)

    if not isinstance(raw, Mapping):
        return fail("invalid_values_item", "values entry must be an object")
    key = raw.get("key")
    if not isinstance(key, str) or not key.strip():
        return fail("missing_value_key", "values entry requires a non-empty key")
    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        return fail("invalid_value_name", "values entry name must be text")
    unit = raw.get("unit")
    if unit is not None and not isinstance(unit, str):
        return fail("invalid_value_unit", "values entry unit must be text")
    is_derived = raw.get("isDerived")
    if is_derived is not None and not isinstance(is_derived, bool):
        return fail("invalid_is_derived", "values entry isDerived must be boolean")
    text = raw.get("text")
    if text is not None and not isinstance(text, str):
        return fail("invalid_value_text", "values entry text must be text")
    if "value" not in raw or raw.get("value") is None:
        return (
            RawValueItem(
                key=key.strip(),
                name=name,
                unit=unit,
                is_derived=is_derived,
                has_numeric_value=False,
                numeric_value=None,
                text=text,
                raw_kind="text" if text is not None else "null",
            ),
            None,
        )
    value = raw.get("value")
    if isinstance(value, bool):
        return fail("invalid_value_type", "values entry value must be numeric or text")
    if isinstance(value, str):
        return (
            RawValueItem(
                key=key.strip(),
                name=name,
                unit=unit,
                is_derived=is_derived,
                has_numeric_value=False,
                numeric_value=None,
                text=text,
                raw_kind="numeric_string",
            ),
            ContractFailure("numeric_string_not_coerced", "numeric text is not coerced", path),
        )
    if not isinstance(value, (int, float)):
        return fail("invalid_value_type", "values entry value must be numeric or text")
    return (
        RawValueItem(
            key=key.strip(),
            name=name,
            unit=unit,
            is_derived=is_derived,
            has_numeric_value=True,
            numeric_value=float(value),
            text=text,
            raw_kind="number",
        ),
        None,
    )


def _parse_sender_datetime(value: Any) -> tuple[ParsedDateTime | None, ContractFailure | None]:
    failure = ContractFailure(
        "invalid_datetime", "sender date must be ISO-8601 calendar date or datetime", None
    )
    if not isinstance(value, str) or not value.strip():
        return None, failure
    text = value.strip()
    date_match = _DATE_ONLY_RE.match(text)
    if date_match:
        try:
            parsed_date = date(
                int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
            )
        except ValueError:
            return None, failure
        return ParsedDateTime(precision="date", local_date=parsed_date), None
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, failure
    if not isinstance(parsed, datetime):
        return None, failure
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        wall = parsed.replace(tzinfo=None).isoformat()
        return (
            ParsedDateTime(precision="minute", local_wall_time=wall, local_date=parsed.date()),
            None,
        )
    utc_value = parsed.astimezone(UTC)
    return (
        ParsedDateTime(
            precision="instant",
            measured_at_utc=utc_value,
            local_wall_time=parsed.replace(tzinfo=None).isoformat(),
            local_date=parsed.date(),
        ),
        None,
    )


def _known_rule(key: str, unit: str | None) -> KnownMetricRule | None:
    if unit is None:
        return None
    return KNOWN_METRICS.get((key, unit.strip()))


def _value_signature(item: RawValueItem) -> tuple[str, str, str]:
    if item.has_numeric_value and item.numeric_value is not None:
        return ("number", repr(item.numeric_value), item.unit or "")
    return (item.raw_kind, item.text or "", item.unit or "")


def _measurement_sort_key(item: NormalizedMeasurement) -> tuple[str, ...]:
    return (
        item.user_id,
        item.record_id or "",
        item.local_date.isoformat() if item.local_date else "",
        item.local_wall_time or "",
        item.measured_at_utc.isoformat() if item.measured_at_utc else "",
    )


def _measurement_time_key(item: NormalizedMeasurement) -> str:
    if item.measured_at_utc is not None:
        return item.measured_at_utc.isoformat()
    if item.local_wall_time is not None:
        return item.local_wall_time
    if item.local_date is not None:
        return item.local_date.isoformat()
    return "unknown-time"


def _envelope_failure(
    event: str, failures: tuple[ContractFailure, ...], payload: Any
) -> EnvelopeResult:
    # Failed envelopes retain no raw payload: the reason codes carry the
    # signal, and raw-byte evidence persistence belongs to the later #10
    # layer.  This keeps failure DTOs free of measurement values.
    return EnvelopeResult(event=event, failures=failures, extras={})


def _hash_canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CONTROL_EVENTS",
    "KNOWN_METRICS",
    "MEASUREMENT_EVENTS",
    "OPENSCALE_CONTRACT_VERSION",
    "OPENSCALE_PINNED_REF",
    "TOP_LEVEL_EVENTS",
    "ContractFailure",
    "EnvelopeResult",
    "InvalidBatchItem",
    "KnownMetricRule",
    "NormalizedMeasurement",
    "NormalizedMetric",
    "ParsedDateTime",
    "RawValueItem",
    "UnknownItem",
    "delete_fallback_identity",
    "measurement_fingerprint",
    "normalize_envelope",
    "semantic_fingerprint",
    "stable_record_identity",
]
