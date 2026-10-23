"""Bounded weekly saved-evidence adapter and deterministic Russian preview (#488)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from healthcheck.chat_evidence import MAX_OUTPUT_BYTES, EvidenceError, _json
from healthcheck.combined_evidence import CombinedEvidenceRequest, read_combined_evidence
from healthcheck.web.owner_presentation import (
    owner_activity_count,
    owner_activity_type,
    owner_date,
    owner_distance,
    owner_duration,
)

VERSION = "health-weekly-digest-v1"
MOSCOW = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class WeeklyDigestConfig:
    """Trusted operator choices, never remote arguments or inferred sources."""

    activity_garmin_source_id: str
    sleep_garmin_source_id: str | None = None
    sleep_google_source_id: str | None = None
    steps_garmin_source_id: str | None = None
    steps_google_source_id: str | None = None
    steps_view: str = "observed"

    def request(self, week_end: date) -> CombinedEvidenceRequest:
        request = CombinedEvidenceRequest(
            end_date=week_end, days=7, include_context=False, projection="compact",
            activity_garmin_source_id=self.activity_garmin_source_id,
            sleep_garmin_source_id=self.sleep_garmin_source_id,
            sleep_google_source_id=self.sleep_google_source_id,
            steps_garmin_source_id=self.steps_garmin_source_id,
            steps_google_source_id=self.steps_google_source_id,
            steps_view=self.steps_view,
        )
        request.validate()
        return request


def get_weekly_digest_evidence(
    *, profile: Path, profile_kind: str, config: WeeklyDigestConfig,
    week_end: date, evaluated_at_utc: datetime,
) -> dict:
    """One saved snapshot at the ACTUAL read clock; no Sunday time travel."""
    if type(week_end) is not date or week_end.weekday() != 6:
        raise EvidenceError("weekly_end_must_be_sunday")
    if (not isinstance(evaluated_at_utc, datetime) or evaluated_at_utc.tzinfo is None
            or evaluated_at_utc.utcoffset() is None):
        raise EvidenceError("aware_evaluation_clock_required")
    local = evaluated_at_utc.astimezone(MOSCOW)
    if week_end > local.date():
        raise EvidenceError("future_week_not_available")
    evidence = read_combined_evidence(
        profile=profile, profile_kind=profile_kind, request=config.request(week_end),
        evaluated_at_utc=evaluated_at_utc, evaluation_local_date=local.date())
    target = datetime.combine(week_end, time(20), MOSCOW)
    packet = {
        "version": VERSION,
        "period": {
            "start_date": (week_end - timedelta(days=6)).isoformat(),
            "end_date": week_end.isoformat(), "calendar_days": 7,
            "scheduled_for": target.isoformat(),
            "as_of": local.isoformat(),
            "sunday_incomplete": week_end == local.date(),
            "late_read": local > target,
            "date_basis": "activity_source_local_sleep_wake_date_steps_saved_civil_date",
        },
        "generated_at_utc": evidence["generated_at_utc"],
        "collection_freshness": {"state": "unknown", "latest_success": None,
                                 "reason": "saved_evidence_does_not_prove_refresh"},
        "comparison": {"state": "not_performed", "reason": "no_compatible_previous_window"},
        "delivery": {"state": "preview_only", "schedule_enabled": False,
                     "transport": "not_connected", "retry": "reuse_frozen_packet",
                     "new_read": "requires_explicit_revision"},
        "evidence": evidence,
    }
    packet["text"] = render_weekly_digest(packet)
    packet["digest_hash"] = hashlib.sha256(_json(packet).encode("utf-8")).hexdigest()
    encode_weekly_digest(packet)
    return packet


def encode_weekly_digest(packet: dict) -> str:
    encoded = _json(packet)
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise EvidenceError("output_exceeds_byte_limit")
    return encoded


def _activity(section):
    cells = section["providers"]["garmin"]["metrics"]
    count = cells["activity_session_count"]
    value = count["aggregation"]["value"]
    if value is None or not count["search"]["complete"]:
        return "Занятия Garmin: надёжного количества записей за период нет."
    if value == 0:
        # Zero is a statement about accepted saved evidence, never all real activity.
        text = "Занятия Garmin: в сохранённых данных подтверждённых занятий нет."
    else:
        text = f"Занятия Garmin: подтверждено {owner_activity_count(value)}."
        types = cells["activity_type_counts"]
        if types["search"]["complete"] and types["aggregation"]["value"]:
            text += " Виды: " + "; ".join(
                f"{owner_activity_type(code).lower()} — {number}"
                for code, number in sorted(types["aggregation"]["value"].items())) + "."
        for code, label, formatter in (
            ("tennis_duration_seconds", "Теннис", owner_duration),
            ("cycling_distance_meters", "Велосипед", owner_distance),
        ):
            cell = cells[code]
            number = cell["aggregation"]["value"]
            if number is not None and cell["search"]["complete"]:
                text += f" {label}: {formatter(number)} по пригодным записям."
    text += f" Даты с записями: {count['observed_day_count']} из 7."
    if count["coverage"].get("observed_on_confirmed_empty_dates"):
        text += " Есть конфликт отметок покрытия с сохранёнными занятиями."
    text += " Это не подтверждает полноту реальной активности."
    return text


def _steps(section, label):
    if section is None:
        return f"Шаги {label}: источник для сводки не выбран."
    cells = section["cells"]
    usable = [cell for cell in cells if cell["state"] in {"value", "zero"}
              and cell["value"] is not None]
    if not usable:
        return f"Шаги {label}: пригодных наблюдений нет; это не нулевые шаги."
    latest = max(usable, key=lambda cell: str(cell["calendar_date"]))
    number = format(latest["value"], ",").replace(",", "\u202f")
    text = (f"Шаги {label}: наблюдения за {len(usable)} из {len(cells)} дат; "
            f"последнее — {owner_date(latest['calendar_date'])}: "
            f"{number} шагов.")
    if section.get("excluded_uncompleted_day_count"):
        text += " Незавершённые даты исключены."
    if section.get("aggregate") is None:
        text += " Недельные сумма и среднее не рассчитаны."
    if section.get("finality") == "unknown" or "not_completed" in section["meaning"]:
        text += " Завершённость суток и полнота сбора не подтверждены."
    return text


def _sleep(section):
    lines = []
    for provider, item in section["providers"].items():
        label = "Garmin" if provider == "garmin" else "Google"
        window = item["source_range"]
        nights = []
        if window:
            for series in window["series"]:
                for point in series["points"]:
                    if (point["state"] == "value" and point["value"] is not None
                            and not point["role_uncertain"]):
                        nights.append((str(point["wake_date"]), point["value"]))
        if nights:
            last = max(nights, key=lambda point: point[0])
            lines.append(f"Сон {label}: пригодная длительность за {len(nights)} из 7 ночей "
                         f"по дате пробуждения; последняя — {owner_date(last[0])}, "
                         f"{owner_duration(last[1])}.")
        else:
            lines.append(f"Сон {label}: пригодной длительности основного сна нет. "
                         "Пропуски и исключённые записи не равны отсутствию сна.")
    lines.append("Дневной сон и записи с неопределённой ролью не добавляются к основному.")
    return " ".join(lines)


def render_weekly_digest(packet: dict) -> str:
    """Format frozen accepted values only; no store access, totals or comparisons."""
    period = packet["period"]
    sections = packet["evidence"]["sections"]
    as_of = datetime.fromisoformat(period["as_of"])
    paragraphs = [
        f"Итог недели: {owner_date(period['start_date'])} — {owner_date(period['end_date'])}. "
        f"По состоянию на {owner_date(as_of.date())}, {as_of:%H:%M} (Москва).",
    ]
    if period["sunday_incomplete"]:
        paragraphs[0] += " Воскресенье ещё не завершено: итог предварительный."
    if period["late_read"]:
        paragraphs[0] += " Позднее чтение: это фактический срез, а не восстановление на 20:00."
    paragraphs.extend([
        _activity(sections["activity"]),
        _steps(sections.get("steps"), "Garmin") + " "
        + _steps(sections.get("google_steps"), "Google"),
        _sleep(sections["sleep"]),
        "Garmin и Google показаны отдельно. Свежесть обновления неизвестна: сохранённая "
        "история не доказывает успешный сбор. Сравнение с прошлой неделей не выполнялось. "
        "Это preview; автоматическая отправка не включена.",
    ])
    return "\n\n".join(paragraphs)
