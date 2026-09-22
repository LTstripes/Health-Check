"""Typed, local-first persistence service for owner-authored context evidence."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    ContextEvent,
    ContextEventHead,
    ContextEventRevision,
    ContextRevisionTag,
    ContextTag,
    utc_now,
)

MAX_TEXT_LENGTH = 4_000
MAX_TAG_LENGTH = 64
MAX_LIST_RESULTS = 200
DEFAULT_LIST_RESULTS = 50
IMPLEMENTED_CAPTURE_SOURCES = frozenset({"cli", "manual"})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$"
)
_OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


class ContextValidationError(ValueError):
    """Raised when owner input does not satisfy the explicit v0 contract."""


class ContextConflictError(RuntimeError):
    """Raised when an idempotency or concurrent-currentness contract conflicts."""


@dataclass(frozen=True, slots=True)
class TemporalValue:
    kind: str
    start_precision: str
    start_local_date: date
    start_at_utc: datetime | None = None
    start_source_timestamp: str | None = None
    start_utc_offset_minutes: int | None = None
    start_timezone: str | None = None
    end_precision: str | None = None
    end_local_date: date | None = None
    end_at_utc: datetime | None = None
    end_source_timestamp: str | None = None
    end_utc_offset_minutes: int | None = None
    end_timezone: str | None = None


@dataclass(frozen=True, slots=True)
class ContextTagView:
    name: str
    status: str
    provenance_source: str


@dataclass(frozen=True, slots=True)
class ContextRevisionView:
    event_id: str
    revision_id: str
    revision_number: int
    operation_id: str
    is_current: bool
    original_text: str
    capture_source: str
    temporal: TemporalValue
    tags: tuple[ContextTagView, ...]
    created_at: datetime


def _timestamp_precision(value: str) -> str:
    clock = value.split("T", 1)[1]
    clock = clock[:-1] if clock.endswith("Z") else clock.rsplit("+", 1)[0]
    if "-" in clock[5:]:
        clock = clock.rsplit("-", 1)[0]
    if clock.count(":") == 1:
        return "minute"
    return "microsecond" if "." in clock else "second"


def _parse_aware_timestamp(value: str, timezone_name: str | None) -> tuple[datetime, int, str]:
    if not _TIMESTAMP_RE.fullmatch(value):
        raise ContextValidationError(
            "timestamp must be ISO 8601 with T and an explicit Z or numeric offset"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ContextValidationError("timestamp is not a valid calendar time") from exc
    offset = parsed.utcoffset()
    if offset is None:
        raise ContextValidationError("timestamp must carry an explicit UTC offset")
    offset_seconds = offset.total_seconds()
    if offset_seconds % 60:
        raise ContextValidationError("timestamp offset must resolve to whole minutes")
    offset_minutes = int(offset_seconds // 60)
    if not -1439 <= offset_minutes <= 1439:
        raise ContextValidationError("timestamp offset is outside the supported range")
    if timezone_name is not None:
        if not timezone_name or len(timezone_name) > 100 or "\x00" in timezone_name:
            raise ContextValidationError("timezone name is malformed or too long")
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ContextValidationError("timezone name is unknown") from exc
        in_zone = parsed.astimezone(UTC).astimezone(zone)
        if (
            in_zone.replace(tzinfo=None) != parsed.replace(tzinfo=None)
            or in_zone.utcoffset() != offset
        ):
            raise ContextValidationError("timestamp offset does not match the supplied timezone")
    return parsed.astimezone(UTC), offset_minutes, _timestamp_precision(value)


def parse_date_only(value: str) -> TemporalValue:
    """Parse an explicit calendar date without inventing a time, offset, or UTC."""

    if not _DATE_RE.fullmatch(value):
        raise ContextValidationError("date must use exact YYYY-MM-DD form")
    try:
        local_date = date.fromisoformat(value)
    except ValueError as exc:
        raise ContextValidationError("date is not a valid calendar date") from exc
    return TemporalValue(kind="date", start_precision="date", start_local_date=local_date)


def parse_timestamp(value: str, *, timezone_name: str | None = None) -> TemporalValue:
    """Parse an explicit offset-bearing instant and preserve its source representation."""

    at_utc, offset_minutes, precision = _parse_aware_timestamp(value, timezone_name)
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    return TemporalValue(
        kind="instant",
        start_precision=precision,
        start_local_date=parsed.date(),
        start_at_utc=at_utc,
        start_source_timestamp=value,
        start_utc_offset_minutes=offset_minutes,
        start_timezone=timezone_name,
    )


def parse_interval(
    start: str,
    end: str,
    *,
    timezone_name: str | None = None,
) -> TemporalValue:
    """Parse a date range or offset-bearing interval and reject reversed bounds."""

    if _DATE_RE.fullmatch(start) or _DATE_RE.fullmatch(end):
        if not (_DATE_RE.fullmatch(start) and _DATE_RE.fullmatch(end)):
            raise ContextValidationError("interval bounds must use the same temporal precision")
        if timezone_name is not None:
            raise ContextValidationError("date-only interval must not specify a timezone")
        start_date = parse_date_only(start).start_local_date
        end_date = parse_date_only(end).start_local_date
        if start_date > end_date:
            raise ContextValidationError("interval end must not be earlier than interval start")
        return TemporalValue(
            kind="interval",
            start_precision="date",
            start_local_date=start_date,
            end_precision="date",
            end_local_date=end_date,
        )
    start_utc, start_offset, start_precision = _parse_aware_timestamp(start, timezone_name)
    end_utc, end_offset, end_precision = _parse_aware_timestamp(end, timezone_name)
    if start_precision != end_precision:
        raise ContextValidationError("interval bounds must use the same temporal precision")
    if start_utc >= end_utc:
        raise ContextValidationError("interval end must be later than interval start")
    start_parsed = datetime.fromisoformat(start[:-1] + "+00:00" if start.endswith("Z") else start)
    end_parsed = datetime.fromisoformat(end[:-1] + "+00:00" if end.endswith("Z") else end)
    return TemporalValue(
        kind="interval",
        start_precision=start_precision,
        start_local_date=start_parsed.date(),
        start_at_utc=start_utc,
        start_source_timestamp=start,
        start_utc_offset_minutes=start_offset,
        start_timezone=timezone_name,
        end_precision=end_precision,
        end_local_date=end_parsed.date(),
        end_at_utc=end_utc,
        end_source_timestamp=end,
        end_utc_offset_minutes=end_offset,
        end_timezone=timezone_name,
    )


def normalize_tag(value: str) -> str:
    """Return a bounded Unicode tag identity without interpreting its meaning."""

    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    pieces: list[str] = []
    previous_separator = False
    for character in normalized:
        if character.isspace() or character in {"_", "-"}:
            if pieces and not previous_separator:
                pieces.append("-")
            previous_separator = True
            continue
        if not character.isalnum():
            raise ContextValidationError("tag contains unsupported punctuation")
        pieces.append(character)
        previous_separator = False
    result = "".join(pieces).strip("-")
    if not result:
        raise ContextValidationError("tag must contain at least one letter or digit")
    if len(result) > MAX_TAG_LENGTH:
        raise ContextValidationError(f"normalized tag exceeds {MAX_TAG_LENGTH} characters")
    return result


def _validate_text(value: str) -> str:
    if not value or not value.strip():
        raise ContextValidationError("context text must not be empty or whitespace-only")
    if len(value) > MAX_TEXT_LENGTH:
        raise ContextValidationError(f"context text exceeds {MAX_TEXT_LENGTH} characters")
    if "\x00" in value:
        raise ContextValidationError("context text contains a forbidden NUL character")
    return value


def _validate_capture_source(value: str) -> str:
    if value not in IMPLEMENTED_CAPTURE_SOURCES:
        raise ContextValidationError("capture source is not implemented in Context Capture v0")
    return value


def _validate_temporal(value: TemporalValue) -> TemporalValue:
    if value.kind == "date":
        expected = TemporalValue(
            kind="date",
            start_precision="date",
            start_local_date=value.start_local_date,
        )
    elif value.kind == "instant" and value.start_source_timestamp is not None:
        expected = parse_timestamp(
            value.start_source_timestamp,
            timezone_name=value.start_timezone,
        )
    elif value.kind == "interval" and value.start_precision == "date":
        if value.end_local_date is None:
            raise ContextValidationError("date interval requires an end date")
        expected = parse_interval(
            value.start_local_date.isoformat(),
            value.end_local_date.isoformat(),
        )
    elif (
        value.kind == "interval"
        and value.start_source_timestamp is not None
        and value.end_source_timestamp is not None
    ):
        if value.start_timezone != value.end_timezone:
            raise ContextValidationError("interval endpoints must use the same timezone context")
        expected = parse_interval(
            value.start_source_timestamp,
            value.end_source_timestamp,
            timezone_name=value.start_timezone,
        )
    else:
        raise ContextValidationError("temporal value has an unsupported or incomplete shape")
    if value != expected:
        raise ContextValidationError("temporal value is internally inconsistent")
    return value


def _validate_operation_id(value: str | None) -> str:
    if value is None:
        return str(uuid4())
    if not _OPERATION_RE.fullmatch(value):
        raise ContextValidationError("operation id is malformed or too long")
    return value


def _validate_event_id(value: str | None) -> str:
    if value is None:
        return str(uuid4())
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ContextValidationError("event id must be a UUID") from exc


def _normalized_tags(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({normalize_tag(value) for value in values}))


def _temporal_identity(value: TemporalValue) -> dict[str, str | int | None]:
    return {
        "kind": value.kind,
        "start_precision": value.start_precision,
        "start_local_date": value.start_local_date.isoformat(),
        "start_at_utc": value.start_at_utc.isoformat() if value.start_at_utc else None,
        "start_source_timestamp": value.start_source_timestamp,
        "start_utc_offset_minutes": value.start_utc_offset_minutes,
        "start_timezone": value.start_timezone,
        "end_precision": value.end_precision,
        "end_local_date": value.end_local_date.isoformat() if value.end_local_date else None,
        "end_at_utc": value.end_at_utc.isoformat() if value.end_at_utc else None,
        "end_source_timestamp": value.end_source_timestamp,
        "end_utc_offset_minutes": value.end_utc_offset_minutes,
        "end_timezone": value.end_timezone,
    }


def _request_fingerprint(operation_kind: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"operation_kind": operation_kind, **payload},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ContextService:
    """Application service shared by present CLI and future typed adapters."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        text: str,
        temporal: TemporalValue,
        capture_source: str = "manual",
        tags: tuple[str, ...] | list[str] = (),
        event_id: str | None = None,
        operation_id: str | None = None,
    ) -> ContextRevisionView:
        original_text = _validate_text(text)
        source = _validate_capture_source(capture_source)
        temporal = _validate_temporal(temporal)
        normalized_tags = _normalized_tags(tags)
        supplied_event_id = _validate_event_id(event_id) if event_id is not None else None
        stable_operation_id = _validate_operation_id(operation_id)
        request_fingerprint = _request_fingerprint(
            "add",
            {
                "event_id": supplied_event_id,
                "text": original_text,
                "capture_source": source,
                "temporal": _temporal_identity(temporal),
                "tags": normalized_tags,
            },
        )
        existing = self.session.scalar(
            select(ContextEventRevision).where(
                ContextEventRevision.operation_id == stable_operation_id
            )
        )
        if existing is not None:
            if (
                existing.operation_kind != "add"
                or existing.request_fingerprint != request_fingerprint
            ):
                raise ContextConflictError(
                    "operation id already belongs to different context input"
                )
            return self._view(existing)

        stable_event_id = supplied_event_id or str(uuid4())
        event = ContextEvent(id=stable_event_id)
        self.session.add(event)
        self.session.flush()
        revision = self._new_revision(
            event_id=event.id,
            revision_number=1,
            operation_id=stable_operation_id,
            operation_kind="add",
            request_fingerprint=request_fingerprint,
            original_text=original_text,
            capture_source=source,
            temporal=temporal,
            tags=normalized_tags,
        )
        self.session.add(ContextEventHead(event_id=event.id, revision_id=revision.id))
        self.session.flush()
        return self._view(revision, is_current=True)

    def revise(
        self,
        event_id: str,
        *,
        text: str | None = None,
        temporal: TemporalValue | None = None,
        capture_source: str = "manual",
        tags: tuple[str, ...] | list[str] | None = None,
        operation_id: str | None = None,
    ) -> ContextRevisionView:
        stable_event_id = _validate_event_id(event_id)
        source = _validate_capture_source(capture_source)
        stable_operation_id = _validate_operation_id(operation_id)
        supplied_text = None if text is None else _validate_text(text)
        supplied_temporal = None if temporal is None else _validate_temporal(temporal)
        supplied_tags = None if tags is None else _normalized_tags(tags)
        request_fingerprint = _request_fingerprint(
            "revise",
            {
                "event_id": stable_event_id,
                "text": {"provided": text is not None, "value": supplied_text},
                "capture_source": source,
                "temporal": {
                    "provided": temporal is not None,
                    "value": (
                        _temporal_identity(supplied_temporal)
                        if supplied_temporal is not None
                        else None
                    ),
                },
                "tags": {"provided": tags is not None, "value": supplied_tags},
            },
        )
        existing = self.session.scalar(
            select(ContextEventRevision).where(
                ContextEventRevision.operation_id == stable_operation_id
            )
        )
        if existing is not None:
            if (
                existing.operation_kind != "revise"
                or existing.request_fingerprint != request_fingerprint
            ):
                raise ContextConflictError(
                    "operation id already belongs to different context input"
                )
            return self._view(existing)

        head = self.session.get(ContextEventHead, stable_event_id)
        if head is None:
            raise ContextValidationError("context event does not exist")
        current = self.session.get(ContextEventRevision, head.revision_id)
        if current is None:
            raise ContextConflictError("context event current revision is unavailable")
        desired_text = current.original_text if supplied_text is None else supplied_text
        desired_temporal = (
            self._temporal_from_row(current)
            if supplied_temporal is None
            else supplied_temporal
        )
        desired_tags = (
            self._tag_names(current.id) if supplied_tags is None else supplied_tags
        )
        revision = self._new_revision(
            event_id=stable_event_id,
            revision_number=current.revision_number + 1,
            operation_id=stable_operation_id,
            operation_kind="revise",
            request_fingerprint=request_fingerprint,
            original_text=desired_text,
            capture_source=source,
            temporal=desired_temporal,
            tags=desired_tags,
        )
        result = self.session.execute(
            update(ContextEventHead)
            .where(
                ContextEventHead.event_id == stable_event_id,
                ContextEventHead.revision_id == current.id,
            )
            .values(revision_id=revision.id, updated_at=utc_now())
        )
        if result.rowcount != 1:
            raise ContextConflictError("context event was revised concurrently")
        self.session.flush()
        return self._view(revision, is_current=True)

    def list(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = DEFAULT_LIST_RESULTS,
        history: bool = False,
    ) -> tuple[ContextRevisionView, ...]:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ContextValidationError("list from date must not be later than to date")
        if not 1 <= limit <= MAX_LIST_RESULTS:
            raise ContextValidationError(f"list limit must be between 1 and {MAX_LIST_RESULTS}")
        statement = select(ContextEventRevision)
        if not history:
            statement = statement.join(
                ContextEventHead,
                ContextEventHead.revision_id == ContextEventRevision.id,
            )
        if from_date is not None:
            statement = statement.where(
                func.coalesce(
                    ContextEventRevision.end_local_date,
                    ContextEventRevision.start_local_date,
                )
                >= from_date
            )
        if to_date is not None:
            statement = statement.where(ContextEventRevision.start_local_date <= to_date)
        statement = statement.order_by(
            ContextEventRevision.start_local_date.desc(),
            ContextEventRevision.start_at_utc.desc(),
            ContextEventRevision.created_at.desc(),
            ContextEventRevision.event_id,
            ContextEventRevision.revision_number.desc(),
            ContextEventRevision.id,
        ).limit(limit)
        revisions = tuple(self.session.scalars(statement))
        current_ids = (
            set(
                self.session.scalars(
                    select(ContextEventHead.revision_id).where(
                        ContextEventHead.event_id.in_({row.event_id for row in revisions})
                    )
                )
            )
            if revisions
            else set()
        )
        return tuple(self._view(row, is_current=row.id in current_ids) for row in revisions)

    def _new_revision(
        self,
        *,
        event_id: str,
        revision_number: int,
        operation_id: str,
        operation_kind: str,
        request_fingerprint: str,
        original_text: str,
        capture_source: str,
        temporal: TemporalValue,
        tags: tuple[str, ...],
    ) -> ContextEventRevision:
        revision = ContextEventRevision(
            event_id=event_id,
            revision_number=revision_number,
            operation_id=operation_id,
            operation_kind=operation_kind,
            request_fingerprint=request_fingerprint,
            original_text=original_text,
            capture_source=capture_source,
            temporal_kind=temporal.kind,
            start_precision=temporal.start_precision,
            end_precision=temporal.end_precision,
            start_local_date=temporal.start_local_date,
            end_local_date=temporal.end_local_date,
            start_at_utc=temporal.start_at_utc,
            end_at_utc=temporal.end_at_utc,
            start_source_timestamp=temporal.start_source_timestamp,
            end_source_timestamp=temporal.end_source_timestamp,
            start_utc_offset_minutes=temporal.start_utc_offset_minutes,
            end_utc_offset_minutes=temporal.end_utc_offset_minutes,
            start_timezone=temporal.start_timezone,
            end_timezone=temporal.end_timezone,
        )
        self.session.add(revision)
        self.session.flush()
        for tag_name in tags:
            tag = self.session.scalar(
                select(ContextTag).where(ContextTag.normalized_name == tag_name)
            )
            if tag is None:
                tag = ContextTag(normalized_name=tag_name)
                self.session.add(tag)
                self.session.flush()
            self.session.add(
                ContextRevisionTag(
                    revision_id=revision.id,
                    tag_id=tag.id,
                    status="confirmed",
                    provenance_source=capture_source,
                )
            )
        self.session.flush()
        return revision

    def _tag_views(self, revision_id: str) -> tuple[ContextTagView, ...]:
        rows = self.session.execute(
            select(
                ContextTag.normalized_name,
                ContextRevisionTag.status,
                ContextRevisionTag.provenance_source,
            )
            .join(ContextRevisionTag, ContextRevisionTag.tag_id == ContextTag.id)
            .where(ContextRevisionTag.revision_id == revision_id)
            .order_by(ContextTag.normalized_name)
        )
        return tuple(ContextTagView(*row) for row in rows)

    def _tag_names(self, revision_id: str) -> tuple[str, ...]:
        return tuple(tag.name for tag in self._tag_views(revision_id))

    @staticmethod
    def _temporal_from_row(row: ContextEventRevision) -> TemporalValue:
        return TemporalValue(
            kind=row.temporal_kind,
            start_precision=row.start_precision,
            start_local_date=row.start_local_date,
            start_at_utc=_aware_utc(row.start_at_utc),
            start_source_timestamp=row.start_source_timestamp,
            start_utc_offset_minutes=row.start_utc_offset_minutes,
            start_timezone=row.start_timezone,
            end_precision=row.end_precision,
            end_local_date=row.end_local_date,
            end_at_utc=_aware_utc(row.end_at_utc),
            end_source_timestamp=row.end_source_timestamp,
            end_utc_offset_minutes=row.end_utc_offset_minutes,
            end_timezone=row.end_timezone,
        )

    def _view(
        self,
        row: ContextEventRevision,
        *,
        is_current: bool | None = None,
    ) -> ContextRevisionView:
        if is_current is None:
            is_current = self.session.scalar(
                select(ContextEventHead.revision_id).where(
                    ContextEventHead.event_id == row.event_id
                )
            ) == row.id
        return ContextRevisionView(
            event_id=row.event_id,
            revision_id=row.id,
            revision_number=row.revision_number,
            operation_id=row.operation_id,
            is_current=is_current,
            original_text=row.original_text,
            capture_source=row.capture_source,
            temporal=self._temporal_from_row(row),
            tags=self._tag_views(row.id),
            created_at=_aware_utc(row.created_at) or row.created_at,
        )
