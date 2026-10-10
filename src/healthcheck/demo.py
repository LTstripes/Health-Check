"""Safe, synthetic-only demo profile seeding.

The versioned demo profile combines the accepted R01 photo/weight path with a
small fixed-seed Garmin/Google sleep history, Garmin activities and dated
Context notes.  Every value comes from the fixed constants in this module
(random seed, anchor date and payload plans), so the same command produces the
same rows on every machine.  Nothing here calls a provider and all runtime
state stays outside the source checkout.
"""

from __future__ import annotations

import json
import os
import random
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.context import (
    ContextService,
    TemporalValue,
    parse_date_only,
    parse_interval,
    parse_timestamp,
)
from healthcheck.db.engine import (
    create_sqlite_engine,
    migrate_database,
    session_scope,
)
from healthcheck.db.models import (
    AcquisitionSource,
    ContextEventHead,
    GarminActivityRecord,
    GarminSleepRecord,
    GarminSource,
    GoogleSleepRecord,
    GoogleSource,
    ImportCandidate,
    IngestBatch,
    IngestEvent,
    MeasurementSession,
    ScalarMeasurement,
)
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.contracts import (
    FAMILY_GOOGLE_WEARABLES,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import (
    encode_synthetic_png,
    six_month_synthetic_batch,
)
from healthcheck.runtime import RuntimePaths, prepare_runtime, resolve_runtime_paths
from healthcheck.web.query import WeightQueryService

DEMO_SEED_ID = "multidomain-synthetic-v2"
DEMO_LEGACY_SEED_IDS = ("r01-six-month-synthetic-v1",)
DEMO_MARKER_NAME = ".healthcheck-synthetic-demo.json"
DEMO_SOURCE_APPLICATION = "Health-Check Synthetic Demo"
DEMO_MARKER_FORMAT_VERSION = 2
DEMO_LEGACY_FORMAT_VERSION = 1
DEMO_RANDOM_SEED = 358
DEMO_ANCHOR_DATE = date(2026, 10, 10)
DEMO_SLEEP_DAYS = 30
DEMO_GARMIN_DEVICE_CODE = "garmin_vivoactive_5"
DEMO_GARMIN_DEVICE_MODEL = "Vivoactive 5"
DEMO_GOOGLE_FAMILY = FAMILY_GOOGLE_WEARABLES
DEMO_RECEIVED_AT = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)

# Honest freshness is part of the demo: each offset marks one wake date before
# the fixed anchor (offset 0 == anchor).  Missing days produce no record at
# all; sparse/partial days keep only the metrics the source could provide.
_GARMIN_SLEEP_MISSING_OFFSETS = (2, 8, 15, 22, 27)
_GARMIN_SLEEP_SPARSE_OFFSETS = (5, 12, 19)
_GARMIN_SLEEP_NAP_OFFSET = 9
_GOOGLE_SLEEP_MISSING_OFFSETS = (3, 10, 16, 24, 28)
_GOOGLE_SLEEP_MANUAL_EDIT_OFFSET = 13
_GOOGLE_SLEEP_PARTIAL_OFFSET = 17
_GOOGLE_SLEEP_NAP_ONLY_OFFSET = 20
_GOOGLE_SLEEP_EXTRA_NAP_OFFSET = 8
_GOOGLE_SLEEP_LONGER_OFFSET = 12

# (offset, activity type, distance in meters, duration in seconds)
_GARMIN_ACTIVITY_SPECS = (
    (27, "cycling", 18500, 3300),
    (21, "tennis_v2", None, 3900),
    (14, "cycling", 24200, 4200),
    (10, "walking", 4200, 2400),
    (6, "tennis_v2", None, 3600),
    (3, "cycling", 15800, 3000),
)


class DemoSeedError(ValueError):
    """Raised when the requested runtime is not a safe demo target."""


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    data_dir: Path
    created: bool
    reset: bool
    weigh_in_count: int
    candidate_count: int
    garmin_sleep_count: int
    garmin_activity_count: int
    google_sleep_count: int
    context_count: int


@dataclass(frozen=True, slots=True)
class _DemoResetPlan:
    marker: Path
    database_paths: tuple[Path, ...]
    artifacts: Path | None


@dataclass(frozen=True, slots=True)
class _ContextNoteSpec:
    temporal: TemporalValue
    text: str
    tags: tuple[str, ...]
    operation_id: str


def seed_demo(settings: Settings, *, reset: bool = False) -> DemoSeedResult:
    """Create or safely re-use a dedicated synthetic demo profile.

    A non-empty runtime without this tool's marker is never modified.  Reset is
    accepted only for a previously marked demo profile and removes only the
    known demo database/artifact state before reseeding it.
    """

    raw_target = Path(settings.data_dir).expanduser().absolute()
    if _is_reparse_link(raw_target):
        raise DemoSeedError("demo target must not be a symlink or junction")

    try:
        paths = resolve_runtime_paths(settings)
    except ValueError as exc:
        raise DemoSeedError(str(exc)) from None

    _reject_source_workspace_target(raw_target)

    marker = paths.root / DEMO_MARKER_NAME
    if paths.root.exists():
        if not paths.root.is_dir() or _is_reparse_link(paths.root):
            raise DemoSeedError("demo target must be a real directory")
        if marker.exists():
            if _is_reparse_link(marker) or not marker.is_file():
                raise DemoSeedError("demo marker is not a regular file")
            marker_data = _read_and_validate_marker(marker)
            if reset:
                _reset_marked_demo(paths, marker)
            else:
                _require_current_demo_version(marker_data)
                _validate_seeded_demo(paths, marker_data)
                return DemoSeedResult(
                    data_dir=paths.root,
                    created=False,
                    reset=False,
                    weigh_in_count=int(marker_data["weigh_in_count"]),
                    candidate_count=int(marker_data["candidate_count"]),
                    garmin_sleep_count=int(marker_data["garmin_sleep_count"]),
                    garmin_activity_count=int(marker_data["garmin_activity_count"]),
                    google_sleep_count=int(marker_data["google_sleep_count"]),
                    context_count=int(marker_data["context_count"]),
                )
        elif any(paths.root.iterdir()):
            raise DemoSeedError(
                "demo target is non-empty and is not a Health-Check synthetic demo; "
                "choose a new dedicated HEALTHCHECK_DATA_DIR"
            )

    paths = prepare_runtime(settings)
    migrate_database(paths)
    uploads, expected_candidates = _synthetic_uploads()
    garmin_sleep_nights = _garmin_sleep_nights()
    garmin_activities = _garmin_activity_sessions()
    google_durations = {
        wake_date: int(payload["dailySleepDTO"]["sleepTimeSeconds"])
        for wake_date, payload in garmin_sleep_nights
    }
    google_sleep_nights = _google_sleep_nights(google_durations)
    context_notes = _context_note_specs()
    google_sleep_count = len(google_sleep_nights)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            service = PhotoImportService(
                session,
                paths,
                FakeImageMeasurementExtractor(version="synthetic-demo-v1"),
            )
            imported = service.import_photos(
                uploads,
                timezone="UTC",
                provider_code="xiaomi_home",
            )
            candidate_ids = [
                candidate_id for item in imported.items for candidate_id in item.candidate_ids
            ]
            if len(candidate_ids) != expected_candidates:
                raise DemoSeedError("synthetic import did not produce the expected candidate set")
            service.confirm(candidate_ids, actor="synthetic-demo")
            _persist_garmin_sleep(session, paths, garmin_sleep_nights)
            _persist_garmin_activities(session, paths, garmin_activities)
            _persist_google_sleep(session, paths, google_sleep_nights)
            _seed_context_notes(session, context_notes)
    finally:
        engine.dispose()

    _write_marker(
        paths,
        weigh_in_count=len(uploads),
        candidate_count=expected_candidates,
        garmin_sleep_count=len(garmin_sleep_nights),
        garmin_activity_count=len(garmin_activities),
        google_sleep_count=google_sleep_count,
        context_count=len(context_notes),
    )
    _validate_seeded_demo(paths, _read_and_validate_marker(_marker_path(paths)))
    return DemoSeedResult(
        data_dir=paths.root,
        created=True,
        reset=reset,
        weigh_in_count=len(uploads),
        candidate_count=expected_candidates,
        garmin_sleep_count=len(garmin_sleep_nights),
        garmin_activity_count=len(garmin_activities),
        google_sleep_count=google_sleep_count,
        context_count=len(context_notes),
    )


def _is_reparse_link(path: Path) -> bool:
    """True for a symlink or a Windows directory junction/reparse point."""

    return path.is_symlink() or path.is_junction()


def _reject_source_workspace_target(raw_target: Path) -> None:
    """Refuse a demo target inside any Git working tree, not only this checkout."""

    for candidate in (raw_target, *raw_target.parents):
        git_entry = candidate / ".git"
        if git_entry.exists() or git_entry.is_symlink():
            raise DemoSeedError(
                "demo target must be outside any source checkout or workspace; "
                f"found Git metadata at {candidate}"
            )


# ---------------------------------------------------------------------------
# Deterministic synthetic payload plans
# ---------------------------------------------------------------------------


def _demo_rng(seed: int = DEMO_RANDOM_SEED) -> random.Random:
    return random.Random(seed)


def _wake_date(offset: int) -> date:
    return DEMO_ANCHOR_DATE - timedelta(days=offset)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _garmin_sleep_nights() -> list[tuple[date, dict[str, Any]]]:
    """Garmin sleep payloads for the fixed window with honest sparse/missing days."""

    rng = _demo_rng()
    nights: list[tuple[date, dict[str, Any]]] = []
    for offset in range(DEMO_SLEEP_DAYS):
        if offset in _GARMIN_SLEEP_MISSING_OFFSETS:
            continue
        wake_date = _wake_date(offset)
        duration = rng.randrange(6 * 3600 + 20 * 60, 8 * 3600 + 10 * 60, 60)
        daily: dict[str, Any] = {
            "calendarDate": wake_date.isoformat(),
            "sleepTimeSeconds": duration,
        }
        levels: list[dict[str, Any]] = []
        if offset not in _GARMIN_SLEEP_SPARSE_OFFSETS:
            deep = int(duration * rng.uniform(0.14, 0.22))
            rem = int(duration * rng.uniform(0.16, 0.24))
            awake = rng.randrange(8 * 60, 39 * 60, 60)
            light = duration - deep - rem - awake
            daily.update(
                {
                    "deepSleepSeconds": deep,
                    "lightSleepSeconds": light,
                    "remSleepSeconds": rem,
                    "awakeSleepSeconds": awake,
                    "sleepScores": {
                        "overall": {"value": rng.randint(68, 95), "qualifierKey": "SYNTHETIC"},
                        "totalDuration": {"value": rng.randint(60, 99)},
                    },
                }
            )
            start = datetime.combine(wake_date - timedelta(days=1), time(22, 30), tzinfo=UTC)
            deep_end = start + timedelta(seconds=deep)
            light_end = deep_end + timedelta(seconds=light)
            rem_end = light_end + timedelta(seconds=rem)
            awake_end = rem_end + timedelta(seconds=awake)
            stages = (
                ("deep", start, deep_end),
                ("light", deep_end, light_end),
                ("rem", light_end, rem_end),
                ("awake", rem_end, awake_end),
            )
            levels = [
                {
                    "startTimeGMT": _utc_iso(stage_start),
                    "endTimeGMT": _utc_iso(stage_end),
                    "activityLevel": stage_level,
                }
                for stage_level, stage_start, stage_end in stages
            ]
            if offset == _GARMIN_SLEEP_NAP_OFFSET:
                daily["napTimeSeconds"] = rng.randrange(15 * 60, 46 * 60, 60)
        payload: dict[str, Any] = {"dailySleepDTO": daily}
        if levels:
            payload["levels"] = levels
        nights.append((wake_date, payload))
    return nights


def _garmin_activity_sessions() -> list[dict[str, Any]]:
    rng = _demo_rng()
    sessions: list[dict[str, Any]] = []
    for offset, kind, distance, duration in _GARMIN_ACTIVITY_SPECS:
        day = _wake_date(offset)
        session: dict[str, Any] = {
            "activityId": f"synthetic-demo-{kind}-{day.isoformat()}",
            "activityType": {"typeKey": kind},
            "startTimeGMT": f"{day.isoformat()}T07:30:00Z",
            "duration": duration,
            "averageHR": rng.randint(105, 148),
            "aerobicTrainingEffect": round(rng.uniform(1.6, 3.6), 1),
            "activityTrainingLoad": rng.randint(25, 85),
        }
        if distance is not None:
            session["distance"] = distance
            session["averageSpeed"] = round(distance / duration, 2)
        sessions.append(session)
    return sessions


def _google_sleep_nights(
    garmin_durations: Mapping[date, int],
) -> list[tuple[date, dict[str, Any]]]:
    """Google family-aggregate sleep payloads with independent labels and gaps."""

    rng = _demo_rng()
    nights: list[tuple[date, dict[str, Any]]] = []
    for offset in range(DEMO_SLEEP_DAYS):
        if offset in _GOOGLE_SLEEP_MISSING_OFFSETS:
            continue
        wake_date = _wake_date(offset)
        if offset == _GOOGLE_SLEEP_NAP_ONLY_OFFSET:
            nights.append((wake_date, {"dataPoints": [_google_nap_data_point(wake_date, rng)]}))
            continue
        base = garmin_durations.get(wake_date)
        if base is None:
            duration = rng.randrange(6 * 3600, 8 * 3600, 60)
        elif offset == _GOOGLE_SLEEP_LONGER_OFFSET:
            duration = base + 8 * 60
        else:
            duration = base - rng.randrange(5, 36) * 60
        data_points = [_google_main_data_point(wake_date, duration, offset, rng)]
        if offset == _GOOGLE_SLEEP_PARTIAL_OFFSET:
            del data_points[0]["sleep"]["summary"]["minutesAsleep"]
        nights.append((wake_date, {"dataPoints": data_points}))
        if offset == _GOOGLE_SLEEP_EXTRA_NAP_OFFSET:
            nights.append((wake_date, {"dataPoints": [_google_nap_data_point(wake_date, rng)]}))
    return nights


def _google_interval(wake_date: date, *, start_hour: int, end_hour: int) -> dict[str, Any]:
    return {
        "startTime": f"{(wake_date - timedelta(days=1)).isoformat()}T{start_hour:02d}:00:00Z",
        "startUtcOffset": "10800s",
        "endTime": f"{wake_date.isoformat()}T{end_hour:02d}:00:00Z",
        "endUtcOffset": "10800s",
        "civilStartTime": {
            "date": wake_date.isoformat(),
            "time": f"{(start_hour + 3) % 24:02d}:00:00",
            "zone": "Europe/Moscow",
        },
        "civilEndTime": {
            "date": wake_date.isoformat(),
            "time": f"{(end_hour + 3) % 24:02d}:00:00",
            "zone": "Europe/Moscow",
        },
    }


def _google_main_data_point(
    wake_date: date, duration: int, offset: int, rng: random.Random
) -> dict[str, Any]:
    asleep = duration // 60
    external_id = f"synthetic-demo-google-sleep-{wake_date.isoformat()}"
    return {
        "name": (
            "users/me/dataSourceFamilies/google-wearables/dataPoints/"
            f"synthetic-demo-sleep-{wake_date.isoformat()}"
        ),
        "sleep": {
            "interval": _google_interval(wake_date, start_hour=22, end_hour=6),
            "type": "STAGES",
            "stages": [],
            "outOfBedSegments": [],
            "metadata": {
                "main": True,
                "nap": False,
                "manuallyEdited": offset == _GOOGLE_SLEEP_MANUAL_EDIT_OFFSET,
                "externalId": external_id,
            },
            "summary": {
                "minutesInSleepPeriod": str(asleep + rng.randrange(5, 21)),
                "minutesAfterWakeUp": "0",
                "minutesToFallAsleep": str(rng.randrange(5, 21)),
                "minutesAsleep": str(asleep),
                "minutesAwake": str(rng.randrange(5, 26)),
                "stagesSummary": [],
            },
            "updateTime": f"{wake_date.isoformat()}T08:04:00Z",
        },
    }


def _google_nap_data_point(wake_date: date, rng: random.Random) -> dict[str, Any]:
    minutes = rng.randrange(25, 61)
    external_id = f"synthetic-demo-google-nap-{wake_date.isoformat()}"
    return {
        "name": (
            "users/me/dataSourceFamilies/google-wearables/dataPoints/"
            f"synthetic-demo-nap-{wake_date.isoformat()}"
        ),
        "sleep": {
            "interval": _google_interval(wake_date, start_hour=13, end_hour=14),
            "type": "STAGES",
            "stages": [],
            "outOfBedSegments": [],
            "metadata": {
                "main": False,
                "nap": True,
                "manuallyEdited": False,
                "externalId": external_id,
            },
            "summary": {
                "minutesInSleepPeriod": str(minutes),
                "minutesAfterWakeUp": "0",
                "minutesToFallAsleep": str(rng.randrange(3, 11)),
                "minutesAsleep": str(minutes),
                "minutesAwake": "0",
                "stagesSummary": [],
            },
            "updateTime": f"{wake_date.isoformat()}T15:04:00Z",
        },
    }


def _context_note_specs() -> list[_ContextNoteSpec]:
    return [
        _ContextNoteSpec(
            temporal=parse_date_only("2026-09-13"),
            text=(
                "Синтетическое демо: заметка без времени для проверки датированного контекста. "
                "Реальные данные не используются."
            ),
            tags=("synthetic-demo", "sleep"),
            operation_id="synthetic-demo-context-01",
        ),
        _ContextNoteSpec(
            temporal=parse_timestamp("2026-09-20T08:15:00+03:00"),
            text="Синтетическое демо: утренняя заметка с явным смещением времени.",
            tags=("synthetic-demo", "morning"),
            operation_id="synthetic-demo-context-02",
        ),
        _ContextNoteSpec(
            temporal=parse_interval("2026-09-27", "2026-09-29"),
            text="Синтетическое демо: интервал нескольких дней для проверки диапазона.",
            tags=("synthetic-demo", "interval"),
            operation_id="synthetic-demo-context-03",
        ),
        _ContextNoteSpec(
            temporal=parse_date_only("2026-10-04"),
            text=(
                "Синтетическое демо: заметка рядом с вымышленной теннисной сессией "
                "(это не медицинское наблюдение)."
            ),
            tags=("synthetic-demo", "tennis"),
            operation_id="synthetic-demo-context-04",
        ),
        _ContextNoteSpec(
            temporal=parse_timestamp("2026-10-08T21:40:00+03:00"),
            text="Синтетическое демо: вечерняя заметка для проверки сортировки по времени.",
            tags=("synthetic-demo", "evening"),
            operation_id="synthetic-demo-context-05",
        ),
        _ContextNoteSpec(
            temporal=parse_date_only(DEMO_ANCHOR_DATE.isoformat()),
            text=(
                "Синтетическое демо: последняя заметка окна; профиль помечен как синтетический."
            ),
            tags=("synthetic-demo", "anchor"),
            operation_id="synthetic-demo-context-06",
        ),
    ]


# ---------------------------------------------------------------------------
# Persistence through accepted application services
# ---------------------------------------------------------------------------


def _persist_garmin_sleep(
    session: Any, paths: RuntimePaths, nights: list[tuple[date, dict[str, Any]]]
) -> None:
    repository = GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    )
    identity = garmin_source_identity(
        device_attributed=True,
        device_code=DEMO_GARMIN_DEVICE_CODE,
        device_model=DEMO_GARMIN_DEVICE_MODEL,
    )
    for wake_date, payload in nights:
        normalized = normalize_garmin_payload(payload, stream="sleep", source_identity=identity)
        repository.persist_result(
            normalized,
            payload=payload,
            received_at=DEMO_RECEIVED_AT,
            source_filename=f"synthetic-demo/garmin-sleep-{wake_date.isoformat()}.json",
        )


def _persist_garmin_activities(
    session: Any, paths: RuntimePaths, sessions: list[dict[str, Any]]
) -> None:
    repository = GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    )
    identity = garmin_source_identity(
        device_attributed=True,
        device_code=DEMO_GARMIN_DEVICE_CODE,
        device_model=DEMO_GARMIN_DEVICE_MODEL,
    )
    payload = {"activities": sessions}
    normalized = normalize_garmin_payload(payload, stream="activity", source_identity=identity)
    repository.persist_result(
        normalized,
        payload=payload,
        received_at=DEMO_RECEIVED_AT,
        source_filename="synthetic-demo/garmin-activities.json",
    )


def _persist_google_sleep(
    session: Any, paths: RuntimePaths, nights: list[tuple[date, dict[str, Any]]]
) -> None:
    repository = GooglePersistenceRepository(
        session, payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    )
    identity = GoogleSourceIdentity(
        source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
        source_instance_id=DEMO_GOOGLE_FAMILY,
    )
    query = GoogleQueryContext(
        query_mode=GoogleQueryMode.LIST,
        data_source_family=DEMO_GOOGLE_FAMILY,
    )
    for wake_date, payload in nights:
        normalized = normalize_google_payload(
            payload, stream=GoogleStream.SLEEP, query=query, source_identity=identity
        )
        repository.persist_result(
            normalized,
            payload=payload,
            received_at=DEMO_RECEIVED_AT,
            source_filename=f"synthetic-demo/google-sleep-{wake_date.isoformat()}.json",
        )


def _seed_context_notes(session: Any, notes: list[_ContextNoteSpec]) -> None:
    service = ContextService(session)
    for note in notes:
        service.add(
            text=note.text,
            temporal=note.temporal,
            capture_source="cli",
            tags=note.tags,
            operation_id=note.operation_id,
        )


def _synthetic_uploads() -> tuple[list[PhotoUpload], int]:
    uploads: list[PhotoUpload] = []
    candidate_count = 0
    for filename, _image, payload in six_month_synthetic_batch():
        labelled_payload = dict(payload)
        labelled_payload["source_application"] = DEMO_SOURCE_APPLICATION
        image = encode_synthetic_png(labelled_payload)
        field_count = sum(len(group.get("fields") or []) for group in labelled_payload["groups"])
        candidate_count += field_count
        uploads.append(
            PhotoUpload(filename=filename, content=image, declared_media_type="image/png")
        )
    return uploads, candidate_count


# ---------------------------------------------------------------------------
# Marker, manifest validation and reset safety
# ---------------------------------------------------------------------------


def _marker_path(paths: RuntimePaths) -> Path:
    return paths.root / DEMO_MARKER_NAME


def _read_and_validate_marker(marker: Path) -> dict[str, Any]:
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DemoSeedError("demo marker is unreadable") from exc
    if not isinstance(value, dict) or value.get("seed_id") not in {
        DEMO_SEED_ID,
        *DEMO_LEGACY_SEED_IDS,
    }:
        raise DemoSeedError("demo marker is not owned by this synthetic seed")
    if value.get("format_version") == DEMO_LEGACY_FORMAT_VERSION:
        required = ("weigh_in_count", "candidate_count")
    elif value.get("format_version") == DEMO_MARKER_FORMAT_VERSION:
        required = (
            "weigh_in_count",
            "candidate_count",
            "garmin_sleep_count",
            "garmin_activity_count",
            "google_sleep_count",
            "context_count",
        )
    else:
        raise DemoSeedError("demo marker format is unsupported")
    for key in required:
        if not isinstance(value.get(key), int) or value[key] <= 0:
            raise DemoSeedError("demo marker is invalid")
    return value


def _require_current_demo_version(marker_data: dict[str, Any]) -> None:
    if (
        marker_data.get("seed_id") != DEMO_SEED_ID
        or marker_data.get("format_version") != DEMO_MARKER_FORMAT_VERSION
    ):
        raise DemoSeedError(
            "synthetic demo marker belongs to an older dataset version; "
            "re-run seed-demo with --reset to rebuild the marked synthetic demo"
        )


def _write_marker(
    paths: RuntimePaths,
    *,
    weigh_in_count: int,
    candidate_count: int,
    garmin_sleep_count: int,
    garmin_activity_count: int,
    google_sleep_count: int,
    context_count: int,
) -> None:
    marker = _marker_path(paths)
    temporary = marker.with_name(f"{marker.name}.tmp")
    payload = {
        "format_version": DEMO_MARKER_FORMAT_VERSION,
        "seed_id": DEMO_SEED_ID,
        "label": "synthetic demo data",
        "anchor_date": DEMO_ANCHOR_DATE.isoformat(),
        "random_seed": DEMO_RANDOM_SEED,
        "weigh_in_count": weigh_in_count,
        "candidate_count": candidate_count,
        "garmin_sleep_count": garmin_sleep_count,
        "garmin_activity_count": garmin_activity_count,
        "google_sleep_count": google_sleep_count,
        "context_count": context_count,
    }
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, marker)


def _reset_marked_demo(paths: RuntimePaths, marker: Path) -> None:
    """Preflight all reset targets, then remove only marked demo state."""

    plan = _preflight_marked_demo_reset(paths, marker)
    _mutate_marked_demo_reset(plan)


def _preflight_marked_demo_reset(paths: RuntimePaths, marker: Path) -> _DemoResetPlan:
    """Validate every reset target without modifying the runtime."""

    if not paths.root.is_dir() or _is_reparse_link(paths.root):
        raise DemoSeedError("demo target must be a real directory")
    if marker.parent != paths.root or _is_reparse_link(marker) or not marker.is_file():
        raise DemoSeedError("demo marker is not a regular file")
    _read_and_validate_marker(marker)

    database_paths = (
        paths.database,
        Path(f"{paths.database}-wal"),
        Path(f"{paths.database}-shm"),
    )
    if not paths.database.is_file() or _is_reparse_link(paths.database):
        raise DemoSeedError("demo database state is not a regular file")
    for database_path in database_paths[1:]:
        if _is_reparse_link(database_path) or (
            database_path.exists() and not database_path.is_file()
        ):
            raise DemoSeedError("demo database state is not a regular file")

    artifacts = paths.root / "artifacts"
    if _is_reparse_link(artifacts) or (artifacts.exists() and not artifacts.is_dir()):
        raise DemoSeedError("demo artifacts directory is not a regular directory")
    if artifacts.exists():
        _validate_artifact_tree(artifacts)
        artifacts_target: Path | None = artifacts
    else:
        artifacts_target = None
    return _DemoResetPlan(
        marker=marker,
        database_paths=database_paths,
        artifacts=artifacts_target,
    )


def _validate_artifact_tree(artifacts: Path) -> None:
    """Reject links and special entries before an artifact tree is removed."""

    try:
        children = artifacts.rglob("*")
        for child in children:
            if _is_reparse_link(child) or not (child.is_file() or child.is_dir()):
                raise DemoSeedError("demo artifacts tree contains an unsafe entry")
    except OSError as exc:
        raise DemoSeedError("demo artifacts tree could not be preflighted") from exc


def _mutate_marked_demo_reset(plan: _DemoResetPlan) -> None:
    """Execute a reset only from a completed, immutable preflight plan."""

    for database_path in plan.database_paths:
        if database_path.exists():
            database_path.unlink()
    if plan.artifacts is not None:
        shutil.rmtree(plan.artifacts)
    plan.marker.unlink()


def _validate_seeded_demo(paths: RuntimePaths, marker_data: dict[str, Any]) -> None:
    if not paths.database.is_file():
        raise DemoSeedError("marked synthetic demo database is missing")
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            garmin_sleep_count = int(marker_data["garmin_sleep_count"])
            garmin_activity_count = int(marker_data["garmin_activity_count"])
            google_sleep_count = int(marker_data["google_sleep_count"])
            expected = {
                IngestBatch: 1 + garmin_sleep_count + 1 + google_sleep_count,
                IngestEvent: (
                    int(marker_data["weigh_in_count"])
                    + garmin_sleep_count
                    + 1
                    + google_sleep_count
                ),
                ImportCandidate: int(marker_data["candidate_count"]),
                MeasurementSession: int(marker_data["weigh_in_count"]),
                ScalarMeasurement: int(marker_data["candidate_count"]),
                GarminSleepRecord: garmin_sleep_count,
                GarminActivityRecord: garmin_activity_count,
                GoogleSleepRecord: google_sleep_count,
                ContextEventHead: int(marker_data["context_count"]),
            }
            for model, count in expected.items():
                actual = session.scalar(select(func.count()).select_from(model))
                if actual != count:
                    raise DemoSeedError("marked synthetic demo does not match its seed manifest")
            source = session.scalar(
                select(AcquisitionSource).where(
                    AcquisitionSource.source_application == DEMO_SOURCE_APPLICATION
                )
            )
            if source is None or source.source_application != DEMO_SOURCE_APPLICATION:
                raise DemoSeedError("marked synthetic demo is not labelled as synthetic")
            garmin_source = session.scalar(
                select(GarminSource).where(GarminSource.provider_code == "garmin_connect")
            )
            if (
                garmin_source is None
                or garmin_source.source_kind != "synthetic"
                or not garmin_source.device_attributed
            ):
                raise DemoSeedError("marked synthetic demo has no labelled Garmin source")
            google_source = session.scalar(
                select(GoogleSource).where(GoogleSource.provider_code == "google_health")
            )
            if google_source is None or google_source.source_kind != "family_aggregate":
                raise DemoSeedError("marked synthetic demo has no labelled Google source")
            latest_garmin = session.scalar(select(func.max(GarminSleepRecord.wake_date)))
            latest_google = session.scalar(select(func.max(GoogleSleepRecord.wake_date)))
            anchor = DEMO_ANCHOR_DATE.isoformat()
            if _iso_date(latest_garmin) != anchor or _iso_date(latest_google) != anchor:
                raise DemoSeedError(
                    "marked synthetic demo is not anchored to the fixed demo date"
                )
            notes = ContextService(session).list(limit=100)
            if len(notes) != int(marker_data["context_count"]) or not all(
                note.original_text.startswith("Синтетическое демо") for note in notes
            ):
                raise DemoSeedError("marked synthetic demo context notes are missing or unlabelled")
            payload = WeightQueryService(session, Settings(data_dir=paths.root)).dashboard()
            if len(payload["series"]["raw_points"]) != marker_data["weigh_in_count"]:
                raise DemoSeedError("marked synthetic demo has an unexpected weight series")
            if not payload["series"]["trend_points"]:
                raise DemoSeedError("marked synthetic demo has no trend data")
            if not payload["summary"]["latest_composition"]["available"]:
                raise DemoSeedError("marked synthetic demo has no composition summary")
            if not payload["series"]["composition_by_group"]:
                raise DemoSeedError("marked synthetic demo has no composition series")
            if payload["summary"]["coverage"] is None:
                raise DemoSeedError("marked synthetic demo has no coverage summary")
    finally:
        engine.dispose()


def _iso_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)
